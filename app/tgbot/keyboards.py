from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Expense, ExpenseCategory, ListMember, ShoppingCategory, ShoppingItem, ShoppingList, User
from app.services.audit import PAGE_SIZE as AUDIT_PAGE_SIZE
from app.services.access import AccessLevel


EXPENSE_DELETE_PAGE_SIZE = 8


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
            [InlineKeyboardButton(text="Открыть списки", callback_data="lists")],
            [InlineKeyboardButton(text="Создать список", callback_data="new")],
            [InlineKeyboardButton(text="Возможности", callback_data="help")],
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
            [InlineKeyboardButton(text=_short(shopping_list.title), callback_data=f"open:{shopping_list.id}")]
        )
    for shopping_list in shared:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"По ссылке: {_short(shopping_list.title)}",
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
    categories: Sequence[ShoppingCategory] = (),
    collapsed_category_ids: frozenset[int] | set[int] = frozenset(),
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    items_by_category: dict[int, list[ShoppingItem]] = {}
    uncategorized: list[ShoppingItem] = []
    for item in items:
        if item.category_id is None:
            uncategorized.append(item)
        else:
            items_by_category.setdefault(item.category_id, []).append(item)

    ordered_categories = sorted(categories, key=lambda entry: (entry.scope != "common", entry.position, entry.id))
    for category in ordered_categories:
        category_items = items_by_category.pop(category.id, [])
        is_collapsed = category.id in collapsed_category_ids
        title = _short(category.title, 34)
        if category.scope == "personal":
            owner = _user_label(category.owner) if category.owner else f"ID {category.owner_id}"
            title = f"👤 Мой · {title}" if category.owner_id == user_id else f"👤 {owner} · {title}"
        else:
            title = f"📁 {title}"
        if shopping_list.prices_enabled is not False:
            mode = {"receipt": "по чеку", "checklist": "без цен"}.get(category.accounting_mode, "по товарам")
            title = _short(f"{title} · {mode}", 56)
        remaining = sum(not item.is_done for item in category_items)
        count = f"{remaining}/{len(category_items)}"
        rows.append([
            InlineKeyboardButton(
                text=f"{'▸' if is_collapsed else '▾'} {_short(title, 48 - len(count))} · {count}",
                callback_data=f"section_toggle:{shopping_list.id}:{category.id}",
            ),
            InlineKeyboardButton(text="⚙️", callback_data=f"shopping_category:{category.id}"),
        ])
        if is_collapsed:
            continue
        for item in sorted(category_items, key=lambda entry: (entry.is_done, entry.position, entry.id)):
            can_toggle = item.scope != "personal" or level == AccessLevel.owner or item.personal_owner_id == user_id
            rows.append(_item_buttons(item, shopping_list.prices_enabled is not False, can_toggle=can_toggle))
        if category.scope == "common" or level == AccessLevel.owner or category.owner_id == user_id:
            rows.append([InlineKeyboardButton(text="＋ Добавить сюда", callback_data=f"add_category:{category.id}")])

    remaining_items = [*uncategorized, *(item for group in items_by_category.values() for item in group)]
    if remaining_items:
        rows.append([InlineKeyboardButton(text="📁 Без раздела", callback_data=f"shopping_categories:{shopping_list.id}")])
        for item in sorted(remaining_items, key=lambda entry: (entry.is_done, entry.position, entry.id)):
            can_toggle = item.scope != "personal" or level == AccessLevel.owner or item.personal_owner_id == user_id
            rows.append(_item_buttons(item, shopping_list.prices_enabled is not False, can_toggle=can_toggle))

    if ordered_categories:
        all_collapsed = all(category.id in collapsed_category_ids for category in ordered_categories)
        action = "expand" if all_collapsed else "collapse"
        label = "Развернуть все" if all_collapsed else "Свернуть все"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"section_toggle_all:{shopping_list.id}:{action}")])
    rows.append([InlineKeyboardButton(text="📄 Список текстом", callback_data=f"list_text:{shopping_list.id}:0")])
    rows.append([InlineKeyboardButton(text="＋ Добавить пункт", callback_data=f"add:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Разделы", callback_data=f"shopping_categories:{shopping_list.id}")])
    if shopping_list.prices_enabled is not False:
        rows.append([InlineKeyboardButton(text="Деньги", callback_data=f"money:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Участники", callback_data=f"members:{shopping_list.id}")])
    if level == AccessLevel.owner:
        rows.append([InlineKeyboardButton(text="⚙️ Настройки списка", callback_data=f"settings:{shopping_list.id}")])
    rows.append([
        InlineKeyboardButton(text="↻ Обновить", callback_data=f"refresh:{shopping_list.id}"),
        InlineKeyboardButton(text="Все списки", callback_data="lists"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def list_text_keyboard(list_id: int, *, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        pages: list[InlineKeyboardButton] = []
        if page > 0:
            pages.append(InlineKeyboardButton(text="←", callback_data=f"list_text:{list_id}:{page - 1}"))
        if page + 1 < total_pages:
            pages.append(InlineKeyboardButton(text="→", callback_data=f"list_text:{list_id}:{page + 1}"))
        rows.append(pages)
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"open:{list_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _item_buttons(item: ShoppingItem, prices_enabled: bool, *, can_toggle: bool = True) -> list[InlineKeyboardButton]:
    mark = "✓" if item.is_done else "□"
    callback = f"item_open:{item.id}" if not can_toggle or (prices_enabled and item.category is not None and item.category.accounting_mode == "receipt") else f"toggle:{item.id}"
    label = f"🔒 {_short(item.text, 34)}" if not can_toggle else f"{mark} {_short(item.text, 34)}"
    return [
        InlineKeyboardButton(text=label, callback_data=callback),
        InlineKeyboardButton(text="⚙️", callback_data=f"item_open:{item.id}"),
    ]


def item_keyboard(shopping_list: ShoppingList, item: ShoppingItem, *, can_edit: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        if item.is_done:
            rows.append([InlineKeyboardButton(text="Снять отметку", callback_data=f"toggle:{item.id}")])
        elif shopping_list.prices_enabled is False or item.expense_links or item.expenses or (item.category is not None and item.category.accounting_mode == "checklist"):
            rows.append([InlineKeyboardButton(text="Отметить готовым", callback_data=f"toggle:{item.id}")])
        elif item.category is not None and item.category.accounting_mode == "receipt":
            rows.append([InlineKeyboardButton(text="Добавить в чек", callback_data=f"receipt:{item.category.id}")])
        else:
            rows.append([InlineKeyboardButton(text="Купить и записать цену", callback_data=f"toggle:{item.id}")])
        rows.append([InlineKeyboardButton(text="Переименовать", callback_data=f"item_rename:{item.id}")])
        if not item.is_done:
            rows.append([InlineKeyboardButton(text="Перенести в другой раздел", callback_data=f"item_move:{item.id}")])
        rows.append([InlineKeyboardButton(text="Удалить пункт", callback_data=f"delitem_ask:{item.id}")])
    if item.category_id is not None:
        rows.append([InlineKeyboardButton(text="К разделу", callback_data=f"shopping_category:{item.category_id}")])
    rows.append([InlineKeyboardButton(text="К списку", callback_data=f"open:{item.list_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def item_move_keyboard(
    item: ShoppingItem,
    categories: Sequence[ShoppingCategory],
    *,
    level: AccessLevel,
    user_id: int,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_shopping_category_label(category, current_user_id=user_id), callback_data=f"item_move_to:{item.id}:{category.id}")]
        for category in categories
        if category.id != item.category_id
        and (category.scope == "common" or level == AccessLevel.owner or category.owner_id == user_id)
    ]
    rows.append([InlineKeyboardButton(text="Разделы списка", callback_data=f"shopping_categories:{item.list_id}")])
    rows.append([InlineKeyboardButton(text="Назад к пункту", callback_data=f"item_open:{item.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def item_delete_confirm_keyboard(item_id: int, list_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить пункт", callback_data=f"delitem:{item_id}")],
            [InlineKeyboardButton(text="Нет, к списку", callback_data=f"open:{list_id}")],
        ]
    )


def _shopping_category_label(category: ShoppingCategory, *, current_user_id: int | None = None) -> str:
    if category.accounting_mode == "checklist":
        mode = "вещи"
    elif category.accounting_mode == "receipt":
        mode = "покупки · чек"
    else:
        mode = "покупки · по товарам"
    if category.scope == "personal":
        if category.owner_id == current_user_id:
            return _short(f"Мой · {category.title} ({mode})", 48)
        owner = _user_label(category.owner) if category.owner is not None else f"ID {category.owner_id}"
        return _short(f"Личный · {category.title} · {owner} ({mode})", 48)
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
            InlineKeyboardButton(text="＋ Общий раздел", callback_data=f"shopping_category_add_common:{shopping_list.id}"),
            InlineKeyboardButton(text="＋ Личный раздел", callback_data=f"shopping_category_add_personal:{shopping_list.id}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="К списку", callback_data=f"open:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shopping_category_keyboard(
    category: ShoppingCategory,
    level: AccessLevel,
    user_id: int,
    items: Sequence[ShoppingItem] = (),
    *,
    prices_enabled: bool = True,
) -> InlineKeyboardMarkup:
    can_edit = level == AccessLevel.owner or (category.scope == "personal" and category.owner_id == user_id)
    can_add = category.scope == "common" or can_edit
    add_label = "＋ Добавить пункт" if not prices_enabled else ("＋ Добавить вещь" if category.accounting_mode == "checklist" else "＋ Добавить товар")
    rows: list[list[InlineKeyboardButton]] = []
    if can_add:
        rows.append([InlineKeyboardButton(text=add_label, callback_data=f"add_category:{category.id}")])
    for item in sorted(items, key=lambda entry: (entry.is_done, entry.position, entry.id)):
        rows.append(_item_buttons(item, prices_enabled, can_toggle=can_edit or item.scope != "personal"))
    if prices_enabled and category.accounting_mode == "receipt":
        rows.append([InlineKeyboardButton(text="Записать чек", callback_data=f"receipt:{category.id}")])
    if can_edit:
        rows.append([InlineKeyboardButton(text="Настройки", callback_data=f"shopping_category_settings:{category.id}")])
    rows.append([
        InlineKeyboardButton(text="Все разделы", callback_data=f"shopping_categories:{category.list_id}"),
        InlineKeyboardButton(text="К списку", callback_data=f"open:{category.list_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shopping_category_settings_keyboard(
    category: ShoppingCategory,
    level: AccessLevel,
    user_id: int,
    *,
    prices_enabled: bool = True,
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
        if prices_enabled:
            for mode, label, is_selected in mode_buttons:
                mark = "✓ " if is_selected else ""
                rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"shopping_category_mode:{category.id}:{mode}")])
        if prices_enabled and category.accounting_mode != "checklist":
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
    *,
    user_id: int,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_shopping_category_label(category, current_user_id=user_id), callback_data=f"add_category:{category.id}")]
        for category in categories
    ]
    if not any(category.scope == "common" for category in categories):
        rows.append([InlineKeyboardButton(text="В общий список", callback_data=f"add_common:{shopping_list.id}")])
    if not any(category.scope == "personal" and category.owner_id == user_id for category in categories):
        rows.append([InlineKeyboardButton(text="В мой личный раздел", callback_data=f"add_personal:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Создать раздел", callback_data=f"shopping_categories:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Назад к списку", callback_data=f"open:{shopping_list.id}")])
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
    if items:
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
                InlineKeyboardButton(text="Из кармана", callback_data="buy_source:personal"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def payer_choice_keyboard(*, callback_prefix: str, has_other_participants: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Из моего кармана", callback_data=f"{callback_prefix}:self")],
    ]
    if has_other_participants:
        rows.append([InlineKeyboardButton(text="Из чужого кармана", callback_data=f"{callback_prefix}:other")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payer_participants_keyboard(
    participants: Sequence[User],
    *,
    current_user_id: int,
    callback_prefix: str,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_user_label(user),
                callback_data=f"{callback_prefix}:{user.id}",
            )
        ]
        for user in participants
        if user.id != current_user_id
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def money_keyboard(shopping_list: ShoppingList, *, has_expenses: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Добавить взнос", callback_data=f"contribution:{shopping_list.id}"),
            InlineKeyboardButton(text="Записать трату", callback_data=f"expense:{shopping_list.id}"),
        ],
        [
            InlineKeyboardButton(text="Категории трат", callback_data=f"categories:{shopping_list.id}"),
            InlineKeyboardButton(text="Кто кому должен", callback_data=f"money_final:{shopping_list.id}"),
        ],
    ]
    if has_expenses:
        rows.append(
            [InlineKeyboardButton(text="Управление тратами", callback_data=f"expense_manage_list:{shopping_list.id}")]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"open:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _expense_management_label(expense: Expense, currency: str) -> str:
    amount = abs(expense.amount)
    sign = "-" if expense.amount < 0 else ""
    money = f"{sign}{amount // 100}.{amount % 100:02d} {currency}"
    category_prefix = f"{expense.category.title}: " if expense.category is not None else ""
    return _short(f"{category_prefix}{expense.title} — {money}", 54)


def expense_management_keyboard(
    shopping_list: ShoppingList,
    expenses: Sequence[Expense],
    *,
    page: int,
) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(expenses) + EXPENSE_DELETE_PAGE_SIZE - 1) // EXPENSE_DELETE_PAGE_SIZE)
    current_page = min(max(page, 0), total_pages - 1)
    start = current_page * EXPENSE_DELETE_PAGE_SIZE
    page_expenses = expenses[start : start + EXPENSE_DELETE_PAGE_SIZE]
    rows = [
        [
            InlineKeyboardButton(
                text=_expense_management_label(expense, shopping_list.currency),
                callback_data=f"expense_manage_open:{expense.id}:{current_page}",
            )
        ]
        for expense in page_expenses
    ]
    navigation: list[InlineKeyboardButton] = []
    if current_page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="← Назад",
                callback_data=f"expense_manage_page:{shopping_list.id}:{current_page - 1}",
            )
        )
    if current_page + 1 < total_pages:
        navigation.append(
            InlineKeyboardButton(
                text="Дальше →",
                callback_data=f"expense_manage_page:{shopping_list.id}:{current_page + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="Назад к деньгам", callback_data=f"money:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def expense_management_detail_keyboard(
    expense: Expense,
    *,
    list_id: int,
    page: int,
    can_manage: bool,
    is_manual: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_manage and is_manual:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="Изменить название",
                        callback_data=f"expense_manage_title:{expense.id}:{page}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Изменить сумму",
                        callback_data=f"expense_manage_amount:{expense.id}:{page}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Изменить категорию",
                        callback_data=f"expense_manage_category:{expense.id}:{page}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Изменить оплату",
                        callback_data=f"expense_manage_payment:{expense.id}:{page}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Изменить участников",
                        callback_data=f"expense_manage_shares:{expense.id}:{page}",
                    )
                ],
            ]
        )
    if can_manage:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"expense_delete_confirm:{expense.id}:{page}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад к тратам",
                callback_data=f"expense_manage_page:{list_id}:{page}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def expense_delete_confirm_keyboard(
    *,
    expense_id: int,
    list_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить",
                    callback_data=f"expense_delete_apply:{expense_id}:{page}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Нет, назад",
                    callback_data=f"expense_manage_open:{expense_id}:{page}",
                )
            ],
        ]
    )


