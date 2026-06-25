import logging
from dataclasses import dataclass
from typing import Any, cast

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.middlewares.access import is_admin_user
from app.db.models import BusinessConnection, BusinessConnectionStatus
from app.db.repositories.messages import MessageRepository
from app.db.repositories.runtime_settings import RuntimeSettingRepository
from app.db.repositories.telegram_access import TelegramAccessRepository
from app.llm.base import LLMProviderError
from app.llm.factory import build_llm_provider
from app.llm.types import LLMMessage
from app.services.memory_service import MemoryService
from app.services.runtime_settings_service import (
    ActiveLLMProvider,
    RuntimeSettingsService,
    RuntimeSettingsUnavailable,
)
from app.services.telegram_access_service import (
    AccessEntry,
    AccessMutationResult,
    TelegramAccessService,
    TelegramAccessUnavailable,
)

SETTINGS_CALLBACK_REFRESH = "settings:refresh"
SETTINGS_CALLBACK_CLOSE = "settings:close"
SETTINGS_CALLBACK_AGENT = "settings:agent"
SETTINGS_CALLBACK_ACCESS = "settings:access"
SETTINGS_CALLBACK_ACCESS_USERS = "settings:access:users"
SETTINGS_CALLBACK_ACCESS_GROUPS = "settings:access:groups"
SETTINGS_CALLBACK_ACCESS_USER_ADD = "settings:access:user:add"
SETTINGS_CALLBACK_ACCESS_USER_REMOVE = "settings:access:user:remove"
SETTINGS_CALLBACK_ACCESS_GROUP_ADD = "settings:access:group:add"
SETTINGS_CALLBACK_ACCESS_GROUP_REMOVE = "settings:access:group:remove"
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
ACCESS_UNAVAILABLE_MESSAGE = (
    "Настройки доступа временно недоступны: миграция БД ещё не применена."
)
logger = logging.getLogger(__name__)


class TelegramAccessInput(StatesGroup):
    add_user = State()
    remove_user = State()
    add_group = State()
    remove_group = State()


@dataclass(frozen=True)
class AccessInput:
    telegram_ids: list[int]
    label: str | None = None


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
                InlineKeyboardButton(text="Агент", callback_data=SETTINGS_CALLBACK_AGENT),
                InlineKeyboardButton(text="Доступ", callback_data=SETTINGS_CALLBACK_ACCESS),
            ],
            [
                InlineKeyboardButton(text="Обновить", callback_data=SETTINGS_CALLBACK_REFRESH),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def build_agent_settings_keyboard() -> InlineKeyboardMarkup:
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
                InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_REFRESH),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def build_access_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пользователи",
                    callback_data=SETTINGS_CALLBACK_ACCESS_USERS,
                ),
                InlineKeyboardButton(
                    text="Группы",
                    callback_data=SETTINGS_CALLBACK_ACCESS_GROUPS,
                ),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_REFRESH),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def build_access_users_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить пользователя",
                    callback_data=SETTINGS_CALLBACK_ACCESS_USER_ADD,
                ),
                InlineKeyboardButton(
                    text="Удалить пользователя",
                    callback_data=SETTINGS_CALLBACK_ACCESS_USER_REMOVE,
                ),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_ACCESS),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def build_access_groups_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить группу",
                    callback_data=SETTINGS_CALLBACK_ACCESS_GROUP_ADD,
                ),
                InlineKeyboardButton(
                    text="Удалить группу",
                    callback_data=SETTINGS_CALLBACK_ACCESS_GROUP_REMOVE,
                ),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_ACCESS),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def render_settings_home_text() -> str:
    return "Настройки Jarvis\n\nРазделы:\n- Агент\n- Доступ"


def render_settings_text(provider: ActiveLLMProvider, *, saved: bool = False) -> str:
    title = "Настройки сохранены." if saved else "Настройки Jarvis"
    return (
        f"{title}\n\n"
        "Раздел: Агент\n\n"
        f"Активный агент: {PROVIDER_LABELS[provider]}\n\n"
        "Выберите LLM-провайдера:\n"
        "[Auto] [Yandex] [OpenRouter]\n\n"
        "Текущий режим применится к следующим сообщениям."
    )


def render_access_settings_text(users_count: int, groups_count: int) -> str:
    return (
        "Доступ Jarvis\n\n"
        "Админы задаются через production env.\n"
        "Здесь можно управлять разрешёнными пользователями и группами.\n\n"
        f"Разрешённые пользователи: {users_count}\n"
        f"Разрешённые группы: {groups_count}"
    )


