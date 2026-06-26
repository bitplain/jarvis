# Hotfix: household memory delete UX

## Verdict

`PASS_HOTFIX_HOUSEHOLD_MEMORY_DELETE_UX_READY` после локальных проверок и PR review/deploy checklist.

## Симптом

Пользователь сохранял:

```text
Запомни: Я Александр системный администратор
```

Затем пытался удалить естественными формулировками:

```text
Забудь: что я Александр и системный администратор
Забудь: я Александр системный администратор
```

Jarvis отвечал `Не нашёл такую запись в памяти.`, хотя запись была active и использовалась в LLM context.

## Root cause

`delete_memory_by_text` сравнивал только exact/contains после whitespace-normalization. Регистр, пунктуация, `ё/е`, filler word `что` и connector `и` не нормализовались для delete-query, поэтому пользователь должен был помнить запись почти символ-в-символ.

## Что изменено

- `что ты помнишь?` показывает нумерованный список и inline-кнопки `🗑 N`.
- Добавлено удаление по номеру:
  - `забудь 1`
  - `забудь #1`
  - `удали память 1`
- Delete by text использует нормализованное matching:
  - case-insensitive;
  - `ё -> е`;
  - пунктуация удаляется;
  - слабые слова delete-query `что`, `это`, `про`, `и` убираются;
  - exact/contains и token-overlap fallback.
- Если найдено несколько похожих записей, Jarvis показывает выбор с кнопками и не удаляет автоматически.
- Если совпадений нет, Jarvis предлагает открыть `что ты помнишь?` и удалить по номеру.

## Safety

- Удаление остаётся soft-delete.
- Private memory удаляется только в private scope.
- Group memory удаляется только в текущем group scope.
- Callback `mem:*` повторно проверяет access policy и сверяет id с active entries текущего scope.
- Deleted memory больше не попадает в LLM injection.
- HTML-list output экранирует memory text.
- Watcher, auto-memory, Railway Variables, Business integration, lists/reminders, prompt profiles, Mira streaming и access routing не менялись.
- Серверные/live project paths в этом репозитории не заведены: `remote AGENTS sync = N/A until server/live paths exist`.

## Live checklist

1. `Запомни: Я Александр системный администратор` -> `Сохранил.`
2. `что ты помнишь?` -> numbered list with `1. Я Александр системный администратор`.
3. `забудь 1` -> `Удалил из памяти: ...`.
4. Сохранить запись повторно.
5. `забудь: что я Александр и системный администратор` -> запись удалена по normalized match.
6. Следующий `Кто я?` не должен использовать удалённую household memory.

## Verification

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_household_memory_delete_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_status_household_context_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_ux_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_private_ingress_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_mira_private_streaming_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_prompt_profiles_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_access_group_routing_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
```
