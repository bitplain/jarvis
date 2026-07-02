import pytest

from scripts.smoke_whoop_oauth_sync_readiness import run_readiness


@pytest.mark.asyncio
async def test_whoop_oauth_sync_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_WHOOP_OAUTH_SYNC_READINESS"
