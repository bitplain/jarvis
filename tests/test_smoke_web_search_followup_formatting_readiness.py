import pytest

from scripts.smoke_web_search_followup_formatting_readiness import run_readiness


@pytest.mark.asyncio
async def test_web_search_followup_formatting_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_WEB_SEARCH_FOLLOWUP_FORMATTING_READINESS"
