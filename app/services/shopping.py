from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Contribution,
    Expense,
    ExpenseCategory,
    ExpenseItem,
    ExpenseShare,
    ListBannedMember,
    ListMember,
    ListViewMessage,
    ShoppingCategory,
    ShoppingItem,
    ShoppingList,
    User,
)
from app.services.access import AccessLevel, require_access
from app.services.errors import AccessDenied, ListNotFound, ValidationError
from app.services.tokens import generate_public_token, hash_public_token


ITEM_SCOPE_COMMON = "common"
ITEM_SCOPE_PERSONAL = "personal"
SHOPPING_CATEGORY_MODE_PER_ITEM = "per_item"
SHOPPING_CATEGORY_MODE_RECEIPT = "receipt"
EXPENSE_SOURCE_CASHBOX = "cashbox"
EXPENSE_SOURCE_PERSONAL = "personal"
EXPENSE_SPLIT_ALL = "all"
EXPENSE_SPLIT_SELECTED = "selected"
EXPENSE_SPLIT_ME = "me"


@dataclass(frozen=True)
class ParticipantBalance:
    user: User
    contributed: int
    paid_personal: int
    share: int
    balance: int


@dataclass(frozen=True)
class Settlement:
    from_user: User
    to_user: User
    amount: int


@dataclass(frozen=True)
class MoneySummary:
    shopping_list: ShoppingList
    participants: Sequence[User]
    categories: Sequence[ExpenseCategory]
    contributions: Sequence[Contribution]
    expenses: Sequence[Expense]
    balances: Sequence[ParticipantBalance]
    settlements: Sequence[Settlement]
    cashbox_balance: int


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


def _normalize_expense_title(title: str) -> str:
    value = " ".join(title.strip().split())
    if not value:
        raise ValidationError("Название траты не может быть пустым.")
    if len(value) > 255:
        raise ValidationError("Название траты должно быть не длиннее 255 символов.")
    return value


def _normalize_category_title(title: str) -> str:
    value = " ".join(title.strip().split())
    if not value:
        raise ValidationError("Название категории не может быть пустым.")
    if len(value) > 80:
        raise ValidationError("Название категории должно быть не длиннее 80 символов.")
    return value


def _validate_expense_split(default_split: str) -> None:
    if default_split not in {EXPENSE_SPLIT_ALL, EXPENSE_SPLIT_SELECTED, EXPENSE_SPLIT_ME}:
        raise ValidationError("Не понял, как распределять траты этой категории.")


def parse_money_amount(value: str | int) -> int:
    if isinstance(value, int):
        amount = value
    else:
        normalized = value.strip().replace(" ", "").replace(",", ".")
        if not normalized:
            raise ValidationError("Напиши сумму, например 25.50.")
        try:
            decimal = Decimal(normalized)
        except InvalidOperation as error:
            raise ValidationError("Не понял сумму. Напиши число вроде 25 или 25.50.") from error
        if decimal.as_tuple().exponent < -2:
            raise ValidationError("Сумма должна быть с точностью до копеек.")
        amount = int(decimal * 100)

    if amount <= 0:
        raise ValidationError("Сумма должна быть больше нуля.")
    return amount


def format_money_amount(amount: int, currency: str = "BYN") -> str:
    sign = "-" if amount < 0 else ""
    absolute = abs(amount)
    return f"{sign}{absolute // 100}.{absolute % 100:02d} {currency}"


def _split_amount(amount: int, user_ids: Sequence[int]) -> dict[int, int]:
    ordered_user_ids = list(dict.fromkeys(user_ids))
    if not ordered_user_ids:
        raise ValidationError("Нужно выбрать хотя бы одного участника для распределения траты.")

    base = amount // len(ordered_user_ids)
    remainder = amount % len(ordered_user_ids)
    return {
        user_id: base + (1 if index < remainder else 0)
        for index, user_id in enumerate(ordered_user_ids)
    }


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
    shopping_list = ShoppingList(
        owner_id=owner_id,
        cashbox_holder_id=owner_id,
        title=_normalize_title(title),
        currency="BYN",
    )
    session.add(shopping_list)
    await session.flush()
    await _ensure_default_shopping_categories(session, shopping_list)
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


