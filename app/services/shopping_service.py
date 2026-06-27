from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import uuid4

SHOPPING_SCOPE_TYPES = {"private", "group"}
SHOPPING_ITEM_STATUSES = {"active", "done"}


@dataclass(frozen=True)
class ShoppingItemInput:
    text: str
    quantity: Decimal | int | None = None
    unit: str | None = None
    note: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class ShoppingItemView:
    id: str
    text: str
    status: str
    quantity: Decimal | None = None
    unit: str | None = None
    note: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class ShoppingListView:
    scope_type: str
    scope_chat_id: int
    title: str
    active: list[ShoppingItemView]
    done: list[ShoppingItemView]


@dataclass
class StoredShoppingItem:
    id: str
    list_id: str
    text: str
    status: str
    created_by_user_id: int
    quantity: Decimal | None = None
    unit: str | None = None
    note: str | None = None
    category: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    done_at: datetime | None = None


@dataclass
class StoredShoppingList:
    id: str
    scope_type: str
    scope_chat_id: int
    owner_user_id: int | None
    title: str = "Список покупок"


class ShoppingRepositoryProtocol(Protocol):
    async def get_or_create_list(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        owner_user_id: int | None,
    ) -> StoredShoppingList:
        raise NotImplementedError

    async def list_items(self, list_id: str) -> list[StoredShoppingItem]:
        raise NotImplementedError

    async def add_items(
        self,
        *,
        shopping_list: StoredShoppingList,
        user_id: int,
        items: list[ShoppingItemInput],
    ) -> list[StoredShoppingItem]:
        raise NotImplementedError

    async def get_item(self, item_id: str) -> StoredShoppingItem | None:
        raise NotImplementedError

    async def get_list(self, list_id: str) -> StoredShoppingList | None:
        raise NotImplementedError

    async def set_item_status(self, item_id: str, status: str) -> None:
        raise NotImplementedError

    async def delete_item(self, item_id: str) -> StoredShoppingItem | None:
        raise NotImplementedError

    async def clear_done(self, *, scope_type: str, scope_chat_id: int) -> StoredShoppingList:
        raise NotImplementedError

    async def clear_all(self, *, scope_type: str, scope_chat_id: int) -> StoredShoppingList:
        raise NotImplementedError

    async def find_active_by_text(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        query: str,
    ) -> list[StoredShoppingItem]:
        raise NotImplementedError


class ShoppingService:
    def __init__(self, repository: ShoppingRepositoryProtocol) -> None:
        self.repository = repository

    @classmethod
    def in_memory(cls) -> ShoppingService:
        return cls(InMemoryShoppingRepository())

    async def add_items(
        self,
        scope: str,
        chat_id: int,
        user_id: int,
        items: Sequence[str | ShoppingItemInput],
    ) -> ShoppingListView:
        scope_type = _normalize_scope(scope)
        normalized_items = [_normalize_input_item(item) for item in items]
        normalized_items = [item for item in normalized_items if item.text]
        shopping_list = await self.repository.get_or_create_list(
            scope_type=scope_type,
            scope_chat_id=chat_id,
            owner_user_id=user_id if scope_type == "private" else None,
        )
        if normalized_items:
            await self.repository.add_items(
                shopping_list=shopping_list,
                user_id=user_id,
                items=normalized_items,
            )
        return await self._view(shopping_list)

    async def list_items(self, scope: str, chat_id: int) -> ShoppingListView:
        shopping_list = await self.repository.get_or_create_list(
            scope_type=_normalize_scope(scope),
            scope_chat_id=chat_id,
            owner_user_id=chat_id if scope == "private" else None,
        )
        return await self._view(shopping_list)

    async def mark_done(self, item_id: str, actor_user_id: int) -> ShoppingListView:
        del actor_user_id
        item = await self.repository.get_item(item_id)
        if item is None:
            return _empty_view()
        if item.status != "done":
            await self.repository.set_item_status(item.id, "done")
        return await self._view_by_list_id(item.list_id)

    async def restore_item(self, item_id: str, actor_user_id: int) -> ShoppingListView:
        del actor_user_id
        item = await self.repository.get_item(item_id)
        if item is None:
            return _empty_view()
        if item.status != "active":
            await self.repository.set_item_status(item.id, "active")
        return await self._view_by_list_id(item.list_id)

    async def delete_item(self, item_id: str, actor_user_id: int) -> ShoppingListView:
        del actor_user_id
        item = await self.repository.delete_item(item_id)
        if item is None:
            return _empty_view()
        return await self._view_by_list_id(item.list_id)

    async def delete_exact_text(
        self,
        scope: str,
        chat_id: int,
        query: str,
        actor_user_id: int,
    ) -> ShoppingListView | None:
        del actor_user_id
        matches = await self.repository.find_active_by_text(
            scope_type=_normalize_scope(scope),
            scope_chat_id=chat_id,
            query=_normalize_item(query),
        )
        if len(matches) != 1:
            return None
        await self.repository.delete_item(matches[0].id)
        return await self._view_by_list_id(matches[0].list_id)

    async def clear_done(
        self,
        scope: str,
        chat_id: int,
        actor_user_id: int,
    ) -> ShoppingListView:
        del actor_user_id
        shopping_list = await self.repository.clear_done(
            scope_type=_normalize_scope(scope),
            scope_chat_id=chat_id,
        )
        return await self._view(shopping_list)

    async def clear_all(
        self,
        scope: str,
        chat_id: int,
        actor_user_id: int,
    ) -> ShoppingListView:
        del actor_user_id
        shopping_list = await self.repository.clear_all(
            scope_type=_normalize_scope(scope),
            scope_chat_id=chat_id,
        )
        return await self._view(shopping_list)

    async def _view_by_list_id(self, list_id: str) -> ShoppingListView:
        shopping_list = await self.repository.get_list(list_id)
        if shopping_list is None:
            return _empty_view()
        return await self._view(shopping_list)

    async def _view(self, shopping_list: StoredShoppingList) -> ShoppingListView:
        items = await self.repository.list_items(shopping_list.id)
        active = [
            ShoppingItemView(
                id=item.id,
                text=item.text,
                status=item.status,
                quantity=item.quantity,
                unit=item.unit,
                note=item.note,
                category=item.category,
            )
            for item in items
            if item.status == "active"
        ]
        done = [
            ShoppingItemView(
                id=item.id,
                text=item.text,
                status=item.status,
                quantity=item.quantity,
                unit=item.unit,
                note=item.note,
                category=item.category,
            )
            for item in items
            if item.status == "done"
        ]
        return ShoppingListView(
            scope_type=shopping_list.scope_type,
            scope_chat_id=shopping_list.scope_chat_id,
            title=shopping_list.title,
            active=active,
            done=done,
        )


