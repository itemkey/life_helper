from __future__ import annotations

import pytest

from app.services import shopping
from app.services.access import AccessLevel
from app.services.errors import AccessDenied
from tests.conftest import FakeTelegramUser


async def test_public_token_adds_member_and_allows_item_editing(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")

    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    joined = await shopping.join_public_list_by_token(session, user_id=200, token=token)
    assert joined is not None
    assert joined.id == shopping_list.id

    _, _, level = await shopping.get_list_view(session, user_id=200, list_id=shopping_list.id)
    assert level == AccessLevel.member

    items = await shopping.add_items(session, user_id=200, list_id=shopping_list.id, text="Сок")
    await shopping.toggle_item(session, user_id=200, item_id=items[0].id)
    _, view_items, _ = await shopping.get_list_view(session, user_id=100, list_id=shopping_list.id)
    assert view_items[0].is_done is True


async def test_regenerated_link_invalidates_old_link_but_keeps_existing_member(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    await shopping.upsert_user(session, FakeTelegramUser(id=300))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")

    old_token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=old_token)
    new_token = await shopping.enable_public_access(
        session,
        owner_id=100,
        list_id=shopping_list.id,
        regenerate=True,
    )

    assert old_token != new_token
    assert await shopping.join_public_list_by_token(session, user_id=300, token=old_token) is None
    assert await shopping.join_public_list_by_token(session, user_id=300, token=new_token) is not None

    _, _, level = await shopping.get_list_view(session, user_id=200, list_id=shopping_list.id)
    assert level == AccessLevel.member


async def test_disabling_public_access_revokes_members(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)

    await shopping.disable_public_access(session, owner_id=100, list_id=shopping_list.id)

    assert await shopping.join_public_list_by_token(session, user_id=200, token=token) is None
    with pytest.raises(AccessDenied):
        await shopping.get_list_view(session, user_id=200, list_id=shopping_list.id)
