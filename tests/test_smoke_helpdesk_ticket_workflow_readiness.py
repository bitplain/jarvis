import pytest

from scripts.smoke_helpdesk_ticket_workflow_readiness import run_readiness


@pytest.mark.asyncio
async def test_helpdesk_ticket_workflow_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_HELPDESK_TICKET_WORKFLOW_READINESS"
