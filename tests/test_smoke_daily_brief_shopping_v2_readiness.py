import pytest

from scripts.smoke_daily_brief_shopping_v2_readiness import run_readiness


@pytest.mark.asyncio
async def test_daily_brief_shopping_v2_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_DAILY_BRIEF_SHOPPING_V2_READINESS"