def expense_management_category_keyboard(
    expense: Expense,
    categories: Sequence[ExpenseCategory],
    *,
    page: int,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=("✓ " if expense.category_id == category.id else "") + _short(category.title, 46),
                callback_data=f"expense_manage_category_set:{expense.id}:{category.id}:{page}",
            )
        ]
        for category in categories
    ]
    none_mark = "✓ " if expense.category_id is None else ""
    rows.append(
        [
            InlineKeyboardButton(
                text=f"{none_mark}Без категории",
                callback_data=f"expense_manage_category_none:{expense.id}:{page}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data=f"expense_manage_open:{expense.id}:{page}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def expense_management_payment_keyboard(expense_id: int, *, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Из кассы",
                    callback_data=f"expense_manage_source:{expense_id}:cashbox:{page}",
                ),
                InlineKeyboardButton(
                    text="Из кармана",
                    callback_data=f"expense_manage_source:{expense_id}:personal:{page}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"expense_manage_open:{expense_id}:{page}",
                )
            ],
        ]
    )


def expense_management_payer_keyboard(
    expense_id: int,
    participants: Sequence[User],
    *,
    page: int,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_user_label(user),
                callback_data=f"expense_manage_payer:{expense_id}:{user.id}:{page}",
            )
        ]
        for user in participants
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data=f"expense_manage_open:{expense_id}:{page}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def expense_management_participants_keyboard(
    expense_id: int,
    participants: Sequence[User],
    selected_user_ids: Sequence[int],
    *,
    page: int,
) -> InlineKeyboardMarkup:
    selected = set(selected_user_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for user in participants:
        mark = "✓" if user.id in selected else "□"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {_user_label(user)}",
                    callback_data=f"expense_manage_share_toggle:{expense_id}:{user.id}:{page}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Готово",
                callback_data=f"expense_manage_share_done:{expense_id}:{page}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data=f"expense_manage_open:{expense_id}:{page}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    rows.append([InlineKeyboardButton(text="Управление тратами", callback_data=f"expense_manage_list:{shopping_list.id}")])
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
                InlineKeyboardButton(text="Из кармана", callback_data="expense_source:personal"),
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
            [InlineKeyboardButton(text=f"Удалить: {label}", callback_data=f"member_remove_ask:{shopping_list.id}:{user.id}")]
        )
        rows.append(
            [InlineKeyboardButton(text=f"Заблокировать: {label}", callback_data=f"member_ban_ask:{shopping_list.id}:{user.id}")]
        )

    rows.append([InlineKeyboardButton(text="Назад к участникам", callback_data=f"members:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Назад к списку", callback_data=f"open:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def member_action_confirm_keyboard(list_id: int, member_user_id: int, *, action: str) -> InlineKeyboardMarkup:
    if action not in {"remove", "ban"}:
        raise ValueError("Unknown member action")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, продолжить", callback_data=f"member_{action}:{list_id}:{member_user_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"members_manage:{list_id}")],
        ]
    )


