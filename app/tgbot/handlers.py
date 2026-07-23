from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import shopping
from app.services.access import AccessLevel
from app.services.errors import AccessDenied, LifeHelperError, ListNotFound, ValidationError
from app.tgbot.keyboards import (
    cancel_keyboard,
    delete_confirm_keyboard,
    expense_participants_keyboard,
    expense_source_keyboard,
    expense_split_keyboard,
    home_keyboard,
    item_purchase_source_keyboard,
    list_keyboard,
    lists_keyboard,
    members_keyboard,
    members_management_keyboard,
    money_keyboard,
    settings_keyboard,
)
from app.tgbot.states import ShoppingListStates
from app.tgbot.texts import (
    HELP_TEXT,
    WELCOME_TEXT,
    format_list_text,
    format_lists_text,
    format_money_final_text,
    format_money_text,
    format_members_management_text,
    format_members_text,
    format_settings_text,
)

router = Router(name="shopping")
logger = logging.getLogger(__name__)


async def _ensure_user(session: AsyncSession, event_user: Any) -> int:
    user = await shopping.upsert_user(session, event_user)
    return user.id


async def _answer_callback(query: CallbackQuery, text: str | None = None, *, show_alert: bool = False) -> None:
    try:
        await query.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest:
        pass


def _is_callback_target(target: Any) -> bool:
    return isinstance(target, CallbackQuery) or (
        hasattr(target, "answer")
        and hasattr(target, "data")
        and hasattr(target, "message")
    )


async def _send_or_edit(
    target: Message | CallbackQuery,
    text: str,
    *,
    reply_markup: Any = None,
    ack: bool = True,
) -> Any | None:
    if _is_callback_target(target):
        if ack:
            await _answer_callback(target)
        if target.message is None:
            return None
        try:
            result = await target.message.edit_text(text, reply_markup=reply_markup)
            return result if isinstance(result, Message) else target.message
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).lower():
                return target.message
            return await target.message.answer(text, reply_markup=reply_markup)

    return await target.answer(text, reply_markup=reply_markup)


def _parse_id(value: str | None, prefix: str) -> int | None:
    if not value or not value.startswith(prefix):
        return None
    try:
        return int(value.removeprefix(prefix))
    except ValueError:
        return None


def _parse_two_ids(value: str | None, prefix: str) -> tuple[int, int] | None:
    if not value or not value.startswith(prefix):
        return None
    parts = value.removeprefix(prefix).split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _message_identity(message: Any | None) -> tuple[int, int] | None:
    if message is None:
        return None
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    message_id = getattr(message, "message_id", None)
    if chat_id is None or message_id is None:
        return None
    try:
        return int(chat_id), int(message_id)
    except (TypeError, ValueError):
        return None


async def _clear_current_list_view(target: Message | CallbackQuery, session: AsyncSession, user_id: int) -> None:
    if not _is_callback_target(target):
        return
    identity = _message_identity(target.message)
    if identity is None:
        return
    chat_id, message_id = identity
    await shopping.clear_list_view_message_by_message(
        session,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
    )


async def _show_home(message: Message) -> None:
    await message.answer(WELCOME_TEXT, reply_markup=home_keyboard())


async def _show_lists(target: Message | CallbackQuery, session: AsyncSession, user_id: int) -> None:
    await _clear_current_list_view(target, session, user_id)
    owned, shared = await shopping.list_owned_and_shared(session, user_id=user_id)
    await _send_or_edit(target, format_lists_text(owned, shared), reply_markup=lists_keyboard(owned, shared))


async def _show_list(target: Message | CallbackQuery, session: AsyncSession, user_id: int, list_id: int) -> None:
    shopping_list, items, level = await shopping.get_list_view(session, user_id=user_id, list_id=list_id)
    sent_message = await _send_or_edit(
        target,
        format_list_text(shopping_list, items, level),
        reply_markup=list_keyboard(shopping_list, items, level, user_id=user_id),
    )
    identity = _message_identity(sent_message)
    if identity is not None:
        chat_id, message_id = identity
        await shopping.save_list_view_message(
            session,
            list_id=list_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
        )


