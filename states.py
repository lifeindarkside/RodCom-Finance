from aiogram.fsm.state import State, StatesGroup

class ReceiptStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_category = State()
    waiting_for_description = State()
