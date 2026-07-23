from __future__ import annotations

from app.db.models import ExpenseCategory, ListMember, ShoppingCategory, ShoppingItem, ShoppingList, User
from app.services.access import AccessLevel
from app.tgbot.keyboards import (
    expense_categories_keyboard,
    expense_category_keyboard,
    expense_category_split_keyboard,
    expense_split_keyboard,
    list_keyboard,
    members_keyboard,
    members_management_keyboard,
    money_keyboard,
    receipt_items_keyboard,
    shopping_categories_keyboard,
    shopping_category_keyboard,
    shopping_category_settings_keyboard,
)


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


def test_list_keyboard_has_categories_and_money_buttons():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")

    keyboard = list_keyboard(shopping_list, [], AccessLevel.member)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert not any(button.text == "Добавить" for button in buttons)
    assert any(
        button.text == "Категории списков" and button.callback_data == "shopping_categories:1"
        for button in buttons
    )
    assert any(button.text == "Деньги" and button.callback_data == "money:1" for button in buttons)


def test_money_keyboard_has_party_money_actions():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")

    keyboard = money_keyboard(shopping_list)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Взнос" and button.callback_data == "contribution:1" for button in buttons)
    assert any(button.text == "Трата" and button.callback_data == "expense:1" for button in buttons)
    assert any(button.text == "Категории трат" and button.callback_data == "categories:1" for button in buttons)
    assert any(button.text == "Итог" and button.callback_data == "money_final:1" for button in buttons)


def test_expense_categories_keyboard_has_category_custom_and_add_actions():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")
    category = ExpenseCategory(id=10, list_id=1, title="Маршрутка", default_split="selected", position=1)

    keyboard = expense_categories_keyboard(shopping_list, [category])
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Маршрутка" and button.callback_data == "expense_category:10" for button in buttons)
    assert any(button.text == "Разовая трата без категории" and button.callback_data == "expense_custom:1" for button in buttons)
    assert any(button.text == "Добавить категорию" and button.callback_data == "category_add:1" for button in buttons)


def test_expense_category_keyboard_has_expense_settings_and_rename_actions():
    category = ExpenseCategory(id=10, list_id=1, title="Маршрутка", default_split="selected", position=1)

    keyboard = expense_category_keyboard(category)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Новая трата" and button.callback_data == "expense_category_add:10" for button in buttons)
    assert any(button.text == "Распределение" and button.callback_data == "expense_category_split:10" for button in buttons)
    assert any(button.text == "Переименовать" and button.callback_data == "expense_category_rename:10" for button in buttons)
    assert any(button.text == "Удалить" and button.callback_data == "expense_category_delete:10" for button in buttons)


def test_expense_category_split_keyboard_has_all_selected_and_me_actions():
    category = ExpenseCategory(id=10, list_id=1, title="Маршрутка", default_split="selected", position=1)

    keyboard = expense_category_split_keyboard(category)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "На всех" and button.callback_data == "expense_category_set_split:10:all" for button in buttons)
    assert any(
        button.text == "Выбирать участников" and button.callback_data == "expense_category_set_split:10:selected"
        for button in buttons
    )
    assert any(button.text == "Только на меня" and button.callback_data == "expense_category_set_split:10:me" for button in buttons)


def test_shopping_categories_keyboard_has_add_and_open_actions():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")
    category = ShoppingCategory(
        id=10,
        list_id=1,
        title="Магазин",
        scope="common",
        accounting_mode="receipt",
        position=1,
    )

    keyboard = shopping_categories_keyboard(shopping_list, [category])
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.callback_data == "shopping_category:10" for button in buttons)
    assert any(button.text == "Добавить общую" and button.callback_data == "shopping_category_add_common:1" for button in buttons)
    assert any(button.text == "Добавить личную" and button.callback_data == "shopping_category_add_personal:1" for button in buttons)


