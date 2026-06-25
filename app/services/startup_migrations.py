import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from app.core.config import Settings

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def should_run_startup_migrations(settings: Settings) -> bool:
    if settings.startup_migrations_enabled is not None:
        return settings.startup_migrations_enabled
    return settings.app_env.lower() in {"production", "railway"}


def run_startup_migrations(
    *,
    project_root: Path | None = None,
    subprocess_run: Callable[..., object] = subprocess.run,
) -> None:
    root = project_root or PROJECT_ROOT
    logger.info("startup_migrations_started")
    try:
        subprocess_run(
            ["alembic", "upgrade", "head"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception as exc:
        logger.exception(
            "startup_migrations_failed",
            extra={"error_type": type(exc).__name__},
        )
        raise
    logger.info("startup_migrations_completed")
