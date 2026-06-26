# Stage 4F-2 Prompt Profiles Design

## Цель

Добавить управляемые Prompt Profiles для обычных личных сообщений, группового ассистента и будущего watcher без включения Smart Watcher, списков покупок, напоминаний, чтения всех сообщений, изменений streaming или эффекта Mira.

## Подход

Профили хранятся как фиксированные enum-значения в существующей таблице `runtime_settings`. Для каждого канала используется отдельный ключ:

- `prompt_profile_private`
- `prompt_profile_group`
- `prompt_profile_watcher`

Отсутствующая запись означает безопасный профиль `balanced`. В БД не хранятся произвольные prompt-тексты пользователя: только выбранные значения enum.

## Профили

- `balanced` — обычный Jarvis: полезно, кратко, структурированно.
- `short` — более короткие ответы без лишних пояснений.
- `deep` — более подробный разбор с оговорками неизвестных фактов.
- `draft` — режим черновика: помогает формулировать текст, но не утверждает, что отправил сообщение.
- `watcher` — подготовленный профиль для будущего watcher; в Stage 4F-2 только настраивается, но не запускает watcher.

Все профили сохраняют базовые правила: русский язык, честное признание неизвестности, запрет выдумывать факты.

## Runtime Flow

Worker перед каждым LLM job читает runtime settings. Для private job применяется `prompt_profile_private`, для group job — `prompt_profile_group`. `prompt_profile_watcher` сохраняется и показывается в UI, но не используется в обработке сообщений на этом этапе.

`MemoryService.build_context()` принимает выбранный профиль и тип канала, после чего строит system prompt из базовой инструкции Jarvis и профильной инструкции. Streaming-сценарии получают тот же список сообщений, но сами streaming sinks не меняются.

Webhook ingress остаётся отдельным release gate: `/start` должен попадать в command handler даже при временно недоступном Redis, а обычный private text от admin/allowed user должен создавать `process_llm_message` через synthetic webhook tests. Redis unavailable логируется sanitized и не должен превращать non-worker handlers в молчание.

## Telegram UI

Admin-only `/settings` получает раздел `Профили` рядом с `Агент` и `Доступ`.

Внутри раздела:

- `Личные` — выбор профиля для private chat.
- `Группы` — выбор профиля для group/supergroup mention/reply.
- `Watcher` — выбор будущего watcher profile без запуска watcher.

Callback-и идемпотентны: повторный выбор текущего профиля отвечает коротко и не редактирует сообщение. Если `runtime_settings` недоступна, пользователь получает безопасное русское сообщение о миграции БД.

## Границы

Stage 4F-2 не добавляет Smart Watcher, списки покупок, напоминания, чтение всех сообщений, изменение streaming, автономные ответы или эффект Mira.

## Проверка

Проверки покрывают:

- enum/service defaults and validation;
- применение private/group profile в `MemoryService`;
- чтение профилей worker-ом на каждый job;
- admin-only Telegram settings callbacks;
- readiness script без `getUpdates`;
- отсутствие изменений streaming behavior;
- private ingress regression: `/start`, admin/allowed private text, unknown private denial, scoped FSM и worker prompt profile fallback.
