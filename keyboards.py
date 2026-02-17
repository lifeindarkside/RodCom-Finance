from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu_kb(user_role: str = "user") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Отчет (Баланс)", callback_data="report")],
        [InlineKeyboardButton(text="📁 Экспорт Excel", callback_data="export")]
    ]
    
    if user_role == "admin":
        buttons.insert(0, [InlineKeyboardButton(text="📤 Добавить расход", callback_data="add_expense")])
        buttons.insert(1, [InlineKeyboardButton(text="📥 Добавить взнос", callback_data="add_income_help")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)
