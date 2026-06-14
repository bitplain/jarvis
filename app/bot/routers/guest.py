from aiogram import Router


async def guest_mode_not_implemented() -> None:
    raise NotImplementedError("Guest Mode переносится на Stage 2.")


def build_router() -> Router:
    return Router(name="guest")


router = build_router()
