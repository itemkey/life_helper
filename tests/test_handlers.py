from __future__ import annotations

from dataclasses import dataclass, field

from aiogram.filters import CommandObject

from app.db.models import ListViewMessage
from app.services import shopping
from app.tgbot.states import ShoppingListStates
from app.tgbot.handlers import (
    callback_add_items,
    callback_add_common_items,
    callback_buy_source,
    callback_cancel,
    callback_category_add,
    callback_contribution,
    callback_delete_item,
    callback_check_all_items,
    callback_expense_category,
    callback_expense_category_add,
    callback_expense_category_set_split,
    callback_expense_source,
    callback_expense_selected_done,
    callback_expense_select,
    callback_expense_split_default,
    callback_expense_split_all,
    callback_members,
    callback_members_manage,
    callback_member_ban,
    callback_member_remove,
    callback_receipt,
    callback_receipt_items_done,
    callback_receipt_select,
    callback_refresh_list,
    callback_shopping_category_add_common,
    callback_shopping_category_delete,
    callback_shopping_category_mode,
    callback_toggle_item,
    callback_uncheck_all_items,
    cmd_start,
    state_add_items,
    state_buying_item_amount,
    state_category_title,
    state_contribution_amount,
    state_expense_amount,
    state_receipt_amount,
    state_shopping_category_title,
)
from tests.conftest import FakeTelegramUser


@dataclass(slots=True)
class FakeChat:
    id: int


@dataclass(slots=True)
class FakeEditableMessage:
    chat: FakeChat
    message_id: int
    text: str = ""
    reply_markup: object | None = None
    edits: list[tuple[str, object | None]] = field(default_factory=list)
    answers: list[tuple[str, object | None]] = field(default_factory=list)

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))
        return FakeEditableMessage(
            chat=self.chat,
            message_id=self.message_id + len(self.answers) + 1000,
            text=text,
            reply_markup=reply_markup,
        )

    async def edit_text(self, text: str, reply_markup=None):
        self.text = text
        self.reply_markup = reply_markup
        self.edits.append((text, reply_markup))
        return self


@dataclass(slots=True)
class FakeMessage:
    from_user: FakeTelegramUser
    text: str | None = None
    chat: FakeChat | None = None
    message_id: int = 1
    answers: list[tuple[str, object | None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.chat is None:
            self.chat = FakeChat(self.from_user.id)

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))
        return FakeEditableMessage(
            chat=self.chat or FakeChat(self.from_user.id),
            message_id=self.message_id + len(self.answers) + 1000,
            text=text,
            reply_markup=reply_markup,
        )


@dataclass(slots=True)
class FakeCallback:
    from_user: FakeTelegramUser
    data: str
    message: FakeEditableMessage | None
    answers: list[tuple[str | None, bool]] = field(default_factory=list)

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self.answers.append((text, show_alert))


@dataclass(slots=True)
class FakeState:
    data: dict[str, object] = field(default_factory=dict)
    cleared: bool = False

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.cleared = True
        self.data.clear()

    async def set_state(self, state):
        self.data["state"] = state

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


@dataclass(slots=True)
class FakeBot:
    edits: list[dict[str, object]] = field(default_factory=list)

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


async def test_start_without_deep_link_shows_home(session):
    message = FakeMessage(from_user=FakeTelegramUser(id=100))
    command = CommandObject(prefix="/", command="start", mention=None, args=None)

    await cmd_start(message, command, session)

    assert message.answers
    assert "Life Helper" in message.answers[0][0]


async def test_start_with_invalid_deep_link_shows_error(session):
    message = FakeMessage(from_user=FakeTelegramUser(id=100))
    command = CommandObject(prefix="/", command="start", mention=None, args="list_missing")

    await cmd_start(message, command, session)

    assert message.answers
    assert "Ссылка недействительна" in message.answers[0][0]