async def _get_participant_users(session: AsyncSession, shopping_list: ShoppingList) -> list[User]:
    owner = await session.get(User, shopping_list.owner_id)
    if owner is None:
        raise ListNotFound("Владелец списка не найден.")

    members_result = await session.scalars(
        select(User)
        .join(ListMember, ListMember.user_id == User.id)
        .where(ListMember.list_id == shopping_list.id)
        .order_by(ListMember.joined_at.asc(), User.id.asc())
    )
    return [owner, *members_result.all()]


def _validate_shopping_category_scope(scope: str) -> None:
    if scope not in {ITEM_SCOPE_COMMON, ITEM_SCOPE_PERSONAL}:
        raise ValidationError("Не понял, это общая или личная категория покупок.")


def _validate_shopping_category_mode(accounting_mode: str) -> None:
    if accounting_mode not in {SHOPPING_CATEGORY_MODE_PER_ITEM, SHOPPING_CATEGORY_MODE_RECEIPT}:
        raise ValidationError("Не понял режим расчёта категории покупок.")


async def _shopping_category_title_exists(
    session: AsyncSession,
    *,
    list_id: int,
    title: str,
    scope: str,
    owner_id: int | None,
    exclude_category_id: int | None = None,
) -> bool:
    filters = [
        ShoppingCategory.list_id == list_id,
        ShoppingCategory.scope == scope,
    ]
    if owner_id is None:
        filters.append(ShoppingCategory.owner_id.is_(None))
    else:
        filters.append(ShoppingCategory.owner_id == owner_id)
    if exclude_category_id is not None:
        filters.append(ShoppingCategory.id != exclude_category_id)
    existing_titles = (await session.scalars(select(ShoppingCategory.title).where(*filters))).all()
    return title.casefold() in {existing.casefold() for existing in existing_titles}


async def _next_shopping_category_position(session: AsyncSession, list_id: int) -> int:
    max_position = await session.scalar(
        select(func.coalesce(func.max(ShoppingCategory.position), 0)).where(ShoppingCategory.list_id == list_id)
    )
    return int(max_position or 0) + 1


async def _create_default_shopping_category(
    session: AsyncSession,
    *,
    shopping_list: ShoppingList,
    title: str,
    scope: str,
    owner_id: int | None,
    position: int | None = None,
) -> ShoppingCategory:
    category = ShoppingCategory(
        list_id=shopping_list.id,
        title=title,
        scope=scope,
        owner_id=owner_id,
        accounting_mode=SHOPPING_CATEGORY_MODE_PER_ITEM,
        position=position if position is not None else await _next_shopping_category_position(session, shopping_list.id),
        created_by_id=owner_id or shopping_list.owner_id,
    )
    session.add(category)
    await session.flush()
    return category


async def _ensure_default_common_category(session: AsyncSession, shopping_list: ShoppingList) -> ShoppingCategory:
    category = await session.scalar(
        select(ShoppingCategory)
        .where(
            ShoppingCategory.list_id == shopping_list.id,
            ShoppingCategory.scope == ITEM_SCOPE_COMMON,
        )
        .order_by(ShoppingCategory.position.asc(), ShoppingCategory.id.asc())
    )
    if category is not None:
        return category
    return await _create_default_shopping_category(
        session,
        shopping_list=shopping_list,
        title="Общее",
        scope=ITEM_SCOPE_COMMON,
        owner_id=None,
        position=1,
    )


async def _ensure_personal_shopping_category(
    session: AsyncSession,
    shopping_list: ShoppingList,
    *,
    owner_id: int,
) -> ShoppingCategory:
    category = await session.scalar(
        select(ShoppingCategory)
        .where(
            ShoppingCategory.list_id == shopping_list.id,
            ShoppingCategory.scope == ITEM_SCOPE_PERSONAL,
            ShoppingCategory.owner_id == owner_id,
        )
        .order_by(ShoppingCategory.position.asc(), ShoppingCategory.id.asc())
    )
    if category is not None:
        return category
    return await _create_default_shopping_category(
        session,
        shopping_list=shopping_list,
        title="Личное",
        scope=ITEM_SCOPE_PERSONAL,
        owner_id=owner_id,
    )


async def _ensure_default_shopping_categories(session: AsyncSession, shopping_list: ShoppingList) -> None:
    await _ensure_default_common_category(session, shopping_list)
    for participant in await _get_participant_users(session, shopping_list):
        await _ensure_personal_shopping_category(session, shopping_list, owner_id=participant.id)


