"""Database Connection Helper."""

import os
import psycopg2


def get_connection():
    # إذا وُجد رابط قاعدة البيانات من بيئة دوكر يستخدمه، وإلا يفترض الإعدادات المحلية
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)

    # إعدادات افتراضية ذكية: إذا كنا داخل الحاوية نستخدم db وإذا على الويندوز نستخدم localhost
    host = os.getenv("DB_HOST", "db")
    user = os.getenv("DB_USER", "grocery_user")
    password = os.getenv("DB_PASSWORD", "grocery_password")
    dbname = os.getenv("DB_NAME", "tracker_db")
    port = os.getenv("DB_PORT", "5432")

    return psycopg2.connect(
        host=host,
        user=user,
        password=password,
        dbname=dbname,
        port=port,
    )