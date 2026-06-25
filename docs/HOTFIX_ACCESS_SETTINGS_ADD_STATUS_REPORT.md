# Hotfix Access Settings Add Status Report

## Статус

Ветка: `codex/hotfix-access-settings-add-status`

PR #10 `codex/hotfix-access-settings-fsm-input` уже был merged, поэтому этот hotfix выполнен отдельной веткой от актуального `main`.

## Проблема

В `/settings -> Доступ -> Группы -> Добавить группу` успешное добавление и повторное добавление показывали один общий текст в формате "добавлена или уже была".

Такой текст вводит в заблуждение: если список был пустой, пользователь видит, что группа появилась, но сообщение одновременно намекает, будто она уже существовала.

## Root Cause

Access add operation была idempotent/upsert, но repository/service не возвращали точный результат мутации. UI не мог отличить:

- запись создана;
- запись уже существовала.

Remove path различал результат только через `bool`, поэтому текст для missing case тоже был недостаточно явным и не совпадал по формату с add result messages.

## Изменения

- Добавлен `AccessMutationResult` со статусами `CREATED`, `ALREADY_EXISTS`, `REMOVED`, `NOT_FOUND`.
- `TelegramAccessRepository.upsert_entry()` возвращает `CREATED` для нового insert и `ALREADY_EXISTS` для conflict path с сохранением idempotent label update.
- `TelegramAccessService.add_allowed_user/add_allowed_group/remove_allowed_user/remove_allowed_group` возвращают точный результат операции.
- Access settings FSM UI теперь показывает точные сообщения:
  - `Пользователь добавлен:`
  - `Пользователь уже есть в списке:`
  - `Группа добавлена:`
  - `Группа уже есть в списке:`
  - `Пользователь удалён:`
  - `Пользователь не найден:`
  - `Группа удалена:`
  - `Группа не найдена:`
- Для multiple IDs результат делится на блоки `Добавлены:` и `Уже были:`.
- После каждой операции по-прежнему показывается актуальный список.
- Access policy не менялась: env admins остаются admin/allowed, DB allowed users не становятся admin, group allowlist и silent unauthorized group behavior сохраняются.

## Тесты

Добавлены/обновлены проверки:

- add group into empty list returns `CREATED`;
- add same group second time returns `ALREADY_EXISTS`;
- UI text for created group does not contain `уже была`;
- UI text for existing group contains `уже есть`;
- add user into empty list returns `CREATED`;
- add same user second time returns `ALREADY_EXISTS`;
- multiple IDs split created vs already existing;
- remove existing returns `REMOVED`;
- remove missing returns `NOT_FOUND`;
- FSM input still does not enqueue LLM.

## Smoke

`scripts/smoke_access_settings_readiness.py` обновлён и проверяет:

- add result distinguishes created/existing;
- exact UX message tests are present;
- old generic add/existing text is absent.

## Expected Verdict

`PASS_HOTFIX_ACCESS_SETTINGS_ADD_STATUS_READY`
