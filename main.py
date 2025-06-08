import hashlib
import threading
import time
from urllib.parse import quote_plus

from flask import Flask, render_template, request, redirect, jsonify, make_response, url_for
from flask_sqlalchemy import SQLAlchemy
from functools import wraps
import requests
from sqlalchemy import case, ColumnElement, func, or_, cast, String

import config
from db import ChatHistory, ChatRequest, Operator, db

app = Flask(__name__)
SUPPORT_KEY = config.SUPPORT_KEY

# Экранируем спецсимволы в пароле
escaped_password = quote_plus("operator")

# Настройка подключения к PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f'postgresql://operator:{escaped_password}@94.198.216.178:5432/oper?sslmode=require'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
with app.app_context():
    db.create_all()

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
    count = ChatRequest.query.filter_by(
        status="open", operator_mode="on", operator_id=0
    ).count()
    return {"count": count}

@app.route('/api/operator/my/chats')
@operator_required
def get_my_chats():
    operator_id = request.cookies.get("operator_id")
    chats = ChatRequest.query.filter_by(
        status="in_progress", operator_mode="on", operator_id=operator_id
    ).with_entities(ChatRequest.id, ChatRequest.user_id, ChatRequest.created_at, ChatRequest.operator_id).all()
    return {"chats": [chat._asdict() for chat in chats]}

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
        chat = ChatRequest.query.filter_by(
            status="open", operator_mode="on", operator_id=0
        ).order_by(ChatRequest.created_at.desc()).first()

        if not chat:
            return {"id": 0, "user_id": 0}

        rows_updated = ChatRequest.query.filter_by(
            id=chat.id, operator_id=0
        ).update({"operator_id": operator_id,"status": "in_progress"})

        db.session.commit()

        if rows_updated == 0:
            return {"id": 0, "user_id": 0}

        async_send_telegram(chat.user_id, f"Оператор #{operator_id} присоединился к чату")
        return {"id": chat.id, "user_id": chat.user_id}

    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 500

@app.route('/api/operator/request/close')
@operator_required
def close_chat():
    chat_id = request.args.get("id")
    operator_id = request.cookies.get("operator_id")
    chat = ChatRequest.query.get(chat_id)

    rows_updated = ChatRequest.query.filter_by(
        id=chat_id, operator_id=operator_id
    ).update({
        "operator_mode": "off",
        "operator_id": 0,
        "status": "closed"
    })

    db.session.commit()

    if rows_updated == 0:
        return {"error": "chat not found or not yours"}, 400

    async_send_telegram(chat.user_id, f"Оператор #{operator_id} закрыл чат")
    return {"id": chat_id}

@app.route('/api/operator/request/answer')
@operator_required
def answer_chat():
    chat_id = request.args.get("id")
    answer = request.args.get("answer")

    try:
        chat = ChatRequest.query.get(chat_id)

        threading.Thread(
            target=async_send_telegram,
            args=(chat.user_id, answer)
        ).start()

        history = ChatHistory(
            user_id=chat_id,
            role="assistant",
            message=answer,
            request_id=chat_id
        )
        db.session.add(history)
        db.session.commit()

        return {"id": chat_id}
    except:
        db.session.rollback()
        return {"error": "chat not found"}, 404

@app.route('/api/operator/request/history')
@operator_required
def get_history():
    chat_id = request.args.get("id")
    last_message_id = request.args.get("since", 0)
    if not str(last_message_id).isdigit():
        last_message_id = 0

    messages = ChatHistory.query.filter(
        ChatHistory.request_id == chat_id,
        ChatHistory.id > last_message_id
    ).order_by(ChatHistory.id.asc()).all()

    return {"history": [{"role": m.role, "message": m.message, "id": m.id} for m in messages]}

