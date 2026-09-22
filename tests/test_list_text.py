from __future__ import annotations

from app.db.models import ShoppingCategory, ShoppingItem, ShoppingList
from app.tgbot.keyboards import list_text_keyboard
from app.tgbot.texts import format_full_list_pages, format_list_overview_pages


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


def test_overview_pages_keep_sections_small_and_collapsing_hides_only_their_text():
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

    pages = format_list_overview_pages(shopping_list, items, categories, user_id=100,
                                       collapsed_category_ids={2})

    assert [page.category_ids for page in pages] == [(1, 2), (3, 4), (5,)]
    assert "Пункт 1" in pages[0].text
    assert "Пункт 2" not in pages[0].text
    assert "Пункт 3" in pages[1].text
    assert all(len(page.text) < 4096 for page in pages)


def test_overview_splits_a_large_section_without_losing_items():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")
    category = ShoppingCategory(id=10, list_id=1, title="Длинный раздел", scope="common")
    items = [
        ShoppingItem(id=index, list_id=1, category_id=10, text=f"Уникальный пункт {index}: " + "&" * 20,
                     scope="common", position=index, is_done=False)
        for index in range(1, 101)
    ]

    pages = format_list_overview_pages(shopping_list, items, [category], user_id=100)

    assert len(pages) > 1
    assert all(page.category_ids == (10,) for page in pages)
    assert all(len(page.text) < 4096 for page in pages)
    assert all(sum(line.startswith("□ ") for line in page.text.splitlines()) <= 8 for page in pages)
    for index in range(1, 101):
        assert sum(f"Уникальный пункт {index}:" in line for page in pages for line in page.text.splitlines()) == 1


def test_overview_omits_empty_sections_while_section_management_remains_available():
    shopping_list = ShoppingList(id=1, owner_id=100, title="Дом")
    empty = ShoppingCategory(id=10, list_id=1, title="Пустой", scope="personal", owner_id=100)
    active = ShoppingCategory(id=11, list_id=1, title="Активный", scope="common")
    item = ShoppingItem(id=20, list_id=1, category_id=11, text="Купить хлеб", scope="common", is_done=False)

    pages = format_list_overview_pages(shopping_list, [item], [empty, active], user_id=100)

    assert len(pages) == 1
    assert pages[0].category_ids == (11,)
    assert "Пустой" not in pages[0].text
    assert "Купить хлеб" in pages[0].text
