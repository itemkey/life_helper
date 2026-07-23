from __future__ import annotations

from collections.abc import Sequence
from html import escape

from app.db.models import ExpenseCategory, ListMember, ShoppingCategory, ShoppingItem, ShoppingList, User
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
    "Привет. Я Life Helper.\n\n"
    "Теперь можно вести тусовки: общий список, личные хотелки, категории покупок, чеки, взносы, траты и честный итог по деньгам."
)

HELP_TEXT = (
    "Команды:\n"
    "/lists - открыть мои тусовки\n"
    "/new - создать тусовку\n"
    "/cancel - отменить текущий ввод\n\n"
    "Ссылка дает доступ только к конкретной тусовке. Участник может добавлять покупки в общее и в свои личные категории. "
    "Деньги считаются по взносам, тратам из кассы и оплатам из своих."
)


def format_lists_text(owned: Sequence[ShoppingList], shared: Sequence[ShoppingList]) -> str:
    if not owned and not shared:
        return "У тебя пока нет тусовок. Создай первую."

    lines = ["<b>Твои тусовки</b>"]
    if owned:
        lines.append("\nМои:")
        lines.extend(f"- {escape(item.title)}" for item in owned)
    if shared:
        lines.append("\nДоступные по ссылке:")
        lines.extend(f"- {escape(item.title)}" for item in shared)
    return "\n".join(lines)


def format_list_text(
    shopping_list: ShoppingList,
    items: Sequence[ShoppingItem],
    level: AccessLevel,
    categories: Sequence[ShoppingCategory] = (),
) -> str:
    role = "владелец" if level == AccessLevel.owner else "участник"
    visibility = "публичный" if shopping_list.is_public else "приватный"
    lines = [
        f"<b>{escape(shopping_list.title)}</b>",
        f"Статус: {visibility}. Твоя роль: {role}.",
        "",
    ]
    if not items:
        lines.append("Тусовка пока пустая. Добавь продукты в категорию покупок.")
        return "\n".join(lines)

    categorized_items: dict[int, list[ShoppingItem]] = {}
    uncategorized_items: list[ShoppingItem] = []
    for item in items:
        if item.category_id is None:
            uncategorized_items.append(item)
        else:
            categorized_items.setdefault(item.category_id, []).append(item)

    shown_category_ids: set[int] = set()
    ordered_categories = sorted(categories, key=lambda category: (category.scope != "common", category.position, category.id))
    for category in ordered_categories:
        category_items = categorized_items.get(category.id, [])
        if not category_items:
            continue
        if shown_category_ids:
            lines.append("")
        lines.append(f"<b>{_format_shopping_category_heading(category)}</b>")
        lines.extend(_format_item_lines(category_items))
        shown_category_ids.add(category.id)

    leftover_category_ids = [category_id for category_id in categorized_items if category_id not in shown_category_ids]
    for category_id in leftover_category_ids:
        if shown_category_ids:
            lines.append("")
        category_items = categorized_items[category_id]
        category = category_items[0].category
        lines.append(f"<b>{_format_shopping_category_heading(category) if category is not None else 'Покупки'}</b>")
        lines.extend(_format_item_lines(category_items))
        shown_category_ids.add(category_id)

    if uncategorized_items:
        if shown_category_ids:
            lines.append("")
        lines.append("<b>Без категории</b>")
        lines.extend(_format_item_lines(uncategorized_items))
    return "\n".join(lines)


def _format_shopping_category_heading(category: ShoppingCategory) -> str:
    mode = _format_shopping_category_mode(category.accounting_mode)
    if category.scope == "personal":
        owner = _format_user_name(category.owner) if category.owner is not None else f"ID {category.owner_id}"
        return f"{escape(category.title)}: {owner} ({mode})"
    return f"{escape(category.title)} ({mode})"


def _format_shopping_category_mode(accounting_mode: str) -> str:
    if accounting_mode == "receipt":
        return "по чеку"
    if accounting_mode == "checklist":
        return "вещи взять"
    return "по товару"


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

    lines.append("Выбери действие для участника:")
    for index, (_, user) in enumerate(members, start=1):
        lines.append(f"{index}. {_format_user_name(user)}")
    return "\n".join(lines)


def format_settings_text(shopping_list: ShoppingList) -> str:
    visibility = "публичный" if shopping_list.is_public else "приватный"
    return (
        f"<b>Настройки тусовки</b>\n"
        f"Название: {escape(shopping_list.title)}\n"
        f"Статус: {visibility}"
    )


def _format_expense_title_with_category(expense: object) -> str:
    category = getattr(expense, "category", None)
    title = escape(getattr(expense, "title"))
    if category is None:
        return title
    return f"{escape(category.title)}: {title}"


