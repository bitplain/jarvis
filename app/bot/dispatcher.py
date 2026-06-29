from aiogram import Dispatcher

from app.bot.middlewares.access import AdminAccessMiddleware
from app.bot.middlewares.group_diagnostics import GroupDiagnosticsMiddleware
from app.bot.routers import (
    business,
    commands,
    daily_brief,
    groups,
    guest,
    helpdesk_tickets,
    household_memory,
    lists_reminders,
    private,
)
from app.core.config import Settings


def build_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher(settings=settings)
    dispatcher.message.middleware(AdminAccessMiddleware(settings.admin_ids))
    dispatcher.message.middleware(GroupDiagnosticsMiddleware(settings))
    dispatcher.include_router(commands.build_router())
    dispatcher.include_router(guest.build_router())
    dispatcher.include_router(business.build_router())
    dispatcher.include_router(daily_brief.build_router())
    dispatcher.include_router(helpdesk_tickets.build_router())
    dispatcher.include_router(lists_reminders.build_router())
    dispatcher.include_router(household_memory.build_router())
    dispatcher.include_router(private.build_router())
    dispatcher.include_router(groups.build_router())
    return dispatcher
