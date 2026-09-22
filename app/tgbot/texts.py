from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta, timezone
from html import escape

from app.db.models import Expense, ExpenseCategory, ListAuditEvent, ListMember, ShoppingCategory, ShoppingItem, ShoppingList, User
from app.services.audit import PAGE_SIZE as AUDIT_PAGE_SIZE
from app.services.access import AccessLevel
from app.services.shopping import (
    EXPENSE_SOURCE_CASHBOX,
    EXPENSE_SPLIT_ALL,
    EXPENSE_SPLIT_ME,
    EXPENSE_SPLIT_SELECTED,
    MoneySummary,
    format_money_amount,
)


WELCOME_TEXT = (
    "<b>Life Helper</b>\n"
    "Общие и личные списки покупок и вещей. При необходимости — учёт денег."
)

HELP_TEXT = (
    "<b>Возможности</b>\n"
    "Разделы группируют пункты списка. Личные разделы видны всем участникам, но менять их может владелец раздела или списка.\n\n"
    "У каждого пункта есть отметка и свои настройки: название, раздел, удаление.\n\n"
    "Список может работать без цен или с учётом денег. Во втором режиме доступны покупки по товарам и чекам, "
    "взносы, траты и расчёты между участниками.\n\n"
    "Ссылка для участников — в настройках списка.\n\n"
    "Команды: /lists — все списки, /new — новый список, /cancel — отменить ввод."
)


def format_lists_text(owned: Sequence[ShoppingList], shared: Sequence[ShoppingList]) -> str:
    if not owned and not shared:
        return "<b>Списки</b>\nПока пусто"
    return f"<b>Списки</b>\nМои: {len(owned)} · По приглашению: {len(shared)}"


def format_list_text(
    shopping_list: ShoppingList,
    items: Sequence[ShoppingItem],
    level: AccessLevel,
    categories: Sequence[ShoppingCategory] = (),
) -> str:
    remaining = sum(not item.is_done for item in items)
    mode = "Список без цен" if shopping_list.prices_enabled is False else "Список с учётом денег"
    lines = [f"<b>{escape(shopping_list.title)}</b>", mode]
    if items:
        lines.append(f"Осталось: {remaining} из {len(items)}")
    else:
        lines.append("Пока пусто")
    return "\n".join(lines)


def format_full_list_pages(
    shopping_list: ShoppingList,
    items: Sequence[ShoppingItem],
    categories: Sequence[ShoppingCategory],
    *,
    user_id: int,
) -> list[str]:
    """Render every section and item, splitting only when Telegram's message limit requires it."""
    remaining = sum(not item.is_done for item in items)
    mode = "без цен" if shopping_list.prices_enabled is False else "с учётом денег"
    header = [
        f"<b>📄 {escape(shopping_list.title)}</b>",
        f"{mode} · осталось {remaining} из {len(items)}",
        "",
    ]
    groups: list[tuple[str, list[ShoppingItem]]] = []
    known_ids = {category.id for category in categories}
    items_by_category: dict[int, list[ShoppingItem]] = {}
    ungrouped: list[ShoppingItem] = []
    for item in items:
        if item.category_id is None or item.category_id not in known_ids:
            ungrouped.append(item)
        else:
            items_by_category.setdefault(item.category_id, []).append(item)
    for category in sorted(categories, key=lambda entry: (entry.scope != "common", entry.position, entry.id)):
        category_items = sorted(
            items_by_category.get(category.id, []),
            key=lambda entry: (entry.is_done, entry.position, entry.id),
        )
        if category.scope == "personal":
            owner = "мой" if category.owner_id == user_id else (
                _format_user_name(category.owner) if category.owner is not None else f"ID {category.owner_id}"
            )
            heading = f"👤 {escape(category.title)} · {owner}"
        else:
            heading = f"📁 {escape(category.title)}"
        if shopping_list.prices_enabled is not False:
            heading += f" · {_format_shopping_category_mode(category.accounting_mode)}"
        groups.append((f"<b>{heading}</b> · {sum(not item.is_done for item in category_items)}/{len(category_items)}", category_items))
    ungrouped.sort(key=lambda entry: (entry.is_done, entry.position, entry.id))
    if ungrouped:
        groups.append(("<b>📁 Без раздела</b>", ungrouped))
    if not groups:
        return ["\n".join([*header, "Пока пусто"])]

    pages: list[str] = []
    lines = header.copy()

    def fits(extra: str) -> bool:
        return len("\n".join([*lines, extra])) <= 3000

    def new_page() -> None:
        nonlocal lines
        pages.append("\n".join(lines).rstrip())
        lines = header.copy()

    for heading, category_items in groups:
        if not fits(f"\n{heading}"):
            new_page()
        lines.extend(["", heading])
        if not category_items:
            if not fits("Пока пусто"):
                new_page()
                lines.extend(["", heading])
            lines.append("Пока пусто")
            continue
        for item in category_items:
            item_line = f"{'✓' if item.is_done else '□'} {escape(item.text)}"
            if not fits(item_line):
                new_page()
                lines.extend(["", heading])
            lines.append(item_line)
    pages.append("\n".join(lines).rstrip())
    if len(pages) > 1:
        return [f"{page}\n\nСтраница {index} из {len(pages)}" for index, page in enumerate(pages, start=1)]
    return pages