@app.route('/api/operator/chat/user/<action>')
@operator_required
def get_user_info(action):
    if action not in ["info", "closes", "profiles", "payments", "promocodes"]:
        return {"error": "invalid action"}, 400

    chat_id = request.args.get("id")
    operator_id = request.cookies.get("operator_id")
    if not chat_id or operator_id is None:
        return {"error": "chat not found"}, 400

    chat = ChatRequest.query.filter_by(id=chat_id, operator_id=operator_id).first()
    if not chat:
        return {"error": "chat not found or not yours"}, 400

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
    operator = Operator.query.filter_by(login=login, password=password).first()

    if operator is None:
        return {"success": False, "message": "Неверный логин или пароль"}

    response = jsonify({"success": True, "token": operator.id, "message": "Авторизация успешна"})
    response.set_cookie(
        "operator_id",
        str(operator.id),
        max_age=60*60*24*7
    )

    return response


#ADMIN
# Декораторы для проверки прав
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        operator_id = request.cookies.get("operator_id")
        if not operator_id:
            return jsonify({'error': 'Unauthorized'}), 401

        operator = Operator.query.get(operator_id)
        if not operator or not operator.is_admin:
            return jsonify({'error': 'Forbidden'}), 403

        return f(*args, **kwargs)

    return decorated_function


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.cookies.get("operator_id") is None:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)

    return decorated_function


# Роуты аутентификации
@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    login = data.get('login')
    password = data.get('password')

    operator = Operator.query.filter_by(login=login).first()
    if not operator or not hashlib.sha256(password.encode()).hexdigest() == operator.password:
        return jsonify({'error': 'Invalid credentials'}), 401


    req = jsonify({'success': True, 'is_admin': operator.is_admin})
    req.set_cookie(
        "operator_id",
        str(operator.id),
        max_age=60*60*24*7
    )
    return req


@app.route('/admin/logout', methods=['POST'])
@login_required
def admin_logout():
    req =  jsonify({'success': True})
    req.delete_cookie("operator_id")
    return req


# Основные роуты администратора
@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('admin.html')


# Операторы
@app.route('/api/admin/operators')
@admin_required
def api_get_operators():
    operators = Operator.query.all()
    return jsonify([{
        'id': op.id,
        'login': op.login,
        'is_admin': op.is_admin
    } for op in operators])


@app.route('/api/admin/operator/<int:operator_id>')
@admin_required
def api_get_operator(operator_id):
    operator = Operator.query.get_or_404(operator_id)
    return jsonify({
        'id': operator.id,
        'login': operator.login,
        'is_admin': operator.is_admin,
        'stats': {
            'total_chats': ChatRequest.query.filter_by(operator_id=operator.id).count(),
            'active_chats': ChatRequest.query.filter_by(operator_id=operator.id, status='in_progress').count(),
            'closed_chats': ChatRequest.query.filter_by(operator_id=operator.id, status='closed').count()
        }
    })


@app.route('/api/admin/create_operator', methods=['POST'])
@admin_required
def api_create_operator():
    data = request.get_json()
    login = data.get('login')
    password = data.get('password')
    is_admin = data.get('is_admin', False)

    if not login or not password:
        return jsonify({'error': 'Login and password are required'}), 400

    if Operator.query.filter_by(login=login).first():
        return jsonify({'error': 'Operator with this login already exists'}), 400

    operator = Operator(
        login=login,
        password=hashlib.sha256(password.encode()).hexdigest(),
        is_admin=is_admin
    )
    db.session.add(operator)
    db.session.commit()

    return jsonify({'success': True, 'operator_id': operator.id})


@app.route('/api/admin/update_operator/<int:operator_id>', methods=['POST'])
@admin_required
def api_update_operator(operator_id):
    operator = Operator.query.get_or_404(operator_id)
    data = request.get_json()

    if 'login' in data:
        if Operator.query.filter(Operator.id != operator.id, Operator.login == data['login']).first():
            return jsonify({'error': 'Login already taken'}), 400
        operator.login = data['login']

    if 'password' in data and data['password']:
        operator.password = hashlib.sha256(data['password'].encode()).hexdigest()

    if 'is_admin' in data:
        operator.is_admin = data['is_admin']

    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/delete_operator/<int:operator_id>', methods=['POST'])
