from aiogram import Router

BUSINESS_UPDATE_KEYS = {
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
}


async def secretary_mode_not_implemented() -> None:
    raise NotImplementedError("Secretary Mode переносится на Stage 3.")


def build_router() -> Router:
    return Router(name="business")


router = build_router()
