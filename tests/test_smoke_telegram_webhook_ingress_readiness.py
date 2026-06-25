import importlib.util
import sys
from pathlib import Path


def load_webhook_ingress_readiness_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "smoke_telegram_webhook_ingress_readiness.py"
    )
    spec = importlib.util.spec_from_file_location(
        "smoke_telegram_webhook_ingress_readiness",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_telegram_webhook_ingress_readiness"] = module
    spec.loader.exec_module(module)
    return module


def test_webhook_ingress_readiness_checks_route_tests_and_production_guard() -> None:
    module = load_webhook_ingress_readiness_module()

    result = module.run_readiness()
    rendered = result.render_sanitized()

    assert result.verdict == "PASS_TELEGRAM_WEBHOOK_INGRESS_READINESS"
    assert "webhook_route_code: OK" in rendered
    assert "private_authorized_ingress_test: OK" in rendered
    assert "group_unauthorized_silent_ingress_test: OK" in rendered
    assert "production_polling_readiness_guard: OK" in rendered
