import pytest

from app.workers.jobs import try_send_chat_action


class FailingBot:
    async def send_chat_action(self, *, chat_id: int, action: object) -> None:
        raise RuntimeError("flood control")


@pytest.mark.asyncio
async def test_try_send_chat_action_does_not_raise() -> None:
    await try_send_chat_action(FailingBot(), chat_id=1)
