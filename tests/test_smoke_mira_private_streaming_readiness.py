from scripts.smoke_mira_private_streaming_readiness import run_readiness


def test_mira_private_streaming_readiness_passes() -> None:
    result = run_readiness()

    assert result.verdict == "PASS_MIRA_PRIVATE_STREAMING_READINESS"
    rendered = result.render_sanitized()
    assert "feature_flag: OK" in rendered
    assert "draft_api_wrappers: OK" in rendered
    assert "private_sink_rich_thinking: OK" in rendered