def test_shopping_category_keyboard_has_main_actions():
    category = ShoppingCategory(
        id=10,
        list_id=1,
        title="Магазин",
        scope="common",
        accounting_mode="receipt",
        position=1,
    )

    keyboard = shopping_category_keyboard(category, AccessLevel.owner, user_id=100)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Чек" and button.callback_data == "receipt:10" for button in buttons)
    assert any(button.text == "Добавить товар" and button.callback_data == "add_category:10" for button in buttons)
    assert any(button.text == "Настройки" and button.callback_data == "shopping_category_settings:10" for button in buttons)
    assert any(button.text == "Назад" and button.callback_data == "shopping_categories:1" for button in buttons)
    assert not any(button.text == "Считать по товарам" for button in buttons)
    assert not any(button.text == "Удалить" for button in buttons)


def test_shopping_category_settings_keyboard_has_mode_rename_delete_and_back_actions():
    category = ShoppingCategory(
        id=10,
        list_id=1,
        title="Магазин",
        scope="common",
        accounting_mode="receipt",
        position=1,
    )

    keyboard = shopping_category_settings_keyboard(category, AccessLevel.owner, user_id=100)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "✓ Список покупок" and button.callback_data == "shopping_category_mode:10:receipt" for button in buttons)
    assert any(button.text == "Список вещей" and button.callback_data == "shopping_category_mode:10:checklist" for button in buttons)
    assert any(button.text == "По товарам" and button.callback_data == "shopping_category_mode:10:per_item" for button in buttons)
    assert any(button.text == "✓ По чеку" and button.callback_data == "shopping_category_mode:10:receipt" for button in buttons)
    assert any(button.text == "Удалить" and button.callback_data == "shopping_category_delete:10" for button in buttons)
    assert any(button.text == "Переименовать" and button.callback_data == "shopping_category_rename:10" for button in buttons)
    assert any(button.text == "Назад" and button.callback_data == "shopping_category:10" for button in buttons)


def test_checklist_shopping_category_keyboard_has_no_receipt_action():
    category = ShoppingCategory(
        id=10,
        list_id=1,
        title="Взять",
        scope="common",
        accounting_mode="checklist",
        position=1,
    )

    keyboard = shopping_category_keyboard(category, AccessLevel.owner, user_id=100)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Добавить вещь" and button.callback_data == "add_category:10" for button in buttons)
    assert not any(button.text == "Чек" for button in buttons)
    assert any(button.text == "Настройки" and button.callback_data == "shopping_category_settings:10" for button in buttons)


def test_checklist_shopping_category_settings_keyboard_hides_purchase_accounting_actions():
    category = ShoppingCategory(
        id=10,
        list_id=1,
        title="Вещи",
        scope="common",
        accounting_mode="checklist",
        position=1,
    )

    keyboard = shopping_category_settings_keyboard(category, AccessLevel.owner, user_id=100)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "Список покупок" and button.callback_data == "shopping_category_mode:10:per_item" for button in buttons)
    assert any(button.text == "✓ Список вещей" and button.callback_data == "shopping_category_mode:10:checklist" for button in buttons)
    assert not any(button.text in {"По товарам", "По чеку"} for button in buttons)


def test_receipt_items_and_default_split_keyboards():
    category = ShoppingCategory(id=10, list_id=1, title="Магазин", scope="common", accounting_mode="receipt")
    item = ShoppingItem(id=20, list_id=1, text="Сок", position=1)

    receipt_keyboard = receipt_items_keyboard(category, [item], [20])
    receipt_buttons = [button for row in receipt_keyboard.inline_keyboard for button in row]
    assert any(button.text == "✓ Сок" and button.callback_data == "receipt_select:20" for button in receipt_buttons)

    split_keyboard = expense_split_keyboard("По умолчанию категории")
    split_buttons = [button for row in split_keyboard.inline_keyboard for button in row]
    assert any(button.text == "По умолчанию категории" and button.callback_data == "expense_split:default" for button in split_buttons)


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
