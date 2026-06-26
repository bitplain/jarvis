from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.workers.jobs import deliver_due_reminders, process_llm_message

settings = get_settings()


async def configure_worker_logging(ctx: dict[object, object]) -> None:
    del ctx
    configure_logging(settings.log_level)


class WorkerSettings:
    functions = [process_llm_message, deliver_due_reminders]
    cron_jobs = [cron(deliver_due_reminders, second={0, 30})]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = configure_worker_logging
    job_timeout = 180
