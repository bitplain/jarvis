from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.workers.jobs import (
    check_helpdesk_imap_mailbox,
    deliver_daily_briefs,
    deliver_due_reminders,
    process_llm_message,
    remind_helpdesk_tickets,
    send_due_digests,
    sync_whoop_integrations,
)

settings = get_settings()


async def configure_worker_logging(ctx: dict[object, object]) -> None:
    del ctx
    configure_logging(settings.log_level)


class WorkerSettings:
    functions = [
        process_llm_message,
        deliver_due_reminders,
        deliver_daily_briefs,
        send_due_digests,
        check_helpdesk_imap_mailbox,
        remind_helpdesk_tickets,
        sync_whoop_integrations,
    ]
    cron_jobs = [
        cron(deliver_due_reminders, second={0, 30}),
        cron(deliver_daily_briefs),
        cron(send_due_digests),
        cron(check_helpdesk_imap_mailbox),
        cron(remind_helpdesk_tickets),
        cron(sync_whoop_integrations, minute={0, 30}),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = configure_worker_logging
    job_timeout = 180
