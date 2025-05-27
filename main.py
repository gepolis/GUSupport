import hashlib
import threading
import time

from flask import Flask, render_template, request, redirect, jsonify
import requests

import config
from db import ChatHistory, ChatRequest, db, Operator
from functools import wraps

app = Flask(__name__)
SUPPORT_KEY = config.SUPPORT_KEY

@app.route('/')
def index():
    return render_template('operator.html')


# Простое кэширование в памяти (замена SimpleCache)
class SimpleCache:
    def __init__(self):
        self._cache = {}
        self._timestamps = {}

    def get(self, key):
        if key in self._cache:
            return self._cache[key]
        return None

    def set(self, key, value, timeout=None):
        self._cache[key] = value
        self._timestamps[key] = time.time() + timeout if timeout else None

    def delete(self, key):
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)


cache = SimpleCache()


# Декоратор для проверки авторизации
def operator_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not request.cookies.get("operator_id"):
            return {"error": "unauthorized"}, 403
        return f(*args, **kwargs)

    return decorated_function


@app.route('/api/operator/requests')
@operator_required
def get_chats():
    count = ChatRequest.select().where(
        ChatRequest.status == "open",
        ChatRequest.operator_mode == "on",
        ChatRequest.operator_id == 0
    ).count()
    print(count)

    return {"count": count}


@app.route('/api/operator/my/chats')
@operator_required
def get_my_chats():
    operator_id = request.cookies.get("operator_id")
    count = ChatRequest.select(
        ChatRequest.id,
        ChatRequest.user_id,
        ChatRequest.created_at,
        ChatRequest.operator_id
    ).where(
        ChatRequest.status == "open",
        ChatRequest.operator_mode == "on",
        ChatRequest.operator_id == operator_id
    )

    return {"chats": list(count.dicts())}

def async_send_telegram(client_id, message):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': client_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram send error: {e}")
@app.route('/api/operator/request/chat')
@operator_required
def get_chat():
    operator_id = request.cookies.get("operator_id")

    try:
        with db.atomic():
            chat = ChatRequest.select().where(
                ChatRequest.status == "open",
                ChatRequest.operator_mode == "on",
                ChatRequest.operator_id == 0
            ).order_by(ChatRequest.created_at.desc()).get()

            updated = ChatRequest.update(
                operator_id=operator_id
            ).where(
                ChatRequest.id == chat.id,
                ChatRequest.operator_id == 0
            ).execute()

            async_send_telegram(chat.user_id, f"Оператор #{operator_id} присоединился к чату")



            if updated == 0:
                return {"id": 0, "user_id": 0}

            return {"id": chat.id, "user_id": chat.user_id}
    except ChatRequest.DoesNotExist:
        return {"id": 0, "user_id": 0}


@app.route('/api/operator/request/close')
@operator_required
def close_chat():
    chat_id = request.args.get("id")
    operator_id = request.cookies.get("operator_id")
    chat = ChatRequest.get(ChatRequest.id == chat_id)
    updated = ChatRequest.update(
        operator_mode="off",
        operator_id=0,
        status="closed"
    ).where(
        ChatRequest.id == chat_id,
        ChatRequest.operator_id == operator_id
    ).execute()


    if updated == 0:
        return {"error": "chat not found or not yours"}, 400
    async_send_telegram(chat.user_id, f"Оператор #{operator_id} закрыл чат")

    return {"id": chat_id}





@app.route('/api/operator/request/answer')
@operator_required
def answer_chat():
    chat_id = request.args.get("id")
    answer = request.args.get("answer")

    try:
        chat = ChatRequest.get(ChatRequest.id == chat_id)

        threading.Thread(
            target=async_send_telegram,
            args=(chat.user_id, answer)
        ).start()

        ChatHistory.create(
            user_id=chat_id,
            role="assistant",
            message=answer,
            request=chat
        )

        return {"id": chat_id}
    except ChatRequest.DoesNotExist:
        return {"error": "chat not found"}, 404


@app.route('/api/operator/request/history')
@operator_required
def get_history():
    chat_id = request.args.get("id")
    last_message_id = request.args.get("since", 0)
    if not last_message_id.isdigit():
        last_message_id = 0

    messages = list(ChatHistory.select(
        ChatHistory.role,
        ChatHistory.message,
        ChatHistory.id
    ).where(
        ChatHistory.request == chat_id,
        ChatHistory.id > last_message_id
    ).order_by(ChatHistory.id.asc()).dicts())

    return {"history": messages}

@app.route('/api/operator/chat/user/<action>')
@operator_required
def get_user_info(action):
    if action not in ["info", "closes", "profiles","payments", "promocodes"]:
        return {"error": "invalid action"}, 400

    chat_id = request.args.get("id")
    operator_id = request.cookies.get("operator_id")
    if not chat_id or operator_id is None:
        return {"error": "chat not found"}, 400
    chat = ChatRequest.select().where(
        ChatRequest.id == chat_id,
        ChatRequest.operator_id == operator_id
    )
    if chat.count() == 0:
        return {"error": "chat not found or not yours"}, 400
    chat = chat.get()
    req = requests.get(
        config.BASE_API_URL + f"{action}",
        params={"id": chat.user_id, "key": SUPPORT_KEY}
    )

    return req.json()

@app.route('/user')
def user():
    if request.cookies.get("operator_id") is None:
        return redirect("/")
    chat_id = request.args.get("id")
    if not chat_id:
        return redirect("/")
    return render_template('user_data.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/api/operator/login', methods=['POST'])
def login_operator():
    data = request.get_json()
    login = data.get("username")
    password = hashlib.sha256(data.get("password").encode()).hexdigest()
    operator = Operator.select().where(Operator.login == login, Operator.password == password).first()
    print(password)
    if operator is None:
        return {"success": False, "message": "Неверный логин или пароль"}


    response = jsonify({"success": True, "token": operator.id, "message": "Авторизация успешна"})
    response.set_cookie("operator_id", str(operator.id))

    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)