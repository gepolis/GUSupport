import datetime

from peewee import *

from urllib.parse import quote_plus

# Экранируем спецсимволы в пароле
escaped_password = quote_plus('operator')

db = PostgresqlDatabase(
    database='oper',
    user='operator',
    password=escaped_password,
    host='94.198.216.178',
    port=5432,
    sslmode='require',
    autorollback=True,
    autocommit=True

)
class ChatRequest(Model):
    id = PrimaryKeyField()
    user_id = BigIntegerField()
    status = CharField(default="open")
    created_at = DateTimeField(default=datetime.datetime.now)
    operator_mode = CharField(default="off")
    operator_id = IntegerField(default=0)

    class Meta:
        database = db
        table_name = "chat_requests"
class ChatHistory(Model):
    id = PrimaryKeyField()
    user_id = IntegerField()
    role = CharField()
    message = TextField()
    request = ForeignKeyField(ChatRequest, backref="history")

    class Meta:
        database = db
        table_name = "chat_history"

class Operator(Model):
    id = PrimaryKeyField()
    login = CharField()
    password = CharField()
    is_admin = BooleanField(default=False)

    class Meta:
        database = db
        table_name = "operators"