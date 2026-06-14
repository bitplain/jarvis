import logging
from typing import Any

logger = logging.getLogger(__name__)


class BusinessService:
    async def record_business_event(
        self, update_type: str, payload: dict[str, Any]
    ) -> dict[str, str]:
        logger.info("business_event_stub_recorded", extra={"update_type": update_type})
        return {"status": "stub_recorded"}

    async def reply_as_business_user(self) -> None:
        raise NotImplementedError("Secretary Mode переносится на Stage 3.")
