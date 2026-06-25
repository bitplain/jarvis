from typing import Any, cast

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.middlewares.access import is_admin_user
from app.db.models import BusinessConnection, BusinessConnectionStatus
from app.db.repositories.messages import MessageRepository
from app.db.repositories.runtime_settings import RuntimeSettingRepository
from app.llm.base import LLMProviderError
from app.llm.factory import build_llm_provider
from app.llm.types import LLMMessage
from app.services.memory_service import MemoryService
from app.services.runtime_settings_service import (
    ActiveLLMProvider,
    RuntimeSettingsService,
    RuntimeSettingsUnavailable,
)

SETTINGS_CALLBACK_REFRESH = "settings:refresh"
SETTINGS_CALLBACK_CLOSE = "settings:close"
SETTINGS_PROVIDER_PREFIX = "settings:provider:"
SETTINGS_PROVIDER_AUTO = "settings:provider:auto"
SETTINGS_PROVIDER_YANDEX = "settings:provider:yandex"
SETTINGS_PROVIDER_OPENROUTER = "settings:provider:openrouter"
PROVIDER_LABELS = {
    ActiveLLMProvider.AUTO: "Auto",
    ActiveLLMProvider.YANDEX: "Yandex",
    ActiveLLMProvider.OPENROUTER: "OpenRouter",
}
SETTINGS_UNAVAILABLE_MESSAGE = (
    "Настройки временно недоступны: миграция БД ещё не применена."
)


def _command_argument(message: Message) -> str | None:
    text = message.text or message.caption
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[0].startswith("/"):
        return None
    argument = parts[1].strip()
    return argument or None


def _command_target_username(message: Message) -> str | None:
    text = getattr(message, "text", None) or getattr(message, "caption", None)
    if not text:
        return None
    command = text.strip().split(maxsplit=1)[0]
    if "@" not in command:
        return None
    return str(command.rsplit("@", maxsplit=1)[1]).lower()


def _is_command_for_other_bot(message: Message, bot_username: str) -> bool:
    target = _command_target_username(message)
    if target is None or not bot_username:
        return False
    return target != bot_username.strip().lstrip("@").lower()


async def _resolve_bot_username(data: dict[str, Any], fallback: str) -> str:
    bot = data.get("bot")
    if bot is not None:
        try:
            me = await bot.get_me()
        except Exception:
            pass
        else:
            username = getattr(me, "username", None)
            if username:
                return str(username)
    return fallback


async def cmd_start(message: Message) -> None:
    await message.answer(
        "Jarvis готов. Пишите вопрос на русском языке.",
        reply_markup=build_settings_button(),
    )


async def cmd_help(message: Message) -> None:
    await message.answer(
        "/reset — очистить память\n"
        "/models — модели\n"
        "/status — статус\n"
        "/settings — настройки\n"
        "/summary — кратко пересказать последний переданный контекст\n"
        "/draft_reply — подготовить ответ\n"
        "/translate — перевести нормально\n"
        "/factcheck — проверить факты"
    )


def build_settings_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Настройки", callback_data=SETTINGS_CALLBACK_REFRESH)]
        ]
    )