async def _show_money(target: Message | CallbackQuery, session: AsyncSession, user_id: int, list_id: int) -> None:
    await _clear_current_list_view(target, session, user_id)
    summary = await shopping.get_money_summary(session, user_id=user_id, list_id=list_id)
    await _send_or_edit(
        target,
        format_money_text(summary),
        reply_markup=money_keyboard(summary.shopping_list),
    )


async def _show_money_final(target: Message | CallbackQuery, session: AsyncSession, user_id: int, list_id: int) -> None:
    await _clear_current_list_view(target, session, user_id)
    summary = await shopping.get_money_summary(session, user_id=user_id, list_id=list_id)
    await _send_or_edit(
        target,
        format_money_final_text(summary),
        reply_markup=money_keyboard(summary.shopping_list),
    )


async def _show_settings(target: Message | CallbackQuery, session: AsyncSession, user_id: int, list_id: int) -> None:
    await _clear_current_list_view(target, session, user_id)
    shopping_list = await shopping.assert_owner(session, owner_id=user_id, list_id=list_id)
    await _send_or_edit(target, format_settings_text(shopping_list), reply_markup=settings_keyboard(shopping_list))


async def _show_members(target: Message | CallbackQuery, session: AsyncSession, user_id: int, list_id: int) -> None:
    await _clear_current_list_view(target, session, user_id)
    shopping_list, owner, members, level = await shopping.get_list_members_view(
        session,
        user_id=user_id,
        list_id=list_id,
    )
    await _send_or_edit(
        target,
        format_members_text(shopping_list, owner, members),
        reply_markup=members_keyboard(shopping_list, level),
    )


async def _show_manage_members(
    target: Message | CallbackQuery,
    session: AsyncSession,
    owner_id: int,
    list_id: int,
    *,
    ack: bool = True,
) -> None:
    await _clear_current_list_view(target, session, owner_id)
    shopping_list, members = await shopping.get_manageable_list_members_view(
        session,
        owner_id=owner_id,
        list_id=list_id,
    )
    await _send_or_edit(
        target,
        format_members_management_text(shopping_list, members),
        reply_markup=members_management_keyboard(shopping_list, members),
        ack=ack,
    )


async def _handle_service_error(target: Message | CallbackQuery, error: Exception) -> None:
    if isinstance(error, (AccessDenied, ListNotFound, ValidationError)):
        text = str(error)
    else:
        text = "Что-то пошло не так. Попробуй еще раз."

    if _is_callback_target(target):
        await _answer_callback(target, text, show_alert=True)
    else:
        await target.answer(text)


def _is_stale_edit_error(error: TelegramBadRequest) -> bool:
    text = str(error).lower()
    stale_markers = (
        "message to edit not found",
        "message can't be edited",
        "message is not found",
        "chat not found",
        "message identifier is not specified",
        "not enough rights",
    )
    return any(marker in text for marker in stale_markers)


async def _broadcast_public_list_update(
    bot: Bot,
    session: AsyncSession,
    list_id: int,
    *,
    exclude_user_id: int | None = None,
) -> None:
    update_view = await shopping.get_public_list_update_view(session, list_id=list_id)
    if update_view is None:
        return

    shopping_list, items, view_messages = update_view
    for view_message in view_messages:
        if view_message.user_id == exclude_user_id:
            continue

        level = AccessLevel.owner if view_message.user_id == shopping_list.owner_id else AccessLevel.member
        try:
            await bot.edit_message_text(
                text=format_list_text(shopping_list, items, level),
                chat_id=view_message.chat_id,
                message_id=view_message.message_id,
                reply_markup=list_keyboard(shopping_list, items, level, user_id=view_message.user_id),
            )
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).lower():
                continue
            if _is_stale_edit_error(error):
                await shopping.clear_list_view_message(
                    session,
                    list_id=view_message.list_id,
                    user_id=view_message.user_id,
                )
                continue
            logger.warning(
                "Could not edit public list view message for list_id=%s user_id=%s",
                list_id,
                view_message.user_id,
                exc_info=True,
            )
        except TelegramForbiddenError:
            await shopping.clear_list_view_message(
                session,
                list_id=view_message.list_id,
                user_id=view_message.user_id,
            )
        except TelegramAPIError:
            logger.warning(
                "Could not edit public list view message for list_id=%s user_id=%s",
                list_id,
                view_message.user_id,
                exc_info=True,
            )


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    args = (command.args or "").strip()

    if args.startswith("list_"):
        token = args.removeprefix("list_")
        shopping_list = await shopping.join_public_list_by_token(session, user_id=user_id, token=token)
        if shopping_list is None:
            await message.answer("Ссылка недействительна или владелец закрыл публичный доступ.")
            return
        await _show_list(message, session, user_id, shopping_list.id)
        return

    await _show_home(message)


