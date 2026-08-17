from __future__ import annotations

import os

from mysql.connector import pooling
from dotenv import load_dotenv

load_dotenv()

import streamlit as st

_pool = None

def get_connection():
    global _pool
    if _pool is None:
        def get_secret(key, default):
            if key in os.environ:
                return os.environ[key]
            try:
                if key in st.secrets:
                    return st.secrets[key]
            except FileNotFoundError:
                pass
            return default

        _pool = pooling.MySQLConnectionPool(
            pool_name="thall_pool",
            pool_size=32,
            host=get_secret("MYSQL_HOST", "127.0.0.1"),
            port=int(get_secret("MYSQL_PORT", "3306")),
            database=get_secret("MYSQL_DATABASE", "thall_lines"),
            user=get_secret("MYSQL_USER", "thall_app"),
            password=get_secret("MYSQL_PASSWORD", ""),
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
        )
    return _pool.get_connection()


def fetch_one(query: str, params: tuple = ()) -> dict | None:
    conn = get_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params)
        return cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        conn.close()


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        conn.close()
