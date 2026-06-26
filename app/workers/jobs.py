import logging
import time
from typing import Any

from aiogram import Bot
from aiogram.enums import ChatAction

from app.bot.streaming.buffer import StreamBuffer
from app.bot.streaming.telegram_draft import TelegramDraftNotAvailable, TelegramPrivateDraftSink
from app.bot.streaming.telegram_fallback import TelegramGroupEditSink
from app.bot.streaming.text_limits import split_telegram_text
from app.core.config import get_settings
from app.db.models import MessageRole
from app.db.repositories.messages import MessageRepository
from app.db.repositories.runtime_settings import RuntimeSettingRepository
from app.db.session import SessionLocal
from app.llm.base import LLMProviderError
from app.llm.factory import build_llm_provider
from app.services.memory_service import MemoryService
from app.services.runtime_settings_service import (
    DEFAULT_PROMPTS,
    ActiveLLMProvider,
    PromptProfileScope,
    RuntimeSettingsService,
    RuntimeSettingsUnavailable,
)

logger = logging.getLogger(__name__)
USER_ERROR_MESSAGE = "Не получилось подготовить ответ. Попробуйте позже."


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
    del ctx
    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)
    chat_id = int(payload["chat_id"])
    is_private = bool(payload.get("private"))
    async with SessionLocal() as session:
        memory = MemoryService(
            MessageRepository(session),
            max_messages=settings.memory_max_messages,
        )
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
        messages = await memory.build_context(
            chat_id=chat_id,
            system_prompt=prompt_text,
        )
        provider = build_llm_provider(settings, active_provider=active_provider)
        final_text = ""
        sent_final = False
        try:
            if payload.get("guest"):
                response = await provider.complete(messages)
                final_text = response.content
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
