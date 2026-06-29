from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOC_PATHS = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/RAILWAY_DEPLOY.md",
    "AGENTS.md",
)


@dataclass
class RailwayConfigAlignmentReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "BLOCKED_RAILWAY_CONFIG_ALIGNMENT_READINESS"

    def render_sanitized(self) -> str:
        lines = ["Railway config alignment readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def _current_docs_text() -> str:
    return "\n\n".join(_read(path) for path in CURRENT_DOC_PATHS)


def _contains_all(text: str, expected_items: tuple[str, ...]) -> bool:
    return all(item in text for item in expected_items)


def run_readiness() -> RailwayConfigAlignmentReadinessResult:
    result = RailwayConfigAlignmentReadinessResult()
    api_config = _read("railway.api.toml")
    worker_config = _read("railway.worker.toml")
    startup_migrations = _read("app/services/startup_migrations.py")
    health_routes = _read("app/api/routes_health.py")
    docs_text = _current_docs_text()

    result.statuses["api_healthcheck_path"] = (
        "OK" if 'healthcheckPath = "/health"' in api_config else "MISSING"
    )
    result.statuses["api_plain_start_command"] = (
        "OK"
        if "uvicorn app.main:app" in api_config
        and "alembic upgrade head" not in api_config
        else "MISSING"
    )
    result.statuses["ready_dependency_diagnostics"] = (
        "OK"
        if "/ready is diagnostics/readiness" in docs_text
        and "Postgres/Redis" in docs_text
        and '@router.get("/ready")' in health_routes
        and "default_ready_probe" in health_routes
        else "MISSING"
    )
    result.statuses["docs_healthcheck_contract"] = (
        "OK"
        if _contains_all(
            docs_text,
            (
                "API healthcheck endpoint: /health",
                "Railway healthcheck endpoint: /health",
                "Healthcheck path: /health",
            ),
        )
        else "MISSING"
    )
    result.statuses["predeploy_not_required"] = (
        "OK"
        if "preDeployCommand" not in api_config
        and "Railway preDeploy migration command is intentionally not used" in docs_text
        and 'preDeployCommand = "alembic upgrade head"' not in docs_text
        else "MISSING"
    )
    result.statuses["startup_migration_markers"] = (
        "OK"
        if _contains_all(
            startup_migrations,
            (
                "startup_migrations_started",
                "startup_migrations_completed",
                "alembic",
                "upgrade",
                "head",
            ),
        )
        else "MISSING"
    )
    result.statuses["worker_no_migrations"] = (
        "OK" if "alembic" not in worker_config.lower() else "UNEXPECTED_ALEMBIC"
    )
    result.statuses["deploy_source_github_main"] = (
        "OK" if "Deploy source: GitHub main" in docs_text else "MISSING"
    )

    if all(value.startswith("OK") for value in result.statuses.values()):
        result.verdict = "PASS_RAILWAY_CONFIG_ALIGNMENT_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_RAILWAY_CONFIG_ALIGNMENT_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
