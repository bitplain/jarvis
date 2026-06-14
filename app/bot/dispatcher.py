from aiogram import Dispatcher

from app.bot.middlewares.access import AdminAccessMiddleware
from app.bot.routers import business, commands, groups, guest, private
from app.core.config import Settings


def build_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher(settings=settings)
    dispatcher.message.middleware(AdminAccessMiddleware(settings.admin_ids))
    dispatcher.include_router(commands.router)
    dispatcher.include_router(guest.router)
    dispatcher.include_router(business.router)
    dispatcher.include_router(private.router)
    dispatcher.include_router(groups.router)
    return dispatcher