def _ensure_shopping_category_edit_allowed(
    *,
    category: ShoppingCategory,
    user_id: int,
    level: AccessLevel,
) -> None:
    if level == AccessLevel.owner:
        return
    if category.scope == ITEM_SCOPE_PERSONAL and category.owner_id == user_id:
        return
    raise AccessDenied("Эту категорию покупок может менять только владелец тусовки или владелец личной категории.")


def _ensure_shopping_category_add_allowed(
    *,
    category: ShoppingCategory,
    user_id: int,
    level: AccessLevel,
) -> None:
    if category.scope == ITEM_SCOPE_COMMON:
        return
    if level == AccessLevel.owner or category.owner_id == user_id:
        return
    raise AccessDenied("В чужую личную категорию можно смотреть, но нельзя добавлять покупки.")


async def get_list_participants(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> tuple[ShoppingList, Sequence[User], AccessLevel]:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    return shopping_list, await _get_participant_users(session, shopping_list), level


async def get_expense_categories(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> tuple[ShoppingList, Sequence[ExpenseCategory], AccessLevel]:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    categories = (
        await session.scalars(
            select(ExpenseCategory)
            .where(ExpenseCategory.list_id == shopping_list.id)
            .order_by(ExpenseCategory.position.asc(), ExpenseCategory.id.asc())
        )
    ).all()
    return shopping_list, categories, level


async def create_expense_category(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    title: str,
    default_split: str = EXPENSE_SPLIT_SELECTED,
) -> ExpenseCategory:
    shopping_list, _ = await require_access(session, user_id=user_id, list_id=list_id)
    normalized_title = _normalize_category_title(title)
    _validate_expense_split(default_split)
    existing_titles = (
        await session.scalars(
            select(ExpenseCategory.title).where(ExpenseCategory.list_id == shopping_list.id)
        )
    ).all()
    if normalized_title.casefold() in {existing.casefold() for existing in existing_titles}:
        raise ValidationError("Такая категория уже есть в этой тусовке.")

    max_position = await session.scalar(
        select(func.coalesce(func.max(ExpenseCategory.position), 0)).where(
            ExpenseCategory.list_id == shopping_list.id
        )
    )
    category = ExpenseCategory(
        list_id=shopping_list.id,
        title=normalized_title,
        default_split=default_split,
        position=int(max_position or 0) + 1,
        created_by_id=user_id,
    )
    session.add(category)
    await session.flush()
    return category


async def get_expense_category(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
) -> tuple[ShoppingList, ExpenseCategory, AccessLevel]:
    category = await session.get(ExpenseCategory, category_id)
    if category is None:
        raise ListNotFound("Категория не найдена.")
    shopping_list, level = await require_access(session, user_id=user_id, list_id=category.list_id)
    return shopping_list, category, level


async def rename_expense_category(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    title: str,
) -> ExpenseCategory:
    shopping_list, category, _ = await get_expense_category(session, user_id=user_id, category_id=category_id)
    normalized_title = _normalize_category_title(title)
    existing_titles = (
        await session.scalars(
            select(ExpenseCategory.title).where(
                ExpenseCategory.list_id == shopping_list.id,
                ExpenseCategory.id != category.id,
            )
        )
    ).all()
    if normalized_title.casefold() in {existing.casefold() for existing in existing_titles}:
        raise ValidationError("Такая категория уже есть в этой тусовке.")
    category.title = normalized_title
    await session.flush()
    return category


async def set_expense_category_default_split(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    default_split: str,
) -> ExpenseCategory:
    _, category, _ = await get_expense_category(session, user_id=user_id, category_id=category_id)
    _validate_expense_split(default_split)
    category.default_split = default_split
    await session.flush()
    return category


async def get_shopping_categories(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> tuple[ShoppingList, Sequence[ShoppingCategory], AccessLevel]:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    await _ensure_default_shopping_categories(session, shopping_list)
    categories = (
        await session.scalars(
            select(ShoppingCategory)
            .options(selectinload(ShoppingCategory.owner))
            .where(ShoppingCategory.list_id == shopping_list.id)
            .order_by(
                ShoppingCategory.scope.asc(),
                ShoppingCategory.position.asc(),
                ShoppingCategory.id.asc(),
            )
        )
    ).all()
    return shopping_list, categories, level


async def get_shopping_category(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
) -> tuple[ShoppingList, ShoppingCategory, AccessLevel]:
    category = await session.scalar(
        select(ShoppingCategory)
        .options(selectinload(ShoppingCategory.owner))
        .where(ShoppingCategory.id == category_id)
    )
    if category is None:
        raise ListNotFound("Категория покупок не найдена.")
    shopping_list, level = await require_access(session, user_id=user_id, list_id=category.list_id)
    return shopping_list, category, level


async def get_shopping_category_items(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
) -> tuple[ShoppingList, ShoppingCategory, Sequence[ShoppingItem], AccessLevel]:
    shopping_list, category, level = await get_shopping_category(
        session,
        user_id=user_id,
        category_id=category_id,
    )
    items = (
        await session.scalars(
            select(ShoppingItem)
            .options(
                selectinload(ShoppingItem.author),
                selectinload(ShoppingItem.personal_owner),
                selectinload(ShoppingItem.category).selectinload(ShoppingCategory.owner),
            )
            .where(
                ShoppingItem.list_id == shopping_list.id,
                ShoppingItem.category_id == category.id,
            )
            .order_by(ShoppingItem.is_done.asc(), ShoppingItem.position.asc(), ShoppingItem.id.asc())
        )
    ).all()
    return shopping_list, category, items, level


async def create_shopping_category(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    title: str,
    scope: str,
    accounting_mode: str = SHOPPING_CATEGORY_MODE_PER_ITEM,
    owner_id: int | None = None,
) -> ShoppingCategory:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    _validate_shopping_category_scope(scope)
    _validate_shopping_category_mode(accounting_mode)
    normalized_title = _normalize_category_title(title)

    if scope == ITEM_SCOPE_COMMON:
        owner_id = None
    else:
        owner_id = owner_id or user_id
        if owner_id != user_id and level != AccessLevel.owner:
            raise AccessDenied("Создать личную категорию для другого участника может только владелец тусовки.")
        participant_ids = await _participant_user_ids(session, shopping_list)
        if owner_id not in participant_ids:
            raise ValidationError("Личная категория должна принадлежать участнику тусовки.")

    if await _shopping_category_title_exists(
        session,
        list_id=shopping_list.id,
        title=normalized_title,
        scope=scope,
        owner_id=owner_id,
    ):
        raise ValidationError("Такая категория покупок уже есть.")

    category = ShoppingCategory(
        list_id=shopping_list.id,
        title=normalized_title,
        scope=scope,
        owner_id=owner_id,
        accounting_mode=accounting_mode,
        position=await _next_shopping_category_position(session, shopping_list.id),
        created_by_id=user_id,
    )
    session.add(category)
    await session.flush()
    return category


async def rename_shopping_category(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    title: str,
) -> ShoppingCategory:
    shopping_list, category, level = await get_shopping_category(session, user_id=user_id, category_id=category_id)
    _ensure_shopping_category_edit_allowed(category=category, user_id=user_id, level=level)
    normalized_title = _normalize_category_title(title)
    if await _shopping_category_title_exists(
        session,
        list_id=shopping_list.id,
        title=normalized_title,
        scope=category.scope,
        owner_id=category.owner_id,
        exclude_category_id=category.id,
    ):
        raise ValidationError("Такая категория покупок уже есть.")
    category.title = normalized_title
    await session.flush()
    return category


async def set_shopping_category_accounting_mode(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    accounting_mode: str,
) -> ShoppingCategory:
    _, category, level = await get_shopping_category(session, user_id=user_id, category_id=category_id)
    _ensure_shopping_category_edit_allowed(category=category, user_id=user_id, level=level)
    _validate_shopping_category_mode(accounting_mode)
    category.accounting_mode = accounting_mode
    await session.flush()
    return category


async def _participant_user_ids(session: AsyncSession, shopping_list: ShoppingList) -> list[int]:
    return [user.id for user in await _get_participant_users(session, shopping_list)]


async def _normalize_share_user_ids(
    session: AsyncSession,
    shopping_list: ShoppingList,
    share_user_ids: Sequence[int] | None,
) -> list[int]:
    participants = await _get_participant_users(session, shopping_list)
    participant_ids = [user.id for user in participants]
    if share_user_ids is None:
        return participant_ids

    requested = set(share_user_ids)
    selected = [user_id for user_id in participant_ids if user_id in requested]
    if len(selected) != len(requested):
        raise ValidationError("Можно распределять траты только между участниками тусовки.")
    return selected


async def get_list_view(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> tuple[ShoppingList, Sequence[ShoppingItem], AccessLevel]:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    await _ensure_default_shopping_categories(session, shopping_list)
    items = await session.scalars(
        select(ShoppingItem)
        .options(
            selectinload(ShoppingItem.author),
            selectinload(ShoppingItem.personal_owner),
            selectinload(ShoppingItem.category).selectinload(ShoppingCategory.owner),
        )
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
        .options(
            selectinload(ShoppingItem.author),
            selectinload(ShoppingItem.personal_owner),
            selectinload(ShoppingItem.category).selectinload(ShoppingCategory.owner),
        )
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
    scope: str = ITEM_SCOPE_COMMON,
    category_id: int | None = None,
) -> list[ShoppingItem]:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    if scope not in {ITEM_SCOPE_COMMON, ITEM_SCOPE_PERSONAL}:
        raise ValidationError("Не понял, в какой список добавить покупку.")

    lines = _normalize_item_lines(text)
    if category_id is not None:
        _, category, _ = await get_shopping_category(session, user_id=user_id, category_id=category_id)
        if category.list_id != shopping_list.id:
            raise ValidationError("Категория покупок должна принадлежать этой тусовке.")
        _ensure_shopping_category_add_allowed(category=category, user_id=user_id, level=level)
    else:
        await _ensure_default_shopping_categories(session, shopping_list)
        category = (
            await _ensure_default_common_category(session, shopping_list)
            if scope == ITEM_SCOPE_COMMON
            else await _ensure_personal_shopping_category(session, shopping_list, owner_id=user_id)
        )

    scope = category.scope
    personal_owner_id = category.owner_id if scope == ITEM_SCOPE_PERSONAL else None
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
            scope=scope,
            personal_owner_id=personal_owner_id,
            category_id=category.id,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    return items


async def _get_item_with_access(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
) -> tuple[ShoppingList, ShoppingItem, AccessLevel]:
    item = await session.scalar(
        select(ShoppingItem)
        .options(
            selectinload(ShoppingItem.personal_owner),
            selectinload(ShoppingItem.category).selectinload(ShoppingCategory.owner),
            selectinload(ShoppingItem.expense_links).selectinload(ExpenseItem.expense),
        )
        .where(ShoppingItem.id == item_id)
    )
    if item is None:
        raise ListNotFound("Покупка не найдена.")
    shopping_list, level = await require_access(session, user_id=user_id, list_id=item.list_id)
    return shopping_list, item, level


def _ensure_item_edit_allowed(
    *,
    shopping_list: ShoppingList,
    item: ShoppingItem,
    user_id: int,
    level: AccessLevel,
) -> None:
    if item.scope != ITEM_SCOPE_PERSONAL:
        return
    if level == AccessLevel.owner or item.personal_owner_id == user_id:
        return
    raise AccessDenied("В чужой личный список можно смотреть, но нельзя удалять или редактировать.")


async def toggle_item(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
) -> int:
    _, item, _ = await _get_item_with_access(session, user_id=user_id, item_id=item_id)
    item.is_done = not item.is_done
    await session.flush()
    return item.list_id


async def unmark_item(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
) -> int:
    _, item, _ = await _get_item_with_access(session, user_id=user_id, item_id=item_id)
    receipt_links = [
        item_link
        for item_link in item.expense_links
        if item_link.expense is not None and item_link.expense.item_id is None
    ]
    if receipt_links:
        raise ValidationError("Эта покупка закрыта чеком. Можно отменить только весь чек целиком.")
    item.is_done = False
    await session.execute(delete(Expense).where(Expense.item_id == item.id))
    await session.flush()
    return item.list_id


async def set_all_items_done(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    is_done: bool,
) -> int:
    shopping_list, _ = await require_access(session, user_id=user_id, list_id=list_id)
    await session.execute(
        update(ShoppingItem)
        .where(ShoppingItem.list_id == shopping_list.id)
        .values(is_done=is_done)
    )
    await session.flush()
    return shopping_list.id


async def delete_item(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
) -> int:
    shopping_list, item, level = await _get_item_with_access(session, user_id=user_id, item_id=item_id)
    _ensure_item_edit_allowed(shopping_list=shopping_list, item=item, user_id=user_id, level=level)
    list_id = item.list_id
    await session.delete(item)
    await session.flush()
    return list_id


async def get_item_view(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
) -> tuple[ShoppingList, ShoppingItem, AccessLevel]:
    return await _get_item_with_access(session, user_id=user_id, item_id=item_id)


async def create_contribution(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    amount: str | int,
    contributor_id: int | None = None,
    note: str | None = None,
) -> Contribution:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    contributor_id = contributor_id or user_id
    if contributor_id != user_id and level != AccessLevel.owner:
        raise AccessDenied("Записать взнос за другого участника может только владелец тусовки.")

    participant_ids = await _participant_user_ids(session, shopping_list)
    if contributor_id not in participant_ids:
        raise ValidationError("Взнос можно записать только за участника тусовки.")

    normalized_note = " ".join(note.strip().split()) if note else None
    contribution = Contribution(
        list_id=shopping_list.id,
        user_id=contributor_id,
        amount=parse_money_amount(amount),
        note=normalized_note[:255] if normalized_note else None,
        created_by_id=user_id,
    )
    session.add(contribution)
    await session.flush()
    return contribution


async def create_expense(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    title: str,
    amount: str | int,
    source: str,
    share_user_ids: Sequence[int] | None = None,
    payer_id: int | None = None,
    item_id: int | None = None,
    item_ids: Sequence[int] | None = None,
    category_id: int | None = None,
) -> Expense:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    payer_id = payer_id or user_id
    if payer_id != user_id and level != AccessLevel.owner:
        raise AccessDenied("Записать оплату за другого участника может только владелец тусовки.")
    if source not in {EXPENSE_SOURCE_CASHBOX, EXPENSE_SOURCE_PERSONAL}:
        raise ValidationError("Не понял источник оплаты.")

    participant_ids = await _participant_user_ids(session, shopping_list)
    if payer_id not in participant_ids:
        raise ValidationError("Плательщик должен быть участником тусовки.")

    category: ExpenseCategory | None = None
    if category_id is not None:
        category = await session.get(ExpenseCategory, category_id)
        if category is None or category.list_id != shopping_list.id:
            raise ValidationError("Категория должна принадлежать этой тусовке.")

    linked_item_ids = list(dict.fromkeys(item_ids or ([] if item_id is None else [item_id])))
    if linked_item_ids:
        existing_item_ids = set(
            (
                await session.scalars(
                    select(ShoppingItem.id).where(
                        ShoppingItem.list_id == shopping_list.id,
                        ShoppingItem.id.in_(linked_item_ids),
                    )
                )
            ).all()
        )
        if existing_item_ids != set(linked_item_ids):
            raise ValidationError("Все товары расхода должны принадлежать этой тусовке.")

    selected_share_user_ids = await _normalize_share_user_ids(session, shopping_list, share_user_ids)
    amount_minor = parse_money_amount(amount)
    shares = _split_amount(amount_minor, selected_share_user_ids)
    expense = Expense(
        list_id=shopping_list.id,
        title=_normalize_expense_title(title),
        amount=amount_minor,
        payer_id=payer_id,
        source=source,
        item_id=item_id,
        category_id=category.id if category is not None else None,
        created_by_id=user_id,
    )
    session.add(expense)
    await session.flush()
    for linked_item_id in linked_item_ids:
        session.add(ExpenseItem(expense_id=expense.id, item_id=linked_item_id))
    for share_user_id, share_amount in shares.items():
        session.add(ExpenseShare(expense_id=expense.id, user_id=share_user_id, amount=share_amount))
    await session.flush()
    return expense


async def record_item_purchase(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
    amount: str | int,
    source: str,
) -> int:
    _, item, _ = await _get_item_with_access(session, user_id=user_id, item_id=item_id)
    if item.is_done:
        raise ValidationError("Эта покупка уже отмечена купленной.")

    if item.category is not None and item.category.accounting_mode == SHOPPING_CATEGORY_MODE_RECEIPT:
        raise ValidationError("Эта категория считается по чеку. Открой категорию и внеси общий чек.")

    if item.scope == ITEM_SCOPE_PERSONAL:
        share_user_ids = [int(item.personal_owner_id)]
    else:
        share_user_ids = None

    await create_expense(
        session,
        user_id=user_id,
        list_id=item.list_id,
        title=item.text,
        amount=amount,
        source=source,
        share_user_ids=share_user_ids,
        payer_id=user_id,
        item_id=item.id,
    )
    item.is_done = True
    await session.flush()
    return item.list_id


async def _default_share_user_ids_for_shopping_category(
    session: AsyncSession,
    shopping_list: ShoppingList,
    category: ShoppingCategory,
) -> Sequence[int] | None:
    if category.scope == ITEM_SCOPE_PERSONAL:
        return [int(category.owner_id)]
    return None


async def record_receipt_purchase(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    item_ids: Sequence[int],
    amount: str | int,
    source: str,
    share_user_ids: Sequence[int] | None = None,
) -> int:
    shopping_list, category, _ = await get_shopping_category(session, user_id=user_id, category_id=category_id)
    if category.accounting_mode != SHOPPING_CATEGORY_MODE_RECEIPT:
        raise ValidationError("Эта категория считается по товарам. Для чека сначала включи режим по чеку.")

    selected_item_ids = list(dict.fromkeys(int(item_id) for item_id in item_ids))
    if not selected_item_ids:
        raise ValidationError("Выбери хотя бы один товар из чека.")

    items = (
        await session.scalars(
            select(ShoppingItem)
            .where(
                ShoppingItem.list_id == shopping_list.id,
                ShoppingItem.category_id == category.id,
                ShoppingItem.id.in_(selected_item_ids),
            )
            .order_by(ShoppingItem.position.asc(), ShoppingItem.id.asc())
        )
    ).all()
    if {item.id for item in items} != set(selected_item_ids):
        raise ValidationError("В чек можно добавить только товары выбранной категории.")
    if any(item.is_done for item in items):
        raise ValidationError("В чеке есть товар, который уже отмечен купленным.")

    default_share_user_ids = (
        share_user_ids
        if share_user_ids is not None
        else await _default_share_user_ids_for_shopping_category(session, shopping_list, category)
    )
    await create_expense(
        session,
        user_id=user_id,
        list_id=shopping_list.id,
        title=f"Чек: {category.title}",
        amount=amount,
        source=source,
        share_user_ids=default_share_user_ids,
        payer_id=user_id,
        item_ids=[item.id for item in items],
    )
    for item in items:
        item.is_done = True
    await session.flush()
    return shopping_list.id


async def get_receipt_expense_for_item(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
) -> tuple[ShoppingList, Expense] | None:
    shopping_list, item, _ = await _get_item_with_access(session, user_id=user_id, item_id=item_id)
    expense = await session.scalar(
        select(Expense)
        .join(ExpenseItem, ExpenseItem.expense_id == Expense.id)
        .options(selectinload(Expense.item_links).selectinload(ExpenseItem.item))
        .where(
            Expense.list_id == shopping_list.id,
            Expense.item_id.is_(None),
            ExpenseItem.item_id == item.id,
        )
        .order_by(Expense.id.desc())
    )
    if expense is None:
        return None
    return shopping_list, expense


async def cancel_receipt_expense(
    session: AsyncSession,
    *,
    user_id: int,
    expense_id: int,
) -> int:
    expense = await session.scalar(
        select(Expense)
        .options(selectinload(Expense.item_links).selectinload(ExpenseItem.item))
        .where(Expense.id == expense_id)
    )
    if expense is None:
        raise ListNotFound("Чек не найден.")
    shopping_list, _ = await require_access(session, user_id=user_id, list_id=expense.list_id)
    if expense.item_id is not None or not expense.item_links:
        raise ValidationError("Это не чековая покупка.")
    for item_link in expense.item_links:
        item_link.item.is_done = False
    await session.delete(expense)
    await session.flush()
    return shopping_list.id


def _build_settlements(balances: Sequence[ParticipantBalance]) -> list[Settlement]:
    creditors = [
        [balance.user, balance.balance]
        for balance in balances
        if balance.balance > 0
    ]
    debtors = [
        [balance.user, -balance.balance]
        for balance in balances
        if balance.balance < 0
    ]
    settlements: list[Settlement] = []
    creditor_index = 0
    debtor_index = 0

    while creditor_index < len(creditors) and debtor_index < len(debtors):
        debtor_user, debt_amount = debtors[debtor_index]
        creditor_user, credit_amount = creditors[creditor_index]
        amount = min(debt_amount, credit_amount)
        settlements.append(Settlement(from_user=debtor_user, to_user=creditor_user, amount=amount))
        debtors[debtor_index][1] -= amount
        creditors[creditor_index][1] -= amount
        if debtors[debtor_index][1] == 0:
            debtor_index += 1
        if creditors[creditor_index][1] == 0:
            creditor_index += 1

    return settlements


async def get_money_summary(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> MoneySummary:
    shopping_list, _ = await require_access(session, user_id=user_id, list_id=list_id)
    participants = await _get_participant_users(session, shopping_list)
    participant_ids = {participant.id for participant in participants}
    categories = (
        await session.scalars(
            select(ExpenseCategory)
            .where(ExpenseCategory.list_id == shopping_list.id)
            .order_by(ExpenseCategory.position.asc(), ExpenseCategory.id.asc())
        )
    ).all()

    contributions = (
        await session.scalars(
            select(Contribution)
            .options(selectinload(Contribution.user), selectinload(Contribution.created_by))
            .where(Contribution.list_id == shopping_list.id)
            .order_by(Contribution.created_at.asc(), Contribution.id.asc())
        )
    ).all()
    expenses = (
        await session.scalars(
            select(Expense)
            .options(
                selectinload(Expense.payer),
                selectinload(Expense.item),
                selectinload(Expense.item_links).selectinload(ExpenseItem.item),
                selectinload(Expense.category),
                selectinload(Expense.shares).selectinload(ExpenseShare.user),
            )
            .where(Expense.list_id == shopping_list.id)
            .order_by(Expense.created_at.asc(), Expense.id.asc())
        )
    ).all()

    contributed_by_user = {participant.id: 0 for participant in participants}
    paid_personal_by_user = {participant.id: 0 for participant in participants}
    share_by_user = {participant.id: 0 for participant in participants}

    for contribution in contributions:
        if contribution.user_id in participant_ids:
            contributed_by_user[contribution.user_id] += contribution.amount

    cashbox_expense_total = 0
    for expense in expenses:
        if expense.source == EXPENSE_SOURCE_CASHBOX:
            cashbox_expense_total += expense.amount
        elif expense.payer_id in participant_ids:
            paid_personal_by_user[expense.payer_id] += expense.amount

        for share in expense.shares:
            if share.user_id in participant_ids:
                share_by_user[share.user_id] += share.amount

    balances = [
        ParticipantBalance(
            user=participant,
            contributed=contributed_by_user[participant.id],
            paid_personal=paid_personal_by_user[participant.id],
            share=share_by_user[participant.id],
            balance=contributed_by_user[participant.id]
            + paid_personal_by_user[participant.id]
            - share_by_user[participant.id],
        )
        for participant in participants
    ]
    return MoneySummary(
        shopping_list=shopping_list,
        participants=participants,
        categories=categories,
        contributions=contributions,
        expenses=expenses,
        balances=balances,
        settlements=_build_settlements(balances),
        cashbox_balance=sum(contributed_by_user.values()) - cashbox_expense_total,
    )


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


async def _cleanup_removed_member(session: AsyncSession, *, list_id: int, member_user_id: int) -> None:
    expense_ids = select(Expense.id).where(Expense.list_id == list_id)
    paid_expense_ids = select(Expense.id).where(
        Expense.list_id == list_id,
        Expense.payer_id == member_user_id,
    )
    await session.execute(
        delete(ShoppingItem).where(
            ShoppingItem.list_id == list_id,
            ShoppingItem.scope == ITEM_SCOPE_PERSONAL,
            ShoppingItem.personal_owner_id == member_user_id,
        )
    )
    await session.execute(
        delete(ShoppingCategory).where(
            ShoppingCategory.list_id == list_id,
            ShoppingCategory.scope == ITEM_SCOPE_PERSONAL,
            ShoppingCategory.owner_id == member_user_id,
        )
    )
    await session.execute(
        delete(ExpenseShare).where(
            or_(
                ExpenseShare.expense_id.in_(paid_expense_ids),
                and_(
                    ExpenseShare.expense_id.in_(expense_ids),
                    ExpenseShare.user_id == member_user_id,
                ),
            )
        )
    )
    await session.execute(
        delete(Expense).where(
            Expense.list_id == list_id,
            Expense.payer_id == member_user_id,
        )
    )
    await session.execute(
        delete(Contribution).where(
            Contribution.list_id == list_id,
            Contribution.user_id == member_user_id,
        )
    )


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
    await _cleanup_removed_member(session, list_id=list_id, member_user_id=member_user_id)
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
    await _cleanup_removed_member(session, list_id=list_id, member_user_id=member_user_id)
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
    member_ids = (
        await session.scalars(select(ListMember.user_id).where(ListMember.list_id == list_id))
    ).all()
    for member_id in member_ids:
        await _cleanup_removed_member(session, list_id=list_id, member_user_id=member_id)
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
        await _ensure_personal_shopping_category(session, shopping_list, owner_id=user_id)
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