def _format_shopping_category_heading(category: ShoppingCategory) -> str:
    mode = _format_shopping_category_mode(category.accounting_mode)
    if category.scope == "personal":
        owner = _format_user_name(category.owner) if category.owner is not None else f"ID {category.owner_id}"
        return f"{escape(category.title)}: {owner} ({mode})"
    return f"{escape(category.title)} ({mode})"


def _format_shopping_category_mode(accounting_mode: str) -> str:
    if accounting_mode == "receipt":
        return "покупки · один чек"
    if accounting_mode == "checklist":
        return "вещи"
    return "покупки · цена каждого товара"


def _format_shopping_category_kind(accounting_mode: str) -> str:
    if accounting_mode == "checklist":
        return "Список вещей"
    return "Список покупок"


def _format_shopping_category_accounting(accounting_mode: str) -> str | None:
    if accounting_mode == "receipt":
        return "по чеку"
    if accounting_mode == "per_item":
        return "по товарам"
    return None


def _format_item_lines(items: Sequence[ShoppingItem]) -> list[str]:
    sorted_items = sorted(items, key=lambda item: (item.is_done, item.position, item.id))
    lines = []
    for index, item in enumerate(sorted_items, start=1):
        mark = "✓" if item.is_done else "□"
        lines.append(f"{index}. {mark} {escape(item.text)}")
    return lines


def _format_user_name(user: User) -> str:
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part)
    if full_name and user.username:
        return f"{escape(full_name)} (@{escape(user.username)})"
    if full_name:
        return escape(full_name)
    if user.username:
        return f"@{escape(user.username)}"
    return f"ID {user.id}"


def format_members_text(
    shopping_list: ShoppingList,
    owner: User,
    members: Sequence[tuple[ListMember, User]],
) -> str:
    lines = [
        f"<b>Участники списка «{escape(shopping_list.title)}»</b>",
        "",
        f"Владелец: {_format_user_name(owner)}",
    ]
    if not members:
        lines.append("Участников по ссылке пока нет.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Участники:")
    for index, (_, user) in enumerate(members, start=1):
        lines.append(f"{index}. {_format_user_name(user)}")
    return "\n".join(lines)


def format_members_management_text(
    shopping_list: ShoppingList,
    members: Sequence[tuple[ListMember, User]],
) -> str:
    lines = [
        f"<b>Управление участниками «{escape(shopping_list.title)}»</b>",
        "",
    ]
    if not members:
        lines.append("Участников по ссылке пока нет.")
        return "\n".join(lines)

    lines.append("Участники:")
    for index, (_, user) in enumerate(members, start=1):
        lines.append(f"{index}. {_format_user_name(user)}")
    return "\n".join(lines)


def format_settings_text(shopping_list: ShoppingList) -> str:
    visibility = "по ссылке" if shopping_list.is_public else "закрыт"
    mode = "с учётом денег" if shopping_list.prices_enabled is not False else "без цен"
    return (
        f"<b>Настройки · {escape(shopping_list.title)}</b>\n"
        f"Режим: {mode}\n"
        f"Доступ: {visibility}"
    )


def _audit_short(value: str, limit: int = 100) -> str:
    cleaned = " ".join(value.split())
    escaped = ""
    for char in cleaned:
        fragment = escape(char)
        if len(escaped) + len(fragment) > limit - 1:
            return escaped + "…"
        escaped += fragment
    return escaped


