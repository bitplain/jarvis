import importlib.util
import sys
from pathlib import Path


def load_group_stability_readiness_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "smoke_group_stability_readiness.py"
    )
    spec = importlib.util.spec_from_file_location("smoke_group_stability_readiness", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_group_stability_readiness"] = module
    spec.loader.exec_module(module)
    return module


def test_group_stability_readiness_checks_guards_tests_and_report() -> None:
    module = load_group_stability_readiness_module()

    result = module.run_readiness()
    rendered = result.render_sanitized()

    assert result.verdict == "PASS_GROUP_STABILITY_READINESS"
    assert "group_unauthorized_silent: OK" in rendered
    assert "group_final_delivery_guard: OK" in rendered
    assert "group_message_not_modified_noop: OK" in rendered
    assert "group_final_dedup_tests: OK" in rendered
