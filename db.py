from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class ChatRequest(db.Model):
    __tablename__ = 'chat_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String, default='open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    operator_mode = db.Column(db.String, default='off')
    operator_id = db.Column(db.Integer, default=0)

    history = db.relationship('ChatHistory', backref='request', lazy=True)


class ChatHistory(db.Model):
    __tablename__ = 'chat_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False)
    role = db.Column(db.String, nullable=False)
    message = db.Column(db.Text, nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey('chat_requests.id'), nullable=False)


class Operator(db.Model):
    __tablename__ = 'operators'

    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String, nullable=False, unique=True)
    password = db.Column(db.String, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
