import logging
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ChatAction

from app.bot.streaming.buffer import StreamBuffer
from app.bot.streaming.telegram_draft import TelegramDraftNotAvailable, TelegramPrivateDraftSink
from app.bot.streaming.telegram_fallback import TelegramGroupEditSink
from app.bot.streaming.text_limits import split_telegram_text
from app.core.config import get_settings
from app.db.models import MessageRole, utcnow
from app.db.repositories.daily_brief import DailyBriefSettingsRepository
from app.db.repositories.household_memory import HouseholdMemoryRepository
from app.db.repositories.messages import MessageRepository
from app.db.repositories.reminders import ReminderRepository
from app.db.repositories.runtime_settings import RuntimeSettingRepository
from app.db.repositories.shopping import ShoppingRepository
from app.db.repositories.web_search_cache import WebSearchCacheRepository
from app.db.session import SessionLocal
from app.llm.base import LLMProviderError
from app.llm.factory import build_llm_provider
from app.services.daily_brief_service import DailyBriefService
from app.services.household_memory_service import HouseholdMemoryService
from app.services.memory_service import MemoryService
from app.services.reminder_service import ReminderService, ReminderView
from app.services.runtime_settings_service import (
    DEFAULT_PROMPTS,
    ActiveLLMProvider,
    PromptProfileScope,
    RuntimeSettingsService,
    RuntimeSettingsUnavailable,
)
from app.services.shopping_service import ShoppingService
from app.services.status_service import record_worker_heartbeat
from app.services.telegram_formatting import format_daily_brief_html, format_reminder_due_html
from app.services.web_search.context_builder import (
    build_search_context,
    build_search_system_prompt,
    build_sources_text,
)
from app.services.web_search.factory import build_web_search_service
from app.services.web_search.service import WEB_SEARCH_NO_RESULTS_MESSAGE
from app.services.web_search.types import WebSearchRequest, WebSearchStatus

logger = logging.getLogger(__name__)
USER_ERROR_MESSAGE = "Не получилось подготовить ответ. Попробуйте позже."
DAILY_BRIEF_SEND_CLAIM_TTL_SECONDS = 36 * 60 * 60


def _mask_int(value: int | str | None) -> str:
    if value is None:
        return "missing"
    text = str(value)
    prefix = "-" if text.startswith("-") else ""
    digits = text[1:] if prefix else text
    tail = digits[-4:] if len(digits) > 4 else digits
    return f"{prefix}***{tail}"


async def try_send_chat_action(bot: Bot, *, chat_id: int) -> None:
    try:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception as exc:
        logger.warning(
            "telegram_chat_action_failed",
            extra={"error_type": type(exc).__name__},
        )


async def send_final_messages(bot: Bot, *, chat_id: int, text: str, path: str) -> None:
    chunks = split_telegram_text(text)
    for index, chunk in enumerate(chunks, start=1):
        await bot.send_message(chat_id=chat_id, text=chunk)
        logger.warning(
            "telegram_final_send_message_called",
            extra={
                "path": path,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "text_length": len(chunk),
                "source_text_length": len(text),
            },
        )


async def _stream_response(provider: Any, messages: list[Any]) -> tuple[str, bool]:
    final_text = ""
    try:
        async for chunk in provider.stream(messages):
            final_text += chunk.content
    except LLMProviderError as exc:
        logger.warning("llm_stream_error_falling_back_to_complete", extra={"error_code": exc.code})
        response = await provider.complete(messages)
        return str(response.content), False
    except Exception as exc:
        logger.warning(
            "llm_stream_failed_falling_back_to_complete",
            extra={"error_type": type(exc).__name__},
        )
        response = await provider.complete(messages)
        return str(response.content), False
    if not final_text:
        response = await provider.complete(messages)
        return str(response.content), False
    return final_text, True


