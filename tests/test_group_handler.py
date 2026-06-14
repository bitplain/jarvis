from app.bot.routers.groups import should_answer_group_message


def test_group_handler_ignores_unrelated_messages() -> None:
    assert should_answer_group_message("привет", None, "jarvis_bot") is False


def test_group_handler_responds_to_mention() -> None:
    assert should_answer_group_message("привет @jarvis_bot", None, "jarvis_bot") is True


def test_group_handler_responds_to_reply_to_bot() -> None:
    assert should_answer_group_message("привет", 100, "jarvis_bot", bot_user_id=100) is True
