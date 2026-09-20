"""DaviSchool package bootstrap.

Render production must use managed PostgreSQL. Local development continues
to use SQLite when DATABASE_URL is absent.
"""
import os

DATABASE_URL = os.environ.get("DATABASE_URL")

# Never silently fall back to an ephemeral SQLite database on Render.
if os.environ.get("RENDER") and not DATABASE_URL:
    raise RuntimeError(
        "DaviSchool production database is not configured. "
        "DATABASE_URL must be supplied by the Render PostgreSQL service."
    )

if DATABASE_URL:
    import sqlite3
    from .db import connect as _postgres_connect

    def _connect(database, *args, **kwargs):
        return _postgres_connect(
            DATABASE_URL,
            connect_timeout=kwargs.pop("connect_timeout", 10),
        )

    sqlite3.connect = _connect
