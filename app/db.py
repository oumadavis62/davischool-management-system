"""DaviSchool database compatibility layer.

Production: uses Render-managed PostgreSQL when DATABASE_URL is present.
Development: falls back to the existing SQLite database.

The application was originally written against sqlite3. This module keeps
that DB-API surface while translating the small SQLite-specific SQL subset
used by DaviSchool to PostgreSQL, so existing routes can continue to use
con.execute(), con.cursor(), ?, row["field"], and row[0].
"""
from __future__ import annotations

import re
from typing import Any

import psycopg


class CompatRow(dict):
    """A row addressable by both column name and numeric position."""

    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    columns = [getattr(col, "name", col[0]) for col in (cursor.description or [])]

    def make_row(values):
        return CompatRow(columns, values)

    return make_row


def _replace_qmarks(sql: str) -> str:
    """Convert SQLite ? parameters to psycopg %s without touching quoted text."""
    out = []
    i = 0
    quote = None
    while i < len(sql):
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    out.append(sql[i + 1])
                    i += 1
                else:
                    quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def translate_sql(sql: str) -> str:
    q = _replace_qmarks(sql)

    # SQLite's INTEGER PRIMARY KEY is an auto-generated row id. BIGSERIAL
    # preserves that behavior in PostgreSQL for the existing application.
    q = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY(?:\s+AUTOINCREMENT)?\b",
        "BIGSERIAL PRIMARY KEY",
        q,
        flags=re.IGNORECASE,
    )

    # Make the additive schema upgrades idempotent on PostgreSQL.
    q = re.sub(
        r"\bALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS\b)",
        r"ALTER TABLE \1 ADD COLUMN IF NOT EXISTS ",
        q,
        flags=re.IGNORECASE,
    )

    # Common SQLite spelling occasionally used by older code.
    q = re.sub(
        r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+",
        "INSERT INTO ",
        q,
        flags=re.IGNORECASE,
    )
    if re.match(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", sql, flags=re.IGNORECASE):
        if "ON CONFLICT" not in q.upper():
            q = q.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    # PRAGMA statements are SQLite-only. They are not needed with PostgreSQL.
    if re.match(r"^\s*PRAGMA\b", q, flags=re.IGNORECASE):
        return "SELECT 1 AS pragma_ignored"
    return q


class CompatCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None

    def execute(self, sql, params=None):
        translated = translate_sql(sql)
        self._cursor.execute(translated, params)
        self._lastrowid = None
        if re.match(r"^\s*INSERT\b", translated, flags=re.IGNORECASE):
            try:
                self._cursor.execute("SELECT lastval()")
                row = self._cursor.fetchone()
                self._lastrowid = row[0] if row else None
            except Exception:
                # Not every INSERT uses a serial sequence.
                self._cursor.connection.rollback()
                # Re-run the original INSERT after the harmless lastval failure.
                self._cursor.execute(translated, params)
        return self

    def executemany(self, sql, seq_of_params):
        self._cursor.executemany(translate_sql(sql), seq_of_params)
        self._lastrowid = None
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchmany(self, size=1):
        return self._cursor.fetchmany(size)

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)

    @property
    def lastrowid(self):
        return self._lastrowid

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class CompatConnection:
    def __init__(self, database_url: str, **kwargs):
        self._conn = psycopg.connect(
            database_url,
            row_factory=_row_factory,
            connect_timeout=int(kwargs.pop("connect_timeout", 10)),
            **kwargs,
        )
        self._row_factory = None

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        # main.py assigns sqlite3.Row. PostgreSQL already uses our compatible
        # row factory, so retain the assignment only as metadata.
        self._row_factory = value

    def cursor(self):
        return CompatCursor(self._conn.cursor())

    def execute(self, sql, params=None):
        cur = CompatCursor(self._conn.cursor())
        return cur.execute(sql, params)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()
        finally:
            self._conn.close()
        return False

    def __getattr__(self, name):
        return getattr(self._conn, name)


def connect(database_url: str, **kwargs) -> CompatConnection:
    return CompatConnection(database_url, **kwargs)
