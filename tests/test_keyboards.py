from __future__ import annotations

from app.db.models import ListMember, ShoppingList, User
from app.services.access import AccessLevel
from app.tgbot.keyboards import list_keyboard, members_keyboard, members_management_keyboard, money_keyboard


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


def test_list_keyboard_has_common_personal_and_money_buttons():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")

    keyboard = list_keyboard(shopping_list, [], AccessLevel.member)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Добавить в общее" and button.callback_data == "add_common:1" for button in buttons)
    assert any(button.text == "Добавить в мой список" and button.callback_data == "add_personal:1" for button in buttons)
    assert any(button.text == "Деньги" and button.callback_data == "money:1" for button in buttons)


def test_money_keyboard_has_party_money_actions():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")

    keyboard = money_keyboard(shopping_list)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Взнос" and button.callback_data == "contribution:1" for button in buttons)
    assert any(button.text == "Трата" and button.callback_data == "expense:1" for button in buttons)
    assert any(button.text == "Такси" and button.callback_data == "taxi:1" for button in buttons)
    assert any(button.text == "Итог" and button.callback_data == "money_final:1" for button in buttons)


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
