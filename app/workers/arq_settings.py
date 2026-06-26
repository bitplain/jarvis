from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings
from app.workers.jobs import deliver_due_reminders, process_llm_message

settings = get_settings()


class WorkerSettings:
    functions = [process_llm_message, deliver_due_reminders]
    cron_jobs = [cron(deliver_due_reminders, second={0, 30})]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 180
