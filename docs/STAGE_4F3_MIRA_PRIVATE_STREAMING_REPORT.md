# Stage 4F-3 Mira-style Private Streaming Report

## Цель

Добавить официальный Telegram draft/rich draft path для private chat, не меняя group fallback, Guest Mode, Prompt Profiles, access settings и Railway Variables.

## Что изменено

- `app/bot/adapters/message_draft_api.py` теперь содержит raw wrappers для `sendMessageDraft` и `sendRichMessageDraft` без логирования token/header.
- `app/bot/streaming/telegram_draft.py` поддерживает rich thinking draft `Думаю` и обновляет тот же non-zero `draft_id` обычными text draft updates.
- `app/workers/jobs.py` включает Mira-style режим только при `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED=true` поверх существующих `STREAMING_ENABLED=true` и `STREAMING_PRIVATE_DRAFT_ENABLED=true`.
- `/status` показывает sanitized `Mira Private Draft Streaming: enabled/disabled`.
- `scripts/smoke_mira_private_streaming_readiness.py` проверяет wrapper, sink, worker wiring, fallback path, group isolation и regression tests без Telegram live calls.

## Поведение private chat

1. Worker выбирает private streaming только если включены общие streaming flags.
2. При `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED=true` worker создаёт один non-zero `draft_id`.
3. Start phase пробует `sendRichMessageDraft` с rich thinking block `Думаю`.
4. Chunks из LLM идут через `StreamBuffer` и обновляют тот же `draft_id` через text draft.
5. Финальный ответ отправляется обычным `sendMessage`; draft preview не пишется в БД.

Exact Mira letter-growth не полностью контролируется backend: Jarvis отправляет throttled draft updates, а Telegram client сам анимирует изменение draft preview.

## Fallback

- Если rich draft недоступен или падает, job логирует sanitized `telegram_private_draft_streaming_failed` и возвращается к text draft `Думаю`.
- Если text draft updates недоступны или падают, worker использует существующий private fallback.
- Ошибка draft API сама по себе не должна валить LLM job и не должна дублировать final answer.

## Group/Guest boundaries

- Group/supergroup path не использует `sendMessageDraft` и `sendRichMessageDraft`; после Stage 4F-4 используется `sendChatAction typing`, provisional `Думаю`, throttled `editMessageText` и final edit/send fallback.
- Guest Mode остаётся final-only через `answerGuestQuery`.
- Business / Secretary auto-reply, watcher, shopping list, reminders и чтение всех сообщений не включались.

## Tests

- `tests/test_telegram_draft_sink.py`
- `tests/test_worker_streaming_jobs.py`
- `tests/test_smoke_mira_private_streaming_readiness.py`

Покрытие:

- initial rich thinking draft;
- text chunks update same `draft_id`;
- final answer sent exactly once;
- rich draft failure falls back to text draft;
- draft API failure still reaches old private fallback;
- disabled Mira flag keeps old private draft behavior;
- group path uses group fallback and no private draft API.

## Live checklist

Live proof не выполнялся в PR, потому что destructive/live Telegram calls запрещены для этого этапа без отдельной команды.

Перед production enablement:

1. Включить `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED=true` только в нужном runtime env.
2. Отправить private message боту от admin/allowed user.
3. Проверить worker logs: `streaming_private_draft_selected`, `telegram_send_rich_message_draft_called`, `telegram_send_message_draft_called`, `telegram_final_send_message_called`.
4. Подтвердить в Telegram client, что появился thinking/draft preview и финальный ответ.
5. Проверить БД: один final assistant response, без draft chunk records.
6. Проверить group mention/reply отдельно: должен быть `streaming_group_fallback_selected`, без rich/text draft calls.

## Verdict

`PASS_STAGE_4F3_MIRA_PRIVATE_STREAMING_READY`
