import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_railway_config_alignment_readiness_module():
    module_path = ROOT / "scripts" / "smoke_railway_config_alignment_readiness.py"
    assert module_path.exists()
    spec = importlib.util.spec_from_file_location(
        "smoke_railway_config_alignment_readiness",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_railway_config_alignment_readiness"] = module
    spec.loader.exec_module(module)
    return module


def test_railway_config_alignment_readiness_passes() -> None:
    module = load_railway_config_alignment_readiness_module()

    result = module.run_readiness()
    rendered = result.render_sanitized()

    assert result.verdict == "PASS_RAILWAY_CONFIG_ALIGNMENT_READINESS"
    assert "api_healthcheck_path: OK" in rendered
    assert "ready_dependency_diagnostics: OK" in rendered
    assert "predeploy_not_required: OK" in rendered
    assert "startup_migration_markers: OK" in rendered
    assert "worker_no_migrations: OK" in rendered
    assert "deploy_source_github_main: OK" in rendered


def test_railway_readiness_script_runs_directly() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_railway_readiness.py",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "PASS_RAILWAY_READINESS" in completed.stdout