def settings_keyboard(shopping_list: ShoppingList) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Режим списка", callback_data=f"list_mode:{shopping_list.id}")],
            [InlineKeyboardButton(text="Журнал аудита", callback_data=f"audit:{shopping_list.id}:all:0")],
            [InlineKeyboardButton(text="Участники и доступ", callback_data=f"settings_access:{shopping_list.id}")],
            [InlineKeyboardButton(text="Переименовать список", callback_data=f"rename:{shopping_list.id}")],
            [InlineKeyboardButton(text="Удалить список", callback_data=f"delete_list:{shopping_list.id}")],
            [InlineKeyboardButton(text="К списку", callback_data=f"open:{shopping_list.id}")],
        ]
    )


def audit_keyboard(list_id: int, *, filter_name: str, page: int, total: int,
                   section_id: int | None = None, item_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if section_id is None and item_id is None:
        filters = [("all", "Все"), ("items", "Разделы и пункты"),
                   ("money", "Деньги"), ("people", "Участники"), ("list", "Список")]
        for key, title in filters:
            rows.append([InlineKeyboardButton(text=f"{'✓ ' if filter_name == key else ''}{title}",
                                            callback_data=f"audit:{list_id}:{key}:0")])
        rows.append([InlineKeyboardButton(text="История по разделам", callback_data=f"audit_sections:{list_id}:0")])
    elif item_id is None:
        rows.append([InlineKeyboardButton(text="Пункты этого раздела", callback_data=f"audit_items:{list_id}:{section_id}:0")])
    pages = max(1, (total + AUDIT_PAGE_SIZE - 1) // AUDIT_PAGE_SIZE)
    navigation = []
    if item_id is not None:
        prefix = f"audit_item:{list_id}:{section_id}:{item_id}"
    elif section_id is not None:
        prefix = f"audit_section:{list_id}:{section_id}"
    else:
        prefix = f"audit:{list_id}:{filter_name}"
    if page > 0:
        navigation.append(InlineKeyboardButton(text="← Новее", callback_data=f"{prefix}:{page - 1}"))
    if page + 1 < pages:
        navigation.append(InlineKeyboardButton(text="Старее →", callback_data=f"{prefix}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    if item_id is not None:
        back = f"audit_items:{list_id}:{section_id}:0"
    elif section_id is not None:
        back = f"audit_sections:{list_id}:0"
    else:
        back = f"settings:{list_id}"
    rows.append([InlineKeyboardButton(text="Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audit_sections_keyboard(list_id: int, sections: Sequence[tuple[int, str]], *, page: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_short(title, 50), callback_data=f"audit_section:{list_id}:{section_id}:0")]
        for section_id, title in sections[page * 10:(page + 1) * 10]
    ]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="← Назад", callback_data=f"audit_sections:{list_id}:{page - 1}"))
    if (page + 1) * 10 < len(sections):
        navigation.append(InlineKeyboardButton(text="Дальше →", callback_data=f"audit_sections:{list_id}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="Весь журнал", callback_data=f"audit:{list_id}:all:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audit_items_keyboard(list_id: int, section_id: int, items: Sequence[tuple[int, str]],
                         *, page: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_short(title, 50), callback_data=f"audit_item:{list_id}:{section_id}:{item_id}:0")]
        for item_id, title in items[page * 10:(page + 1) * 10]
    ]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="← Назад", callback_data=f"audit_items:{list_id}:{section_id}:{page - 1}"))
    if (page + 1) * 10 < len(items):
        navigation.append(InlineKeyboardButton(text="Дальше →", callback_data=f"audit_items:{list_id}:{section_id}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="История раздела", callback_data=f"audit_section:{list_id}:{section_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def list_mode_keyboard(shopping_list: ShoppingList) -> InlineKeyboardMarkup:
    enabled = shopping_list.prices_enabled is not False
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{'✓ ' if not enabled else ''}Простой список · без цен", callback_data=f"list_mode_set:{shopping_list.id}:off")],
            [InlineKeyboardButton(text=f"{'✓ ' if enabled else ''}Список с деньгами", callback_data=f"list_mode_set:{shopping_list.id}:on")],
            [InlineKeyboardButton(text="Назад к настройкам", callback_data=f"settings:{shopping_list.id}")],
        ]
    )


def access_settings_keyboard(shopping_list: ShoppingList) -> InlineKeyboardMarkup:
    share_label = "Показать ссылку" if shopping_list.is_public else "Пригласить по ссылке"
    rows = [
        [InlineKeyboardButton(text=share_label, callback_data=f"share:{shopping_list.id}")],
        [InlineKeyboardButton(text="Участники", callback_data=f"members:{shopping_list.id}")],
    ]
    if shopping_list.is_public:
        rows.append([InlineKeyboardButton(text="Заменить ссылку", callback_data=f"relink_ask:{shopping_list.id}")])
        rows.append([InlineKeyboardButton(text="Закрыть доступ", callback_data=f"private_ask:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Назад к настройкам", callback_data=f"settings:{shopping_list.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def access_change_confirm_keyboard(shopping_list: ShoppingList, *, action: str) -> InlineKeyboardMarkup:
    if action not in {"relink", "private"}:
        raise ValueError("Unknown access change action")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, продолжить", callback_data=f"{action}:{shopping_list.id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"settings_access:{shopping_list.id}")],
        ]
    )


def delete_confirm_keyboard(shopping_list: ShoppingList) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=f"delete_confirm:{shopping_list.id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"settings:{shopping_list.id}")],
        ]
    )
