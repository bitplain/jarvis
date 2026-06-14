from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.db.models import MessageRole
from app.llm.base import LLMProvider, LLMProviderError
from app.llm.factory import build_llm_provider
from app.llm.types import LLMMessage
from app.services.memory_service import MemoryService

FORWARDED_ACTIONS_TEXT = (
    "Я сохранил пересланное сообщение как контекст.\n"
    "Что сделать дальше?\n"
    "/summary — кратко пересказать\n"
    "/draft_reply — подготовить ответ\n"
    "/translate — перевести нормально\n"
    "/factcheck — проверить факты"
)
DRAFT_REPLY_SYSTEM_PROMPT = (
    "Ты Jarvis в Regular Assistant Mode. Подготовь черновик ответа на русском языке. "
    "Не утверждай, что отправил сообщение от имени пользователя. "
    "Не обещай действий, которых не можешь выполнить. "
    "Если контекста недостаточно, попроси уточнение."
)
DRAFT_REPLY_EMPTY_CONTEXT = (
    "Не вижу текста, на который нужно ответить. Пришли так:\n"
    "Ответь на это:\n"
    "<текст клиента>"
)
REGULAR_LLM_ERROR_MESSAGE = "Не смог подготовить черновик: временная ошибка модели."


@dataclass(frozen=True)
class RegularAssistantResult:
    text: str
    status: str


def is_draft_reply_request(text: str | None) -> str | None:
    if not text:
        return None
    marker = "ответь на это:"
    stripped = text.strip()
    if not stripped.lower().startswith(marker):
        return None
    body = stripped[len(marker) :].strip()
    return body or None


def build_forwarded_context_text(text: str) -> str:
    return (
        "Пересланное сообщение для Regular Assistant Mode.\n"
        "Jarvis не видит личный чат пользователя и работает только с переданным текстом.\n\n"
        f"{text.strip()}"
    )


class RegularAssistantService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        memory: MemoryService | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.memory = memory
        self.provider = provider or build_llm_provider(self.settings)

    async def handle_forwarded_message(
        self,
        *,
        chat_id: int,
        user_id: int,
        telegram_message_id: int,
        text: str,
    ) -> RegularAssistantResult:
        if self.memory is not None:
            await self.memory.add_message(
                chat_id=chat_id,
                user_id=user_id,
                role=MessageRole.USER,
                text=build_forwarded_context_text(text),
                telegram_message_id=telegram_message_id,
            )
        return RegularAssistantResult(text=FORWARDED_ACTIONS_TEXT, status="forwarded_saved")

    async def handle_draft_reply(
        self,
        *,
        chat_id: int,
        user_id: int,
        telegram_message_id: int,
        client_text: str,
    ) -> RegularAssistantResult:
        if self.memory is not None:
            await self.memory.add_message(
                chat_id=chat_id,
                user_id=user_id,
                role=MessageRole.USER,
                text=f"Запрос на черновик ответа:\n{client_text}",
                telegram_message_id=telegram_message_id,
            )
        try:
            response = await self.provider.complete(self.build_draft_reply_prompt(client_text))
        except LLMProviderError:
            return RegularAssistantResult(text=REGULAR_LLM_ERROR_MESSAGE, status="failed")
        response_text = response.content.strip() or REGULAR_LLM_ERROR_MESSAGE
        return RegularAssistantResult(text=response_text, status="answered")

    def build_draft_reply_prompt(self, client_text: str) -> list[LLMMessage]:
        return [
            LLMMessage(role="system", content=DRAFT_REPLY_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(
                    "Подготовь черновик ответа, который пользователь сам скопирует и отправит.\n"
                    "Текст клиента:\n"
                    f"{client_text}"
                ),
            ),
        ]
