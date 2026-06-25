# Stage 4F-0 Group Stability Report

Verdict: `PASS_STAGE_4F0_GROUP_STABILITY_READY`

## Production symptoms

- Group mention/reply работал и создавал один worker job `process_llm_message(private=false)`.
- В Telegram иногда появлялся дубль финального ответа, хотя production logs не показывали duplicate job.
- В group/supergroup бот мог отвечать `Доступ запрещён.` на сообщения неразрешённых пользователей, что превращалось в шум для всей группы.

## Evidence

- Production logs показывали один group update и один `process_llm_message(private=False)`.
- В том же job были события `streaming_group_fallback_selected`, `telegram_group_provisional_sent`, `telegram_group_edit_message_text_called`, а затем `telegram_streaming_final_edit_failed` или повторные final edit события.
- Значит дубль происходил внутри group fallback final delivery, а не на уровне webhook/router enqueue.

## Root cause

- `AdminAccessMiddleware` отвечал `Доступ запрещён.` на любой unauthorized `Message` без различения private и group/supergroup.
- `TelegramGroupEditSink.final()` не имел `final_delivered` guard: повторная finalization могла повторно делать final edit/send.
- Любой `TelegramBadRequest`, включая safe `message is not modified`, считался ошибкой final edit и запускал fallback send.
- Group router отправлял отдельный accepted message, а worker затем создавал второй provisional message, хотя editable provisional должен принадлежать worker.

## Fix

- Unauthorized private messages получают `Доступ запрещён.` как раньше.
- Unauthorized group/supergroup messages, включая mention/reply, молча игнорируются и логируют sanitized `access_denied_group_silent`.
- Group router больше не отправляет отдельный accepted message после enqueue; worker отправляет один provisional `Принял. Готовлю групповой ответ.`.
- Group final delivery получил `final_delivered` guard.
- `message is not modified` считается success/no-op и не запускает fallback duplicate send.
- Fallback final send и long-response chunks отправляются ровно один раз.

## Tests

- `test_private_unauthorized_gets_access_denied`
- `test_group_unauthorized_is_silent`
- `test_group_unauthorized_mention_is_silent`
- `test_group_authorized_mention_enqueues_once`
- `test_group_final_edit_success_sends_no_duplicate`
- `test_group_final_edit_failure_sends_one_fallback`
- `test_group_message_not_modified_is_success`
- `test_group_long_final_split_once`
- Existing private streaming tests remain in `tests/test_worker_streaming_jobs.py`.

## Live verification checklist after merge

- Unknown user in group/supergroup is silent.
- Unknown user in private gets `Доступ запрещён.`.
- Authorized group mention/reply creates exactly one worker job.
- Worker logs show `process_llm_message(private=false)` once for the group update.
- Telegram group receives one provisional and one final answer, without duplicate final send.
- `message is not modified` in logs is treated as safe no-op.
- Private streaming still creates draft/fallback and final response as before.

## Проверки

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_group_stability_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_streaming_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
```
