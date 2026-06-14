from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.jobs import process_llm_message

settings = get_settings()


class WorkerSettings:
    functions = [process_llm_message]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 180
