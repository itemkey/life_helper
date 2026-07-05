from __future__ import annotations

from collections.abc import Sequence
from html import escape

from app.db.models import ShoppingItem, ShoppingList
from app.services.access import AccessLevel


WELCOME_TEXT = (
    "Привет. Я Life Helper.\n\n"
    "Пока умею вести списки покупок: можно создавать несколько списков, отмечать купленное, "
    "удалять позиции и делиться отдельным списком по ссылке."
)

HELP_TEXT = (
    "Команды:\n"
    "/lists - открыть мои списки\n"
    "/new - создать список\n"
    "/cancel - отменить текущий ввод\n\n"
    "Публичная ссылка дает доступ только к конкретному списку. Участник может добавлять, "
    "отмечать и удалять покупки, но не может менять настройки списка."
)


def format_lists_text(owned: Sequence[ShoppingList], shared: Sequence[ShoppingList]) -> str:
    if not owned and not shared:
        return "У тебя пока нет списков покупок. Создай первый список."

    lines = ["<b>Твои списки покупок</b>"]
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
        lines.append("Список пуст. Добавь первую покупку.")
    else:
        for index, item in enumerate(items, start=1):
            mark = "✓" if item.is_done else "□"
            lines.append(f"{index}. {mark} {escape(item.text)}")
    return "\n".join(lines)


def format_settings_text(shopping_list: ShoppingList) -> str:
    visibility = "публичный" if shopping_list.is_public else "приватный"
    return (
        f"<b>Настройки списка</b>\n"
        f"Название: {escape(shopping_list.title)}\n"
        f"Статус: {visibility}"
    )
