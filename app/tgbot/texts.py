from __future__ import annotations

from collections.abc import Sequence
from html import escape

from app.db.models import Expense, ExpenseCategory, ListMember, ShoppingCategory, ShoppingItem, ShoppingList, User
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
    "Привет! Я Life Helper.\n\n"
    "Помогу собрать покупки и вещи для общего дела и понять, кто сколько потратил. "
    "Создай список или открой уже существующий."
)

HELP_TEXT = (
    "<b>Как пользоваться</b>\n"
    "1. Создай список или открой список по ссылке.\n"
    "2. Нажми «Добавить», чтобы записать покупки или вещи. Разделы помогают их сгруппировать.\n"
    "3. Нажми на пункт списка, чтобы отметить его. Для покупки бот попросит цену и способ оплаты.\n"
    "4. В «Деньгах» записывай взносы и другие траты, смотри итог расчётов.\n\n"
    "Общие и личные разделы видны участникам; обычно каждый добавляет в свой личный раздел. "
    "Касса — общие деньги, «из кармана» — личная оплата. "
    "Пригласить людей можно через «Настройки» → «Поделиться».\n\n"
    "Команды: /lists — все списки, /new — новый список, /cancel — отменить ввод."
)


def format_lists_text(owned: Sequence[ShoppingList], shared: Sequence[ShoppingList]) -> str:
    if not owned and not shared:
        return "Списков пока нет. Нажми «Создать список», чтобы начать."

    lines = ["<b>Списки</b>", "Выбери список или создай новый."]
    if owned:
        lines.append("\nСозданные мной:")
        lines.extend(f"- {escape(item.title)}" for item in owned)
    if shared:
        lines.append("\nПо приглашению:")
        lines.extend(f"- {escape(item.title)}" for item in shared)
    return "\n".join(lines)


def format_list_text(
    shopping_list: ShoppingList,
    items: Sequence[ShoppingItem],
    level: AccessLevel,
    categories: Sequence[ShoppingCategory] = (),
) -> str:
    visibility = "по ссылке" if shopping_list.is_public else "только для тебя"
    lines = [
        f"<b>{escape(shopping_list.title)}</b>",
        f"Доступ: {visibility}.",
        "",
    ]
    if not items:
        lines.append("Здесь пока пусто. Нажми «Добавить», чтобы записать первую покупку или вещь.")
        return "\n".join(lines)
    lines.append("Нажми на пункт ниже, чтобы отметить его. Корзина рядом откроет удаление.")
    lines.append("")

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

    lines.append("Выбери действие для участника:")
    for index, (_, user) in enumerate(members, start=1):
        lines.append(f"{index}. {_format_user_name(user)}")
    return "\n".join(lines)


def format_settings_text(shopping_list: ShoppingList) -> str:
    visibility = "открыт по ссылке" if shopping_list.is_public else "закрыт"
    return (
        f"<b>Настройки списка</b>\n"
        f"Название: {escape(shopping_list.title)}\n"
        f"Доступ: {visibility}\n\n"
        "Здесь можно пригласить участников, изменить название или удалить список."
    )


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
        f"<b>Разделы: {escape(shopping_list.title)}</b>",
        "Разделы группируют покупки и вещи. Общие доступны всем, личные — для отдельных участников.",
        "",
    ]
    if not categories:
        lines.append("Разделов пока нет. Создай общий или личный раздел.")
        return "\n".join(lines)

    for index, category in enumerate(categories, start=1):
        lines.append(f"{index}. {_format_shopping_category_heading(category)}")
    return "\n".join(lines)


def format_shopping_category_text(
    category: ShoppingCategory,
    items: Sequence[ShoppingItem],
    *,
    can_add: bool = True,
) -> str:
    lines = [
        f"<b>{_format_shopping_category_heading(category)}</b>",
        "",
    ]
    if items:
        lines.append("Чтобы отметить пункт, нажми «К списку» ниже.")
        lines.append("")
        lines.extend(_format_item_lines(items))
    elif not can_add:
        lines.append("Здесь пока пусто. Добавить пункты может владелец раздела.")
    else:
        lines.append("Здесь пока пусто. Нажми «Добавить» ниже.")
    return "\n".join(lines)


def format_shopping_category_settings_text(category: ShoppingCategory) -> str:
    lines = [
        f"<b>Настройки: {_format_shopping_category_heading(category)}</b>",
        "",
        f"Тип: {_format_shopping_category_kind(category.accounting_mode)}.",
    ]
    accounting = _format_shopping_category_accounting(category.accounting_mode)
    if accounting is not None:
        lines.append(f"Расчёт: {accounting}.")
    return "\n".join(
        lines
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
        lines.append("В этом разделе нет некупленных товаров для чека.")
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
