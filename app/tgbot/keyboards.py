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
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        mark = "✓" if item.is_done else "□"
        rows.append(
            [
                InlineKeyboardButton(text=f"{mark} {_short(item.text, 34)}", callback_data=f"toggle:{item.id}"),
                InlineKeyboardButton(text="Удалить", callback_data=f"delitem:{item.id}"),
            ]
        )

    rows.append([InlineKeyboardButton(text="Обновить", callback_data=f"refresh:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Добавить покупку", callback_data=f"add:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Поставить все галочки", callback_data=f"checkall:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Убрать все галочки", callback_data=f"uncheckall:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="Участники списка", callback_data=f"members:{shopping_list.id}")])
    if level == AccessLevel.owner:
        rows.append([InlineKeyboardButton(text="Настройки", callback_data=f"settings:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="К спискам", callback_data="lists")])
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