class InMemoryShoppingRepository:
    def __init__(self) -> None:
        self.lists: dict[str, StoredShoppingList] = {}
        self.scope_index: dict[tuple[str, int], str] = {}
        self.items: dict[str, StoredShoppingItem] = {}
        self.deleted_scope_by_item_id: dict[str, str] = {}

    async def get_or_create_list(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        owner_user_id: int | None,
    ) -> StoredShoppingList:
        key = (scope_type, scope_chat_id)
        existing_id = self.scope_index.get(key)
        if existing_id is not None:
            return self.lists[existing_id]
        list_id = uuid4().hex
        shopping_list = StoredShoppingList(
            id=list_id,
            scope_type=scope_type,
            scope_chat_id=scope_chat_id,
            owner_user_id=owner_user_id,
        )
        self.lists[list_id] = shopping_list
        self.scope_index[key] = list_id
        return shopping_list

    async def list_items(self, list_id: str) -> list[StoredShoppingItem]:
        return [
            item
            for item in self.items.values()
            if item.list_id == list_id
        ]

    async def add_items(
        self,
        *,
        shopping_list: StoredShoppingList,
        user_id: int,
        items: list[ShoppingItemInput],
    ) -> list[StoredShoppingItem]:
        created = []
        for item_input in items:
            item = StoredShoppingItem(
                id=uuid4().hex,
                list_id=shopping_list.id,
                text=item_input.text,
                status="active",
                created_by_user_id=user_id,
                quantity=_decimal_or_none(item_input.quantity),
                unit=item_input.unit,
                note=item_input.note,
                category=item_input.category,
            )
            self.items[item.id] = item
            created.append(item)
        return created

    async def get_item(self, item_id: str) -> StoredShoppingItem | None:
        return self.items.get(item_id)

    async def get_list(self, list_id: str) -> StoredShoppingList | None:
        return self.lists.get(list_id)

    async def set_item_status(self, item_id: str, status: str) -> None:
        item = self.items.get(item_id)
        if item is not None:
            item.status = status

    async def delete_item(self, item_id: str) -> StoredShoppingItem | None:
        item = self.items.pop(item_id, None)
        if item is not None:
            self.deleted_scope_by_item_id[item_id] = item.list_id
            return item
        list_id = self.deleted_scope_by_item_id.get(item_id)
        if list_id is None:
            return None
        return StoredShoppingItem(
            id=item_id,
            list_id=list_id,
            text="",
            status="done",
            created_by_user_id=0,
        )

    async def clear_done(self, *, scope_type: str, scope_chat_id: int) -> StoredShoppingList:
        shopping_list = await self.get_or_create_list(
            scope_type=scope_type,
            scope_chat_id=scope_chat_id,
            owner_user_id=scope_chat_id if scope_type == "private" else None,
        )
        for item_id, item in list(self.items.items()):
            if item.list_id == shopping_list.id and item.status == "done":
                del self.items[item_id]
        return shopping_list

    async def clear_all(self, *, scope_type: str, scope_chat_id: int) -> StoredShoppingList:
        shopping_list = await self.get_or_create_list(
            scope_type=scope_type,
            scope_chat_id=scope_chat_id,
            owner_user_id=scope_chat_id if scope_type == "private" else None,
        )
        for item_id, item in list(self.items.items()):
            if item.list_id == shopping_list.id:
                del self.items[item_id]
        return shopping_list

    async def find_active_by_text(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        query: str,
    ) -> list[StoredShoppingItem]:
        shopping_list = await self.get_or_create_list(
            scope_type=scope_type,
            scope_chat_id=scope_chat_id,
            owner_user_id=scope_chat_id if scope_type == "private" else None,
        )
        normalized = query.casefold()
        return [
            item
            for item in self.items.values()
            if item.list_id == shopping_list.id
            and item.status == "active"
            and item.text.casefold() == normalized
        ]


