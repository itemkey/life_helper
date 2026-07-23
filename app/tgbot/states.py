from aiogram.fsm.state import State, StatesGroup


class ShoppingListStates(StatesGroup):
    creating_title = State()
    adding_items = State()
    buying_item_amount = State()
    choosing_item_purchase_source = State()
    adding_contribution_amount = State()
    adding_expense_title = State()
    adding_expense_amount = State()
    choosing_expense_source = State()
    choosing_expense_split = State()
    renaming_list = State()
