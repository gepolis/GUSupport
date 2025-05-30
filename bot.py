import asyncio
import datetime
from urllib.parse import quote_plus

from aiogram import Bot, Dispatcher, types, enums, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, MISTRAL_TOKEN, SYSTEM_PROMT
from db import db, ChatRequest, ChatHistory
from mistralai import Mistral, SDKError
from flask import Flask
from utils import format_chat_history, load_system_promt, check_system_promt


# DB Middleware
class DBMiddleware:
    async def __call__(self, handler, event, data):
        data['db'] = db.session
        return await handler(event, data)


# Flask setup
escaped_password = quote_plus("operator")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f'postgresql://operator:{escaped_password}@94.198.216.178:5432/oper?sslmode=require'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# AIogram & Mistral
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.update.middleware(DBMiddleware())
mclient = Mistral(MISTRAL_TOKEN)
SYSTEM_PROMT_BOT = load_system_promt(SYSTEM_PROMT)

# --- Keyboards ---
start_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📝 Создать обращение", callback_data="start")]
])

@dp.message(Command("systempromt"))
async def handle_message(message: types.Message):
    await message.answer(SYSTEM_PROMT_BOT)
# --- Handlers ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать!\nНажмите кнопку ниже, чтобы создать обращение:",
        reply_markup=start_keyboard
    )


@dp.callback_query(F.data == "start")
async def process_callback_start(callback: types.CallbackQuery):
    await callback.answer()

    with app.app_context():
        existing_chat = db.session.query(ChatRequest).filter(
            ChatRequest.user_id == callback.from_user.id,
            ChatRequest.status == "open"
        ).first()

        if existing_chat:
            await callback.message.answer("У вас уже есть открытое обращение.")
        else:
            new_chat = ChatRequest(
                user_id=callback.from_user.id,
                status="open",
                operator_mode="off",
                operator_id=0,
                created_at=datetime.datetime.utcnow()
            )
            db.session.add(new_chat)
            db.session.commit()
            await callback.message.answer("🎉 Обращение создано! Напишите ваш вопрос.")


@dp.message(Command("close"))
async def close_chat(message: types.Message):
    with app.app_context():
        chat = db.session.query(ChatRequest).filter(
            ChatRequest.user_id == message.from_user.id,
            ChatRequest.status == "open"
        ).first()

        if not chat:
            await message.answer("У вас нет открытых обращений.")
            return

        chat.status = "closed"
        db.session.commit()
        await message.answer("✅ Обращение закрыто.")

@dp.message()
async def handle_message(message: types.Message):
    with app.app_context():
        chat = db.session.query(ChatRequest).filter(
            ChatRequest.user_id == message.from_user.id,
            ChatRequest.status == "open"
        ).first()


        if not chat:
            chat = ChatRequest(
                user_id=message.from_user.id,
                status="open",
                operator_mode="off",
                operator_id=0,
                created_at=datetime.datetime.utcnow()
            )
            db.session.add(chat)
            db.session.commit()

        text = message.caption or message.text or ""
        addon = " (прикрепил фото)" if message.caption else ""

        # Добавление system prompt (если отсутствует)
        first_message = db.session.query(ChatHistory).filter_by(
            user_id=message.from_user.id,
            request_id=chat.id
        ).first()
        if not first_message:
            db.session.add(ChatHistory(
                user_id=message.from_user.id,
                role="system",
                message=SYSTEM_PROMT_BOT,
                request=chat
            ))

        # Добавление пользовательского сообщения
        db.session.add(ChatHistory(
            user_id=message.from_user.id,
            role="user",
            message=f"{text}{addon}",
            request=chat
        ))
        db.session.commit()

        await bot.send_chat_action(message.chat.id, enums.ChatAction.TYPING)

        # Получение истории
        histories = db.session.query(ChatHistory).filter_by(
            user_id=message.from_user.id,
            request_id=chat.id
        ).order_by(ChatHistory.id).all()
        history_data = format_chat_history(histories)

        # Попытки генерации
        attempt = 0
        chat_response = None
        max_retries = 3

        while attempt < max_retries:
            try:
                chat_response = mclient.chat.complete(
                    model="mistral-large-latest",
                    messages=history_data,
                    temperature=0.7,
                )
                break
            except SDKError as e:
                attempt += 1
                print(f"[Mistral Error] Попытка {attempt}: {e}")
                await asyncio.sleep(1)  # небольшая задержка перед повтором
                if attempt == max_retries:
                    await message.answer("⚠️ Возникла ошибка при генерации ответа. Пожалуйста, попробуйте позже.")
                    return

        # Обработка и сохранение ответа
        content = chat_response.choices[0].message.content
        msg, sys_tags = (content.split("-END-END-") + [""])[:2]

        db.session.add(ChatHistory(
            user_id=message.from_user.id,
            role="assistant",
            message=msg,
            request=chat
        ))

        if "OPERATOR" in sys_tags:
            chat.operator_mode = "on"

        db.session.commit()
        await message.answer(msg)


# --- Entry point ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("Бот запущен")
        dp.run_polling(bot)
