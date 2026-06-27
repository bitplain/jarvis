from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import WebSearchCache, utcnow


class WebSearchCacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_fresh(
        self,
        *,
        provider: str,
        query_hash: str,
        now: datetime,
    ) -> list[dict[str, Any]] | None:
        result = await self.session.execute(
            select(WebSearchCache).where(
                WebSearchCache.provider == provider,
                WebSearchCache.query_hash == query_hash,
                WebSearchCache.expires_at > now,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return list(row.results_json)

    async def upsert(
        self,
        *,
        provider: str,
        query_hash: str,
        query_text: str,
        results_json: list[dict[str, Any]],
        expires_at: datetime,
    ) -> None:
        statement = (
            insert(WebSearchCache)
            .values(
                provider=provider,
                query_hash=query_hash,
                query_text=query_text,
                results_json=results_json,
                created_at=utcnow(),
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=[WebSearchCache.provider, WebSearchCache.query_hash],
                set_={
                    "query_text": query_text,
                    "results_json": results_json,
                    "created_at": utcnow(),
                    "expires_at": expires_at,
                },
            )
        )
        await self.session.execute(statement)
        await self.session.commit()
