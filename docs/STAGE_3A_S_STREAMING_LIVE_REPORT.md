# Stage 3A-S Streaming Live Report

Дата: 2026-06-14

Стартовый commit: `29e9692 Stage 3A-S: implement streaming UX`

Этот отчёт входит в commit `Stage 3A-S: validate streaming live smoke`.

## Итог

Verdict: `PASS_STAGE_3A_S_STREAMING_READY`

Причина: private draft streaming path, safe fallback, final persistence, group fallback streaming и Guest no-streaming checks подтверждены фактическими Telegram/logs/DB evidence.

## Env Flags Sanitized

- `STREAMING_ENABLED=true`
- `STREAMING_PRIVATE_DRAFT_ENABLED=true`
- `STREAMING_GROUP_FALLBACK_ENABLED=true`
- `STREAMING_DRAFT_UPDATE_INTERVAL_MS=800`
- `STREAMING_GROUP_EDIT_INTERVAL_MS=1000`
- `STREAMING_MIN_CHARS_DELTA=120`
- `STREAMING_MAX_DRAFT_SECONDS=25`
- `STREAMING_SEND_CHAT_ACTION_INTERVAL_SECONDS=4`
- `STREAMING_DRAFT_RAW_API_FALLBACK=true`

## Readiness

Перед live smoke:

- `scripts/smoke_streaming_readiness.py`: `PASS_STREAMING_READINESS`
- `scripts/smoke_llm.py`: `PASS_LLM_SMOKE`
- `scripts/smoke_polling_readiness.py`: `PASS_POLLING_READINESS`
- `scripts/smoke_regular_readiness.py`: `PASS_REGULAR_READINESS`
- `scripts/smoke_group_readiness.py`: `PASS_GROUP_READINESS`

Runtime:

- `docker compose up -d`: containers running
- `docker compose ps`: api healthy, postgres healthy, redis healthy, worker running
- `docker compose exec api alembic upgrade head`: OK
- `curl /health`: OK
- `curl /ready`: OK

## Polling Runner

Polling runner:

- webhook delete path executed before polling;
- `drop_pending_updates=false`;
- `allowed_updates` included `guest_message` and regular `message`;
- streaming flags logged sanitized;
- bot username resolved at runtime as `@Home_ai_my_bot`.

## Private Streaming

Manual prompt sent in private chat:

```text
Напиши длинный ответ на 8 пунктов: как правильно обслуживать PostgreSQL в небольшом проекте
```

Facts:

- worker got private job: `private=true`;
- selected sink: `streaming_private_draft_selected`;
- draft API called: yes, repeated `telegram_send_message_draft_called`;
- draft id: non-zero by implementation and regression tests; full value not included in report;
- throttling: draft calls were fewer than raw provider chunks and gated by `StreamBuffer`;
- final sendMessage: yes, `telegram_final_send_message_called`;
- Telegram client visual confirmation: user answered `везде да`;
- DB final-only: yes.

DB success window:

| Role | Count | Length evidence |
| --- | ---: | --- |
| USER | 1 | min=max `91` |
| ASSISTANT | 1 | min=max `4076` |

Intermediate draft chunks were not saved as assistant messages.

Observed fallback:

- During a long answer Telegram draft path was disabled by Telegram-side constraints.
- Fallback continued safely and final response was sent.
- Regression fix added Telegram text limits: draft/edit preview is clipped to Telegram-safe length; final send is split into Telegram-safe chunks when needed while DB stores one full assistant response.

## Group Fallback

Manual prompt sent in real group/supergroup:

```text
@Home_ai_my_bot дай длинный ответ на 6 пунктов: зачем нужен DNS
```

Facts:

- update arrived as regular group `message`, not `guest_message`;
- worker job had `private=false`;
- selected sink: `streaming_group_fallback_selected`;
- `sendChatAction typing`: yes, `telegram_send_chat_action_called`;
- provisional `Думаю...`: yes, `telegram_group_provisional_sent`;
- throttled edits: yes, repeated `telegram_group_edit_message_text_called`;
- final edit/send: yes, `telegram_group_final_edit_called`;
- Telegram client visual confirmation: user answered `везде да`.

DB success window:

| Role | Count | Length evidence |
| --- | ---: | --- |
| USER | 1 | min=max `63` |
| ASSISTANT | 1 | min=max `1313` |

Isolation:

- recent guest rows: `0`;
- recent business rows: `0`.

## Guest No-Streaming

Guest live smoke was not repeated in this run because Stage 2 Guest Mode already had real readiness and the Stage 3A-S task allowed regression confirmation if live Guest repeat was not convenient.

Confirmed by:

- `tests/test_worker_streaming_jobs.py::test_guest_job_remains_final_only_without_streaming`;
- `tests/test_guest_mode.py`;
- live window had no guest streaming logs;
- recent guest rows during private/group streaming live window: `0`.

Guest path remains:

`guest_message -> LLM final answer -> answerGuestQuery`

No `sendMessageDraft`, no `TelegramPrivateDraftSink`, no `TelegramGroupEditSink`.

## Provider Streaming

LLM smoke passed for Yandex and OpenRouter.
Worker logs showed provider streaming chunks were sufficient for draft updates. When provider/Telegram stream path hit a long-answer constraint, fallback to safe final path completed the job.

## Security

Reports do not include:

- Telegram token;
- Yandex/OpenRouter keys;
- Authorization headers;
- `ADMIN_API_TOKEN`;
- full `ADMIN_TELEGRAM_IDS`;
- full Telegram chat/user ids;
- private message text beyond the public test prompts.

`.env` was not committed. GitHub repo was not created. Push was not performed.

## Known Limitations

- Telegram client visibility of draft preview depends on client support; this run was visually confirmed by the user.
- Telegram draft path can still be disabled mid-stream by Telegram-side constraints. Current behavior is safe fallback with final response and final-only DB persistence.
- Long final responses are split into Telegram-safe message chunks; DB still stores one full assistant response.
