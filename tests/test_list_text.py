from __future__ import annotations

from app.db.models import ShoppingCategory, ShoppingItem, ShoppingList
from app.tgbot.keyboards import list_text_keyboard
from app.tgbot.texts import format_full_list_pages


def test_long_text_list_includes_every_item_across_telegram_sized_pages():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Поездка", prices_enabled=False)
    category = ShoppingCategory(id=10, list_id=1, title="Снаряжение", scope="common", position=1)
    items = [
        ShoppingItem(id=index, list_id=1, category_id=10, text=f"Пункт {index}: " + "&" * 15,
                     scope="common", position=index, is_done=index % 2 == 0)
        for index in range(1, 151)
    ]

    pages = format_full_list_pages(shopping_list, items, [category], user_id=100)

    assert len(pages) > 1
    assert all(len(page) < 4096 for page in pages)
    assert all("Снаряжение" in page for page in pages)
    for index in range(1, 151):
        assert sum(f"Пункт {index}:" in line for page in pages for line in page.splitlines()) == 1
    buttons = [button for row in list_text_keyboard(1, page=1, total_pages=len(pages)).inline_keyboard for button in row]
    assert any(button.callback_data == "list_text:1:0" for button in buttons)
    assert any(button.callback_data == "open:1" for button in buttons)


def test_full_list_shows_all_sections_and_items_in_one_message_when_it_fits():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом", prices_enabled=False)
    categories = [
        ShoppingCategory(id=index, list_id=1, title=f"Раздел {index}", scope="common", position=index)
        for index in range(1, 6)
    ]
    items = [
        ShoppingItem(id=index, list_id=1, category_id=index, text=f"Пункт {index}",
                     scope="common", position=index, is_done=False)
        for index in range(1, 6)
    ]

    pages = format_full_list_pages(shopping_list, items, categories, user_id=100)

    assert len(pages) == 1
    for index in range(1, 6):
        assert f"Раздел {index}" in pages[0]
        assert f"Пункт {index}" in pages[0]
