import importlib.util
import sys
from pathlib import Path


def load_update_idempotency_readiness_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "smoke_telegram_update_idempotency_readiness.py"
    )
    spec = importlib.util.spec_from_file_location(
        "smoke_telegram_update_idempotency_readiness",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_telegram_update_idempotency_readiness"] = module
    spec.loader.exec_module(module)
    return module


def test_update_idempotency_readiness_checks_guard_job_id_and_regressions() -> None:
    module = load_update_idempotency_readiness_module()

    result = module.run_readiness()
    rendered = result.render_sanitized()

    assert result.verdict == "PASS_TELEGRAM_UPDATE_IDEMPOTENCY_READINESS"
    assert "webhook_update_id_guard: OK" in rendered
    assert "dedup_redis_fail_open: OK" in rendered
    assert "stable_llm_job_id: OK" in rendered
    assert "duplicate_private_test: OK" in rendered
    assert "production_polling_guard: OK" in rendered