@router.message(Command("help"))
async def cmd_help(message: Message, session: AsyncSession) -> None:
    await _ensure_user(session, message.from_user)
    await message.answer(HELP_TEXT, reply_markup=home_keyboard())


@router.message(Command("lists"))
async def cmd_lists(message: Message, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    await _show_lists(message, session, user_id)


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, message.from_user)
    await state.set_state(ShoppingListStates.creating_title)
    await message.answer("Напиши название нового списка покупок.", reply_markup=cancel_keyboard())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, message.from_user)
    await state.clear()
    await message.answer("Ок, отменил ввод.", reply_markup=home_keyboard())


@router.callback_query(F.data == "cancel")
async def callback_cancel(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, query.from_user)
    await state.clear()
    await _send_or_edit(query, "Ок, отменил ввод.", reply_markup=home_keyboard())


@router.callback_query(F.data == "lists")
async def callback_lists(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await _show_lists(query, session, user_id)


@router.callback_query(F.data == "new")
async def callback_new(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await _clear_current_list_view(query, session, user_id)
    await state.set_state(ShoppingListStates.creating_title)
    await _send_or_edit(query, "Напиши название нового списка покупок.", reply_markup=cancel_keyboard())


@router.message(ShoppingListStates.creating_title)
async def state_create_list(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    try:
        shopping_list = await shopping.create_shopping_list(session, owner_id=user_id, title=message.text or "")
        await state.clear()
        await _show_list(message, session, user_id, shopping_list.id)
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("open:"))
async def callback_open_list(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "open:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_list(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("refresh:"))
async def callback_refresh_list(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "refresh:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_list(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("money:"))
async def callback_money(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await state.clear()
    list_id = _parse_id(query.data, "money:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_money(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("money_final:"))
async def callback_money_final(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await state.clear()
    list_id = _parse_id(query.data, "money_final:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_money_final(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("members:"))
async def callback_members(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "members:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_members(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("members_manage:"))
async def callback_members_manage(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "members_manage:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_manage_members(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("member_remove:"))
async def callback_member_remove(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    ids = _parse_two_ids(query.data, "member_remove:")
    if ids is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    list_id, member_user_id = ids
    try:
        await shopping.remove_list_member(
            session,
            owner_id=user_id,
            list_id=list_id,
            member_user_id=member_user_id,
        )
        await _answer_callback(query, "Участник удален.")
        await _show_manage_members(query, session, user_id, list_id, ack=False)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("member_ban:"))
async def callback_member_ban(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    ids = _parse_two_ids(query.data, "member_ban:")
    if ids is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    list_id, member_user_id = ids
    try:
        await shopping.ban_list_member(
            session,
            owner_id=user_id,
            list_id=list_id,
            member_user_id=member_user_id,
        )
        await _answer_callback(query, "Участник забанен.")
        await _show_manage_members(query, session, user_id, list_id, ack=False)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


async def _start_add_items(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    *,
    prefix: str,
    scope: str,
) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, prefix)
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.get_list_view(session, user_id=user_id, list_id=list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)
        return

    await shopping.clear_list_view_message(session, list_id=list_id, user_id=user_id)
    await session.commit()
    await state.set_state(ShoppingListStates.adding_items)
    await state.update_data(list_id=list_id, item_scope=scope)
    prompt = (
        "Напиши покупки для общего списка. Можно несколькими строками."
        if scope == shopping.ITEM_SCOPE_COMMON
        else "Напиши личные хотелки для своего списка. Можно несколькими строками."
    )
    await _send_or_edit(
        query,
        prompt,
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data.startswith("add:"))
async def callback_add_items(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _start_add_items(
        query,
        state,
        session,
        prefix="add:",
        scope=shopping.ITEM_SCOPE_COMMON,
    )


@router.callback_query(F.data.startswith("add_common:"))
async def callback_add_common_items(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _start_add_items(
        query,
        state,
        session,
        prefix="add_common:",
        scope=shopping.ITEM_SCOPE_COMMON,
    )


@router.callback_query(F.data.startswith("add_personal:"))
async def callback_add_personal_items(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _start_add_items(
        query,
        state,
        session,
        prefix="add_personal:",
        scope=shopping.ITEM_SCOPE_PERSONAL,
    )


@router.message(ShoppingListStates.adding_items)
async def state_add_items(message: Message, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    item_scope = str(data.get("item_scope", shopping.ITEM_SCOPE_COMMON))
    try:
        await shopping.add_items(
            session,
            user_id=user_id,
            list_id=list_id,
            text=message.text or "",
            scope=item_scope,
        )
        await session.commit()
        await state.clear()
        await _show_list(message, session, user_id, list_id)
        await _broadcast_public_list_update(bot, session, list_id, exclude_user_id=user_id)
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("toggle:"))
async def callback_toggle_item(
    query: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext | None = None,
) -> None:
    user_id = await _ensure_user(session, query.from_user)
    item_id = _parse_id(query.data, "toggle:")
    if item_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        _, item, _ = await shopping.get_item_view(session, user_id=user_id, item_id=item_id)
        if item.is_done:
            list_id = await shopping.unmark_item(session, user_id=user_id, item_id=item_id)
            await session.commit()
            await _show_list(query, session, user_id, list_id)
            await _broadcast_public_list_update(bot, session, list_id, exclude_user_id=user_id)
            return

        if state is None:
            await _answer_callback(query, "Не могу начать ввод цены.", show_alert=True)
            return
        await shopping.clear_list_view_message(session, list_id=item.list_id, user_id=user_id)
        await session.commit()
        await state.set_state(ShoppingListStates.buying_item_amount)
        await state.update_data(item_id=item.id, list_id=item.list_id)
        await _send_or_edit(
            query,
            f"Сколько вышло за «{item.text}»? Напиши сумму, например 12.50.",
            reply_markup=cancel_keyboard(),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.message(ShoppingListStates.buying_item_amount)
async def state_buying_item_amount(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, message.from_user)
    try:
        amount = shopping.parse_money_amount(message.text or "")
        await state.update_data(amount=amount)
        await state.set_state(ShoppingListStates.choosing_item_purchase_source)
        await message.answer("Откуда оплатили покупку?", reply_markup=item_purchase_source_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("buy_source:"))
async def callback_buy_source(query: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    source = (query.data or "").removeprefix("buy_source:")
    data = await state.get_data()
    item_id = int(data.get("item_id", 0))
    amount = int(data.get("amount", 0))
    try:
        list_id = await shopping.record_item_purchase(
            session,
            user_id=user_id,
            item_id=item_id,
            amount=amount,
            source=source,
        )
        await session.commit()
        await state.clear()
        await _show_list(query, session, user_id, list_id)
        await _broadcast_public_list_update(bot, session, list_id, exclude_user_id=user_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


async def _callback_set_all_items_done(
    query: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
    *,
    prefix: str,
    is_done: bool,
) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, prefix)
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        updated_list_id = await shopping.set_all_items_done(
            session,
            user_id=user_id,
            list_id=list_id,
            is_done=is_done,
        )
        await session.commit()
        await _show_list(query, session, user_id, updated_list_id)
        await _broadcast_public_list_update(bot, session, updated_list_id, exclude_user_id=user_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("checkall:"))
async def callback_check_all_items(query: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    await _callback_set_all_items_done(
        query,
        bot,
        session,
        prefix="checkall:",
        is_done=True,
    )


@router.callback_query(F.data.startswith("uncheckall:"))
async def callback_uncheck_all_items(query: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    await _callback_set_all_items_done(
        query,
        bot,
        session,
        prefix="uncheckall:",
        is_done=False,
    )


@router.callback_query(F.data.startswith("delitem:"))
async def callback_delete_item(query: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    item_id = _parse_id(query.data, "delitem:")
    if item_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        list_id = await shopping.delete_item(session, user_id=user_id, item_id=item_id)
        await session.commit()
        await _show_list(query, session, user_id, list_id)
        await _broadcast_public_list_update(bot, session, list_id, exclude_user_id=user_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("contribution:"))
async def callback_contribution(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "contribution:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.get_money_summary(session, user_id=user_id, list_id=list_id)
        await state.set_state(ShoppingListStates.adding_contribution_amount)
        await state.update_data(list_id=list_id)
        await _send_or_edit(
            query,
            "Сколько ты внёс в кассу тусовки? Напиши сумму, например 50.",
            reply_markup=cancel_keyboard(),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.message(ShoppingListStates.adding_contribution_amount)
async def state_contribution_amount(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    try:
        await shopping.create_contribution(
            session,
            user_id=user_id,
            list_id=list_id,
            amount=message.text or "",
        )
        await state.clear()
        await _show_money(message, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("expense:"))
async def callback_expense(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "expense:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.get_money_summary(session, user_id=user_id, list_id=list_id)
        await state.set_state(ShoppingListStates.adding_expense_title)
        await state.update_data(list_id=list_id)
        await _send_or_edit(query, "Как назвать трату?", reply_markup=cancel_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("taxi:"))
async def callback_taxi(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "taxi:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.get_money_summary(session, user_id=user_id, list_id=list_id)
        await state.set_state(ShoppingListStates.adding_expense_amount)
        await state.update_data(list_id=list_id, expense_title="Такси")
        await _send_or_edit(query, "Сколько стоило такси?", reply_markup=cancel_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.message(ShoppingListStates.adding_expense_title)
async def state_expense_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, message.from_user)
    try:
        await state.update_data(expense_title=message.text or "")
        await state.set_state(ShoppingListStates.adding_expense_amount)
        await message.answer("Какая сумма?", reply_markup=cancel_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.message(ShoppingListStates.adding_expense_amount)
async def state_expense_amount(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, message.from_user)
    try:
        amount = shopping.parse_money_amount(message.text or "")
        await state.update_data(amount=amount)
        await state.set_state(ShoppingListStates.choosing_expense_source)
        await message.answer("Откуда оплатили?", reply_markup=expense_source_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("expense_source:"))
async def callback_expense_source(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, query.from_user)
    source = (query.data or "").removeprefix("expense_source:")
    await state.update_data(source=source)
    await state.set_state(ShoppingListStates.choosing_expense_split)
    await _send_or_edit(query, "На кого распределить трату?", reply_markup=expense_split_keyboard())


async def _create_expense_from_state(
    target: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    *,
    user_id: int,
    share_user_ids: Sequence[int] | None,
) -> None:
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    title = str(data.get("expense_title", ""))
    amount = int(data.get("amount", 0))
    source = str(data.get("source", ""))
    await shopping.create_expense(
        session,
        user_id=user_id,
        list_id=list_id,
        title=title,
        amount=amount,
        source=source,
        share_user_ids=share_user_ids,
    )
    await state.clear()
    await _show_money(target, session, user_id, list_id)


@router.callback_query(F.data == "expense_split:all")
async def callback_expense_split_all(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    try:
        await _create_expense_from_state(query, state, session, user_id=user_id, share_user_ids=None)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data == "expense_split:me")
async def callback_expense_split_me(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    try:
        await _create_expense_from_state(query, state, session, user_id=user_id, share_user_ids=[user_id])
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data == "expense_split:selected")
async def callback_expense_split_selected(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    try:
        _, participants, _ = await shopping.get_list_participants(session, user_id=user_id, list_id=list_id)
        await state.update_data(selected_user_ids=[user_id])
        await _send_or_edit(
            query,
            "Выбери участников для этой траты.",
            reply_markup=expense_participants_keyboard(participants, [user_id]),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("expense_select:"))
async def callback_expense_select(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    selected_user_id = _parse_id(query.data, "expense_select:")
    if selected_user_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return

    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    selected_user_ids = set(int(value) for value in data.get("selected_user_ids", []))
    if selected_user_id in selected_user_ids:
        selected_user_ids.remove(selected_user_id)
    else:
        selected_user_ids.add(selected_user_id)

    try:
        _, participants, _ = await shopping.get_list_participants(session, user_id=user_id, list_id=list_id)
        selected = sorted(selected_user_ids)
        await state.update_data(selected_user_ids=selected)
        await _send_or_edit(
            query,
            "Выбери участников для этой траты.",
            reply_markup=expense_participants_keyboard(participants, selected),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data == "expense_selected_done")
async def callback_expense_selected_done(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    data = await state.get_data()
    selected_user_ids = [int(value) for value in data.get("selected_user_ids", [])]
    if not selected_user_ids:
        await _answer_callback(query, "Выбери хотя бы одного участника.", show_alert=True)
        return
    try:
        await _create_expense_from_state(
            query,
            state,
            session,
            user_id=user_id,
            share_user_ids=selected_user_ids,
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("settings:"))
async def callback_settings(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "settings:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_settings(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("share:"))
async def callback_share(query: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "share:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        token = await shopping.enable_public_access(session, owner_id=user_id, list_id=list_id)
        link = await create_start_link(bot, f"list_{token}")
        await _answer_callback(query)
        if query.message is not None:
            await query.message.answer(f"Публичная ссылка на список:\n{link}")
        await _show_settings(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("relink:"))
async def callback_relink(query: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "relink:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        token = await shopping.enable_public_access(session, owner_id=user_id, list_id=list_id, regenerate=True)
        link = await create_start_link(bot, f"list_{token}")
        await _answer_callback(query)
        if query.message is not None:
            await query.message.answer(f"Новая публичная ссылка:\n{link}\n\nСтарая ссылка больше не откроет список.")
        await _show_settings(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("private:"))
async def callback_private(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "private:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.disable_public_access(session, owner_id=user_id, list_id=list_id)
        await _show_settings(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("rename:"))
async def callback_rename(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "rename:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.assert_owner(session, owner_id=user_id, list_id=list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)
        return

    await state.set_state(ShoppingListStates.renaming_list)
    await state.update_data(list_id=list_id)
    await _send_or_edit(query, "Напиши новое название списка.", reply_markup=cancel_keyboard())


@router.message(ShoppingListStates.renaming_list)
async def state_rename_list(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    try:
        await shopping.rename_list(session, owner_id=user_id, list_id=list_id, title=message.text or "")
        await state.clear()
        await _show_settings(message, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("delete_list:"))
async def callback_delete_list(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "delete_list:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        shopping_list = await shopping.assert_owner(session, owner_id=user_id, list_id=list_id)
        await _send_or_edit(
            query,
            f"Удалить список «{shopping_list.title}»? Это действие нельзя отменить.",
            reply_markup=delete_confirm_keyboard(shopping_list),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("delete_confirm:"))
async def callback_delete_confirm(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "delete_confirm:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.delete_list(session, owner_id=user_id, list_id=list_id)
        await _send_or_edit(query, "Список удален.", reply_markup=home_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.message()
async def fallback_message(message: Message, session: AsyncSession) -> None:
    await _ensure_user(session, message.from_user)
    await message.answer("Я пока понимаю команды и кнопки. Открой меню списков.", reply_markup=home_keyboard())
