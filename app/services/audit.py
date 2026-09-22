from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from app.db.models import (
    Contribution, Expense, ExpenseCategory, ListAuditEvent, ListBannedMember, ListMember,
    ShoppingCategory, ShoppingItem, ShoppingList, User,
)
from app.services.access import require_access


PAGE_SIZE = 6
FILTERS = {
    "all": None,
    "items": ("section", "item"),
    "money": ("expense_category", "expense", "contribution"),
    "people": ("member", "access"),
    "list": ("list",),
}


def add_event(
    session: AsyncSession | Session,
    *,
    list_id: int,
    actor_id: int | None,
    subject_type: str,
    subject_id: int | None,
    subject_title: str,
    action: str,
    section_id: int | None = None,
    previous_section_id: int | None = None,
    section_title: str | None = None,
    details: str | None = None,
) -> None:
    session.add(ListAuditEvent(
        list_id=list_id, actor_id=actor_id, subject_type=subject_type,
        subject_id=subject_id, subject_title=subject_title,
        section_id=section_id, previous_section_id=previous_section_id,
        section_title=section_title,
        action=action, details=details, origin="live",
    ))


def _actor_id(session: Session) -> int | None:
    return session.info.get("audit_actor_id")


def _old_new(obj: object, field: str) -> tuple[object | None, object | None] | None:
    history = inspect(obj).attrs[field].history
    if not history.has_changes():
        return None
    old = history.deleted[0] if history.deleted else None
    new = history.added[0] if history.added else getattr(obj, field)
    if old == new:
        return None
    return old, new


def _section(obj: ShoppingItem) -> tuple[int | None, str | None]:
    category = obj.__dict__.get("category")
    return obj.category_id, category.title if category is not None else None


def _money(value: object) -> str:
    return f"{int(value) / 100:.2f}" if value is not None else "?"


def _label(field: str, value: object) -> str:
    labels = {
        "accounting_mode": {"per_item": "по товарам", "receipt": "по чеку", "checklist": "без цен"},
        "default_split": {"all": "на всех", "selected": "на выбранных", "me": "на себя"},
        "source": {"cashbox": "из кассы", "personal": "из кармана"},
    }
    return labels.get(field, {}).get(value, str(value) if value is not None else "?")


@sqlalchemy_event.listens_for(Session, "before_flush")
def capture_audit_changes(session: Session, flush_context, instances) -> None:
    actor_id = _actor_id(session)
    deleted_lists = {obj.id for obj in session.deleted if isinstance(obj, ShoppingList)}
    for obj in tuple(session.dirty):
        if obj in session.deleted or not session.is_modified(obj, include_collections=False):
            continue
        if (obj.id if isinstance(obj, ShoppingList) else getattr(obj, "list_id", None)) in deleted_lists:
            continue
        if isinstance(obj, ShoppingList):
            for field, action in (
                ("title", "Переименован список"),
                ("prices_enabled", "Изменён режим списка"),
                ("is_public", "Изменён доступ"),
                ("cashbox_holder_id", "Изменён держатель кассы"),
            ):
                change = _old_new(obj, field)
                if change is None:
                    continue
                old, new = change
                if field == "prices_enabled":
                    details = "Учёт денег включён" if new else "Учёт денег выключен"
                elif field == "is_public":
                    details = "Доступ по ссылке открыт" if new else "Доступ по ссылке закрыт"
                else:
                    details = f"{old if old is not None else '?'} → {new}"
                add_event(session, list_id=obj.id, actor_id=actor_id, subject_type="list",
                          subject_id=obj.id, subject_title=obj.title, action=action, details=details)
        elif isinstance(obj, ShoppingCategory):
            for field, action in (("title", "Переименован раздел"), ("accounting_mode", "Изменён тип раздела")):
                change = _old_new(obj, field)
                if change:
                    add_event(session, list_id=obj.list_id, actor_id=actor_id, subject_type="section",
                              subject_id=obj.id, subject_title=obj.title, action=action,
                              details=f"{_label(field, change[0])} → {_label(field, change[1])}")
        elif isinstance(obj, ShoppingItem):
            section_id, section_title = _section(obj)
            for field, action in (("text", "Переименован пункт"), ("is_done", "Изменена отметка"),
                                  ("category_id", "Пункт перенесён в другой раздел")):
                change = _old_new(obj, field)
                if change is None:
                    continue
                if field == "is_done":
                    details = "Отмечен" if change[1] else "Отметка снята"
                elif field == "category_id":
                    category_history = inspect(obj).attrs.category.history
                    old_category = category_history.deleted[0] if category_history.deleted else None
                    old_title = old_category.title if old_category is not None else f"раздел #{change[0]}"
                    new_title = section_title or f"раздел #{change[1]}"
                    details = f"{old_title} → {new_title}"
                else:
                    details = f"{change[0] if change[0] is not None else '?'} → {change[1]}"
                add_event(session, list_id=obj.list_id, actor_id=actor_id, subject_type="item",
                          subject_id=obj.id, subject_title=obj.text, section_id=section_id,
                          previous_section_id=change[0] if field == "category_id" else None,
                          section_title=section_title, action=action, details=details)
        elif isinstance(obj, ExpenseCategory):
            for field, action in (("title", "Переименована категория трат"),
                                  ("default_split", "Изменено распределение трат")):
                change = _old_new(obj, field)
                if change:
                    add_event(session, list_id=obj.list_id, actor_id=actor_id,
                              subject_type="expense_category", subject_id=obj.id,
                              subject_title=obj.title, action=action,
                              details=f"{_label(field, change[0])} → {_label(field, change[1])}")
        elif isinstance(obj, Expense):
            for field, action in (("title", "Переименована трата"), ("amount", "Изменена сумма траты"),
                                  ("source", "Изменён источник оплаты"), ("payer_id", "Изменён плательщик"),
                                  ("category_id", "Изменена категория траты")):
                change = _old_new(obj, field)
                if change:
                    old, new = change
                    details = (f"{_money(old)} → {_money(new)}" if field == "amount"
                               else f"{_label(field, old)} → {_label(field, new)}")
                    add_event(session, list_id=obj.list_id, actor_id=actor_id, subject_type="expense",
                              subject_id=obj.id, subject_title=obj.title, action=action, details=details)
    for obj in tuple(session.deleted):
        if isinstance(obj, ShoppingList):
            continue
        if getattr(obj, "list_id", None) in deleted_lists:
            continue
        kind = None
        title = None
        section_id = None
        section_title = None
        if isinstance(obj, ShoppingItem):
            kind, title, action = "item", obj.text, "Удалён пункт"
            section_id, section_title = _section(obj)
        elif isinstance(obj, ShoppingCategory):
            kind, title, action = "section", obj.title, "Удалён раздел"
        elif isinstance(obj, Expense):
            kind, title, action = "expense", obj.title, "Удалена трата"
        elif isinstance(obj, ExpenseCategory):
            kind, title, action = "expense_category", obj.title, "Удалена категория трат"
        elif isinstance(obj, Contribution):
            kind, title, action = "contribution", f"Взнос участника {obj.user_id}", "Удалён взнос"
        elif isinstance(obj, ListMember):
            kind, title, action = "member", f"Участник {obj.user_id}", "Удалён из списка"
        if kind is not None:
            add_event(session, list_id=obj.list_id, actor_id=actor_id, subject_type=kind,
                      subject_id=getattr(obj, "id", None), subject_title=title, action=action,
                      section_id=section_id, section_title=section_title)


