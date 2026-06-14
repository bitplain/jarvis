# Правила проекта Jarvis

## Язык и стиль

- Вся документация, stage-отчёты, комментарии к задачам и ответы бота пользователю пишутся на русском языке.
- Пользовательские ответы Telegram-бота должны быть только на русском.
- Если бот не знает ответ, он честно говорит, что не знает, и не выдумывает факты.

## Безопасность

- Нельзя хардкодить Telegram token, LLM API keys, пароли, model IDs, Telegram IDs и другие секреты.
- Все секреты задаются только через `.env` или GitHub Secrets.
- `.env` не должен попадать в git.
- В логах нельзя печатать Telegram token, LLM API keys, Authorization headers, пароли и реальные env secrets.

## Stage 1 границы

- GitHub repository не создаётся и ничего не пушится до отдельной команды.
- Guest Mode, Secretary Mode и Mini App в Stage 1 не реализуются полностью.
- Guest/Business код должен оставаться явным stub/no-op или выбрасывать `NotImplementedError`, чтобы его нельзя было принять за готовую функцию.
- Реальный Telegram/LLM smoke без настоящих env-секретов считается `BLOCKED_NEEDS_REAL_ENV`, а не успехом.
- Stage 1R env bootstrap может генерировать только локальные секреты в `.env`, выводить только sanitized status и никогда не коммитить реальные значения `.env`.

## Проверки

Перед финальным отчётом выполнять:

```bash
ruff check .
mypy app
pytest -q
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
git status --short
```

## Remote AGENTS sync

Stage 1 выполняется до создания сервера/live project paths.

`remote AGENTS sync = N/A until server/live paths exist`
