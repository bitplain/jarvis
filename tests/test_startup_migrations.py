import pytest

from app.core.config import Settings
from app.main import create_app
from app.services.startup_migrations import run_startup_migrations, should_run_startup_migrations


def test_startup_migrations_enabled_for_production_by_default() -> None:
    assert should_run_startup_migrations(Settings(app_env="production")) is True


def test_startup_migrations_disabled_for_local_unit_tests_by_default() -> None:
    assert should_run_startup_migrations(Settings(app_env="local")) is False


@pytest.mark.asyncio
async def test_api_startup_runs_migrations_before_serving_in_production() -> None:
    calls: list[str] = []

    async def fake_runner() -> None:
        calls.append("migrated")

    app = create_app(
        settings=Settings(app_env="production"),
        startup_migration_runner=fake_runner,
    )

    async with app.router.lifespan_context(app):
        pass

    assert calls == ["migrated"]


@pytest.mark.asyncio
async def test_api_startup_does_not_run_migrations_for_local_tests() -> None:
    calls: list[str] = []

    async def fake_runner() -> None:
        calls.append("migrated")

    app = create_app(
        settings=Settings(app_env="local"),
        startup_migration_runner=fake_runner,
    )

    async with app.router.lifespan_context(app):
        pass

    assert calls == []


@pytest.mark.asyncio
async def test_api_startup_raises_when_migration_fails() -> None:
    async def failing_runner() -> None:
        raise RuntimeError("migration failed")

    app = create_app(
        settings=Settings(app_env="production"),
        startup_migration_runner=failing_runner,
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        async with app.router.lifespan_context(app):
            pass


def test_run_startup_migrations_invokes_alembic_upgrade_head() -> None:
    calls: list[dict[str, object]] = []

    def fake_run(*args: object, **kwargs: object) -> object:
        calls.append({"args": args, "kwargs": kwargs})
        return object()

    run_startup_migrations(subprocess_run=fake_run)

    assert calls[0]["args"][0] == ["alembic", "upgrade", "head"]
    assert calls[0]["kwargs"]["check"] is True


def test_worker_does_not_import_startup_migration_guard() -> None:
    source = open("app/workers/jobs.py", encoding="utf-8").read()

    assert "startup_migrations" not in source
