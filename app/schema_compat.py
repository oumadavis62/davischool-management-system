"""Small additive schema migrations for existing DaviSchool databases.

The application historically used SQLite and Render may already contain a
PostgreSQL database created from an older schema.  CREATE TABLE IF NOT EXISTS
does not add columns to an existing table, so these migrations keep old
databases compatible without deleting existing records.
"""
from __future__ import annotations

import os

def _ensure_live_postgres_schema():
    """Apply additive migrations to Render PostgreSQL when DATABASE_URL is present."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return
    try:
        import psycopg
    except Exception:
        return

    migrations = {
        "users": {
            "email": "TEXT", "password": "TEXT", "role": "TEXT",
            "full_name": "TEXT", "school_id": "INTEGER",
            "student_id": "INTEGER", "teacher_id": "INTEGER",
        },
        "schools": {
            "name": "TEXT", "email": "TEXT", "code": "TEXT",
            "location": "TEXT", "phone": "TEXT", "principal": "TEXT",
            "school_type": "TEXT",
        },
        "pending_schools": {
            "name": "TEXT", "email": "TEXT", "location": "TEXT",
            "phone": "TEXT", "principal": "TEXT", "school_type": "TEXT",
            "auth_code": "TEXT", "timestamp": "TEXT",
        },
        "system_audit": {
            "school_id": "INTEGER", "user_email": "TEXT", "action": "TEXT",
            "details": "TEXT", "timestamp": "TEXT",
        },
    }

    with psycopg.connect(database_url) as pg:
        with pg.cursor() as cur:
            for table, columns in migrations.items():
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s",
                    (table,),
                )
                existing = {row[0] for row in cur.fetchall()}
                for column, definition in columns.items():
                    if column not in existing:
                        cur.execute(
                            f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
                        )
        pg.commit()



def ensure_schema_compatibility(con):
    cur = con.cursor()

    migrations = {
        "users": {
            "email": "TEXT",
            "password": "TEXT",
            "role": "TEXT",
            "full_name": "TEXT",
            "school_id": "INTEGER",
            "student_id": "INTEGER",
            "teacher_id": "INTEGER",
        },
        "schools": {
            "name": "TEXT",
            "email": "TEXT",
            "code": "TEXT",
            "location": "TEXT",
            "phone": "TEXT",
            "principal": "TEXT",
            "school_type": "TEXT",
        },
        "pending_schools": {
            "name": "TEXT",
            "email": "TEXT",
            "location": "TEXT",
            "phone": "TEXT",
            "principal": "TEXT",
            "school_type": "TEXT",
            "auth_code": "TEXT",
            "timestamp": "TEXT",
        },
        "system_audit": {
            "school_id": "INTEGER",
            "user_email": "TEXT",
            "action": "TEXT",
            "details": "TEXT",
            "timestamp": "TEXT",
        },
    }

    for table, columns in migrations.items():
        for column, definition in columns.items():
            try:
                cur.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
                )
            except Exception:
                # SQLite does not support IF NOT EXISTS on ADD COLUMN.
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                except Exception:
                    pass

    con.commit()

    # Keep the live Render PostgreSQL schema compatible with older deployments.
    try:
        _ensure_live_postgres_schema()
    except Exception as exc:
        print("DAVISCHOOL POSTGRES SCHEMA MIGRATION ERROR:", repr(exc), flush=True)
