from __future__ import annotations

import re
from typing import Any, Protocol

MAX_HOUSEHOLD_MEMORY_TEXT_LENGTH = 500
MAX_HOUSEHOLD_MEMORIES_PER_SCOPE = 100
SECRET_REJECTION_MESSAGE = "Похоже на секрет. Я не буду это сохранять."
SECRET_PATTERNS = (
    re.compile(r"\btoken\b", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\bapi[\s_-]*key\b", re.IGNORECASE),
    re.compile(r"\bauthorization\b", re.IGNORECASE),
)


class HouseholdMemorySecretRejected(ValueError):
    pass


class HouseholdMemoryLimitExceeded(ValueError):
    pass


class HouseholdMemoryEntryProtocol(Protocol):
    id: object
    scope_type: str
    scope_chat_id: int
    created_by_user_id: int
    text: str
    status: str


class HouseholdMemoryRepositoryProtocol(Protocol):
    async def active_count(self, *, scope_type: str, scope_chat_id: int) -> int:
        ...

    async def create(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        created_by_user_id: int,
        text: str,
    ) -> HouseholdMemoryEntryProtocol:
        ...

    async def list_active(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        limit: int = 100,
    ) -> list[HouseholdMemoryEntryProtocol]:
        ...

    async def soft_delete(
        self,
        *,
        memory_id: str,
        actor_user_id: int,
    ) -> HouseholdMemoryEntryProtocol | None:
        ...


class HouseholdMemoryService:
    def __init__(
        self,
        repository: Any,
        *,
        max_text_length: int = MAX_HOUSEHOLD_MEMORY_TEXT_LENGTH,
        max_entries_per_scope: int = MAX_HOUSEHOLD_MEMORIES_PER_SCOPE,
    ) -> None:
        self.repository: HouseholdMemoryRepositoryProtocol = repository
        self.max_text_length = max_text_length
        self.max_entries_per_scope = max_entries_per_scope

    async def add_memory(
        self,
        scope_type: str,
        chat_id: int,
        user_id: int,
        text: str,
    ) -> HouseholdMemoryEntryProtocol:
        normalized = normalize_memory_text(text)
        validate_scope(scope_type)
        if not normalized:
            raise ValueError("empty_memory")
        if len(normalized) > self.max_text_length:
            raise ValueError("memory_too_long")
        if looks_like_secret(normalized):
            raise HouseholdMemorySecretRejected("secret_rejected")
        active_count = await self.repository.active_count(
            scope_type=scope_type,
            scope_chat_id=chat_id,
        )
        if active_count >= self.max_entries_per_scope:
            raise HouseholdMemoryLimitExceeded("memory_limit_exceeded")
        return await self.repository.create(
            scope_type=scope_type,
            scope_chat_id=chat_id,
            created_by_user_id=user_id,
            text=normalized,
        )

    async def list_memories(
        self,
        scope_type: str,
        chat_id: int,
        *,
        limit: int = MAX_HOUSEHOLD_MEMORIES_PER_SCOPE,
    ) -> list[HouseholdMemoryEntryProtocol]:
        validate_scope(scope_type)
        return await self.repository.list_active(
            scope_type=scope_type,
            scope_chat_id=chat_id,
            limit=limit,
        )

    async def list_memory_texts_for_prompt(self, scope_type: str, chat_id: int) -> list[str]:
        memories = await self.list_memories(scope_type, chat_id, limit=20)
        selected: list[str] = []
        total = 0
        for memory in memories:
            next_len = len(memory.text) + 3
            if total + next_len > 2000:
                break
            selected.append(memory.text)
            total += next_len
        return selected

    async def delete_memory_by_id(
        self,
        memory_id: str,
        actor_user_id: int,
    ) -> HouseholdMemoryEntryProtocol | None:
        return await self.repository.soft_delete(
            memory_id=memory_id,
            actor_user_id=actor_user_id,
        )

    async def delete_memory_by_text(
        self,
        scope_type: str,
        chat_id: int,
        text: str,
        actor_user_id: int,
    ) -> list[HouseholdMemoryEntryProtocol]:
        query = normalize_memory_text(text).casefold()
        if not query:
            return []
        matches = [
            memory
            for memory in await self.list_memories(scope_type, chat_id)
            if query == memory.text.casefold() or query in memory.text.casefold()
        ]
        if len(matches) == 1:
            deleted = await self.delete_memory_by_id(str(matches[0].id), actor_user_id)
            return [deleted] if deleted is not None else []
        return matches


def validate_scope(scope_type: str) -> None:
    if scope_type not in {"private", "group"}:
        raise ValueError("invalid_scope")


def normalize_memory_text(text: str) -> str:
    return " ".join(text.strip().split())


def looks_like_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)
