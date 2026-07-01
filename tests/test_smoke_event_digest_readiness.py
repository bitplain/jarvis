import pytest

from scripts.smoke_event_digest_readiness import run_readiness


@pytest.mark.asyncio
async def test_event_digest_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_EVENT_DIGEST_READINESS"
