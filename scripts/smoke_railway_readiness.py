from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCKER_SOCKET = Path.home() / ".docker" / "run" / "docker.sock"


@dataclass
class RailwayReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_RAILWAY_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4C Railway readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def _contains(path: str, expected: str) -> bool:
    return expected in _read(path)


def detect_local_container_runtime(
    *,
    docker_socket: Path = DEFAULT_DOCKER_SOCKET,
    container_path: str | None = None,
) -> dict[str, str]:
    resolved_container = container_path if container_path is not None else which("container")
    docker_status = (
        "OK Docker Desktop socket available"
        if docker_socket.exists()
        else "WARN Docker Desktop socket missing"
    )
    container_status = (
        "OK Apple Container CLI available"
        if resolved_container
        else "WARN Apple Container CLI unavailable"
    )
    return {
        "local_docker_socket": docker_status,
        "local_apple_container_cli": container_status,
    }


def _status_allows_pass(status: str) -> bool:
    return status.startswith(("OK", "WARN"))


def run_readiness(
    *,
    local_container_statuses: Mapping[str, str] | None = None,
) -> RailwayReadinessResult:
    result = RailwayReadinessResult()
    env_example = _read(".env.example")
    deploy_doc = _read("docs/RAILWAY_DEPLOY.md")
    api_config = _read("railway.api.toml")
    worker_config = _read("railway.worker.toml")
    startup_migrations = _read("app/services/startup_migrations.py")
    result.statuses.update(local_container_statuses or detect_local_container_runtime())

    required_env = [
        "APP_ENV=production",
        "PUBLIC_BASE_URL=https://your-service.up.railway.app",
        "DATABASE_URL=",
        "REDIS_URL=",
        "TELEGRAM_BOT_TOKEN=",
        "TELEGRAM_BOT_USERNAME=",
        "TELEGRAM_WEBHOOK_SECRET=",
        "ADMIN_TELEGRAM_IDS=",
        "ADMIN_API_TOKEN=",
        "STREAMING_ENABLED=true",
        "STREAMING_PRIVATE_DRAFT_ENABLED=true",
        "STREAMING_GROUP_FALLBACK_ENABLED=true",
    ]
    missing_env = [item.split("=", 1)[0] for item in required_env if item not in env_example]
    result.statuses["env_example"] = "OK" if not missing_env else "MISSING " + ",".join(missing_env)
    result.statuses["database_url"] = (
        "OK DATABASE_URL documented" if "DATABASE_URL=" in env_example else "MISSING"
    )
    result.statuses["redis_url"] = (
        "OK REDIS_URL documented" if "REDIS_URL=" in env_example else "MISSING"
    )
    result.statuses["telegram_env"] = (
        "OK names documented"
        if all(name in env_example for name in ["TELEGRAM_BOT_TOKEN=", "TELEGRAM_WEBHOOK_SECRET="])
        else "MISSING"
    )
    result.statuses["health_ready"] = (
        "OK /health and /ready documented"
        if "/health" in deploy_doc and "/ready" in deploy_doc
        else "MISSING"
    )
    result.statuses["api_config_exists"] = "OK" if api_config else "MISSING"
    result.statuses["worker_config_exists"] = "OK" if worker_config else "MISSING"
    result.statuses["api_start_command"] = (
        "OK"
        if "python -m uvicorn app.main:app" in api_config and "${PORT:-8080}" in api_config
        else "MISSING"
    )
    result.statuses["api_start_migration"] = (
        "OK"
        if "alembic upgrade head && python -m uvicorn app.main:app" in api_config
        else "MISSING"
    )
    result.statuses["api_startup_migration_guard"] = (
        "OK"
        if "startup_migrations_started" in startup_migrations
        and "alembic" in startup_migrations
        and "upgrade" in startup_migrations
        and "head" in startup_migrations
        else "MISSING"
    )
    result.statuses["api_predeploy_migration"] = (
        "OK" if 'preDeployCommand = "alembic upgrade head"' in api_config else "MISSING"
    )
    result.statuses["worker_start_command"] = (
        "OK" if "arq app.workers.arq_settings.WorkerSettings" in worker_config else "MISSING"
    )
    result.statuses["worker_no_alembic"] = (
        "OK" if "alembic" not in worker_config.lower() else "UNEXPECTED_ALEMBIC"
    )
    result.statuses["railway_doc"] = "OK" if deploy_doc else "MISSING"
    required_doc_items = [
        "DATABASE_URL=${{Postgres.DATABASE_URL}}",
        "REDIS_URL=${{Redis.REDIS_URL}}",
        "PYTHONPATH=/app python scripts/smoke_llm.py",
        "value only, no KEY=value",
        "$PORT is not a valid integer",
        "provider_not_configured",
        'relation "messages" does not exist',
        "alembic upgrade head && python -m uvicorn app.main:app",
        "Railway UI Start Command",
        "startup migration guard",
        "Apple Container CLI",
        "Docker Compose checks are optional",
        "Railway/live checks",
    ]
    missing_doc_items = [item for item in required_doc_items if item not in deploy_doc]
    result.statuses["railway_doc_stage_4c"] = (
        "OK" if not missing_doc_items else "MISSING " + ",".join(missing_doc_items)
    )
    result.statuses["webhook_script"] = (
        "OK" if (ROOT / "scripts" / "setup_telegram_webhook.py").exists() else "MISSING"
    )
    result.statuses["polling_production"] = (
        "OK local-only"
        if "Polling разрешён только для local/Mac smoke" in deploy_doc
        else "MISSING"
    )

    if all(_status_allows_pass(value) for value in result.statuses.values()):
        result.verdict = "PASS_RAILWAY_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_RAILWAY_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
