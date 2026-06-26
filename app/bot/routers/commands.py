import logging
from dataclasses import dataclass
from typing import Any, cast
from zoneinfo import ZoneInfoNotFoundError

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
    MAX_PROMPT_LENGTH,
    ActiveLLMProvider,
    PromptProfile,
    PromptProfileScope,
    PromptSetting,
    PromptSource,
    RuntimeSettingsService,
    RuntimeSettingsUnavailable,
)
from app.services.telegram_access_service import (
    AccessEntry,
    AccessMutationResult,
    TelegramAccessService,
    TelegramAccessUnavailable,
)
from app.services.telegram_formatting import format_lists_reminders_private_help_html

SETTINGS_CALLBACK_REFRESH = "settings:refresh"
SETTINGS_CALLBACK_CLOSE = "settings:close"
SETTINGS_CALLBACK_AGENT = "settings:agent"
SETTINGS_CALLBACK_ACCESS = "settings:access"
SETTINGS_CALLBACK_LISTS = "settings:lists"
SETTINGS_CALLBACK_LISTS_TIMEZONE = "settings:lists:timezone"
SETTINGS_CALLBACK_LISTS_HELP = "settings:lists:help"
SETTINGS_CALLBACK_LISTS_REMINDERS = "settings:lists:reminders"
SETTINGS_CALLBACK_LISTS_SHOPPING = "settings:lists:shopping"
SETTINGS_CALLBACK_PROMPTS = "settings:prompts"
SETTINGS_CALLBACK_PROMPTS_PRIVATE = "settings:prompts:private"
SETTINGS_CALLBACK_PROMPTS_GROUP = "settings:prompts:group"
SETTINGS_CALLBACK_PROMPTS_WATCHER = "settings:prompts:watcher"
SETTINGS_CALLBACK_PROFILES = "settings:profiles"
SETTINGS_CALLBACK_PROFILES_PRIVATE = "settings:profiles:private"
SETTINGS_CALLBACK_PROFILES_GROUP = "settings:profiles:group"
SETTINGS_CALLBACK_PROFILES_WATCHER = "settings:profiles:watcher"
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
SETTINGS_PROFILE_PREFIX = "settings:profile:"
SETTINGS_PROMPT_PREFIX = "settings:prompt:"
PROMPT_PREVIEW_LIMIT = 3200
PROVIDER_LABELS = {
    ActiveLLMProvider.AUTO: "Auto",
    ActiveLLMProvider.YANDEX: "Yandex",
    ActiveLLMProvider.OPENROUTER: "OpenRouter",
}
PROMPT_PROFILE_LABELS = {
    PromptProfile.BALANCED: "Сбалансированный",
    PromptProfile.SHORT: "Короткий",
    PromptProfile.DEEP: "Подробный",
    PromptProfile.DRAFT: "Черновик",
    PromptProfile.WATCHER: "Watcher",
}
PROMPT_PROFILE_SCOPE_LABELS = {
    PromptProfileScope.PRIVATE: "личные сообщения",
    PromptProfileScope.GROUP: "группы",
    PromptProfileScope.WATCHER: "watcher",
}
PROMPT_SCOPE_TITLES = {
    PromptProfileScope.PRIVATE: "Личка",
    PromptProfileScope.GROUP: "Группа",
    PromptProfileScope.WATCHER: "Наблюдение",
}
PROMPT_PROFILE_SCOPE_OVERVIEW_LABELS = {
    PromptProfileScope.PRIVATE: "Личные сообщения",
    PromptProfileScope.GROUP: "Группы",
    PromptProfileScope.WATCHER: "Watcher",
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


class PromptEditorInput(StatesGroup):
    private = State()
    group = State()
    watcher = State()


class ListsRemindersSettingsInput(StatesGroup):
    timezone = State()


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
                InlineKeyboardButton(text="Промты", callback_data=SETTINGS_CALLBACK_PROMPTS),
                InlineKeyboardButton(
                    text="Стиль ответа",
                    callback_data=SETTINGS_CALLBACK_PROFILES,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Списки и напоминания",
                    callback_data=SETTINGS_CALLBACK_LISTS,
                )
            ],
            [
                InlineKeyboardButton(text="Обновить", callback_data=SETTINGS_CALLBACK_REFRESH),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def build_lists_reminders_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Часовой пояс",
                    callback_data=SETTINGS_CALLBACK_LISTS_TIMEZONE,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Помощь по командам",
                    callback_data=SETTINGS_CALLBACK_LISTS_HELP,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Мои напоминания",
                    callback_data=SETTINGS_CALLBACK_LISTS_REMINDERS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Мой список покупок",
                    callback_data=SETTINGS_CALLBACK_LISTS_SHOPPING,
                )
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_REFRESH),
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


