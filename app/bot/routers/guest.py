from aiogram import Router

router = Router(name="guest")


async def guest_mode_not_implemented() -> None:
    raise NotImplementedError("Guest Mode переносится на Stage 2.")