def build_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Auto",
                    callback_data=SETTINGS_PROVIDER_AUTO,
                ),
                InlineKeyboardButton(
                    text="Yandex",
                    callback_data=SETTINGS_PROVIDER_YANDEX,
                ),
                InlineKeyboardButton(
                    text="OpenRouter",
                    callback_data=SETTINGS_PROVIDER_OPENROUTER,
                ),
            ],
            [
                InlineKeyboardButton(text="Обновить", callback_data=SETTINGS_CALLBACK_REFRESH),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def render_settings_text(provider: ActiveLLMProvider, *, saved: bool = False) -> str:
    title = "Настройки сохранены." if saved else "Настройки Jarvis"
    return (
        f"{title}\n\n"
        f"Активный агент: {PROVIDER_LABELS[provider]}\n\n"
        "Выберите LLM-провайдера:\n"
        "[Auto] [Yandex] [OpenRouter]\n\n"
        "Текущий режим применится к следующим сообщениям."
    )


def _message_user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None


def _callback_user_id(callback: CallbackQuery) -> int | None:
    return callback.from_user.id if callback.from_user else None


def _runtime_settings_service(session: object) -> RuntimeSettingsService:
    return RuntimeSettingsService(RuntimeSettingRepository(session))  # type: ignore[arg-type]


async def cmd_settings(message: Message, **data: Any) -> None:
    settings = data["settings"]
    if not is_admin_user(_message_user_id(message), settings.admin_ids):
        await message.answer("Доступ запрещён.")
        return
    session = data.get("db_session")
    if session is None:
        await message.answer("Настройки доступны только в runtime с БД.")
        return
    try:
        provider = await _runtime_settings_service(session).get_active_llm_provider()
    except RuntimeSettingsUnavailable:
        await message.answer(
            f"{SETTINGS_UNAVAILABLE_MESSAGE}\n"
            "Railway должен автоматически выполнить `alembic upgrade head` перед стартом API."
        )
        return
    await message.answer(render_settings_text(provider), reply_markup=build_settings_keyboard())


async def handle_settings_callback(callback: CallbackQuery, **data: Any) -> None:
    settings = data["settings"]
    user_id = _callback_user_id(callback)
    if not is_admin_user(user_id, settings.admin_ids):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    session = data.get("db_session")
    if session is None:
        await callback.answer("Настройки доступны только в runtime с БД.", show_alert=True)
        return
    callback_data = callback.data or ""
    service = _runtime_settings_service(session)
    saved = False
    if callback_data.startswith(SETTINGS_PROVIDER_PREFIX):
        provider_value = callback_data.removeprefix(SETTINGS_PROVIDER_PREFIX)
        try:
            provider = await service.set_active_llm_provider(
                provider_value,
                updated_by_telegram_id=user_id,
            )
        except ValueError:
            await callback.answer("Неизвестный провайдер.", show_alert=True)
            return
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        saved = True
        await callback.answer("Настройки сохранены.", show_alert=False)
    elif callback_data == SETTINGS_CALLBACK_REFRESH:
        try:
            provider = await service.get_active_llm_provider()
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        await callback.answer()
    elif callback_data == SETTINGS_CALLBACK_CLOSE:
        if callback.message is not None and hasattr(callback.message, "delete"):
            await cast(Message, callback.message).delete()
        await callback.answer()
        return
    else:
        await callback.answer("Неизвестная команда настроек.", show_alert=True)
        return
    if callback.message is not None and hasattr(callback.message, "edit_text"):
        await cast(Message, callback.message).edit_text(
            render_settings_text(provider, saved=saved),
            reply_markup=build_settings_keyboard(),
        )


async def cmd_status(message: Message, **data: Any) -> None:
    settings = data["settings"]
    bot_username = await _resolve_bot_username(data, settings.telegram_bot_username)
    if _is_command_for_other_bot(message, bot_username):
        return
    personal_chat = "enabled" if settings.regular_assistant_enabled else "disabled"
    group_assistant = "enabled" if settings.group_assistant_enabled else "disabled"
    guest_status = "enabled" if settings.guest_mode_enabled else "disabled"
    guest_access = "admin-only" if settings.guest_mode_admin_only else "open"
    forwarded_status = "enabled" if settings.forwarded_message_assistant_enabled else "disabled"
    draft_status = "enabled" if settings.draft_reply_enabled else "disabled"
    business_mode = "enabled" if settings.business_mode_enabled else "optional/disabled"
    business_reply = "enabled" if settings.business_reply_enabled else "disabled"
    business_admin_only = "true" if settings.business_admin_only else "false"
    streaming = "enabled" if settings.streaming_enabled else "disabled"
    private_draft_streaming = (
        "enabled" if settings.streaming_private_draft_enabled else "disabled"
    )
    group_fallback_streaming = (
        "enabled" if settings.streaming_group_fallback_enabled else "disabled"
    )
    draft_raw_api_fallback = (
        "enabled" if settings.streaming_draft_raw_api_fallback else "disabled"
    )
    business_count, business_active_count = await resolve_business_counts(data)
    await message.answer(
        "Статус: Regular Assistant Mode активен.\n"
        f"Personal Chat: {personal_chat}\n"
        f"Group Assistant: {group_assistant}\n"
        f"Guest Mode: {guest_status}\n"
        f"Guest access: {guest_access}\n"
        f"Forwarded Assistant: {forwarded_status}\n"
        f"Draft Reply: {draft_status}\n"
        f"Business Mode: {business_mode}\n"
        f"Business Reply: {business_reply}\n"
        f"Business Admin Only: {business_admin_only}\n"
        f"Business Connections: {business_count}\n"
        f"Business Active Connections: {business_active_count}\n"
        f"Streaming: {streaming}\n"
        f"Private Draft Streaming: {private_draft_streaming}\n"
        f"Group Fallback Streaming: {group_fallback_streaming}\n"
        f"Draft Raw API Fallback: {draft_raw_api_fallback}"
    )


async def _handle_context_command(
    message: Message,
    data: dict[str, Any],
    *,
    action: str,
) -> None:
    session = data.get("db_session")
    settings = data["settings"]
    bot_username = await _resolve_bot_username(data, settings.telegram_bot_username)
    if _is_command_for_other_bot(message, bot_username):
        return
    if session is None:
        await message.answer("Контекст доступен только в runtime с БД.")
        return
    inline_context = _command_argument(message)
    if inline_context is None:
        memory = MemoryService(
            MessageRepository(session),
            max_messages=settings.memory_max_messages,
        )
        recent = await memory.recent_messages(chat_id=message.chat.id)
        if not recent:
            await message.answer(
                "Не вижу переданного контекста. Перешли сообщение боту или пришли текст."
            )
            return
        context = "\n".join(item.content for item in recent[-5:])
    else:
        context = inline_context
    if not context.strip():
        await message.answer(
            "Не вижу переданного контекста. Перешли сообщение боту или пришли текст."
        )
        return
    provider = data.get("llm_provider") or build_llm_provider(settings)
    prompts = {
        "summary": "Кратко перескажи переданный контекст на русском.",
        "draft_reply": (
            "Подготовь вежливый черновик ответа на русском. Не утверждай, что отправил его."
        ),
        "translate": (
            "Выполни перевод по запросу пользователя. Если целевой язык указан, "
            "используй его; иначе переведи на русский. Не добавляй лишних пояснений."
        ),
        "factcheck": "Проверь факты в тексте. Если не уверен, честно отметь, что нужна проверка.",
    }
    try:
        response = await provider.complete(
            [
                LLMMessage(
                    role="system",
                    content="Ты Jarvis в Regular Assistant Mode. Отвечай только на русском.",
                ),
                LLMMessage(role="user", content=f"{prompts[action]}\n\nКонтекст:\n{context}"),
            ]
        )
    except LLMProviderError:
        await message.answer("Не смог обработать контекст: временная ошибка модели.")
        return
    await message.answer(response.content.strip() or "Не смог подготовить ответ.")


async def cmd_summary(message: Message, **data: Any) -> None:
    await _handle_context_command(message, data, action="summary")


async def cmd_draft_reply(message: Message, **data: Any) -> None:
    await _handle_context_command(message, data, action="draft_reply")


async def cmd_translate(message: Message, **data: Any) -> None:
    await _handle_context_command(message, data, action="translate")


async def cmd_factcheck(message: Message, **data: Any) -> None:
    await _handle_context_command(message, data, action="factcheck")


async def resolve_business_counts(data: dict[str, Any]) -> tuple[int, int]:
    injected = data.get("business_status_counts")
    if isinstance(injected, tuple) and len(injected) == 2:
        return int(injected[0]), int(injected[1])
    session = data.get("db_session")
    if not isinstance(session, AsyncSession):
        return 0, 0
    total_result = await session.execute(select(func.count(BusinessConnection.id)))
    active_result = await session.execute(
        select(func.count(BusinessConnection.id)).where(
            BusinessConnection.status == BusinessConnectionStatus.ENABLED,
            BusinessConnection.is_enabled.is_(True),
        )
    )
    return int(total_result.scalar_one()), int(active_result.scalar_one())


async def cmd_models(message: Message, **data: Any) -> None:
    settings = data["settings"]
    bot_username = await _resolve_bot_username(data, settings.telegram_bot_username)
    if _is_command_for_other_bot(message, bot_username):
        return
    current = settings.selected_model or "не задана"
    await message.answer(f"Текущая модель: {current}")


async def cmd_reset(message: Message, **data: Any) -> None:
    session = data.get("db_session")
    settings = data["settings"]
    bot_username = await _resolve_bot_username(data, settings.telegram_bot_username)
    if _is_command_for_other_bot(message, bot_username):
        return
    if session is None:
        await message.answer("Память очищается только в runtime с БД.")
        return
    service = MemoryService(MessageRepository(session), max_messages=settings.memory_max_messages)
    await service.reset_chat(chat_id=message.chat.id)
    await message.answer("Память этого чата очищена.")


def build_router() -> Router:
    router = Router(name="commands")
    router.message(Command("start"))(cmd_start)
    router.message(Command("help"))(cmd_help)
    router.message(Command("settings"))(cmd_settings)
    router.message(Command("status"))(cmd_status)
    router.message(Command("models"))(cmd_models)
    router.message(Command("reset"))(cmd_reset)
    router.message(Command("summary"))(cmd_summary)
    router.message(Command("draft_reply"))(cmd_draft_reply)
    router.message(Command("translate"))(cmd_translate)
    router.message(Command("factcheck"))(cmd_factcheck)
    router.callback_query(F.data.startswith("settings:"))(handle_settings_callback)
    return router


router = build_router()
