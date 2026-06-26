import pytest

from scripts.smoke_prompt_profiles_readiness import run_readiness


@pytest.mark.asyncio
async def test_prompt_profiles_readiness_passes() -> None:
    result = await run_readiness()

    assert result.verdict == "PASS_PROMPT_PROFILES_RAW_EDITOR_READINESS"
