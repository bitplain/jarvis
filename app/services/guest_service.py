import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import GuestMessageRecord, GuestMessageStatus, utcnow
from app.llm.base import LLMProvider, LLMProviderError
from app.llm.factory import build_llm_provider
from app.llm.types import LLMMessage

logger = logging.getLogger(__name__)

GUEST_DISABLED_MESSAGE = "Guest Mode сейчас выключен."
GUEST_EMPTY_TEXT_MESSAGE = (
    "Я получил вызов, но не вижу текста запроса. Напиши задачу после упоминания бота."
)
GUEST_OWNER_ONLY_MESSAGE = "Guest Mode пока доступен только владельцу бота."
GUEST_LLM_ERROR_MESSAGE = (
    "Не смог обработать запрос: временная ошибка модели. Попробуй ещё раз позже."
)


@dataclass(frozen=True)
class GuestRequest:
    telegram_update_id: int | None
    guest_query_id: str | None
    caller_user_id: int | None
    caller_chat_id: int | None
    request_text: str
    replied_text: str | None = None


@dataclass
class GuestMessageEvent:
    telegram_update_id: int | None
    guest_query_id_hash: str | None
    caller_user_id_hash: str | None
    caller_chat_id_hash: str | None
    request_text: str
    replied_text: str | None
    response_text: str | None
    provider: str | None
    model: str | None
    status: str
    error_code: str | None


@dataclass(frozen=True)
class GuestServiceResult:
    text: str | None
    status: str
    should_answer: bool = True