async def _process_private_streaming(
    *,
    bot: Bot,
    provider: Any,
    messages: list[Any],
    chat_id: int,
    settings: Any,
) -> str:
    buffer = StreamBuffer(
        update_interval_ms=settings.streaming_draft_update_interval_ms,
        min_chars_delta=settings.streaming_min_chars_delta,
        max_draft_seconds=settings.streaming_max_draft_seconds,
    )
    draft = TelegramPrivateDraftSink(
        bot,
        raw_api_fallback=settings.streaming_draft_raw_api_fallback,
        rich_thinking_enabled=settings.telegram_private_draft_streaming_enabled,
    )
    logger.warning(
        "streaming_private_draft_selected",
        extra={
            "draft_id": draft.draft_id,
            "draft_update_interval_ms": settings.streaming_draft_update_interval_ms,
            "min_chars_delta": settings.streaming_min_chars_delta,
            "mira_style_enabled": settings.telegram_private_draft_streaming_enabled,
        },
    )
    fallback: TelegramGroupEditSink | None = None
    draft_available = True
    try:
        await draft.start(chat_id=chat_id)
    except TelegramDraftNotAvailable:
        draft_available = False
        logger.warning("streaming_private_draft_unavailable_using_fallback")
        fallback = TelegramGroupEditSink(
            bot,
            edit_interval_ms=settings.streaming_group_edit_interval_ms,
            chat_action_interval_seconds=settings.streaming_send_chat_action_interval_seconds,
        )
        await fallback.start(chat_id=chat_id, now=time.monotonic())
    final_text = ""
    try:
        async for chunk in provider.stream(messages):
            if not chunk.content:
                continue
            now = time.monotonic()
            final_text += chunk.content
            buffer.append(chunk.content, now=now)
            decision = buffer.should_flush(now=now)
            if decision is None:
                continue
            if draft_available:
                try:
                    await draft.publish(chat_id=chat_id, text=decision.text)
                except TelegramDraftNotAvailable:
                    draft_available = False
                    logger.warning(
                        "streaming_private_draft_failed_using_fallback",
                        extra={"flush_reason": decision.reason.value},
                    )
                    fallback = TelegramGroupEditSink(
                        bot,
                        edit_interval_ms=settings.streaming_group_edit_interval_ms,
                        chat_action_interval_seconds=settings.streaming_send_chat_action_interval_seconds,
                    )
                    await fallback.start(chat_id=chat_id, now=now)
                    await fallback.publish(chat_id=chat_id, text=decision.text, now=now)
            else:
                if fallback is None:
                    fallback = TelegramGroupEditSink(
                        bot,
                        edit_interval_ms=settings.streaming_group_edit_interval_ms,
                        chat_action_interval_seconds=settings.streaming_send_chat_action_interval_seconds,
                    )
                    await fallback.start(chat_id=chat_id, now=now)
                await fallback.publish(chat_id=chat_id, text=decision.text, now=now)
            buffer.mark_flushed(now=now)
    except LLMProviderError as exc:
        logger.warning("llm_stream_error_falling_back_to_complete", extra={"error_code": exc.code})
        response = await provider.complete(messages)
        return str(response.content)
    except Exception as exc:
        logger.warning(
            "llm_stream_failed_falling_back_to_complete",
            extra={"error_type": type(exc).__name__},
        )
        response = await provider.complete(messages)
        return str(response.content)
    if not final_text:
        response = await provider.complete(messages)
        return str(response.content)
    decision = buffer.final_flush(now=time.monotonic())
    if decision.delta_length > 0 and not draft_available and fallback is not None:
        await fallback.publish(chat_id=chat_id, text=decision.text, now=time.monotonic())
    return final_text


