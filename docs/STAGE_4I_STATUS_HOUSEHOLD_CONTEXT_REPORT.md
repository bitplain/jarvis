# Stage 4I: status diagnostics and household context

## Verdict

`PASS_STATUS_HOUSEHOLD_CONTEXT_READY` после локальных проверок и PR review/deploy checklist.

## Что добавлено

- Admin-only `/status` diagnostics для API, PostgreSQL, Redis, worker heartbeat, webhook state, reminders, LLM provider, draft streaming, prompt profiles и access DB.
- Redis heartbeat key `jarvis:worker:heartbeat`, обновляемый worker jobs.
- PostgreSQL таблица `household_memory_entries` для ручной памяти.
- Явные memory-команды:
  - `запомни: <факт>`
  - `запомни что <факт>`
  - `что ты помнишь?`
  - `забудь: <текст>`
- Inline UI: delete buttons и `➕ Запомнить` FSM.
- Scoped LLM injection: `Память о текущем чате` только для текущего private/group scope.

## Privacy и границы

- Watcher не включён.
- Auto-memory из обычных сообщений нет.
- Group memory работает только через mention/reply.
- Group non-mention messages не читаются ради памяти.
- Voice/media/transcription не добавлены.
- Telegram Business integration не менялась.
- Railway Variables не менялись.
- Secret-looking memory text отклоняется: `Похоже на секрет. Я не буду это сохранять.`

## Live checklist

1. Admin private `/status` показывает diagnostics без секретов.
2. Non-admin private `/status` получает `Доступ запрещён.`
3. `запомни: у нас семейный чат Фемилис` сохраняет факт.
4. `что ты помнишь?` показывает сохранённый факт.
5. `забудь: у нас семейный чат Фемилис` soft-delete-ит факт.
6. Следующий LLM ответ учитывает active memory текущего scope.
7. Group mention `@bot_username запомни: ...` сохраняет group memory.
8. Group non-mention memory phrase игнорируется.
9. Списки покупок и напоминания продолжают работать.

## Verification

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_status_household_context_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_ux_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_private_ingress_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_mira_private_streaming_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_prompt_profiles_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_access_settings_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_access_group_routing_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_group_stability_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_telegram_webhook_ingress_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_webhook_self_healing_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
```