async def test_refresh_list_edits_message_and_saves_view(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Молоко")
    query = FakeCallback(
        from_user=FakeTelegramUser(id=100),
        data=f"refresh:{shopping_list.id}",
        message=FakeEditableMessage(chat=FakeChat(1000), message_id=10),
    )

    await callback_refresh_list(query, session)

    assert query.message is not None
    assert query.message.edits
    assert "Молоко" in query.message.edits[0][0]
    view_message = await session.get(ListViewMessage, (shopping_list.id, 100))
    assert view_message is not None
    assert view_message.chat_id == 1000
    assert view_message.message_id == 10


async def test_members_button_edits_message_with_list_members(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner", first_name="Owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member", first_name="Member"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=200, chat_id=2000, message_id=20)
    query = FakeCallback(
        from_user=FakeTelegramUser(id=200, username="member", first_name="Member"),
        data=f"members:{shopping_list.id}",
        message=FakeEditableMessage(chat=FakeChat(2000), message_id=20),
    )

    await callback_members(query, session)

    assert query.message is not None
    assert query.message.edits
    text = query.message.edits[0][0]
    assert "Участники списка" in text
    assert "Owner (@owner)" in text
    assert "Member (@member)" in text
    assert await session.get(ListViewMessage, (shopping_list.id, 200)) is None


async def test_owner_can_open_members_management(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner", first_name="Owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member", first_name="Member"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    query = FakeCallback(
        from_user=FakeTelegramUser(id=100, username="owner", first_name="Owner"),
        data=f"members_manage:{shopping_list.id}",
        message=FakeEditableMessage(chat=FakeChat(1000), message_id=10),
    )

    await callback_members_manage(query, session)

    assert query.message is not None
    assert query.message.edits
    text, keyboard = query.message.edits[0]
    assert "Управление участниками" in text
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert any(button.callback_data == f"member_remove:{shopping_list.id}:200" for button in buttons)
    assert any(button.callback_data == f"member_ban:{shopping_list.id}:200" for button in buttons)


async def test_owner_can_remove_member_from_members_management(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner", first_name="Owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member", first_name="Member"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    query = FakeCallback(
        from_user=FakeTelegramUser(id=100, username="owner", first_name="Owner"),
        data=f"member_remove:{shopping_list.id}:200",
        message=FakeEditableMessage(chat=FakeChat(1000), message_id=10),
    )

    await callback_member_remove(query, session)

    assert ("Участник удален.", False) in query.answers
    assert query.message is not None
    assert "Участников по ссылке пока нет." in query.message.edits[-1][0]
    _, _, members, _ = await shopping.get_list_members_view(session, user_id=100, list_id=shopping_list.id)
    assert members == []
    assert await shopping.join_public_list_by_token(session, user_id=200, token=token) is not None


async def test_owner_can_ban_member_from_members_management(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner", first_name="Owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member", first_name="Member"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    query = FakeCallback(
        from_user=FakeTelegramUser(id=100, username="owner", first_name="Owner"),
        data=f"member_ban:{shopping_list.id}:200",
        message=FakeEditableMessage(chat=FakeChat(1000), message_id=10),
    )

    await callback_member_ban(query, session)

    assert ("Участник забанен.", False) in query.answers
    assert query.message is not None
    assert "Участников по ссылке пока нет." in query.message.edits[-1][0]
    assert await shopping.join_public_list_by_token(session, user_id=200, token=token) is None


async def test_add_items_broadcasts_public_list_update_to_other_viewers(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=100, chat_id=1000, message_id=10)
    state = FakeState(data={"list_id": shopping_list.id})
    message = FakeMessage(
        from_user=FakeTelegramUser(id=200),
        text="Сок",
        chat=FakeChat(2000),
        message_id=20,
    )
    bot = FakeBot()

    await state_add_items(message, state, bot, session)

    assert state.cleared is True
    assert message.answers
    assert "Сок" in message.answers[0][0]
    assert len(bot.edits) == 1
    assert bot.edits[0]["chat_id"] == 1000
    assert bot.edits[0]["message_id"] == 10
    assert "Сок" in str(bot.edits[0]["text"])


async def test_toggle_and_delete_broadcast_public_list_updates_to_other_viewers(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    items = await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Молоко")
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=100, chat_id=1000, message_id=10)
    bot = FakeBot()
    state = FakeState()

    await callback_toggle_item(
        FakeCallback(
            from_user=FakeTelegramUser(id=200),
            data=f"toggle:{items[0].id}",
            message=FakeEditableMessage(chat=FakeChat(2000), message_id=20),
        ),
        bot,
        session,
        state=state,
    )
    assert state.data["state"] == ShoppingListStates.buying_item_amount

    await state_buying_item_amount(
        FakeMessage(from_user=FakeTelegramUser(id=200), text="12.50"),
        state,
        session,
    )
    assert state.data["state"] == ShoppingListStates.choosing_item_purchase_source

    await callback_buy_source(
        FakeCallback(
            from_user=FakeTelegramUser(id=200),
            data="buy_source:personal",
            message=FakeEditableMessage(chat=FakeChat(2000), message_id=21),
        ),
        state,
        bot,
        session,
    )

    assert len(bot.edits) == 1
    assert "Молоко" in str(bot.edits[0]["text"])
    summary = await shopping.get_money_summary(session, user_id=100, list_id=shopping_list.id)
    assert len(summary.expenses) == 1
    assert summary.expenses[0].amount == 1250

    bot.edits.clear()
    await callback_delete_item(
        FakeCallback(
            from_user=FakeTelegramUser(id=200),
            data=f"delitem:{items[0].id}",
            message=FakeEditableMessage(chat=FakeChat(2000), message_id=20),
        ),
        bot,
        session,
    )

    assert len(bot.edits) == 1
    assert "Тусовка пока пустая" in str(bot.edits[0]["text"])


async def test_bulk_check_buttons_update_items_and_broadcast(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    await shopping.add_items(session, user_id=100, list_id=shopping_list.id, text="Молоко\nХлеб")
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=100, chat_id=1000, message_id=10)
    bot = FakeBot()
    query = FakeCallback(
        from_user=FakeTelegramUser(id=200),
        data=f"checkall:{shopping_list.id}",
        message=FakeEditableMessage(chat=FakeChat(2000), message_id=20),
    )

    await callback_check_all_items(query, bot, session)

    assert query.message is not None
    assert "✓ Молоко" in query.message.edits[-1][0]
    assert "✓ Хлеб" in query.message.edits[-1][0]
    assert len(bot.edits) == 1
    assert "✓ Молоко" in str(bot.edits[0]["text"])
    assert "✓ Хлеб" in str(bot.edits[0]["text"])

    bot.edits.clear()
    query.data = f"uncheckall:{shopping_list.id}"
    await callback_uncheck_all_items(query, bot, session)

    assert "□ Молоко" in query.message.edits[-1][0]
    assert "□ Хлеб" in query.message.edits[-1][0]
    assert len(bot.edits) == 1
    assert "□ Молоко" in str(bot.edits[0]["text"])
    assert "□ Хлеб" in str(bot.edits[0]["text"])


async def test_private_list_add_does_not_broadcast(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Дом")
    await shopping.save_list_view_message(session, list_id=shopping_list.id, user_id=100, chat_id=1000, message_id=10)
    state = FakeState(data={"list_id": shopping_list.id})
    message = FakeMessage(
        from_user=FakeTelegramUser(id=100),
        text="Молоко",
        chat=FakeChat(1000),
        message_id=20,
    )
    bot = FakeBot()

    await state_add_items(message, state, bot, session)

    assert bot.edits == []


async def test_cancel_from_add_items_returns_to_list(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    query_message = FakeEditableMessage(chat=FakeChat(1000), message_id=10)
    state = FakeState()

    await callback_add_common_items(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"add_common:{shopping_list.id}",
            message=query_message,
        ),
        state,
        session,
    )
    await callback_cancel(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data="cancel",
            message=query_message,
        ),
        state,
        session,
    )

    assert state.cleared is True
    assert query_message.edits
    assert "Пикник" in query_message.edits[-1][0]
    assert "Тусовка пока пустая" in query_message.edits[-1][0]


async def test_cancel_from_contribution_returns_to_money(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    query_message = FakeEditableMessage(chat=FakeChat(1000), message_id=10)
    state = FakeState()

    await callback_contribution(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"contribution:{shopping_list.id}",
            message=query_message,
        ),
        state,
        session,
    )
    await callback_cancel(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data="cancel",
            message=query_message,
        ),
        state,
        session,
    )

    assert state.cleared is True
    assert query_message.edits
    assert "Деньги: Пикник" in query_message.edits[-1][0]
    assert "Остаток кассы" in query_message.edits[-1][0]


async def test_add_button_shows_shopping_categories(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    query_message = FakeEditableMessage(chat=FakeChat(1000), message_id=10)
    state = FakeState()

    await callback_add_items(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"add:{shopping_list.id}",
            message=query_message,
        ),
        state,
        session,
    )

    assert query_message.edits
    assert "Выбери категорию покупок" in query_message.edits[-1][0]
    buttons = [button for row in query_message.reply_markup.inline_keyboard for button in row]
    assert any(button.callback_data.startswith("add_category:") for button in buttons)


async def test_shopping_category_add_and_receipt_mode_flow(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    query_message = FakeEditableMessage(chat=FakeChat(1000), message_id=10)
    state = FakeState()

    await callback_shopping_category_add_common(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"shopping_category_add_common:{shopping_list.id}",
            message=query_message,
        ),
        state,
        session,
    )
    assert state.data["state"] == ShoppingListStates.adding_shopping_category_title

    message = FakeMessage(from_user=FakeTelegramUser(id=100), text="Магазин продуктов")
    await state_shopping_category_title(message, state, session)
    assert message.answers
    assert "Магазин продуктов" in message.answers[0][0]

    _, categories, _ = await shopping.get_shopping_categories(session, user_id=100, list_id=shopping_list.id)
    category = next(item for item in categories if item.title == "Магазин продуктов")
    await callback_shopping_category_mode(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"shopping_category_mode:{category.id}:receipt",
            message=query_message,
        ),
        session,
    )
    await session.refresh(category)
    assert category.accounting_mode == shopping.SHOPPING_CATEGORY_MODE_RECEIPT