def build_prompts_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Личка",
                    callback_data=SETTINGS_CALLBACK_PROMPTS_PRIVATE,
                ),
                InlineKeyboardButton(
                    text="Группа",
                    callback_data=SETTINGS_CALLBACK_PROMPTS_GROUP,
                ),
                InlineKeyboardButton(
                    text="Наблюдение",
                    callback_data=SETTINGS_CALLBACK_PROMPTS_WATCHER,
                ),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_REFRESH),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def build_prompt_editor_keyboard(
    scope: PromptProfileScope,
    *,
    show_full: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Изменить",
                callback_data=f"{SETTINGS_PROMPT_PREFIX}{scope.value}:edit",
            ),
            InlineKeyboardButton(
                text="Сбросить",
                callback_data=f"{SETTINGS_PROMPT_PREFIX}{scope.value}:reset",
            ),
        ],
    ]
    if show_full:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Показать полностью",
                    callback_data=f"{SETTINGS_PROMPT_PREFIX}{scope.value}:full",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_PROMPTS),
            InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_prompt_profiles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Личные",
                    callback_data=SETTINGS_CALLBACK_PROFILES_PRIVATE,
                ),
                InlineKeyboardButton(
                    text="Группы",
                    callback_data=SETTINGS_CALLBACK_PROFILES_GROUP,
                ),
                InlineKeyboardButton(
                    text="Watcher",
                    callback_data=SETTINGS_CALLBACK_PROFILES_WATCHER,
                ),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_REFRESH),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def build_prompt_profile_scope_keyboard(scope: PromptProfileScope) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=PROMPT_PROFILE_LABELS[PromptProfile.BALANCED],
                    callback_data=f"{SETTINGS_PROFILE_PREFIX}{scope.value}:balanced",
                ),
                InlineKeyboardButton(
                    text=PROMPT_PROFILE_LABELS[PromptProfile.SHORT],
                    callback_data=f"{SETTINGS_PROFILE_PREFIX}{scope.value}:short",
                ),
                InlineKeyboardButton(
                    text=PROMPT_PROFILE_LABELS[PromptProfile.DEEP],
                    callback_data=f"{SETTINGS_PROFILE_PREFIX}{scope.value}:deep",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=PROMPT_PROFILE_LABELS[PromptProfile.DRAFT],
                    callback_data=f"{SETTINGS_PROFILE_PREFIX}{scope.value}:draft",
                ),
                InlineKeyboardButton(
                    text=PROMPT_PROFILE_LABELS[PromptProfile.WATCHER],
                    callback_data=f"{SETTINGS_PROFILE_PREFIX}{scope.value}:watcher",
                ),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data=SETTINGS_CALLBACK_PROFILES),
                InlineKeyboardButton(text="Закрыть", callback_data=SETTINGS_CALLBACK_CLOSE),
            ],
        ]
    )


def render_settings_home_text() -> str:
    return (
        "Настройки Jarvis\n\n"
        "Разделы:\n"
        "- Агент\n"
        "- Доступ\n"
        "- Промты\n"
        "- Стиль ответа\n"
        "- Списки и напоминания"
    )