@admin_required
def api_delete_operator(operator_id):
    operator = Operator.query.get_or_404(operator_id)

    # Переназначаем чаты другому оператору
    other_operator = Operator.query.filter(Operator.id != operator.id).first()
    if other_operator:
        ChatRequest.query.filter_by(operator_id=operator.id).update({'operator_id': other_operator.id})

    db.session.delete(operator)
    db.session.commit()
    return jsonify({'success': True})


# Чаты
STATUS_PRIORITY = {
    'in_progress': 1,
    'open': 2,
    'closed': 3,
}
from flask import jsonify, request
from sqlalchemy import or_, func, text
from sqlalchemy.orm import aliased

@app.route('/api/admin/chats')
@admin_required
def api_get_chats():
    status = request.args.get('status')
    search = request.args.get('search')
    operator_id = request.args.get('operator_id')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = db.session.query(ChatRequest)

    # Фильтрация по статусу
    if status and status != 'all':
        query = query.filter(ChatRequest.status == status)

    # Фильтрация по оператору
    if operator_id:
        query = query.filter(ChatRequest.operator_id == operator_id)

    # Поиск по user_id (каст в текст) и тексту сообщений
    if search:
        subq = db.session.query(ChatHistory.request_id).join(
            ChatRequest, ChatRequest.id == ChatHistory.request_id
        ).filter(
            or_(
                cast(ChatRequest.user_id, String).ilike(f'%{search}%'),
                ChatHistory.message.ilike(f'%{search}%')
            )
        ).subquery()

        query = query.filter(ChatRequest.id.in_(subq))

    # Сортировка
    query = query.order_by(
        text("POSITION(status IN 'in_progress open closed')"),
        ChatRequest.id.desc()
    )

    # Пагинация
    chats = query.paginate(page=page, per_page=per_page)

    chat_ids = [chat.id for chat in chats.items]

    # Последние сообщения
    last_messages = db.session.query(
        ChatHistory.request_id,
        func.max(ChatHistory.id)
    ).filter(ChatHistory.request_id.in_(chat_ids)) \
     .group_by(ChatHistory.request_id).all()

    last_message_map = {row.request_id: f"message #{row[1]}" for row in last_messages}

    # Количество сообщений
    message_counts = db.session.query(
        ChatHistory.request_id,
        func.count(ChatHistory.id)
    ).filter(ChatHistory.request_id.in_(chat_ids)) \
     .group_by(ChatHistory.request_id).all()

    message_count_map = {row[0]: row[1] for row in message_counts}

    return jsonify({
        'chats': [{
            'id': chat.id,
            'user_id': chat.user_id,
            'status': chat.status,
            'operator_id': chat.operator_id,
            'operator_name': chat.operator_id if chat.operator_id else "Не назначен",
            'last_message': last_message_map.get(chat.id),
            'message_count': message_count_map.get(chat.id, 0)
        } for chat in chats.items],
        'total': chats.total,
        'pages': chats.pages,
        'current_page': chats.page
    })

def get_last_message(chat_id):
    last_msg = ChatHistory.query.filter_by(request_id=chat_id).order_by(ChatHistory.id.desc()).first()
    if last_msg:
        return {
            'text': last_msg.message[:50] + '...' if len(last_msg.message) > 50 else last_msg.message,
            'role': last_msg.role
        }
    return None