async def test_shopping_category_delete_handler_removes_empty_category(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    category = await shopping.create_shopping_category(
        session,
        user_id=100,
        list_id=shopping_list.id,
        title="Напитки",
        scope=shopping.ITEM_SCOPE_COMMON,
    )
    query_message = FakeEditableMessage(chat=FakeChat(1000), message_id=10)

    await callback_shopping_category_delete(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"shopping_category_delete:{category.id}",
            message=query_message,
        ),
        session,
    )

    assert query_message.edits
    assert "Напитки" not in query_message.edits[-1][0]
    assert await session.get(type(category), category.id) is None


async def test_receipt_handler_flow_records_one_expense_for_selected_items(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100))
    await shopping.upsert_user(session, FakeTelegramUser(id=200))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    _, categories, _ = await shopping.get_shopping_categories(session, user_id=100, list_id=shopping_list.id)
    category = next(item for item in categories if item.scope == shopping.ITEM_SCOPE_COMMON)
    await shopping.set_shopping_category_accounting_mode(
        session,
        user_id=100,
        category_id=category.id,
        accounting_mode=shopping.SHOPPING_CATEGORY_MODE_RECEIPT,
    )
    items = await shopping.add_items(
        session,
        user_id=100,
        list_id=shopping_list.id,
        text="Сок\nЧипсы",
        category_id=category.id,
    )
    query_message = FakeEditableMessage(chat=FakeChat(1000), message_id=10)
    state = FakeState()

    await callback_receipt(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"receipt:{category.id}",
            message=query_message,
        ),
        state,
        session,
    )
    assert state.data["state"] == ShoppingListStates.choosing_receipt_items
    assert state.data["receipt_item_ids"] == [item.id for item in items]

    await callback_receipt_select(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"receipt_select:{items[1].id}",
            message=query_message,
        ),
        state,
        session,
    )
    assert state.data["receipt_item_ids"] == [items[0].id]

    await callback_receipt_items_done(
        FakeCallback(from_user=FakeTelegramUser(id=100), data="receipt_items_done", message=query_message),
        state,
        session,
    )
    assert state.data["state"] == ShoppingListStates.adding_receipt_amount

    await state_receipt_amount(FakeMessage(from_user=FakeTelegramUser(id=100), text="10"), state, session)
    assert state.data["state"] == ShoppingListStates.choosing_expense_source

    await callback_expense_source(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data="expense_source:personal",
            message=query_message,
        ),
        state,
        session,
    )
    buttons = [button for row in query_message.reply_markup.inline_keyboard for button in row]
    assert any(button.callback_data == "expense_split:default" for button in buttons)

    await callback_expense_split_default(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data="expense_split:default",
            message=query_message,
        ),
        state,
        session,
    )

    summary = await shopping.get_money_summary(session, user_id=100, list_id=shopping_list.id)
    assert [(expense.title, expense.amount) for expense in summary.expenses] == [("Чек: Общее", 1000)]
    assert [item.is_done for item in items] == [True, False]


