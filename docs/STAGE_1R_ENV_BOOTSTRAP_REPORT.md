# Stage 1R ENV Bootstrap Report

## Стартовая точка

- Commit: `870f443 Stage 1: bootstrap Jarvis Telegram AI bot`.
- GitHub repo не создавался.
- Push в GitHub не выполнялся.
- Remote AGENTS sync: `N/A until server/live paths exist`.

## Что добавлено

- `scripts/bootstrap_real_env.py` — безопасный bootstrap/fix `.env` с dry-run по умолчанию и явным `--apply`.
- `tests/test_bootstrap_real_env.py` — проверки dry-run/apply, генерации безопасного webhook secret и sanitized output.
- `docs/STAGE_1R_ENV_BOOTSTRAP.md` — инструкция по повторному запуску bootstrap и ручному `/start`.
- `.env.example`, `README.md`, `docs/STAGE_1_REPORT.md`, `AGENTS.md` — обновлены без реальных секретов.

## Sanitized env status после `--apply`

- `TELEGRAM_BOT_TOKEN`: `<set>`
- `TELEGRAM_BOT_USERNAME`: `<set>`
- `TELEGRAM_WEBHOOK_SECRET`: `<set>`
- `ADMIN_API_TOKEN`: `<set>`
- `ADMIN_TELEGRAM_IDS`: `<missing>`
- `YANDEX_AI_BASE_URL`: `<set>`
- `YANDEX_AI_API_KEY`: `<set>`
- `YANDEX_AI_MODEL`: `<set>`
- `OPENROUTER_API_KEY`: `<set>`
- `OPENROUTER_MODEL`: `<set>`

## Сгенерировано локально

- `TELEGRAM_WEBHOOK_SECRET`
- `ADMIN_API_TOKEN`

Значения не выводились и не добавлялись в git.

## Получено или проверено через API

- `TELEGRAM_BOT_USERNAME`: уже `<set>` в `.env` на момент Stage 1R-ENV проверки.
- Yandex chat completion smoke: `chat_smoke_ok`.
- OpenRouter model discovery: `OPENROUTER_MODEL` стал `<set>`.
- OpenRouter chat completion smoke: sanitized `http_400`, provider пока не считается подтверждённым real runtime smoke.

## Заблокировано

- `ADMIN_TELEGRAM_IDS`: `<missing>`.
- Telegram `getUpdates`: sanitized `http_409`, причина: webhook уже установлен, поэтому polling API конфликтует с webhook.

Скрипт не удалял webhook автоматически. Для этого требуется явный флаг:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
```

## Выполненные команды

```bash
git status --short
uv run --python 3.12 --extra dev pytest -q tests/test_bootstrap_real_env.py
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

## Результаты проверок

- `ruff check .` — PASS.
- `mypy app` — PASS, `47 source files`.
- `pytest -q` — PASS, `18 passed`.
- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose ps` — `api`, `postgres`, `redis` healthy; `worker` running.
- `docker compose logs --tail=100 api` — Uvicorn стартовал без ошибок.
- `docker compose logs --tail=100 worker` — arq worker стартовал с `process_llm_message`.
- `docker compose exec api alembic upgrade head` — PASS.
- `docker compose exec api pytest -q` — PASS, `18 passed`.
- `curl /health` — `{"status":"ok"}`.
- `curl /ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.

## Что не запускалось

- Stage 1R Telegram live message smoke не запускался: `ADMIN_TELEGRAM_IDS` ещё не заполнен.
- Stage 1R full real runtime smoke не продолжался до verdict ready: обязательный env не полный.
- `scripts/smoke_llm.py` не создавался, потому что переход к Stage 1R smoke по условиям задачи выполняется только после полного обязательного env.

## Что сделать вручную

Вариант A, если webhook можно временно удалить:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
```

Вариант B, если webhook удалять сейчас нельзя:

1. Открыть Telegram.
2. Найти своего бота.
3. Отправить ему `/start` в личке.
4. Указать свой Telegram numeric id в `ADMIN_TELEGRAM_IDS` локального `.env` вручную.
5. Запустить:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
```

## Verdict

`BLOCKED_NEEDS_MANUAL_TELEGRAM_START`
