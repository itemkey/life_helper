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
    expense_categories_keyboard,
    expense_category_keyboard,
    expense_category_split_keyboard,
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
    receipt_cancel_keyboard,
    receipt_items_keyboard,
    settings_keyboard,
    shopping_categories_keyboard,
    shopping_category_keyboard,
    shopping_category_select_keyboard,
)
from app.tgbot.states import ShoppingListStates
from app.tgbot.texts import (
    HELP_TEXT,
    WELCOME_TEXT,
    format_categories_text,
    format_expense_category_split_text,
    format_expense_category_text,
    format_list_text,
    format_lists_text,
    format_money_final_text,
    format_money_text,
    format_members_management_text,
    format_members_text,
    format_receipt_items_text,
    format_settings_text,
    format_shopping_categories_text,
    format_shopping_category_text,
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
    _, categories, _ = await shopping.get_shopping_categories(session, user_id=user_id, list_id=list_id)
    sent_message = await _send_or_edit(
        target,
        format_list_text(shopping_list, items, level, categories),
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


async def _show_categories(target: Message | CallbackQuery, session: AsyncSession, user_id: int, list_id: int) -> None:
    shopping_list, categories, _ = await shopping.get_expense_categories(
        session,
        user_id=user_id,
        list_id=list_id,
    )
    await _send_or_edit(
        target,
        format_categories_text(shopping_list, categories),
        reply_markup=expense_categories_keyboard(shopping_list, categories),
    )


async def _show_expense_category(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user_id: int,
    category_id: int,
) -> None:
    shopping_list, category, _ = await shopping.get_expense_category(
        session,
        user_id=user_id,
        category_id=category_id,
    )
    await _send_or_edit(
        target,
        format_expense_category_text(shopping_list, category),
        reply_markup=expense_category_keyboard(category),
    )


async def _show_shopping_categories(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user_id: int,
    list_id: int,
) -> None:
    shopping_list, categories, _ = await shopping.get_shopping_categories(
        session,
        user_id=user_id,
        list_id=list_id,
    )
    await _send_or_edit(
        target,
        format_shopping_categories_text(shopping_list, categories),
        reply_markup=shopping_categories_keyboard(shopping_list, categories),
    )


async def _show_shopping_category(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user_id: int,
    category_id: int,
) -> None:
    _, category, items, level = await shopping.get_shopping_category_items(
        session,
        user_id=user_id,
        category_id=category_id,
    )
    await _send_or_edit(
        target,
        format_shopping_category_text(category, items),
        reply_markup=shopping_category_keyboard(category, level, user_id),
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


async def _show_cancel_return(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user_id: int,
    data: dict[str, Any],
) -> None:
    destination = str(data.get("cancel_return") or "")
    list_id = int(data.get("cancel_list_id") or data.get("list_id") or 0)
    category_id = int(data.get("cancel_category_id") or data.get("category_id") or 0)

    try:
        if destination == "list" and list_id:
            await _show_list(target, session, user_id, list_id)
            return
        if destination == "shopping_categories" and list_id:
            await _show_shopping_categories(target, session, user_id, list_id)
            return
        if destination == "shopping_category" and category_id:
            await _show_shopping_category(target, session, user_id, category_id)
            return
        if destination == "money" and list_id:
            await _show_money(target, session, user_id, list_id)
            return
        if destination == "categories" and list_id:
            await _show_categories(target, session, user_id, list_id)
            return
        if destination == "expense_category" and category_id:
            await _show_expense_category(target, session, user_id, category_id)
            return
        if destination == "settings" and list_id:
            await _show_settings(target, session, user_id, list_id)
            return
        if destination == "lists":
            await _show_lists(target, session, user_id)
            return
    except LifeHelperError as error:
        await _handle_service_error(target, error)
        return

    if _is_callback_target(target):
        await _send_or_edit(target, WELCOME_TEXT, reply_markup=home_keyboard())
    else:
        await target.answer(WELCOME_TEXT, reply_markup=home_keyboard())


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
    _, categories, _ = await shopping.get_shopping_categories(
        session,
        user_id=shopping_list.owner_id,
        list_id=shopping_list.id,
    )
    for view_message in view_messages:
        if view_message.user_id == exclude_user_id:
            continue

        level = AccessLevel.owner if view_message.user_id == shopping_list.owner_id else AccessLevel.member
        try:
            await bot.edit_message_text(
                text=format_list_text(shopping_list, items, level, categories),
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
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    await state.clear()
    await _show_cancel_return(message, session, user_id, data)


@router.callback_query(F.data == "cancel")
async def callback_cancel(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    data = await state.get_data()
    await state.clear()
    await _show_cancel_return(query, session, user_id, data)


@router.callback_query(F.data == "lists")
async def callback_lists(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await _show_lists(query, session, user_id)


@router.callback_query(F.data == "new")
async def callback_new(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await _clear_current_list_view(query, session, user_id)
    await state.set_state(ShoppingListStates.creating_title)
    await state.update_data(cancel_return="lists")
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


@router.callback_query(F.data.startswith("categories:"))
async def callback_categories(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await state.clear()
    list_id = _parse_id(query.data, "categories:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_categories(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("shopping_categories:"))
async def callback_shopping_categories(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await state.clear()
    list_id = _parse_id(query.data, "shopping_categories:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_shopping_categories(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("shopping_category:"))
async def callback_shopping_category(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    category_id = _parse_id(query.data, "shopping_category:")
    if category_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_shopping_category(query, session, user_id, category_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("shopping_category_mode:"))
async def callback_shopping_category_mode(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    parts = (query.data or "").removeprefix("shopping_category_mode:").split(":")
    if len(parts) != 2:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        category_id = int(parts[0])
    except ValueError:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        category = await shopping.set_shopping_category_accounting_mode(
            session,
            user_id=user_id,
            category_id=category_id,
            accounting_mode=parts[1],
        )
        await _show_shopping_category(query, session, user_id, category.id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


async def _start_shopping_category_title(
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
        await shopping.get_shopping_categories(session, user_id=user_id, list_id=list_id)
        await state.set_state(ShoppingListStates.adding_shopping_category_title)
        await state.update_data(
            list_id=list_id,
            shopping_category_scope=scope,
            cancel_return="shopping_categories",
            cancel_list_id=list_id,
        )
        label = "общей" if scope == shopping.ITEM_SCOPE_COMMON else "личной"
        await _send_or_edit(query, f"Напиши название {label} категории покупок.", reply_markup=cancel_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("shopping_category_add_common:"))
async def callback_shopping_category_add_common(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _start_shopping_category_title(
        query,
        state,
        session,
        prefix="shopping_category_add_common:",
        scope=shopping.ITEM_SCOPE_COMMON,
    )


@router.callback_query(F.data.startswith("shopping_category_add_personal:"))
async def callback_shopping_category_add_personal(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _start_shopping_category_title(
        query,
        state,
        session,
        prefix="shopping_category_add_personal:",
        scope=shopping.ITEM_SCOPE_PERSONAL,
    )


@router.message(ShoppingListStates.adding_shopping_category_title)
async def state_shopping_category_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    scope = str(data.get("shopping_category_scope", shopping.ITEM_SCOPE_COMMON))
    try:
        await shopping.create_shopping_category(
            session,
            user_id=user_id,
            list_id=list_id,
            title=message.text or "",
            scope=scope,
        )
        await state.clear()
        await _show_shopping_categories(message, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("shopping_category_rename:"))
async def callback_shopping_category_rename(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    category_id = _parse_id(query.data, "shopping_category_rename:")
    if category_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        shopping_list, category, _ = await shopping.get_shopping_category(
            session,
            user_id=user_id,
            category_id=category_id,
        )
        await state.set_state(ShoppingListStates.renaming_shopping_category)
        await state.update_data(
            category_id=category.id,
            cancel_return="shopping_category",
            cancel_list_id=shopping_list.id,
            cancel_category_id=category.id,
        )
        await _send_or_edit(query, "Напиши новое название категории покупок.", reply_markup=cancel_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.message(ShoppingListStates.renaming_shopping_category)
async def state_rename_shopping_category(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    category_id = int(data.get("category_id", 0))
    try:
        category = await shopping.rename_shopping_category(
            session,
            user_id=user_id,
            category_id=category_id,
            title=message.text or "",
        )
        await state.clear()
        await _show_shopping_category(message, session, user_id, category.id)
    except LifeHelperError as error:
        await _handle_service_error(message, error)


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
        shopping_list, categories, level = await shopping.get_shopping_categories(
            session,
            user_id=user_id,
            list_id=list_id,
        )
        category = next(
            (
                item
                for item in categories
                if item.scope == scope and (scope == shopping.ITEM_SCOPE_COMMON or item.owner_id == user_id)
            ),
            None,
        )
        if category is None:
            category = await shopping.create_shopping_category(
                session,
                user_id=user_id,
                list_id=shopping_list.id,
                title="Общее" if scope == shopping.ITEM_SCOPE_COMMON else "Личное",
                scope=scope,
            )
        if category.scope == shopping.ITEM_SCOPE_PERSONAL and category.owner_id != user_id and level != AccessLevel.owner:
            raise AccessDenied("В чужую личную категорию можно смотреть, но нельзя добавлять покупки.")
        await _start_add_items_for_category(
            query,
            state,
            session,
            user_id=user_id,
            category_id=category.id,
            cancel_return="list",
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)
    return


async def _start_add_items_for_category(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    cancel_return: str = "shopping_category",
) -> None:
    shopping_list, category, _ = await shopping.get_shopping_category(
        session,
        user_id=user_id,
        category_id=category_id,
    )

    await shopping.clear_list_view_message(session, list_id=shopping_list.id, user_id=user_id)
    await session.commit()
    await state.set_state(ShoppingListStates.adding_items)
    await state.update_data(
        list_id=shopping_list.id,
        item_scope=category.scope,
        category_id=category.id,
        cancel_return=cancel_return,
        cancel_list_id=shopping_list.id,
        cancel_category_id=category.id,
    )
    prompt = (
        f"Напиши покупки для категории «{category.title}». Можно несколькими строками."
        if category.scope == shopping.ITEM_SCOPE_COMMON
        else f"Напиши личные хотелки для категории «{category.title}». Можно несколькими строками."
    )
    await _send_or_edit(
        query,
        prompt,
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data.startswith("add:"))
async def callback_add_items(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "add:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        shopping_list, categories, level = await shopping.get_shopping_categories(
            session,
            user_id=user_id,
            list_id=list_id,
        )
        visible_categories = [
            category
            for category in categories
            if category.scope == shopping.ITEM_SCOPE_COMMON
            or level == AccessLevel.owner
            or category.owner_id == user_id
        ]
        if len(visible_categories) == 1:
            await _start_add_items_for_category(
                query,
                state,
                session,
                user_id=user_id,
                category_id=visible_categories[0].id,
            )
            return
        await _send_or_edit(
            query,
            "Выбери категорию покупок.",
            reply_markup=shopping_category_select_keyboard(shopping_list, visible_categories),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("add_category:"))
async def callback_add_category_items(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    category_id = _parse_id(query.data, "add_category:")
    if category_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _start_add_items_for_category(query, state, session, user_id=user_id, category_id=category_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


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
    raw_category_id = data.get("category_id")
    category_id = int(raw_category_id) if raw_category_id is not None else None
    try:
        await shopping.add_items(
            session,
            user_id=user_id,
            list_id=list_id,
            text=message.text or "",
            scope=item_scope,
            category_id=category_id,
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
            receipt_view = await shopping.get_receipt_expense_for_item(session, user_id=user_id, item_id=item_id)
            if receipt_view is not None:
                shopping_list, expense = receipt_view
                await _send_or_edit(
                    query,
                    f"«{item.text}» закрыт чеком «{expense.title}». Можно отменить только весь чек.",
                    reply_markup=receipt_cancel_keyboard(expense.id, shopping_list.id),
                )
                return
            list_id = await shopping.unmark_item(session, user_id=user_id, item_id=item_id)
            await session.commit()
            await _show_list(query, session, user_id, list_id)
            await _broadcast_public_list_update(bot, session, list_id, exclude_user_id=user_id)
            return

        if state is None:
            await _answer_callback(query, "Не могу начать ввод цены.", show_alert=True)
            return
        if item.category is not None and item.category.accounting_mode == shopping.SHOPPING_CATEGORY_MODE_RECEIPT:
            await _answer_callback(query, "Эта категория считается по чеку.")
            await _show_shopping_category(query, session, user_id, item.category.id)
            return
        await shopping.clear_list_view_message(session, list_id=item.list_id, user_id=user_id)
        await session.commit()
        await state.set_state(ShoppingListStates.buying_item_amount)
        await state.update_data(
            item_id=item.id,
            list_id=item.list_id,
            cancel_return="list",
            cancel_list_id=item.list_id,
        )
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


async def _show_receipt_item_selection(
    target: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
) -> None:
    shopping_list, category, items, _ = await shopping.get_shopping_category_items(
        session,
        user_id=user_id,
        category_id=category_id,
    )
    if category.accounting_mode != shopping.SHOPPING_CATEGORY_MODE_RECEIPT:
        raise ValidationError("Эта категория считается по товарам. Сначала включи режим по чеку.")
    available_items = [item for item in items if not item.is_done]
    data = await state.get_data()
    selected_item_ids = [int(item_id) for item_id in data.get("receipt_item_ids", [])]
    selection_initialized = bool(data.get("receipt_selection_initialized"))
    available_ids = {item.id for item in available_items}
    selected_item_ids = [item_id for item_id in selected_item_ids if item_id in available_ids]
    if not selection_initialized:
        selected_item_ids = [item.id for item in available_items]
    await state.set_state(ShoppingListStates.choosing_receipt_items)
    await state.update_data(
        list_id=shopping_list.id,
        receipt_category_id=category.id,
        receipt_item_ids=selected_item_ids,
        receipt_selection_initialized=True,
        cancel_return="shopping_category",
        cancel_list_id=shopping_list.id,
        cancel_category_id=category.id,
    )
    await _send_or_edit(
        target,
        format_receipt_items_text(category, available_items, selected_item_ids),
        reply_markup=receipt_items_keyboard(category, available_items, selected_item_ids),
    )


@router.callback_query(F.data.startswith("receipt:"))
async def callback_receipt(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    category_id = _parse_id(query.data, "receipt:")
    if category_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_receipt_item_selection(query, state, session, user_id=user_id, category_id=category_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("receipt_select:"))
async def callback_receipt_select(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    item_id = _parse_id(query.data, "receipt_select:")
    if item_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    data = await state.get_data()
    category_id = int(data.get("receipt_category_id", 0))
    selected = set(int(value) for value in data.get("receipt_item_ids", []))
    if item_id in selected:
        selected.remove(item_id)
    else:
        selected.add(item_id)
    await state.update_data(receipt_item_ids=sorted(selected))
    try:
        await _show_receipt_item_selection(query, state, session, user_id=user_id, category_id=category_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data == "receipt_items_done")
async def callback_receipt_items_done(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, query.from_user)
    data = await state.get_data()
    selected_item_ids = [int(value) for value in data.get("receipt_item_ids", [])]
    if not selected_item_ids:
        await _answer_callback(query, "Выбери хотя бы один товар.", show_alert=True)
        return
    await state.set_state(ShoppingListStates.adding_receipt_amount)
    await _send_or_edit(query, "Какая сумма по чеку?", reply_markup=cancel_keyboard())


@router.message(ShoppingListStates.adding_receipt_amount)
async def state_receipt_amount(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _ensure_user(session, message.from_user)
    try:
        amount = shopping.parse_money_amount(message.text or "")
        await state.update_data(amount=amount)
        await state.set_state(ShoppingListStates.choosing_expense_source)
        await message.answer("Откуда оплатили чек?", reply_markup=expense_source_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(message, error)


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


@router.callback_query(F.data.startswith("receipt_cancel:"))
async def callback_receipt_cancel(query: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    expense_id = _parse_id(query.data, "receipt_cancel:")
    if expense_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        list_id = await shopping.cancel_receipt_expense(session, user_id=user_id, expense_id=expense_id)
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
        await state.update_data(
            list_id=list_id,
            cancel_return="money",
            cancel_list_id=list_id,
        )
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
    await state.clear()
    list_id = _parse_id(query.data, "expense:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_categories(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("expense_custom:"))
async def callback_expense_custom(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "expense_custom:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.get_money_summary(session, user_id=user_id, list_id=list_id)
        await state.set_state(ShoppingListStates.adding_expense_title)
        await state.update_data(
            list_id=list_id,
            category_id=None,
            cancel_return="categories",
            cancel_list_id=list_id,
        )
        await _send_or_edit(query, "Как назвать разовую трату?", reply_markup=cancel_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("expense_category:"))
async def callback_expense_category(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    await state.clear()
    category_id = _parse_id(query.data, "expense_category:")
    if category_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await _show_expense_category(query, session, user_id, category_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("expense_category_add:"))
async def callback_expense_category_add(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    category_id = _parse_id(query.data, "expense_category_add:")
    if category_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        shopping_list, category, _ = await shopping.get_expense_category(
            session,
            user_id=user_id,
            category_id=category_id,
        )
        await state.set_state(ShoppingListStates.adding_expense_amount)
        await state.update_data(
            list_id=shopping_list.id,
            category_id=category.id,
            expense_title=category.title,
            expense_category_default_split=category.default_split,
            cancel_return="expense_category",
            cancel_list_id=shopping_list.id,
            cancel_category_id=category.id,
        )
        await _send_or_edit(
            query,
            f"Сколько вышло за «{category.title}»?",
            reply_markup=cancel_keyboard(),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("expense_category_split:"))
async def callback_expense_category_split(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    category_id = _parse_id(query.data, "expense_category_split:")
    if category_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        _, category, _ = await shopping.get_expense_category(session, user_id=user_id, category_id=category_id)
        await _send_or_edit(
            query,
            format_expense_category_split_text(category),
            reply_markup=expense_category_split_keyboard(category),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("expense_category_set_split:"))
async def callback_expense_category_set_split(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    parts = (query.data or "").removeprefix("expense_category_set_split:").split(":")
    if len(parts) != 2:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        category_id = int(parts[0])
    except ValueError:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        category = await shopping.set_expense_category_default_split(
            session,
            user_id=user_id,
            category_id=category_id,
            default_split=parts[1],
        )
        await _show_expense_category(query, session, user_id, category.id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("expense_category_rename:"))
async def callback_expense_category_rename(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    category_id = _parse_id(query.data, "expense_category_rename:")
    if category_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        shopping_list, category, _ = await shopping.get_expense_category(
            session,
            user_id=user_id,
            category_id=category_id,
        )
        await state.set_state(ShoppingListStates.renaming_expense_category)
        await state.update_data(
            category_id=category.id,
            cancel_return="expense_category",
            cancel_list_id=shopping_list.id,
            cancel_category_id=category.id,
        )
        await _send_or_edit(query, "Напиши новое название категории трат.", reply_markup=cancel_keyboard())
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.message(ShoppingListStates.renaming_expense_category)
async def state_rename_expense_category(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    category_id = int(data.get("category_id", 0))
    try:
        category = await shopping.rename_expense_category(
            session,
            user_id=user_id,
            category_id=category_id,
            title=message.text or "",
        )
        await state.clear()
        await _show_expense_category(message, session, user_id, category.id)
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("category_add:"))
async def callback_category_add(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "category_add:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.get_money_summary(session, user_id=user_id, list_id=list_id)
        await state.set_state(ShoppingListStates.adding_category_title)
        await state.update_data(
            list_id=list_id,
            cancel_return="categories",
            cancel_list_id=list_id,
        )
        await _send_or_edit(
            query,
            "Напиши название категории: например Маршрутка, Автобус, Такси, Доставка.",
            reply_markup=cancel_keyboard(),
        )
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.message(ShoppingListStates.adding_category_title)
async def state_category_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    try:
        category = await shopping.create_expense_category(
            session,
            user_id=user_id,
            list_id=list_id,
            title=message.text or "",
        )
        await state.clear()
        await message.answer(
            format_expense_category_split_text(category),
            reply_markup=expense_category_split_keyboard(category),
        )
    except LifeHelperError as error:
        await _handle_service_error(message, error)


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
    user_id = await _ensure_user(session, query.from_user)
    source = (query.data or "").removeprefix("expense_source:")
    data = await state.get_data()
    await state.update_data(source=source)
    list_id = int(data.get("list_id", 0))
    default_split = str(data.get("expense_category_default_split") or "")

    if default_split == shopping.EXPENSE_SPLIT_SELECTED:
        try:
            _, participants, _ = await shopping.get_list_participants(session, user_id=user_id, list_id=list_id)
            await state.set_state(ShoppingListStates.choosing_expense_split)
            await state.update_data(selected_user_ids=[user_id])
            await _send_or_edit(
                query,
                "Кто участвует?",
                reply_markup=expense_participants_keyboard(participants, [user_id]),
            )
        except LifeHelperError as error:
            await _handle_service_error(query, error)
        return

    await state.set_state(ShoppingListStates.choosing_expense_split)
    default_label = None
    if data.get("receipt_category_id"):
        default_label = "По умолчанию категории"
    elif default_split == shopping.EXPENSE_SPLIT_ALL:
        default_label = "По умолчанию: на всех"
    elif default_split == shopping.EXPENSE_SPLIT_ME:
        default_label = "По умолчанию: только на меня"
    await _send_or_edit(
        query,
        "Кто участвует?",
        reply_markup=expense_split_keyboard(default_label),
    )


async def _create_expense_from_state(
    target: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    *,
    user_id: int,
    share_user_ids: Sequence[int] | None,
    use_default_split: bool = False,
) -> None:
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    raw_receipt_category_id = data.get("receipt_category_id")
    if raw_receipt_category_id is not None:
        receipt_share_user_ids = share_user_ids
        if share_user_ids is None and not use_default_split:
            _, participants, _ = await shopping.get_list_participants(session, user_id=user_id, list_id=list_id)
            receipt_share_user_ids = [participant.id for participant in participants]
        list_id = await shopping.record_receipt_purchase(
            session,
            user_id=user_id,
            category_id=int(raw_receipt_category_id),
            item_ids=[int(value) for value in data.get("receipt_item_ids", [])],
            amount=int(data.get("amount", 0)),
            source=str(data.get("source", "")),
            share_user_ids=receipt_share_user_ids,
        )
        await state.clear()
        await _show_list(target, session, user_id, list_id)
        return

    raw_category_id = data.get("category_id")
    default_split = str(data.get("expense_category_default_split") or "")
    if use_default_split:
        if default_split == shopping.EXPENSE_SPLIT_ME:
            share_user_ids = [user_id]
        elif default_split == shopping.EXPENSE_SPLIT_ALL:
            share_user_ids = None

    title = str(data.get("expense_title", ""))
    amount = int(data.get("amount", 0))
    source = str(data.get("source", ""))
    category_id = int(raw_category_id) if raw_category_id is not None else None
    await shopping.create_expense(
        session,
        user_id=user_id,
        list_id=list_id,
        title=title,
        amount=amount,
        source=source,
        share_user_ids=share_user_ids,
        category_id=category_id,
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


@router.callback_query(F.data == "expense_split:default")
async def callback_expense_split_default(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    try:
        await _create_expense_from_state(
            query,
            state,
            session,
            user_id=user_id,
            share_user_ids=None,
            use_default_split=True,
        )
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
        await state.set_state(ShoppingListStates.choosing_expense_split)
        await state.update_data(selected_user_ids=[user_id])
        await _send_or_edit(
            query,
            "Кто участвует?",
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
            "Кто участвует?",
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
    await state.update_data(
        list_id=list_id,
        cancel_return="settings",
        cancel_list_id=list_id,
    )
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
