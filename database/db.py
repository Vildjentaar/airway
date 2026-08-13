from __future__ import annotations

import os

from mysql.connector import pooling
from dotenv import load_dotenv

load_dotenv()

pool = pooling.MySQLConnectionPool(
    pool_name="thall_pool",
    pool_size=5,
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    database=os.getenv("MYSQL_DATABASE", "thall_lines"),
    user=os.getenv("MYSQL_USER", "thall_app"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    charset="utf8mb4",
    collation="utf8mb4_unicode_ci",
)


def get_connection():
    return pool.get_connection()


def fetch_one(query: str, params: tuple = ()) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params)
        return cursor.fetchone()
    finally:
        conn.close()


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()
