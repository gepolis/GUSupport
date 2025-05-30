from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Новое обращение", callback_data="start"),
        ]
    ]
)

def rate_operator(chat_id):
    kb = InlineKeyboardBuilder()
    rates = ["1","2","3","4","5"]
    for rate in rates:
        kb.add(InlineKeyboardButton(text=rate, callback_data=f"rate_{chat_id}_{rate}"))

