from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.db.models import ListAuditEvent, ShoppingList, User
from app.services import audit, shopping
from app.services.errors import AccessDenied
from app.tgbot.texts import format_audit_text
from tests.conftest import FakeTelegramUser


async def test_owner_sees_chronological_hierarchy_and_deleted_item_history(session):
    session.info["audit_actor_id"] = 100
    await shopping.upsert_user(session, FakeTelegramUser(id=100, first_name="Анна"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, first_name="Борис"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    category = await shopping.create_shopping_category(
        session, user_id=100, list_id=shopping_list.id, title="Продукты",
        scope=shopping.ITEM_SCOPE_COMMON,
    )
    item = (await shopping.add_items(
        session, user_id=100, list_id=shopping_list.id, category_id=category.id, text="Молоко"
    ))[0]
    await shopping.rename_item(session, user_id=100, item_id=item.id, title="Молоко 2")
    other_category = await shopping.create_shopping_category(
        session, user_id=100, list_id=shopping_list.id, title="На дачу",
        scope=shopping.ITEM_SCOPE_COMMON,
    )
    await shopping.move_item(session, user_id=100, item_id=item.id, category_id=other_category.id)
    await shopping.move_item(session, user_id=100, item_id=item.id, category_id=category.id)
    await shopping.toggle_item(session, user_id=100, item_id=item.id)
    await shopping.delete_item(session, user_id=100, item_id=item.id)
    await session.commit()

    _, events, total, actors = await audit.get_page(
        session, owner_id=100, list_id=shopping_list.id, filter_name="items", section_id=category.id
    )
    assert total >= 5
    assert [entry.action for entry in events[:3]] == [
        "Удалён пункт", "Изменена отметка", "Пункт перенесён в другой раздел"
    ]
    assert sum(entry.action == "Пункт перенесён в другой раздел" for entry in events) == 2
    assert all(entry.actor_id == 100 for entry in events)
    assert all(entry.section_id == category.id or entry.previous_section_id == category.id
               for entry in events if entry.subject_type == "item")
    text = format_audit_text(shopping_list, events, actors, total=total, page=0,
                             filter_name="items", section_title=category.title)
    assert "Раздел «Продукты» › пункт «Молоко 2»" in text
    assert "Удалён пункт" in text
    assert "Анна" in text
    _, historical_items = await audit.get_items(
        session, owner_id=100, list_id=shopping_list.id, section_id=category.id
    )
    assert historical_items == [(item.id, "Молоко 2")]

    with pytest.raises(AccessDenied):
        await audit.get_page(session, owner_id=200, list_id=shopping_list.id)


async def test_audit_is_rolled_back_with_list_changes(session):
    session.info["audit_actor_id"] = 100
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Черновик")
    await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Хлеб")
    await session.rollback()

    assert await session.scalar(select(func.count()).select_from(ListAuditEvent)) == 0


async def test_deleting_list_cascades_audit_without_foreign_key_errors(session):
    session.info["audit_actor_id"] = 100
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Временный")
    await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Пункт")
    await session.commit()

    await shopping.delete_list(session, owner_id=100, list_id=shopping_list.id)
    await session.commit()
    assert await session.scalar(select(func.count()).select_from(ListAuditEvent)) == 0


async def test_member_removal_keeps_hierarchy_of_removed_personal_records(session):
    session.info["audit_actor_id"] = 100
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Поездка")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    item = (await shopping.add_items(
        session, user_id=200, list_id=shopping_list.id, text="Личная вещь",
        scope=shopping.ITEM_SCOPE_PERSONAL,
    ))[0]
    expense = await shopping.create_expense(
        session, user_id=100, list_id=shopping_list.id, title="Общая трата",
        amount="10", source=shopping.EXPENSE_SOURCE_CASHBOX,
    )
    section_id = item.category_id
    await session.commit()

    await shopping.remove_list_member(session, owner_id=100, list_id=shopping_list.id,
                                      member_user_id=200)
    await session.commit()
    _, events, _, _ = await audit.get_page(
        session, owner_id=100, list_id=shopping_list.id, filter_name="items",
        section_id=section_id,
    )
    assert any(entry.subject_id == item.id and entry.action == "Добавлен пункт" for entry in events)
    assert any(entry.subject_id == item.id and entry.action == "Удалён при исключении участника"
               for entry in events)
    _, items = await audit.get_items(session, owner_id=100, list_id=shopping_list.id,
                                     section_id=section_id)
    assert items == [(item.id, "Личная вещь")]
    _, money_events, _, _ = await audit.get_page(
        session, owner_id=100, list_id=shopping_list.id, filter_name="money"
    )
    assert any(entry.subject_id == expense.id and entry.action == "Удалена доля исключённого участника"
               for entry in money_events)


