from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RailwayReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_RAILWAY_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4B Railway readiness sanitized result:"]
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


def run_readiness() -> RailwayReadinessResult:
    result = RailwayReadinessResult()
    env_example = _read(".env.example")
    deploy_doc = _read("docs/RAILWAY_DEPLOY.md")
    api_config = _read("railway.api.toml")
    worker_config = _read("railway.worker.toml")

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
    result.statuses["api_start_command"] = (
        "OK"
        if "uvicorn app.main:app" in api_config and "${PORT:-8000}" in api_config
        else "MISSING"
    )
    result.statuses["worker_start_command"] = (
        "OK" if "arq app.workers.arq_settings.WorkerSettings" in worker_config else "MISSING"
    )
    result.statuses["railway_doc"] = "OK" if deploy_doc else "MISSING"
    result.statuses["webhook_script"] = (
        "OK" if (ROOT / "scripts" / "setup_telegram_webhook.py").exists() else "MISSING"
    )
    result.statuses["polling_production"] = (
        "OK local-only" if "polling только для local" in deploy_doc else "MISSING"
    )

    if all(value.startswith("OK") for value in result.statuses.values()):
        result.verdict = "PASS_RAILWAY_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_RAILWAY_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
