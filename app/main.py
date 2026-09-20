from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse, FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import sqlite3
import os
import hashlib
import hmac
import base64
import secrets
import re
from starlette.middleware.sessions import SessionMiddleware
import random
from datetime import datetime
from zoneinfo import ZoneInfo

app = FastAPI()
SECRET_KEY = os.environ.get("DAVISCHOOL_SECRET_KEY") or "dev-only-change-this-secret"
SESSION_HTTPS_ONLY = os.environ.get("DAVISCHOOL_HTTPS_ONLY", "0").lower() in {"1", "true", "yes"}
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=SESSION_HTTPS_ONLY, same_site="lax", max_age=60*60*12)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if SESSION_HTTPS_ONLY:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
SUPER_ADMIN = os.environ.get("DAVISCHOOL_SUPER_ADMIN", "admin@davischool.com")
SUPER_ADMIN_PASSWORD = os.environ.get("DAVISCHOOL_SUPER_ADMIN_PASSWORD", "DaviSchool@2026!")
DB_PATH = os.environ.get("DAVISCHOOL_DB_PATH", "davischool.db")

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310000

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    if not stored:
        return False, False
    if not stored.startswith(PASSWORD_SCHEME + "$"):
        return hmac.compare_digest(password, stored), True
    try:
        _, iterations, salt_b64, digest_b64 = stored.split("$", 3)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected), False
    except (ValueError, TypeError):
        return False, False

def get_db():
    # Render can run multiple application workers against the same SQLite
    # database. Give writes a reasonable wait window and enable WAL so a
    # verification request is not rejected simply because another worker
    # briefly has the database open.
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
    return con

def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, assessment_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_phone TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT, initial TEXT)")