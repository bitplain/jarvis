from app.bot.dispatcher import build_dispatcher
from app.core.config import Settings


def test_build_dispatcher_can_be_called_more_than_once() -> None:
    settings = Settings(admin_telegram_ids="100500")

    first = build_dispatcher(settings)
    second = build_dispatcher(settings)

    assert first is not second
