from __future__ import annotations

from app.db.models import ListMember, ShoppingList, User
from app.services.access import AccessLevel
from app.tgbot.keyboards import list_keyboard, members_keyboard, members_management_keyboard


def test_list_keyboard_has_refresh_button():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")

    keyboard = list_keyboard(shopping_list, [], AccessLevel.owner)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Обновить" and button.callback_data == "refresh:1" for button in buttons)


def test_list_keyboard_has_members_button():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")

    keyboard = list_keyboard(shopping_list, [], AccessLevel.member)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Участники списка" and button.callback_data == "members:1" for button in buttons)


def test_list_keyboard_has_bulk_check_buttons_below_add_button():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")

    keyboard = list_keyboard(shopping_list, [], AccessLevel.member)
    row_texts = [[button.text for button in row] for row in keyboard.inline_keyboard]
    row_callbacks = [[button.callback_data for button in row] for row in keyboard.inline_keyboard]
    add_row_index = row_texts.index(["Добавить покупку"])

    assert row_texts[add_row_index + 1] == ["Поставить все галочки"]
    assert row_callbacks[add_row_index + 1] == ["checkall:1"]
    assert row_texts[add_row_index + 2] == ["Убрать все галочки"]
    assert row_callbacks[add_row_index + 2] == ["uncheckall:1"]


def test_owner_members_keyboard_has_manage_button():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")

    keyboard = members_keyboard(shopping_list, AccessLevel.owner)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(
        button.text == "Управлять участниками" and button.callback_data == "members_manage:1"
        for button in buttons
    )


def test_members_management_keyboard_has_remove_and_ban_buttons():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")
    user = User(id=200, username="member", first_name="Member")
    member = ListMember(list_id=1, user_id=200)

    keyboard = members_management_keyboard(shopping_list, [(member, user)])
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.callback_data == "member_remove:1:200" for button in buttons)
    assert any(button.callback_data == "member_ban:1:200" for button in buttons)
