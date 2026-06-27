from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, EditMessageText

from app.bot.routers import commands
from app.core.config import Settings
from app.services.runtime_settings_service import (
    DEFAULT_PROMPTS,
    ActiveLLMProvider,
    PromptProfile,
    PromptProfileScope,
    PromptSetting,
    PromptSource,
    RuntimeSettingsUnavailable,
    WebSearchProviderName,
    WebSearchSettings,
)
from app.services.telegram_access_service import AccessMutationResult


class FakeUser:
    def __init__(self, user_id: int | None) -> None:
        self.id = user_id


class FakeChat:
    id = 123
    type = "private"


class FakeMessage:
    def __init__(
        self,
        text: str = "/settings",
        user_id: int | None = 100500,
        *,
        delete_error: Exception | None = None,
        edit_error: Exception | None = None,
    ) -> None:
        self.text = text
        self.caption = None
        self.chat = FakeChat()
        self.from_user = FakeUser(user_id) if user_id is not None else None
        self.answers: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.deleted = False
        self.delete_error = delete_error
        self.edit_error = edit_error

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        if self.edit_error is not None:
            raise self.edit_error
        self.edits.append({"text": text, **kwargs})

    async def delete(self) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True


class FakeCallbackQuery:
    def __init__(
        self,
        data: str,
        *,
        user_id: int | None = 100500,
        message: FakeMessage | None = None,
    ) -> None:
        self.data = data
        self.from_user = FakeUser(user_id) if user_id is not None else None
        self.message = message or FakeMessage(user_id=user_id)
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


def telegram_bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=DeleteMessage(chat_id=123, message_id=1), message=message)


def telegram_edit_bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(
        method=EditMessageText(chat_id=123, message_id=1, text="text"),
        message=message,
    )


def test_settings_home_contains_daily_brief_section() -> None:
    text = commands.render_settings_home_text()
    keyboard = commands.build_settings_keyboard()

    assert "Сводка дня" in text
    assert any(
        button.text == "Сводка дня"
        and button.callback_data == commands.SETTINGS_CALLBACK_DAILY_BRIEF
        for row in keyboard.inline_keyboard
        for button in row
    )


def test_settings_home_contains_web_search_section() -> None:
    text = commands.render_settings_home_text()
    keyboard = commands.build_settings_keyboard()

    assert "Интернет-поиск" in text
    assert any(
        button.text == "Интернет-поиск"
        and button.callback_data == commands.SETTINGS_CALLBACK_WEB_SEARCH
        for row in keyboard.inline_keyboard
        for button in row
    )


def test_render_web_search_settings_text_shows_degraded_without_key() -> None:
    text = commands.render_web_search_settings_text(
        WebSearchSettings(
            enabled=True,
            provider=WebSearchProviderName.TAVILY,
            max_results=5,
        ),
        provider_key_available=False,
    )
    keyboard = commands.build_web_search_settings_keyboard(enabled=True)

    assert "Интернет-поиск" in text
    assert "Статус: включён" in text
    assert "Provider: tavily" in text
    assert "Режим: только явные команды" in text
    assert "Максимум источников: 5" in text
    assert "provider key не настроен" in text
    assert any(
        button.callback_data == commands.SETTINGS_CALLBACK_WEB_SEARCH_MAX_RESULTS
        for row in keyboard.inline_keyboard
        for button in row
    )


def test_render_daily_brief_settings_text() -> None:
    text = commands.render_daily_brief_settings_text(
        enabled=True,
        send_time="09:00",
        timezone_name="Europe/Moscow",
    )

    assert "Сводка дня" in text
    assert "Статус: включена" in text
    assert "Время: 09:00" in text
    assert "Часовой пояс: Europe/Moscow" in text
    assert "Куда: личка" in text


