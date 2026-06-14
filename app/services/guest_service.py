import logging
from typing import Any

logger = logging.getLogger(__name__)


class GuestService:
    async def record_guest_message(self, payload: dict[str, Any]) -> dict[str, str]:
        logger.info("guest_message_stub_recorded")
        return {"status": "stub_recorded"}

    async def answer_guest_message(self) -> None:
        raise NotImplementedError("Guest Mode переносится на Stage 2.")
