from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, EditMessageText

from app.bot.routers import commands
from app.core.config import Settings
from app.services.runtime_settings_service import ActiveLLMProvider, RuntimeSettingsUnavailable


class FakeUser:
    def __init__(self, user_id: int | None) -> None:
        self.id = user_id


class FakeChat:
    id = 123


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


class FakeRuntimeSettingsService:
    instances: list["FakeRuntimeSettingsService"] = []
    provider = ActiveLLMProvider.AUTO

    def __init__(self, repository: object) -> None:
        del repository
        self.saved: list[tuple[str, int | None]] = []
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


@pytest.fixture(autouse=True)
def patch_settings_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeRuntimeSettingsService.instances = []
    FakeRuntimeSettingsService.provider = ActiveLLMProvider.AUTO
    monkeypatch.setattr(commands, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(commands, "RuntimeSettingsService", FakeRuntimeSettingsService)


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
    assert "Активный агент: Auto" in answer["text"]
    assert [button.text for button in keyboard[0]] == ["Auto", "Yandex", "OpenRouter"]
    assert [button.callback_data for button in keyboard[0]] == [
        "settings:provider:auto",
        "settings:provider:yandex",
        "settings:provider:openrouter",
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
    message = FakeMessage(user_id=100500)

    await commands.cmd_settings(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        db_session=object(),
    )

    assert "Настройки временно недоступны" in message.answers[0]["text"]
    assert "alembic upgrade head" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_settings_callback_handles_missing_runtime_settings_table() -> None:
    class MissingTableSettingsService(FakeRuntimeSettingsService):
        async def get_active_llm_provider(self) -> ActiveLLMProvider:
            raise RuntimeSettingsUnavailable("runtime_settings_unavailable")

    commands.RuntimeSettingsService = MissingTableSettingsService  # type: ignore[assignment]
    callback = FakeCallbackQuery("settings:refresh", user_id=100500)

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