def render_lists_reminders_settings_text(timezone_name: str) -> str:
    return (
        "Списки и напоминания\n\n"
        f"Часовой пояс: {timezone_name}\n\n"
        "Что можно делать:\n"
        "- список покупок в личке и группе\n"
        "- напоминания в личке и группе\n\n"
        "Действия:"
    )


def render_lists_timezone_prompt_text() -> str:
    return (
        "Отправьте часовой пояс, например:\n"
        "Europe/Moscow\n"
        "Europe/Amsterdam\n"
        "Asia/Dubai\n\n"
        "Для отмены отправьте /cancel."
    )


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


def render_prompt_profiles_text(
    *,
    private_profile: PromptProfile,
    group_profile: PromptProfile,
    watcher_profile: PromptProfile,
) -> str:
    return (
        "Стиль ответа Jarvis\n\n"
        f"Личные сообщения: {PROMPT_PROFILE_LABELS[private_profile]}\n"
        f"Группы: {PROMPT_PROFILE_LABELS[group_profile]}\n"
        f"Watcher: {PROMPT_PROFILE_LABELS[watcher_profile]}\n\n"
        "Это пресеты стиля ответа, а не редактор raw prompt."
    )


def render_prompt_profile_scope_text(
    scope: PromptProfileScope,
    profile: PromptProfile,
    *,
    saved: bool = False,
) -> str:
    title = "Профиль сохранён." if saved else f"Профиль: {PROMPT_PROFILE_SCOPE_LABELS[scope]}"
    return (
        f"{title}\n\n"
        f"Профиль: {PROMPT_PROFILE_SCOPE_LABELS[scope]}\n"
        f"Текущий профиль: {PROMPT_PROFILE_LABELS[profile]}\n\n"
        "Выберите один из фиксированных безопасных профилей."
    )


def render_prompts_text() -> str:
    return (
        "Промты Jarvis\n\n"
        "Выберите режим:\n"
        "Личка — prompt для private chat\n"
        "Группа — prompt для group mention/reply\n"
        "Наблюдение — заготовка для будущего watcher\n\n"
        "Наблюдение пока ничего не включает автоматически."
    )


def render_prompt_editor_text(prompt: PromptSetting, *, saved: bool = False) -> tuple[str, bool]:
    title = f"Промт: {PROMPT_SCOPE_TITLES[prompt.scope]}"
    prefix = "Промт сохранён.\n\n" if saved else ""
    source = "custom" if prompt.source is PromptSource.CUSTOM else "default"
    if len(prompt.text) > PROMPT_PREVIEW_LIMIT:
        shown = prompt.text[:PROMPT_PREVIEW_LIMIT]
        prompt_text = (
            f"{shown}\n\n"
            "Показан preview: prompt не помещается в экран настроек. "
            "Нажмите «Показать полностью»."
        )
        show_full = True
    else:
        prompt_text = prompt.text
        show_full = False
    text = (
        f"{prefix}{title}\n"
        f"Источник: {source}\n"
        f"Длина: {len(prompt.text)} символов\n\n"
        f"Текущий prompt:\n{prompt_text}\n\n"
        "Действия:"
    )
    return text, show_full


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


async def _prompt_profiles_snapshot(
    service: RuntimeSettingsService,
) -> tuple[PromptProfile, PromptProfile, PromptProfile]:
    return (
        await service.get_prompt_profile(PromptProfileScope.PRIVATE),
        await service.get_prompt_profile(PromptProfileScope.GROUP),
        await service.get_prompt_profile(PromptProfileScope.WATCHER),
    )


def _parse_prompt_profile_callback(
    callback_data: str,
) -> tuple[PromptProfileScope, PromptProfile] | None:
    payload = callback_data.removeprefix(SETTINGS_PROFILE_PREFIX)
    parts = payload.split(":")
    if len(parts) != 2:
        return None
    try:
        return PromptProfileScope(parts[0]), PromptProfile(parts[1])
    except ValueError:
        return None