class FakeRuntimeSettingsService:
    instances: list["FakeRuntimeSettingsService"] = []
    provider = ActiveLLMProvider.AUTO
    profiles = {
        PromptProfileScope.PRIVATE: PromptProfile.BALANCED,
        PromptProfileScope.GROUP: PromptProfile.BALANCED,
        PromptProfileScope.WATCHER: PromptProfile.BALANCED,
    }
    prompts: dict[PromptProfileScope, str] = {}
    brief_enabled = False
    brief_time = "09:00"
    brief_timezone = "Europe/Moscow"

    def __init__(self, repository: object) -> None:
        del repository
        self.saved: list[tuple[str, int | None]] = []
        self.saved_profiles: list[tuple[PromptProfileScope, str, int | None]] = []
        self.saved_prompts: list[tuple[PromptProfileScope, str, int | None]] = []
        self.reset_prompts: list[PromptProfileScope] = []
        self.__class__.instances.append(self)

    async def get_active_llm_provider(self) -> ActiveLLMProvider:
        return self.__class__.provider

    async def set_active_llm_provider(
        self,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> ActiveLLMProvider:
        self.saved.append((value, updated_by_telegram_id))
        self.__class__.provider = ActiveLLMProvider(value)
        return self.__class__.provider

    async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
        return self.__class__.profiles[scope]

    async def set_prompt_profile(
        self,
        scope: PromptProfileScope,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> PromptProfile:
        self.saved_profiles.append((scope, value, updated_by_telegram_id))
        self.__class__.profiles[scope] = PromptProfile(value)
        return self.__class__.profiles[scope]

    async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
        if scope in self.__class__.prompts:
            return PromptSetting(
                scope=scope,
                text=self.__class__.prompts[scope],
                source=PromptSource.CUSTOM,
            )
        return PromptSetting(scope=scope, text=DEFAULT_PROMPTS[scope], source=PromptSource.DEFAULT)

    async def set_prompt(
        self,
        scope: PromptProfileScope,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> PromptSetting:
        self.saved_prompts.append((scope, value, updated_by_telegram_id))
        self.__class__.prompts[scope] = value
        return PromptSetting(scope=scope, text=value, source=PromptSource.CUSTOM)

    async def reset_prompt(self, scope: PromptProfileScope) -> PromptSetting:
        self.reset_prompts.append(scope)
        self.__class__.prompts.pop(scope, None)
        return PromptSetting(scope=scope, text=DEFAULT_PROMPTS[scope], source=PromptSource.DEFAULT)

    async def get_daily_brief_settings(self, *, chat_id: int, user_id: int) -> object:
        del chat_id, user_id
        return type(
            "DailyBriefSettings",
            (),
            {
                "enabled": self.__class__.brief_enabled,
                "send_time": self.__class__.brief_time,
                "timezone": self.__class__.brief_timezone,
            },
        )()


class FakeTelegramAccessService:
    instances: list["FakeTelegramAccessService"] = []
    users: list[Any] = []
    groups: list[Any] = []
    added_users: list[tuple[int, str | None, int | None]] = []
    removed_users: list[int] = []
    added_groups: list[tuple[int, str | None, int | None]] = []
    removed_groups: list[int] = []

    def __init__(self, repository: object, *, admin_ids: set[int]) -> None:
        del repository
        self.admin_ids = admin_ids
        self.__class__.instances.append(self)

    def is_admin_user(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    async def list_allowed_users(self) -> list[Any]:
        return self.__class__.users

    async def list_allowed_groups(self) -> list[Any]:
        return self.__class__.groups

    async def add_allowed_user(
        self,
        user_id: int,
        label: str | None,
        *,
        created_by: int | None,
    ) -> AccessMutationResult:
        self.__class__.added_users.append((user_id, label, created_by))
        existing = next(
            (entry for entry in self.__class__.users if entry.telegram_id == user_id),
            None,
        )
        if existing is not None:
            self.__class__.users = [
                commands.AccessEntry("user", user_id, label, created_by)
                if entry.telegram_id == user_id
                else entry
                for entry in self.__class__.users
            ]
            return AccessMutationResult.ALREADY_EXISTS
        self.__class__.users.append(commands.AccessEntry("user", user_id, label, created_by))
        return AccessMutationResult.CREATED

    async def remove_allowed_user(self, user_id: int) -> AccessMutationResult:
        self.__class__.removed_users.append(user_id)
        before = len(self.__class__.users)
        self.__class__.users = [
            entry for entry in self.__class__.users if entry.telegram_id != user_id
        ]
        if len(self.__class__.users) == before:
            return AccessMutationResult.NOT_FOUND
        return AccessMutationResult.REMOVED

    async def add_allowed_group(
        self,
        chat_id: int,
        label: str | None,
        *,
        created_by: int | None,
    ) -> AccessMutationResult:
        self.__class__.added_groups.append((chat_id, label, created_by))
        existing = next(
            (entry for entry in self.__class__.groups if entry.telegram_id == chat_id),
            None,
        )
        if existing is not None:
            self.__class__.groups = [
                commands.AccessEntry("group", chat_id, label, created_by)
                if entry.telegram_id == chat_id
                else entry
                for entry in self.__class__.groups
            ]
            return AccessMutationResult.ALREADY_EXISTS
        self.__class__.groups.append(commands.AccessEntry("group", chat_id, label, created_by))
        return AccessMutationResult.CREATED

    async def remove_allowed_group(self, chat_id: int) -> AccessMutationResult:
        self.__class__.removed_groups.append(chat_id)
        before = len(self.__class__.groups)
        self.__class__.groups = [
            entry for entry in self.__class__.groups if entry.telegram_id != chat_id
        ]
        if len(self.__class__.groups) == before:
            return AccessMutationResult.NOT_FOUND
        return AccessMutationResult.REMOVED

class FakeState:
    def __init__(self, state: str | None = None) -> None:
        self.current_state = state
        self.data: dict[str, Any] = {}
        self.cleared = False

    async def set_state(self, state: Any) -> None:
        self.current_state = state.state

    async def get_state(self) -> str | None:
        return self.current_state

    async def update_data(self, **kwargs: Any) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, Any]:
        return self.data

    async def clear(self) -> None:
        self.current_state = None
        self.cleared = True

@pytest.fixture(autouse=True)
def patch_settings_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeRuntimeSettingsService.instances = []
    FakeRuntimeSettingsService.provider = ActiveLLMProvider.AUTO
    FakeRuntimeSettingsService.profiles = {
        PromptProfileScope.PRIVATE: PromptProfile.BALANCED,
        PromptProfileScope.GROUP: PromptProfile.BALANCED,
        PromptProfileScope.WATCHER: PromptProfile.BALANCED,
    }
    FakeRuntimeSettingsService.prompts = {}
    FakeTelegramAccessService.instances = []
    FakeTelegramAccessService.users = []
    FakeTelegramAccessService.groups = []
    FakeTelegramAccessService.added_users = []
    FakeTelegramAccessService.removed_users = []
    FakeTelegramAccessService.added_groups = []
    FakeTelegramAccessService.removed_groups = []
    monkeypatch.setattr(commands, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(commands, "RuntimeSettingsService", FakeRuntimeSettingsService)
    monkeypatch.setattr(commands, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(commands, "TelegramAccessService", FakeTelegramAccessService)


@pytest.mark.asyncio
async def test_start_command_shows_settings_button() -> None:
    message = FakeMessage("/start")

    await commands.cmd_start(message)  # type: ignore[arg-type]

    answer = message.answers[0]
    keyboard = answer["reply_markup"].inline_keyboard
    assert "Jarvis готов" in answer["text"]
    assert keyboard[0][0].text == "Настройки"
    assert keyboard[0][0].callback_data == "settings:refresh"


@pytest.mark.asyncio
async def test_settings_command_admin_can_open_menu() -> None:
    message = FakeMessage(user_id=100500)

    await commands.cmd_settings(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    answer = message.answers[0]
    keyboard = answer["reply_markup"].inline_keyboard
    assert "Настройки Jarvis" in answer["text"]
    assert "Разделы:" in answer["text"]
    assert [button.text for button in keyboard[0]] == ["Агент", "Доступ"]
    assert [button.callback_data for button in keyboard[0]] == [
        "settings:agent",
        "settings:access",
    ]
    assert [button.text for button in keyboard[1]] == ["Промты", "Стиль ответа"]
    assert [button.callback_data for button in keyboard[1]] == [
        "settings:prompts",
        "settings:profiles",
    ]


@pytest.mark.asyncio
async def test_settings_command_non_admin_is_denied() -> None:
    message = FakeMessage(user_id=7)

    await commands.cmd_settings(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert message.answers == [{"text": "Доступ запрещён."}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("callback_data", "expected_provider", "expected_label"),
    [
        ("settings:provider:openrouter", ActiveLLMProvider.OPENROUTER, "OpenRouter"),
        ("settings:provider:yandex", ActiveLLMProvider.YANDEX, "Yandex"),
    ],
)
async def test_provider_callback_saves_setting_and_refreshes_menu(
    callback_data: str,
    expected_provider: ActiveLLMProvider,
    expected_label: str,
) -> None:
    callback = FakeCallbackQuery(callback_data, user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    service = FakeRuntimeSettingsService.instances[0]
    assert service.saved == [(expected_provider.value, 100500)]
    assert callback.answers == [{"text": "Настройки сохранены.", "show_alert": False}]
    assert f"Активный агент: {expected_label}" in callback.message.edits[0]["text"]


@pytest.mark.asyncio
async def test_whoami_returns_user_and_chat_ids_in_private() -> None:
    message = FakeMessage("/whoami", user_id=59144850)
    message.chat.id = 59144850
    message.chat.type = "private"

    await commands.cmd_whoami(message)  # type: ignore[arg-type]

    assert message.answers == [
        {
            "text": (
                "Ваш Telegram user ID: 59144850\n"
                "Тип чата: private\n"
                "Telegram chat ID: 59144850"
            )
        }
    ]


@pytest.mark.asyncio
async def test_access_section_visible_to_admin() -> None:
    callback = FakeCallbackQuery("settings:access", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    edit = callback.message.edits[0]
    keyboard = edit["reply_markup"].inline_keyboard
    assert "Доступ Jarvis" in edit["text"]
    assert "Разрешённые пользователи: 0" in edit["text"]
    assert "Разрешённые группы: 0" in edit["text"]
    assert [button.text for button in keyboard[0]] == ["Пользователи", "Группы"]


@pytest.mark.asyncio
async def test_prompt_profiles_section_visible_to_admin() -> None:
    callback = FakeCallbackQuery("settings:prompts", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    edit = callback.message.edits[0]
    keyboard = edit["reply_markup"].inline_keyboard
    assert "Промты Jarvis" in edit["text"]
    assert "Выберите режим:" in edit["text"]
    assert "Личка — prompt для private chat" in edit["text"]
    assert "Группа — prompt для group mention/reply" in edit["text"]
    assert "Наблюдение — заготовка для будущего watcher" in edit["text"]
    assert [button.text for button in keyboard[0]] == ["Личка", "Группа", "Наблюдение"]


@pytest.mark.asyncio
async def test_private_prompt_page_shows_default_raw_prompt_text() -> None:
    callback = FakeCallbackQuery("settings:prompts:private", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    edit = callback.message.edits[0]
    keyboard = edit["reply_markup"].inline_keyboard
    assert "Промт: Личка" in edit["text"]
    assert "Источник: default" in edit["text"]
    assert "Текущий prompt:" in edit["text"]
    assert DEFAULT_PROMPTS[PromptProfileScope.PRIVATE] in edit["text"]
    assert [button.text for button in keyboard[0]] == ["Изменить", "Сбросить"]
    assert [button.callback_data for button in keyboard[0]] == [
        "settings:prompt:private:edit",
        "settings:prompt:private:reset",
    ]


@pytest.mark.asyncio
async def test_group_prompt_page_shows_default_raw_prompt_text() -> None:
    callback = FakeCallbackQuery("settings:prompts:group", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Промт: Группа" in callback.message.edits[0]["text"]
    assert DEFAULT_PROMPTS[PromptProfileScope.GROUP] in callback.message.edits[0]["text"]


@pytest.mark.asyncio
async def test_watch_prompt_page_shows_default_raw_prompt_text() -> None:
    callback = FakeCallbackQuery("settings:prompts:watcher", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Промт: Наблюдение" in callback.message.edits[0]["text"]
    assert DEFAULT_PROMPTS[PromptProfileScope.WATCHER] in callback.message.edits[0]["text"]


@pytest.mark.asyncio
async def test_custom_prompt_after_save_is_shown_and_input_does_not_go_to_llm() -> None:
    callback = FakeCallbackQuery("settings:prompt:private:edit", user_id=100500)
    state = FakeState()

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
        state=state,
    )

    assert state.current_state == commands.PromptEditorInput.private.state
    assert 'Отправьте новый prompt для режима "Личка".' in callback.message.edits[0]["text"]

    message = FakeMessage("Новый сырой prompt", user_id=100500)
    await commands.handle_prompt_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    service = FakeRuntimeSettingsService.instances[-1]
    assert service.saved_prompts == [
        (PromptProfileScope.PRIVATE, "Новый сырой prompt", 100500)
    ]
    assert state.cleared is True
    assert "Промт сохранён." in message.answers[0]["text"]
    assert "Новый сырой prompt" in message.answers[0]["text"]
    assert "Думаю" not in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_reset_prompt_returns_default_prompt_to_ui() -> None:
    FakeRuntimeSettingsService.prompts[PromptProfileScope.GROUP] = "Кастомный group prompt"
    callback = FakeCallbackQuery("settings:prompt:group:reset", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    service = FakeRuntimeSettingsService.instances[0]
    assert service.reset_prompts == [PromptProfileScope.GROUP]
    assert callback.answers == [{"text": "Промт сброшен.", "show_alert": False}]
    assert "Источник: default" in callback.message.edits[0]["text"]
    assert DEFAULT_PROMPTS[PromptProfileScope.GROUP] in callback.message.edits[0]["text"]


@pytest.mark.asyncio
async def test_long_prompt_uses_preview_and_full_message_callback() -> None:
    FakeRuntimeSettingsService.prompts[PromptProfileScope.PRIVATE] = "я" * 3900
    callback = FakeCallbackQuery("settings:prompts:private", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    edit = callback.message.edits[0]
    keyboard = edit["reply_markup"].inline_keyboard
    assert "Показан preview" in edit["text"]
    assert any(button.text == "Показать полностью" for row in keyboard for button in row)

    full_callback = FakeCallbackQuery(
        "settings:prompt:private:full",
        user_id=100500,
        message=callback.message,
    )
    await commands.handle_settings_callback(
        full_callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert full_callback.message.answers[-1] == {"text": "я" * 3900}


@pytest.mark.asyncio
async def test_cancel_clears_prompt_edit_state_and_returns_profile_screen() -> None:
    state = FakeState(commands.PromptEditorInput.group.state)
    message = FakeMessage("/cancel", user_id=100500)

    await commands.handle_prompt_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert state.cleared is True
    assert "Редактирование prompt отменено." in message.answers[0]["text"]
    assert "Промт: Группа" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_response_style_section_keeps_presets_separate_from_raw_prompts() -> None:
    FakeRuntimeSettingsService.profiles[PromptProfileScope.PRIVATE] = PromptProfile.SHORT
    callback = FakeCallbackQuery("settings:profiles", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Стиль ответа Jarvis" in callback.message.edits[0]["text"]
    assert "Личные сообщения: Короткий" in callback.message.edits[0]["text"]


@pytest.mark.asyncio
async def test_access_users_list_works() -> None:
    FakeTelegramAccessService.users = [
        commands.AccessEntry(entry_type="user", telegram_id=59144850, label="Александр")
    ]
    callback = FakeCallbackQuery("settings:access:users", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Разрешённые пользователи" in callback.message.edits[0]["text"]
    assert "- 59144850 — Александр" in callback.message.edits[0]["text"]


@pytest.mark.asyncio
async def test_access_groups_list_works() -> None:
    FakeTelegramAccessService.groups = [
        commands.AccessEntry(entry_type="group", telegram_id=-5437860232, label="Домашний чат")
    ]
    callback = FakeCallbackQuery("settings:access:groups", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Разрешённые группы" in callback.message.edits[0]["text"]
    assert "- -5437860232 — Домашний чат" in callback.message.edits[0]["text"]


@pytest.mark.asyncio
async def test_add_user_fsm_works() -> None:
    callback = FakeCallbackQuery("settings:access:user:add", user_id=100500)
    state = FakeState()

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
        state=state,
    )
    assert state.current_state == commands.TelegramAccessInput.add_user.state
    assert "Отправьте Telegram user ID" in callback.message.edits[0]["text"]

    message = FakeMessage("59144850 Александр", user_id=100500)
    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert FakeTelegramAccessService.added_users == [(59144850, "Александр", 100500)]
    assert state.cleared is True
    assert "Пользователь добавлен:" in message.answers[0]["text"]
    assert "уже" not in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_add_existing_user_fsm_reports_already_exists() -> None:
    FakeTelegramAccessService.users = [
        commands.AccessEntry(entry_type="user", telegram_id=59144850, label="Александр")
    ]
    state = FakeState(commands.TelegramAccessInput.add_user.state)
    message = FakeMessage("59144850 Александр", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Пользователь уже есть в списке:" in message.answers[0]["text"]
    assert "- 59144850 — Александр" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_add_multiple_users_splits_created_and_existing() -> None:
    FakeTelegramAccessService.users = [
        commands.AccessEntry(entry_type="user", telegram_id=123456789, label=None)
    ]
    state = FakeState(commands.TelegramAccessInput.add_user.state)
    message = FakeMessage("5117224471 291844566 123456789", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    text = message.answers[0]["text"]
    assert "Добавлены:" in text
    assert "- 5117224471" in text
    assert "- 291844566" in text
    assert "Уже были:" in text
    assert "- 123456789" in text


@pytest.mark.asyncio
async def test_remove_user_fsm_works() -> None:
    state = FakeState(commands.TelegramAccessInput.remove_user.state)
    message = FakeMessage("59144850", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert FakeTelegramAccessService.removed_users == [59144850]
    assert "Пользователь не найден:" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_remove_existing_user_fsm_reports_removed() -> None:
    FakeTelegramAccessService.users = [
        commands.AccessEntry(entry_type="user", telegram_id=59144850, label="Александр")
    ]
    state = FakeState(commands.TelegramAccessInput.remove_user.state)
    message = FakeMessage("59144850", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Пользователь удалён:" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_add_group_fsm_works() -> None:
    state = FakeState(commands.TelegramAccessInput.add_group.state)
    message = FakeMessage("-5437860232 Домашний чат", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert FakeTelegramAccessService.added_groups == [(-5437860232, "Домашний чат", 100500)]
    assert "Группа добавлена:" in message.answers[0]["text"]
    assert "- -5437860232 — Домашний чат" in message.answers[0]["text"]
    assert "уже была" not in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_add_existing_group_fsm_reports_already_exists() -> None:
    FakeTelegramAccessService.groups = [
        commands.AccessEntry(entry_type="group", telegram_id=-5437860232, label="Домашний чат")
    ]
    state = FakeState(commands.TelegramAccessInput.add_group.state)
    message = FakeMessage("-5437860232 Домашний чат", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    text = message.answers[0]["text"]
    assert "Группа уже есть в списке:" in text
    assert "- -5437860232 — Домашний чат" in text


@pytest.mark.asyncio
async def test_remove_group_fsm_works() -> None:
    state = FakeState(commands.TelegramAccessInput.remove_group.state)
    message = FakeMessage("-5437860232", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert FakeTelegramAccessService.removed_groups == [-5437860232]
    assert "Группа не найдена:" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_remove_existing_group_fsm_reports_removed() -> None:
    FakeTelegramAccessService.groups = [
        commands.AccessEntry(entry_type="group", telegram_id=-5437860232, label="Домашний чат")
    ]
    state = FakeState(commands.TelegramAccessInput.remove_group.state)
    message = FakeMessage("-5437860232", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Группа удалена:" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_cancel_clears_access_input_state() -> None:
    state = FakeState(commands.TelegramAccessInput.add_user.state)
    message = FakeMessage("/cancel", user_id=100500)

    await commands.handle_access_input_message(
        message,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert state.cleared is True
    assert message.answers == [{"text": "Ввод отменён."}]


@pytest.mark.asyncio
async def test_settings_callback_non_admin_is_denied() -> None:
    callback = FakeCallbackQuery("settings:provider:openrouter", user_id=7)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert callback.answers == [{"text": "Доступ запрещён.", "show_alert": True}]
    assert FakeRuntimeSettingsService.instances == []


@pytest.mark.asyncio
async def test_settings_command_handles_missing_runtime_settings_table() -> None:
    class MissingTableSettingsService(FakeRuntimeSettingsService):
        async def get_active_llm_provider(self) -> ActiveLLMProvider:
            raise RuntimeSettingsUnavailable("runtime_settings_unavailable")

    commands.RuntimeSettingsService = MissingTableSettingsService  # type: ignore[assignment]
    callback = FakeCallbackQuery("settings:agent", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert callback.answers == [
        {
            "text": "Настройки временно недоступны: миграция БД ещё не применена.",
            "show_alert": True,
        }
    ]


@pytest.mark.asyncio
async def test_settings_callback_handles_missing_runtime_settings_table() -> None:
    class MissingTableSettingsService(FakeRuntimeSettingsService):
        async def get_active_llm_provider(self) -> ActiveLLMProvider:
            raise RuntimeSettingsUnavailable("runtime_settings_unavailable")

    commands.RuntimeSettingsService = MissingTableSettingsService  # type: ignore[assignment]
    callback = FakeCallbackQuery("settings:agent", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert callback.answers == [
        {
            "text": "Настройки временно недоступны: миграция БД ещё не применена.",
            "show_alert": True,
        }
    ]
    assert callback.message.edits == []


@pytest.mark.asyncio
async def test_refresh_callback_ignores_message_not_modified() -> None:
    callback = FakeCallbackQuery(
        "settings:refresh",
        user_id=100500,
        message=FakeMessage(
            user_id=100500,
            edit_error=telegram_edit_bad_request("Bad Request: message is not modified"),
        ),
    )

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert callback.answers == [{"text": "Настройки уже актуальны.", "show_alert": False}]


@pytest.mark.asyncio
async def test_provider_callback_for_same_provider_does_not_edit_same_message() -> None:
    FakeRuntimeSettingsService.provider = ActiveLLMProvider.YANDEX
    callback = FakeCallbackQuery("settings:provider:yandex", user_id=100500)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert callback.answers == [{"text": "Уже выбрано: Yandex", "show_alert": False}]
    assert callback.message.edits == []


@pytest.mark.asyncio
async def test_close_callback_deletes_settings_message() -> None:
    message = FakeMessage(user_id=100500)
    callback = FakeCallbackQuery("settings:close", user_id=100500, message=message)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert message.deleted is True
    assert callback.answers == [{"text": None}]


@pytest.mark.asyncio
async def test_close_callback_edits_closed_text_when_delete_fails() -> None:
    message = FakeMessage(
        user_id=100500,
        delete_error=telegram_bad_request("Bad Request: message can't be deleted"),
    )
    callback = FakeCallbackQuery("settings:close", user_id=100500, message=message)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert message.edits == [{"text": "Настройки закрыты.", "reply_markup": None}]
    assert callback.answers == [{"text": None}]


@pytest.mark.asyncio
async def test_message_not_modified_is_safe_noop_for_close_fallback_edit() -> None:
    message = FakeMessage(
        user_id=100500,
        delete_error=telegram_bad_request("Bad Request: message can't be deleted"),
        edit_error=telegram_edit_bad_request("Bad Request: message is not modified"),
    )
    callback = FakeCallbackQuery("settings:close", user_id=100500, message=message)

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert callback.answers == [{"text": None}]


@pytest.mark.asyncio
async def test_unexpected_telegram_bad_request_is_reported_without_webhook_crash() -> None:
    callback = FakeCallbackQuery(
        "settings:refresh",
        user_id=100500,
        message=FakeMessage(
            user_id=100500,
            edit_error=telegram_edit_bad_request("Bad Request: chat not found"),
        ),
    )

    await commands.handle_settings_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert callback.answers == [
        {"text": "Не удалось обновить сообщение настроек.", "show_alert": True}
    ]
