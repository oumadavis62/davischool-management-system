"""DaviSchool database compatibility layer.

Production uses Render-managed PostgreSQL when DATABASE_URL is present.
Development falls back to the existing SQLite database.
"""
from __future__ import annotations

import re
import os
import threading
import atexit
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

    pragma_table_info = re.match(
        r"^\s*PRAGMA\s+table_info\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*;?\s*$",
        q,
        flags=re.IGNORECASE,
    )
    if pragma_table_info:
        table_name = pragma_table_info.group(1)
        return (
            "SELECT ordinal_position - 1 AS cid, column_name AS name, "
            "data_type AS type, 0 AS notnull, NULL AS dflt_value, "
            "0 AS pk FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='%s' "
            "ORDER BY ordinal_position" % table_name.lower()
        )

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
            if table_match and table_match.group(1).lower() not in {"teacher_mark_drafts", "academic_locks", "system_audit", "exam_class_participation", "student_promotion_cohort_snapshots", "student_promotion_cohort_members", "parent_student_links", "parent_access_credentials", "ds_fin_accounts", "admission_number_settings", "ds_fin_periods", "ds_fin_reversals"}:
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
_database_guard_lock = threading.Lock()
_database_guard_checked = set()


def _allow_empty_database() -> bool:
    return os.environ.get("DAVISCHOOL_ALLOW_EMPTY_DATABASE", "0").strip().lower() in {"1", "true", "yes"}


