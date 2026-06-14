import pytest

from app.services.business_service import BusinessService
from app.services.guest_service import GuestService


@pytest.mark.asyncio
async def test_guest_service_records_noop_stub() -> None:
    service = GuestService()
    result = await service.record_guest_message({"guest_query_id": "g1"})

    assert result["status"] == "stub_recorded"


@pytest.mark.asyncio
async def test_business_service_records_noop_stub() -> None:
    service = BusinessService()
    result = await service.record_business_event("business_message", {"id": 1})

    assert result["status"] == "stub_recorded"
