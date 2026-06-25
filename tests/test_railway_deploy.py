import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_railway_deploy_doc_exists_and_readme_links_to_it() -> None:
    doc = ROOT / "docs" / "RAILWAY_DEPLOY.md"

    assert doc.exists()
    assert "docs/RAILWAY_DEPLOY.md" in read("README.md")


def test_env_example_contains_railway_variables_without_secrets() -> None:
    env_example = read(".env.example")
    required = [
        "APP_ENV=production",
        "APP_HOST=0.0.0.0",
        "APP_PORT=8000",
        "PUBLIC_BASE_URL=https://your-service.up.railway.app",
        "TELEGRAM_BOT_TOKEN=",
        "TELEGRAM_BOT_USERNAME=",
        "TELEGRAM_WEBHOOK_SECRET=",
        "ADMIN_TELEGRAM_IDS=",
        "ADMIN_API_TOKEN=",
        "DATABASE_URL=",
        "REDIS_URL=",
        "LLM_PRIMARY_PROVIDER=yandex",
        "LLM_FALLBACK_PROVIDER=openrouter",
        "YANDEX_AI_BASE_URL=",
        "YANDEX_AI_API_KEY=",
        "YANDEX_AI_FOLDER_ID=",
        "YANDEX_AI_MODEL=",
        "OPENROUTER_BASE_URL=",
        "OPENROUTER_API_KEY=",
        "OPENROUTER_MODEL=",
        "GUEST_MODE_ENABLED=true",
        "GUEST_MODE_ADMIN_ONLY=true",
        "STREAMING_ENABLED=true",
        "STREAMING_PRIVATE_DRAFT_ENABLED=true",
        "STREAMING_GROUP_FALLBACK_ENABLED=true",
        "STREAMING_DRAFT_UPDATE_INTERVAL_MS=800",
        "STREAMING_GROUP_EDIT_INTERVAL_MS=1000",
        "STREAMING_MIN_CHARS_DELTA=120",
        "STREAMING_MAX_DRAFT_SECONDS=25",
        "STREAMING_SEND_CHAT_ACTION_INTERVAL_SECONDS=4",
        "STREAMING_DRAFT_RAW_API_FALLBACK=true",
    ]

    for item in required:
        assert item in env_example
    assert "bot123" not in env_example
    assert "Authorization" + ": Bearer " not in env_example


def test_railway_configs_and_documented_start_commands_exist() -> None:
    api_config = read("railway.api.toml")
    worker_config = read("railway.worker.toml")
    deploy_doc = read("docs/RAILWAY_DEPLOY.md")

    assert (ROOT / "railway.api.toml").exists()
    assert (ROOT / "railway.worker.toml").exists()
    assert "python -m uvicorn app.main:app" in api_config
    assert "--port ${PORT:-8080}" in api_config
    assert 'preDeployCommand = "alembic upgrade head"' in api_config
    assert 'healthcheckPath = "/health"' in api_config
    assert "arq app.workers.arq_settings.WorkerSettings" in worker_config
    assert "alembic" not in worker_config.lower()
    assert "railway.api.toml" in deploy_doc
    assert "railway.worker.toml" in deploy_doc
    assert "alembic upgrade head" in deploy_doc


def test_railway_doc_captures_live_deploy_rules_and_failures() -> None:
    deploy_doc = read("docs/RAILWAY_DEPLOY.md")
    required = [
        "DATABASE_URL=${{Postgres.DATABASE_URL}}",
        "REDIS_URL=${{Redis.REDIS_URL}}",
        "PYTHONPATH=/app python scripts/smoke_llm.py",
        "value only, no KEY=value",
        "$PORT is not a valid integer",
        "provider_not_configured",
        'relation "messages" does not exist',
        "Railway services",
        "Required API variables",
        "Required worker variables",
    ]

    for item in required:
        assert item in deploy_doc


def test_railway_smoke_and_webhook_scripts_exist() -> None:
    assert (ROOT / "scripts" / "smoke_railway_readiness.py").exists()
    assert (ROOT / "scripts" / "setup_telegram_webhook.py").exists()


def test_env_is_not_tracked() -> None:
    tracked_env = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked_env.stdout.strip() == ""
    assert ".env" in read(".gitignore")


def test_production_docs_keep_polling_local_only() -> None:
    deploy_doc = read("docs/RAILWAY_DEPLOY.md")

    assert "webhook" in deploy_doc.lower()
    assert "polling только для local" in deploy_doc
    assert "scripts/run_polling.py" not in deploy_doc
