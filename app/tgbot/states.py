from aiogram.fsm.state import State, StatesGroup


class ShoppingListStates(StatesGroup):
    creating_title = State()
    adding_items = State()
    renaming_list = State()
