import datetime

from aiogram import Bot, Dispatcher, enums, F
from aiogram.filters import Command

from config import *
from db import db, ChatHistory, ChatRequest, Operator
from mistralai import Mistral

from keyboards import create_keyboard
from utils import format_chat_history, load_system_promt, check_system_promt

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
mclient = Mistral(MISTRAL_TOKEN)
SYSTEM_PROMT_BOT = load_system_promt(SYSTEM_PROMT)

@dp.message(Command("start"))
async def start(message):
    kb = create_keyboard()
    await message.answer("Привет, это теч. поддержка сервиса Госуслуги 2.0. \n\nДля создания обращения нажмите на кнопку ниже.", reply_markup=kb)

@dp.message(Command("close"))
async def clear(message):
    chat = ChatRequest.select().where(ChatRequest.user_id == message.from_user.id, ChatRequest.status == "open")
    print(chat.count())
    if chat.count() == 0:
        await message.answer("У вас нет открытых обращений")
        return
    chat = chat.get()
    chat.status = "closed"
    chat.save()

    await message.answer("Чат закрыт")
@dp.message()
async def echo(message):
    if ChatRequest.select().where(ChatRequest.user_id == message.from_user.id, ChatRequest.status == "open").count() == 0:
        ch = ChatRequest(user_id=message.from_user.id)
        ch.save()
    else:
        ch = ChatRequest.get(ChatRequest.user_id == message.from_user.id, ChatRequest.status == "open")
    if ch.operator_mode == "on":
        ChatHistory.create(user_id=message.from_user.id, role="user", message=message.text, request=ch)
        print("operator mode")
        return
    print(message.text)
    if message.text or message.caption:
        if message.caption:
            text = message.caption
            addon = "Прекрепил фото"
        else:
            addon = ""
            text = message.text
        if ChatHistory.select().where(ChatHistory.user_id == message.from_user.id, ChatHistory.request == ch).count() == 0:
            ChatHistory.create(user_id=message.from_user.id, role="system", message=SYSTEM_PROMT_BOT, request=ch)
        if not check_system_promt(ChatHistory.select().where(ChatHistory.user_id == message.from_user.id, ChatHistory.request == ch), SYSTEM_PROMT_BOT):
            ChatHistory.delete().where(ChatHistory.user_id == message.from_user.id, ChatHistory.request == ch).execute()
            ChatHistory.create(user_id=message.from_user.id, role="system", message=SYSTEM_PROMT_BOT, request=ch)
        ChatHistory.create(user_id=message.from_user.id, role="user", message=text+" "+addon, request=ch)
        await bot.send_chat_action(message.from_user.id, enums.ChatAction.TYPING)
        print(format_chat_history(ChatHistory.select().where(ChatHistory.user_id == message.from_user.id)))

        chat_response = mclient.chat.complete(
            model="mistral-large-latest",
            messages=format_chat_history(ChatHistory.select().where(ChatHistory.user_id == message.from_user.id, ChatHistory.request == ch)),
            temperature=0.7,
        )

        ChatHistory.create(user_id=message.from_user.id, role="assistant", message=chat_response.choices[0].message.content, request=ch)
        if "-END-END-" in chat_response.choices[0].message.content:
            msg= chat_response.choices[0].message.content.split("-END-END-")[0]
            sys_tags = chat_response.choices[0].message.content.split("-END-END-")[1]

        else:
            msg = chat_response.choices[0].message.content
            sys_tags = ""

        if "OPERATOR" in sys_tags:
            ch.operator_mode = "on"
            ch.save()
        if message.from_user.username == "gepolis":
            await message.answer(chat_response.choices[0].message.content)
            return
        await message.answer(msg)


@dp.callback_query(F.data == "start")
async def process_callback_start(callback_query):
    await callback_query.answer()
    ch = ChatRequest.select().where(ChatRequest.user_id == callback_query.from_user.id, ChatRequest.status == "open").count()
    if ch != 0:
        await callback_query.message.answer("У вас уже есть открытое обращение")
    else:
        print(callback_query.from_user.id)
        ch = ChatRequest(
            user_id=callback_query.from_user.id,
            status="open",
            operator_mode="off",
            operator_id=0,
            created_at=datetime.datetime.now()
        )
        ch.save()
        await callback_query.message.answer("Обращение создано. Напишите Ваш вопрос")


if __name__ == '__main__':
    db.connect()
    db.create_tables([ChatHistory, ChatRequest, Operator])
    print("Бот запущен")
    dp.run_polling(bot)
