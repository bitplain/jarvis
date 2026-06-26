# Hotfix: shopping buy-colon intent

## Симптом

Сообщение `Купить: хлеб сок мазик запеканку` не попадало в deterministic shopping flow. Оно уходило в обычный LLM path, бот отвечал текстом вроде "Список покупок принят", но таблицы `shopping_lists` / `shopping_list_items` не получали новые позиции, и реальный `Список покупок` оставался пустым.

## Root cause

Parser `app/services/simple_intent_parser.py` поддерживал shopping add через `добавь ... в список` и `купи ...`, но не считал `купить:` / `покупки:` / `список покупок:` strong command prefix. Из-за этого private/group router не перехватывал команду до generic LLM handler.

## Что изменено

- Добавлены strong colon triggers:
  - `купить:`
  - `покупки:`
  - `список покупок:`
- Colon payload использует существующие sanitizer/split helpers.
- Если colon payload без запятых, точки с запятой, newline или connector `и` содержит 2-10 простых слов, он делится по пробелам.
- Existing PR #21 behavior сохранён: `мазик и молоко` делится на два item-а, текущий bot mention вырезается case-insensitive.
- Handled shopping commands не создают `process_llm_message`.

## Поддержанные примеры

- `Купить: хлеб сок молоко` -> `хлеб`, `сок`, `молоко`
- `Купить: хлеб, сок и молоко` -> `хлеб`, `сок`, `молоко`
- `@Home_ai_my_bot купить: творожок` -> `творожок`

## Не-цели

- Watcher не включается.
- Auto-memory не добавляется.
- Broad natural language parser не добавляется.
- `где купить молоко?` и `можешь купить молоко?` остаются обычным LLM path.
- Railway Variables не менялись.
- Live destructive Telegram calls не выполнялись.
- Серверные/live project paths в этом репозитории не заведены: `remote AGENTS sync = N/A until server/live paths exist`.

## Проверки

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_shopping_buy_colon_readiness.py
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
