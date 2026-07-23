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
    ExpenseShare,
    ListBannedMember,
    ListMember,
    ListViewMessage,
    ShoppingItem,
    ShoppingList,
    User,
)
from app.services.access import AccessLevel, require_access
from app.services.errors import AccessDenied, ListNotFound, ValidationError
from app.services.tokens import generate_public_token, hash_public_token


ITEM_SCOPE_COMMON = "common"
ITEM_SCOPE_PERSONAL = "personal"
EXPENSE_SOURCE_CASHBOX = "cashbox"
EXPENSE_SOURCE_PERSONAL = "personal"


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


async def get_list_participants(
    session: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> tuple[ShoppingList, Sequence[User], AccessLevel]:
    shopping_list, level = await require_access(session, user_id=user_id, list_id=list_id)
    return shopping_list, await _get_participant_users(session, shopping_list), level


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
    items = await session.scalars(
        select(ShoppingItem)
        .options(selectinload(ShoppingItem.author), selectinload(ShoppingItem.personal_owner))
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
        .options(selectinload(ShoppingItem.author), selectinload(ShoppingItem.personal_owner))
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
) -> list[ShoppingItem]:
    shopping_list, _ = await require_access(session, user_id=user_id, list_id=list_id)
    if scope not in {ITEM_SCOPE_COMMON, ITEM_SCOPE_PERSONAL}:
        raise ValidationError("Не понял, в какой список добавить покупку.")

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
            scope=scope,
            personal_owner_id=user_id if scope == ITEM_SCOPE_PERSONAL else None,
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
        .options(selectinload(ShoppingItem.personal_owner))
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
        created_by_id=user_id,
    )
    session.add(expense)
    await session.flush()
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