@app.route('/api/admin/chat/<int:chat_id>')
@admin_required
def api_get_chat(chat_id):
    chat = ChatRequest.query.get_or_404(chat_id)
    return jsonify({
        'id': chat.id,
        'user_id': chat.user_id,
        'status': chat.status,
        'operator_id': chat.operator_id,
        'created_at': chat.created_at.isoformat(),
        'stats': {
            'message_count': ChatHistory.query.filter_by(request_id=chat.id).count(),
            'operator_messages': ChatHistory.query.filter_by(request_id=chat.id, role='assistant').count(),
            'client_messages': ChatHistory.query.filter_by(request_id=chat.id, role='client').count()
        }
    })


@app.route('/api/admin/chat/<int:chat_id>/messages')
@admin_required
def api_chat_messages(chat_id):
    messages = ChatHistory.query.filter_by(request_id=chat_id).order_by(ChatHistory.id.asc()).all()
    return jsonify([{
        'id': m.id,
        'role': m.role,
        'message': m.message,
        'user_id': m.user_id
    } for m in messages])


@app.route('/api/admin/chat/<int:chat_id>/send', methods=['POST'])
@admin_required
def api_send_message(chat_id):
    data = request.get_json()
    message = data.get('message')
    if not message:
        return jsonify({'error': 'Message is required'}), 400

    chat = ChatRequest.query.get_or_404(chat_id)
    operator_id = request.cookies.get('operator_id')

    new_message = ChatHistory(
        request_id=chat_id,
        user_id=str(operator_id),
        role='assistant',
        message=message
    )
    db.session.add(new_message)

    if chat.status == 'open':
        chat.status = 'in_progress'
        chat.operator_id = operator_id

    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/chat/<int:chat_id>/close', methods=['POST'])
@admin_required
def api_close_chat(chat_id):
    chat = ChatRequest.query.get_or_404(chat_id)
    async_send_telegram(chat.user_id,"🔒 Администратор закрыл чат")
    chat.status = 'closed'
    db.session.commit()

    return jsonify({'success': True})


@app.route('/api/admin/chat/<int:chat_id>/assign', methods=['POST'])
@admin_required
def api_assign_chat(chat_id):
    data = request.get_json()
    operator_id = data.get('operator_id')

    if not operator_id:
        return jsonify({'error': 'Operator ID is required'}), 400

    operator = Operator.query.get(operator_id)
    if not operator:
        return jsonify({'error': 'Operator not found'}), 404

    chat = ChatRequest.query.get_or_404(chat_id)
    chat.operator_id = operator_id
    chat.status = 'in_progress'
    if chat.operator_mode == "off":
        async_send_telegram(chat.user_id,f"❗ Администратор передал обращение оператору #{operator_id}")
    db.session.commit()
    async_send_telegram(chat.user_id,"❗ Администратор передал обращение другому оператору")

    return jsonify({'success': True})


# Статистика
@app.route('/api/admin/stats')
@admin_required
def api_admin_stats():
    return jsonify({
        'total_operators': Operator.query.count(),
        'total_chats': ChatRequest.query.count(),
        'open_chats': ChatRequest.query.filter_by(status='open').count(),
        'active_chats': ChatRequest.query.filter_by(status='in_progress').count(),
        'closed_chats': ChatRequest.query.filter_by(status='closed').count()
    })


def get_busiest_operator():
    return {
        'id': 0,
        'login': "test",
        'active_chats': 0
    }
    return None


# Быстрые ответы (без отдельной модели)
@app.route('/api/admin/quick_responses')
@admin_required
def api_get_quick_responses():
    # В реальной системе это бы бралось из базы данных
    return jsonify([
        {"id": 1, "text": "Здравствуйте! Чем могу помочь?"},
        {"id": 2, "text": "Спасибо за ваше сообщение. Мы работаем над вашим вопросом."},
        {"id": 3, "text": "Для решения этого вопроса нам потребуется дополнительная информация."},
        {"id": 4, "text": "Ваш вопрос передан специалисту. Ожидайте ответа."},
        {"id": 5, "text": "Благодарим вас за обращение! Чем еще могу помочь?"}
    ])
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