def render_access_entries_text(title: str, entries: list[AccessEntry]) -> str:
    lines = [title, ""]
    if entries:
        lines.extend(
            f"- {entry.telegram_id} — {entry.label or 'без подписи'}" for entry in entries
        )
    else:
        lines.append("Список пуст.")
    lines.extend(["", "Действия:"])
    return "\n".join(lines)


def _message_user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None


def _callback_user_id(callback: CallbackQuery) -> int | None:
    return callback.from_user.id if callback.from_user else None


def _runtime_settings_service(session: object) -> RuntimeSettingsService:
    return RuntimeSettingsService(RuntimeSettingRepository(session))  # type: ignore[arg-type]


def _telegram_access_service(session: object, admin_ids: set[int]) -> TelegramAccessService:
    return TelegramAccessService(
        TelegramAccessRepository(session),  # type: ignore[arg-type]
        admin_ids=admin_ids,
    )


def _is_message_not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in str(exc).lower()


async def _safe_edit_settings_message(
    message: object,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> str:
    if not hasattr(message, "edit_text"):
        return "missing_message"
    try:
        await cast(Message, message).edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if _is_message_not_modified(exc):
            return "not_modified"
        logger.warning(
            "settings_message_edit_failed",
            extra={"error_type": type(exc).__name__},
        )
        return "telegram_error"
    return "updated"


async def _safe_delete_settings_message(message: object) -> str:
    if not hasattr(message, "delete"):
        return "missing_message"
    try:
        await cast(Message, message).delete()
    except TelegramBadRequest as exc:
        if _is_message_not_modified(exc):
            return "not_modified"
        logger.warning(
            "settings_message_delete_failed",
            extra={"error_type": type(exc).__name__},
        )
        return "telegram_error"
    return "deleted"


async def _edit_settings_callback_message(
    callback: CallbackQuery,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    if callback.message is None:
        await callback.answer()
        return True
    edit_status = await _safe_edit_settings_message(
        callback.message,
        text=text,
        reply_markup=reply_markup,
    )
    if edit_status == "not_modified":
        await callback.answer("Настройки уже актуальны.", show_alert=False)
        return False
    if edit_status == "telegram_error":
        await callback.answer("Не удалось обновить сообщение настроек.", show_alert=True)
        return False
    return True


def _parse_access_input(text: str | None) -> AccessInput | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    tokens = stripped.split()
    if _all_integer_tokens(tokens):
        return AccessInput([int(token) for token in tokens])
    parts = stripped.split(maxsplit=1)
    try:
        telegram_id = int(parts[0])
    except ValueError:
        return None
    label = parts[1].strip() if len(parts) > 1 else None
    return AccessInput([telegram_id], label or None)


def _all_integer_tokens(tokens: list[str]) -> bool:
    if not tokens:
        return False
    for token in tokens:
        try:
            int(token)
        except ValueError:
            return False
    return True


def _render_id_lines(ids: list[int]) -> str:
    return "\n".join(f"- {telegram_id}" for telegram_id in ids)


def _render_access_input_lines(parsed: AccessInput, ids: list[int]) -> str:
    if len(parsed.telegram_ids) == 1 and parsed.label is not None:
        return "\n".join(f"- {telegram_id} — {parsed.label}" for telegram_id in ids)
    return _render_id_lines(ids)


def _invalid_access_input_message(kind: str) -> str:
    return (
        f"Не понял ID. Отправьте Telegram {kind} ID числом.\n"
        "Пример:\n"
        "59144850 Александр\n\n"
        "Для отмены отправьте /cancel."
    )


def _validate_positive_ids(telegram_ids: list[int]) -> None:
    if any(telegram_id <= 0 for telegram_id in telegram_ids):
        raise ValueError("invalid_user_id")


def _render_remove_result(
    *,
    singular_removed: str,
    plural_removed: str,
    singular_missing: str,
    plural_missing: str,
    removed_ids: list[int],
    missing_ids: list[int],
    screen_title: str,
    entries: list[AccessEntry],
) -> str:
    lines: list[str] = []
    if removed_ids:
        if len(removed_ids) == 1:
            lines.append(singular_removed)
            lines.append(_render_id_lines(removed_ids))
        else:
            lines.append(plural_removed)
            lines.append(_render_id_lines(removed_ids))
    if missing_ids:
        lines.append(singular_missing if len(missing_ids) == 1 else plural_missing)
        lines.append(_render_id_lines(missing_ids))
    if not lines:
        lines.append(singular_missing)
    lines.extend(["", render_access_entries_text(screen_title, entries)])
    return "\n".join(lines)


def _render_add_result(
    *,
    singular_created: str,
    singular_existing: str,
    created_ids: list[int],
    existing_ids: list[int],
    parsed: AccessInput,
    screen_title: str,
    entries: list[AccessEntry],
) -> str:
    lines: list[str] = []
    if len(parsed.telegram_ids) == 1:
        if created_ids:
            lines.append(singular_created)
            lines.append(_render_access_input_lines(parsed, created_ids))
        else:
            lines.append(singular_existing)
            lines.append(_render_access_input_lines(parsed, existing_ids))
    else:
        if created_ids:
            lines.append("Добавлены:")
            lines.append(_render_access_input_lines(parsed, created_ids))
        if existing_ids:
            lines.append("Уже были:")
            lines.append(_render_access_input_lines(parsed, existing_ids))
    lines.extend(["", render_access_entries_text(screen_title, entries)])
    return "\n".join(lines)


async def cmd_whoami(message: Message, **data: Any) -> None:
    settings = data.get("settings")
    bot_username = await _resolve_bot_username(
        data,
        settings.telegram_bot_username if settings is not None else "",
    )
    if bot_username and _is_command_for_other_bot(message, bot_username):
        return
    if message.from_user is None:
        await message.answer("Не удалось определить Telegram user ID.")
        return
    text = (
        f"Ваш Telegram ID: {message.from_user.id}\n"
        f"Chat ID: {message.chat.id}\n"
        f"Тип чата: {message.chat.type}"
    )
    kwargs: dict[str, Any] = {}
    if message.chat.type in {"group", "supergroup"}:
        kwargs["reply_to_message_id"] = message.message_id
    await message.answer(text, **kwargs)


async def cmd_settings(message: Message, **data: Any) -> None:
    settings = data["settings"]
    if not is_admin_user(_message_user_id(message), settings.admin_ids):
        await message.answer("Доступ запрещён.")
        return
    session = data.get("db_session")
    if session is None:
        await message.answer("Настройки доступны только в runtime с БД.")
        return
    await message.answer(render_settings_home_text(), reply_markup=build_settings_keyboard())


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
    saved = False
    if callback_data.startswith(SETTINGS_PROVIDER_PREFIX):
        service = _runtime_settings_service(session)
        provider_value = callback_data.removeprefix(SETTINGS_PROVIDER_PREFIX)
        try:
            current_provider = await service.get_active_llm_provider()
            provider = ActiveLLMProvider(provider_value)
            if current_provider == provider:
                await callback.answer(
                    f"Уже выбрано: {PROVIDER_LABELS[provider]}",
                    show_alert=False,
                )
                return
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
        edited = await _edit_settings_callback_message(
            callback,
            text=render_settings_text(provider, saved=saved),
            reply_markup=build_agent_settings_keyboard(),
        )
        if not edited:
            return
        await callback.answer("Настройки сохранены.", show_alert=False)
        return
    if callback_data == SETTINGS_CALLBACK_REFRESH:
        edited = await _edit_settings_callback_message(
            callback,
            text=render_settings_home_text(),
            reply_markup=build_settings_keyboard(),
        )
        if edited:
            await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_AGENT:
        service = _runtime_settings_service(session)
        try:
            provider = await service.get_active_llm_provider()
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        edited = await _edit_settings_callback_message(
            callback,
            text=render_settings_text(provider),
            reply_markup=build_agent_settings_keyboard(),
        )
        if edited:
            await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_ACCESS:
        try:
            access_service = _telegram_access_service(session, settings.admin_ids)
            users = await access_service.list_allowed_users()
            groups = await access_service.list_allowed_groups()
        except TelegramAccessUnavailable:
            await callback.answer(ACCESS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        edited = await _edit_settings_callback_message(
            callback,
            text=render_access_settings_text(len(users), len(groups)),
            reply_markup=build_access_settings_keyboard(),
        )
        if edited:
            await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_ACCESS_USERS:
        try:
            users = await _telegram_access_service(session, settings.admin_ids).list_allowed_users()
        except TelegramAccessUnavailable:
            await callback.answer(ACCESS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        edited = await _edit_settings_callback_message(
            callback,
            text=render_access_entries_text("Разрешённые пользователи", users),
            reply_markup=build_access_users_keyboard(),
        )
        if edited:
            await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_ACCESS_GROUPS:
        try:
            access_service = _telegram_access_service(session, settings.admin_ids)
            groups = await access_service.list_allowed_groups()
        except TelegramAccessUnavailable:
            await callback.answer(ACCESS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        edited = await _edit_settings_callback_message(
            callback,
            text=render_access_entries_text("Разрешённые группы", groups),
            reply_markup=build_access_groups_keyboard(),
        )
        if edited:
            await callback.answer()
        return
    if callback_data in {
        SETTINGS_CALLBACK_ACCESS_USER_ADD,
        SETTINGS_CALLBACK_ACCESS_USER_REMOVE,
        SETTINGS_CALLBACK_ACCESS_GROUP_ADD,
        SETTINGS_CALLBACK_ACCESS_GROUP_REMOVE,
    }:
        state = cast(Any, data.get("state"))
        if state is None or not all(
            hasattr(state, attr) for attr in ("set_state", "clear")
        ):
            await callback.answer("FSM временно недоступен.", show_alert=True)
            return
        prompts = {
            SETTINGS_CALLBACK_ACCESS_USER_ADD: (
                TelegramAccessInput.add_user,
                "Отправьте Telegram user ID.\n"
                "Можно добавить подпись через пробел:\n\n"
                "59144850 Александр",
            ),
            SETTINGS_CALLBACK_ACCESS_USER_REMOVE: (
                TelegramAccessInput.remove_user,
                "Отправьте Telegram ID, который нужно удалить.\n"
                "Для отмены отправьте /cancel.",
            ),
            SETTINGS_CALLBACK_ACCESS_GROUP_ADD: (
                TelegramAccessInput.add_group,
                "Отправьте Telegram group chat ID.\n"
                "Можно добавить подпись через пробел:\n\n"
                "-5437860232 Домашний чат",
            ),
            SETTINGS_CALLBACK_ACCESS_GROUP_REMOVE: (
                TelegramAccessInput.remove_group,
                "Отправьте Telegram ID, который нужно удалить.\n"
                "Для отмены отправьте /cancel.",
            ),
        }
        next_state, prompt = prompts[callback_data]
        await state.set_state(next_state)
        edited = await _edit_settings_callback_message(
            callback,
            text=prompt,
            reply_markup=None,
        )
        if edited:
            await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_CLOSE:
        await callback.answer()
        if callback.message is not None:
            delete_status = await _safe_delete_settings_message(callback.message)
            if delete_status not in {"deleted", "not_modified"}:
                await _safe_edit_settings_message(
                    callback.message,
                    text="Настройки закрыты.",
                    reply_markup=None,
                )
        return
    await callback.answer("Неизвестная команда настроек.", show_alert=True)


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


async def handle_access_input_message(
    message: Message,
    state: FSMContext,
    **data: Any,
) -> None:
    settings = data["settings"]
    user_id = _message_user_id(message)
    if not is_admin_user(user_id, settings.admin_ids):
        await message.answer("Доступ запрещён.")
        return
    text = message.text or message.caption
    if text and text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("Ввод отменён.")
        return
    session = data.get("db_session")
    if session is None:
        await message.answer("Настройки доступны только в runtime с БД.")
        return
    current_state = await state.get_state()
    parsed = _parse_access_input(text)
    if parsed is None:
        await message.answer(_invalid_access_input_message("user/group"))
        return
    service = _telegram_access_service(session, settings.admin_ids)
    try:
        if current_state == TelegramAccessInput.add_user.state:
            _validate_positive_ids(parsed.telegram_ids)
            created_ids: list[int] = []
            existing_ids: list[int] = []
            for telegram_id in parsed.telegram_ids:
                label = parsed.label if len(parsed.telegram_ids) == 1 else None
                mutation_result = await service.add_allowed_user(
                    telegram_id,
                    label,
                    created_by=user_id,
                )
                if mutation_result is AccessMutationResult.CREATED:
                    created_ids.append(telegram_id)
                else:
                    existing_ids.append(telegram_id)
            logger.info("telegram_access_user_added")
            await state.clear()
            users = await service.list_allowed_users()
            await message.answer(
                _render_add_result(
                    singular_created="Пользователь добавлен:",
                    singular_existing="Пользователь уже есть в списке:",
                    created_ids=created_ids,
                    existing_ids=existing_ids,
                    parsed=parsed,
                    screen_title="Разрешённые пользователи",
                    entries=users,
                ),
                reply_markup=build_access_users_keyboard(),
            )
            return
        if current_state == TelegramAccessInput.remove_user.state:
            _validate_positive_ids(parsed.telegram_ids)
            removed_ids: list[int] = []
            missing_ids: list[int] = []
            for telegram_id in parsed.telegram_ids:
                removed = await service.remove_allowed_user(telegram_id)
                if removed is AccessMutationResult.REMOVED:
                    removed_ids.append(telegram_id)
                else:
                    missing_ids.append(telegram_id)
            logger.info("telegram_access_user_removed")
            await state.clear()
            users = await service.list_allowed_users()
            await message.answer(
                _render_remove_result(
                    singular_removed="Пользователь удалён:",
                    plural_removed="Удалены пользователи:",
                    singular_missing="Пользователь не найден:",
                    plural_missing="Пользователи не найдены:",
                    removed_ids=removed_ids,
                    missing_ids=missing_ids,
                    screen_title="Разрешённые пользователи",
                    entries=users,
                ),
                reply_markup=build_access_users_keyboard(),
            )
            return
        if current_state == TelegramAccessInput.add_group.state:
            created_ids = []
            existing_ids = []
            for telegram_id in parsed.telegram_ids:
                label = parsed.label if len(parsed.telegram_ids) == 1 else None
                mutation_result = await service.add_allowed_group(
                    telegram_id,
                    label,
                    created_by=user_id,
                )
                if mutation_result is AccessMutationResult.CREATED:
                    created_ids.append(telegram_id)
                else:
                    existing_ids.append(telegram_id)
            logger.info("telegram_access_group_added")
            await state.clear()
            groups = await service.list_allowed_groups()
            await message.answer(
                _render_add_result(
                    singular_created="Группа добавлена:",
                    singular_existing="Группа уже есть в списке:",
                    created_ids=created_ids,
                    existing_ids=existing_ids,
                    parsed=parsed,
                    screen_title="Разрешённые группы",
                    entries=groups,
                ),
                reply_markup=build_access_groups_keyboard(),
            )
            return
        if current_state == TelegramAccessInput.remove_group.state:
            removed_ids = []
            missing_ids = []
            for telegram_id in parsed.telegram_ids:
                removed = await service.remove_allowed_group(telegram_id)
                if removed is AccessMutationResult.REMOVED:
                    removed_ids.append(telegram_id)
                else:
                    missing_ids.append(telegram_id)
            logger.info("telegram_access_group_removed")
            await state.clear()
            groups = await service.list_allowed_groups()
            await message.answer(
                _render_remove_result(
                    singular_removed="Группа удалена:",
                    plural_removed="Удалены группы:",
                    singular_missing="Группа не найдена:",
                    plural_missing="Группы не найдены:",
                    removed_ids=removed_ids,
                    missing_ids=missing_ids,
                    screen_title="Разрешённые группы",
                    entries=groups,
                ),
                reply_markup=build_access_groups_keyboard(),
            )
            return
    except ValueError:
        await message.answer(_invalid_access_input_message("user"))
        return
    except TelegramAccessUnavailable:
        await message.answer(ACCESS_UNAVAILABLE_MESSAGE)
        return
    await state.clear()
    await message.answer("Ввод отменён.")


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
    router.message(Command("whoami"))(cmd_whoami)
    router.message(Command("settings"))(cmd_settings)
    router.message(Command("status"))(cmd_status)
    router.message(Command("models"))(cmd_models)
    router.message(Command("reset"))(cmd_reset)
    router.message(Command("summary"))(cmd_summary)
    router.message(Command("draft_reply"))(cmd_draft_reply)
    router.message(Command("translate"))(cmd_translate)
    router.message(Command("factcheck"))(cmd_factcheck)
    router.message(Command("cancel"))(handle_access_input_message)
    router.message(StateFilter(TelegramAccessInput.add_user))(handle_access_input_message)
    router.message(StateFilter(TelegramAccessInput.remove_user))(handle_access_input_message)
    router.message(StateFilter(TelegramAccessInput.add_group))(handle_access_input_message)
    router.message(StateFilter(TelegramAccessInput.remove_group))(handle_access_input_message)
    router.callback_query(F.data.startswith("settings:"))(handle_settings_callback)
    return router


router = build_router()
