def test_thinking_text_readiness_passes() -> None:
    from scripts.smoke_thinking_text_readiness import run_readiness

    result = run_readiness()

    assert result.ok is True
    rendered = result.render()
    assert "PASS_THINKING_TEXT_READINESS" in rendered
    assert "thinking_constant: OK" in rendered
    assert "private_mira_no_regular_ack_test: OK" in rendered
    assert "group_provisional_thinking_test: OK" in rendered
