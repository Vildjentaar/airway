import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

def get_secret(key, default):
    return os.environ.get(key, default)

conn = mysql.connector.connect(
    host=get_secret("MYSQL_HOST", "127.0.0.1"),
    port=int(get_secret("MYSQL_PORT", "3306")),
    database=get_secret("MYSQL_DATABASE", "thall_lines"),
    user=get_secret("MYSQL_USER", "thall_app"),
    password=get_secret("MYSQL_PASSWORD", ""),
    charset="utf8mb4",
    collation="utf8mb4_unicode_ci",
    autocommit=True,
)

with open('mysql/init/02-ancillary.sql', 'r', encoding='utf-8') as f:
    sql_script = f.read()

cursor = conn.cursor()
for statement in sql_script.split(';'):
    stmt = statement.strip()
    if stmt:
        cursor.execute(stmt)

cursor.close()
conn.close()
print("Executed 02-ancillary.sql successfully.")
