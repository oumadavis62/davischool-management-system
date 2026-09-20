"""DaviSchool package bootstrap.

When Render provides DATABASE_URL, transparently route the legacy sqlite3
connection calls in app.main to the PostgreSQL compatibility layer. Local
development continues to use normal SQLite.
"""
import os

if os.environ.get("DATABASE_URL"):
    import sqlite3
    from .db import connect as _postgres_connect

    def _connect(database, *args, **kwargs):
        return _postgres_connect(
            os.environ["DATABASE_URL"],
            connect_timeout=kwargs.pop("connect_timeout", 10),
        )

    sqlite3.connect = _connect
