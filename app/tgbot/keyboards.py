from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import ExpenseCategory, ListMember, ShoppingCategory, ShoppingItem, ShoppingList, User
from app.services.access import AccessLevel


def _short(text: str, limit: int = 42) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."


def _user_label(user: User, limit: int = 32) -> str:
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part)
    if full_name and user.username:
        return _short(f"{full_name} (@{user.username})", limit)
    if full_name:
        return _short(full_name, limit)
    if user.username:
        return _short(f"@{user.username}", limit)
    return f"ID {user.id}"


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Мои списки", callback_data="lists"),
                InlineKeyboardButton(text="Создать список", callback_data="new"),
            ]
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="cancel")]]
    )


def lists_keyboard(
    owned: Sequence[ShoppingList],
    shared: Sequence[ShoppingList],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for shopping_list in owned:
        rows.append(
            [InlineKeyboardButton(text=f"Мой: {_short(shopping_list.title)}", callback_data=f"open:{shopping_list.id}")]
        )
    for shopping_list in shared:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Общий: {_short(shopping_list.title)}",
                    callback_data=f"open:{shopping_list.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Создать список", callback_data="new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def list_keyboard(
    shopping_list: ShoppingList,
    items: Sequence[ShoppingItem],
    level: AccessLevel,
    user_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        mark = "✓" if item.is_done else "□"
        row = [InlineKeyboardButton(text=f"{mark} {_short(item.text, 34)}", callback_data=f"toggle:{item.id}")]
        can_delete = item.scope != "personal" or level == AccessLevel.owner or item.personal_owner_id == user_id
        if can_delete:
            row.append(InlineKeyboardButton(text="Удалить", callback_data=f"delitem:{item.id}"))
        rows.append(row)

    rows.append([InlineKeyboardButton(text="Обновить", callback_data=f"refresh:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Категории списков", callback_data=f"shopping_categories:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Деньги", callback_data=f"money:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Участники списка", callback_data=f"members:{shopping_list.id}")])
    if level == AccessLevel.owner:
        rows.append([InlineKeyboardButton(text="Настройки", callback_data=f"settings:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="К спискам", callback_data="lists")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _shopping_category_label(category: ShoppingCategory) -> str:
    if category.accounting_mode == "checklist":
        mode = "список вещей"
    elif category.accounting_mode == "receipt":
        mode = "список покупок, чек"
    else:
        mode = "список покупок, товары"
    if category.scope == "personal":
        owner = _user_label(category.owner) if category.owner is not None else f"ID {category.owner_id}"
        return _short(f"{category.title}: {owner} ({mode})", 48)
    return _short(f"{category.title} ({mode})", 48)


def shopping_categories_keyboard(
    shopping_list: ShoppingList,
    categories: Sequence[ShoppingCategory],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for category in categories:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_shopping_category_label(category),
                    callback_data=f"shopping_category:{category.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Добавить общую", callback_data=f"shopping_category_add_common:{shopping_list.id}"),
            InlineKeyboardButton(text="Добавить личную", callback_data=f"shopping_category_add_personal:{shopping_list.id}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="Назад к тусовке", callback_data=f"open:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shopping_category_keyboard(
    category: ShoppingCategory,
    level: AccessLevel,
    user_id: int,
) -> InlineKeyboardMarkup:
    can_edit = level == AccessLevel.owner or (category.scope == "personal" and category.owner_id == user_id)
    add_label = "Добавить вещь" if category.accounting_mode == "checklist" else "Добавить товар"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=add_label, callback_data=f"add_category:{category.id}")],
    ]
    if category.accounting_mode != "checklist":
        rows.append([InlineKeyboardButton(text="Чек", callback_data=f"receipt:{category.id}")])
    if can_edit:
        rows.append([InlineKeyboardButton(text="Настройки", callback_data=f"shopping_category_settings:{category.id}")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"shopping_categories:{category.list_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shopping_category_settings_keyboard(
    category: ShoppingCategory,
    level: AccessLevel,
    user_id: int,
) -> InlineKeyboardMarkup:
    can_edit = level == AccessLevel.owner or (category.scope == "personal" and category.owner_id == user_id)
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        mode_buttons = [
            (
                "per_item" if category.accounting_mode == "checklist" else category.accounting_mode,
                "Список покупок",
                category.accounting_mode != "checklist",
            ),
            ("checklist", "Список вещей", category.accounting_mode == "checklist"),
        ]
        for mode, label, is_selected in mode_buttons:
            mark = "✓ " if is_selected else ""
            rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"shopping_category_mode:{category.id}:{mode}")])
        if category.accounting_mode != "checklist":
            accounting_buttons = [
                ("per_item", "По товарам"),
                ("receipt", "По чеку"),
            ]
            for mode, label in accounting_buttons:
                mark = "✓ " if category.accounting_mode == mode else ""
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"{mark}{label}",
                            callback_data=f"shopping_category_mode:{category.id}:{mode}",
                        )
                    ]
                )
        rows.append([InlineKeyboardButton(text="Переименовать", callback_data=f"shopping_category_rename:{category.id}")])
        rows.append([InlineKeyboardButton(text="Удалить", callback_data=f"shopping_category_delete:{category.id}")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"shopping_category:{category.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shopping_category_select_keyboard(
    shopping_list: ShoppingList,
    categories: Sequence[ShoppingCategory],
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_shopping_category_label(category), callback_data=f"add_category:{category.id}")]
        for category in categories
    ]
    rows.append([InlineKeyboardButton(text="Категории списков", callback_data=f"shopping_categories:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Назад к тусовке", callback_data=f"open:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def receipt_items_keyboard(
    category: ShoppingCategory,
    items: Sequence[ShoppingItem],
    selected_item_ids: Sequence[int],
) -> InlineKeyboardMarkup:
    selected = set(selected_item_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        mark = "✓" if item.id in selected else "□"
        rows.append([InlineKeyboardButton(text=f"{mark} {_short(item.text, 42)}", callback_data=f"receipt_select:{item.id}")])
    rows.append([InlineKeyboardButton(text="Дальше", callback_data="receipt_items_done")])
    rows.append([InlineKeyboardButton(text="Назад к категории", callback_data=f"shopping_category:{category.id}")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def receipt_cancel_keyboard(expense_id: int, list_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отменить весь чек", callback_data=f"receipt_cancel:{expense_id}")],
            [InlineKeyboardButton(text="Оставить как есть", callback_data=f"open:{list_id}")],
        ]
    )


def item_purchase_source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Из кассы", callback_data="buy_source:cashbox"),
                InlineKeyboardButton(text="Из своих", callback_data="buy_source:personal"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def money_keyboard(shopping_list: ShoppingList) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Взнос", callback_data=f"contribution:{shopping_list.id}"),
                InlineKeyboardButton(text="Трата", callback_data=f"expense:{shopping_list.id}"),
            ],
            [
                InlineKeyboardButton(text="Категории трат", callback_data=f"categories:{shopping_list.id}"),
                InlineKeyboardButton(text="Итог", callback_data=f"money_final:{shopping_list.id}"),
            ],
            [InlineKeyboardButton(text="Назад к тусовке", callback_data=f"open:{shopping_list.id}")],
        ]
    )


def expense_categories_keyboard(
    shopping_list: ShoppingList,
    categories: Sequence[ExpenseCategory],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for category in categories:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_short(category.title, 48),
                    callback_data=f"expense_category:{category.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Разовая трата без категории", callback_data=f"expense_custom:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Добавить категорию", callback_data=f"category_add:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Назад к деньгам", callback_data=f"money:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def expense_category_keyboard(category: ExpenseCategory) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Новая трата", callback_data=f"expense_category_add:{category.id}")],
            [InlineKeyboardButton(text="Распределение", callback_data=f"expense_category_split:{category.id}")],
            [InlineKeyboardButton(text="Переименовать", callback_data=f"expense_category_rename:{category.id}")],
            [InlineKeyboardButton(text="Удалить", callback_data=f"expense_category_delete:{category.id}")],
            [InlineKeyboardButton(text="Назад к категориям", callback_data=f"categories:{category.list_id}")],
            [InlineKeyboardButton(text="Назад к деньгам", callback_data=f"money:{category.list_id}")],
        ]
    )