async def get_page(
    session: AsyncSession, *, owner_id: int, list_id: int, filter_name: str = "all",
    page: int = 0, section_id: int | None = None, item_id: int | None = None,
) -> tuple[ShoppingList, Sequence[ListAuditEvent], int, dict[int, User]]:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    kinds = FILTERS.get(filter_name)
    if filter_name not in FILTERS:
        filter_name = "all"
    conditions = [ListAuditEvent.list_id == list_id]
    if kinds is not None:
        conditions.append(ListAuditEvent.subject_type.in_(kinds))
    if section_id is not None:
        conditions.append((ListAuditEvent.section_id == section_id) |
                          (ListAuditEvent.previous_section_id == section_id) |
                          ((ListAuditEvent.subject_type == "section") & (ListAuditEvent.subject_id == section_id)))
    if item_id is not None:
        conditions.extend((ListAuditEvent.subject_type == "item", ListAuditEvent.subject_id == item_id))
    total = int(await session.scalar(select(func.count()).select_from(ListAuditEvent).where(*conditions)) or 0)
    page = min(max(page, 0), max((total - 1) // PAGE_SIZE, 0))
    entries = (await session.scalars(
        select(ListAuditEvent).where(*conditions)
        .order_by(ListAuditEvent.occurred_at.desc(), ListAuditEvent.id.desc())
        .limit(PAGE_SIZE).offset(page * PAGE_SIZE)
    )).all()
    actor_ids = {entry.actor_id for entry in entries if entry.actor_id is not None}
    users = (await session.scalars(select(User).where(User.id.in_(actor_ids)))).all() if actor_ids else []
    return shopping_list, entries, total, {user.id: user for user in users}


async def get_sections(session: AsyncSession, *, owner_id: int, list_id: int) -> tuple[ShoppingList, list[tuple[int, str]]]:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    current = (await session.execute(select(ShoppingCategory.id, ShoppingCategory.title).where(ShoppingCategory.list_id == list_id))).all()
    historical = (await session.execute(
        select(ListAuditEvent.subject_id, ListAuditEvent.subject_title)
        .where(ListAuditEvent.list_id == list_id, ListAuditEvent.subject_type == "section",
               ListAuditEvent.subject_id.is_not(None))
        .order_by(ListAuditEvent.id.desc())
    )).all()
    sections: dict[int, str] = {}
    for section_id, title in historical:
        sections.setdefault(section_id, title)
    sections.update({section_id: title for section_id, title in current})
    return shopping_list, sorted(sections.items(), key=lambda pair: pair[1].casefold())


async def get_items(session: AsyncSession, *, owner_id: int, list_id: int,
                    section_id: int) -> tuple[ShoppingList, list[tuple[int, str]]]:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    historical = (await session.execute(
        select(ListAuditEvent.subject_id, ListAuditEvent.subject_title)
        .where(ListAuditEvent.list_id == list_id, ListAuditEvent.subject_type == "item",
               (ListAuditEvent.section_id == section_id) |
               (ListAuditEvent.previous_section_id == section_id),
               ListAuditEvent.subject_id.is_not(None))
        .order_by(ListAuditEvent.id.desc())
    )).all()
    current = (await session.execute(
        select(ShoppingItem.id, ShoppingItem.text).where(
            ShoppingItem.list_id == list_id, ShoppingItem.category_id == section_id
        )
    )).all()
    items: dict[int, str] = {}
    for item_id, title in historical:
        items.setdefault(item_id, title)
    items.update({item_id: title for item_id, title in current})
    return shopping_list, sorted(items.items(), key=lambda pair: pair[1].casefold())
