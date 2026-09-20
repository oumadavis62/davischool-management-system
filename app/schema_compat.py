"""Small additive schema migrations for existing DaviSchool databases.

The application historically used SQLite and Render may already contain a
PostgreSQL database created from an older schema.  CREATE TABLE IF NOT EXISTS
does not add columns to an existing table, so these migrations keep old
databases compatible without deleting existing records.
"""
from __future__ import annotations


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
    }

    for table, columns in migrations.items():
        for column, definition in columns.items():
            cur.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
            )

    con.commit()
