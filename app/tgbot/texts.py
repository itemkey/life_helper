from __future__ import annotations

from collections.abc import Sequence
from html import escape

from app.db.models import ListMember, ShoppingItem, ShoppingList, User
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
        f"<b>Настройки списка</b>\n"
        f"Название: {escape(shopping_list.title)}\n"
        f"Статус: {visibility}"
    )
