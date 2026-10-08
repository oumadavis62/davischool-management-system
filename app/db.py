"""DaviSchool database compatibility layer.

Production uses Render-managed PostgreSQL when DATABASE_URL is present.
Development falls back to the existing SQLite database.
"""
from __future__ import annotations

import re
import psycopg
from psycopg_pool import ConnectionPool


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
    columns = []
    for col in (cursor.description or []):
        columns.append(getattr(col, "name", None) or col[0])

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

    q = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY(?:\s+AUTOINCREMENT)?\b",
        "BIGSERIAL PRIMARY KEY",
        q,
        flags=re.IGNORECASE,
    )

    q = re.sub(
        r"\bALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS\b)",
        r"ALTER TABLE \1 ADD COLUMN IF NOT EXISTS ",
        q,
        flags=re.IGNORECASE,
    )

    if re.match(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", q, flags=re.IGNORECASE):
        q = re.sub(
            r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+",
            "INSERT INTO ",
            q,
            flags=re.IGNORECASE,
        )
        if "ON CONFLICT" not in q.upper():
            q = q.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    if re.match(r"^\s*PRAGMA\b", q, flags=re.IGNORECASE):
        return "SELECT 1 AS pragma_ignored"

    return q


class CompatCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None
        self._pending_row = None

    def execute(self, sql, params=None):
        translated = translate_sql(sql)
        # The legacy application uses sqlite3.Cursor.lastrowid after INSERTs.
        # PostgreSQL has no DB-API lastrowid, so request the generated id from
        # the same INSERT statement without changing application behavior.
        if re.match(r"^\s*INSERT\b", translated, flags=re.IGNORECASE) and re.search(r"\bRETURNING\b", translated, flags=re.IGNORECASE) is None:
            candidate = translated.rstrip().rstrip(";")
            # Some additive/private tables intentionally have no id column.
            # Never append PostgreSQL's RETURNING id to those inserts.
            table_match = re.search(
                r"\bINTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                candidate,
                flags=re.IGNORECASE,
            )
            if table_match and table_match.group(1).lower() not in {"teacher_mark_drafts", "academic_locks", "system_audit"}:
                translated = candidate + " RETURNING id"
        self._cursor.execute(translated, params)
        self._lastrowid = None
        self._pending_row = None
        if translated != translate_sql(sql) and re.search(r"\bRETURNING\s+id\s*$", translated, flags=re.IGNORECASE):
            self._pending_row = self._cursor.fetchone()
            if self._pending_row:
                self._lastrowid = self._pending_row[0]
        return self

    def executemany(self, sql, seq_of_params):
        self._cursor.executemany(translate_sql(sql), seq_of_params)
        self._lastrowid = None
        self._pending_row = None
        return self

    def fetchone(self):
        if self._pending_row is not None:
            row = self._pending_row
            self._pending_row = None
            return row
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


_pools = {}

def _get_pool(database_url: str, connect_timeout: int = 10) -> ConnectionPool:
    """Return one process-local PostgreSQL connection pool."""
    key = database_url.strip()
    pool = _pools.get(key)
    if pool is None:
        pool = ConnectionPool(
            conninfo=key,
            min_size=1,
            max_size=8,
            timeout=connect_timeout,
            max_idle=300,
            kwargs={"row_factory": _row_factory, "connect_timeout": connect_timeout},
            open=True,
        )
        _pools[key] = pool
    return pool


class CompatConnection:
    def __init__(self, database_url: str, **kwargs):
        connect_timeout = int(kwargs.pop("connect_timeout", 10))
        self._pool = _get_pool(database_url, connect_timeout=connect_timeout)
        self._conn = self._pool.getconn(timeout=connect_timeout)
        self._row_factory = None
        self._returned = False

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        # main.py assigns sqlite3.Row. PostgreSQL already uses CompatRow.
        self._row_factory = value

    def cursor(self):
        return CompatCursor(self._conn.cursor())

    def execute(self, sql, params=None):
        return CompatCursor(self._conn.cursor()).execute(sql, params)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        if self._returned:
            return None
        self._returned = True
        try:
            if not self._conn.closed:
                self._conn.rollback()
        finally:
            self._pool.putconn(self._conn)
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()
        finally:
            self.close()
        return False

    def __getattr__(self, name):
        return getattr(self._conn, name)

def connect(database_url: str, **kwargs) -> CompatConnection:
    return CompatConnection(database_url, **kwargs)
