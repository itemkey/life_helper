from __future__ import annotations

from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
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
    home_keyboard,
    list_keyboard,
    lists_keyboard,
    settings_keyboard,
)
from app.tgbot.states import ShoppingListStates
from app.tgbot.texts import HELP_TEXT, WELCOME_TEXT, format_list_text, format_lists_text, format_settings_text

router = Router(name="shopping")


async def _ensure_user(session: AsyncSession, event_user: Any) -> int:
    user = await shopping.upsert_user(session, event_user)
    return user.id


async def _answer_callback(query: CallbackQuery, text: str | None = None, *, show_alert: bool = False) -> None:
    try:
        await query.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest:
        pass


async def _send_or_edit(
    target: Message | CallbackQuery,
    text: str,
    *,
    reply_markup: Any = None,
    ack: bool = True,
) -> None:
    if isinstance(target, CallbackQuery):
        if ack:
            await _answer_callback(target)
        if target.message is None:
            return
        try:
            await target.message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).lower():
                await target.message.answer(text, reply_markup=reply_markup)
        return

    await target.answer(text, reply_markup=reply_markup)


def _parse_id(value: str | None, prefix: str) -> int | None:
    if not value or not value.startswith(prefix):
        return None
    try:
        return int(value.removeprefix(prefix))
    except ValueError:
        return None


async def _show_home(message: Message) -> None:
    await message.answer(WELCOME_TEXT, reply_markup=home_keyboard())


async def _show_lists(target: Message | CallbackQuery, session: AsyncSession, user_id: int) -> None:
    owned, shared = await shopping.list_owned_and_shared(session, user_id=user_id)
    await _send_or_edit(target, format_lists_text(owned, shared), reply_markup=lists_keyboard(owned, shared))


async def _show_list(target: Message | CallbackQuery, session: AsyncSession, user_id: int, list_id: int) -> None:
    shopping_list, items, level = await shopping.get_list_view(session, user_id=user_id, list_id=list_id)
    await _send_or_edit(
        target,
        format_list_text(shopping_list, items, level),
        reply_markup=list_keyboard(shopping_list, items, level),
    )


async def _show_settings(target: Message | CallbackQuery, session: AsyncSession, user_id: int, list_id: int) -> None:
    shopping_list = await shopping.assert_owner(session, owner_id=user_id, list_id=list_id)
    await _send_or_edit(target, format_settings_text(shopping_list), reply_markup=settings_keyboard(shopping_list))


async def _handle_service_error(target: Message | CallbackQuery, error: Exception) -> None:
    if isinstance(error, (AccessDenied, ListNotFound, ValidationError)):
        text = str(error)
    else:
        text = "Что-то пошло не так. Попробуй еще раз."

    if isinstance(target, CallbackQuery):
        await _answer_callback(target, text, show_alert=True)
    else:
        await target.answer(text)


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
    await _ensure_user(session, query.from_user)
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


@router.callback_query(F.data.startswith("add:"))
async def callback_add_items(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    list_id = _parse_id(query.data, "add:")
    if list_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        await shopping.get_list_view(session, user_id=user_id, list_id=list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)
        return

    await state.set_state(ShoppingListStates.adding_items)
    await state.update_data(list_id=list_id)
    await _send_or_edit(
        query,
        "Напиши покупку. Можно отправить несколько строк, каждая строка станет отдельной покупкой.",
        reply_markup=cancel_keyboard(),
    )


@router.message(ShoppingListStates.adding_items)
async def state_add_items(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, message.from_user)
    data = await state.get_data()
    list_id = int(data.get("list_id", 0))
    try:
        await shopping.add_items(session, user_id=user_id, list_id=list_id, text=message.text or "")
        await state.clear()
        await _show_list(message, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(message, error)


@router.callback_query(F.data.startswith("toggle:"))
async def callback_toggle_item(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    item_id = _parse_id(query.data, "toggle:")
    if item_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        list_id = await shopping.toggle_item(session, user_id=user_id, item_id=item_id)
        await _show_list(query, session, user_id, list_id)
    except LifeHelperError as error:
        await _handle_service_error(query, error)


@router.callback_query(F.data.startswith("delitem:"))
async def callback_delete_item(query: CallbackQuery, session: AsyncSession) -> None:
    user_id = await _ensure_user(session, query.from_user)
    item_id = _parse_id(query.data, "delitem:")
    if item_id is None:
        await _answer_callback(query, "Не понял кнопку.", show_alert=True)
        return
    try:
        list_id = await shopping.delete_item(session, user_id=user_id, item_id=item_id)
        await _show_list(query, session, user_id, list_id)
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