class GuestMessageRepositoryProtocol(Protocol):
    async def create_received(self, request: GuestRequest) -> Any:
        ...

    async def mark_answered(
        self,
        record: Any,
        *,
        response_text: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        ...

    async def mark_failed(self, record: Any, *, response_text: str, error_code: str) -> None:
        ...

    async def mark_ignored(
        self,
        record: Any,
        *,
        response_text: str | None = None,
        error_code: str | None = None,
    ) -> None:
        ...


def hash_identifier(value: str | int | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def normalize_guest_text(text: str, bot_username: str) -> str:
    normalized = text.strip()
    username = bot_username.strip().lstrip("@")
    if username:
        normalized = re.sub(
            rf"^@{re.escape(username)}\b[:,\s-]*",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized.strip()


class GuestMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_received(self, request: GuestRequest) -> GuestMessageRecord:
        record = GuestMessageRecord(
            payload={},
            telegram_update_id=request.telegram_update_id,
            guest_query_id_hash=hash_identifier(request.guest_query_id),
            caller_user_id_hash=hash_identifier(request.caller_user_id),
            caller_chat_id_hash=hash_identifier(request.caller_chat_id),
            request_text=request.request_text,
            replied_text=request.replied_text,
            status=GuestMessageStatus.RECEIVED,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def mark_answered(
        self,
        record: GuestMessageRecord,
        *,
        response_text: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        record.response_text = response_text
        record.provider = provider
        record.model = model
        record.status = GuestMessageStatus.ANSWERED
        record.answered_at = utcnow()
        await self.session.commit()
        await self.session.refresh(record)

    async def mark_failed(
        self,
        record: GuestMessageRecord,
        *,
        response_text: str,
        error_code: str,
    ) -> None:
        record.response_text = response_text
        record.status = GuestMessageStatus.FAILED
        record.error_code = error_code
        record.answered_at = utcnow()
        await self.session.commit()
        await self.session.refresh(record)

    async def mark_ignored(
        self,
        record: GuestMessageRecord,
        *,
        response_text: str | None = None,
        error_code: str | None = None,
    ) -> None:
        record.response_text = response_text
        record.status = GuestMessageStatus.IGNORED
        record.error_code = error_code
        record.answered_at = utcnow() if response_text else None
        await self.session.commit()
        await self.session.refresh(record)


class InMemoryGuestMessageRepository:
    def __init__(self) -> None:
        self.records: list[GuestMessageEvent] = []

    async def create_received(self, request: GuestRequest) -> GuestMessageEvent:
        record = GuestMessageEvent(
            telegram_update_id=request.telegram_update_id,
            guest_query_id_hash=hash_identifier(request.guest_query_id),
            caller_user_id_hash=hash_identifier(request.caller_user_id),
            caller_chat_id_hash=hash_identifier(request.caller_chat_id),
            request_text=request.request_text,
            replied_text=request.replied_text,
            response_text=None,
            provider=None,
            model=None,
            status=GuestMessageStatus.RECEIVED.value,
            error_code=None,
        )
        self.records.append(record)
        return record

    async def mark_answered(
        self,
        record: GuestMessageEvent,
        *,
        response_text: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        record.response_text = response_text
        record.provider = provider
        record.model = model
        record.status = GuestMessageStatus.ANSWERED.value

    async def mark_failed(
        self,
        record: GuestMessageEvent,
        *,
        response_text: str,
        error_code: str,
    ) -> None:
        record.response_text = response_text
        record.status = GuestMessageStatus.FAILED.value
        record.error_code = error_code

    async def mark_ignored(
        self,
        record: GuestMessageEvent,
        *,
        response_text: str | None = None,
        error_code: str | None = None,
    ) -> None:
        record.response_text = response_text
        record.status = GuestMessageStatus.IGNORED.value
        record.error_code = error_code


class GuestService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repository: GuestMessageRepositoryProtocol | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or InMemoryGuestMessageRepository()
        self.provider = provider or build_llm_provider(self.settings)

    async def record_guest_message(self, payload: dict[str, Any]) -> dict[str, str]:
        logger.info("guest_message_legacy_stub_recorded")
        del payload
        return {"status": "stub_recorded"}

    async def handle(self, request: GuestRequest) -> GuestServiceResult:
        record = await self.repository.create_received(request)
        if not request.guest_query_id:
            await self.repository.mark_ignored(record, error_code="missing_guest_query_id")
            return GuestServiceResult(
                text=None,
                status=GuestMessageStatus.IGNORED.value,
                should_answer=False,
            )
        if not self.settings.guest_mode_enabled:
            await self.repository.mark_ignored(
                record,
                response_text=GUEST_DISABLED_MESSAGE,
                error_code="guest_mode_disabled",
            )
            return GuestServiceResult(
                text=GUEST_DISABLED_MESSAGE,
                status=GuestMessageStatus.IGNORED.value,
            )
        if (
            self.settings.guest_mode_admin_only
            and request.caller_user_id not in self.settings.admin_ids
        ):
            await self.repository.mark_ignored(
                record,
                response_text=GUEST_OWNER_ONLY_MESSAGE,
                error_code="guest_caller_not_allowed",
            )
            return GuestServiceResult(
                text=GUEST_OWNER_ONLY_MESSAGE,
                status=GuestMessageStatus.IGNORED.value,
            )

        normalized_text = normalize_guest_text(
            request.request_text,
            self.settings.telegram_bot_username,
        )
        if not normalized_text:
            await self.repository.mark_answered(record, response_text=GUEST_EMPTY_TEXT_MESSAGE)
            return GuestServiceResult(
                text=GUEST_EMPTY_TEXT_MESSAGE,
                status=GuestMessageStatus.ANSWERED.value,
            )

        messages = self.build_prompt(normalized_text, request.replied_text)
        try:
            response = await self.provider.complete(
                messages,
                max_tokens=self.settings.guest_mode_max_tokens,
            )
        except LLMProviderError as exc:
            logger.warning("guest_llm_failed", extra={"error_code": exc.code})
            await self.repository.mark_failed(
                record,
                response_text=GUEST_LLM_ERROR_MESSAGE,
                error_code=exc.code,
            )
            return GuestServiceResult(
                text=GUEST_LLM_ERROR_MESSAGE,
                status=GuestMessageStatus.FAILED.value,
            )
        except Exception as exc:
            logger.warning(
                "guest_llm_unexpected_error",
                extra={"error_type": type(exc).__name__},
            )
            await self.repository.mark_failed(
                record,
                response_text=GUEST_LLM_ERROR_MESSAGE,
                error_code="unexpected_error",
            )
            return GuestServiceResult(
                text=GUEST_LLM_ERROR_MESSAGE,
                status=GuestMessageStatus.FAILED.value,
            )

        response_text = response.content.strip() or GUEST_LLM_ERROR_MESSAGE
        if response_text == GUEST_LLM_ERROR_MESSAGE:
            await self.repository.mark_failed(
                record,
                response_text=response_text,
                error_code="empty_response",
            )
            return GuestServiceResult(
                text=response_text,
                status=GuestMessageStatus.FAILED.value,
            )
        await self.repository.mark_answered(
            record,
            response_text=response_text,
            provider=response.provider,
            model=response.model,
        )
        return GuestServiceResult(text=response_text, status=GuestMessageStatus.ANSWERED.value)

    def build_prompt(self, request_text: str, replied_text: str | None) -> list[LLMMessage]:
        system_prompt = (
            "Ты Jarvis в Telegram Guest Mode. Отвечай только на русском. "
            "Отвечай кратко и по делу. Не используй память личного чата, историю чужого чата, "
            "список участников или постоянную память. Учитывай только текст guest-вызова "
            "и сообщение, на которое был reply, если оно передано. Если пользователь просит "
            "\"это\", \"выше\" или \"предыдущее\", а replied message недоступен, честно скажи, "
            "что контекста не видно."
        )
        if replied_text:
            user_prompt = (
                "Текст guest-вызова:\n"
                f"{request_text}\n\n"
                "Сообщение, на которое был reply:\n"
                f"{replied_text}"
            )
        else:
            user_prompt = (
                "Текст guest-вызова:\n"
                f"{request_text}\n\n"
                "Replied message недоступен: если запрос ссылается на это, выше или предыдущее, "
                "скажи, что контекста не видно."
            )
        return [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]
