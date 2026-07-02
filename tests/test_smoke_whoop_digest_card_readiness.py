import pytest

from scripts.smoke_whoop_digest_card_readiness import run_readiness


@pytest.mark.asyncio
async def test_whoop_digest_card_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_WHOOP_DIGEST_CARD_READINESS"
