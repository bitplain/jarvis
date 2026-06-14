from app.bot.middlewares.access import is_admin_user


def test_unauthorized_telegram_user_rejected() -> None:
    assert is_admin_user(99, {1, 2}) is False


def test_authorized_telegram_user_accepted() -> None:
    assert is_admin_user(1, {1, 2}) is True