def _parse_prompt_action_callback(
    callback_data: str,
) -> tuple[PromptProfileScope, str] | None:
    payload = callback_data.removeprefix(SETTINGS_PROMPT_PREFIX)
    parts = payload.split(":")
    if len(parts) != 2:
        return None
    scope_value, action = parts
    if action not in {"edit", "reset", "full"}:
        return None
    try:
        return PromptProfileScope(scope_value), action
    except ValueError:
        return None


def _prompt_editor_state(scope: PromptProfileScope) -> State:
    return {
        PromptProfileScope.PRIVATE: PromptEditorInput.private,
        PromptProfileScope.GROUP: PromptEditorInput.group,
        PromptProfileScope.WATCHER: PromptEditorInput.watcher,
    }[scope]


def _prompt_scope_from_state(state: str | None) -> PromptProfileScope | None:
    return {
        PromptEditorInput.private.state: PromptProfileScope.PRIVATE,
        PromptEditorInput.group.state: PromptProfileScope.GROUP,
        PromptEditorInput.watcher.state: PromptProfileScope.WATCHER,
    }.get(state)


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
    lines = [
        f"Ваш Telegram user ID: {message.from_user.id}",
        f"Тип чата: {message.chat.type}",
        f"Telegram chat ID: {message.chat.id}",
    ]
    if message.chat.type in {"group", "supergroup"} and settings is not None:
        user_allowed = False
        group_allowed = False
        session = data.get("db_session")
        if session is not None:
            try:
                access_service = _telegram_access_service(session, settings.admin_ids)
                user_allowed = await access_service.is_allowed_user(message.from_user.id)
                group_allowed = await access_service.is_allowed_group(message.chat.id)
            except TelegramAccessUnavailable:
                user_allowed = False
                group_allowed = False
        lines.append(f"Пользователь разрешён: {'да' if user_allowed else 'нет'}")
        lines.append(f"Группа разрешена: {'да' if group_allowed else 'нет'}")
    text = "\n".join(lines)
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
    if user_id is None:
        await callback.answer("Не удалось определить Telegram user ID.", show_alert=True)
        return
    if not is_admin_user(user_id, settings.admin_ids):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    session = data.get("db_session")
    if session is None:
        await callback.answer("Настройки доступны только в runtime с БД.", show_alert=True)
        return
    callback_data = callback.data or ""
    saved = False
    if callback_data.startswith(SETTINGS_PROMPT_PREFIX):
        parsed_prompt_action = _parse_prompt_action_callback(callback_data)
        if parsed_prompt_action is None:
            await callback.answer("Неизвестный prompt.", show_alert=True)
            return
        scope, action = parsed_prompt_action
        service = _runtime_settings_service(session)
        if action == "edit":
            state = cast(Any, data.get("state"))
            if state is None or not all(
                hasattr(state, attr) for attr in ("set_state", "clear")
            ):
                await callback.answer("FSM временно недоступен.", show_alert=True)
                return
            await state.set_state(_prompt_editor_state(scope))
            edited = await _edit_settings_callback_message(
                callback,
                text=(
                    f"Отправьте новый prompt для режима "
                    f"\"{PROMPT_SCOPE_TITLES[scope]}\".\n"
                    f"Лимит: {MAX_PROMPT_LENGTH} символов.\n"
                    "Чтобы отменить, отправьте /cancel."
                ),
                reply_markup=None,
            )
            if edited:
                await callback.answer()
            return
        try:
            if action == "reset":
                prompt = await service.reset_prompt(scope)
                text, show_full = render_prompt_editor_text(prompt)
                edited = await _edit_settings_callback_message(
                    callback,
                    text=text,
                    reply_markup=build_prompt_editor_keyboard(scope, show_full=show_full),
                )
                if edited:
                    await callback.answer("Промт сброшен.", show_alert=False)
                return
            prompt = await service.get_prompt(scope)
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        if action == "full":
            if callback.message is not None:
                await callback.message.answer(prompt.text)
            await callback.answer()
            return
    if callback_data.startswith(SETTINGS_PROFILE_PREFIX):
        parsed_profile = _parse_prompt_profile_callback(callback_data)
        if parsed_profile is None:
            await callback.answer("Неизвестный профиль.", show_alert=True)
            return
        scope, profile = parsed_profile
        service = _runtime_settings_service(session)
        try:
            current_profile = await service.get_prompt_profile(scope)
            if current_profile == profile:
                await callback.answer(
                    f"Уже выбран профиль: {PROMPT_PROFILE_LABELS[profile]}",
                    show_alert=False,
                )
                return
            profile = await service.set_prompt_profile(
                scope,
                profile.value,
                updated_by_telegram_id=user_id,
            )
        except ValueError:
            await callback.answer("Неизвестный профиль.", show_alert=True)
            return
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        edited = await _edit_settings_callback_message(
            callback,
            text=render_prompt_profile_scope_text(scope, profile, saved=True),
            reply_markup=build_prompt_profile_scope_keyboard(scope),
        )
        if not edited:
            return
        await callback.answer("Профиль сохранён.", show_alert=False)
        return
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
    if callback_data == SETTINGS_CALLBACK_LISTS:
        service = _runtime_settings_service(session)
        try:
            timezone = await service.get_lists_timezone()
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        edited = await _edit_settings_callback_message(
            callback,
            text=render_lists_reminders_settings_text(getattr(timezone, "key", str(timezone))),
            reply_markup=build_lists_reminders_settings_keyboard(),
        )
        if edited:
            await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_LISTS_TIMEZONE:
        state = cast(Any, data.get("state"))
        if state is None or not all(hasattr(state, attr) for attr in ("set_state", "clear")):
            await callback.answer("FSM временно недоступен.", show_alert=True)
            return
        await state.set_state(ListsRemindersSettingsInput.timezone)
        edited = await _edit_settings_callback_message(
            callback,
            text=render_lists_timezone_prompt_text(),
            reply_markup=None,
        )
        if edited:
            await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_LISTS_HELP:
        if callback.message is not None:
            await callback.message.answer(
                format_lists_reminders_private_help_html(),
                parse_mode="HTML",
            )
        await callback.answer()
        return
    if callback_data in {SETTINGS_CALLBACK_LISTS_REMINDERS, SETTINGS_CALLBACK_LISTS_SHOPPING}:
        if callback.message is None:
            await callback.answer()
            return
        try:
            if callback_data == SETTINGS_CALLBACK_LISTS_SHOPPING:
                from app.bot.routers.lists_reminders import build_shopping_keyboard
                from app.db.repositories.shopping import ShoppingRepository
                from app.services.shopping_service import ShoppingService
                from app.services.telegram_formatting import format_shopping_list_html

                view = await ShoppingService(ShoppingRepository(session)).list_items(
                    "private",
                    user_id,
                )
                await callback.message.answer(
                    format_shopping_list_html(view),
                    parse_mode="HTML",
                    reply_markup=build_shopping_keyboard(view),
                )
            else:
                from app.bot.routers.lists_reminders import build_reminders_list_keyboard
                from app.db.repositories.reminders import ReminderRepository
                from app.services.reminder_service import ReminderService
                from app.services.telegram_formatting import format_reminders_html

                timezone = await _runtime_settings_service(session).get_lists_timezone()
                reminders = await ReminderService(ReminderRepository(session)).list_reminders(
                    "private",
                    user_id,
                    user_id,
                )
                await callback.message.answer(
                    format_reminders_html(reminders, timezone=timezone),
                    parse_mode="HTML",
                    reply_markup=build_reminders_list_keyboard(reminders),
                )
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_PROMPTS:
        edited = await _edit_settings_callback_message(
            callback,
            text=render_prompts_text(),
            reply_markup=build_prompts_keyboard(),
        )
        if edited:
            await callback.answer()
        return
    prompt_scope_callbacks = {
        SETTINGS_CALLBACK_PROMPTS_PRIVATE: PromptProfileScope.PRIVATE,
        SETTINGS_CALLBACK_PROMPTS_GROUP: PromptProfileScope.GROUP,
        SETTINGS_CALLBACK_PROMPTS_WATCHER: PromptProfileScope.WATCHER,
    }
    if callback_data in prompt_scope_callbacks:
        scope = prompt_scope_callbacks[callback_data]
        service = _runtime_settings_service(session)
        try:
            prompt = await service.get_prompt(scope)
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        text, show_full = render_prompt_editor_text(prompt)
        edited = await _edit_settings_callback_message(
            callback,
            text=text,
            reply_markup=build_prompt_editor_keyboard(scope, show_full=show_full),
        )
        if edited:
            await callback.answer()
        return
    if callback_data == SETTINGS_CALLBACK_PROFILES:
        service = _runtime_settings_service(session)
        try:
            private_profile, group_profile, watcher_profile = await _prompt_profiles_snapshot(
                service
            )
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        edited = await _edit_settings_callback_message(
            callback,
            text=render_prompt_profiles_text(
                private_profile=private_profile,
                group_profile=group_profile,
                watcher_profile=watcher_profile,
            ),
            reply_markup=build_prompt_profiles_keyboard(),
        )
        if edited:
            await callback.answer()
        return
    profile_scope_callbacks = {
        SETTINGS_CALLBACK_PROFILES_PRIVATE: PromptProfileScope.PRIVATE,
        SETTINGS_CALLBACK_PROFILES_GROUP: PromptProfileScope.GROUP,
        SETTINGS_CALLBACK_PROFILES_WATCHER: PromptProfileScope.WATCHER,
    }
    if callback_data in profile_scope_callbacks:
        scope = profile_scope_callbacks[callback_data]
        service = _runtime_settings_service(session)
        try:
            profile = await service.get_prompt_profile(scope)
        except RuntimeSettingsUnavailable:
            await callback.answer(SETTINGS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        edited = await _edit_settings_callback_message(
            callback,
            text=render_prompt_profile_scope_text(scope, profile),
            reply_markup=build_prompt_profile_scope_keyboard(scope),
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
        next_state, access_prompt = prompts[callback_data]
        await state.set_state(next_state)
        edited = await _edit_settings_callback_message(
            callback,
            text=access_prompt,
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
    mira_private_draft_streaming = (
        "enabled" if settings.telegram_private_draft_streaming_enabled else "disabled"
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
        f"Mira Private Draft Streaming: {mira_private_draft_streaming}\n"
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


async def handle_prompt_input_message(
    message: Message,
    state: FSMContext,
    **data: Any,
) -> None:
    settings = data["settings"]
    user_id = _message_user_id(message)
    if not is_admin_user(user_id, settings.admin_ids):
        await message.answer("Доступ запрещён.")
        return
    current_state = await state.get_state()
    scope = _prompt_scope_from_state(current_state)
    if scope is None:
        await state.clear()
        await message.answer("Ввод отменён.")
        return
    text = message.text or message.caption or ""
    if text.strip().lower() == "/cancel":
        await state.clear()
        session = data.get("db_session")
        if session is None:
            await message.answer("Редактирование prompt отменено.")
            return
        try:
            prompt = await _runtime_settings_service(session).get_prompt(scope)
        except RuntimeSettingsUnavailable:
            await message.answer("Редактирование prompt отменено.")
            return
        rendered, show_full = render_prompt_editor_text(prompt)
        await message.answer(
            f"Редактирование prompt отменено.\n\n{rendered}",
            reply_markup=build_prompt_editor_keyboard(scope, show_full=show_full),
        )
        return
    if not text.strip():
        await message.answer(
            "Prompt не может быть пустым.\n"
            f"Лимит: {MAX_PROMPT_LENGTH} символов.\n"
            "Чтобы отменить, отправьте /cancel."
        )
        return
    session = data.get("db_session")
    if session is None:
        await message.answer("Настройки доступны только в runtime с БД.")
        return
    service = _runtime_settings_service(session)
    try:
        prompt = await service.set_prompt(
            scope,
            text,
            updated_by_telegram_id=user_id,
        )
    except ValueError:
        await message.answer(
            f"Prompt слишком длинный. Лимит: {MAX_PROMPT_LENGTH} символов.\n"
            "Чтобы отменить, отправьте /cancel."
        )
        return
    except RuntimeSettingsUnavailable:
        await message.answer(SETTINGS_UNAVAILABLE_MESSAGE)
        return
    await state.clear()
    rendered, show_full = render_prompt_editor_text(prompt, saved=True)
    await message.answer(
        rendered,
        reply_markup=build_prompt_editor_keyboard(scope, show_full=show_full),
    )


async def handle_lists_timezone_input_message(
    message: Message,
    state: FSMContext,
    **data: Any,
) -> None:
    settings = data["settings"]
    user_id = _message_user_id(message)
    if not is_admin_user(user_id, settings.admin_ids):
        await message.answer("Доступ запрещён.")
        return
    text = (message.text or message.caption or "").strip()
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Изменение часового пояса отменено.")
        return
    if not text:
        await message.answer(render_lists_timezone_prompt_text())
        return
    session = data.get("db_session")
    if session is None:
        await message.answer("Настройки доступны только в runtime с БД.")
        return
    try:
        timezone = await _runtime_settings_service(session).set_lists_timezone(
            text,
            updated_by_telegram_id=user_id,
        )
    except (ValueError, ZoneInfoNotFoundError):
        await message.answer(
            "Не знаю такой часовой пояс.\n\n"
            f"{render_lists_timezone_prompt_text()}"
        )
        return
    except RuntimeSettingsUnavailable:
        await message.answer(SETTINGS_UNAVAILABLE_MESSAGE)
        return
    await state.clear()
    timezone_name = getattr(timezone, "key", str(timezone))
    await message.answer(
        f"Часовой пояс сохранён: {timezone_name}\n\n"
        f"{render_lists_reminders_settings_text(timezone_name)}",
        reply_markup=build_lists_reminders_settings_keyboard(),
    )


async def handle_cancel_message(
    message: Message,
    state: FSMContext,
    **data: Any,
) -> None:
    current_state = await state.get_state()
    if _prompt_scope_from_state(current_state) is not None:
        await handle_prompt_input_message(message, state, **data)
        return
    if current_state == ListsRemindersSettingsInput.timezone.state:
        await handle_lists_timezone_input_message(message, state, **data)
        return
    if current_state and (
        current_state.startswith("ShoppingListInput:")
        or current_state.startswith("ReminderInput:")
    ):
        await state.clear()
        await message.answer("Ввод отменён.")
        return
    await handle_access_input_message(message, state, **data)


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
    router.message(Command("cancel"))(handle_cancel_message)
    router.message(StateFilter(PromptEditorInput.private))(handle_prompt_input_message)
    router.message(StateFilter(PromptEditorInput.group))(handle_prompt_input_message)
    router.message(StateFilter(PromptEditorInput.watcher))(handle_prompt_input_message)
    router.message(StateFilter(ListsRemindersSettingsInput.timezone))(
        handle_lists_timezone_input_message
    )
    router.message(StateFilter(TelegramAccessInput.add_user))(handle_access_input_message)
    router.message(StateFilter(TelegramAccessInput.remove_user))(handle_access_input_message)
    router.message(StateFilter(TelegramAccessInput.add_group))(handle_access_input_message)
    router.message(StateFilter(TelegramAccessInput.remove_group))(handle_access_input_message)
    router.callback_query(F.data.startswith("settings:"))(handle_settings_callback)
    return router


router = build_router()
