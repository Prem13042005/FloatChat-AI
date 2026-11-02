"""
scripts/setup_ai_role.py

Configures floatchat_ai_user in PostgreSQL with strict read-only permissions
on the FloatChat scientific database (floatchat_db) and zero access to floatchat_app.
Generates a secure password and registers POSTGRES_READONLY_USER and
POSTGRES_READONLY_PASSWORD into .env idempotently.
"""

import os
import secrets
import string
import psycopg2
from psycopg2 import sql

def generate_secure_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def load_existing_env(env_path: str) -> dict:
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip("'\"")
    return env_vars

def update_env_file(env_path: str, new_vars: dict):
    lines = []
    existing_keys = set()
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            trimmed = line.strip()
            if trimmed and not trimmed.startswith("#") and "=" in trimmed:
                k = trimmed.split("=", 1)[0].strip()
                existing_keys.add(k)

    # Append any missing new_vars
    appended = []
    for k, v in new_vars.items():
        if k not in existing_keys:
            appended.append(f"{k}={v}\n")
        else:
            # Update in place if exists
            new_lines = []
            for line in lines:
                trimmed = line.strip()
                if trimmed and not trimmed.startswith("#") and "=" in trimmed:
                    curr_k = trimmed.split("=", 1)[0].strip()
                    if curr_k == k:
                        new_lines.append(f"{k}={v}\n")
                        continue
                new_lines.append(line)
            lines = new_lines

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        if appended:
            if lines and not lines[-1].endswith("\n"):
                f.write("\n")
            f.write("\n# Dedicated Read-Only AI Role & Security Secrets (F11 Hardening)\n")
            f.writelines(appended)

def setup_role():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env_path = os.path.join(base_dir, ".env")
    env = load_existing_env(env_path)

    pg_host = env.get("POSTGRES_HOST", "localhost")
    pg_port = int(env.get("POSTGRES_PORT", "5433"))
    pg_admin_user = env.get("POSTGRES_USER", "floatchat_user")
    pg_admin_pass = env.get("POSTGRES_PASSWORD", "floatchat_password")
    pg_db = env.get("POSTGRES_DB", "floatchat_db")

    ai_user = "floatchat_ai_user"
    ai_password = env.get("POSTGRES_READONLY_PASSWORD") or generate_secure_password()
    internal_secret = env.get("FLOATCHAT_INTERNAL_SECRET") or generate_secure_password(48)
    jwt_secret = env.get("JWT_SECRET") or generate_secure_password(64)

    # 1. Connect to floatchat_db as admin
    conn = psycopg2.connect(
        host=pg_host,
        port=pg_port,
        dbname=pg_db,
        user=pg_admin_user,
        password=pg_admin_pass,
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Check if role exists
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ai_user,))
    exists = cur.fetchone() is not None

    if not exists:
        cur.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;").format(
            sql.Identifier(ai_user)
        ), [ai_password])
        print(f"Created PostgreSQL role '{ai_user}' with LOGIN and zero admin privileges.")
    else:
        cur.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;").format(
            sql.Identifier(ai_user)
        ), [ai_password])
        print(f"Updated PostgreSQL role '{ai_user}'.")

    # Grant database connect and schema usage
    cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {};").format(
        sql.Identifier(pg_db),
        sql.Identifier(ai_user)
    ))
    cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {};").format(
        sql.Identifier(ai_user)
    ))

    # Grant SELECT only on scientific tables
    scientific_tables = ["argo_floats", "argo_profiles", "argo_measurements", "argo_doc_embeddings"]
    for tbl in scientific_tables:
        cur.execute(sql.SQL("GRANT SELECT ON TABLE {} TO {};").format(
            sql.Identifier(tbl),
            sql.Identifier(ai_user)
        ))
        cur.execute(sql.SQL("REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE {} FROM {};").format(
            sql.Identifier(tbl),
            sql.Identifier(ai_user)
        ))

    # Revoke default permissions on future tables
    cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {};").format(
        sql.Identifier(ai_user)
    ))
    cur.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {};").format(
        sql.Identifier(ai_user)
    ))

    # Explicitly revoke connect on floatchat_app
    try:
        cur.execute("REVOKE CONNECT ON DATABASE floatchat_app FROM PUBLIC;")
        cur.execute("GRANT CONNECT ON DATABASE floatchat_app TO floatchat_app_user;")
        cur.execute("GRANT CONNECT ON DATABASE floatchat_app TO floatchat_user;")
        cur.execute(sql.SQL("REVOKE CONNECT ON DATABASE floatchat_app FROM {};").format(
            sql.Identifier(ai_user)
        ))
        cur.execute(sql.SQL("REVOKE ALL ON DATABASE floatchat_app FROM {};").format(
            sql.Identifier(ai_user)
        ))
    except Exception as e:
        print(f"Notice on floatchat_app revoke: {e}")

    conn.close()

    # 2. Update .env
    env_updates = {
        "POSTGRES_READONLY_USER": ai_user,
        "POSTGRES_READONLY_PASSWORD": ai_password,
        "FLOATCHAT_INTERNAL_SECRET": internal_secret,
        "JWT_SECRET": jwt_secret,
    }
    update_env_file(env_path, env_updates)
    print("Updated .env with POSTGRES_READONLY_USER, FLOATCHAT_INTERNAL_SECRET, and JWT_SECRET.")

    # 3. Test verification as floatchat_ai_user
    test_conn = psycopg2.connect(
        host=pg_host,
        port=pg_port,
        dbname=pg_db,
        user=ai_user,
        password=ai_password,
    )
    test_cur = test_conn.cursor()
    test_cur.execute("SELECT COUNT(*) FROM argo_floats;")
    count = test_cur.fetchone()[0]
    print(f"Verification: floatchat_ai_user can SELECT argo_floats (count = {count}).")

    # Verify write rejection
    write_blocked = False
    try:
        test_cur.execute("INSERT INTO argo_floats (platform_number) VALUES ('test_fail');")
        test_conn.commit()
    except psycopg2.errors.InsufficientPrivilege:
        test_conn.rollback()
        write_blocked = True
        print("Verification: floatchat_ai_user INSERT was correctly rejected by PostgreSQL (InsufficientPrivilege).")

    test_conn.close()

    # Verify connection rejection to floatchat_app
    app_blocked = False
    try:
        psycopg2.connect(
            host=pg_host,
            port=pg_port,
            dbname="floatchat_app",
            user=ai_user,
            password=ai_password,
        )
    except psycopg2.OperationalError as e:
        app_blocked = True
        print("Verification: floatchat_ai_user connection to floatchat_app correctly blocked by PostgreSQL.")

    if count > 0 and write_blocked and app_blocked:
        print("SUCCESS: floatchat_ai_user role fully configured and verified.")
    else:
        print("WARNING: floatchat_ai_user verification had unexpected outcomes.")

if __name__ == "__main__":
    setup_role()
