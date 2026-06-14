# Stage 2: Guest Mode Plan

В Stage 1 Guest Mode не реализован полностью. Код содержит только безопасный stub:

- `app/bot/routers/guest.py`
- `app/services/guest_service.py`
- таблица `guest_messages_stub`

## Что сделать в Stage 2

- Обработать Telegram `guest_message`, если update type доступен в используемой версии Bot API/aiogram.
- Извлечь `guest_query_id`.
- Сгенерировать финальный ответ через LLM.
- Вызвать `answerGuestQuery`.
- В MVP не использовать streaming.
- Добавить тесты на happy path, ошибки Telegram API и отсутствие необходимых полей.