def _verify_database_persistence(conn, database_url: str) -> None:
    """Refuse to run against an empty/uninitialized production database by accident.

    A deployment must never silently switch to a new empty PostgreSQL database.
    Existing DaviSchool databases contain the core tables and at least one account
    or school. A genuinely new database can still be initialized explicitly by
    setting DAVISCHOOL_ALLOW_EMPTY_DATABASE=1 for that deployment.
    """
    key = database_url.strip()
    if key in _database_guard_checked:
        return
    with _database_guard_lock:
        if key in _database_guard_checked:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT table_name
                   FROM information_schema.tables
                   WHERE table_schema='public'
                     AND table_name IN ('users','schools','students','teachers')"""
            )
            tables = {str(row[0]) for row in cur.fetchall()}
            required = {"users", "schools", "students", "teachers"}
            if required.issubset(tables):
                cur.execute("SELECT COUNT(*) FROM users")
                user_count = int(cur.fetchone()[0] or 0)
                cur.execute("SELECT COUNT(*) FROM schools")
                school_count = int(cur.fetchone()[0] or 0)
                if user_count > 0 or school_count > 0:
                    _database_guard_checked.add(key)
                    return
            if _allow_empty_database():
                _database_guard_checked.add(key)
                return
            raise RuntimeError(
                "DaviSchool database persistence guard blocked startup: the configured PostgreSQL database "
                "does not contain the expected existing DaviSchool data. Refusing to initialize a possibly "
                "wrong or empty database. Set DAVISCHOOL_ALLOW_EMPTY_DATABASE=1 only when intentionally "
                "provisioning a brand-new DaviSchool database."
            )
        finally:
            cur.close()


def _pool_size(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read safe connection-pool sizing from the hosting environment."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _get_pool(database_url: str, connect_timeout: int = 10) -> ConnectionPool:
    """Return one process-local PostgreSQL connection pool.

    Keep a few connections warm for quick page loads and allow additional
    concurrent requests to obtain a connection without queuing behind a
    small fixed pool. The limits are configurable for hosts with tighter
    database connection quotas.
    """
    key = database_url.strip()
    with _database_guard_lock:
        pool = _pools.get(key)
        if pool is None:
            # Supabase session-mode poolers commonly expose only 15 client
            # connections to the whole project. This pool is per process, so
            # a large per-process default can exhaust that shared limit when
            # the host runs multiple workers or instances.
            min_size = _pool_size("DAVISCHOOL_DB_POOL_MIN", 1, 1, 1)
            # Supabase shared session-mode poolers have a small per-project
            # client limit (15 in the affected deployment). This pool is
            # process-local, so each worker/replica multiplies the limit.
            # Keep one warm connection and permit at most one additional
            # concurrent DB request per process; do not let env overrides
            # accidentally exhaust the shared Supavisor session quota.
            max_size = _pool_size("DAVISCHOOL_DB_POOL_MAX", 2, min_size, 2)
            pool = ConnectionPool(
                conninfo=key,
                min_size=min_size,
                max_size=max_size,
                timeout=connect_timeout,
                max_idle=30,
                kwargs={
                    "row_factory": _row_factory,
                    "connect_timeout": connect_timeout,
                    "application_name": "DaviSchool",
                },
                open=True,
            )
            _pools[key] = pool
    return pool


class CompatConnection:
    def __init__(self, database_url: str, **kwargs):
        # Initialize every attribute used by cleanup before acquiring a pool or
        # connection. Python may call __del__ on an object whose __init__ failed.
        object.__setattr__(self, "_pool", None)
        object.__setattr__(self, "_conn", None)
        object.__setattr__(self, "_row_factory", None)
        object.__setattr__(self, "_returned", True)

        connect_timeout = int(kwargs.pop("connect_timeout", 10))
        pool = _get_pool(database_url, connect_timeout=connect_timeout)
        object.__setattr__(self, "_pool", pool)

        conn = pool.getconn(timeout=connect_timeout)
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_returned", False)
        try:
            _verify_database_persistence(conn, database_url)
        except BaseException:
            # Mark returned before cleanup so a partially initialized object's
            # finalizer cannot attempt to return this connection a second time.
            object.__setattr__(self, "_returned", True)
            object.__setattr__(self, "_conn", None)
            try:
                pool.putconn(conn)
            except Exception as cleanup_exc:
                try:
                    print(
                        "DAVISCHOOL_DB_INIT_CONNECTION_RETURN_WARNING:",
                        type(cleanup_exc).__name__,
                        flush=True,
                    )
                except Exception:
                    pass
            raise

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
        # Read internal attributes without invoking __getattr__; this method
        # must also be safe when called during interpreter shutdown.
        try:
            returned = object.__getattribute__(self, "_returned")
        except AttributeError:
            return None
        if returned:
            return None

        object.__setattr__(self, "_returned", True)
        try:
            conn = object.__getattribute__(self, "_conn")
            pool = object.__getattribute__(self, "_pool")
        except AttributeError:
            return None
        if conn is None or pool is None:
            return None

        try:
            if not conn.closed:
                conn.rollback()
        finally:
            # psycopg_pool discards broken connections rather than putting
            # them back into circulation.
            pool.putconn(conn)
        return None

    def __del__(self):
        # Finalizers can run for objects whose __init__ failed. Never use
        # getattr(self, ...) here: missing attributes would recurse through
        # __getattr__ and can cause RecursionError during DNS/connect failures.
        try:
            try:
                returned = object.__getattribute__(self, "_returned")
                conn = object.__getattribute__(self, "_conn")
                pool = object.__getattribute__(self, "_pool")
            except AttributeError:
                return
            if returned or conn is None or pool is None:
                return
            self.close()
        except Exception as exc:
            # Finalizers must never raise, especially during interpreter shutdown.
            try:
                print(
                    "DAVISCHOOL_DB_CONNECTION_FINALIZER_WARNING:",
                    type(exc).__name__,
                    flush=True,
                )
            except Exception:
                pass

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
        # object.__getattribute__ bypasses this method and therefore cannot
        # recurse when _conn has not yet been assigned during failed startup.
        try:
            conn = object.__getattribute__(self, "_conn")
        except AttributeError:
            raise AttributeError(name) from None
        if conn is None:
            raise AttributeError(name)
        return getattr(conn, name)

def close_pools() -> None:
    """Close process-local PostgreSQL pools before interpreter finalization."""
    with _database_guard_lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        try:
            # Explicit close stops the pool's worker threads while Python can
            # still join them, avoiding ConnectionPool.__del__ at finalization.
            pool.close(timeout=5.0)
        except TypeError:
            try:
                pool.close()
            except Exception as exc:
                print("DAVISCHOOL_DB_POOL_CLOSE_WARNING:", repr(exc), flush=True)
        except Exception as exc:
            print("DAVISCHOOL_DB_POOL_CLOSE_WARNING:", repr(exc), flush=True)


atexit.register(close_pools)


def connect(database_url: str, **kwargs) -> CompatConnection:
    return CompatConnection(database_url, **kwargs)
