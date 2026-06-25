import pytest

from scripts.smoke_access_settings_readiness import run_readiness


@pytest.mark.asyncio
async def test_access_settings_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_ACCESS_SETTINGS_READINESS"
