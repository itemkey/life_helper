from __future__ import annotations

from collections.abc import Sequence
from html import escape

from app.db.models import ListMember, ShoppingItem, ShoppingList, User
from app.services.access import AccessLevel
from app.services.shopping import EXPENSE_SOURCE_CASHBOX, MoneySummary, format_money_amount


WELCOME_TEXT = (
    "Привет. Я Life Helper.\n\n"
    "Теперь можно вести тусовки: общий список, личные хотелки, взносы, траты, такси и честный итог по деньгам."
)

HELP_TEXT = (
    "Команды:\n"
    "/lists - открыть мои тусовки\n"
    "/new - создать тусовку\n"
    "/cancel - отменить текущий ввод\n\n"
    "Ссылка дает доступ только к конкретной тусовке. Участник может добавлять покупки в общее и в свой личный список. "
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
) -> str:
    role = "владелец" if level == AccessLevel.owner else "участник"
    visibility = "публичный" if shopping_list.is_public else "приватный"
    lines = [
        f"<b>{escape(shopping_list.title)}</b>",
        f"Статус: {visibility}. Твоя роль: {role}.",
        "",
    ]
    if not items:
        lines.append("Тусовка пока пустая. Добавь продукты в общее или хотелки в личный список.")
        return "\n".join(lines)

    common_items = [item for item in items if item.scope != "personal"]
    personal_items = [item for item in items if item.scope == "personal"]

    if common_items:
        lines.append("<b>Общее</b>")
        lines.extend(_format_item_lines(common_items))
    else:
        lines.append("<b>Общее</b>")
        lines.append("Пока пусто.")

    personal_groups: dict[int, tuple[str, list[ShoppingItem]]] = {}
    for item in personal_items:
        owner = item.personal_owner
        owner_id = item.personal_owner_id or 0
        owner_label = _format_user_name(owner) if owner is not None else f"ID {owner_id}"
        if owner_id not in personal_groups:
            personal_groups[owner_id] = (owner_label, [])
        personal_groups[owner_id][1].append(item)

    for _, (owner_label, owner_items) in sorted(personal_groups.items(), key=lambda group: group[1][0]):
        lines.append("")
        lines.append(f"<b>Личное: {owner_label}</b>")
        lines.extend(_format_item_lines(owner_items))
    return "\n".join(lines)


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


def _format_expense_source(source: str) -> str:
    return "касса" if source == EXPENSE_SOURCE_CASHBOX else "из своих"


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
            split_count = len(expense.shares)
            lines.append(
                f"- {escape(expense.title)}: {format_money_amount(expense.amount, currency)} "
                f"({_format_expense_source(expense.source)}, платил {_format_user_name(expense.payer)}, "
                f"долей: {split_count})"
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