async def _process_group_streaming(
    *,
    bot: Bot,
    provider: Any,
    messages: list[Any],
    chat_id: int,
    settings: Any,
) -> str:
    buffer = StreamBuffer(
        update_interval_ms=settings.streaming_group_edit_interval_ms,
        min_chars_delta=settings.streaming_min_chars_delta,
        max_draft_seconds=settings.streaming_max_draft_seconds,
    )
    sink = TelegramGroupEditSink(
        bot,
        edit_interval_ms=settings.streaming_group_edit_interval_ms,
        chat_action_interval_seconds=settings.streaming_send_chat_action_interval_seconds,
    )
    logger.warning(
        "streaming_group_fallback_selected",
        extra={
            "group_edit_interval_ms": settings.streaming_group_edit_interval_ms,
            "min_chars_delta": settings.streaming_min_chars_delta,
        },
    )
    await sink.start(chat_id=chat_id, now=time.monotonic())
    final_text = ""
    try:
        async for chunk in provider.stream(messages):
            if not chunk.content:
                continue
            now = time.monotonic()
            final_text += chunk.content
            buffer.append(chunk.content, now=now)
            decision = buffer.should_flush(now=now)
            if decision is None:
                continue
            await sink.publish(chat_id=chat_id, text=decision.text, now=now)
            buffer.mark_flushed(now=now)
    except LLMProviderError as exc:
        logger.warning("llm_stream_error_falling_back_to_complete", extra={"error_code": exc.code})
        response = await provider.complete(messages)
        await sink.final(chat_id=chat_id, text=response.content)
        return str(response.content)
    except Exception as exc:
        logger.warning(
            "llm_stream_failed_falling_back_to_complete",
            extra={"error_type": type(exc).__name__},
        )
        response = await provider.complete(messages)
        await sink.final(chat_id=chat_id, text=response.content)
        return str(response.content)
    if not final_text:
        response = await provider.complete(messages)
        await sink.final(chat_id=chat_id, text=response.content)
        return str(response.content)
    await sink.final(chat_id=chat_id, text=final_text)
    return final_text


