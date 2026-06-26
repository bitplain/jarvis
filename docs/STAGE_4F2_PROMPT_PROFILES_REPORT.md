# Stage 4F-2 Prompt Profiles Report

## Итог

Stage 4F-2 добавляет управляемые Prompt Profiles для личных сообщений, группового ассистента и будущего watcher.

Hotfix `docs/HOTFIX_PROMPT_PROFILES_RAW_EDITOR_REPORT.md` уточняет UX: fixed preset-стили не являются raw prompt editor. Актуальный admin-only raw editor находится в `/settings -> Промты` и хранит тексты в `runtime_settings` ключами `prompt.private`, `prompt.group`, `prompt.watch`.

## Реализовано

- Admin-only раздел `/settings -> Профили`.
- Runtime settings keys:
  - `prompt_profile_private`;
  - `prompt_profile_group`;
  - `prompt_profile_watcher`.
- Фиксированные профили: `balanced`, `short`, `deep`, `draft`, `watcher`.
- Worker читает private/group profile перед каждым LLM job и передаёт его в `MemoryService`.
- `MemoryService` строит system prompt из базовых правил Jarvis и профильной инструкции.
- Восстановлен private ingress guard: `/start` доходит до command handler даже если Redis pool временно недоступен, а обычный private text от admin/allowed user покрыт synthetic webhook tests.
- Readiness script `scripts/smoke_prompt_profiles_readiness.py` не вызывает `getUpdates`.
- Добавлен `scripts/smoke_private_ingress_readiness.py`, который проверяет `/start`, private text, scoped FSM filters, persistent Dispatcher и worker prompt profile fallback без live Telegram/LLM calls.

## Root cause private silence

Предыдущие tests/smokes проверяли private text только при заранее установленном `app.state.redis_pool`. В production-like пути `POST /telegram/webhook` пытался создать Redis pool до `dispatcher.feed_update(...)`; если Redis был временно недоступен, update не доходил ни до `/start`, ни до private handler, поэтому бот молчал.

Фикс: webhook route логирует sanitized `telegram_webhook_redis_unavailable`, передаёт `redis=None` в dispatcher для non-worker handlers и сохраняет успешно созданный Redis pool на `app.state.redis_pool`.

## Не входит в Stage 4F-2

- Smart Watcher;
- списки покупок;
- напоминания;
- чтение всех сообщений;
- изменение streaming;
- эффект Mira;
- watcher/shopping/reminders/Mira и автономные действия watcher.

## Проверка

Ожидаемый локальный readiness verdict:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_prompt_profiles_readiness.py
```

`PASS_PROMPT_PROFILES_RAW_EDITOR_READINESS`

```bash
uv run --python 3.12 --extra dev python scripts/smoke_private_ingress_readiness.py
```

`PASS_PRIVATE_INGRESS_READINESS`
