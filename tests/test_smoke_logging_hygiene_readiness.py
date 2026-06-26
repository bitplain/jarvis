import importlib.util
import sys
from pathlib import Path


def load_logging_hygiene_readiness_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "smoke_logging_hygiene_readiness.py"
    )
    spec = importlib.util.spec_from_file_location(
        "smoke_logging_hygiene_readiness",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_logging_hygiene_readiness"] = module
    spec.loader.exec_module(module)
    return module


def test_logging_hygiene_readiness_checks_redaction_logging_and_docs() -> None:
    module = load_logging_hygiene_readiness_module()

    result = module.run_readiness()
    rendered = result.render_sanitized()

    assert result.verdict == "PASS_LOGGING_HYGIENE_READINESS"
    assert "central_redactor: OK" in rendered
    assert "stdout_stderr_split: OK" in rendered
    assert "http_client_info_quiet: OK" in rendered
    assert "worker_logging_hook: OK" in rendered
