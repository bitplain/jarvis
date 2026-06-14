from app.bot.dispatcher import build_dispatcher
from app.bot.routers import groups, private
from app.core.config import Settings


def test_build_dispatcher_can_be_called_more_than_once() -> None:
    settings = Settings(admin_telegram_ids="100500")

    first = build_dispatcher(settings)
    second = build_dispatcher(settings)

    assert first is not second


def test_private_and_group_routers_have_chat_type_filters() -> None:
    private_handlers = private.build_router().message.handlers
    group_handlers = groups.build_router().message.handlers

    assert private_handlers[0].filters
    assert group_handlers[0].filters
