from app.bot.dispatcher import build_dispatcher
from app.core.config import Settings


def test_dispatcher_factory_has_guest_observer_for_webhook_and_polling() -> None:
    settings = Settings(admin_telegram_ids="100500", guest_mode_enabled=True)

    webhook_dispatcher = build_dispatcher(settings)
    polling_dispatcher = build_dispatcher(settings)

    assert webhook_dispatcher is not polling_dispatcher
    assert "guest_message" in webhook_dispatcher.observers
    assert "guest_message" in polling_dispatcher.observers
    assert "message" in polling_dispatcher.observers
