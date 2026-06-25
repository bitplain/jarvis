import pytest

from scripts.smoke_provider_settings_readiness import run_readiness


@pytest.mark.asyncio
async def test_provider_settings_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_PROVIDER_SETTINGS_READINESS"
