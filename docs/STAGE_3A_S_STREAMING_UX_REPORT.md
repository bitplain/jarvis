# Stage 3A-S Streaming UX Report

Дата: 2026-06-14

Стартовый commit: `d346f9f Stage 3A-R: validate group routing live smoke`

## Цель

Закрыть отдельный verified stage для streaming ответа “как в Mira” до release-hardening.

## Что реализовано

- `app/bot/streaming/buffer.py`: `StreamBuffer` накапливает LLM chunks и выдаёт `FlushDecision` с `text`, `delta_length`, `is_final` и `reason`.
- `app/bot/streaming/telegram_draft.py`: `TelegramPrivateDraftSink` использует typed `send_message_draft`, если он есть у aiogram `Bot`, иначе isolated raw adapter.
- `app/bot/adapters/message_draft_api.py`: raw Telegram `sendMessageDraft` adapter без вывода token или Authorization headers.
- `app/bot/streaming/telegram_fallback.py`: `TelegramGroupEditSink` отправляет `sendChatAction typing`, provisional `Думаю...`, throttled `editMessageText` и финальный edit/send fallback.
- `app/workers/jobs.py`: worker выбирает private draft streaming, group fallback streaming или final-only path по env flags и payload.
- `scripts/smoke_streaming_readiness.py`: readiness без `getUpdates`, проверяет env flags, Telegram `getMe`, LLM smoke, polling/group readiness, imports draft adapter/buffer/worker.
- `/status`: показывает streaming flags без секретов.
- `app/bot/streaming/text_limits.py`: preview draft/edit обрезается под Telegram limit, финальный ответ делится на Telegram-safe chunks, а в БД сохраняется один полный assistant response.

## Telegram API behavior

Private chat:

1. Worker создаёт non-zero `draft_id` на LLM job.
2. Первый draft call может отправить пустой текст как placeholder.
3. `StreamBuffer` не обновляет draft на каждый token.
4. После завершения worker отправляет обычный финальный `sendMessage`.
5. В БД сохраняется только финальный assistant response.

Group/supergroup:

1. `sendMessageDraft` не используется.
2. Worker отправляет `sendChatAction typing`.
3. Worker отправляет provisional `Думаю...`.
4. Worker редактирует provisional message накопленным текстом с throttling.
5. Финал приходит через final edit; если edit failed, worker отправляет final `sendMessage`.
6. Worker job остаётся `private=false`.

Guest Mode:

- streaming запрещён;
- draft запрещён;
- group edit sink запрещён;
- guest path остаётся final-only через `answerGuestQuery`.

Business / Secretary:

- полноценный Business auto-reply не включён;
- fallback abstraction учитывает `business_connection_id` для `sendChatAction`;
- Stage 3A-S не меняет guards Business Mode.

## Provider streaming support

Yandex и OpenRouter идут через OpenAI-compatible adapter.
Streaming path использует SSE `chat/completions` с `stream=true`.
Если stream path provider ломается, worker пробует обычный non-stream completion и отправляет финальный ответ.

Known limitation: реальная поддержка streaming зависит от выбранного provider/model из `.env`. Model IDs не хардкодятся и не выводятся в отчёты.

## Tests

Добавлены и обновлены:

- `tests/test_stream_buffer.py`
- `tests/test_telegram_draft_sink.py`
- `tests/test_telegram_group_edit_sink.py`
- `tests/test_worker_streaming_jobs.py`
- `tests/test_smoke_streaming_readiness.py`
- `tests/test_status_streaming.py`
- `tests/test_worker_jobs.py`

Покрыто:

- flush by interval/chars/sentence/final;
- no flush on every token;
- non-zero `draft_id`;
- empty first draft placeholder;
- raw adapter isolation;
- Telegram draft API error fallback;
- final send after draft;
- group typing/provisional/edit/final fallback;
- no draft in group;
- Guest final-only worker path;
- no secrets in rendered status/readiness.

## Live smoke status

Live smoke выполнен в Stage 3A-S-LIVE.

Факты:

- private worker job получил `private=true`;
- `sendMessageDraft` вызывался многократно;
- Telegram client visual confirmation: private final answer виден, draft/preview подтверждён пользователем;
- draft path в середине отключился sanitized и job безопасно дошёл до финального ответа;
- private DB success window: `1 USER`, `1 ASSISTANT`, draft chunks в БД не сохранялись;
- group worker job получил `private=false`;
- group fallback выбрал `sendChatAction`, provisional `Думаю...`, throttled `editMessageText`, final edit;
- Telegram client visual confirmation: `Думаю...`, редактирование/замена и финальный group answer подтверждены пользователем;
- group DB success window: `1 USER`, `1 ASSISTANT`;
- recent guest rows: `0`;
- recent business rows: `0`;
- Guest no-streaming подтверждён regression tests `tests/test_worker_streaming_jobs.py::test_guest_job_remains_final_only_without_streaming` и `tests/test_guest_mode.py`.

Итоговый live report:

- `docs/STAGE_3A_S_STREAMING_LIVE_REPORT.md`

Verdict:

`PASS_STAGE_3A_S_STREAMING_READY`

Known limitation:

- Telegram draft API/client preview подтвердился, но draft path может быть отключён во время длинного ответа при Telegram-side ограничениях; fallback отработал безопасно, финальный ответ и БД final-only подтверждены.

## Security

Не выводить:

- Telegram token;
- Yandex/OpenRouter keys;
- Authorization headers;
- `ADMIN_API_TOKEN`;
- полный `ADMIN_TELEGRAM_IDS`;
- приватный текст сообщений.

`.env` не коммитить. GitHub repo не создавать. Push не выполнять.
