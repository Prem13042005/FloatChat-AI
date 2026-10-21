#!/usr/bin/env python3
"""
scripts/setup_db_local.py

Helper script to initialize PostgreSQL database `floatchat_db`, user `floatchat_user`,
and apply `scripts/init-db.sql` DDL to local PostgreSQL instance.
"""

import os
import psycopg2

def setup_local_database():
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = int(os.getenv("POSTGRES_PORT", 5432))
    db_name = os.getenv("POSTGRES_DB", "floatchat_db")
    db_user = os.getenv("POSTGRES_USER", "floatchat_user")
    db_password = os.getenv("POSTGRES_PASSWORD", "floatchat_password")
    admin_user = os.getenv("POSTGRES_ADMIN_USER", "postgres")

    print(f"Connecting to PostgreSQL server at {host}:{port} as admin '{admin_user}'...")
    conn = psycopg2.connect(host=host, port=port, dbname="postgres", user=admin_user)
    conn.autocommit = True
    cur = conn.cursor()

    # Create database if missing
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s;", (db_name,))
    if not cur.fetchone():
        cur.execute(f"CREATE DATABASE {db_name};")
        print(f"Database '{db_name}' created.")
    else:
        print(f"Database '{db_name}' already exists.")

    # Create user if missing
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s;", (db_user,))
    if not cur.fetchone():
        cur.execute(f"CREATE USER {db_user} WITH PASSWORD '{db_password}';")
        print(f"User '{db_user}' created.")
    else:
        print(f"User '{db_user}' already exists.")

    cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};")

    cur.close()
    conn.close()

    # Apply init-db.sql DDL
    print(f"Connecting to target database '{db_name}' to apply schema DDL...")
    conn_target = psycopg2.connect(host=host, port=port, dbname=db_name, user=admin_user)
    conn_target.autocommit = True
    cur_target = conn_target.cursor()

    init_sql_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "init-db.sql"))
    with open(init_sql_path, "r", encoding="utf-8") as f:
        ddl_sql = f.read()

    cur_target.execute(ddl_sql)
    cur_target.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {db_user};")
    cur_target.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {db_user};")
    print("Schema DDL, extensions, and grants applied successfully!")

    cur_target.close()
    conn_target.close()

if __name__ == "__main__":
    setup_local_database()