def expense_category_split_keyboard(category: ExpenseCategory) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="На всех", callback_data=f"expense_category_set_split:{category.id}:all")],
            [
                InlineKeyboardButton(
                    text="Выбирать участников",
                    callback_data=f"expense_category_set_split:{category.id}:selected",
                )
            ],
            [InlineKeyboardButton(text="Только на меня", callback_data=f"expense_category_set_split:{category.id}:me")],
            [InlineKeyboardButton(text="Назад к категории", callback_data=f"expense_category:{category.id}")],
        ]
    )


def expense_source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Из кассы", callback_data="expense_source:cashbox"),
                InlineKeyboardButton(text="Из своих", callback_data="expense_source:personal"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def expense_split_keyboard(default_label: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if default_label is not None:
        rows.append([InlineKeyboardButton(text=default_label, callback_data="expense_split:default")])
    rows.extend(
        [
            [InlineKeyboardButton(text="На всех", callback_data="expense_split:all")],
            [InlineKeyboardButton(text="Только на меня", callback_data="expense_split:me")],
            [InlineKeyboardButton(text="Выбрать участников", callback_data="expense_split:selected")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def expense_participants_keyboard(
    participants: Sequence[User],
    selected_user_ids: Sequence[int],
) -> InlineKeyboardMarkup:
    selected = set(selected_user_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for user in participants:
        mark = "✓" if user.id in selected else "□"
        rows.append([InlineKeyboardButton(text=f"{mark} {_user_label(user)}", callback_data=f"expense_select:{user.id}")])
    rows.append([InlineKeyboardButton(text="Готово", callback_data="expense_selected_done")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def members_keyboard(shopping_list: ShoppingList, level: AccessLevel) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if level == AccessLevel.owner:
        rows.append([InlineKeyboardButton(text="Управлять участниками", callback_data=f"members_manage:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Назад к списку", callback_data=f"open:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def members_management_keyboard(
    shopping_list: ShoppingList,
    members: Sequence[tuple[ListMember, User]],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for _, user in members:
        label = _user_label(user)
        rows.append(
            [InlineKeyboardButton(text=f"Удалить: {label}", callback_data=f"member_remove:{shopping_list.id}:{user.id}")]
        )
        rows.append(
            [InlineKeyboardButton(text=f"Забанить: {label}", callback_data=f"member_ban:{shopping_list.id}:{user.id}")]
        )

    rows.append([InlineKeyboardButton(text="Назад к участникам", callback_data=f"members:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Назад к списку", callback_data=f"open:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard(shopping_list: ShoppingList) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Поделиться", callback_data=f"share:{shopping_list.id}")],
        [InlineKeyboardButton(text="Создать новую ссылку", callback_data=f"relink:{shopping_list.id}")],
    ]
    if shopping_list.is_public:
        rows.append([InlineKeyboardButton(text="Закрыть публичный доступ", callback_data=f"private:{shopping_list.id}")])
    rows.extend(
        [
            [InlineKeyboardButton(text="Переименовать", callback_data=f"rename:{shopping_list.id}")],
            [InlineKeyboardButton(text="Удалить список", callback_data=f"delete_list:{shopping_list.id}")],
            [InlineKeyboardButton(text="Назад к списку", callback_data=f"open:{shopping_list.id}")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_keyboard(shopping_list: ShoppingList) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=f"delete_confirm:{shopping_list.id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"settings:{shopping_list.id}")],
        ]
    )