def format_audit_text(
    shopping_list: ShoppingList,
    entries: Sequence[ListAuditEvent],
    actors: dict[int, User],
    *,
    total: int,
    page: int,
    filter_name: str,
    section_title: str | None = None,
) -> str:
    filter_titles = {
        "all": "Все события", "items": "Разделы и пункты", "money": "Деньги",
        "people": "Участники и доступ", "list": "Настройки списка",
    }
    heading = section_title or filter_titles.get(filter_name, "Все события")
    lines = [f"<b>Журнал · {escape(shopping_list.title)}</b>", _audit_short(heading),
             f"Событий: {total} · страница {page + 1} из {max(1, (total + AUDIT_PAGE_SIZE - 1) // AUDIT_PAGE_SIZE)} · время Минска", ""]
    if not entries:
        lines.append("Записей пока нет.")
    last_day = None
    for entry in entries:
        at = entry.occurred_at
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        at = at.astimezone(timezone(timedelta(hours=3)))
        if at.date() != last_day:
            lines.append(f"<b>{at:%d.%m.%Y}</b>")
            last_day = at.date()
        if entry.subject_type == "item":
            section = _audit_short(entry.section_title or
                                   (f"Раздел #{entry.section_id}" if entry.section_id else "Без раздела"), 40)
            path = f"Раздел «{section}» › пункт «{_audit_short(entry.subject_title, 60)}»"
        elif entry.subject_type == "section":
            path = f"Раздел «{_audit_short(entry.subject_title, 60)}»"
        elif entry.subject_type in {"expense", "expense_category", "contribution"}:
            path = f"Деньги › {_audit_short(entry.subject_title, 60)}"
        elif entry.subject_type in {"member", "access"}:
            path = f"Участники › {_audit_short(entry.subject_title, 60)}"
        else:
            path = "Настройки списка"
        actor = actors.get(entry.actor_id) if entry.actor_id is not None else None
        actor_text = (_audit_short(" ".join(part for part in (actor.first_name, actor.last_name) if part)
                                   or actor.username or f"ID {actor.id}", 50)
                      if actor is not None else (f"ID {entry.actor_id}" if entry.actor_id else "неизвестно"))
        archive = " · архив" if entry.origin == "legacy" else ""
        lines.append(f"{at:%H:%M} · {actor_text}{archive}\n"
                     f"↳ {path}\n"
                     f"   {_audit_short(entry.action, 90)}"
                     + (f" · {_audit_short(entry.details, 100)}" if entry.details else ""))
        lines.append("")
    lines.append("Архив восстановлен из сохранившихся записей. Прежние удаления и промежуточные правки недоступны.")
    return "\n".join(lines)


def _format_expense_title_with_category(expense: object) -> str:
    category = getattr(expense, "category", None)
    title = escape(getattr(expense, "title"))
    if category is None or category.title == expense.title:
        return title
    return f"{escape(category.title)}: {title}"


def _format_expense_meta(expense: object) -> str:
    split_count = len(getattr(expense, "shares"))
    source = getattr(expense, "source")
    if source == EXPENSE_SOURCE_CASHBOX:
        return f"касса, участников: {split_count}"
    return f"из кармана, платил {_format_user_name(getattr(expense, 'payer'))}, участников: {split_count}"


def format_expense_management_text(
    shopping_list: ShoppingList,
    expense: Expense,
    *,
    can_manage: bool,
    is_manual: bool,
) -> str:
    category = escape(expense.category.title) if expense.category is not None else "без категории"
    if expense.source == EXPENSE_SOURCE_CASHBOX:
        payment = "из кассы"
    else:
        payment = f"из кармана — {_format_user_name(expense.payer)}"
    participants = ", ".join(
        f"{_format_user_name(share.user)} ({format_money_amount(share.amount, shopping_list.currency)})"
        for share in expense.shares
    )
    author = _format_user_name(expense.created_by) if expense.created_by is not None else "неизвестен"
    lines = [
        f"<b>Трата: {escape(expense.title)}</b>",
        "",
        f"Сумма: {format_money_amount(expense.amount, shopping_list.currency)}",
        f"Категория: {category}",
        f"Оплата: {payment}",
        f"Участники: {participants or 'не выбраны'}",
        f"Автор записи: {author}",
    ]
    if not is_manual:
        lines.extend(["", "Трата связана с покупкой или чеком, поэтому отдельно редактировать её нельзя."])
    if not can_manage:
        lines.extend(["", "Изменять и удалять эту трату может только её автор или владелец списка."])
    return "\n".join(lines)


def _format_balance_action(balance: int, currency: str) -> str:
    if balance > 0:
        return f"получить {format_money_amount(balance, currency)}"
    if balance < 0:
        return f"оплатить {format_money_amount(-balance, currency)}"
    return "расчёт закрыт"


def format_money_text(summary: MoneySummary) -> str:
    currency = summary.shopping_list.currency
    lines = [
        f"<b>Деньги: {escape(summary.shopping_list.title)}</b>",
        f"В кассе сейчас: {format_money_amount(summary.cashbox_balance, currency)}",
        "",
        "<b>Взносы</b>",
    ]
    if summary.contributions:
        for contribution in summary.contributions:
            lines.append(
                f"- {_format_user_name(contribution.user)}: "
                f"{format_money_amount(contribution.amount, currency)}"
            )
    else:
        lines.append("Пока никто ничего не внёс.")

    lines.append("")
    lines.append("<b>Траты</b>")
    if summary.expenses:
        for expense in summary.expenses:
            lines.append(
                f"- {_format_expense_title_with_category(expense)}: {format_money_amount(expense.amount, currency)} "
                f"({_format_expense_meta(expense)})"
            )
    else:
        lines.append("Трат пока нет.")

    lines.append("")
    lines.append("<b>Расчёты</b>")
    for balance in summary.balances:
        lines.append(
            f"- {_format_user_name(balance.user)}: {_format_balance_action(balance.balance, currency)}"
        )
    return "\n".join(lines)