async def test_mode_and_money_edits_are_recorded_in_order(session):
    session.info["audit_actor_id"] = 100
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    await shopping.set_list_prices_enabled(session, owner_id=100, list_id=shopping_list.id,
                                           enabled=False)
    await shopping.set_list_prices_enabled(session, owner_id=100, list_id=shopping_list.id,
                                           enabled=True)
    expense = await shopping.create_expense(
        session, user_id=100, list_id=shopping_list.id, title="Транспорт", amount="5",
        source=shopping.EXPENSE_SOURCE_CASHBOX,
    )
    await shopping.update_expense_title(session, user_id=100, expense_id=expense.id,
                                        title="Такси")
    await shopping.update_expense_amount(session, user_id=100, expense_id=expense.id,
                                         amount="7")
    await shopping.delete_expense(session, user_id=100, expense_id=expense.id)
    await session.commit()

    _, money_events, _, _ = await audit.get_page(
        session, owner_id=100, list_id=shopping_list.id, filter_name="money"
    )
    assert [entry.action for entry in money_events[:4]] == [
        "Удалена трата", "Изменена сумма траты", "Переименована трата", "Записана трата"
    ]
    assert money_events[1].details == "5.00 → 7.00"
    _, list_events, _, _ = await audit.get_page(
        session, owner_id=100, list_id=shopping_list.id, filter_name="list"
    )
    assert [entry.details for entry in list_events[:2]] == [
        "Учёт денег включён", "Учёт денег выключен"
    ]


def test_audit_page_fits_telegram_message_even_with_html_heavy_names():
    shopping_list = ShoppingList(id=1, owner_id=100, title="<" * 120)
    actor = User(id=100, first_name="<" * 128)
    entries = [ListAuditEvent(
        list_id=1, actor_id=100, occurred_at=datetime.now(timezone.utc),
        subject_type="item", subject_id=index, subject_title="<" * 255,
        section_id=10, section_title="<" * 80, action="<" * 255,
        details="<" * 500, origin="live",
    ) for index in range(audit.PAGE_SIZE)]
    rendered = format_audit_text(shopping_list, entries, {100: actor}, total=6,
                                 page=0, filter_name="all")
    assert len(rendered) < 4096
    assert "&lt;" in rendered


async def test_deleting_purchased_item_records_lost_expense_link(session):
    session.info["audit_actor_id"] = 100
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    item = (await shopping.add_items(session, user_id=100, list_id=shopping_list.id,
                                     text="Молоко"))[0]
    await shopping.record_item_purchase(
        session, user_id=100, item_id=item.id, amount="10",
        source=shopping.EXPENSE_SOURCE_CASHBOX,
    )
    await shopping.delete_item(session, user_id=100, item_id=item.id)
    await session.commit()
    _, events, _, _ = await audit.get_page(
        session, owner_id=100, list_id=shopping_list.id, filter_name="money"
    )
    assert any(entry.action == "Связь с пунктом удалена" and entry.details == "Молоко"
               for entry in events)
