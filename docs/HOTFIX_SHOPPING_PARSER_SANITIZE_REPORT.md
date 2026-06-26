# Hotfix: shopping parser sanitize

## Verdict

`PASS_HOTFIX_SHOPPING_PARSER_SANITIZE_READY` после локальных проверок и PR review/deploy checklist.

## Live symptom

Shopping list показывал:

```text
1. хлеб
2. мазик и молоко
3. @home_ai_my_bot творожок
```

## Root cause

Shopping add parser делил items по запятой/newline или по connector `и` только как альтернативные ветки. Поэтому смешанный ввод вроде `хлеб, молоко и яйца` оставлял `молоко и яйца` одной позицией. Общего sanitizer для текущего bot mention внутри shopping add payload не было, поэтому FSM/reply path мог сохранить `@Home_ai_my_bot творожок` как текст item.

## Что исправлено

- Добавлен общий `sanitize_shopping_items_input`.
- Текущий bot mention вырезается case-insensitive перед сохранением item.
- Чужие mentions не удаляются.
- Добавлен общий `split_shopping_items`.
- Items делятся по comma, semicolon, newline и простому connector `и`.
- Parser/sanitizer подключён к private intent, group mention intent и shopping add FSM.
- Пустой payload после удаления mention отклоняется и не уходит в LLM.

## Проверка live bugs

- `мазик и молоко` -> `мазик`, `молоко`.
- `хлеб, молоко и яйца` -> `хлеб`, `молоко`, `яйца`.
- `@Home_ai_my_bot творожок` -> `творожок`.
- `@home_ai_my_bot творожок` -> `творожок`.

## Safety

- Watcher не включался.
- Auto-memory не включалась.
- Railway Variables не менялись.
- Live destructive Telegram calls не выполнялись.
- Reminders, status, household memory, prompt profiles, Mira streaming и access routing не менялись.
- Серверные/live project paths в этом репозитории не заведены: `remote AGENTS sync = N/A until server/live paths exist`.

## Verification

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_shopping_parser_sanitize_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_ux_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_status_household_context_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_private_ingress_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_mira_private_streaming_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_prompt_profiles_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_access_group_routing_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
```