def _normalize_scope(scope: str) -> str:
    if scope not in SHOPPING_SCOPE_TYPES:
        raise ValueError("invalid_shopping_scope")
    return scope


def _normalize_item(item: str) -> str:
    return " ".join(item.strip().split())[:120]


def _normalize_input_item(item: str | ShoppingItemInput) -> ShoppingItemInput:
    if isinstance(item, ShoppingItemInput):
        return ShoppingItemInput(
            text=_normalize_item(item.text),
            quantity=_decimal_or_none(item.quantity),
            unit=_normalize_optional(item.unit),
            note=_normalize_optional(item.note),
            category=_normalize_optional(item.category) or categorize_shopping_item(item.text),
        )
    return parse_shopping_item(item)


def parse_shopping_item(raw_text: str) -> ShoppingItemInput:
    normalized = _normalize_item(raw_text)
    if not normalized:
        return ShoppingItemInput(text="", category="Другое")
    text = normalized
    notes: list[str] = []

    parenthetical_notes = re.findall(r"\(([^()]+)\)", text)
    for note in parenthetical_notes:
        cleaned = _normalize_item(note)
        if cleaned:
            notes.append(cleaned)
    text = re.sub(r"\([^()]+\)", " ", text)

    size_match = re.search(r"\bразмер\s+\S+", text, flags=re.IGNORECASE)
    if size_match:
        notes.append(_normalize_item(size_match.group(0)))
        text = (text[: size_match.start()] + " " + text[size_match.end() :]).strip()

    percent_match = re.search(r"\b\d+(?:[,.]\d+)?\s*%", text)
    if percent_match:
        notes.append(percent_match.group(0).replace(" ", ""))
        text = (text[: percent_match.start()] + " " + text[percent_match.end() :]).strip()

    quantity: Decimal | None = None
    unit: str | None = None
    quantity_match = re.search(
        r"\b(\d+(?:[,.]\d+)?)\s*(шт|кг|г|гр|бутылки|бутылка|бутылок|л|литр|литра|литров)\b",
        text,
        flags=re.IGNORECASE,
    )
    if quantity_match:
        quantity = _parse_decimal(quantity_match.group(1))
        unit = quantity_match.group(2).casefold()
        text = (text[: quantity_match.start()] + " " + text[quantity_match.end() :]).strip()

    text = _normalize_item(text)
    return ShoppingItemInput(
        text=text or normalized,
        quantity=quantity,
        unit=unit,
        note=", ".join(notes) or None,
        category=categorize_shopping_item(text or normalized),
    )


def categorize_shopping_item(text: str) -> str:
    normalized = text.casefold()
    rules = (
        ("Молочка", ("молоко", "сыр", "творог", "йогурт", "кефир", "майонез")),
        ("Хлеб", ("хлеб", "булка", "лаваш")),
        ("Ребёнок", ("памперс", "памперсы", "подгузник", "подгузники", "салфетки")),
        ("Мясо", ("мясо", "курица", "фарш")),
        ("Овощи", ("овощ", "картошка", "картофель", "морковь", "лук", "огур", "помидор")),
        ("Фрукты", ("фрукт", "яблок", "банан", "груш", "апельсин", "мандарин")),
    )
    for category, keywords in rules:
        if any(keyword in normalized for keyword in keywords):
            return category
    return "Другое"


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_item(value)
    return normalized or None


def _parse_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation:
        return None


def _decimal_or_none(value: Decimal | int | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def _empty_view() -> ShoppingListView:
    return ShoppingListView(
        scope_type="private",
        scope_chat_id=0,
        title="Список покупок",
        active=[],
        done=[],
    )