async def process_llm_message(ctx: dict[str, Any], payload: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)
    chat_id = int(payload["chat_id"])
    is_private = bool(payload.get("private"))
    async with SessionLocal() as session:
        redis = ctx.get("redis") if isinstance(ctx, dict) else None
        await record_worker_heartbeat(redis)
        memory = MemoryService(
            MessageRepository(session),
            max_messages=settings.memory_max_messages,
        )
        household_memory = HouseholdMemoryService(HouseholdMemoryRepository(session))
        runtime_settings = RuntimeSettingsService(RuntimeSettingRepository(session))
        try:
            active_provider = await runtime_settings.get_active_llm_provider()
        except RuntimeSettingsUnavailable:
            logger.warning("runtime_settings_unavailable_using_auto_provider")
            active_provider = ActiveLLMProvider.AUTO
        profile_scope = PromptProfileScope.PRIVATE if is_private else PromptProfileScope.GROUP
        try:
            prompt_setting = await runtime_settings.get_prompt(profile_scope)
        except RuntimeSettingsUnavailable:
            logger.warning("runtime_settings_unavailable_using_default_prompt")
            prompt_text = DEFAULT_PROMPTS[profile_scope]
        else:
            prompt_text = prompt_setting.text
        web_search_sources_text: str | None = None
        web_search_payload = payload.get("web_search")
        if isinstance(web_search_payload, dict):
            query = str(web_search_payload.get("query") or "").strip()
            try:
                web_settings = await runtime_settings.get_web_search_settings(
                    default_provider=settings.web_search_provider,
                    default_max_results=settings.web_search_max_results,
                )
            except RuntimeSettingsUnavailable:
                logger.warning("runtime_settings_unavailable_using_disabled_web_search")
                web_settings = None
            if web_settings is None:
                final_text = "Интернет-поиск выключен. Включите его в /settings -> Интернет-поиск."
                await send_final_messages(bot, chat_id=chat_id, text=final_text, path="web_search")
                await memory.add_message(
                    chat_id=chat_id,
                    user_id=None,
                    role=MessageRole.ASSISTANT,
                    text=final_text,
                )
                await bot.session.close()
                return
            service = build_web_search_service(
                settings,
                provider_name=web_settings.provider.value,
                cache_repository=WebSearchCacheRepository(session),
            )
            search_response = await service.search(
                WebSearchRequest(
                    query=query,
                    provider_name=web_settings.provider.value,
                    enabled=web_settings.enabled,
                    max_results=web_settings.max_results,
                )
            )
            logger.info(
                "web_search_completed",
                extra={
                    "user_id_masked": _mask_int(payload.get("user_id")),
                    "provider": web_settings.provider.value,
                    "query_length": len(query),
                    "result_count": len(search_response.results),
                    "status": search_response.status.value,
                    "from_cache": search_response.from_cache,
                },
            )
            if search_response.status is not WebSearchStatus.OK:
                final_text = search_response.user_message or WEB_SEARCH_NO_RESULTS_MESSAGE
                await send_final_messages(bot, chat_id=chat_id, text=final_text, path="web_search")
                await memory.add_message(
                    chat_id=chat_id,
                    user_id=None,
                    role=MessageRole.ASSISTANT,
                    text=final_text,
                )
                await bot.session.close()
                return
            search_context = build_search_context(search_response.results)
            web_search_sources_text = build_sources_text(search_response.results)
            prompt_text = build_search_system_prompt(prompt_text, search_context)
        messages = await memory.build_context(
            chat_id=chat_id,
            system_prompt=prompt_text,
            household_memory=household_memory,
            household_scope_type="private" if is_private else "group",
        )
        provider = build_llm_provider(settings, active_provider=active_provider)
        final_text = ""
        sent_final = False
        try:
            if payload.get("guest"):
                response = await provider.complete(messages)
                final_text = response.content
            elif web_search_sources_text is not None:
                response = await provider.complete(messages)
                final_text = _with_web_search_sources(response.content, web_search_sources_text)
                await send_final_messages(
                    bot,
                    chat_id=chat_id,
                    text=final_text,
                    path="web_search",
                )
                sent_final = True
            elif (
                settings.streaming_enabled
                and is_private
                and settings.streaming_private_draft_enabled
            ):
                final_text = await _process_private_streaming(
                    bot=bot,
                    provider=provider,
                    messages=messages,
                    chat_id=chat_id,
                    settings=settings,
                )
                await send_final_messages(
                    bot,
                    chat_id=chat_id,
                    text=final_text,
                    path="private_streaming",
                )
                sent_final = True
            elif (
                settings.streaming_enabled
                and not is_private
                and settings.streaming_group_fallback_enabled
            ):
                final_text = await _process_group_streaming(
                    bot=bot,
                    provider=provider,
                    messages=messages,
                    chat_id=chat_id,
                    settings=settings,
                )
            elif not is_private:
                await try_send_chat_action(bot, chat_id=chat_id)
                response = await provider.complete(messages)
                final_text = response.content
            else:
                final_text, _ = await _stream_response(provider, messages)
                await send_final_messages(
                    bot,
                    chat_id=chat_id,
                    text=final_text,
                    path="private_final",
                )
                sent_final = True
        except LLMProviderError as exc:
            logger.warning("llm_failed", extra={"error_code": exc.code})
            final_text = USER_ERROR_MESSAGE
            await send_final_messages(bot, chat_id=chat_id, text=final_text, path="error")
            sent_final = True
        if not sent_final and (
            payload.get("guest")
            or (not is_private and not settings.streaming_group_fallback_enabled)
        ):
            await send_final_messages(bot, chat_id=chat_id, text=final_text, path="final_only")
        await memory.add_message(
            chat_id=chat_id,
            user_id=None,
            role=MessageRole.ASSISTANT,
            text=final_text,
        )
    await bot.session.close()


def _with_web_search_sources(answer: str, sources_text: str) -> str:
    clean_answer = answer.strip()
    if clean_answer:
        return f"Нашёл актуальные источники.\n\n{clean_answer}\n\n{sources_text}"
    return f"Нашёл актуальные источники.\n\n{sources_text}"


async def deliver_due_reminders(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)
    logger.info("reminder_due_delivery_started")
    try:
        await record_worker_heartbeat(ctx.get("redis") if isinstance(ctx, dict) else None)
        async with SessionLocal() as session:
            repository = ReminderRepository(session)
            service = ReminderService(repository)
            for _ in range(50):
                now = utcnow()
                reminders = await repository.due(now, limit=1)
                if not reminders:
                    break
                reminder = reminders[0]
                if not await _deliver_one_reminder(bot, service, session, reminder, now=now):
                    break
    finally:
        await bot.session.close()


