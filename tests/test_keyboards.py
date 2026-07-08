from __future__ import annotations

from app.db.models import ShoppingList
from app.services.access import AccessLevel
from app.tgbot.keyboards import list_keyboard


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
