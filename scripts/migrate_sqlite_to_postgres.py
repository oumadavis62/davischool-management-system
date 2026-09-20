#!/usr/bin/env python3
"""One-time SQLite -> PostgreSQL migration for DaviSchool."""
from __future__ import annotations

import os
import re
import sqlite3
import psycopg


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def normalize_create_sql(sql: str) -> str:
    sql = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY(?:\s+AUTOINCREMENT)?\b",
        "BIGSERIAL PRIMARY KEY",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"\bAUTOINCREMENT\b", "", sql, flags=re.IGNORECASE)
    return sql


def main():
    sqlite_path = os.environ.get("SQLITE_PATH", "davischool.db")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    if not os.path.exists(sqlite_path):
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    dst = psycopg.connect(database_url)
    try:
        tables = src.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

        for table in tables:
            name = table["name"]
            if table["sql"]:
                dst.execute(normalize_create_sql(table["sql"]))
        dst.commit()

        for table in tables:
            name = table["name"]
            src_cols = [r["name"] for r in src.execute(f"PRAGMA table_info({qident(name)})")]
            dst_cols = [
                r[0] for r in dst.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                    (name,),
                ).fetchall()
            ]
            cols = [c for c in src_cols if c in dst_cols]
            if not cols:
                continue
            col_sql = ", ".join(qident(c) for c in cols)
            placeholders = ", ".join(["%s"] * len(cols))
            insert_sql = f"INSERT INTO {qident(name)} ({col_sql}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            rows = src.execute(
                f"SELECT {', '.join(qident(c) for c in cols)} FROM {qident(name)}"
            ).fetchall()
            for row in rows:
                dst.execute(insert_sql, tuple(row[c] for c in cols))
            dst.commit()
            print(f"Migrated {len(rows)} rows: {name}")

        id_tables = dst.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema='public' AND column_name='id'"
        ).fetchall()
        for (name,) in id_tables:
            seq = dst.execute("SELECT pg_get_serial_sequence(%s, 'id')", (name,)).fetchone()[0]
            if not seq:
                continue
            max_id = dst.execute(f"SELECT MAX(id) FROM {qident(name)}").fetchone()[0]
            if max_id is not None:
                dst.execute("SELECT setval(%s::regclass, %s, true)", (seq, int(max_id)))
        dst.commit()
        print("SQLite -> PostgreSQL migration completed successfully.")
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()
