import pytest

from scripts.smoke_helpdesk_vacation_readiness import run_readiness


@pytest.mark.asyncio
async def test_helpdesk_vacation_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_HELPDESK_VACATION_READINESS"
