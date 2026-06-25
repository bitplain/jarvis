from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import RuntimeSetting, utcnow


class RuntimeSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_value(self, key: str) -> str | None:
        result = await self.session.execute(select(RuntimeSetting).where(RuntimeSetting.key == key))
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
        await self.session.execute(statement)
        await self.session.commit()
