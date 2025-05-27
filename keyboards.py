from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def create_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Новое обращение", callback_data="start"),
            ],
        ]
    )
    return keyboard