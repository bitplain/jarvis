import pytest

from app.services.shopping_service import ShoppingItemInput, ShoppingService, parse_shopping_item


@pytest.mark.asyncio
async def test_shopping_private_and_group_lists_are_scoped() -> None:
    service = ShoppingService.in_memory()

    private_view = await service.add_items("private", 100500, 100500, ["хлеб"])
    group_view = await service.add_items("group", -100123, 100500, ["молоко"])

    assert private_view.scope_type == "private"
    assert private_view.scope_chat_id == 100500
    assert [item.text for item in private_view.active] == ["хлеб"]
    assert group_view.scope_type == "group"
    assert group_view.scope_chat_id == -100123
    assert [item.text for item in group_view.active] == ["молоко"]


def test_parse_shopping_v2_quantity_note_and_category() -> None:
    assert parse_shopping_item("молоко 2 шт") == ShoppingItemInput(
        text="молоко",
        quantity=2,
        unit="шт",
        category="Молочка",
    )
    assert parse_shopping_item("яблоки 1 кг") == ShoppingItemInput(
        text="яблоки",
        quantity=1,
        unit="кг",
        category="Фрукты",
    )
    assert parse_shopping_item("памперсы размер 4") == ShoppingItemInput(
        text="памперсы",
        note="размер 4",
        category="Ребёнок",
    )
    assert parse_shopping_item("молоко 2.5% 2 бутылки") == ShoppingItemInput(
        text="молоко",
        quantity=2,
        unit="бутылки",
        note="2.5%",
        category="Молочка",
    )


@pytest.mark.asyncio
async def test_shopping_item_lifecycle_and_repeated_callbacks_are_safe() -> None:
    service = ShoppingService.in_memory()
    view = await service.add_items("private", 100500, 100500, ["молоко", "яйца"])
    item_id = view.active[0].id

    done = await service.mark_done(item_id, 100500)
    repeated_done = await service.mark_done(item_id, 100500)
    restored = await service.restore_item(item_id, 100500)
    deleted = await service.delete_item(item_id, 100500)
    repeated_delete = await service.delete_item(item_id, 100500)

    assert [item.text for item in done.done] == ["молоко"]
    assert [item.text for item in repeated_done.done] == ["молоко"]
    assert [item.text for item in restored.active] == ["молоко", "яйца"]
    assert [item.text for item in deleted.active] == ["яйца"]
    assert [item.text for item in repeated_delete.active] == ["яйца"]


@pytest.mark.asyncio
async def test_shopping_service_preserves_structured_item_fields() -> None:
    service = ShoppingService.in_memory()

    view = await service.add_items("private", 100500, 100500, ["молоко 2 шт", "хлеб"])

    assert view.active[0].text == "молоко"
    assert view.active[0].quantity == 2
    assert view.active[0].unit == "шт"
    assert view.active[0].category == "Молочка"
    assert view.active[1].text == "хлеб"
    assert view.active[1].quantity is None
    assert view.active[1].category == "Хлеб"


@pytest.mark.asyncio
async def test_shopping_clear_done() -> None:
    service = ShoppingService.in_memory()
    view = await service.add_items("group", -100123, 100500, ["хлеб", "сыр"])
    await service.mark_done(view.active[0].id, 100500)

    cleared = await service.clear_done("group", -100123, 100500)

    assert [item.text for item in cleared.active] == ["сыр"]
    assert cleared.done == []