def _format_expense_meta(expense: object) -> str:
    split_count = len(getattr(expense, "shares"))
    source = getattr(expense, "source")
    if source == EXPENSE_SOURCE_CASHBOX:
        return f"касса, долей: {split_count}"
    return f"из своих, платил {_format_user_name(getattr(expense, 'payer'))}, долей: {split_count}"


def _format_balance_action(balance: int, currency: str) -> str:
    if balance > 0:
        return f"вернуть {format_money_amount(balance, currency)}"
    if balance < 0:
        return f"доплатить {format_money_amount(-balance, currency)}"
    return "ровно"


def format_money_text(summary: MoneySummary) -> str:
    currency = summary.shopping_list.currency
    lines = [
        f"<b>Деньги: {escape(summary.shopping_list.title)}</b>",
        f"Остаток кассы: {format_money_amount(summary.cashbox_balance, currency)}",
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
    lines.append("<b>Баланс</b>")
    for balance in summary.balances:
        lines.append(
            f"- {_format_user_name(balance.user)}: {_format_balance_action(balance.balance, currency)}"
        )
    return "\n".join(lines)


def format_categories_text(
    shopping_list: ShoppingList,
    categories: Sequence[ExpenseCategory],
) -> str:
    lines = [
        f"<b>Категории трат: {escape(shopping_list.title)}</b>",
        "",
    ]
    if categories:
        lines.append("Выбери категорию для новой траты или добавь свою.")
        lines.append("")
        for index, category in enumerate(categories, start=1):
            lines.append(f"{index}. {escape(category.title)} — {_format_expense_split_label(category.default_split)}")
    else:
        lines.append("Категорий пока нет. Добавь любую: такси, маршрутка, автобус, доставка, билеты.")
    return "\n".join(lines)


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
            "",
            "Выбери, как обычно делить траты этой категории.",
        ]
    )


def format_shopping_categories_text(
    shopping_list: ShoppingList,
    categories: Sequence[ShoppingCategory],
) -> str:
    lines = [
        f"<b>Категории покупок: {escape(shopping_list.title)}</b>",
        "",
    ]
    if not categories:
        lines.append("Категорий покупок пока нет.")
        return "\n".join(lines)

    for index, category in enumerate(categories, start=1):
        lines.append(f"{index}. {_format_shopping_category_heading(category)}")
    return "\n".join(lines)


def format_shopping_category_text(
    category: ShoppingCategory,
    items: Sequence[ShoppingItem],
) -> str:
    lines = [
        f"<b>{_format_shopping_category_heading(category)}</b>",
        "",
    ]
    if items:
        lines.extend(_format_item_lines(items))
    else:
        lines.append("В этой категории пока пусто.")
    return "\n".join(lines)


def format_shopping_category_settings_text(category: ShoppingCategory) -> str:
    return "\n".join(
        [
            f"<b>Настройки: {_format_shopping_category_heading(category)}</b>",
            "",
            f"Режим: {_format_shopping_category_mode(category.accounting_mode)}.",
        ]
    )


def format_receipt_items_text(
    category: ShoppingCategory,
    items: Sequence[ShoppingItem],
    selected_item_ids: Sequence[int],
) -> str:
    selected = set(selected_item_ids)
    lines = [
        f"<b>Чек: {_format_shopping_category_heading(category)}</b>",
        "",
    ]
    if not items:
        lines.append("В этой категории нет некупленных товаров для чека.")
        return "\n".join(lines)
    for index, item in enumerate(items, start=1):
        mark = "✓" if item.id in selected else "□"
        lines.append(f"{index}. {mark} {escape(item.text)}")
    return "\n".join(lines)


def format_money_final_text(summary: MoneySummary) -> str:
    currency = summary.shopping_list.currency
    lines = [
        f"<b>Итог: {escape(summary.shopping_list.title)}</b>",
        f"Остаток кассы: {format_money_amount(summary.cashbox_balance, currency)}",
        "",
        "<b>Кто в каком балансе</b>",
    ]
    for balance in summary.balances:
        lines.append(
            f"- {_format_user_name(balance.user)}: внес "
            f"{format_money_amount(balance.contributed, currency)}, оплатил из своих "
            f"{format_money_amount(balance.paid_personal, currency)}, доля "
            f"{format_money_amount(balance.share, currency)} -> "
            f"{_format_balance_action(balance.balance, currency)}"
        )

    lines.append("")
    lines.append("<b>Переводы</b>")
    if summary.settlements:
        for settlement in summary.settlements:
            lines.append(
                f"- {_format_user_name(settlement.from_user)} -> {_format_user_name(settlement.to_user)}: "
                f"{format_money_amount(settlement.amount, currency)}"
            )
    else:
        lines.append("Все ровно. Никто никому ничего не должен.")
    return "\n".join(lines)
