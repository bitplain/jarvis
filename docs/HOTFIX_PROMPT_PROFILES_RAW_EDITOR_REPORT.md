# Hotfix Prompt Profiles Raw Editor Report

## Проблема

Stage 4F-2 реализовал `/settings -> Профили` как выбор фиксированных preset-стилей: `balanced`, `short`, `deep`, `draft`, `watcher`.

Это не закрывало пользовательское требование: администратор должен видеть текущий raw system prompt, полностью переписывать его вручную, сохранять custom prompt и сбрасывать его к default.

## Исправление

Добавлен admin-only raw prompt editor:

- `/settings -> Промты -> Личка`;
- `/settings -> Промты -> Группа`;
- `/settings -> Промты -> Наблюдение`.

Экран prompt показывает:

- источник: `default` или `custom`;
- длину prompt в символах;
- текущий prompt text;
- действия `Изменить`, `Сбросить`, `Назад`, `Закрыть`;
- `Показать полностью`, если prompt не помещается в экран настроек.

Prompt text отправляется без `parse_mode`. Лимит custom prompt: 4000 символов.

## Хранение

Используется существующая таблица `runtime_settings`.

Ключи raw prompt:

- `prompt.private`;
- `prompt.group`;
- `prompt.watch`.

Старые style presets остаются отдельной настройкой:

- `prompt_profile_private`;
- `prompt_profile_group`;
- `prompt_profile_watcher`.

`Стиль ответа` не является raw prompt editor и не заменяет `Промты`.

## Worker behavior

- Private `process_llm_message` читает `prompt.private`.
- Group/supergroup `process_llm_message` читает `prompt.group`.
- `prompt.watch` пока не используется автоматически.
- Если `runtime_settings` временно недоступна, worker использует default prompt для нужного scope и пишет только sanitized log event без полного prompt text.

## Как проверить live после merge

1. Открыть `/settings -> Промты`.
2. Открыть `Личка`.
3. Увидеть текущий prompt text и `Источник: default` или `custom`.
4. Нажать `Изменить`, отправить новый prompt, убедиться, что текст не ушёл в LLM.
5. Отправить private `Привет` и проверить, что новый prompt влияет на ответ.
6. Открыть `Группа`, изменить group prompt.
7. Проверить group mention/reply в настоящей Telegram group/supergroup.
8. Нажать `Сбросить` и увидеть default prompt.
9. Проверить `/start` и обычный private ingress.

## Не входит

- Smart Watcher;
- shopping list;
- reminders;
- Mira;
- чтение всех сообщений;
- изменение streaming;
- Railway Variables;
- merge/push в `main`.

## Readiness

Ожидаемый локальный verdict:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_prompt_profiles_readiness.py
```

`PASS_PROMPT_PROFILES_RAW_EDITOR_READINESS`
