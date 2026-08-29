import os
import mysql.connector
from dotenv import load_dotenv

# Load the Aiven credentials from .env
load_dotenv()

def migrate():
    print("Connecting to Aiven Database...")
    try:
        conn = mysql.connector.connect(
            host=os.environ.get("MYSQL_HOST"),
            port=int(os.environ.get("MYSQL_PORT", 3306)),
            database=os.environ.get("MYSQL_DATABASE"),
            user=os.environ.get("MYSQL_USER"),
            password=os.environ.get("MYSQL_PASSWORD"),
            # Aiven requires SSL for connection
            ssl_ca="", 
            ssl_disabled=False
        )
        print("Successfully connected!")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    cursor = conn.cursor()

    scripts = ['mysql/init/01-schema.sql', 'mysql/init/02-ancillary.sql']

    for script_path in scripts:
        print(f"\nExecuting {script_path}...")
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                sql_script = f.read()

            # Execute each statement separated by semicolon
            for statement in sql_script.split(';'):
                stmt = statement.strip()
                if stmt:
                    cursor.execute(stmt)
            print(f"Successfully executed {script_path}!")
        except Exception as e:
            print(f"Error executing {script_path}: {e}")

    conn.commit()
    cursor.close()
    conn.close()
    print("\nMigration Complete! Your Aiven database is ready.")

if __name__ == "__main__":
    migrate()
