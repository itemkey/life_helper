from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Contribution, Expense, ExpenseShare, ListBannedMember, ListViewMessage, ShoppingItem
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
    assert [item.position for item in items] == [1, 2]

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


async def test_added_items_get_sequential_positions(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")

    first_items = await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Молоко\nХлеб")
    next_items = await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Сыр\nЯблоки")

    assert [item.position for item in first_items + next_items] == [1, 2, 3, 4]


async def test_set_all_items_done_updates_every_item(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    items = await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Молоко\nХлеб")
    await shopping.toggle_item(session, user_id=100, item_id=items[0].id)

    await shopping.set_all_items_done(session, user_id=100, list_id=shopping_list.id, is_done=True)
    _, view_items, _ = await shopping.get_list_view(session, user_id=100, list_id=shopping_list.id)
    assert [item.is_done for item in view_items] == [True, True]

    await shopping.set_all_items_done(session, user_id=100, list_id=shopping_list.id, is_done=False)
    _, view_items, _ = await shopping.get_list_view(session, user_id=100, list_id=shopping_list.id)
    assert [item.is_done for item in view_items] == [False, False]


async def test_private_list_is_not_accessible_to_other_user(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")

    with pytest.raises(AccessDenied):
        await shopping.get_list_view(session, user_id=200, list_id=shopping_list.id)


async def test_list_view_message_can_be_saved_updated_and_cleared(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")

    view_message = await shopping.save_list_view_message(
        session,
        list_id=shopping_list.id,
        user_id=100,
        chat_id=10,
        message_id=20,
    )
    assert view_message.chat_id == 10
    assert view_message.message_id == 20

    updated = await shopping.save_list_view_message(
        session,
        list_id=shopping_list.id,
        user_id=100,
        chat_id=11,
        message_id=21,
    )
    assert updated.chat_id == 11
    assert updated.message_id == 21

    await shopping.clear_list_view_message_by_message(session, user_id=100, chat_id=11, message_id=21)
    assert await session.get(ListViewMessage, (shopping_list.id, 100)) is None


async def test_public_update_view_only_returns_owner_and_active_members(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    await shopping.upsert_user(session, FakeTelegramUser(id=300))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Сок")

    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=100, chat_id=10, message_id=1)
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=200, chat_id=20, message_id=2)
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=300, chat_id=30, message_id=3)

    update_view = await shopping.get_public_list_update_view(session, list_id=shopping_list.id)

    assert update_view is not None
    _, items, view_messages = update_view
    assert [item.text for item in items] == ["Сок"]
    assert {message.user_id for message in view_messages} == {100, 200}

    await shopping.disable_public_access(session, owner_id=100, list_id=shopping_list.id)

    assert await shopping.get_public_list_update_view(session, list_id=shopping_list.id) is None
    assert await session.get(ListViewMessage, (shopping_list.id, 200)) is None


async def test_get_list_members_view_returns_owner_and_joined_members(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner", first_name="Owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member", first_name="Member"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)

    view, owner, members, level = await shopping.get_list_members_view(
        session,
        user_id=200,
        list_id=shopping_list.id,
    )

    assert view.id == shopping_list.id
    assert owner.id == 100
    assert level == AccessLevel.member
    assert [(member.user_id, member_user.username) for member, member_user in members] == [(200, "member")]


async def test_owner_can_remove_member_without_banning(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=200, chat_id=20, message_id=2)

    await shopping.remove_list_member(session, owner_id=100, list_id=shopping_list.id, member_user_id=200)

    with pytest.raises(AccessDenied):
        await shopping.get_list_view(session, user_id=200, list_id=shopping_list.id)
    assert await session.get(ListViewMessage, (shopping_list.id, 200)) is None
    assert await shopping.join_public_list_by_token(session, user_id=200, token=token) is not None


async def test_owner_can_ban_member_and_block_rejoin(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)

    await shopping.ban_list_member(session, owner_id=100, list_id=shopping_list.id, member_user_id=200)

    with pytest.raises(AccessDenied):
        await shopping.get_list_view(session, user_id=200, list_id=shopping_list.id)
    assert await session.get(ListBannedMember, (shopping_list.id, 200)) is not None
    assert await shopping.join_public_list_by_token(session, user_id=200, token=token) is None


async def test_member_cannot_manage_other_members(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    await shopping.upsert_user(session, FakeTelegramUser(id=300))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    await shopping.join_public_list_by_token(session, user_id=300, token=token)

    with pytest.raises(AccessDenied):
        await shopping.remove_list_member(session, owner_id=200, list_id=shopping_list.id, member_user_id=300)


async def test_personal_items_are_visible_but_only_owner_or_personal_owner_can_delete(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member"))
    await shopping.upsert_user(session, FakeTelegramUser(id=300, username="other"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    await shopping.join_public_list_by_token(session, user_id=300, token=token)

    personal_items = await shopping.add_items(
        session,
        user_id=200,
        list_id=shopping_list.id,
        text="Энергетик",
        scope=shopping.ITEM_SCOPE_PERSONAL,
    )

    _, owner_view_items, _ = await shopping.get_list_view(session, user_id=100, list_id=shopping_list.id)
    assert [(item.text, item.scope, item.personal_owner_id) for item in owner_view_items] == [
        ("Энергетик", shopping.ITEM_SCOPE_PERSONAL, 200)
    ]

    with pytest.raises(AccessDenied):
        await shopping.delete_item(session, user_id=300, item_id=personal_items[0].id)

    await shopping.delete_item(session, user_id=100, item_id=personal_items[0].id)
    _, owner_view_items, _ = await shopping.get_list_view(session, user_id=100, list_id=shopping_list.id)
    assert owner_view_items == []


async def test_item_purchase_creates_default_common_and_personal_expense_shares(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)

    common_item = (
        await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Сок")
    )[0]
    personal_item = (
        await shopping.add_items(
            session,
            user_id=200,
            list_id=shopping_list.id,
            text="Энергетик",
            scope=shopping.ITEM_SCOPE_PERSONAL,
        )
    )[0]

    await shopping.record_item_purchase(
        session,
        user_id=100,
        item_id=common_item.id,
        amount="10.01",
        source=shopping.EXPENSE_SOURCE_PERSONAL,
    )
    await shopping.record_item_purchase(
        session,
        user_id=100,
        item_id=personal_item.id,
        amount="5",
        source=shopping.EXPENSE_SOURCE_CASHBOX,
    )

    summary = await shopping.get_money_summary(session, user_id=100, list_id=shopping_list.id)
    assert summary.cashbox_balance == -500
    assert [(expense.title, expense.amount, expense.source) for expense in summary.expenses] == [
        ("Сок", 1001, shopping.EXPENSE_SOURCE_PERSONAL),
        ("Энергетик", 500, shopping.EXPENSE_SOURCE_CASHBOX),
    ]
    assert [
        (share.user_id, share.amount)
        for expense in summary.expenses
        for share in expense.shares
    ] == [(100, 501), (200, 500), (200, 500)]
    assert {balance.user.id: balance.balance for balance in summary.balances} == {100: 500, 200: -1000}


async def test_money_summary_tracks_contributions_sources_and_settlements(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)

    await shopping.create_contribution(session, user_id=100, list_id=shopping_list.id, amount="100")
    await shopping.create_expense(
        session,
        user_id=200,
        list_id=shopping_list.id,
        title="Такси",
        amount="30",
        source=shopping.EXPENSE_SOURCE_CASHBOX,
        share_user_ids=None,
    )

    summary = await shopping.get_money_summary(session, user_id=100, list_id=shopping_list.id)

    assert summary.cashbox_balance == 7000
    assert {balance.user.id: balance.balance for balance in summary.balances} == {100: 8500, 200: -1500}
    assert [(settlement.from_user.id, settlement.to_user.id, settlement.amount) for settlement in summary.settlements] == [
        (200, 100, 1500)
    ]


async def test_removed_member_cleanup_removes_personal_items_and_member_money(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    await shopping.add_items(
        session,
        user_id=200,
        list_id=shopping_list.id,
        text="Энергетик",
        scope=shopping.ITEM_SCOPE_PERSONAL,
    )
    await shopping.create_contribution(session, user_id=200, list_id=shopping_list.id, amount="50")
    await shopping.create_expense(
        session,
        user_id=200,
        list_id=shopping_list.id,
        title="Личный чек",
        amount="10",
        source=shopping.EXPENSE_SOURCE_PERSONAL,
        share_user_ids=[200],
    )

    await shopping.remove_list_member(session, owner_id=100, list_id=shopping_list.id, member_user_id=200)

    assert (await session.scalars(select(ShoppingItem))).all() == []
    assert (await session.scalars(select(Contribution))).all() == []
    assert (await session.scalars(select(Expense))).all() == []
    assert (await session.scalars(select(ExpenseShare))).all() == []
