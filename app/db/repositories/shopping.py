from uuid import UUID

from sqlalchemy import cast, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select
from sqlalchemy.sql.sqltypes import String

from app.db.models import ShoppingList, ShoppingListItem, utcnow
from app.services.shopping_service import StoredShoppingItem, StoredShoppingList


class ShoppingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_list(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        owner_user_id: int | None,
    ) -> StoredShoppingList:
        now = utcnow()
        statement = (
            insert(ShoppingList)
            .values(
                scope_type=scope_type,
                scope_chat_id=scope_chat_id,
                owner_user_id=owner_user_id,
                title="Список покупок",
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[ShoppingList.scope_type, ShoppingList.scope_chat_id],
            )
        )
        await self.session.execute(statement)
        await self.session.commit()
        result = await self.session.execute(
            select(ShoppingList).where(
                ShoppingList.scope_type == scope_type,
                ShoppingList.scope_chat_id == scope_chat_id,
            )
        )
        shopping_list = result.scalar_one()
        return _list_to_stored(shopping_list)

    async def list_items(self, list_id: str) -> list[StoredShoppingItem]:
        result = await self.session.execute(
            select(ShoppingListItem)
            .where(ShoppingListItem.list_id == _uuid(list_id))
            .order_by(ShoppingListItem.created_at)
        )
        return [_item_to_stored(item) for item in result.scalars().all()]

    async def add_items(
        self,
        *,
        shopping_list: StoredShoppingList,
        user_id: int,
        items: list[str],
    ) -> list[StoredShoppingItem]:
        now = utcnow()
        rows = [
            ShoppingListItem(
                list_id=_uuid(shopping_list.id),
                text=item,
                status="active",
                created_by_user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            for item in items
        ]
        self.session.add_all(rows)
        await self.session.commit()
        for row in rows:
            await self.session.refresh(row)
        return [_item_to_stored(row) for row in rows]

    async def get_item(self, item_id: str) -> StoredShoppingItem | None:
        item = await self._get_item_model(item_id)
        return _item_to_stored(item) if item is not None else None

    async def get_list(self, list_id: str) -> StoredShoppingList | None:
        result = await self.session.execute(
            select(ShoppingList).where(ShoppingList.id == _uuid(list_id))
        )
        shopping_list = result.scalar_one_or_none()
        return _list_to_stored(shopping_list) if shopping_list is not None else None

    async def set_item_status(self, item_id: str, status: str) -> None:
        item = await self._get_item_model(item_id)
        if item is None:
            return
        item.status = status
        item.updated_at = utcnow()
        item.done_at = utcnow() if status == "done" else None
        await self.session.commit()

    async def delete_item(self, item_id: str) -> StoredShoppingItem | None:
        item = await self._get_item_model(item_id)
        if item is None:
            return None
        stored = _item_to_stored(item)
        await self.session.delete(item)
        await self.session.commit()
        return stored

    async def clear_done(self, *, scope_type: str, scope_chat_id: int) -> StoredShoppingList:
        shopping_list = await self.get_or_create_list(
            scope_type=scope_type,
            scope_chat_id=scope_chat_id,
            owner_user_id=scope_chat_id if scope_type == "private" else None,
        )
        await self.session.execute(
            delete(ShoppingListItem).where(
                ShoppingListItem.list_id == _uuid(shopping_list.id),
                ShoppingListItem.status == "done",
            )
        )
        await self.session.commit()
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
        result = await self.session.execute(
            select(ShoppingListItem)
            .where(
                ShoppingListItem.list_id == _uuid(shopping_list.id),
                ShoppingListItem.status == "active",
                ShoppingListItem.text == query,
            )
            .order_by(ShoppingListItem.created_at)
        )
        return [_item_to_stored(item) for item in result.scalars().all()]

    async def _get_item_model(self, item_id: str) -> ShoppingListItem | None:
        parsed = _uuid_or_none(item_id)
        if parsed is not None:
            result = await self.session.execute(
                select(ShoppingListItem).where(ShoppingListItem.id == parsed)
            )
        else:
            result = await self.session.execute(
                select(ShoppingListItem)
                .where(cast(ShoppingListItem.id, String).like(f"{item_id}%"))
                .order_by(ShoppingListItem.created_at)
                .limit(1)
            )
        return result.scalar_one_or_none()


def _uuid(value: str) -> UUID:
    return UUID(value)


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _list_to_stored(shopping_list: ShoppingList) -> StoredShoppingList:
    return StoredShoppingList(
        id=shopping_list.id.hex,
        scope_type=shopping_list.scope_type,
        scope_chat_id=shopping_list.scope_chat_id,
        owner_user_id=shopping_list.owner_user_id,
        title=shopping_list.title,
    )


def _item_to_stored(item: ShoppingListItem) -> StoredShoppingItem:
    return StoredShoppingItem(
        id=item.id.hex,
        list_id=item.list_id.hex,
        text=item.text,
        status=item.status,
        created_by_user_id=item.created_by_user_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        done_at=item.done_at,
    )