async def test_contribution_and_category_expense_flow_updates_money_summary(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner", first_name="Owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member", first_name="Member"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    state = FakeState()

    await callback_contribution(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"contribution:{shopping_list.id}",
            message=FakeEditableMessage(chat=FakeChat(1000), message_id=10),
        ),
        state,
        session,
    )
    contribution_message = FakeMessage(from_user=FakeTelegramUser(id=100), text="100")
    await state_contribution_amount(contribution_message, state, session)

    assert contribution_message.answers
    assert "100.00 BYN" in contribution_message.answers[0][0]

    await callback_category_add(
        FakeCallback(
            from_user=FakeTelegramUser(id=200),
            data=f"category_add:{shopping_list.id}",
            message=FakeEditableMessage(chat=FakeChat(2000), message_id=20),
        ),
        state,
        session,
    )
    category_message = FakeMessage(from_user=FakeTelegramUser(id=200), text="Маршрутка")
    await state_category_title(category_message, state, session)
    assert category_message.answers
    assert "Маршрутка" in category_message.answers[0][0]

    summary = await shopping.get_money_summary(session, user_id=100, list_id=shopping_list.id)
    category = summary.categories[0]
    await callback_expense_category_add(
        FakeCallback(
            from_user=FakeTelegramUser(id=200),
            data=f"expense_category_add:{category.id}",
            message=FakeEditableMessage(chat=FakeChat(2000), message_id=21),
        ),
        state,
        session,
    )
    await state_expense_amount(FakeMessage(from_user=FakeTelegramUser(id=200), text="30"), state, session)
    source_message = FakeEditableMessage(chat=FakeChat(2000), message_id=22)
    await callback_expense_source(
        FakeCallback(
            from_user=FakeTelegramUser(id=200),
            data="expense_source:cashbox",
            message=source_message,
        ),
        state,
        session,
    )
    assert source_message.edits
    assert "Кто участвует?" in source_message.edits[-1][0]
    assert state.data["selected_user_ids"] == [200]
    done_message = FakeEditableMessage(chat=FakeChat(2000), message_id=23)
    await callback_expense_selected_done(
        FakeCallback(
            from_user=FakeTelegramUser(id=200),
            data="expense_selected_done",
            message=done_message,
        ),
        state,
        session,
    )
    assert done_message.edits
    assert "Маршрутка: Маршрутка: 30.00 BYN (касса, долей: 1)" in done_message.edits[-1][0]
    assert "платил" not in done_message.edits[-1][0]

    summary = await shopping.get_money_summary(session, user_id=100, list_id=shopping_list.id)
    assert summary.cashbox_balance == 7000
    assert [(expense.title, expense.category.title, expense.amount, expense.source) for expense in summary.expenses] == [
        ("Маршрутка", "Маршрутка", 3000, shopping.EXPENSE_SOURCE_CASHBOX)
    ]
    assert {balance.user.id: balance.balance for balance in summary.balances} == {100: 10000, 200: -3000}


