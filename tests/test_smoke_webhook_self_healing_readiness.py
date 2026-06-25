import importlib.util
import sys
from pathlib import Path


def load_webhook_self_healing_readiness_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "smoke_webhook_self_healing_readiness.py"
    )
    spec = importlib.util.spec_from_file_location(
        "smoke_webhook_self_healing_readiness",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_webhook_self_healing_readiness"] = module
    spec.loader.exec_module(module)
    return module


def test_webhook_self_healing_readiness_checks_startup_tests_and_docs() -> None:
    module = load_webhook_self_healing_readiness_module()

    result = module.run_readiness()
    rendered = result.render_sanitized()

    assert result.verdict == "PASS_WEBHOOK_SELF_HEALING_READINESS"
    assert "production_startup_hook: OK" in rendered
    assert "non_fatal_failures: OK" in rendered
    assert "worker_no_webhook_setup: OK" in rendered
    assert "delete_webhook_production_guard: OK" in rendered
