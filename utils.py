import os
from aiogram import Bot

from config import BOT_TOKEN
from db import ChatHistory

bot = Bot(token=BOT_TOKEN)

def format_chat_history(chat_history: list[ChatHistory]):
    data = []
    for history in chat_history:
        data.append({"role": history.role, "content": history.message})
    return data

def load_system_promt(BASE_PROMT):
    sp = BASE_PROMT
    for i in os.listdir("data"):
        if i.endswith(".txt"):
            with open(f"data/{i}", "r", encoding="utf-8") as f:
                sp += f.read()

    return sp

def check_system_promt(chat_history: list[ChatHistory], BASE_PROMT):
    if len(chat_history) == 0:
        return True
    else:
        first = chat_history[0]
        if first.role == "system" and first.message == BASE_PROMT:
            return True
        else:
            return False

async def send_message_to_client(client_id, message):
    await bot.send_message(client_id, message)
