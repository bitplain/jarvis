from typing import Any

import pytest

from app.db.repositories.telegram_access import TelegramAccessRepository
from app.services.telegram_access_service import AccessMutationResult


class FakeScalarResult:
    def __init__(self, value: int | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> int | None:
        return self.value


class FakeAsyncSession:
    def __init__(self, scalar_value: int | None) -> None:
        self.scalar_value = scalar_value
        self.executed: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.executed.append(statement)
        return FakeScalarResult(self.scalar_value)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_repository_upsert_entry_builds_conflict_update_statement() -> None:
    session = FakeAsyncSession(scalar_value=291844566)
    repository = TelegramAccessRepository(session)  # type: ignore[arg-type]

    result = await repository.upsert_entry(
        entry_type="user",
        telegram_id=291844566,
        label="Пользователь",
        created_by=100500,
    )

    assert result is AccessMutationResult.CREATED
    assert len(session.executed) == 1
    assert session.commits == 1
    assert session.rollbacks == 0
