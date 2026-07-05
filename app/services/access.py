from __future__ import annotations

from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ListMember, ShoppingList
from app.services.errors import AccessDenied, ListNotFound


class AccessLevel(str, Enum):
    none = "none"
    member = "member"
    owner = "owner"


async def get_access_level(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> tuple[AccessLevel, ShoppingList | None]:
    shopping_list = await session.get(ShoppingList, list_id)
    if shopping_list is None:
        return AccessLevel.none, None

    if shopping_list.owner_id == user_id:
        return AccessLevel.owner, shopping_list

    membership = await session.get(ListMember, (list_id, user_id))
    if membership is not None:
        return AccessLevel.member, shopping_list

    return AccessLevel.none, shopping_list


async def require_access(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    owner_only: bool = False,
) -> tuple[ShoppingList, AccessLevel]:
    level, shopping_list = await get_access_level(session, user_id=user_id, list_id=list_id)
    if shopping_list is None:
        raise ListNotFound("Список не найден.")
    if owner_only and level != AccessLevel.owner:
        raise AccessDenied("Настройки списка доступны только владельцу.")
    if level == AccessLevel.none:
        raise AccessDenied("У тебя нет доступа к этому списку.")
    return shopping_list, level