async def deliver_daily_briefs(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)
    try:
        async with SessionLocal() as session:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
            await record_worker_heartbeat(redis)
            repository = DailyBriefSettingsRepository(session)
            now = utcnow()
            due_settings = await repository.due_for_delivery(now)
            for brief_settings in due_settings:
                timezone = ZoneInfo(brief_settings.timezone)
                local_date = now.astimezone(timezone).date()
                if not await _claim_daily_brief_send(
                    redis,
                    settings_id=brief_settings.id,
                    local_date=local_date,
                ):
                    continue
                service = DailyBriefService(
                    shopping=ShoppingService(ShoppingRepository(session)),
                    reminders=ReminderService(ReminderRepository(session)),
                    household_memory=HouseholdMemoryService(HouseholdMemoryRepository(session)),
                )
                brief = await service.build_brief(
                    scope_type=brief_settings.scope_type,
                    chat_id=brief_settings.chat_id,
                    user_id=brief_settings.user_id,
                    now=now,
                    timezone=timezone,
                )
                try:
                    await bot.send_message(
                        chat_id=brief_settings.chat_id,
                        text=format_daily_brief_html(brief),
                        parse_mode="HTML",
                    )
                except Exception as exc:
                    logger.warning(
                        "daily_brief_send_failed",
                        extra={"error_type": type(exc).__name__},
                    )
                    await _release_daily_brief_send_claim(
                        redis,
                        settings_id=brief_settings.id,
                        local_date=local_date,
                    )
                    continue
                await repository.mark_sent_if_due(
                    brief_settings.id,
                    local_date,
                )
    finally:
        await bot.session.close()


async def _claim_daily_brief_send(
    redis: Any,
    *,
    settings_id: str,
    local_date: date,
) -> bool:
    if redis is None:
        return True
    key = _daily_brief_send_claim_key(settings_id=settings_id, local_date=local_date)
    try:
        claimed = await redis.set(
            key,
            "1",
            ex=DAILY_BRIEF_SEND_CLAIM_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:
        logger.warning(
            "daily_brief_send_claim_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return True
    if not claimed:
        logger.info("daily_brief_duplicate_send_skipped")
        return False
    return True


async def _release_daily_brief_send_claim(
    redis: Any,
    *,
    settings_id: str,
    local_date: date,
) -> None:
    if redis is None:
        return
    key = _daily_brief_send_claim_key(settings_id=settings_id, local_date=local_date)
    try:
        await redis.delete(key)
    except Exception as exc:
        logger.warning(
            "daily_brief_send_claim_release_failed",
            extra={"error_type": type(exc).__name__},
        )


def _daily_brief_send_claim_key(*, settings_id: str, local_date: date) -> str:
    return f"daily_brief:send:{settings_id}:{local_date.isoformat()}"


async def _deliver_one_reminder(
    bot: Bot,
    service: ReminderService,
    session: Any,
    reminder: Any,
    *,
    now: datetime,
) -> bool:
    try:
        timezone = await RuntimeSettingsService(
            RuntimeSettingRepository(session)
        ).get_lists_timezone()
        await bot.send_message(
            chat_id=reminder.chat_id,
            text=format_reminder_due_html(
                ReminderView(
                    id=reminder.id,
                    scope_type=reminder.scope_type,
                    chat_id=reminder.chat_id,
                    user_id=reminder.user_id,
                    text=reminder.text,
                    remind_at=reminder.remind_at,
                    status=reminder.status,
                ),
                now=now,
                timezone=timezone,
            ),
            parse_mode="HTML",
        )
        await service.mark_sent(reminder.id)
        logger.info(
            "reminder_due_delivery_sent",
            extra={"scope_type": reminder.scope_type},
        )
        return True
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "reminder_due_delivery_failed",
            extra={"error_type": type(exc).__name__},
        )
        return False
