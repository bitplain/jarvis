# Stage 4F Container CLI Docs Report

Verdict: `PASS_STAGE_4F_CONTAINER_CLI_DOCS_READY`

## Цель

Зафиксировать локальное правило для этой Mac-машины: отсутствие Docker Desktop socket `~/.docker/run/docker.sock` само по себе не означает, что контейнерные проверки невозможны.

## Что изменено

- `AGENTS.md` теперь требует сначала проверять Apple Container CLI:

```bash
command -v container
container --help
```

- `README.md` и `docs/RAILWAY_DEPLOY.md` объясняют, что primary local container runtime can be Apple Container CLI.
- Docker Compose checks are optional when Docker daemon is unavailable.
- Railway/live checks are the deployment source of truth для production readiness.
- `scripts/smoke_railway_readiness.py` показывает non-failing статусы локального runtime:
  - `local_docker_socket`;
  - `local_apple_container_cli`.

## Ограничения

- Если задача требует именно Docker Compose, отсутствие Docker daemon нужно честно указывать как Docker Compose limitation.
- Агент не должен пытаться запускать Docker Desktop.
- Railway Variables не меняются.
- В `main` напрямую не пушить.

## Проверки

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_provider_settings_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
```
