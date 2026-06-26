import importlib.util
import sys
from pathlib import Path


def load_private_ingress_readiness_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "smoke_private_ingress_readiness.py"
    )
    spec = importlib.util.spec_from_file_location(
        "smoke_private_ingress_readiness",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_private_ingress_readiness"] = module
    spec.loader.exec_module(module)
    return module


def test_private_ingress_readiness_checks_start_text_fsm_and_worker_fallback() -> None:
    module = load_private_ingress_readiness_module()

    result = module.run_readiness()
    rendered = result.render_sanitized()

    assert result.verdict == "PASS_PRIVATE_INGRESS_READINESS"
    assert "start_handler_exists: OK" in rendered
    assert "private_text_handler_exists: OK" in rendered
    assert "webhook_redis_soft_failure: OK" in rendered
    assert "private_ingress_regression_tests: OK" in rendered
    assert "worker_prompt_profile_fallback: OK" in rendered
