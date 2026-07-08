from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ListBannedMember, ListMember, ListViewMessage, ShoppingItem, ShoppingList, User
from app.services.access import AccessLevel, require_access
from app.services.errors import AccessDenied, ListNotFound, ValidationError
from app.services.tokens import generate_public_token, hash_public_token


def _normalize_title(title: str) -> str:
    value = " ".join(title.strip().split())
    if not value:
        raise ValidationError("Название списка не может быть пустым.")
    if len(value) > 120:
        raise ValidationError("Название списка должно быть не длиннее 120 символов.")
    return value


def _normalize_item_lines(text: str) -> list[str]:
    lines = [" ".join(line.strip().split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ValidationError("Напиши хотя бы одну покупку.")
    too_long = [line for line in lines if len(line) > 255]
    if too_long:
        raise ValidationError("Одна покупка должна быть не длиннее 255 символов.")
    return lines


async def upsert_user(session: AsyncSession, telegram_user: object) -> User:
    user_id = int(getattr(telegram_user, "id"))
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        session.add(user)

    user.username = getattr(telegram_user, "username", None)
    user.first_name = getattr(telegram_user, "first_name", None)
    user.last_name = getattr(telegram_user, "last_name", None)
    user.language_code = getattr(telegram_user, "language_code", None)
    await session.flush()
    return user


async def create_shopping_list(session: AsyncSession, *, owner_id: int, title: str) -> ShoppingList:
    shopping_list = ShoppingList(owner_id=owner_id, title=_normalize_title(title))
    session.add(shopping_list)
    await session.flush()
    return shopping_list


async def list_owned_and_shared(
    session: AsyncSession,
    *,
    user_id: int,
) -> tuple[Sequence[ShoppingList], Sequence[ShoppingList]]:
    owned_result = await session.scalars(
        select(ShoppingList)
        .where(ShoppingList.owner_id == user_id)
        .order_by(ShoppingList.created_at.desc(), ShoppingList.id.desc())
    )
    shared_result = await session.scalars(
        select(ShoppingList)
        .join(ListMember, ListMember.list_id == ShoppingList.id)
        .where(ListMember.user_id == user_id)
        .order_by(ListMember.joined_at.desc(), ShoppingList.id.desc())
    )
    return owned_result.all(), shared_result.all()


async def get_list_view(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> tuple[ShoppingList, Sequence[ShoppingItem], AccessLevel]:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    items = await session.scalars(
        select(ShoppingItem)
        .where(ShoppingItem.list_id == list_id)
        .order_by(ShoppingItem.position.asc(), ShoppingItem.id.asc())
    )
    return shopping_list, items.all(), level


async def get_list_members_view(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> tuple[ShoppingList, User, Sequence[tuple[ListMember, User]], AccessLevel]:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    owner = await session.get(User, shopping_list.owner_id)
    if owner is None:
        raise ListNotFound("Владелец списка не найден.")

    members_result = await session.execute(
        select(ListMember, User)
        .join(User, User.id == ListMember.user_id)
        .where(ListMember.list_id == list_id)
        .order_by(ListMember.joined_at.asc(), ListMember.user_id.asc())
    )
    members = [(member, member_user) for member, member_user in members_result.all()]
    return shopping_list, owner, members, level


async def get_manageable_list_members_view(
    session: AsyncSession,
    *,
    owner_id: int,
    list_id: int,
) -> tuple[ShoppingList, Sequence[tuple[ListMember, User]]]:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    members_result = await session.execute(
        select(ListMember, User)
        .join(User, User.id == ListMember.user_id)
        .where(ListMember.list_id == list_id)
        .order_by(ListMember.joined_at.asc(), ListMember.user_id.asc())
    )
    members = [(member, member_user) for member, member_user in members_result.all()]
    return shopping_list, members


async def save_list_view_message(
    session: AsyncSession,
    *,
    list_id: int,
    user_id: int,
    chat_id: int,
    message_id: int,
) -> ListViewMessage:
    view_message = await session.get(ListViewMessage, (list_id, user_id))
    if view_message is None:
        view_message = ListViewMessage(
            list_id=list_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
        )
        session.add(view_message)
    else:
        view_message.chat_id = chat_id
        view_message.message_id = message_id
    await session.flush()
    return view_message


async def clear_list_view_message(
    session: AsyncSession,
    *,
    list_id: int,
    user_id: int,
) -> None:
    await session.execute(
        delete(ListViewMessage).where(
            ListViewMessage.list_id == list_id,
            ListViewMessage.user_id == user_id,
        )
    )
    await session.flush()


async def clear_list_view_message_by_message(
    session: AsyncSession,
    *,
    user_id: int,
    chat_id: int,
    message_id: int,
) -> None:
    await session.execute(
        delete(ListViewMessage).where(
            ListViewMessage.user_id == user_id,
            ListViewMessage.chat_id == chat_id,
            ListViewMessage.message_id == message_id,
        )
    )
    await session.flush()


async def get_public_list_update_view(
    session: AsyncSession,
    *,
    list_id: int,
) -> tuple[ShoppingList, Sequence[ShoppingItem], Sequence[ListViewMessage]] | None:
    shopping_list = await session.get(ShoppingList, list_id, populate_existing=True)
    if shopping_list is None or not shopping_list.is_public:
        return None

    items = await session.scalars(
        select(ShoppingItem)
        .where(ShoppingItem.list_id == list_id)
        .order_by(ShoppingItem.position.asc(), ShoppingItem.id.asc())
    )
    messages = await session.scalars(
        select(ListViewMessage)
        .outerjoin(
            ListMember,
            and_(
                ListMember.list_id == ListViewMessage.list_id,
                ListMember.user_id == ListViewMessage.user_id,
            ),
        )
        .where(
            ListViewMessage.list_id == list_id,
            or_(
                ListViewMessage.user_id == shopping_list.owner_id,
                ListMember.user_id.is_not(None),
            ),
        )
        .order_by(ListViewMessage.updated_at.asc(), ListViewMessage.user_id.asc())
    )
    return shopping_list, items.all(), messages.all()


async def add_items(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    text: str,
) -> list[ShoppingItem]:
    shopping_list, _ = await require_access(session, user_id=user_id, list_id=list_id)
    lines = _normalize_item_lines(text)
    locked_list = await session.scalar(
        select(ShoppingList).where(ShoppingList.id == shopping_list.id).with_for_update()
    )
    if locked_list is None:
        raise ListNotFound("Список не найден.")
    shopping_list = locked_list
    max_position = await session.scalar(
        select(func.coalesce(func.max(ShoppingItem.position), 0)).where(ShoppingItem.list_id == shopping_list.id)
    )
    position = int(max_position or 0)
    items = []
    for line in lines:
        position += 1
        item = ShoppingItem(
            list_id=shopping_list.id,
            text=line,
            position=position,
            author_id=user_id,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    return items


async def toggle_item(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
) -> int:
    item = await session.get(ShoppingItem, item_id)
    if item is None:
        raise ListNotFound("Покупка не найдена.")
    await require_access(session, user_id=user_id, list_id=item.list_id)
    item.is_done = not item.is_done
    await session.flush()
    return item.list_id


async def delete_item(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
) -> int:
    item = await session.get(ShoppingItem, item_id)
    if item is None:
        raise ListNotFound("Покупка не найдена.")
    list_id = item.list_id
    await require_access(session, user_id=user_id, list_id=list_id)
    await session.delete(item)
    await session.flush()
    return list_id


async def rename_list(
    session: AsyncSession,
    *,
    owner_id: int,
    list_id: int,
    title: str,
) -> ShoppingList:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    shopping_list.title = _normalize_title(title)
    await session.flush()
    return shopping_list


async def delete_list(
    session: AsyncSession,
    *,
    owner_id: int,
    list_id: int,
) -> None:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    await session.delete(shopping_list)
    await session.flush()


async def remove_list_member(
    session: AsyncSession,
    *,
    owner_id: int,
    list_id: int,
    member_user_id: int,
) -> ShoppingList:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    if shopping_list.owner_id == member_user_id:
        raise ValidationError("Владельца списка нельзя удалить из участников.")

    membership = await session.get(ListMember, (list_id, member_user_id))
    if membership is None:
        raise ListNotFound("Участник не найден.")

    await session.delete(membership)
    await clear_list_view_message(session, list_id=list_id, user_id=member_user_id)
    await session.flush()
    return shopping_list


async def ban_list_member(
    session: AsyncSession,
    *,
    owner_id: int,
    list_id: int,
    member_user_id: int,
) -> ShoppingList:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    if shopping_list.owner_id == member_user_id:
        raise ValidationError("Владельца списка нельзя забанить.")

    member_user = await session.get(User, member_user_id)
    membership = await session.get(ListMember, (list_id, member_user_id))
    if member_user is None or membership is None:
        raise ListNotFound("Участник не найден.")

    banned_member = await session.get(ListBannedMember, (list_id, member_user_id))
    if banned_member is None:
        session.add(ListBannedMember(list_id=list_id, user_id=member_user_id))

    await session.delete(membership)
    await clear_list_view_message(session, list_id=list_id, user_id=member_user_id)
    await session.flush()
    return shopping_list


async def _unique_public_token(session: AsyncSession) -> str:
    for _ in range(10):
        token = generate_public_token()
        token_hash = hash_public_token(token)
        existing_id = await session.scalar(
            select(ShoppingList.id).where(ShoppingList.public_token_hash == token_hash)
        )
        if existing_id is None:
            return token
    raise RuntimeError("Could not generate a unique public token.")


async def enable_public_access(
    session: AsyncSession,
    *,
    owner_id: int,
    list_id: int,
    regenerate: bool = False,
) -> str:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    if shopping_list.is_public and shopping_list.public_token and not regenerate:
        return shopping_list.public_token

    token = await _unique_public_token(session)
    shopping_list.is_public = True
    shopping_list.public_token = token
    shopping_list.public_token_hash = hash_public_token(token)
    await session.flush()
    return token


async def disable_public_access(
    session: AsyncSession,
    *,
    owner_id: int,
    list_id: int,
) -> ShoppingList:
    shopping_list, _ = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    shopping_list.is_public = False
    shopping_list.public_token = None
    shopping_list.public_token_hash = None
    await session.execute(delete(ListMember).where(ListMember.list_id == list_id))
    await session.execute(
        delete(ListViewMessage).where(
            ListViewMessage.list_id == list_id,
            ListViewMessage.user_id != owner_id,
        )
    )
    await session.flush()
    return shopping_list


async def join_public_list_by_token(
    session: AsyncSession,
    *,
    user_id: int,
    token: str,
) -> ShoppingList | None:
    token = token.strip()
    if not token:
        return None

    shopping_list = await session.scalar(
        select(ShoppingList).where(
            ShoppingList.is_public.is_(True),
            ShoppingList.public_token_hash == hash_public_token(token),
        )
    )
    if shopping_list is None:
        return None

    if shopping_list.owner_id != user_id:
        banned_member = await session.get(ListBannedMember, (shopping_list.id, user_id))
        if banned_member is not None:
            return None

        membership = await session.get(ListMember, (shopping_list.id, user_id))
        if membership is None:
            session.add(ListMember(list_id=shopping_list.id, user_id=user_id))
            await session.flush()
    return shopping_list


async def assert_owner(
    session: AsyncSession,
    *,
    owner_id: int,
    list_id: int,
) -> ShoppingList:
    shopping_list, level = await require_access(session, user_id=owner_id, list_id=list_id, owner_only=True)
    if level != AccessLevel.owner:
        raise AccessDenied("Настройки списка доступны только владельцу.")
    return shopping_list
