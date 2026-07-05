from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import ShoppingItem, ShoppingList
from app.services.access import AccessLevel


def _short(text: str, limit: int = 42) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."


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

    rows.append([InlineKeyboardButton(text="Добавить покупку", callback_data=f"add:{shopping_list.id}")])
    if level == AccessLevel.owner:
        rows.append([InlineKeyboardButton(text="Настройки", callback_data=f"settings:{shopping_list.id}")])
    rows.append([InlineKeyboardButton(text="К спискам", callback_data="lists")])
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