async def test_expense_category_default_all_flow_has_fast_default_button(session):
    await shopping.upsert_user(session, FakeTelegramUser(id=100, username="owner", first_name="Owner"))
    await shopping.upsert_user(session, FakeTelegramUser(id=200, username="member", first_name="Member"))
    shopping_list = await shopping.create_shopping_list(session, owner_id=100, title="Пикник")
    token = await shopping.enable_public_access(session, owner_id=100, list_id=shopping_list.id)
    await shopping.join_public_list_by_token(session, user_id=200, token=token)
    category = await shopping.create_expense_category(
        session,
        user_id=100,
        list_id=shopping_list.id,
        title="Еда",
    )
    state = FakeState()

    await callback_expense_category_set_split(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"expense_category_set_split:{category.id}:all",
            message=FakeEditableMessage(chat=FakeChat(1000), message_id=10),
        ),
        session,
    )
    await session.refresh(category)
    assert category.default_split == shopping.EXPENSE_SPLIT_ALL

    await callback_expense_category_add(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data=f"expense_category_add:{category.id}",
            message=FakeEditableMessage(chat=FakeChat(1000), message_id=11),
        ),
        state,
        session,
    )
    await state_expense_amount(FakeMessage(from_user=FakeTelegramUser(id=100), text="10"), state, session)
    source_message = FakeEditableMessage(chat=FakeChat(1000), message_id=12)
    await callback_expense_source(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data="expense_source:personal",
            message=source_message,
        ),
        state,
        session,
    )
    buttons = [button for row in source_message.reply_markup.inline_keyboard for button in row]
    assert any(button.text == "По умолчанию: на всех" and button.callback_data == "expense_split:default" for button in buttons)

    done_message = FakeEditableMessage(chat=FakeChat(1000), message_id=13)
    await callback_expense_split_default(
        FakeCallback(
            from_user=FakeTelegramUser(id=100),
            data="expense_split:default",
            message=done_message,
        ),
        state,
        session,
    )
    assert done_message.edits
    assert "из своих, платил" in done_message.edits[-1][0]
    assert "долей: 2" in done_message.edits[-1][0]

    summary = await shopping.get_money_summary(session, user_id=100, list_id=shopping_list.id)
    assert [(share.user_id, share.amount) for share in summary.expenses[0].shares] == [(100, 500), (200, 500)]
    assert {balance.user.id: balance.balance for balance in summary.balances} == {100: 500, 200: -500}
