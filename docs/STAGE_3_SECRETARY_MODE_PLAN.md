# Stage 3: Secretary / Business Mode Plan

В Stage 1 Secretary Mode не реализован полностью. Код содержит только безопасный stub:

- `app/bot/routers/business.py`
- `app/services/business_service.py`
- таблица `business_connections_stub`

## Что сделать в Stage 3

- Включить Secretary Mode в BotFather вручную.
- Хранить `business_connection_id`.
- Проверять реальные права ответа из Telegram Business API.
- Отправлять ответы через `business_connection_id`.
- Использовать fallback через `sendChatAction`.
- Не имитировать `can_reply` и не придумывать права.
