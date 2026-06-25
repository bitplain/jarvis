from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import RuntimeSetting, utcnow
from app.services.runtime_settings_service import RuntimeSettingsUnavailable


def _is_missing_runtime_settings_table(exc: ProgrammingError) -> bool:
    rendered = str(exc)
    return "runtime_settings" in rendered and (
        "UndefinedTableError" in rendered or "does not exist" in rendered
    )


class RuntimeSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_value(self, key: str) -> str | None:
        try:
            result = await self.session.execute(
                select(RuntimeSetting).where(RuntimeSetting.key == key)
            )
        except ProgrammingError as exc:
            await self.session.rollback()
            if _is_missing_runtime_settings_table(exc):
                raise RuntimeSettingsUnavailable("runtime_settings_unavailable") from exc
            raise
        setting = result.scalar_one_or_none()
        return setting.value if setting is not None else None

    async def set_value(
        self,
        key: str,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> None:
        statement = (
            insert(RuntimeSetting)
            .values(
                key=key,
                value=value,
                updated_by_telegram_id=updated_by_telegram_id,
                updated_at=utcnow(),
            )
            .on_conflict_do_update(
                index_elements=[RuntimeSetting.key],
                set_={
                    "value": value,
                    "updated_by_telegram_id": updated_by_telegram_id,
                    "updated_at": utcnow(),
                },
            )
        )
        try:
            await self.session.execute(statement)
            await self.session.commit()
        except ProgrammingError as exc:
            await self.session.rollback()
            if _is_missing_runtime_settings_table(exc):
                raise RuntimeSettingsUnavailable("runtime_settings_unavailable") from exc
            raise
