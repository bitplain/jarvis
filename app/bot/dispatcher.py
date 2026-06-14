from aiogram import Dispatcher

from app.bot.middlewares.access import AdminAccessMiddleware
from app.bot.middlewares.group_diagnostics import GroupDiagnosticsMiddleware
from app.bot.routers import business, commands, groups, guest, private
from app.core.config import Settings


def build_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher(settings=settings)
    dispatcher.message.middleware(AdminAccessMiddleware(settings.admin_ids))
    dispatcher.message.middleware(GroupDiagnosticsMiddleware(settings))
    dispatcher.include_router(commands.build_router())
    dispatcher.include_router(guest.build_router())
    dispatcher.include_router(business.build_router())
    dispatcher.include_router(private.build_router())
    dispatcher.include_router(groups.build_router())
    return dispatcher
