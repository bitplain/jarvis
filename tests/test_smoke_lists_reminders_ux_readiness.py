import pytest

from scripts.smoke_lists_reminders_ux_readiness import run_readiness


@pytest.mark.asyncio
async def test_lists_reminders_ux_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_LISTS_REMINDERS_UX_READINESS"
