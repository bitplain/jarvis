import pytest

from app.core.config import Settings
from app.services.regular_assistant_service import (
    DRAFT_REPLY_SYSTEM_PROMPT,
    RegularAssistantService,
    is_draft_reply_request,
)


def test_regular_modes_are_enabled_without_business_env() -> None:
    settings = Settings()

    assert settings.regular_assistant_enabled is True
    assert settings.forwarded_message_assistant_enabled is True
    assert settings.draft_reply_enabled is True
    assert settings.group_assistant_enabled is True
    assert settings.business_mode_enabled is False
    assert settings.business_reply_enabled is False


def test_draft_reply_prompt_is_detected_and_extracts_client_text() -> None:
    result = is_draft_reply_request("Ответь на это:\nКлиент спрашивает цену")

    assert result == "Клиент спрашивает цену"


def test_draft_reply_prompt_rejects_missing_context() -> None:
    assert is_draft_reply_request("Ответь на это:") is None


@pytest.mark.asyncio
async def test_draft_reply_generation_does_not_claim_to_send_as_user() -> None:
    service = RegularAssistantService(Settings())

    messages = service.build_draft_reply_prompt("Клиент спрашивает цену")
    rendered = "\n".join(message.content for message in messages)

    assert DRAFT_REPLY_SYSTEM_PROMPT in rendered
    assert "Клиент спрашивает цену" in rendered
    assert "черновик" in rendered.lower()
    assert "отправь от имени пользователя" not in rendered.lower()


def test_group_assistant_can_be_disabled_by_env_flag() -> None:
    settings = Settings(group_assistant_enabled=False)

    assert settings.group_assistant_enabled is False
