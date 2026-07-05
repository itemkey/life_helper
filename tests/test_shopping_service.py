from __future__ import annotations

import pytest

from app.services import shopping
from app.services.access import AccessLevel
from app.services.errors import AccessDenied, ValidationError
from tests.conftest import FakeTelegramUser


async def test_owner_can_manage_shopping_list(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner"))

    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="  Дом  ")
    assert shopping_list.title == "Дом"

    items = await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Молоко\nХлеб")
    assert [item.text for item in items] == ["Молоко", "Хлеб"]

    await shopping.toggle_item(session, user_id=100, item_id=items[0].id)
    view, view_items, level = await shopping.get_list_view(session, user_id=100, list_id=shopping_list.id)
    assert view.title == "Дом"
    assert level == AccessLevel.owner
    assert view_items[0].is_done is True

    await shopping.delete_item(session, user_id=100, item_id=items[1].id)
    _, view_items, _ = await shopping.get_list_view(session, user_id=100, list_id=shopping_list.id)
    assert [item.text for item in view_items] == ["Молоко"]

    await shopping.rename_list(session, owner_id=100, list_id=shopping_list.id, title="Дача")
    assert shopping_list.title == "Дача"


async def test_validation_rejects_empty_values(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))

    with pytest.raises(ValidationError):
        await shopping.create_shopping_list(session, owner_id=100, title="   ")

    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    with pytest.raises(ValidationError):
        await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="\n")


async def test_private_list_is_not_accessible_to_other_user(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")

    with pytest.raises(AccessDenied):
        await shopping.get_list_view(session, user_id=200, list_id=shopping_list.id)