def format_categories_text(
    shopping_list: ShoppingList,
    categories: Sequence[ExpenseCategory],
) -> str:
    return f"<b>Категории трат · {escape(shopping_list.title)}</b>\nВсего: {len(categories)}"


def _format_expense_split_label(default_split: str) -> str:
    if default_split == EXPENSE_SPLIT_ALL:
        return "на всех"
    if default_split == EXPENSE_SPLIT_ME:
        return "только на меня"
    if default_split == EXPENSE_SPLIT_SELECTED:
        return "выбирать участников"
    return "выбирать участников"


def format_expense_category_text(
    shopping_list: ShoppingList,
    category: ExpenseCategory,
) -> str:
    return "\n".join(
        [
            f"<b>Категория трат: {escape(category.title)}</b>",
            f"Тусовка: {escape(shopping_list.title)}",
            f"Распределение: {_format_expense_split_label(category.default_split)}",
        ]
    )


def format_expense_category_split_text(category: ExpenseCategory) -> str:
    return "\n".join(
        [
            f"<b>Распределение: {escape(category.title)}</b>",
            f"Сейчас: {_format_expense_split_label(category.default_split)}",
        ]
    )


def format_shopping_categories_text(
    shopping_list: ShoppingList,
    categories: Sequence[ShoppingCategory],
) -> str:
    return f"<b>Разделы · {escape(shopping_list.title)}</b>\nВсего: {len(categories)}"


def format_shopping_category_text(
    category: ShoppingCategory,
    items: Sequence[ShoppingItem],
    *,
    can_add: bool = True,
) -> str:
    lines = [f"<b>{escape(category.title)}</b>"]
    if items:
        lines.append(f"Осталось: {sum(not item.is_done for item in items)} из {len(items)}")
    else:
        lines.append("Пока пусто")
    return "\n".join(lines)


def format_item_text(item: ShoppingItem) -> str:
    category = item.category
    section = escape(category.title) if category is not None else "Без раздела"
    return "\n".join(
        [
            f"<b>{escape(item.text)}</b>",
            f"Раздел: {section}",
            f"Статус: {'готово' if item.is_done else 'не отмечено'}",
        ]
    )


def format_shopping_category_settings_text(category: ShoppingCategory, *, prices_enabled: bool = True) -> str:
    lines = [
        f"<b>Настройки раздела · {escape(category.title)}</b>",
    ]
    if not prices_enabled:
        return "\n".join(lines)
    lines.append(f"Тип: {_format_shopping_category_kind(category.accounting_mode)}")
    accounting = _format_shopping_category_accounting(category.accounting_mode)
    if accounting is not None:
        lines.append(f"Расчёт: {accounting}")
    return "\n".join(
        lines
    )


def format_receipt_items_text(
    category: ShoppingCategory,
    items: Sequence[ShoppingItem],
    selected_item_ids: Sequence[int],
) -> str:
    return f"<b>Чек · {escape(category.title)}</b>\nВыбрано: {len(selected_item_ids)} из {len(items)}"


def format_money_final_text(summary: MoneySummary) -> str:
    currency = summary.shopping_list.currency
    lines = [
        f"<b>Итог: {escape(summary.shopping_list.title)}</b>",
        f"Остаток кассы: {format_money_amount(summary.cashbox_balance, currency)}",
        "",
        "<b>Расчёт по людям</b>",
    ]
    for balance in summary.balances:
        lines.append(
            f"- {_format_user_name(balance.user)}: внес "
            f"{format_money_amount(balance.contributed, currency)}, оплатил из своих "
            f"{format_money_amount(balance.paid_personal, currency)}, его доля "
            f"{format_money_amount(balance.share, currency)} → "
            f"{_format_balance_action(balance.balance, currency)}"
        )

    lines.append("")
    lines.append("<b>Переводы между участниками</b>")
    if summary.settlements:
        for settlement in summary.settlements:
            lines.append(
                f"- {_format_user_name(settlement.from_user)} -> {_format_user_name(settlement.to_user)}: "
                f"{format_money_amount(settlement.amount, currency)}"
            )
    else:
        lines.append("Переводов между участниками нет.")
    if summary.cashbox_balance != 0:
        lines.extend(["", "Остаток кассы учтите отдельно при окончательном расчёте."])
    return "\n".join(lines)
