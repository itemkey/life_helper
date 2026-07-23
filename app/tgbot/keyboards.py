from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import ListMember, ShoppingItem, ShoppingList, User
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
    rows.append(
        [
            InlineKeyboardButton(text="Добавить в общее", callback_data=f"add_common:{shopping_list.id}"),
            InlineKeyboardButton(text="Добавить в мой список", callback_data=f"add_personal:{shopping_list.id}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="Деньги", callback_data=f"money:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Участники списка", callback_data=f"members:{shopping_list.id}")])
    if level == AccessLevel.owner:
        rows.append([InlineKeyboardButton(text="Настройки", callback_data=f"settings:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="К спискам", callback_data="lists")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
                InlineKeyboardButton(text="Такси", callback_data=f"taxi:{shopping_list.id}"),
                InlineKeyboardButton(text="Итог", callback_data=f"money_final:{shopping_list.id}"),
            ],
            [InlineKeyboardButton(text="Назад к тусовке", callback_data=f"open:{shopping_list.id}")],
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


def expense_split_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="На всех", callback_data="expense_split:all")],
            [InlineKeyboardButton(text="Только на меня", callback_data="expense_split:me")],
            [InlineKeyboardButton(text="Выбрать участников", callback_data="expense_split:selected")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


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
