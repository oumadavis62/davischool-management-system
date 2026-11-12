from fastapi import FastAPI, Request, Form
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse, FileResponse
from html import escape
from urllib.parse import quote
from starlette.exceptions import HTTPException as StarletteHTTPException
import sqlite3
import os
import hashlib
import hmac
import base64
import json
import secrets
import re
import traceback
import smtplib
import ssl
from email.message import EmailMessage
import threading
import time
from app.tab_session import DaviSchoolTabSessionMiddleware
import random
from datetime import datetime, timedelta
from app.schema_compat import ensure_schema_compatibility
from app.timetable.schema import ensure_timetable_schema
from app.timetable.routes import register_timetable_setup_routes
from app.timetable.builder_routes import register_timetable_builder_routes
from app.timetable.generator_routes import register_timetable_generator_routes
from app.timetable.views_routes import register_timetable_view_routes
from app.timetable.export_routes import register_timetable_export_routes
from app.timetable.publishing_routes import register_timetable_publishing_routes
from app.timetable.portal_routes import register_timetable_portal_routes
from app.db import RequestDatabaseConnectionMiddleware, acquire_schema_migration_lock
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet, InvalidToken

BUILD_COMMIT = "students-save-role-fix-2026-10-04"

TEACHER_TIMETABLE_PALETTE = ["#DC2626","#2563EB","#16A34A","#9333EA","#EA580C","#0891B2","#BE185D","#4F46E5","#65A30D","#C2410C","#0F766E","#7C3AED"]
def _teacher_timetable_color(teacher_id):
    try:
        return TEACHER_TIMETABLE_PALETTE[(int(teacher_id)-1) % len(TEACHER_TIMETABLE_PALETTE)]
    except Exception:
        return TEACHER_TIMETABLE_PALETTE[0]

app = FastAPI()
# Compress larger responses to reduce transfer time on mobile connections.
app.add_middleware(GZipMiddleware, minimum_size=700)
# Ensure pooled PostgreSQL connections are returned even when a legacy route
# raises before reaching its own con.close() statement.
app.add_middleware(RequestDatabaseConnectionMiddleware)

# Render/Uvicorn must be able to bind the HTTP port even when PostgreSQL
# migrations take time. Database initialization therefore runs in a background
# thread instead of blocking the ASGI startup/lifespan phase.
DB_INIT_READY = False
DB_INIT_ERROR = None
DB_INIT_THREAD = None

def _repair_recreated_subject_references():
    """Safely reconnect records when a subject was deleted and recreated with the same name.

    This only repairs an orphan subject_id when the audit trail proves that the
    same subject name was deleted and subsequently recreated, and there is
    exactly one orphan subject id and one current subject with that name.
    Existing marks/records are not recreated or altered beyond their subject_id.
    """
    con = get_db()
    cur = con.cursor()
    try:
        tables = (
            "marks",
            "teacher_allocations",
            "subject_grading_rules",
            "subject_performance_comments",
            "academic_locks",
            "set_marks_config",
            "teacher_mark_drafts",
            "marks_correction_requests",
            "assessment_scores",
            "assessments",
        )

        # Find schools/names for which the audit trail records a deletion followed
        # by a creation of the same subject name.
        audit_rows = cur.execute(
            """SELECT school_id, details, MAX(timestamp) AS deleted_at
               FROM system_audit
               WHERE action='SUBJECT_DELETE' AND trim(COALESCE(details,''))<>''
               GROUP BY school_id, details"""
        ).fetchall()

        for audit in audit_rows:
            school_id = int(audit["school_id"] or 0)
            subject_name = str(audit["details"] or "").strip()
            deleted_at = str(audit["deleted_at"] or "")
            if not school_id or not subject_name:
                continue

            recreated = cur.execute(
                """SELECT id FROM subjects
                   WHERE school_id=? AND lower(trim(name))=lower(trim(?))
                   ORDER BY id DESC LIMIT 2""",
                (school_id, subject_name),
            ).fetchall()
            if len(recreated) != 1:
                continue
            target_id = int(recreated[0]["id"])

            created_after = cur.execute(
                """SELECT 1 FROM system_audit
                   WHERE school_id=? AND action='SUBJECT_CREATE'
                     AND lower(trim(details))=lower(trim(?))
                     AND timestamp>=?
                   LIMIT 1""",
                (school_id, subject_name, deleted_at),
            ).fetchone()
            if not created_after:
                continue

            orphan_ids = set()
            for table in tables:
                try:
                    cur.execute("SAVEPOINT davischool_subject_orphan_scan")
                    rows = cur.execute(
                        "SELECT DISTINCT subject_id FROM %s "
                        "WHERE school_id=? AND subject_id IS NOT NULL "
                        "AND NOT EXISTS (SELECT 1 FROM subjects s WHERE s.id=%s.subject_id AND s.school_id=%s.school_id)"
                        % (table, table, table),
                        (school_id,),
                    ).fetchall()
                    cur.execute("RELEASE SAVEPOINT davischool_subject_orphan_scan")
                    orphan_ids.update(
                        int(row["subject_id"]) for row in rows
                        if row["subject_id"] is not None
                    )
                except Exception:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT davischool_subject_orphan_scan")
                        cur.execute("RELEASE SAVEPOINT davischool_subject_orphan_scan")
                    except Exception:
                        pass

            # Do not guess if more than one orphan subject could be involved.
            if len(orphan_ids) != 1:
                continue

            old_id = next(iter(orphan_ids))
            if old_id == target_id:
                continue

            for table in tables:
                try:
                    cur.execute("SAVEPOINT davischool_subject_repair")
                    cur.execute(
                        "UPDATE %s SET subject_id=? WHERE school_id=? AND subject_id=?"
                        % table,
                        (target_id, school_id, old_id),
                    )
                    cur.execute("RELEASE SAVEPOINT davischool_subject_repair")
                except Exception:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT davischool_subject_repair")
                        cur.execute("RELEASE SAVEPOINT davischool_subject_repair")
                    except Exception:
                        pass

            print(
                "DAVISCHOOL SUBJECT REFERENCE REPAIR: school=%s old_subject_id=%s new_subject_id=%s name=%r"
                % (school_id, old_id, target_id, subject_name),
                flush=True,
            )

        con.commit()
    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        print("DAVISCHOOL SUBJECT REFERENCE REPAIR WARNING:", repr(exc), flush=True)
    finally:
        con.close()


def _is_transient_database_startup_error(exc):
    message = (repr(exc) + " " + str(exc)).lower()
    transient_markers = (
        "pooltimeout",
        "temporary failure in name resolution",
        "could not translate host name",
        "name or service not known",
        "connection timed out",
        "connection refused",
        "network is unreachable",
        "server closed the connection unexpectedly",
        "connection reset by peer",
    )
    return any(marker in message for marker in transient_markers)


def _initialize_database_background():
    global DB_INIT_READY, DB_INIT_ERROR
    # Hosting DNS and managed-pooler connections can fail briefly during
    # replica startup. Retry transient connection failures so a short DNS
    # outage does not permanently leave this process with DB_INIT_READY=False.
    retry_delays = (5, 10, 20, 30, 30)
    for attempt in range(len(retry_delays) + 1):
        try:
            init_db()
            init_extended_db()
            # Timetable v2 owns a fresh ds_timetable_* schema; this is additive
            # and intentionally runs only after legacy timetable retirement.
            timetable_con = get_db()
            try:
                ensure_timetable_schema(timetable_con)
            finally:
                timetable_con.close()
            # Subject-reference repair is intentionally not run during every startup.
            # It is a one-time maintenance task and can scan many academic tables,
            # causing unnecessary startup/database load on production replicas.
            DB_INIT_READY = True
            DB_INIT_ERROR = None
            print("DAVISCHOOL DATABASE INITIALIZATION COMPLETE", flush=True)
            return
        except Exception as exc:
            DB_INIT_ERROR = repr(exc)
            if not _is_transient_database_startup_error(exc) or attempt >= len(retry_delays):
                print("DAVISCHOOL DATABASE INITIALIZATION FAILED:", DB_INIT_ERROR, flush=True)
                return
            delay = retry_delays[attempt]
            print(
                "DAVISCHOOL DATABASE INITIALIZATION RETRY %s/%s IN %ss: %s"
                % (attempt + 1, len(retry_delays), delay, DB_INIT_ERROR),
                flush=True,
            )
            time.sleep(delay)

@app.on_event("startup")
def _startup_database_initialization():
    # Do not let Render route login/dashboard requests while schema setup is
    # still running. Uvicorn completes startup only after this function returns,
    # so the service becomes ready only when the database is ready as well.
    print("DAVISCHOOL DATABASE INITIALIZATION STARTED", flush=True)
    _initialize_database_background()
    if not DB_INIT_READY:
        raise RuntimeError(
            "Mabale_ICT database initialization did not complete; refusing "
            "to serve requests against an unready database. "
            + str(DB_INIT_ERROR or "Unknown database initialization error")
        )
    # Start the durable timetable job consumer only after the production
    # database and timetable schema are ready. A worker startup problem must
    # not take down authentication or ordinary school operations.
    try:
        from app.timetable.generation_jobs import start_generation_worker
        start_generation_worker(get_db)
        print("DAVISCHOOL TIMETABLE BACKGROUND WORKER INITIALIZED", flush=True)
    except Exception:
        import logging
        logging.getLogger("davischool.timetable.jobs").exception(
            "Timetable background worker could not be initialized"
        )

def send_school_verification_email(recipient: str, school_name: str, auth_code: str) -> None:
    """Send a one-time school registration code; prefer Gmail HTTPS API on Render Free."""
    safe_school = escape(str(school_name or "your school"))
    message = EmailMessage()
    message["Subject"] = "Your Mabale_ICT registration verification code"
    message["To"] = recipient
    message.set_content(
        "Mabale_ICT school registration verification\n\n"
        f"Your verification code is: {auth_code}\n\n"
        "Enter this six-digit code on the Mabale_ICT Register School page to confirm "
        "the email address. If you did not request this, you can ignore this email.\n\n"
        "Mabale_ICT Support"
    )
    message.add_alternative(
        "<div style='font-family:Arial,sans-serif;color:#1f2937;max-width:560px;margin:auto'>"
        "<div style='background:#14532d;color:white;padding:18px;border-radius:12px 12px 0 0;font-size:20px;font-weight:800'>Mabale_ICT</div>"
        "<div style='padding:22px;border:1px solid #e5e7eb;border-radius:0 0 12px 12px'>"
        "<h2 style='color:#14532d'>Verify your school email</h2>"
        f"<p>Use the code below to confirm the administrator email for <b>{safe_school}</b>.</p>"
        f"<div style='font-size:32px;letter-spacing:9px;font-weight:900;text-align:center;background:#f0fdf4;color:#166534;padding:18px;border-radius:10px'>{escape(auth_code)}</div>"
        "<p>This code is for one-time registration verification. If you did not request it, ignore this message.</p>"
        "<p style='color:#64748b;font-size:12px'>Mabale_ICT · A modern platform for managing school operations securely.</p>"
        "</div></div>",
        subtype="html",
    )

    # Gmail API uses HTTPS (443), which works on Render Free. It requires an
    # OAuth refresh token; a Gmail App Password is only valid for SMTP.
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()
    gmail_sender = os.environ.get("GMAIL_SENDER_EMAIL", "").strip()
    gmail_values = (client_id, client_secret, refresh_token, gmail_sender)
    if any(gmail_values):
        if not all(gmail_values):
            raise RuntimeError(
                "Gmail API setup is incomplete. Configure GMAIL_CLIENT_ID, "
                "GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN and GMAIL_SENDER_EMAIL."
            )
        import json
        from urllib.parse import urlencode
        from urllib.request import Request as URLRequest, urlopen

        token_data = urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode("utf-8")
        token_request = URLRequest(
            "https://oauth2.googleapis.com/token",
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(token_request, timeout=20) as response:
                token_result = json.loads(response.read().decode("utf-8"))
            access_token = token_result.get("access_token")
            if not access_token:
                raise RuntimeError("Google did not return an access token.")
            message["From"] = gmail_sender
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
            gmail_request = URLRequest(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                data=json.dumps({"raw": raw_message}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(gmail_request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not result.get("id"):
                raise RuntimeError("Gmail API did not confirm message submission.")
            print("DAVISCHOOL SCHOOL VERIFICATION EMAIL ACCEPTED BY GMAIL API", flush=True)
            return
        except Exception as exc:
            # Do not log OAuth credentials, access tokens, or message contents.
            print("DAVISCHOOL GMAIL API SEND FAILED:", type(exc).__name__, str(exc)[:300], flush=True)
            raise RuntimeError("Gmail API could not send the verification email. Check OAuth setup and Gmail API access.") from exc

    # Legacy SMTP fallback remains available for paid hosts that permit SMTP.
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM_EMAIL", username).strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = os.environ.get("SMTP_USE_SSL", "0").strip().lower() in {"1", "true", "yes"}
    if not host or not username or not password or not sender:
        raise RuntimeError(
            "Configure Gmail API OAuth variables for Render Free, or SMTP_HOST, "
            "SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM_EMAIL on a host that permits SMTP."
        )
    message["From"] = sender
    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(username, password)
            server.send_message(message)


SECRET_KEY = os.environ.get("DAVISCHOOL_SECRET_KEY") or "dev-only-change-this-secret"
SESSION_HTTPS_ONLY = os.environ.get("DAVISCHOOL_HTTPS_ONLY", "0").lower() in {"1", "true", "yes"}




# Automatic inactivity protection. The configured inactivity timeout is
# 15 minutes. Keep a 15-minute floor so a stale/misconfigured deployment
# variable (for example, 60 seconds) cannot lock users out after one minute.
# Active users remain signed in because authenticated requests refresh activity.
try:
    IDLE_TIMEOUT_SECONDS = max(15 * 60, int(os.environ.get("DAVISCHOOL_IDLE_TIMEOUT_SECONDS", str(15 * 60))))
except (TypeError, ValueError):
    # A malformed environment value must not shorten the configured timeout.
    IDLE_TIMEOUT_SECONDS = 15 * 60

@app.middleware("http")
async def idle_session_timeout(request: Request, call_next):
    now = datetime.now().timestamp()
    session = request.session
    if session.get("email"):
        last_activity = session.get("_last_activity")
        try:
            last_activity = float(last_activity) if last_activity is not None else None
        except (TypeError, ValueError):
            last_activity = None
        if last_activity is not None and now - last_activity > IDLE_TIMEOUT_SECONDS:
            session.clear()
            return RedirectResponse("/", status_code=303)
        session["_last_activity"] = now
    response = await call_next(request)
    return response



@app.get("/healthz")
def healthz():
    """Render readiness check: HTTP is up, and the database initialization is complete."""
    if DB_INIT_ERROR:
        return JSONResponse(
            {"status": "error", "database": "initialization_failed", "detail": DB_INIT_ERROR},
            status_code=503,
        )
    if not DB_INIT_READY:
        return JSONResponse(
            {"status": "starting", "database": "initialization_in_progress"},
            status_code=503,
        )
    con = get_db()
    try:
        con.execute("SELECT 1").fetchone()
        return JSONResponse({"status": "ok", "database": "reachable", "build_commit": BUILD_COMMIT})
    finally:
        con.close()


@app.middleware("http")
async def same_origin_guard(request: Request, call_next):
    # Defense-in-depth CSRF protection for browser state-changing requests.
    # Requests without Origin/Referer are allowed for compatibility with
    # server-to-server clients and older integrations.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source = origin or referer
        if source:
            # Render terminates TLS at the proxy, so request.url.scheme can be
            # http internally while the browser correctly sends an https Origin.
            forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
            scheme = forwarded_proto or request.url.scheme
            expected = f"{scheme}://{request.url.netloc}"
            if not (source == expected or source.startswith(expected + "/")):
                return PlainTextResponse("Cross-site request blocked.", status_code=403)
    return await call_next(request)

@app.middleware("http")
async def students_page_swipe_scroll(request: Request, call_next):
    """Keep the Students page vertically swipe-scrollable on touch devices.

    This is intentionally limited to /app/students so it does not alter
    scrolling behavior of other application pages.
    """
    response = await call_next(request)
    if request.url.path == "/app/students" and response.headers.get("content-type", "").lower().startswith("text/html"):
        try:
            body = getattr(response, "body", None)
            if body:
                css = b"<style id='davischool-students-scroll-fix'>html,body{min-height:100%;height:auto;overflow-y:auto;overflow-x:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y}.app,.main,.page{min-height:auto}.page .card.section{min-width:0;max-width:100%;box-sizing:border-box}.page .card.section:has(table){max-width:100%;width:100%;box-sizing:border-box}.students-register-scroll{display:block;width:100%;max-width:100%;overflow-x:auto;overflow-y:visible;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;overscroll-behavior-x:contain}.students-register-scroll table{width:max-content;min-width:100%;max-width:none;white-space:nowrap}</style>"
                marker = b"</head>"
                if marker in body:
                    body = body.replace(marker, css + marker, 1)
                    response.body = body
                    response.headers["content-length"] = str(len(body))
        except Exception as exc:
            print("DAVISCHOOL STUDENTS SWIPE SCROLL INJECTION WARNING:", repr(exc), flush=True)
    return response

@app.middleware("http")
async def super_admin_landing_redirect(request: Request, call_next):
    """
    Send platform-level Super Admin sessions to the redesigned platform
    overview instead of the separate /app school workspace. Super Admins
    impersonating a school keep using the school workspace.
    """
    # The legacy cross-school Global Control workspace is retired. Keep the
    # platform-level Super Admin experience on the platform overview and
    # prevent old Global Control URLs/forms from exposing duplicate controls.
    session = request.session
    role = str(session.get("role") or "").strip().lower()
    school_id = session.get("school_id") or 0
    is_impersonating = bool(session.get("is_impersonating"))
    if request.url.path == "/app" or request.url.path.startswith("/app/"):
        if role == "super_admin" and not school_id and not is_impersonating:
            return RedirectResponse("/dashboard", status_code=303)
    return await call_next(request)

@app.middleware("http")
async def dynamic_app_no_cache(request: Request, call_next):
    """
    Prevent browsers/proxies from reusing stale dynamic DaviSchool pages.

    Data-entry operations redirect back to live workspace pages after saving.
    Those pages must be fetched again so newly created/edited records are
    immediately reflected in dependent lists, dashboards, filters and reports.
    Static assets are intentionally excluded.
    """
    response = await call_next(request)
    if request.url.path == "/app" or request.url.path.startswith("/app/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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

# Install the tab-aware SessionMiddleware outside every @app.middleware layer.
# Request.session must exist before inactivity and role-routing middleware run.
# Tab-scoped sessions are installed once around the completed ASGI app at the end of this module.

SUPER_ADMIN = os.environ.get("DAVISCHOOL_SUPER_ADMIN", "admin@davischool.com")
DB_PATH = os.environ.get("DAVISCHOOL_DB_PATH", "davischool.db")
# Production deployments MUST use the persistent PostgreSQL database.
# SQLite is allowed only when the process explicitly identifies itself as local
# development.  This prevents a hosting environment from silently falling back
# to an ephemeral SQLite file after a deploy/restart and making accounts,
# students, marks, and other records appear to disappear.
LOCAL_DEVELOPMENT = os.environ.get("DAVISCHOOL_LOCAL_DEVELOPMENT", "0").strip().lower() in {"1", "true", "yes"}
REQUIRE_DATABASE = True

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310000

def _credential_cipher():
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode("utf-8")).digest())
    return Fernet(key)

def encrypt_credential(password: str) -> str:
    return _credential_cipher().encrypt(password.encode("utf-8")).decode("utf-8")

def decrypt_credential(token: str) -> str:
    return _credential_cipher().decrypt(token.encode("utf-8")).decode("utf-8")

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
    """
    Return the application's database connection.

    Production uses the managed Render PostgreSQL database whenever
    DATABASE_URL is configured. SQLite remains available for local
    development/backwards compatibility when DATABASE_URL is absent.
    """
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        from app.db import connect as pg_connect
        return pg_connect(database_url, connect_timeout=10)

    if not LOCAL_DEVELOPMENT:
        raise RuntimeError(
            "Mabale_ICT production database is not configured: DATABASE_URL is missing. "
            "Refusing to fall back to local SQLite because local SQLite is not persistent "
            "across normal hosting deployments/restarts. Set DATABASE_URL to the persistent "
            "PostgreSQL database used by Mabale_ICT."
        )

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
    acquire_schema_migration_lock(con)
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, status TEXT DEFAULT 'active')")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    # Additive account fields used by the current login and teacher-account
    # workflows. Inspect cursor metadata instead of PRAGMA so this works on
    # both the Render PostgreSQL database and local SQLite without touching
    # existing user records.
    try:
        cur.execute("SELECT * FROM users LIMIT 0")
        user_columns = {str(col.name if hasattr(col, "name") else col[0]).lower() for col in (cur.description or [])}
        for column, definition in (("username","TEXT"),("teacher_id","INTEGER"),("student_id","INTEGER"),("created_by_role","TEXT"),("created_by_email","TEXT")):
            if column not in user_columns:
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN %s %s" % (column, definition))
                    user_columns.add(column)
                except Exception:
                    pass
    except Exception:
        pass
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, role TEXT DEFAULT 'school_admin', auth_code TEXT, timestamp TEXT)")
    try: cur.execute("ALTER TABLE pending_schools ADD COLUMN role TEXT DEFAULT 'school_admin'")
    except Exception: pass
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, assessment_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_phone TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT, initial TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY, school_id INTEGER, term_name TEXT, year TEXT, start_date TEXT, end_date TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, email TEXT, phone TEXT, tsc_no TEXT, gender TEXT, id_no TEXT, role TEXT, employment_type TEXT)")
    teacher_color_column_added = False
    try:
        cur.execute("SELECT * FROM teachers LIMIT 0")
        teacher_columns = {str(col.name if hasattr(col, "name") else col[0]).lower() for col in (cur.description or [])}
        if "teacher_color" not in teacher_columns:
            cur.execute("ALTER TABLE teachers ADD COLUMN teacher_color TEXT DEFAULT '#2563EB'")
            teacher_color_column_added = True
        if "teacher_initials" not in teacher_columns:
            cur.execute("ALTER TABLE teachers ADD COLUMN teacher_initials TEXT")
            for teacher_row in cur.execute("SELECT id,name FROM teachers").fetchall():
                parts = [part for part in re.split(r"\s+", str(teacher_row["name"] or "").strip()) if part]
                initials = "".join(part[0] for part in (parts[:1] + (parts[-1:] if len(parts) > 1 else []))).upper()[:4]
                cur.execute("UPDATE teachers SET teacher_initials=? WHERE id=?", (initials, teacher_row["id"]))
    except Exception:
        pass
    try:
        cur.execute("SELECT id,teacher_color FROM teachers ORDER BY id")
        for teacher_row in cur.fetchall():
            saved_color = str(teacher_row["teacher_color"] or "").strip()
            if teacher_color_column_added or not re.fullmatch(r"#[0-9A-Fa-f]{6}", saved_color):
                cur.execute("UPDATE teachers SET teacher_color=? WHERE id=?", (_teacher_timetable_color(teacher_row["id"]), teacher_row["id"]))
    except Exception:
        pass
    cur.execute("CREATE TABLE IF NOT EXISTS teacher_allocations (id INTEGER PRIMARY KEY, school_id INTEGER, teacher_id INTEGER, subject_id INTEGER, class_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS global_notices (id INTEGER PRIMARY KEY, message TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS system_audit (id INTEGER PRIMARY KEY, school_id INTEGER, user_email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS billing (id INTEGER PRIMARY KEY, school_id INTEGER, amount TEXT, status TEXT, due_date TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, subject_id INTEGER, exam_id INTEGER, class_id INTEGER, marks INTEGER, year TEXT, term TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS set_marks_config (id INTEGER PRIMARY KEY, school_id INTEGER, subject_id INTEGER, class_name TEXT, stream TEXT, year TEXT, term TEXT, exam_id INTEGER, out_of INTEGER, created_at TEXT)")
    try: cur.execute("ALTER TABLE teachers ADD COLUMN employment_type TEXT")
    except: pass
    try: cur.execute("ALTER TABLE students ADD COLUMN category TEXT")
    except: pass
    try: cur.execute("ALTER TABLE students ADD COLUMN guardian_name TEXT")
    except: pass
    # Upgrade legacy PostgreSQL schemas before any query that depends on
    # columns introduced by the current application.
    ensure_schema_compatibility(con)
    try:
        cur.execute("UPDATE schools SET status='active' WHERE status IS NULL OR trim(status)=''")
        con.commit()
    except Exception:
        pass

    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        legacy_admin = cur.execute("SELECT * FROM users WHERE email=?", ("oumadavis62@gmail.com",)).fetchone()
        admin_password = os.environ.get("DAVISCHOOL_SUPER_ADMIN_PASSWORD", "DaviSchool@2026!")
        if legacy_admin:
            cur.execute("UPDATE users SET email=?, password=?, role=?, full_name=?, school_id=? WHERE id=?",
                        (SUPER_ADMIN, hash_password(admin_password), "super_admin", "Davis Ouma", 0, legacy_admin["id"]))
        else:
            cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)",
                        (SUPER_ADMIN,hash_password(admin_password),"super_admin","Davis Ouma",0))
    # IMPORTANT: Database initialization must be additive only.
    # Never delete user accounts during application startup or deployment.
    # Legacy/duplicate accounts must be handled explicitly from an authenticated
    # management action, never as a side effect of a code deployment.
    con.commit(); con.close()
def init_extended_db():
    con = get_db(); cur = con.cursor()
    acquire_schema_migration_lock(con)
    cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, amount REAL, paid REAL DEFAULT 0, description TEXT, due_date TEXT, status TEXT DEFAULT 'Pending')")
    cur.execute("CREATE TABLE IF NOT EXISTS announcements (id INTEGER PRIMARY KEY, school_id INTEGER, title TEXT, message TEXT, audience TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS sms_logs (id INTEGER PRIMARY KEY, school_id INTEGER, recipient TEXT, message TEXT, status TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS roles_permissions (id INTEGER PRIMARY KEY, school_id INTEGER, role TEXT, permission TEXT, enabled INTEGER DEFAULT 1)")
    # One-time destructive retirement migration. The marker prevents this
    # legacy timetable cleanup is isolated from all non-timetable school data.
    cur.execute("CREATE TABLE IF NOT EXISTS davischool_schema_migrations (migration_key TEXT PRIMARY KEY, applied_at TEXT)")
    cur.execute("SELECT 1 FROM davischool_schema_migrations WHERE migration_key=?", ("retire_all_legacy_timetable_v2",))
    if not cur.fetchone():
        if os.environ.get("DATABASE_URL", "").strip():
            try:
                cur.execute("DROP FUNCTION IF EXISTS timetable_active_profile(INTEGER)")
            except Exception:
                con.rollback()
                cur = con.cursor()
                acquire_schema_migration_lock(con)
        _drop_cascade = " CASCADE" if os.environ.get("DATABASE_URL", "").strip() else ""
        for _table in (
            "timetable_edit_history", "timetable_snapshots", "timetable_publications",
            "timetable_generation_runs", "timetable_profile_availability",
            "timetable_availability", "timetable_lesson_classes", "timetable_lesson_teachers",
            "timetable_slots", "timetable_lessons", "timetable_constraints",
            "timetable_teacher_availability", "timetable_subjects", "timetable_classes", "timetable_teachers",
            "timetable_rooms", "timetable_days", "timetable_periods", "timetable_breaks",
            "timetable_profiles", "timetable_profile_migrations", "timetable_manager_settings",
            "timetable_settings", "timetable",
        ):
            cur.execute("DROP TABLE IF EXISTS " + _table + _drop_cascade)
        cur.execute("DELETE FROM roles_permissions WHERE lower(COALESCE(permission,'')) LIKE '%timetable%'")
        cur.execute("DELETE FROM system_audit WHERE lower(COALESCE(action,'')) LIKE '%timetable%' OR lower(COALESCE(details,'')) LIKE '%timetable%'")
        cur.execute("DELETE FROM activity_log WHERE lower(COALESCE(action,'')) LIKE '%timetable%' OR lower(COALESCE(details,'')) LIKE '%timetable%'")
        cur.execute("INSERT INTO davischool_schema_migrations (migration_key, applied_at) VALUES (?, ?)", ("retire_all_legacy_timetable_v2", datetime.now().isoformat()))
    cur.execute("CREATE TABLE IF NOT EXISTS integrations (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, status TEXT, config TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS report_comments (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, student_id INTEGER, exam_id INTEGER, comment TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, student_id INTEGER, date TEXT, status TEXT)")
    # Finance / school accounting tables (additive; existing tables are preserved).
    cur.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, category TEXT, description TEXT, amount REAL, paid_to TEXT, voucher_no TEXT, date TEXT, status TEXT DEFAULT 'Paid')")
    cur.execute("CREATE TABLE IF NOT EXISTS pledges (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, parent_name TEXT, phone TEXT, amount REAL, paid REAL DEFAULT 0, purpose TEXT, due_date TEXT, status TEXT DEFAULT 'Pending')")
    cur.execute("CREATE TABLE IF NOT EXISTS payment_vouchers (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, voucher_no TEXT, payee TEXT, description TEXT, amount REAL, date TEXT, status TEXT DEFAULT 'Approved')")
    cur.execute("CREATE TABLE IF NOT EXISTS lpos (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, lpo_no TEXT, supplier TEXT, description TEXT, amount REAL, date TEXT, status TEXT DEFAULT 'Open')")
    cur.execute("CREATE TABLE IF NOT EXISTS cashbook (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, date TEXT, reference TEXT, description TEXT, debit REAL DEFAULT 0, credit REAL DEFAULT 0, account TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS fee_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, student_id INTEGER, amount REAL, reference TEXT, method TEXT, date TEXT, received_by TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS finance_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, code TEXT, name TEXT, type TEXT, opening_balance REAL DEFAULT 0)")
    try: cur.execute("ALTER TABLE users ADD COLUMN student_id INTEGER")
    except: pass
    try: cur.execute("ALTER TABLE users ADD COLUMN teacher_id INTEGER")
    except: pass

    # Performance indexes for the multi-school production workload. These are
    # additive and safe for existing data.
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_users_school ON users(school_id)",
        "CREATE INDEX IF NOT EXISTS idx_students_school ON students(school_id)",
        "CREATE INDEX IF NOT EXISTS idx_students_class ON students(school_id,class_id)",
        "CREATE INDEX IF NOT EXISTS idx_classes_school ON classes(school_id)",
        "CREATE INDEX IF NOT EXISTS idx_subjects_school ON subjects(school_id)",
        "CREATE INDEX IF NOT EXISTS idx_teachers_school ON teachers(school_id)",
        "CREATE INDEX IF NOT EXISTS idx_marks_school ON marks(school_id)",
        "CREATE INDEX IF NOT EXISTS idx_marks_student ON marks(school_id,student_id)",
        "CREATE INDEX IF NOT EXISTS idx_marks_exam_class ON marks(school_id,exam_id,class_id)",
        "CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(school_id,student_id,date)",
        "CREATE INDEX IF NOT EXISTS idx_fee_payments_student ON fee_payments(school_id,student_id,date)",
        "CREATE INDEX IF NOT EXISTS idx_fees_student ON fees(school_id,student_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_school_time ON system_audit(school_id,timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_users_email_lower ON users(lower(email))",
        "CREATE INDEX IF NOT EXISTS idx_users_username_lower ON users(lower(username))",
        "CREATE INDEX IF NOT EXISTS idx_students_school_class_stream ON students(school_id,class_id,stream)",
        "CREATE INDEX IF NOT EXISTS idx_teachers_school_email_lower ON teachers(school_id,lower(email))",
        "CREATE INDEX IF NOT EXISTS idx_teachers_school_tsc_lower ON teachers(school_id,lower(tsc_no))",
        "CREATE INDEX IF NOT EXISTS idx_teachers_school_idno_lower ON teachers(school_id,lower(id_no))",
        "CREATE INDEX IF NOT EXISTS idx_subjects_school_code ON subjects(school_id,code)",
        "CREATE INDEX IF NOT EXISTS idx_classes_school_name_stream ON classes(school_id,name,stream)",
        "CREATE INDEX IF NOT EXISTS idx_exams_school_year_term ON exams(school_id,year,term)",
        "CREATE INDEX IF NOT EXISTS idx_terms_school_year_term ON terms(school_id,year,term_name)",
        "CREATE INDEX IF NOT EXISTS idx_marks_school_student_exam_subject ON marks(school_id,student_id,exam_id,subject_id)",
        "CREATE INDEX IF NOT EXISTS idx_marks_school_class_exam_subject ON marks(school_id,class_id,exam_id,subject_id)",
        "CREATE INDEX IF NOT EXISTS idx_marks_school_exam_subject_student ON marks(school_id,exam_id,subject_id,student_id)",
        "CREATE INDEX IF NOT EXISTS idx_teacher_allocations_school_teacher_class_subject ON teacher_allocations(school_id,teacher_id,class_id,subject_id)",
        "CREATE INDEX IF NOT EXISTS idx_roles_permissions_lookup ON roles_permissions(school_id,role,permission,id)",
        "CREATE INDEX IF NOT EXISTS idx_attendance_school_date_student ON attendance(school_id,date,student_id)",
        "CREATE INDEX IF NOT EXISTS idx_fee_payments_school_student_date ON fee_payments(school_id,student_id,date)",
        "CREATE INDEX IF NOT EXISTS idx_fees_school_student ON fees(school_id,student_id)",
    ]
    for statement in indexes:
        try:
            cur.execute(statement)
        except Exception:
            pass

    con.commit(); con.close()
def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0: return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    s = cur.fetchone()
    con.close()
    if not s:
        return None
    try:
        status = str(s["status"] or "active").strip().lower()
    except Exception:
        status = "active"
    is_private_demo = (
        status == "demo"
        and bool(req.session.get("is_portal_preview"))
        and str(s["email"] or "").strip().lower() == "portal-demo@davischool.invalid"
    )
    if status not in ("active", "enabled") and not is_private_demo:
        return None
    return s

def generate_unique_password(name):
    p = "".join([c for c in name.upper() if c.isalpha()])[:4]
    if len(p)<3: p="SCH"
    return f"{p}@{random.randint(1000,9999)}!"



def _ensure_student_parent_name_column(cur):
    """Add the parent-name field without changing existing student records."""
    cur.execute("SELECT * FROM students LIMIT 0")
    columns = {str(col.name if hasattr(col, "name") else col[0]).lower() for col in (cur.description or [])}
    if "parent_name" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN parent_name TEXT")


def _create_or_link_parent_access(cur, school_id, student_id, admission_no, parent_name, parent_phone):
    """Create one phone-based parent login per school and link all their children."""
    phone = re.sub(r"[^0-9+]", "", str(parent_phone or "").strip())
    if not phone:
        return None
    _ensure_student_parent_name_column(cur)
    cur.execute("""CREATE TABLE IF NOT EXISTS parent_student_links (
        school_id INTEGER NOT NULL, user_id INTEGER NOT NULL, student_id INTEGER NOT NULL,
        created_at TEXT, PRIMARY KEY (school_id,user_id,student_id))""")
    cur.execute("SELECT * FROM users LIMIT 0")
    user_columns = {str(col.name if hasattr(col, "name") else col[0]).lower() for col in (cur.description or [])}
    if "must_change_password" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
    cur.execute("""CREATE TABLE IF NOT EXISTS parent_access_credentials (
        school_id INTEGER NOT NULL, student_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        username TEXT NOT NULL, password_cipher TEXT, created_at TEXT,
        PRIMARY KEY (school_id,student_id))""")

    account = cur.execute("""SELECT * FROM users
        WHERE school_id=? AND role='parent'
          AND lower(trim(COALESCE(username,'')))=lower(trim(?))
        ORDER BY id DESC LIMIT 1""", (school_id, phone)).fetchone()

    if not account:
        conflicting = cur.execute("""SELECT id,role FROM users
            WHERE school_id=? AND lower(trim(COALESCE(username,'')))=lower(trim(?))
            ORDER BY id DESC LIMIT 1""", (school_id, phone)).fetchone()
        if conflicting:
            raise ValueError("This phone number is already used as another school account's username.")
        other_school = cur.execute("""SELECT id,school_id FROM users
            WHERE role='parent' AND lower(trim(COALESCE(username,'')))=lower(trim(?))
              AND school_id<>? ORDER BY id DESC LIMIT 1""", (phone, school_id)).fetchone()
        if other_school:
            raise ValueError("This phone number already has a parent account at another school. Ask the school to resolve the account link before sharing credentials.")
        initial_password = str(admission_no or "").strip() + "@" + str(datetime.now(ZoneInfo("Africa/Nairobi")).year)
        parent_label = str(parent_name or "").strip() or "Parent / Guardian"
        cur.execute("""INSERT INTO users
            (email,username,password,role,full_name,school_id,student_id,must_change_password)
            VALUES (?,?,?,?,?,?,?,?)""",
            (phone, phone, hash_password(initial_password), "parent", parent_label, school_id, student_id, 1))
        account = cur.execute("""SELECT * FROM users
            WHERE school_id=? AND role='parent'
              AND lower(trim(COALESCE(username,'')))=lower(trim(?))
            ORDER BY id DESC LIMIT 1""", (school_id, phone)).fetchone()
        if not account:
            raise RuntimeError("Parent account could not be created.")
        password_to_show = initial_password
    else:
        password_to_show = None
        prior_credential = cur.execute("""SELECT password_cipher FROM parent_access_credentials
            WHERE school_id=? AND user_id=? AND COALESCE(password_cipher,'')<>''
            ORDER BY created_at ASC LIMIT 1""", (school_id, int(account["id"]))).fetchone()
        if prior_credential:
            try:
                password_to_show = decrypt_credential(str(prior_credential["password_cipher"]))
            except Exception:
                password_to_show = None
        if not account["student_id"]:
            cur.execute("UPDATE users SET student_id=? WHERE id=?", (student_id, account["id"]))

    user_id = int(account["id"])
    created_at = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""INSERT INTO parent_student_links(school_id,user_id,student_id,created_at)
        VALUES(?,?,?,?) ON CONFLICT(school_id,user_id,student_id) DO NOTHING""",
        (school_id, user_id, student_id, created_at))
    encrypted = encrypt_credential(password_to_show) if password_to_show else None
    cur.execute("""INSERT INTO parent_access_credentials
        (school_id,student_id,user_id,username,password_cipher,created_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(school_id,student_id) DO UPDATE SET
          user_id=excluded.user_id, username=excluded.username,
          password_cipher=excluded.password_cipher, created_at=excluded.created_at""",
        (school_id, student_id, user_id, phone, encrypted, created_at))
    return {"student_id": int(student_id), "username": phone, "password": password_to_show}

def header_html(initials, name, email):
    return f"""<style>.do-avatar{{width:36px;height:36px;background:#dcf0dc;color:#14532d;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #dce9dc}}.dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#166534;color:white}}</style><div style='background:white;border-bottom:1px solid #dce9dc;padding:10px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:14px'>🏫 Mabale_ICT Management System (Super Admin)</b><div style='font-size:11px;color:#64748b'>{name} • Super Admin</div></div><div style='position:relative'><div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div><div id='profileDropdown' style='display:none;position:absolute;right:0;top:44px;background:white;border:1px solid #dce9dc;border-radius:12px;width:220px;box-shadow:0 10px 25px rgba(0,0,0,0.12);z-index:1000;overflow:hidden'><div style='padding:14px;border-bottom:1px solid #f1f5f9;background:#f1f8f1'><div style='font-weight:700;font-size:13px'>{name}</div><div style='font-size:11px;color:#64748b'>{email}</div></div><a href='/super/global-control/dashboard' class='dropdown-item' style='color:#166534'>🌍 Global Control</a><a href='/logout' class='dropdown-item' style='color:#dc2626'>🚪 Logout</a></div></div></div><script>function toggleProfileMenu(){{let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none';}}</script>"""

def school_header(school, name, active="dashboard", is_impersonating=False, role="school_admin"):
    """Retired legacy navigation renderer. Kept as a no-op for old helper callers."""
    return ""

def staff_manager_html(teachers, school_name, is_global=False):
    total = len(teachers)
    male = len([t for t in teachers if (t['gender'] or '').lower().startswith('m')])
    female = total - male
    teaching_roles = ['teacher','classteacher','principal','deputy principal']
    teaching = len([t for t in teachers if (t['role'] or '').lower() in teaching_roles])
    non_teaching = total - teaching
    from collections import Counter
    role_counter = Counter([(t['role'] or 'Unknown') for t in teachers])
    role_pills = "".join([f"<span style='border:1px solid #e2e8f0;background:white;padding:4px 10px;border-radius:16px;font-size:12px;font-weight:600;margin-right:6px;display:inline-block;margin-bottom:6px'>{r}: {c}</span>" for r,c in role_counter.items()]) or "<span style='font-size:12px;color:#94a3b8'>No roles yet</span>"
    rows_html = ""
    for i, t in enumerate(teachers, 1):
        delete_url = f"/super/global-control/teachers/delete/{t['id']}" if is_global else f"/school/teachers/delete/{t['id']}"
        edit_action = "" if is_global else f"<a href='/school/teachers/{int(t['id'])}/edit' style='background:#eaf3ec;color:#246441;padding:6px 9px;border-radius:8px;text-decoration:none;font-size:12px;margin-right:5px'>Edit</a>"
        teacher_color = str(t["teacher_color"] or "#2563EB")
        rows_html += f"""<tr class='staff-row' data-role="{(t['role'] or '').lower()}" data-gender="{(t['gender'] or '').lower()}" data-employment="{(t['employment_type'] or ('teaching' if (t['role'] or '').lower() in teaching_roles else 'non-teaching')).lower()}" data-search="{(t['name'] or '').lower()} {(t['id_no'] or '').lower()} {(t['email'] or '').lower()} {(t['tsc_no'] or '').lower()}"><td style='padding:14px 12px;font-size:13px'>{i}</td><td style='padding:14px 12px;font-size:13px;font-weight:600'>{t['id_no'] or t['tsc_no'] or '—'}</td><td style='padding:14px 12px;font-size:13px;font-weight:700'><span style='display:inline-block;width:9px;height:9px;border-radius:50%;background:{teacher_color};margin-right:6px'></span>{t['name']}</td><td style='padding:14px 12px;font-size:13px'>{t['gender'] or '—'}</td><td style='padding:14px 12px;font-size:13px'><span style='background:#f1f5f9;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700'>{t['role'] or 'Teacher'}</span></td><td style='padding:14px 12px;font-size:13px'>{t['phone'] or '—'}</td><td style='padding:14px 12px;font-size:13px;color:#475569'>{t['email'] or '—'}</td><td style='padding:14px 12px'>{edit_action}<a href='{delete_url}' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:8px;text-decoration:none;font-size:12px'>🗑️</a></td></tr>"""
    if not rows_html:
        rows_html = "<tr><td colspan='8' style='padding:40px;text-align:center;color:#94a3b8'>No staff yet</td></tr>"
    add_action = "/super/global-control/teachers/add" if is_global else "/school/teachers/add"
    return f"""<style>.staff-card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px;display:flex;justify-content:space-between;align-items:center}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;min-width:140px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-staff-btn{{background:#0b3d91;color:white;padding:12px 18px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:20px}}.modal.active{{display:flex}}</style><div style='padding:22px;max-width:1500px;margin:auto'><div style='margin-bottom:18px'><h1 style='margin:0;font-size:28px;font-weight:900'>Staff</h1><p style='margin:6px 0 0;color:#64748b;font-size:14px'>Manage staff records — {school_name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px'><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Total Staff</div><div style='font-size:28px;font-weight:900;margin-top:8px'>{total}</div></div></div><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Male / Female</div><div style='font-size:24px;font-weight:900;margin-top:8px'><span style='color:#2563eb'>{male}</span> / <span style='color:#db2777'>{female}</span></div></div></div><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Teaching / Non-Teaching</div><div style='font-size:24px;font-weight:900;margin-top:8px'><span style='color:#059669'>{teaching}</span> / <span style='color:#ea580c'>{non_teaching}</span></div></div></div><div class='staff-card' style='flex-direction:column;align-items:flex-start'><div style='font-size:13px;color:#64748b;font-weight:600;margin-bottom:10px'>By Role</div><div>{role_pills}</div></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center'><input id='searchInput' onkeyup='filterStaff()' placeholder='Search name, ID, email.' style='padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;min-width:200px'><select id='roleFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Roles</option><option value='administrator'>Administrator</option><option value='principal'>Principal</option><option value='deputy principal'>Deputy Principal</option><option value='classteacher'>Classteacher</option><option value='teacher'>Teacher</option></select><select id='genderFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Gender</option><option value='male'>Male</option><option value='female'>Female</option></select><select id='employmentFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Employment</option><option value='teaching'>Teaching</option><option value='non-teaching'>Non-Teaching</option></select><button class='action-btn' onclick='exportCSV()'>📄 CSV</button><button class='action-btn' onclick='window.print()'>⬇️ PDF</button><button class='add-staff-btn' onclick='openModal()'>+ Add Staff</button></div><div style='overflow:auto;max-height:65vh'><table id='staffTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:12px;color:#64748b;border-top:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9'><th style='padding:12px'>#</th><th style='padding:12px'>NATIONAL ID</th><th style='padding:12px'>NAME</th><th style='padding:12px'>GENDER</th><th style='padding:12px'>ROLE</th><th style='padding:12px'>PHONE</th><th style='padding:12px'>EMAIL</th><th style='padding:12px'>ACTIONS</th></tr></thead><tbody>{rows_html}</tbody></table></div></div></div><div id='addStaffModal' class='modal'><div style='background:white;border-radius:16px;width:520px;max-width:95%;max-height:90vh;overflow:auto'><div style='padding:20px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>➕ Add Staff</b><span onclick='closeModal()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_action}' style='padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:12px'><div style='grid-column:span 2'><input name='name' required placeholder='Full Name *' class='input-field'></div><div><input name='id_no' required placeholder='National ID *' class='input-field'></div><div><input name='tsc_no' placeholder='TSC No' class='input-field'></div><div><select name='gender' required class='input-field'><option value='Male'>Male</option><option value='Female'>Female</option></select></div><div><select name='role' id='addStaffRole' required class='input-field' onchange="filterStaffDepartments('addStaffRole','addStaffDepartment')"><option value=''>Select Role *</option><option value='Teacher'>Teacher</option><option value='Classteacher'>Classteacher</option><option value='Principal'>Principal</option><option value='Deputy Principal'>Deputy Principal</option><option value='Administrator'>Administrator</option><option value='Other'>Other</option></select></div><div><select name='department' id='addStaffDepartment' class='input-field'><option value=''>Select Department</option></select></div><div><select name='employment_type' required class='input-field'><option value='Teaching'>Teaching</option><option value='Non-Teaching'>Non-Teaching</option></select></div><div><input name='phone' required placeholder='Phone *' class='input-field'></div><div style='grid-column:span 2'><input name='email' placeholder='Email' class='input-field'></div><div style='grid-column:span 2'><button class='add-btn'>➕ Add Staff</button></div></form></div></div><script>function filterStaffDepartments(roleId,deptId,selected){{const role=(document.getElementById(roleId)?.value||'').toLowerCase();const teaching=['teacher','classteacher','principal','deputy principal'].includes(role);const teachingDepartments=['ECDE / Early Childhood Education','Lower Primary','Upper Primary','Junior School','Senior School','Languages','Mathematics','Sciences','Humanities & Social Sciences','Technical & Vocational Studies','Creative Arts & Sports','Religious Education','Special Needs Education','Academic Coordination'];const otherDepartments=['School Administration','Registry & Admissions','Finance & Accounts','Human Resources','ICT & Technology','Library Services','Guidance & Counselling','Examinations Department','Laboratory Department','Sports & Physical Education','Transport Department','Security Department','Catering & Nutrition','Health & Medical Services','Maintenance & Facilities','Cleaning & Sanitation','Boarding & Accommodation','Procurement & Stores','Support Services','Other'];const select=document.getElementById(deptId);if(!select)return;const previous=selected!==undefined?selected:select.value;const options=teaching?teachingDepartments:otherDepartments;select.innerHTML='<option value="">Select Department</option>'+options.map(v=>'<option value="'+v.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'">'+v+'</option>').join('');if(previous&&!options.includes(previous)&&selected!==undefined)select.add(new Option(previous,previous));if(previous&&options.includes(previous))select.value=previous;}}function openModal(){{document.getElementById('addStaffModal').classList.add('active');}}function closeModal(){{document.getElementById('addStaffModal').classList.remove('active');}}function filterStaff(){{let s=document.getElementById('searchInput').value.toLowerCase();let r=document.getElementById('roleFilter').value.toLowerCase();let g=document.getElementById('genderFilter').value.toLowerCase();let e=document.getElementById('employmentFilter').value.toLowerCase();document.querySelectorAll('.staff-row').forEach(row=>{{let ok=row.getAttribute('data-search').includes(s);if(r!=='all'&&!row.getAttribute('data-role').includes(r))ok=false;if(g!=='all'&&!row.getAttribute('data-gender').includes(g))ok=false;if(e!=='all'&&!row.getAttribute('data-employment').includes(e))ok=false;row.style.display=ok?'':'none';}});}}function exportCSV(){{let rows=document.querySelectorAll('#staffTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i<7)d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}});csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='staff_{school_name}.csv';a.click();}}</script>"""

def students_manager_html(students, classes_list, school_name, is_global=False):
    total = len(students)
    male = len([s for s in students if (s['gender'] or '').lower().startswith('m')])
    female = total - male
    boarding = len([s for s in students if (s['category'] or 'Day').lower().startswith('b')])
    day = total - boarding
    from collections import Counter
    class_counter = Counter([(s['class_name'] or 'UNASSIGNED') for s in students])
    class_pills = "".join([f"<span style='border:1px solid #e2e8f0;background:white;padding:4px 10px;border-radius:16px;font-size:11px;font-weight:600;margin-right:6px;display:inline-block;margin-bottom:6px'>{k}: {v}</span>" for k,v in class_counter.items()]) or "<span style='font-size:11px;color:#94a3b8'>No classes yet</span>"
    class_filter_opts = "<option value='all'>All Classes</option>"
    for c in classes_list:
        label = f"{c['name']} {c['stream'] or ''}".strip()
        class_filter_opts += f"<option value='{label.lower()}'>{label}</option>"
    rows_html = ""
    for i, st in enumerate(students, 1):
        del_url = f"/super/global-control/students/delete/{st['id']}" if is_global else f"/school/students/delete/{st['id']}"
        cname = st['class_name'] or '—'
        cat = st['category'] or 'Day'
        guardian = st['guardian_name'] or '—'
        phone = st['parent_phone'] or '—'
        adm = st['admission_no'] or st['assessment_no'] or '—'
        rows_html += f"""<tr class='stu-row' data-class="{cname.lower()}" data-gender="{(st['gender'] or '').lower()}" data-category="{cat.lower()}" data-search="{(st['name'] or '').lower()} {adm.lower()} {guardian.lower()} {cname.lower()}"><td style='padding:12px 10px;font-size:12px'>{i}</td><td style='padding:12px 10px;font-size:12px;font-weight:600'>{adm}</td><td style='padding:12px 10px;font-size:12px;font-weight:700'>{st['name']}</td><td style='padding:12px 10px;font-size:12px'>{st['gender'] or '—'}</td><td style='padding:12px 10px;font-size:12px'><span style='background:#f1f5f9;padding:3px 8px;border-radius:10px;font-size:11px'>{cname}</span></td><td style='padding:12px 10px;font-size:12px'>{cat}</td><td style='padding:12px 10px;font-size:12px'>{guardian}</td><td style='padding:12px 10px;font-size:12px'>{phone}</td><td style='padding:12px 10px'><a href='{del_url}' style='background:#fee2e2;color:#991b1b;padding:5px 8px;border-radius:7px;text-decoration:none;font-size:11px'>🗑️</a></td></tr>"""
    if not rows_html:
        rows_html = "<tr><td colspan='9' style='padding:40px;text-align:center;color:#94a3b8'>No pupils yet — click + Admit Pupil</td></tr>"
    add_action = "/super/global-control/students/add" if is_global else "/school/students/add"
    class_opts_form = "".join([f"<option value='{c[0]}'>{c['name']} {c['stream'] or ''}</option>" for c in classes_list])
    return f"""<style>.stu-card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px;display:flex;justify-content:space-between;align-items:center}}.filter-select{{padding:9px 11px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:12px;min-width:130px}}.action-btn{{padding:9px 12px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:12px;font-weight:600;cursor:pointer}}.add-pupil-btn{{background:#0b3d91;color:white;padding:11px 16px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div style='margin-bottom:16px'><h1 style='margin:0;font-size:26px;font-weight:900'>Students Manager</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage pupils — {school_name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px'><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Total Students</div><div style='font-size:26px;font-weight:900;margin-top:6px'>{total}</div></div></div><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Male / Female</div><div style='font-size:22px;font-weight:900;margin-top:6px'><span style='color:#2563eb'>{male}</span> / <span style='color:#db2777'>{female}</span></div></div></div><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Boarding / Day</div><div style='font-size:22px;font-weight:900;margin-top:6px'><span style='color:#059669'>{boarding}</span> / <span style='color:#ea580c'>{day}</span></div></div></div><div class='stu-card' style='flex-direction:column;align-items:flex-start'><div style='font-size:12px;color:#64748b;font-weight:600;margin-bottom:8px'>By Class</div><div style='display:flex;flex-wrap:wrap'>{class_pills}</div></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;border-bottom:1px solid #f1f5f9'><div style='display:flex;align-items:center;gap:8px'><span style='font-size:12px;color:#64748b'>Show</span><select id='perPage' class='filter-select' style='min-width:70px' onchange='filterStu()'><option value='10'>10</option><option value='25'>25</option><option value='50'>50</option><option value='100'>100</option><option value='1000'>All</option></select><span style='font-size:12px;color:#64748b'>items</span></div><div style='display:flex;gap:8px;flex-wrap:wrap'><button class='add-pupil-btn' onclick='openStuModal()'>+ Admit Pupil</button></div></div><div style='padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:9px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='stuSearch' onkeyup='filterStu()' placeholder='Search name, ADM, guardian' style='padding:9px 12px 9px 30px;border:1px solid #e2e8f0;border-radius:10px;font-size:12px;min-width:200px'></div><select id='classFilter' class='filter-select' onchange='filterStu()'>{class_filter_opts}</select><select id='genderFilter' class='filter-select' onchange='filterStu()'><option value='all'>All Gender</option><option value='male'>Male</option><option value='female'>Female</option></select><select id='categoryFilter' class='filter-select' onchange='filterStu()'><option value='all'>All Category</option><option value='day'>Day</option><option value='boarding'>Boarding</option></select><button class='action-btn' onclick='exportStuCSV()'>📄 CSV</button><button class='action-btn' onclick='exportPDF()'>⬇️ PDF</button><button class='action-btn' onclick='exportKemis()'>📤 KEMIS Export</button></div><div style='overflow:auto;max-height:68vh'><table id='stuTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-top:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9'><th style='padding:11px 10px'>#</th><th style='padding:11px 10px'>ADM NO</th><th style='padding:11px 10px'>NAME</th><th style='padding:11px 10px'>GENDER</th><th style='padding:11px 10px'>CLASS</th><th style='padding:11px 10px'>CATEGORY</th><th style='padding:11px 10px'>GUARDIAN</th><th style='padding:11px 10px'>PHONE</th><th style='padding:11px 10px'>ACTIONS</th></tr></thead><tbody>{rows_html}</tbody></table></div></div></div><div id='stuModal' class='modal'><div style='background:white;border-radius:16px;width:560px;max-width:96%;max-height:92vh;overflow:auto'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center'><b>➕ Admit Pupil — {school_name}</b><span onclick='closeStuModal()' style='cursor:pointer;font-size:20px'>✕</span></div><form method='post' action='{add_action}' data-native-post='1' data-no-history-filter='1' style='padding:18px;display:grid;grid-template-columns:1fr 1fr;gap:12px'><div><label style='font-size:11px;font-weight:700'>🆔 Admission No *</label><input name='admission_no' required placeholder='e.g. 1001' class='input-field'></div><div><label style='font-size:11px;font-weight:700'>📝 Assessment No</label><input name='assessment_no' placeholder='KEMIS' class='input-field'></div><div style='grid-column:span 2'><label style='font-size:11px;font-weight:700'>👤 Full Name *</label><input name='student_name' required placeholder='Full Name *' class='input-field'></div><div><label style='font-size:11px;font-weight:700'>🏫 Class *</label><select name='class_id' required class='input-field'><option value=''>Select Class *</option>{class_opts_form}</select></div><div><label style='font-size:11px;font-weight:700'>⚧️ Gender *</label><select name='gender' required class='input-field'><option value='Male'>Male</option><option value='Female'>Female</option></select></div><div><label style='font-size:11px;font-weight:700'>🏠 Category *</label><select name='category' required class='input-field'><option value='Day'>Day</option><option value='Boarding'>Boarding</option></select></div><div><label style='font-size:11px;font-weight:700'>👨‍👩‍👧 Guardian Name</label><input name='guardian_name' placeholder='Guardian Name' class='input-field'></div><div style='grid-column:span 2'><label style='font-size:11px;font-weight:700'>📞 Guardian Phone</label><input name='parent_phone' placeholder='Phone' class='input-field'></div><div style='grid-column:span 2;margin-top:6px'><button type='submit' name='save_student' value='1' class='add-btn'>✅ Save Student</button></div></form></div></div><script>function openStuModal(){{document.getElementById('stuModal').classList.add('active');}}function closeStuModal(){{document.getElementById('stuModal').classList.remove('active');}}function filterStu(){{let q=document.getElementById('stuSearch').value.toLowerCase();let cf=document.getElementById('classFilter').value.toLowerCase();let gf=document.getElementById('genderFilter').value.toLowerCase();let catf=document.getElementById('categoryFilter').value.toLowerCase();let per=parseInt(document.getElementById('perPage').value);let rows=document.querySelectorAll('.stu-row');let vis=0;rows.forEach(r=>{{let ok=true;if(q&&!r.getAttribute('data-search').includes(q))ok=false;if(cf!=='all'&&!r.getAttribute('data-class').includes(cf))ok=false;if(gf!=='all'&&!r.getAttribute('data-gender').includes(gf))ok=false;if(catf!=='all'&&!r.getAttribute('data-category').includes(catf))ok=false;if(ok){{vis++;r.style.display=(per>=1000||vis<=per)?'':'none';}} else {{r.style.display='none';}}}});}}function exportStuCSV(){{let rows=document.querySelectorAll('#stuTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i<8)d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}});if(d.length)csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='students_{school_name}.csv';a.click();}}function exportKemis(){{let rows=document.querySelectorAll('.stu-row');let out=[['ADM_NO','NAME','GENDER','CLASS','CATEGORY','GUARDIAN','PHONE'].join(',')];rows.forEach(r=>{{if(r.style.display==='none')return;let tds=r.querySelectorAll('td');let vals=[tds[1].innerText,tds[2].innerText,tds[3].innerText,tds[4].innerText,tds[5].innerText,tds[6].innerText,tds[7].innerText].map(v=>'\"'+v.replace(/\"/g,'\"\"')+'\"');out.push(vals.join(','));}});let b=new Blob([out.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='KEMIS_{school_name}.csv';a.click();}}function exportPDF(){{window.print();}}</script>"""

def dean_manager_html(terms, subjects, teachers, classes, allocations, students, school_name, is_global=False, active_tab="terms"):
    years = sorted(list(set([t['year'] for t in terms if t['year']])), reverse=True)
    year_opts = "<option value='all'>All Years</option>" + "".join([f"<option value='{y}'>{y}</option>" for y in years])
    term_rows = ""
    for idx, t in enumerate(terms,1):
        edit_btn = f"""<a href='#' onclick='openEditTerm({t['id']},\"{t['term_name']}\",\"{t['year']}\",\"{t['start_date']}\",\"{t['end_date']}\");return false;' style='padding:6px 8px;background:#f1f5f9;border-radius:8px;text-decoration:none'>✏️</a>"""
        del_url = f"/super/global-control/dean-settings/delete-term/{t['id']}" if is_global else f"/school/dean-settings/delete-term/{t['id']}"
        term_rows += f"""<tr class='term-row' data-search="{t['term_name'].lower()} {t['year']}" data-year="{t['year']}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:13px'>{idx}</td><td style='padding:12px;font-size:13px;font-weight:700'>{t['term_name']}</td><td style='padding:12px;font-size:13px'>{t['year']}</td><td style='padding:12px;font-size:13px'>{t['start_date']}</td><td style='padding:12px;font-size:13px'>{t['end_date']}</td><td style='padding:12px;display:flex;gap:6px'>{edit_btn}<a href='{del_url}' style='padding:6px 8px;background:#fee2e2;border-radius:8px;text-decoration:none'>🗑️</a></td></tr>"""
    if not term_rows:
        term_rows = "<tr><td colspan='7' style='padding:40px;text-align:center;color:#94a3b8'>No terms — click + Add Term</td></tr>"
    subj_rows = ""
    for idx, s in enumerate(subjects,1):
        del_url = f"/super/global-control/dean-settings/delete-subject/{s['id']}" if is_global else f"/school/dean-settings/delete-subject/{s['id']}"
        subj_rows += f"""<tr class='subj-row' data-search="{s['name'].lower()}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:13px'>{idx}</td><td style='padding:12px;font-size:13px;font-weight:700'>{s['name']}</td><td style='padding:12px;font-size:13px'>{s['code'] or '—'}</td><td style='padding:12px;font-size:13px'>{s['initial'] or '—'}</td><td style='padding:12px'><a href='{del_url}' style='padding:6px 8px;background:#fee2e2;border-radius:8px;text-decoration:none'>🗑️</a></td></tr>"""
    if not subj_rows:
        subj_rows = "<tr><td colspan='6' style='padding:40px;text-align:center;color:#94a3b8'>No subjects — add in Subjects tab</td></tr>"
    t_opts = "".join([f"<option value='{t['id']}'>{t['name']} ({t['role'] or 'Teacher'})</option>" for t in teachers])
    s_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    c_opts = "".join([f"<option value='{c[0]}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    alloc_rows = ""
    for a in allocations:
        del_url = f"/super/global-control/dean-settings/delete-alloc/{a['id']}" if is_global else f"/school/dean-settings/delete-alloc/{a['id']}"
        alloc_rows += f"""<tr><td style='padding:10px 12px;font-size:13px'>{a['tname'] or '—'}</td><td style='padding:10px 12px;font-size:13px'>{a['sname'] or '—'}</td><td style='padding:10px 12px;font-size:13px'>{a['cname'] or '—'}</td><td style='padding:10px 12px'><a href='{del_url}' style='background:#fee2e2;color:#991b1b;padding:5px 8px;border-radius:7px;text-decoration:none'>🗑️</a></td></tr>"""
    if not alloc_rows:
        alloc_rows = "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No allocations yet</td></tr>"
    class_options_promote = "".join([f"<option value='{c[0]}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    add_term_action = "/super/global-control/dean-settings/add-term" if is_global else "/school/dean-settings/add-term"
    add_subject_action = "/super/global-control/dean-settings/add-subject" if is_global else "/school/dean-settings/add-subject"
    alloc_action = "/super/global-control/dean-settings/allocate" if is_global else "/school/dean-settings/allocate"
    promote_action = "/super/global-control/dean-settings/promote" if is_global else "/school/dean-settings/promote"
    return f"""<style>.dean-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden}}.dean-tab{{padding:10px 16px;border-radius:10px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid transparent;display:inline-flex;align-items:center;gap:6px}}.dean-tab.active{{background:#0b3d91;color:white}}.dean-tab:not(.active){{background:#f8fafc;color:#475569;border:1px solid #e2e8f0}}.filter-input{{padding:10px 12px 10px 34px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;width:220px}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-term-btn{{background:#0b3d91;color:white;padding:10px 16px;border:none;border-radius:12px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1450px;margin:auto'><div style='margin-bottom:14px'><h1 style='margin:0;font-size:26px;font-weight:900;letter-spacing:-0.5px'>Dean Settings</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage terms, subjects, teacher allocation & promotions</p></div><div class='dean-card'><div style='padding:14px 16px;display:flex;gap:8px;border-bottom:1px solid #f1f5f9;flex-wrap:wrap'><div onclick="switchTab('terms')" id='tab-terms' class='dean-tab {"active" if active_tab=="terms" else ""}'>📅 Terms</div><div onclick="switchTab('subjects')" id='tab-subjects' class='dean-tab {"active" if active_tab=="subjects" else ""}'>📖 Subjects</div><div onclick="switchTab('allocation')" id='tab-allocation' class='dean-tab {"active" if active_tab=="allocation" else ""}'>👥 Teacher Allocation</div><div onclick="switchTab('promote')" id='tab-promote' class='dean-tab {"active" if active_tab=="promote" else ""}'>↗️ Promote</div></div><div id='panel-terms' style='display:{"block" if active_tab=="terms" else "none"}'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='termSearch' onkeyup='filterTerms()' placeholder='Search terms...' class='filter-input'></div><select id='yearFilter' class='filter-select' onchange='filterTerms()'>{year_opts}</select></div><div style='display:flex;gap:8px'><button class='action-btn' onclick='downloadTerms()'>⬇️ Download</button><button class='add-term-btn' onclick='openAddTerm()'>+ Add Term</button></div></div><div style='overflow:auto;max-height:60vh'><table id='termsTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px 12px'><input type='checkbox'></th><th style='padding:12px'>#</th><th style='padding:12px'>TERM ↕️</th><th style='padding:12px'>YEAR ↕️</th><th style='padding:12px'>START DATE ↕️</th><th style='padding:12px'>END DATE ↕️</th><th style='padding:12px;text-align:right'>ACTIONS</th></tr></thead><tbody>{term_rows}</tbody></table></div></div><div id='panel-subjects' style='display:{"block" if active_tab=="subjects" else "none"}'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='subjSearch' onkeyup='filterSubjects()' placeholder='Search subjects...' class='filter-input'></div></div><div style='display:flex;gap:8px'><button class='add-term-btn' onclick='openAddSubject()'>+ Add Subject</button></div></div><div style='overflow:auto;max-height:60vh'><table style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px'><input type='checkbox'></th><th style='padding:12px'>#</th><th style='padding:12px'>NAME</th><th style='padding:12px'>CODE</th><th style='padding:12px'>INITIAL</th><th style='padding:12px'>ACTIONS</th></tr></thead><tbody>{subj_rows}</tbody></table></div></div><div id='panel-allocation' style='display:{"block" if active_tab=="allocation" else "none"}'><div style='padding:16px;display:grid;grid-template-columns:320px 1fr;gap:16px'><div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;height:fit-content'><b style='font-size:13px'>📌 Allocate Teacher</b><form method='post' action='{alloc_action}' style='margin-top:10px'><select name='teacher_id' required class='input-field'><option value=''>Select Teacher *</option>{t_opts}</select><select name='subject_id' required class='input-field'><option value=''>Select Subject *</option>{s_opts}</select><select name='class_id' required class='input-field'><option value=''>Select Class *</option>{c_opts}</select><button class='add-btn' style='margin-top:10px'>Allocate</button></form></div><div style='background:white;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden'><div style='padding:12px 14px;border-bottom:1px solid #f1f5f9'><b>Allocations ({len(allocations)})</b></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>TEACHER</th><th>SUBJECT</th><th>CLASS</th><th>ACTION</th></tr></thead><tbody>{alloc_rows}</tbody></table></div></div></div><div id='panel-promote' style='display:{"block" if active_tab=="promote" else "none"}'><div style='padding:20px;max-width:600px'><div style='background:#fffbeb;border:1px solid #fde68a;padding:12px;border-radius:10px;margin-bottom:16px;font-size:13px'>⚠️ Promotion will move all students from source class to destination class. This action is recorded.</div><form method='post' action='{promote_action}' style='display:grid;gap:12px'><div><label style='font-size:12px;font-weight:700'>From Class *</label><select name='from_class' required class='input-field'><option value=''>Select Source Class *</option>{class_options_promote}</select></div><div><label style='font-size:12px;font-weight:700'>To Class *</label><select name='to_class' required class='input-field'><option value=''>Select Destination Class *</option>{class_options_promote}</select></div><button class='add-btn'>↗️ Promote Students</button></form></div></div></div></div><div id='addTermModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Term</b><span onclick='closeAddTerm()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_term_action}' style='padding:18px;display:grid;gap:10px'><select name='term_name' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='Year e.g. 2026' class='input-field'><label style='font-size:11px;font-weight:700'>Start Date</label><input name='start_date' type='date' required class='input-field'><label style='font-size:11px;font-weight:700'>End Date</label><input name='end_date' type='date' required class='input-field'><button class='add-btn'>Add Term</button></form></div></div><div id='editTermModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>✏️ Edit Term</b><span onclick='closeEditTerm()' style='cursor:pointer'>✕</span></div><form id='editTermForm' method='post' style='padding:18px;display:grid;gap:10px'><select name='term_name' id='e_term_name' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' id='e_year' required class='input-field'><input name='start_date' id='e_start' type='date' required class='input-field'><input name='end_date' id='e_end' type='date' required class='input-field'><button class='add-btn'>Update Term</button></form></div></div><div id='addSubjectModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Subject</b><span onclick='closeAddSubject()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_subject_action}' style='padding:18px;display:grid;gap:10px'><input name='subject_name' required placeholder='Subject Name *' class='input-field'><input name='code' placeholder='Code e.g. MAT' class='input-field'><input name='initial' placeholder='Initial e.g. M' class='input-field'><button class='add-btn'>Add Subject</button></form></div></div><script>function switchTab(t){{document.querySelectorAll('[id^=panel-]').forEach(p=>p.style.display='none');document.querySelectorAll('.dean-tab').forEach(b=>b.classList.remove('active'));document.getElementById('panel-'+t).style.display='block';document.getElementById('tab-'+t).classList.add('active');const url=new URL(window.location); url.searchParams.set('tab',t); history.pushState({{}},'',url);}}function openAddTerm(){{document.getElementById('addTermModal').classList.add('active');}}function closeAddTerm(){{document.getElementById('addTermModal').classList.remove('active');}}function openEditTerm(id,name,year,s,e){{document.getElementById('editTermModal').classList.add('active');document.getElementById('editTermForm').action = (window.location.pathname.includes('global-control')? '/super/global-control/dean-settings/edit-term/' : '/school/dean-settings/edit-term/') + id;document.getElementById('e_term_name').value=name;document.getElementById('e_year').value=year;document.getElementById('e_start').value=s;document.getElementById('e_end').value=e;}}function closeEditTerm(){{document.getElementById('editTermModal').classList.remove('active');}}function openAddSubject(){{document.getElementById('addSubjectModal').classList.add('active');}}function closeAddSubject(){{document.getElementById('addSubjectModal').classList.remove('active');}}function filterTerms(){{let q=document.getElementById('termSearch').value.toLowerCase();let y=document.getElementById('yearFilter').value.toLowerCase();document.querySelectorAll('.term-row').forEach(r=>{{let ok=true;if(q &&!r.getAttribute('data-search').includes(q)) ok=false;if(y!=='all' && r.getAttribute('data-year').toLowerCase()!==y) ok=false;r.style.display=ok?'':'none';}});}}function filterSubjects(){{let q=document.getElementById('subjSearch').value.toLowerCase();document.querySelectorAll('.subj-row').forEach(r=>{{r.style.display=r.getAttribute('data-search').includes(q)?'':'none';}});}}function downloadTerms(){{let rows=document.querySelectorAll('#termsTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i>0 && i<6) d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}}); if(d.length) csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='terms_{school_name}.csv';a.click();}}</script>"""

def exam_manager_html(exams, school_name, is_global=False):
    from collections import Counter
    year_counter = Counter([e['year'] for e in exams if e['year']])
    term_counter = Counter([e['term'] for e in exams if e['term']])
    year_opts_filter = "<option value='all'>All Years</option>" + "".join([f"<option value='{y}'>{y} ({c})</option>" for y,c in sorted(year_counter.items(), reverse=True)])
    term_opts_filter = "<option value='all'>All Terms</option>" + "".join([f"<option value='{t}'>{t} ({c})</option>" for t,c in term_counter.items()])
    rows = ""
    for idx, e in enumerate(exams, 1):
        del_url = f"/super/global-control/exams/delete/{e['id']}" if is_global else f"/school/exams/delete/{e['id']}"
        edit_btn = f"""<a href='#' onclick='openEditExam({e['id']},"{e['name']}","{e['term']}","{e['year']}","{e['exam_type'] or 'Main Exam'}");return false;' style='padding:6px 8px;background:#f1f5f9;border-radius:8px;text-decoration:none;font-size:12px'>✏️</a>"""
        rows += f"""<tr class='exam-row' data-search="{e['name'].lower()} {e['year']} {e['term'].lower()}" data-year="{e['year']}" data-term="{e['term']}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:13px'>{idx}</td><td style='padding:12px;font-size:13px;font-weight:700'>{e['name']}</td><td style='padding:12px;font-size:13px'>{e['term']}</td><td style='padding:12px;font-size:13px'>{e['year']}</td><td style='padding:12px'><span style='background:#0b3d91;color:white;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:700'>{e['exam_type'] or 'Main Exam'}</span></td><td style='padding:12px;display:flex;gap:6px'>{edit_btn}<a href='{del_url}' style='padding:6px 8px;background:#fee2e2;border-radius:8px;text-decoration:none;font-size:12px'>🗑️</a></td></tr>"""
    if not rows:
        rows = "<tr><td colspan='7' style='padding:40px;text-align:center;color:#94a3b8'>No exams — click + Add Exam</td></tr>"
    add_action = "/super/global-control/exams/add" if is_global else "/school/exams/add"
    edit_base = "/super/global-control/exams/edit/" if is_global else "/school/exams/edit/"
    return f"""<style>.exam-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden}}.filter-input{{padding:10px 12px 10px 34px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;width:220px}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;min-width:120px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-exam-btn{{background:#0b3d91;color:white;padding:10px 16px;border:none;border-radius:12px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1450px;margin:auto'><div style='margin-bottom:14px'><h1 style='margin:0;font-size:26px;font-weight:900;letter-spacing:-0.5px'>Exam Settings</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage exams — {school_name} • Linked to Set Marks (Out Of)</p></div><div class='exam-card'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='examSearch' onkeyup='filterExams()' placeholder='Search exams...' class='filter-input'></div><select id='yearFilter' class='filter-select' onchange='filterExams()'>{year_opts_filter}</select><select id='termFilter' class='filter-select' onchange='filterExams()'>{term_opts_filter}</select></div><div style='display:flex;gap:8px'><button class='action-btn' onclick='downloadExams()'>⬇️ Download CSV</button><button class='add-exam-btn' onclick='openAddExam()'>+ Add Exam</button></div></div><div style='overflow:auto;max-height:65vh'><table id='examTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px'><input type='checkbox'></th><th style='padding:12px'>#</th><th style='padding:12px'>EXAM NAME ↕️</th><th style='padding:12px'>TERM ↕️</th><th style='padding:12px'>YEAR ↕️</th><th style='padding:12px'>TYPE</th><th style='padding:12px;text-align:right'>ACTIONS</th></tr></thead><tbody>{rows}</tbody></table></div></div></div><div id='addExamModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Exam</b><span onclick='closeAddExam()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_action}' style='padding:18px;display:grid;gap:10px'><input name='exam_name' required placeholder='Exam Name * e.g. OPENER' class='input-field'><select name='term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='Year e.g. 2026' class='input-field'><select name='exam_type' required class='input-field'><option>Main Exam</option><option>End Term Exam</option><option>Mid Term</option><option>CAT</option></select><button class='add-btn'>Add Exam</button></form></div></div><div id='editExamModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>✏️ Edit Exam</b><span onclick='closeEditExam()' style='cursor:pointer'>✕</span></div><form id='editExamForm' method='post' style='padding:18px;display:grid;gap:10px'><input name='exam_name' id='e_name' required class='input-field'><select name='term' id='e_term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' id='e_year' required class='input-field'><select name='exam_type' id='e_type' required class='input-field'><option>Main Exam</option><option>End Term Exam</option><option>Mid Term</option><option>CAT</option></select><button class='add-btn'>Update Exam</button></form></div></div><script>function openAddExam(){{document.getElementById('addExamModal').classList.add('active');}}function closeAddExam(){{document.getElementById('addExamModal').classList.remove('active');}}function openEditExam(id,name,term,year,type){{document.getElementById('editExamModal').classList.add('active');document.getElementById('editExamForm').action = "{edit_base}" + id; document.getElementById('e_name').value=name; document.getElementById('e_term').value=term; document.getElementById('e_year').value=year; document.getElementById('e_type').value=type;}}function closeEditExam(){{document.getElementById('editExamModal').classList.remove('active');}}function filterExams(){{let q=document.getElementById('examSearch').value.toLowerCase();let y=document.getElementById('yearFilter').value.toLowerCase();let t=document.getElementById('termFilter').value.toLowerCase();document.querySelectorAll('.exam-row').forEach(r=>{{let ok=true;if(q &&!r.getAttribute('data-search').includes(q)) ok=false;if(y!=='all' && r.getAttribute('data-year').toLowerCase()!==y) ok=false;if(t!=='all' && r.getAttribute('data-term').toLowerCase()!==t) ok=false;r.style.display=ok?'':'none';}});}}function downloadExams(){{let rows=document.querySelectorAll('#examTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i>0 && i<6) d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}}); if(d.length) csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='exams_{school_name}.csv';a.click();}}</script>"""

def set_marks_exact_html(subjects, classes, streams, years, terms_list, exams, configs, school_name, is_global=False, filters=None):
    filters = filters or {}
    subj_opts = "<option value=''>-- Select Subject --</option>" + "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    class_opts = "<option value=''>-- Select Class --</option>" + "".join([f"<option value='{c['name']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    stream_opts = "<option value=''>-- Select Stream --</option>" + "".join([f"<option value='{st}'>{st}</option>" for st in streams])
    year_opts = "<option value=''>-- Select Year --</option>" + "".join([f"<option value='{y}'>{y}</option>" for y in years])
    term_opts = "<option value=''>-- Select Term --</option>" + "".join([f"<option value='{t}'>{t}</option>" for t in terms_list])
    exam_opts = "<option value=''>-- Select Exam --</option>" + "".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams])
    all_years_filter = "<option value='all'>All Years</option>" + "".join([f"<option value='{y}' {'selected' if filters.get('year')==y else ''}>{y}</option>" for y in years])
    all_terms_filter = "<option value='all'>All Terms</option>" + "".join([f"<option value='{t}' {'selected' if filters.get('term')==t else ''}>{t}</option>" for t in terms_list])
    all_classes_filter = "<option value='all'>All Classes</option>" + "".join([f"<option value='{c['name']}' {'selected' if filters.get('class')==c['name'] else ''}>{c['name']}</option>" for c in classes])
    rows = ""
    for idx, cfg in enumerate(configs, 1):
        del_url = f"/super/global-control/set-marks/delete/{cfg['id']}" if is_global else f"/school/set-marks/delete/{cfg['id']}"
        rows += f"""<tr class='cfg-row' data-search="{(cfg['subject_name'] or '').lower()} {(cfg['class_name'] or '').lower()}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:12px'>{idx}</td><td style='padding:12px;font-size:12px'>{cfg['year']}</td><td style='padding:12px;font-size:12px'>{cfg['term']}</td><td style='padding:12px;font-size:12px;font-weight:700'>{cfg['class_name']} {cfg['stream'] or ''}</td><td style='padding:12px;font-size:12px;font-weight:600'>{cfg['subject_name']}</td><td style='padding:12px;font-size:12px'>{cfg['out_of']}</td><td style='padding:12px'><a href='{del_url}' style='background:#fee2e2;color:#991b1b;padding:5px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️</a></td></tr>"""
    if not rows:
        rows = "<tr><td colspan='8' style='padding:40px;text-align:center;color:#94a3b8'>No set marks yet — configure on left</td></tr>"
    save_action = "/super/global-control/set-marks/save" if is_global else "/school/set-marks/save"
    return f"""<style>.page-title{{font-size:24px;font-weight:900;margin:0}}.page-sub{{font-size:13px;color:#64748b;margin-top:4px}}.two-col{{display:grid;grid-template-columns:380px 1fr;gap:16px;margin-top:16px}}.card-white{{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px}}.info-blue{{background:#e6f0ff;border:1px solid #bfdbfe;border-radius:12px;padding:12px;font-size:12px;color:#1e40af;display:flex;gap:8px;line-height:1.5}}.label-red{{font-size:11px;font-weight:700;color:#dc2626;display:block;margin-top:10px;margin-bottom:4px}}.select-field{{width:100%;padding:11px 12px;border:1px solid #e5e7eb;border-radius:10px;background:white;font-size:13px}}.save-btn{{width:100%;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer;margin-top:14px;display:flex;justify-content:center;align-items:center;gap:8px}}.filter-bar{{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}}.filter-select{{padding:8px 10px;border:1px solid #e5e7eb;border-radius:10px;background:white;font-size:12px;min-width:110px}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div><h1 class='page-title'>Set Marks</h1><p class='page-sub'>Configure the maximum marks (out of) for each subject per exam</p></div><div class='two-col'><div class='card-white'><h3 style='margin:0 0 12px;font-size:16px;font-weight:800'>Set Marks Options</h3><div class='info-blue'>ℹ️ <span><b>Out Of:</b> This is what the teacher will mark this paper out of e.g. 50 or 100. Marks are not converted. e.g. if the paper is out of 60 set that.</span></div><form method='post' action='{save_action}' style='margin-top:14px'><label class='label-red'>Subject *</label><select name='subject_id' required class='select-field'>{subj_opts}</select><label class='label-red'>Class *</label><select name='class_name' required class='select-field'>{class_opts}</select><label class='label-red'>Stream *</label><select name='stream' required class='select-field'>{stream_opts}</select><label class='label-red'>Year *</label><select name='year' required class='select-field'>{year_opts}</select><label class='label-red'>Term *</label><select name='term' required class='select-field'>{term_opts}</select><label class='label-red'>Exam *</label><select name='exam_id' required class='select-field'>{exam_opts}</select><label class='label-red'>Out Of *</label><input name='out_of' required type='number' min='1' max='500' placeholder='Out Of' class='select-field'><button class='save-btn'>💾 Save Settings</button></form></div><div class='card-white'><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'><h3 style='margin:0;font-size:16px;font-weight:800'>Already Set Marks</h3><span style='font-size:11px;color:#64748b'>{len(configs)} records</span></div><div class='filter-bar'><select id='filterYear' class='filter-select' onchange='filterConfigs()'>{all_years_filter}</select><select id='filterTerm' class='filter-select' onchange='filterConfigs()'>{all_terms_filter}</select><select id='filterClass' class='filter-select' onchange='filterConfigs()'>{all_classes_filter}</select><input id='searchConfig' onkeyup='filterConfigs()' placeholder='🔍 Search...' style='padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;font-size:12px;min-width:130px'></div><div style='overflow:auto;max-height:70vh'><table id='configTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:10px 12px'><input type='checkbox'></th><th style='padding:10px 12px'>#</th><th>YEAR ↓</th><th>TERM</th><th>CLASS</th><th>SUBJECT</th><th>OUT OF</th><th>ACTION</th></tr></thead><tbody>{rows}</tbody></table></div><div style='display:flex;justify-content:space-between;margin-top:12px;font-size:12px;color:#64748b'><span>Show <select id='perPage' onchange='filterConfigs()' style='padding:4px;border:1px solid #e5e7eb;border-radius:6px'><option>10</option><option>25</option><option>50</option><option>100</option></select> items per page</span><span id='showing'>Showing 1-{len(configs)} of {len(configs)}</span></div></div></div></div><script>function filterConfigs(){{let q=document.getElementById('searchConfig').value.toLowerCase();let yf=document.getElementById('filterYear').value.toLowerCase();let tf=document.getElementById('filterTerm').value.toLowerCase();let cf=document.getElementById('filterClass').value.toLowerCase();let rows=document.querySelectorAll('.cfg-row');let visible=0;rows.forEach(r=>{{let ok=true;let txt=r.getAttribute('data-search');if(q &&!txt.includes(q)) ok=false;let tds=r.querySelectorAll('td');let year=tds[2].innerText.toLowerCase();let term=tds[3].innerText.toLowerCase();let cls=tds[4].innerText.toLowerCase();if(yf!=='all' && yf!=='' &&!year.includes(yf)) ok=false;if(tf!=='all' && tf!=='' &&!term.includes(tf)) ok=false;if(cf!=='all' && cf!=='' &&!cls.includes(cf)) ok=false;r.style.display=ok?'':'none';if(ok) visible++;}});document.getElementById('showing').innerText='Showing 1-'+visible+' of '+visible;}}</script>"""

# NEW EXACT RECORD MARKS WINDOW - ONLY ADDITION
def record_marks_exact_html(students, subject_name, exam_name, class_name, stream_name, out_of, total_count, filled_count, school_name, exam_id, subject_id, year, term):
    full_class = f"{class_name} {stream_name}".strip()
    rows = ""
    for idx, st in enumerate(students, 1):
        mv = st.get('marks','')
        dv = f"{mv}" if mv!="" and mv is not None else ""
        rows += f"""<tr class='stu-row' data-search="{(st['name'] or '').lower()} {str(st['admission_no'] or '').lower()}"><td style='padding:14px 12px;font-size:13px;color:#64748b'>{idx}</td><td style='padding:14px 12px;font-size:13px;font-weight:700'>{st['admission_no'] or ''}</td><td style='padding:14px 12px;font-size:13px;font-weight:600'>{st['name']}</td><td style='padding:14px 12px'><input type='number' min='0' max='{out_of}' step='0.01' id='mark_{st['id']}' value='{dv}' placeholder='/ {out_of}' onblur='autoSave({st['id']})' onkeydown='if(event.key==="Enter"){{autoSave({st['id']})}}' style='width:110px;padding:9px 12px;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;background:#fcfcfc;text-align:center'></td></tr>"""
    return f"""<style>.record-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden}}.badge{{padding:4px 10px;border-radius:12px;font-size:11px;font-weight:800;display:inline-block}}.badge-total{{background:#e0f2fe;color:#0369a1;border:1px solid #bae6fd}}.badge-filled{{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}}.badge-open{{background:#f1f5f9;color:#475569;border:1px solid #e2e8f0}}.filter-input{{padding:9px 12px 9px 32px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;min-width:200px}}.action-btn{{padding:9px 14px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.save-finish{{background:#0b3d91;color:white;padding:10px 18px;border:none;border-radius:10px;font-weight:800;cursor:pointer}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div class='record-card'><div style='padding:14px 18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px'><div style='display:flex;gap:16px;flex-wrap:wrap;font-size:13px'><span><span style='color:#64748b'>Subject:</span> <b>{subject_name}</b></span><span><span style='color:#64748b'>Exam:</span> <b>{exam_name}</b></span><span><span style='color:#64748b'>Class:</span> <b>{full_class}</b></span><span><span style='color:#64748b'>Out of:</span> <b>{out_of}</b></span></div><div style='display:flex;gap:8px'><span class='badge badge-total'>Total: {total_count}</span><span class='badge badge-filled' id='filledBadge'>Filled: {filled_count}</span><span class='badge badge-open'>open</span></div></div><div style='padding:12px 18px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;align-items:center;gap:8px;font-size:13px'><span style='color:#64748b'>Show</span><select id='perPage' onchange='changePerPage()' style='padding:6px 8px;border:1px solid #e2e8f0;border-radius:8px'><option value='10' selected>10</option><option value='25'>25</option><option value='50'>50</option><option value='100'>100</option><option value='1000'>All</option></select><span style='color:#64748b'>items per page</span></div><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='searchInput' onkeyup='filterStudents()' placeholder='Search by name or admno...' class='filter-input'></div><button class='action-btn' onclick='exportCSV()'>⬇️ Export CSV</button></div></div><div style='overflow:auto;max-height:62vh'><table id='marksTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#f8fafc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px'>#</th><th style='padding:12px'>ADMNO ↑</th><th style='padding:12px'>STUDENT NAME ↕️</th><th style='padding:12px'>MARKS ↕️</th></tr></thead><tbody id='tableBody'>{rows}</tbody></table></div><div style='padding:14px 18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;border-top:1px solid #f1f5f9'><div style='font-size:12px;color:#64748b'><span id='showingText'>Showing 1-10 of {total_count}</span><br><span id='enteredText'>{filled_count} of {total_count} marks entered</span><br><span style='font-size:11px'>Marks auto-save when you move to the next field. Click 'Save & Finish' when done to mark as recorded.</span></div><div style='display:flex;gap:10px;align-items:center'><div style='display:flex;gap:6px;align-items:center;font-size:12px'><button onclick='prevPage()' class='action-btn'>‹ Previous</button><span id='pageInfo'>Page 1</span><button onclick='nextPage()' class='action-btn'>Next ›</button></div><button onclick='saveFinish()' class='save-finish'>💾 Save & Finish</button></div></div></div></div><script>let currentPage=1; let perPage=10; let allRows=[]; window.onload=function(){{ allRows=Array.from(document.querySelectorAll('.stu-row')); updatePagination(); }}; function filterStudents(){{ currentPage=1; updatePagination(); }} function changePerPage(){{ perPage=parseInt(document.getElementById('perPage').value); currentPage=1; updatePagination(); }} function updatePagination(){{ let searchQ=document.getElementById('searchInput').value.toLowerCase(); let toShow=allRows.filter(r=>r.getAttribute('data-search').includes(searchQ)); let total=toShow.length; let start=(currentPage-1)*perPage; let end=start+perPage; allRows.forEach(r=>r.style.display='none'); toShow.slice(start,end).forEach(r=>r.style.display=''); document.getElementById('showingText').innerText='Showing '+(total==0?0:start+1)+'-'+Math.min(end,total)+' of {total_count}'; let totalPages=Math.ceil(total/perPage)||1; document.getElementById('pageInfo').innerText='Page '+currentPage+' of '+totalPages; }} function prevPage(){{ if(currentPage>1){{currentPage--; updatePagination();}} }} function nextPage(){{ let searchQ=document.getElementById('searchInput').value.toLowerCase(); let toShow=allRows.filter(r=>r.getAttribute('data-search').includes(searchQ)); let totalPages=Math.ceil(toShow.length/perPage)||1; if(currentPage<totalPages){{currentPage++; updatePagination();}} }} function autoSave(studentId){{ let input=document.getElementById('mark_'+studentId); let val=input.value; if(val==='' ) return; let num=parseFloat(val); if(num>{out_of}){{ input.value={out_of}; num={out_of}; }} input.style.border='1px solid #22c55e'; fetch('/school/record-marks/auto-save',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'student_id='+studentId+'&exam_id={exam_id}&subject_id={subject_id}&class_name={class_name}&stream={stream_name}&year={year}&term={term}&out_of={out_of}&marks='+num}}).then(r=>r.json()).then(data=>{{ if(data.ok){{ let filledCount=0; document.querySelectorAll('input[id^=mark_]').forEach(i=>{{if(i.value!=='') filledCount++;}}); document.getElementById('filledBadge').innerText='Filled: '+filledCount; document.getElementById('enteredText').innerText=filledCount+' of {total_count} marks entered'; }} }}); }} function saveFinish(){{ window.location.href='/school/dashboard'; }} function exportCSV(){{ let rows=document.querySelectorAll('.stu-row'); let csv=['#,ADMNO,STUDENT NAME,MARKS']; rows.forEach((r,i)=>{{ let tds=r.querySelectorAll('td'); let adm=tds[1].innerText; let name=tds[2].innerText; let inp=r.querySelector('input'); let mark=inp?inp.value:''; csv.push([i+1,adm,'"'+name+'"',mark].join(',')); }}); let b=new Blob([csv.join('\\n')],{{type:'text/csv'}}); let u=URL.createObjectURL(b); let a=document.createElement('a'); a.href=u; a.download='marks_{class_name}_{subject_name}_{exam_name}.csv'; a.click(); }}</script>"""
    # === CORE ROUTES — EXACT FROM YOUR PART 1 ===
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    failed_login = request.query_params.get("error") == "1"
    saved_username = escape(request.query_params.get("username", ""), quote=True)
    # Establish the tab-scoped session on the login POST itself. This avoids
    # a second-request cookie migration race on mobile browsers after sign-in.
    login_tab_id = request.query_params.get("ds_tab", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", login_tab_id):
        login_tab_id = secrets.token_urlsafe(24)
    error_html = ("<div class='err'><span class='err-icon'>!</span><div><strong>Sign-in failed.</strong><br>Incorrect username or password. Please check your details and try again.</div></div>" if failed_login else "")
    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#0b5135"><title>Mabale_ICT | Sign in</title><style>
:root{--forest:#0b5135;--forest-deep:#073c29;--green:#168451;--sage:#eaf4ed;--ink:#173b2b;--muted:#718278;--line:#dce8df}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;width:100%;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Arial,sans-serif}
body{min-height:100vh;display:grid;place-items:center;padding:34px;background:radial-gradient(ellipse at 12% 12%,rgba(190,224,199,.65),transparent 38%),linear-gradient(135deg,#edf5ef 0%,#f7faf7 52%,#e6f1e9 100%);color:var(--ink)}
.login-shell{width:min(680px,100%);min-height:520px;display:grid;grid-template-columns:1.08fr .92fr;background:#fff;border:1px solid rgba(13,77,48,.09);border-radius:28px;overflow:hidden;box-shadow:0 28px 90px rgba(15,62,39,.16)}
.brand-panel{position:relative;isolation:isolate;overflow:hidden;display:flex;flex-direction:column;justify-content:space-between;padding:48px 54px;color:#fff;background:linear-gradient(145deg,#073d2a 0%,#0b6040 55%,#168451 100%)}
.brand-panel:before,.brand-panel:after{content:"";position:absolute;z-index:-1;border:1px solid rgba(255,255,255,.12);border-radius:50%}
.brand-panel:before{width:560px;height:560px;right:-270px;top:-230px}
.brand-panel:after{width:420px;height:420px;left:-260px;bottom:-230px}
.brand-top{display:flex;align-items:center;gap:15px}
.brand-icon{width:54px;height:54px;flex:0 0 54px;border-radius:16px;display:grid;place-items:center;background:linear-gradient(145deg,#e6f4e9,#b9e4c8);box-shadow:0 10px 25px rgba(0,0,0,.15)}
.davi-mark{position:relative;width:48px;height:48px;display:block}
.davi-mark:before{content:"M";position:absolute;inset:0;display:grid;place-items:center;font-family:Georgia,"Times New Roman",serif;font-size:43px;font-weight:900;font-style:italic;line-height:1;color:#0b5135}
.brand-wordmark{font-family:Georgia,"Times New Roman",serif;font-size:25px;font-weight:800;letter-spacing:.1px;line-height:1.1}
.brand-subtitle{display:block;margin-top:6px;font-family:Arial,sans-serif;font-size:10px;font-weight:800;letter-spacing:2px;color:#ccebd7}
.brand-copy{max-width:490px;margin:64px 0 34px}
.eyebrow{display:inline-flex;align-items:center;gap:9px;margin-bottom:22px;color:#c8ead4;font-size:11px;font-weight:800;letter-spacing:2.1px;text-transform:uppercase}
.eyebrow:before{content:"";width:25px;height:2px;background:#a7dfbc}
.brand-copy h2{max-width:470px;margin:0 0 18px;font-family:Georgia,"Times New Roman",serif;font-size:clamp(37px,4.2vw,54px);line-height:1.08;letter-spacing:-1.1px;font-weight:700}
.brand-copy p{max-width:420px;margin:0;color:#d4eadd;font-size:15px;line-height:1.8}
.visual-stage{position:relative;height:205px;max-width:490px;margin:0 0 30px}
.visual-glow{position:absolute;width:230px;height:230px;right:24px;top:-28px;border-radius:50%;background:rgba(190,231,202,.12);filter:blur(2px)}
.school-card{position:absolute;right:14px;top:4px;width:min(330px,82%);padding:18px 20px 16px;border:1px solid rgba(255,255,255,.24);border-radius:18px;background:rgba(255,255,255,.13);backdrop-filter:blur(9px);box-shadow:0 18px 42px rgba(0,0,0,.16);transform:rotate(-3deg)}
.school-card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;color:#e7f5eb;font-size:11px;font-weight:700;letter-spacing:.5px}
.school-dot{width:8px;height:8px;border-radius:50%;background:#a6e5b9;box-shadow:0 0 0 4px rgba(166,229,185,.15)}
.school-card-title{font-family:Georgia,"Times New Roman",serif;font-size:20px;font-weight:700;margin-bottom:15px}
.school-bars{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}
.school-bar{height:54px;border-radius:10px;background:rgba(255,255,255,.13);padding:10px}
.school-bar:before{content:"";display:block;width:18px;height:4px;border-radius:4px;background:#c4e9cf;margin-bottom:9px}
.school-bar:after{content:"";display:block;width:75%;height:13px;border-radius:4px;background:rgba(255,255,255,.72)}
.brand-foot{display:flex;align-items:center;gap:9px;color:#cce6d5;font-size:11px;letter-spacing:.35px}
.brand-foot:before{content:"";width:22px;height:1px;background:#9ed8b2}
.login-panel{display:flex;flex-direction:column;justify-content:center;padding:62px clamp(34px,5.5vw,70px);background:#fff}
.login-kicker{margin-bottom:12px;color:#168451;font-size:11px;font-weight:800;letter-spacing:1.8px;text-transform:uppercase}
.login-title{margin:0 0 9px;color:#173b2b;font-family:Georgia,"Times New Roman",serif;font-size:36px;font-weight:700;letter-spacing:-.7px}
.sub{margin:0 0 34px;color:#77877d;font-size:14px;line-height:1.6}
.err{display:flex;gap:10px;align-items:flex-start;margin:0 0 18px;padding:13px 14px;border:1px solid #fecaca;border-radius:12px;background:#fff5f5;color:#991b1b;font-size:13px;line-height:1.5}
.err-icon{width:20px;height:20px;flex:0 0 20px;border-radius:50%;background:#dc2626;color:#fff;text-align:center;font-weight:900;line-height:20px}
form{width:100%}
label{display:block;margin:18px 0 8px;color:#294c39;font-size:12px;font-weight:800;letter-spacing:.25px}
.input{width:100%;height:52px;padding:0 15px;border:1px solid #d9e5dc;border-radius:12px;background:#fbfdfb;color:#183d2b;font:inherit;font-size:14px;outline:none;transition:border-color .18s,box-shadow .18s,background .18s}
.input::placeholder{color:#a2afa6}
.input:focus{border-color:#168451;background:#fff;box-shadow:0 0 0 4px rgba(22,132,81,.11)}
.password-wrap{position:relative;width:100%}
.password-wrap .input{padding-right:70px}
.password-toggle{position:absolute;right:10px;top:50%;transform:translateY(-50%);padding:7px 8px;border:0;border-radius:7px;background:transparent;color:#168451;font-size:11px;font-weight:800;cursor:pointer}
.password-toggle:hover{background:#edf6ef}
.sign{width:100%;height:52px;margin-top:27px;border:0;border-radius:12px;background:linear-gradient(110deg,#0b5135,#168451);color:#fff;font-size:14px;font-weight:800;letter-spacing:.25px;cursor:pointer;box-shadow:0 10px 22px rgba(11,81,53,.2);transition:transform .18s,box-shadow .18s}
.sign:hover{transform:translateY(-2px);box-shadow:0 14px 26px rgba(11,81,53,.25)}
.sign:focus-visible,.password-toggle:focus-visible{outline:3px solid #91d7ab;outline-offset:3px}
.login-note{margin-top:26px;padding-top:19px;border-top:1px solid #edf2ee;color:#8a988f;font-size:11px;line-height:1.6;text-align:center}
@media(max-width:760px){body{display:block;min-height:100vh;padding:16px;background:#edf5ef}.login-shell{width:100%;min-height:0;grid-template-columns:1fr;border-radius:22px}.brand-panel{padding:25px 25px 22px}.brand-top{gap:12px}.brand-icon{width:46px;height:46px;flex-basis:46px;border-radius:13px}.davi-mark{width:42px;height:42px}.davi-mark:before{font-size:38px}.brand-wordmark{font-size:22px}.brand-subtitle{font-size:9px;letter-spacing:1.5px}.brand-copy{margin:34px 0 18px}.eyebrow{margin-bottom:13px;font-size:9px}.brand-copy h2{font-size:32px;max-width:390px}.brand-copy p{font-size:13px;line-height:1.65}.visual-stage{height:120px;margin:0 0 8px}.school-card{right:3px;top:0;width:245px;padding:12px 14px}.school-card-title{font-size:16px;margin-bottom:10px}.school-card-head{margin-bottom:10px}.school-bar{height:36px;padding:7px}.school-bar:before{margin-bottom:5px}.school-bar:after{height:9px}.visual-glow{width:160px;height:160px;right:10px;top:-20px}.brand-foot{font-size:10px}.login-panel{padding:34px 26px 30px}.login-title{font-size:31px}.sub{margin-bottom:22px}}
@media(max-width:380px){body{padding:10px}.brand-panel{padding:22px 20px 18px}.login-panel{padding:29px 20px 25px}.brand-copy h2{font-size:29px}.school-card{width:220px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{transition:none!important}}
</style></head><body><main class="login-shell"><section class="brand-panel" aria-label="Mabale_ICT introduction"><div class="brand-top"><div class="brand-icon" aria-label="Mabale_ICT logo"><span class="davi-mark"></span></div><div class="brand-wordmark">Mabale_ICT<span class="brand-subtitle">SCHOOL MANAGEMENT SYSTEM</span></div></div><div class="brand-copy"><div class="eyebrow">A smarter way to manage schools</div><h2>Everything your school needs, in one place.</h2></div><div class="visual-stage" aria-hidden="true"><div class="visual-glow"></div><div class="school-card"><div class="school-card-head"><span>SCHOOL OVERVIEW</span><span class="school-dot"></span></div><div class="school-card-title">Your school, connected.</div><div class="school-bars"><div class="school-bar"></div><div class="school-bar"></div><div class="school-bar"></div></div></div></div><div class="brand-foot">Secure access for your school community</div></section><section class="login-panel"><h1 class="login-title">Welcome back</h1><p class="sub">Sign in with your school account to continue.</p>__LOGIN_ERROR__<form method="post" action="/login"><input type="hidden" name="ds_tab" value="__LOGIN_TAB__"><label for="login-username">Username or email</label><input id="login-username" name="email" class="input" type="text" value="__LOGIN_USERNAME__" placeholder="Enter your username or email" autocomplete="username" autocapitalize="none" spellcheck="false" required><label for="login-password">Password</label><div class="password-wrap"><input id="login-password" name="password" class="input" type="password" placeholder="Enter your password" autocomplete="current-password" required__LOGIN_FOCUS__><button type="button" class="password-toggle" aria-label="Show password" onclick="var i=document.getElementById('login-password');i.type=i.type==='password'?'text':'password';this.textContent=i.type==='password'?'Show':'Hide';this.setAttribute('aria-label',i.type==='password'?'Show password':'Hide password');i.focus();">Show</button></div><button class="sign" type="submit">Sign In</button></form></section></main></body></html>"""
    page = page.replace("__LOGIN_ERROR__", error_html).replace("__LOGIN_USERNAME__", saved_username).replace("__LOGIN_FOCUS__", " autofocus" if failed_login else "").replace("__LOGIN_TAB__", escape(login_tab_id, quote=True))
    # Keep the login form's tab ID aligned with this browser tab. A new tab
    # gets its own server-issued ID; a returning tab reuses its existing ID.
    page = page.replace("</body></html>", """<script>
(function () {
  try {
    var key = "davischool_tab_id";
    var field = document.querySelector("form input[name='ds_tab']");
    if (!field) return;
    var url = new URL(window.location.href);
    var forceNew = url.searchParams.get("ds_tab_new") === "1";
    var current = sessionStorage.getItem(key) || "";
    var urlId = url.searchParams.get("ds_tab") || "";
    var valid = /^[A-Za-z0-9_-]{16,64}$/;
    function newTabId() {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, "");
      return Date.now().toString(36) + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    }
    // A fresh browser tab must not adopt a ds_tab copied from another tab's URL.
    // The server-issued field value is used for forced new tabs; otherwise
    // create a new identity when this tab has no tab-scoped storage yet.
    var id = forceNew ? field.value : (valid.test(current) ? current : newTabId());
    if (!valid.test(id)) return;
    field.value = id;
    sessionStorage.setItem(key, id);
    url.searchParams.delete("ds_tab_new");
    url.searchParams.delete("ds_tab_source");
    url.searchParams.set("ds_tab", id);
    if (url.search !== window.location.search) {
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
  } catch (_) {}
})();
</script></body></html>""")
    return HTMLResponse(page, headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0"})

@app.head("/")
def home_head(): return PlainTextResponse("OK")
@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    try:
        cur = con.cursor()
        # Keep the login schema in sync with the School Users account schema.
        # This is additive only; it never changes existing academic records.
        try:
            cur.execute("SELECT * FROM users LIMIT 0")
            columns = {str(col.name if hasattr(col, "name") else col[0]).lower() for col in (cur.description or [])}
            definitions = {"username":"TEXT","teacher_id":"INTEGER","student_id":"INTEGER","temporary_password":"TEXT","must_change_password":"INTEGER DEFAULT 0"}
            for column, definition in definitions.items():
                if column not in columns:
                    cur.execute("ALTER TABLE users ADD COLUMN %s %s" % (column, definition))
            con.commit()
        except Exception as schema_exc:
            print("DAVISCHOOL LOGIN SCHEMA WARNING:", repr(schema_exc), flush=True)

        login_id = email.strip()
        # Prefer the exact generated username first. This prevents an older
        # account sharing the same email from being selected before the account
        # whose credentials are currently being used.
        u = cur.execute(
            "SELECT * FROM users WHERE lower(trim(COALESCE(username,'')))=lower(trim(?)) ORDER BY id DESC LIMIT 1",
            (login_id,)
        ).fetchone()
        # Parent usernames are phone numbers. Match equivalent Kenyan formats
        # (07..., 2547..., +2547...) without changing the stored username.
        if not u:
            phone_digits = re.sub(r"\D", "", login_id)
            phone_key = ("254" + phone_digits[1:]) if len(phone_digits) == 10 and phone_digits.startswith("0") else (("254" + phone_digits) if len(phone_digits) == 9 else phone_digits)
            if len(phone_key) >= 9:
                try:
                    parent_candidates = cur.execute("SELECT * FROM users WHERE lower(trim(COALESCE(role,'')))='parent' ORDER BY id DESC").fetchall()
                    for candidate in parent_candidates:
                        stored_phone = re.sub(r"\D", "", str(candidate["username"] or candidate["email"] or ""))
                        stored_key = ("254" + stored_phone[1:]) if len(stored_phone) == 10 and stored_phone.startswith("0") else (("254" + stored_phone) if len(stored_phone) == 9 else stored_phone)
                        if stored_key == phone_key:
                            u = candidate
                            break
                except Exception as phone_lookup_exc:
                    print("DAVISCHOOL PARENT PHONE LOOKUP WARNING:", repr(phone_lookup_exc), flush=True)
        if not u:
            u = cur.execute(
                "SELECT * FROM users WHERE lower(trim(COALESCE(email,'')))=lower(trim(?)) ORDER BY id DESC LIMIT 1",
                (login_id,)
            ).fetchone()
        # The sign-in form is labelled "Username or Email". School-created
        # accounts historically stored only an email, so also accept the
        # account full name and linked teacher profile name as identifiers.
        if not u:
            u = cur.execute("""SELECT u.* FROM users u
                WHERE lower(trim(COALESCE(u.full_name,'')))=lower(trim(?))
                ORDER BY u.id DESC LIMIT 1""", (login_id,)).fetchone()
        if not u:
            try:
                u = cur.execute("""SELECT u.* FROM users u
                    JOIN teachers t ON t.id=u.teacher_id AND t.school_id=u.school_id
                    WHERE lower(trim(COALESCE(t.name,'')))=lower(trim(?))
                    ORDER BY u.id DESC LIMIT 1""", (login_id,)).fetchone()
            except Exception:
                u = None
        # Also accept the username portion of an account email (the value
        # commonly given to staff as their username).
        if not u and "@" not in login_id:
            try:
                all_users = cur.execute("SELECT * FROM users WHERE email IS NOT NULL").fetchall()
                wanted = login_id.casefold()
                for candidate in all_users:
                    candidate_email = str(candidate["email"] or "").strip()
                    if candidate_email and candidate_email.split("@",1)[0].casefold() == wanted:
                        u = candidate
                        break
            except Exception:
                pass
        # Older student records may predate automatic parent-account creation.
        # On the first valid parent sign-in, provision the account from the
        # matching student's phone + admission-number@current-year credential.
        if not u:
            try:
                phone_digits = re.sub(r"\D", "", login_id)
                phone_key = ("254" + phone_digits[1:]) if len(phone_digits) == 10 and phone_digits.startswith("0") else (("254" + phone_digits) if len(phone_digits) == 9 else phone_digits)
                current_year = datetime.now(ZoneInfo("Africa/Nairobi")).year
                if len(phone_key) >= 9:
                    student_rows = cur.execute("""SELECT * FROM students
                        WHERE COALESCE(parent_phone,'')<>'' ORDER BY id DESC""").fetchall()
                    matching_students = []
                    for student in student_rows:
                        stored_digits = re.sub(r"\D", "", str(student["parent_phone"] or ""))
                        stored_key = ("254" + stored_digits[1:]) if len(stored_digits) == 10 and stored_digits.startswith("0") else (("254" + stored_digits) if len(stored_digits) == 9 else stored_digits)
                        if stored_key == phone_key:
                            matching_students.append(student)
                    valid_student = next((student for student in matching_students
                        if str(student["admission_no"] or "").strip()
                        and hmac.compare_digest(str(password or ""), str(student["admission_no"]).strip() + "@" + str(current_year))), None)
                    if valid_student:
                        target_school_id = valid_student["school_id"]
                        created_account = None
                        ordered_students = [valid_student] + [student for student in matching_students if int(student["id"]) != int(valid_student["id"])]
                        for student in ordered_students:
                            if student["school_id"] != target_school_id:
                                continue
                            parent_result = _create_or_link_parent_access(
                                cur, target_school_id, int(student["id"]),
                                str(student["admission_no"] or ""),
                                str(student["parent_name"] or "") if "parent_name" in student.keys() else "",
                                str(student["parent_phone"] or "")
                            )
                            if parent_result:
                                created_account = parent_result
                        if created_account:
                            con.commit()
                            u = cur.execute("""SELECT * FROM users
                                WHERE school_id=? AND role='parent'
                                  AND lower(trim(COALESCE(username,'')))=lower(trim(?))
                                ORDER BY id DESC LIMIT 1""",
                                (target_school_id, created_account["username"])).fetchone()
            except Exception as parent_provision_exc:
                print("DAVISCHOOL PARENT LOGIN PROVISION WARNING:", repr(parent_provision_exc), flush=True)
        if not u:
            return RedirectResponse("/?error=1&username=" + quote(login_id, safe=""), status_code=303)
        valid, legacy_password = verify_password(password, u["password"])
        # A parent may have used a sibling's admission number when the shared
        # account was first created. During first login only, accept the
        # documented admission-number@current-year credential for any linked
        # child, then persist its hash and still require an immediate change.
        if not valid and str(u["role"] or "").strip().lower() == "parent":
            try:
                must_change = bool(u["must_change_password"]) if "must_change_password" in u.keys() else False
                if must_change:
                    current_year = datetime.now(ZoneInfo("Africa/Nairobi")).year
                    linked_admissions = []
                    try:
                        linked_rows = cur.execute("""SELECT s.admission_no
                            FROM parent_student_links p
                            JOIN students s ON s.id=p.student_id AND s.school_id=p.school_id
                            WHERE p.user_id=? AND p.school_id=?""",
                            (u["id"], u["school_id"])).fetchall()
                        linked_admissions.extend(str(row["admission_no"] or "").strip() for row in linked_rows)
                    except Exception:
                        pass
                    if u["student_id"]:
                        own_student = cur.execute("SELECT admission_no FROM students WHERE id=? AND school_id=?",
                            (u["student_id"], u["school_id"])).fetchone()
                        if own_student:
                            linked_admissions.append(str(own_student["admission_no"] or "").strip())
                    submitted = str(password or "")
                    if any(adm and hmac.compare_digest(submitted, adm + "@" + str(current_year)) for adm in linked_admissions):
                        cur.execute("UPDATE users SET password=? WHERE id=?", (hash_password(submitted), u["id"]))
                        con.commit()
                        valid = True
                        legacy_password = True
            except Exception as parent_password_exc:
                print("DAVISCHOOL PARENT FIRST LOGIN WARNING:", repr(parent_password_exc), flush=True)
        # Every School Users account stores the exact generated credential in
        # temporary_password. If the stored hash was created incorrectly or
        # belongs to an older account-migration format, accept only that exact
        # generated credential and immediately replace the stored value with a
        # fresh PBKDF2 hash. This does not alter marks or any academic record.
        if not valid:
            try:
                temporary_password = str(u["temporary_password"] or "") if "temporary_password" in u.keys() else ""
            except Exception:
                temporary_password = ""
            if temporary_password:
                submitted_temporary = str(password or "")
                if hmac.compare_digest(submitted_temporary, temporary_password) or hmac.compare_digest(submitted_temporary.strip(), temporary_password):
                    try:
                        cur.execute("UPDATE users SET password=? WHERE id=?", (hash_password(temporary_password), u["id"]))
                        con.commit()
                        valid = True
                        legacy_password = True
                    except Exception as repair_exc:
                        print("DAVISCHOOL LOGIN PASSWORD REPAIR WARNING:", repr(repair_exc), flush=True)
                        valid = False
        if not valid:
            return RedirectResponse("/?error=1&username=" + quote(login_id, safe=""), status_code=303)
        user_id=u["id"]; user_email=u["email"]; role=u["role"]; full_name=u["full_name"]; school_id=u["school_id"] or 0
        # Every school-linked account is blocked when its school is suspended.
        # Super Admin accounts are platform-level and may not have a school_id.
        if school_id and role != "super_admin":
            school = cur.execute("SELECT status FROM schools WHERE id=?", (school_id,)).fetchone()
            school_status = str(school["status"] or "active").strip().lower() if school else "suspended"
            if school_status not in ("active", "enabled"):
                return HTMLResponse("❌ This school account is suspended. Please contact the Mabale_ICT administrator. <a href='/'>Back</a>", status_code=403)
    except Exception as exc:
        print("DAVISCHOOL LOGIN ERROR:", repr(exc), flush=True)
        return HTMLResponse("Mabale_ICT could not complete the sign-in request. Please try again.", status_code=500)
    finally:
        con.close()
    request.session["user_id"]=user_id; request.session["email"]=(str(u["username"] or user_email) if role == "parent" else user_email); request.session["role"]=role
    request.session["name"]=full_name; request.session["school_id"]=school_id
    # Preserve the linked profile created in School Users so dedicated portals
    # can identify the correct teacher/student/parent after sign-in.
    request.session["teacher_id"]=u["teacher_id"] if "teacher_id" in u.keys() else None
    request.session["student_id"]=u["student_id"] if "student_id" in u.keys() else None
    request.session["is_impersonating"]=False
    must_change_parent_password = bool(u["must_change_password"]) if role == "parent" and "must_change_password" in u.keys() else False
    if must_change_parent_password:
        request.session["must_change_password"] = True
        return RedirectResponse("/account/change-password?first_login=1", status_code=303)
    return RedirectResponse("/app", status_code=303)
@app.get("/account/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    return HTMLResponse("""<html><body style='font-family:Arial;background:#f8fafc;padding:30px'><div style='max-width:520px;margin:auto;background:white;padding:24px;border-radius:16px;border:1px solid #e2e8f0'><h2>Change Password</h2><form method='post'><input name='current_password' type='password' required placeholder='Current password' style='width:100%;padding:12px;margin:6px 0;box-sizing:border-box'><input name='new_password' type='password' required minlength='10' placeholder='New password (10+ characters)' style='width:100%;padding:12px;margin:6px 0;box-sizing:border-box'><input name='confirm_password' type='password' required minlength='10' placeholder='Confirm new password' style='width:100%;padding:12px;margin:6px 0;box-sizing:border-box'><button style='background:#0b3d91;color:white;border:0;border-radius:10px;padding:12px 18px;margin-top:8px'>Update Password</button></form></div></body></html>""")
@app.post("/account/change-password")
def change_password(request: Request,current_password:str=Form(...),new_password:str=Form(...),confirm_password:str=Form(...)):
    if "email" not in request.session: return RedirectResponse("/",303)
    if len(new_password) < 10 or new_password != confirm_password: return HTMLResponse("Invalid new password. Use at least 10 characters and ensure both fields match. <a href='/account/change-password'>Back</a>",400)
    con=get_db(); cur=con.cursor(); u=cur.execute("SELECT * FROM users WHERE id=?",(request.session.get('user_id',0),)).fetchone()
    if not u: u=cur.execute("SELECT * FROM users WHERE lower(email)=lower(?)",(request.session.get('email',''),)).fetchone()
    if not u or not verify_password(current_password,u['password'])[0]: con.close(); return HTMLResponse("Current password is incorrect. <a href='/account/change-password'>Back</a>",403)
    cur.execute("UPDATE users SET password=? WHERE id=?",(hash_password(new_password),u['id']))
    if str(request.session.get("role") or "") == "parent":
        try:
            cur.execute("UPDATE users SET must_change_password=0 WHERE id=?", (u["id"],))
        except Exception:
            pass
        try:
            cur.execute("UPDATE parent_access_credentials SET password_cipher=NULL WHERE user_id=?", (u["id"],))
        except Exception:
            pass
    ts=datetime.now(ZoneInfo('Africa/Nairobi')).strftime('%Y-%m-%d %H:%M:%S'); cur.execute("INSERT INTO system_audit(school_id,user_email,action,details,timestamp) VALUES(?,?,?,?,?)",(u['school_id'] or 0,u['email'],'PASSWORD_CHANGE','Password changed',ts)); con.commit(); con.close()
    if str(request.session.get("role") or "") == "parent":
        request.session["must_change_password"] = False
        return RedirectResponse("/app/parent", 303)
    return RedirectResponse('/account/change-password',303)

@app.get("/logout")
def logout(request: Request):
    if request.session.get("is_portal_preview"):
        request.session["role"] = "super_admin"
        request.session["school_id"] = 0
        request.session["user_id"] = request.session.pop("_preview_admin_user_id", 0)
        request.session["email"] = request.session.pop("_preview_admin_email", "")
        request.session["name"] = request.session.pop("_preview_admin_name", "Super Administrator")
        for key in ("teacher_id", "student_id", "is_portal_preview", "is_impersonating", "preview_portal", "preview_school_id"):
            request.session.pop(key, None)
        return RedirectResponse("/super/portal-management", 303)
    request.session.clear()
    return RedirectResponse("/")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    if request.session.get("role") == "school_admin":
        return RedirectResponse("/school/dashboard")
    if request.session.get("role") != "super_admin":
        return RedirectResponse("/")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM schools WHERE lower(COALESCE(email,''))<>'portal-demo@davischool.invalid'")
    total = int(cur.fetchone()["c"] or 0)
    cur.execute("SELECT COUNT(*) c FROM schools WHERE lower(COALESCE(email,''))<>'portal-demo@davischool.invalid' AND lower(COALESCE(status,'active')) IN ('active','enabled')")
    active = int(cur.fetchone()["c"] or 0)
    suspended = max(0, total-active)
    # Only records belonging to registered schools count in platform totals.
    cur.execute("SELECT COUNT(*) c FROM students st INNER JOIN schools s ON s.id=st.school_id")
    learners = int(cur.fetchone()["c"] or 0)
    cur.execute("SELECT COUNT(*) c FROM teachers t INNER JOIN schools s ON s.id=t.school_id")
    staff = int(cur.fetchone()["c"] or 0)
    cur.execute("SELECT COUNT(*) c FROM users u INNER JOIN schools s ON s.id=u.school_id WHERE lower(COALESCE(u.role,'')) IN ('school_admin','registrar')")
    accounts = int(cur.fetchone()["c"] or 0)
    cur.execute("""SELECT COUNT(*) c FROM pending_schools p
                   WHERE NOT EXISTS (SELECT 1 FROM system_audit a
                     WHERE a.action='SCHOOL_DELETE'
                       AND lower(trim(COALESCE(p.name,''))) =
                           lower(trim(replace(COALESCE(a.details,''),'Deleted school ',''))))""")
    pending = int(cur.fetchone()["c"] or 0)
    try:
        cur.execute("SELECT COALESCE(SUM(CASE WHEN lower(COALESCE(status,'')) IN ('paid','complete','completed') THEN CAST(amount AS REAL) ELSE 0 END),0) total FROM billing")
        revenue = float(cur.fetchone()["total"] or 0)
    except Exception:
        revenue = 0.0
    cur.execute("SELECT school_type,COUNT(*) c FROM schools WHERE lower(COALESCE(email,''))<>'portal-demo@davischool.invalid' GROUP BY school_type ORDER BY school_type")
    school_types = cur.fetchall()
    cur.execute("""SELECT s.id,s.name,s.location,s.school_type,s.status,COUNT(DISTINCT st.id) learners
                   FROM schools s LEFT JOIN students st ON st.school_id=s.id
                   WHERE lower(COALESCE(s.email,''))<>'portal-demo@davischool.invalid'
                   GROUP BY s.id,s.name,s.location,s.school_type,s.status
                   ORDER BY s.id DESC LIMIT 10""")
    recent = cur.fetchall()
    cur.execute("""SELECT s.id,s.name FROM schools s
                   LEFT JOIN users u ON u.school_id=s.id AND lower(COALESCE(u.role,''))='school_admin'
                   WHERE lower(COALESCE(s.email,''))<>'portal-demo@davischool.invalid'
                   GROUP BY s.id,s.name HAVING COUNT(u.id)=0 ORDER BY s.name""")
    no_admin = cur.fetchall()
    con.close()
    name = request.session.get("name","Super Administrator")
    email = request.session.get("email","")
    initials = "".join(p[0] for p in name.split()[:2]).upper()
    safe = lambda v: str(v or "—").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")
    type_total = max(1,sum(int(r["c"] or 0) for r in school_types))
    type_html = "".join("<div class='type-row'><span>{}</span><div><i style='width:{:.1f}%'></i></div><b>{}</b></div>".format(safe(r["school_type"] or "Unspecified"),int(r["c"] or 0)/type_total*100,int(r["c"] or 0)) for r in school_types) or "<p class='muted'>No registered schools yet.</p>"
    school_html = "".join("<tr><td><b>{}</b><small>{}</small></td><td>{}</td><td>{:,}</td><td><span class='status {}'>{}</span></td><td><a href='/schools/profile/{}'>Profile →</a></td></tr>".format(safe(r["name"]),safe(r["location"]),safe(r["school_type"]),int(r["learners"] or 0),"active" if str(r["status"] or "active").lower() in ("active","enabled") else "suspended","Active" if str(r["status"] or "active").lower() in ("active","enabled") else "Suspended",int(r["id"])) for r in recent) or "<tr><td colspan='5' class='empty'>No schools have been registered.</td></tr>"
    alerts = []
    if pending: alerts.append("<a href='/schools/manage#pending-schools'>{} school registration request(s) awaiting verification</a>".format(pending))
    if no_admin: alerts.append("<a href='/schools/manage'>{} school(s) have no School Admin account</a>".format(len(no_admin)))
    if suspended: alerts.append("<a href='/schools/manage?status=suspended'>{} suspended school account(s)</a>".format(suspended))
    alert_html = "".join("<div class='alert'>• {}</div>".format(x) for x in alerts) or "<div class='healthy'>No outstanding platform alerts from the available checks.</div>"
    header = header_html(initials,name,email)
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Mabale_ICT Platform Overview</title>
    <style>
    *{{box-sizing:border-box}}body{{margin:0;font-family:Arial;background:#f1f8f1;color:#203126}}.wrap{{max-width:1480px;margin:auto;padding:22px}}
    .hero{{background:linear-gradient(120deg,#14532d,#166534 65%,#23834a);color:white;padding:24px;border-radius:17px;display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:16px}}.hero h1{{margin:0;font-size:23px}}.hero p{{margin:7px 0 0;color:#d8f0dc;font-size:12px}}.actions{{display:flex;gap:8px;flex-wrap:wrap}}.actions a{{background:white;color:#14532d;padding:10px 13px;border-radius:9px;text-decoration:none;font-size:12px;font-weight:800}}
    .stats{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:11px;margin-bottom:15px}}.stat{{display:block;background:white;border:1px solid #dce9dc;border-radius:13px;padding:16px;text-decoration:none;color:#14532d}}.stat span{{font-size:10px;color:#718477;font-weight:800}}.stat b{{display:block;font-size:27px;margin:8px 0 4px}}.stat small{{font-size:10px;color:#718477}}
    .layout{{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(270px,.85fr);gap:14px}}.layout>div,.panel{{min-width:0}}.panel{{background:white;border:1px solid #dce9dc;border-radius:14px;margin-bottom:14px;overflow:hidden}}.panel-head{{padding:14px 16px;border-bottom:1px solid #edf3ed;display:flex;justify-content:space-between;gap:10px;align-items:center}}.panel-head b{{font-size:14px}}.panel-head a,.panel a{{color:#166534;text-decoration:none;font-size:11px;font-weight:800}}.panel-body{{padding:15px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px;text-align:left;border-bottom:1px solid #edf3ed;font-size:11px}}th{{font-size:10px;background:#f7fbf7;color:#718477}}td small{{display:block;color:#718477;margin-top:4px}}.status{{padding:4px 8px;border-radius:18px;font-size:10px;font-weight:800}}.status.active{{background:#dcfce7;color:#166534}}.status.suspended{{background:#fee2e2;color:#991b1b}}.table-scroll{{display:block;width:100%;max-width:100%;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;overscroll-behavior-x:contain;scrollbar-width:thin}}.table-scroll table{{width:max-content;min-width:100%;border-collapse:collapse}}.type-row{{display:flex;align-items:center;gap:8px;margin:12px 0;font-size:11px}}.type-row span{{flex:1}}.type-row div{{width:38%;height:8px;background:#edf4ed;border-radius:10px;overflow:hidden}}.type-row i{{display:block;height:100%;background:#2f855a;border-radius:10px}}.type-row b{{min-width:20px;text-align:right}}.activity{{display:flex;justify-content:space-between;gap:10px;padding:11px 0;border-bottom:1px solid #edf3ed;font-size:11px}}.activity:last-child{{border:0}}.activity small{{display:block;color:#718477;margin-top:4px}}.activity time{{font-size:10px;color:#718477;white-space:nowrap}}.alert{{padding:10px 0;border-bottom:1px solid #edf3ed;font-size:11px}}.alert a{{color:#8a5a00}}.healthy{{padding:11px;background:#e9f6eb;color:#166534;border-radius:9px;font-size:11px}}.muted,.empty{{color:#94a3b8;font-size:11px}}.empty{{text-align:center;padding:22px}}
    @media(max-width:1050px){{.stats{{grid-template-columns:repeat(3,1fr)}}}}@media(max-width:760px){{.wrap{{padding:12px}}.hero{{align-items:flex-start;flex-direction:column}}.hero h1{{font-size:20px}}.stats{{grid-template-columns:repeat(2,minmax(0,1fr))}}.layout{{grid-template-columns:minmax(0,1fr)}}.table-scroll{{cursor:grab;scrollbar-width:thin}}.table-scroll:active{{cursor:grabbing}}.table-scroll table{{min-width:620px;width:max-content}}}}
    </style></head><body>{header}<main class='wrap'>
    <section class='hero'><div><h1>Mabale_ICT Platform Overview</h1><p>Manage registered schools and monitor platform-wide school operations.</p></div><div class='actions'><a href='/super/portal-management'>▦ Portal Management</a><a href='/schools/manage'>＋ Manage Schools</a></div></section>
    <section class='stats'>
    <a class='stat' href='/schools/manage'><span>REGISTERED SCHOOLS</span><b>{total:,}</b><small>All school accounts</small></a>
    <a class='stat' href='/schools/manage?status=active'><span>ACTIVE SCHOOLS</span><b>{active:,}</b><small>Enabled accounts</small></a>
    <a class='stat' href='/schools/manage?status=suspended'><span>SUSPENDED SCHOOLS</span><b>{suspended:,}</b><small>Restricted accounts</small></a>
    <a class='stat' href='/schools/manage'><span>LEARNERS</span><b>{learners:,}</b><small>In currently registered schools</small></a>
    <a class='stat' href='/schools/manage'><span>STAFF</span><b>{staff:,}</b><small>{accounts:,} admin / registrar accounts in registered schools</small></a>
    </section>
    <section class='layout'><div>
    <section class='panel'><div class='panel-head'><b>Recently Added Schools</b><a href='/schools/manage'>View all →</a></div><div class='table-scroll'><table><thead><tr><th>SCHOOL</th><th>LEVEL</th><th>LEARNERS</th><th>STATUS</th><th></th></tr></thead><tbody>{school_html}</tbody></table></div></section>
    </div><div>
    <section class='panel'><div class='panel-head'><b>School Distribution</b></div><div class='panel-body'>{type_html}</div></section>
    <section class='panel'><div class='panel-head'><b>Attention Required</b></div><div class='panel-body'>{alert_html}</div></section>
    <section class='panel'><div class='panel-head'><b>Platform Billing Summary</b></div><div class='panel-body'><span class='muted'>RECORDED PAID / COMPLETED BILLING</span><div style='font-size:25px;color:#14532d;font-weight:900;margin:8px 0'>KES {revenue:,.2f}</div><span class='muted'>Based on billing records; this is not a live subscription entitlement check.</span></div></section>
    </div></section></main></body></html>""")

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = "", message: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com"); initials = "".join([p[0] for p in name.split()][:2]).upper()
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE lower(COALESCE(email,''))<>? ORDER BY id DESC", ("portal-demo@davischool.invalid",)); schools = cur.fetchall(); cur.execute("SELECT * FROM users WHERE role IN ('school_admin','registrar') ORDER BY id"); users = cur.fetchall(); cur.execute("""SELECT u.id,u.full_name,u.email,u.username,u.school_id,u.teacher_id,s.name AS school_name,t.name AS teacher_name,t.phone AS teacher_phone,t.role AS teacher_role FROM users u LEFT JOIN schools s ON s.id=u.school_id LEFT JOIN teachers t ON t.id=u.teacher_id WHERE lower(COALESCE(u.role,''))='registrar' ORDER BY u.id DESC"""); registrars = cur.fetchall(); cur.execute("""SELECT p.* FROM pending_schools p
                   WHERE NOT EXISTS (SELECT 1 FROM system_audit a
                     WHERE a.action='SCHOOL_DELETE'
                       AND lower(trim(COALESCE(p.name,''))) =
                           lower(trim(replace(COALESCE(a.details,''),'Deleted school ',''))))
                   ORDER BY p.id DESC"""); pending_schools = cur.fetchall(); cur.execute("SELECT school_id,MAX(timestamp) AS last_activity FROM system_audit GROUP BY school_id"); last_activity_by_school = {int(r["school_id"] or 0): r["last_activity"] for r in cur.fetchall()}; pending=None
    if pending_id: cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    con.close(); users_by_school = {u["school_id"]: u for u in users}
    popup=""
    if success=="invalid_code":
        popup=f"""<div style='margin-bottom:16px;background:#fff1f2;border:2px solid #fb7185;border-radius:14px;padding:18px'><div style='font-size:18px;font-weight:900;color:#9f1239'>❌ Verification code is incorrect</div><div style='margin-top:8px;color:#475569'>Please enter the 6-digit code shown for this school.</div></div>"""
    elif success=="verify_error":
        safe = (message or "The school account could not be created.").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        popup=f"""<div style='margin-bottom:16px;background:#fff1f2;border:2px solid #fb7185;border-radius:14px;padding:18px'><div style='font-size:18px;font-weight:900;color:#9f1239'>❌ Verification failed</div><div style='margin-top:8px;color:#475569'>The school was not partially created. Try the verification again.</div><div style='margin-top:10px;font-family:monospace;font-size:12px;word-break:break-word'>{safe}</div></div>"""
    elif success=="email_error":
        popup="""<div style='margin-bottom:16px;background:#fff1f2;border:2px solid #fb7185;border-radius:14px;padding:18px'><div style='font-size:18px;font-weight:900;color:#9f1239'>❌ Verification email could not be sent</div><div style='margin-top:8px;color:#475569'>The school registration was not saved. Please check the email service configuration and try again.</div></div>"""
    elif success=="register_error":
        safe = (message or "The school could not be registered. Please review the details and try again.").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        popup=f"""<div style='margin-bottom:16px;background:#fff1f2;border:2px solid #fb7185;border-radius:14px;padding:18px'><div style='font-size:18px;font-weight:900;color:#9f1239'>❌ School registration failed</div><div style='margin-top:8px;color:#475569'>{safe}</div></div>"""
    elif success=="already_added":
        popup=f"""<div style='margin-bottom:16px;background:#fef3c7;border:2px solid #f4b400;border-radius:14px;padding:18px'><div style='font-size:18px;font-weight:900;color:#92400e'>⚠️ School account already exists</div><div style='margin-top:8px;color:#475569'>{school_email}</div></div>"""
    elif success=="status_updated":
        popup="""<div style='margin-bottom:16px;background:#eff6ff;border:2px solid #60a5fa;border-radius:14px;padding:16px'><div style='font-size:17px;font-weight:900;color:#1d4ed8'>🔄 School status updated</div><div style='margin-top:6px;color:#475569'>The school can now sign in only when its status is Active.</div></div>"""
    elif success=="registrar_updated":
        popup="""<div style='margin-bottom:16px;background:#dcfce7;border:2px solid #22c55e;border-radius:14px;padding:16px'><div style='font-size:17px;font-weight:900;color:#166534'>✅ Registrar updated</div><div style='margin-top:6px;color:#475569'>The changes are now reflected in the linked school account.</div></div>"""
    elif success=="registrar_deleted":
        popup="""<div style='margin-bottom:16px;background:#dcfce7;border:2px solid #22c55e;border-radius:14px;padding:16px'><div style='font-size:17px;font-weight:900;color:#166534'>✅ Registrar deleted</div><div style='margin-top:6px;color:#475569'>The Registrar account has been removed from the linked school.</div></div>"""
    if success=="code_sent" and pending: popup=f"""<div style='margin-bottom:16px;background:white;border:1.5px solid #86b98b;border-radius:12px;padding:16px'><div style='font-weight:800;color:#166534'>✉️ Verification code sent</div><div style='margin-top:7px;color:#475569'>A six-digit code has been emailed to <b>{escape(str(pending["email"] or ""))}</b> for <b>{escape(str(pending["name"] or ""))}</b>. Check the inbox and spam folder.</div><form method='post' action='/verify-school-code' style='display:flex;gap:10px;flex-wrap:wrap;margin-top:14px'><input type='hidden' name='pending_id' value='{escape(str(pending_id))}'><input name='auth_code' inputmode='numeric' autocomplete='one-time-code' maxlength='6' pattern='[0-9]{{6}}' placeholder='Enter 6-digit code' required style='flex:1;min-width:180px;padding:12px;border:1px solid #e2e8f0;border-radius:10px;text-align:center;font-weight:700;letter-spacing:5px'><button style='background:#0b3d91;color:white;padding:12px 18px;border:none;border-radius:10px'>✅ Confirm Email & Register</button></form></div>"""
    elif success=="added" and new_pass:
        popup=f"""<div id='daviSuccessOverlay' style='position:fixed;inset:0;background:rgba(15,23,42,.28);display:flex;align-items:center;justify-content:center;padding:20px;z-index:99999'><div style='width:min(760px,96vw);background:#dcfce7;border:3px solid #16a34a;border-radius:18px;padding:28px;font-family:Arial,sans-serif'><div style='font-size:25px;font-weight:900;color:#166534;margin-bottom:18px'>✅ Success! 🏫 {school_name}</div><div style='background:white;border:1.5px dashed #22c55e;border-radius:14px;padding:18px;margin-bottom:18px'><div style='font-size:15px;color:#64748b'>👤 Username:</div><div style='font-size:25px;font-weight:900;color:#166534;word-break:break-word'>{school_email}</div><div style='font-size:15px;color:#64748b;margin-top:12px'>🔑 Password:</div><div style='font-size:25px;font-weight:900;color:#166534;word-break:break-word'>{new_pass}</div></div><button type='button' onclick="document.getElementById('daviSuccessOverlay').remove()" style='display:block;margin-left:auto;background:#0b3d91;color:white;border:0;border-radius:12px;padding:13px 30px;font-size:17px;font-weight:900;cursor:pointer'>OK ✅</button></div></div>"""
    rows=[]
    for s in schools:
        sid=int(s["id"])
        admin=users_by_school.get(sid)
        admin_email=admin["email"] if admin else ""
        school_status = str(s["status"] or "active").strip().lower() if "status" in s.keys() else "active"
        status_text = "🟢 Active" if school_status in ("active", "enabled") else "🔴 Suspended"
        status_bg = "#dcfce7" if school_status in ("active", "enabled") else "#fee2e2"
        status_fg = "#166534" if school_status in ("active", "enabled") else "#991b1b"
        school_name_js=str(s["name"] or "this school").replace("\\","\\\\").replace("'","\\'")
        rows.append(f"""<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:12px 10px'><div style='font-weight:700'>🏫 {s['name']}</div><div style='font-size:10px;color:#64748b'>{s['school_type'] or 'School'} · 🔑 {s['code']}</div></td><td style='padding:12px 10px;font-size:12px'>{s['phone'] or ''}</td><td style='padding:12px 10px;font-size:11px'>{s['email']}</td><td style='padding:12px 10px;font-size:12px'>{s['location']}</td><td style='padding:12px 10px;font-size:11px'>{admin_email}<div style='font-size:10px;color:#647b68'>{('Active' if str(admin['status'] or 'active').lower() in ('active','enabled') else 'Inactive') if admin and 'status' in admin.keys() else ('Account linked' if admin else 'No account')}</div></td><td style='padding:12px 10px;font-size:11px;color:#647b68'>{last_activity_by_school.get(sid) or 'No audit activity'}</td><td style='padding:12px 10px;font-size:12px'><button type='button' onclick='viewSchoolPassword({sid})' title='View password' style='border:0;background:#eff6ff;color:#1d4ed8;border-radius:7px;padding:6px 10px;cursor:pointer;font-size:15px'>👁️</button></td><td style='padding:12px 10px'><form method='post' action='/schools/status/{sid}' style='display:inline' onsubmit="return confirm('Change the account status for {school_name_js}?')"><button type='submit' style='border:0;background:{status_bg};color:{status_fg};border-radius:7px;padding:6px 9px;cursor:pointer;font-size:11px;font-weight:800'>{status_text}</button></form></td><td style='padding:12px 10px;white-space:nowrap'><a href='/schools/profile/{sid}' style='background:#dcf0dc;color:#14532d;padding:6px 9px;border-radius:6px;text-decoration:none;font-size:11px;font-weight:700'>Profile</a> <a href='/schools/edit/{sid}' onclick="return confirm('Open edit screen for {school_name_js}?')" style='background:#e0f2fe;color:#075985;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px;font-weight:700'>✏️ Edit</a><form method='post' action='/schools/delete/{sid}' style='display:inline' onsubmit="return confirm('Delete {school_name_js} and its school administrator account? This cannot be undone.')"><button type='submit' style='border:0;background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px;font-weight:700;cursor:pointer'>🗑️</button></form></td></tr>""")
    rows="".join(rows) or "<tr><td colspan='9' style='padding:40px;text-align:center'>No schools</td></tr>"
    registrar_rows=[]
    for rr in registrars:
        registrar_rows.append(f"""<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:11px 10px;font-weight:700'>{str(rr['teacher_name'] or rr['full_name'] or 'Registrar')}</td><td style='padding:11px 10px'>{str(rr['email'] or '')}<div style='font-size:10px;color:#64748b'>{str(rr['username'] or '')}</div></td><td style='padding:11px 10px'>{str(rr['school_name'] or '—')}</td><td style='padding:11px 10px'>{str(rr['teacher_phone'] or '—')}</td><td style='padding:11px 10px'>{str(rr['teacher_role'] or 'Registrar')}</td><td style='padding:11px 10px;white-space:nowrap'><a href='/registrars/edit/{int(rr["id"])}' style='background:#e0f2fe;color:#075985;padding:6px 9px;border-radius:6px;text-decoration:none;font-size:11px;font-weight:700'>✏️ Edit</a> <form method='post' action='/registrars/delete/{int(rr["id"])}' style='display:inline' onsubmit="return confirm('Delete this Registrar account from the school? This cannot be undone.')"><button type='submit' style='border:0;background:#fee2e2;color:#991b1b;padding:6px 9px;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer'>🗑️ Delete</button></form></td></tr>""")
    registrar_rows="".join(registrar_rows) or "<tr><td colspan='6' style='padding:30px;text-align:center;color:#94a3b8'>No registrar accounts yet.</td></tr>"
    pending_rows = "".join([f"""<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px;font-weight:700'>{ps["name"]}</td><td>{ps["email"]}</td><td>{ps["school_type"]}</td><td>{ps["timestamp"]}</td><td><a href='/schools/manage?success=code_sent&pending_id={ps["id"]}' style='background:#dcf0dc;color:#14532d;padding:6px 9px;border-radius:7px;text-decoration:none;font-size:11px;font-weight:700'>Continue verification</a></td></tr>""" for ps in pending_schools]) or "<tr><td colspan='5' style='padding:24px;text-align:center;color:#94a3b8'>No pending school registrations.</td></tr>"
    
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f1f8f1;color:#203126}}.card{{background:white;border:1px solid #dce9dc;border-radius:16px;padding:18px}}input,select{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px}}</style><style>
.manage-school-tabs{{display:flex;gap:8px;flex-wrap:wrap;padding:8px;background:#e7f1e7;border:1px solid #d5e6d5;border-radius:14px}}
.manage-school-tab{{appearance:none;border:1px solid transparent;background:transparent;color:#315c3b;border-radius:10px;padding:11px 16px;font-size:12px;font-weight:800;cursor:pointer;transition:background .18s,transform .18s,box-shadow .18s}}
.manage-school-tab:hover{{background:#f7fbf7;transform:translateY(-1px)}}
.manage-school-tab.active{{background:#fff;color:#14532d;border-color:#cfe2cf;box-shadow:0 3px 10px rgba(20,83,45,.10)}}
.manage-school-panel{{min-width:0}}
@media(max-width:600px){{.manage-school-tabs{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}}.manage-school-tab{{padding:12px 8px}}}}
</style></head><body>{header_html(initials, name, email)}<script>
async function viewSchoolPassword(id){{
  try{{
    let r=await fetch('/schools/password/'+id);
    let d=await r.json();
    if(d.needs_reset){{
      if(!confirm('This password cannot be recovered because it was created before secure password viewing was enabled. Generate a new password for this school and show it now?')) return;
      r=await fetch('/schools/password/'+id+'?reset=1');
      d=await r.json();
    }}
    if(d.ok) alert((d.reset?'New password generated and saved.\\n\\n':'School administrator password:\\n\\n')+d.password);
    else alert(d.message||'Password unavailable.');
  }}catch(e){{ alert('Unable to retrieve the password right now.'); }}
}}
</script><div style='display:flex;flex-direction:column;gap:16px;padding:16px;max-width:1500px;margin:auto'>
<div class='manage-school-tabs' role='tablist' aria-label='Manage schools sections'>
<button type='button' class='manage-school-tab active' data-tab='register'>Register School</button>
<button type='button' class='manage-school-tab' data-tab='schools'>Registered Schools</button>
<button type='button' class='manage-school-tab' data-tab='pending'>Pending Registrations</button>
<button type='button' class='manage-school-tab' data-tab='registrars'>Registrars</button>
</div>
<div class='card manage-school-panel' id='manage-panel-register' style='height:fit-content'><div style='font-weight:800;font-size:15px'>➕ Register New School</div><div style='font-size:12px;color:#64748b;margin:6px 0 10px'>Create the school and its administrator account immediately. Email verification is deferred.</div><form method='post' action='/register-school' style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px'><input name='school_name' required placeholder='🏫 School Name *'><input name='school_email' required type='email' placeholder='📧 Admin Email *'><input name='location' required placeholder='📍 Location *'><input name='phone' required placeholder='📱 Phone *'><input name='principal' required placeholder='👤 Principal *'><select name='role' required><option value='school_admin'>School Admin</option><option value='registrar'>Registrar</option></select><select name='school_type' required><option>Primary</option><option>Junior School</option><option>Primary & Junior School</option><option>Senior School</option><option>Tertiary/College</option><option>University</option></select><button style='grid-column:1/-1;width:100%;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;margin-top:4px'>＋ Register School</button></form></div><div><div class='card manage-school-panel' id='manage-panel-schools'>{popup}<div style='font-weight:800'>📚 Registered Schools ({len(schools)})</div><div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin:12px 0'><input id='schoolSearch' type='search' placeholder='Search school, code, location, email...' oninput='filterSchoolDirectory()' style='padding:10px;border:1px solid #dce9dc;border-radius:9px'><select id='schoolStatusFilter' onchange='filterSchoolDirectory()' style='padding:10px;border:1px solid #dce9dc;border-radius:9px'><option value='all'>All account statuses</option><option value='active'>Active</option><option value='suspended'>Suspended</option></select><select id='schoolTypeFilter' onchange='filterSchoolDirectory()' style='padding:10px;border:1px solid #dce9dc;border-radius:9px'><option value='all'>All school levels</option><option>Primary</option><option>Junior School</option><option>Primary & Junior School</option><option>Senior School</option><option>Tertiary/College</option><option>University</option></select></div><div id='schoolFilterCount' style='font-size:11px;color:#647b68;margin-bottom:8px'>Showing all registered schools</div><div style='overflow:auto;max-height:65vh;border:1px solid #f1f5f9;border-radius:10px;margin-top:10px'><table style='width:100%;border-collapse:collapse;font-size:13px'><thead style='position:sticky;top:0;background:#f8fafc'><tr style='text-align:left;font-size:11px'><th style='padding:10px'>School</th><th>Contact</th><th>Email</th><th>Location</th><th>Admin Account</th><th>Last Activity</th><th>Password</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div><a href='/dashboard' style='margin-top:14px;display:inline-block;padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0b3d91;font-weight:700;font-size:12px'>⬅️ Back</a></div><div class='card manage-school-panel' id='manage-panel-pending' style='margin-top:16px'><div id='pending-schools'><div style='font-weight:800;font-size:15px'>⏳ Pending School Registrations ({len(pending_schools)})</div><div style='font-size:12px;color:#64748b;margin-top:4px'>Registrations awaiting verification before a school account is created.</div><div style='overflow:auto;margin-top:10px;border:1px solid #f1f5f9;border-radius:10px'><table style='width:100%;border-collapse:collapse;font-size:13px'><thead style='background:#f8fafc;text-align:left;font-size:11px'><tr><th style='padding:10px'>School</th><th>Email</th><th>School Level</th><th>Submitted</th><th>Action</th></tr></thead><tbody>{pending_rows}</tbody></table></div></div></div><div class='card manage-school-panel' id='manage-panel-registrars' style='margin-top:16px'><div style='font-weight:800;font-size:15px'>👩‍💼 Registrars</div><div style='font-size:12px;color:#64748b;margin-top:4px'>Registrar accounts across all schools. Registrar details are linked to the teacher record whenever the account was created from a teacher profile.</div><div style='overflow:auto;margin-top:10px;border:1px solid #f1f5f9;border-radius:10px'><table style='width:100%;border-collapse:collapse;font-size:13px'><thead style='background:#f8fafc;text-align:left;font-size:11px'><tr><th style='padding:10px'>Registrar</th><th>Email / Username</th><th>School</th><th>Phone</th><th>Teacher Role</th><th>Action</th></tr></thead><tbody>{registrar_rows}</tbody></table></div></div></div></div><script>
(function(){{
 const tabs=Array.from(document.querySelectorAll('.manage-school-tab'));
 const panels={{register:document.getElementById('manage-panel-register'),schools:document.getElementById('manage-panel-schools'),pending:document.getElementById('manage-panel-pending'),registrars:document.getElementById('manage-panel-registrars')}};
 function activate(name){{
   tabs.forEach(t=>{{const on=t.dataset.tab===name;t.classList.toggle('active',on);t.setAttribute('aria-selected',on?'true':'false');}});
   Object.entries(panels).forEach(([key,p])=>{{if(p)p.style.display=key===name?'':'none';}});
 }}
 const params=new URLSearchParams(location.search);
 const initial=params.get('success')?'schools':(location.hash==='#pending-schools'?'pending':'register');
 tabs.forEach(t=>t.addEventListener('click',()=>activate(t.dataset.tab)));
 activate(initial);
}})();
function filterSchoolDirectory(){{const q=(document.getElementById('schoolSearch')?.value||'').toLowerCase();const st=document.getElementById('schoolStatusFilter')?.value||'all';const ty=document.getElementById('schoolTypeFilter')?.value||'all';const table=document.querySelector('.card table');if(!table)return;let shown=0,total=0;Array.from(table.querySelectorAll('tbody tr')).forEach(row=>{{const txt=row.innerText.toLowerCase();const status=txt.includes('suspended')?'suspended':'active';const ok=txt.includes(q)&&(st==='all'||status===st)&&(ty==='all'||txt.includes(ty.toLowerCase()));row.style.display=ok?'':'none';if(row.querySelector('td')){{total++;if(ok)shown++;}}}});const out=document.getElementById('schoolFilterCount');if(out)out.textContent='Showing '+shown+' of '+total+' schools';}}const schoolParams=new URLSearchParams(location.search);if(schoolParams.get('status')&&document.getElementById('schoolStatusFilter'))document.getElementById('schoolStatusFilter').value=schoolParams.get('status');filterSchoolDirectory();</script></div></div></body></html>""")
@app.post("/register-school")
def register_school(request: Request, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), role: str = Form("school_admin"), school_type: str = Form(...)):
    if request.session.get("role") != "super_admin":
        return RedirectResponse("/", status_code=303)

    from urllib.parse import quote
    school_name_clean = str(school_name or "").strip()
    email_clean = str(school_email or "").strip()
    location_clean = str(location or "").strip()
    phone_clean = str(phone or "").strip()
    principal_clean = str(principal or "").strip()
    role_clean = str(role or "school_admin").strip().lower()
    school_type_clean = str(school_type or "Primary").strip()

    if not all((school_name_clean, email_clean, location_clean, phone_clean, principal_clean)):
        return RedirectResponse("/schools/manage?success=register_error&message=Please%20complete%20all%20required%20fields", status_code=303)
    if role_clean not in {"school_admin", "registrar"}:
        return RedirectResponse("/schools/manage?success=register_error&message=Invalid%20account%20role", status_code=303)

    con = get_db()
    try:
        cur = con.cursor()
        existing = cur.execute(
            "SELECT id FROM users WHERE lower(trim(COALESCE(email,'')))=lower(trim(?))",
            (email_clean,)
        ).fetchone()
        if existing:
            con.close()
            return RedirectResponse(
                f"/schools/manage?success=already_added&school_email={quote(email_clean)}&school_name={quote(school_name_clean)}",
                status_code=303
            )

        school_code = str(random.randint(100000, 999999))
        unique_pass = generate_unique_password(school_name_clean)
        cur.execute(
            "INSERT INTO schools (name,email,code,location,phone,principal,school_type,status) VALUES (?,?,?,?,?,?,?,?)",
            (school_name_clean.upper(), email_clean, school_code, location_clean,
             phone_clean, principal_clean, school_type_clean, "active")
        )
        school_id = cur.lastrowid
        cur.execute(
            "INSERT INTO users (email,password,role,full_name,school_id,credential_secret) VALUES (?,?,?,?,?,?)",
            (email_clean, hash_password(unique_pass), role_clean, principal_clean,
             school_id, encrypt_credential(unique_pass))
        )
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",
            (school_id, email_clean, "SCHOOL_REGISTERED",
             "School account created directly by Super Admin; email verification deferred", ts)
        )
        con.commit()
        return RedirectResponse(
            f"/schools/manage?success=added&new_pass={quote(unique_pass)}&school_email={quote(email_clean)}&school_name={quote(school_name_clean)}",
            status_code=303
        )
    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        print("DAVISCHOOL DIRECT SCHOOL REGISTRATION FAILED:", type(exc).__name__, str(exc)[:300], flush=True)
        return RedirectResponse(
            f"/schools/manage?success=register_error&message={quote(str(exc)[:180])}",
            status_code=303
        )
    finally:
        try:
            con.close()
        except Exception:
            pass

@app.post("/verify-school-code", response_class=HTMLResponse)
def verify_school_code(request: Request, pending_id: str = Form(...), auth_code: str = Form(...)):
    from urllib.parse import quote
    # Do not access request.session here. School verification is authorized by the one-time code.
    con = get_db()
    try:
        cur = con.cursor()
        pending = cur.execute("SELECT * FROM pending_schools WHERE id=?", (str(pending_id).strip(),)).fetchone()
        if not pending:
            return RedirectResponse("/schools/manage?success=invalid_code", status_code=303)

        entered = "".join(ch for ch in (auth_code or "") if ch.isdigit())
        expected = "".join(ch for ch in str(pending["auth_code"] or "") if ch.isdigit())
        if not expected or not hmac.compare_digest(entered, expected):
            return RedirectResponse(
                f"/schools/manage?success=invalid_code&pending_id={pending_id}", status_code=303
            )

        email = str(pending["email"] or "").strip()
        if not email:
            raise ValueError("School administrator email is missing.")

        existing = cur.execute(
            "SELECT id, school_id FROM users WHERE lower(email)=lower(?) AND role IN ('school_admin','registrar')",
            (email,)
        ).fetchone()
        if existing:
            return RedirectResponse(
                f"/schools/manage?success=already_added&school_email={quote(email)}&school_name={quote(str(pending['name']))}",
                status_code=303
            )

        # Schema compatibility is already applied during application startup.
        # Do not use SQLite PRAGMA introspection here: production uses PostgreSQL,
        # where the compatibility layer intentionally translates PRAGMA calls.
        # The required provisioning columns are therefore guaranteed before this route.
        school_code = str(random.randint(100000, 999999))
        unique_pass = generate_unique_password(str(pending["name"]))

        cur.execute(
            "INSERT INTO schools (name,email,code,location,phone,principal,school_type,status) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(pending["name"] or "").strip(),
                email,
                school_code,
                str(pending["location"] or "").strip(),
                str(pending["phone"] or "").strip(),
                str(pending["principal"] or "").strip(),
                str(pending["school_type"] or "Primary").strip(),
                "active",
            )
        )
        school_id = cur.lastrowid

        account_role = str(pending["role"] or "school_admin").strip().lower() if "role" in pending.keys() else "school_admin"
        if account_role not in {"school_admin", "registrar"}:
            account_role = "school_admin"
        cur.execute(
            "INSERT INTO users (email,password,role,full_name,school_id,credential_secret) VALUES (?,?,?,?,?,?)",
            (
                email,
                hash_password(unique_pass),
                account_role,
                str(pending["principal"] or "").strip(),
                school_id,
                encrypt_credential(unique_pass),
            )
        )

        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)", (school_id, email, "SCHOOL_REGISTERED", "School account created through verification", ts))

        cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,))
        con.commit()

        # Return the success screen directly. This avoids losing the generated
        # credentials during a redirect and guarantees the OK button is shown.
        safe_name = str(pending["name"] or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        safe_email = email.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        safe_pass = unique_pass.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        return HTMLResponse(f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>School Created - Mabale_ICT</title></head>
<body style="margin:0;font-family:Arial,sans-serif;background:#f8fafc;min-height:100vh;display:flex;align-items:center;justify-content:center">
<div style="position:fixed;inset:0;background:rgba(15,23,42,.30);display:flex;align-items:center;justify-content:center;padding:20px">
<div style="width:min(700px,96vw);background:#dcfce7;border:3px solid #16a34a;border-radius:18px;padding:30px;box-shadow:0 20px 60px rgba(0,0,0,.20)">
<div style="font-size:26px;font-weight:900;color:#166534;margin-bottom:20px">✅ School Created Successfully</div>
<div style="font-size:15px;color:#475569;margin-bottom:16px">The school has been added and its administrator login has been created.</div>
<div style="font-size:15px;color:#64748b">🏫 School</div>
<div style="font-size:22px;font-weight:900;color:#166534;margin:4px 0 18px">{safe_name}</div>
<div style="background:white;border:1.5px dashed #22c55e;border-radius:14px;padding:20px">
<div style="font-size:14px;color:#64748b">👤 Username / Email</div>
<div style="font-size:24px;font-weight:900;color:#166534;word-break:break-word;margin:5px 0 16px">{safe_email}</div>
<div style="font-size:14px;color:#64748b">🔑 Password</div>
<div style="font-size:24px;font-weight:900;color:#166534;word-break:break-word;margin-top:5px">{safe_pass}</div>
</div>
<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:20px">
<a href="/schools/manage" style="background:#0b3d91;color:white;text-decoration:none;border-radius:12px;padding:13px 30px;font-size:16px;font-weight:900">OK ✅</a>
</div>
</div></div></body></html>""")
    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        from urllib.parse import quote
        error_text = quote(str(exc)[:220])
        return RedirectResponse(
            f"/schools/manage?success=verify_error&pending_id={pending_id}&message={error_text}",
            status_code=303
        )
    finally:
        con.close()

@app.get("/verify-school-code")
def verify_school_code_get():
    return RedirectResponse("/schools/manage", status_code=303)


@app.get("/schools/profile/{sid}", response_class=HTMLResponse)
def school_profile(sid: int, request: Request):
    if request.session.get("role") != "super_admin":
        return RedirectResponse("/", status_code=303)
    con = get_db()
    cur = con.cursor()
    school = cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not school:
        con.close()
        return RedirectResponse("/schools/manage", status_code=303)
    users = cur.execute("SELECT full_name,email,username,role FROM users WHERE school_id=? AND lower(COALESCE(role,'')) IN ('school_admin','registrar') ORDER BY id", (sid,)).fetchall()
    counts = {}
    for table in ("students", "teachers", "classes", "subjects", "exams"):
        try:
            counts[table] = int(cur.execute("SELECT COUNT(*) c FROM " + table + " WHERE school_id=?", (sid,)).fetchone()["c"] or 0)
        except Exception:
            counts[table] = 0
    try:
        bill = cur.execute("SELECT COALESCE(SUM(CASE WHEN lower(COALESCE(status,'')) IN ('paid','complete','completed') THEN CAST(amount AS REAL) ELSE 0 END),0) total,COUNT(*) records FROM billing WHERE school_id=?", (sid,)).fetchone()
        paid_total = float(bill["total"] or 0)
        bill_count = int(bill["records"] or 0)
    except Exception:
        paid_total, bill_count = 0.0, 0
    try:
        registration = cur.execute("SELECT timestamp FROM system_audit WHERE school_id=? AND action='SCHOOL_REGISTERED' ORDER BY id ASC LIMIT 1", (sid,)).fetchone()
        registration_date = registration["timestamp"] if registration else "Not recorded for this legacy school"
    except Exception:
        registration_date = "Not recorded"
    con.close()
    safe = lambda v: str(v or "—").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")
    active = str(school["status"] or "active").lower() in ("active", "enabled")
    user_rows = "".join("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(safe(u["full_name"]), safe(u["email"]), safe(u["username"]), safe(u["role"])) for u in users) or "<tr><td colspan='4'>No School Admin or Registrar accounts found.</td></tr>"
    stats = "".join("<div class='stat'><span>{}</span><b>{:,}</b></div>".format(label, counts[key]) for key, label in (("students","Learners"),("teachers","Staff"),("classes","Classes"),("subjects","Subjects"),("exams","Exams")))
    name = request.session.get("name", "Super Administrator")
    initials = "".join(p[0] for p in name.split()[:2]).upper()
    header = header_html(initials, name, request.session.get("email", ""))
    html = f"""<main class='wrap'>
    <section class='hero'><div><small>SCHOOL PROFILE · ID {sid}</small><h1>{safe(school['name'])}</h1><p>{safe(school['school_type'])} · {safe(school['location'])}</p></div><b class='status {'active' if active else 'suspended'}'>{'Active' if active else 'Suspended'}</b></section>
    <div class='actions'><a href='/schools/edit/{sid}'>Edit School Details</a></div>
    <section class='stats'>{stats}</section>
    <div class='grid'><section class='panel'><h2>School Details</h2><dl>
    <dt>Registration</dt><dd>{safe(registration_date)}</dd><dt>School code</dt><dd>{safe(school['code'])}</dd><dt>Email</dt><dd>{safe(school['email'])}</dd><dt>Phone</dt><dd>{safe(school['phone'])}</dd><dt>Principal</dt><dd>{safe(school['principal'])}</dd><dt>Location</dt><dd>{safe(school['location'])}</dd><dt>School level</dt><dd>{safe(school['school_type'])}</dd><dt>Account status</dt><dd>{'Active' if active else 'Suspended'}</dd>
    </dl></section></div>
    <section class='panel'><h2>Users & Access</h2><div class='scroll'><table><thead><tr><th>NAME</th><th>EMAIL</th><th>USERNAME</th><th>ROLE</th></tr></thead><tbody>{user_rows}</tbody></table></div></section>
    <section class='panel'><h2>Subscription & Billing Snapshot</h2><div class='money'>KES {paid_total:,.2f}</div><p class='muted'>Recorded paid / completed billing · {bill_count} billing records. This is a billing summary, not a live subscription entitlement check.</p><a href='/super/global-control/system-settings/billing-payments'>Open billing records →</a></section>
    </main>
    <style>*{{box-sizing:border-box}}body{{font-family:Arial;background:#f1f8f1;color:#203126;margin:0}}.wrap{{max-width:1350px;margin:auto;padding:22px}}.hero{{background:linear-gradient(120deg,#14532d,#166534);color:white;border-radius:16px;padding:22px;display:flex;justify-content:space-between;align-items:center;gap:15px}}.hero h1{{margin:8px 0;font-size:24px}}.hero p{{margin:0;color:#d8f0dc;font-size:12px}}.hero small{{font-size:10px;color:#cde8d2;font-weight:800}}.status{{padding:6px 10px;border-radius:20px;font-size:11px}}.status.active{{background:#dcfce7;color:#166534}}.status.suspended{{background:#fee2e2;color:#991b1b}}.actions{{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}}.actions a{{background:white;border:1px solid #dce9dc;padding:10px 12px;border-radius:9px;color:#166534;text-decoration:none;font-size:12px;font-weight:800}}.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:10px;margin-bottom:14px}}.stat,.panel{{background:white;border:1px solid #dce9dc;border-radius:13px;padding:15px}}.stat span{{display:block;font-size:10px;color:#718477;font-weight:800}}.stat b{{display:block;font-size:25px;color:#14532d;margin-top:7px}}.grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:13px}}.panel{{margin-bottom:14px;overflow:hidden}}.panel h2{{font-size:14px;margin:0 0 12px}}dl{{display:grid;grid-template-columns:130px 1fr;gap:10px;font-size:12px;margin:0}}dt{{color:#718477}}dd{{margin:0;font-weight:700;overflow-wrap:anywhere}}.money{{font-size:27px;color:#14532d;font-weight:900}}.muted{{font-size:11px;color:#718477}}table{{width:100%;border-collapse:collapse;min-width:560px}}th,td{{padding:11px;text-align:left;border-bottom:1px solid #edf3ed;font-size:11px}}th{{background:#f7fbf7;color:#718477}}.scroll{{overflow:auto}}@media(max-width:760px){{.wrap{{padding:13px}}.hero{{align-items:flex-start;flex-direction:column}}.grid{{grid-template-columns:1fr}}dl{{grid-template-columns:105px 1fr}}}}</style>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>{safe(school['name'])} · Mabale_ICT</title></head><body>{header}{html}</div></div></body></html>")


@app.post("/schools/status/{sid}")
def update_school_status(sid: int, request: Request):
    if request.session.get("role") != "super_admin":
        return RedirectResponse("/", status_code=303)
    con = get_db(); cur = con.cursor()
    school = cur.execute("SELECT id, name, status FROM schools WHERE id=?", (sid,)).fetchone()
    if not school:
        con.close()
        return RedirectResponse("/schools/manage", status_code=303)
    current = str(school["status"] or "active").strip().lower()
    new_status = "suspended" if current in ("active", "enabled") else "active"
    cur.execute("UPDATE schools SET status=? WHERE id=?", (new_status, sid))
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",
                (sid, request.session.get("email",""), "SCHOOL_STATUS_CHANGE", f"{current} -> {new_status}", ts))
    con.commit(); con.close()
    return RedirectResponse("/schools/manage?success=status_updated", status_code=303)

@app.get("/schools/password/{sid}")
def view_school_password(sid: int, request: Request, reset: int = 0):
    if request.session.get("role") != "super_admin":
        return JSONResponse({"ok": False, "message": "Not authorized."}, status_code=403)
    con=get_db(); cur=con.cursor()
    school=cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    user=cur.execute("SELECT * FROM users WHERE school_id=? AND role='school_admin' ORDER BY id LIMIT 1", (sid,)).fetchone()
    if not school or not user:
        con.close()
        return JSONResponse({"ok": False, "message": "School administrator account not found."}, status_code=404)
    token=user["credential_secret"] if "credential_secret" in user.keys() else None
    if token:
        try:
            password=decrypt_credential(token)
            con.close()
            return JSONResponse({"ok": True, "password": password, "reset": False})
        except (InvalidToken, ValueError, TypeError):
            pass
    stored=str(user["password"] or "")
    if stored and not stored.startswith(PASSWORD_SCHEME+"$"):
        con.close()
        return JSONResponse({"ok": True, "password": stored, "reset": False})
    if not reset:
        con.close()
        return JSONResponse({"ok": False, "needs_reset": True, "message": "Password is securely hashed and cannot be recovered."})
    new_pass=generate_unique_password(str(school["name"] or "Mabale_ICT"))
    cur.execute("UPDATE users SET password=?, credential_secret=? WHERE id=?", (hash_password(new_pass), encrypt_credential(new_pass), user["id"]))
    con.commit(); con.close()
    return JSONResponse({"ok": True, "password": new_pass, "reset": True})

@app.get("/schools/edit/{sid}", response_class=HTMLResponse)
def edit_school(sid: int, request: Request):
    if request.session.get("role") != "super_admin":
        return RedirectResponse("/")
    con=get_db(); cur=con.cursor()
    school=cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    user=cur.execute("SELECT * FROM users WHERE school_id=? AND role='school_admin' ORDER BY id LIMIT 1", (sid,)).fetchone()
    con.close()
    if not school:
        return RedirectResponse("/schools/manage")
    email=user["email"] if user else school["email"]
    full_name=user["full_name"] if user else school["principal"]
    primary_selected = "selected" if school["school_type"] == "Primary" else ""
    secondary_selected = "selected" if school["school_type"] in ("Secondary", "Senior School") else ""
    pjs_selected = "selected" if school["school_type"] in ("Primary & Junior Secondary", "Primary & Junior School") else ""
    junior_selected = "selected" if school["school_type"] == "Junior School" else ""
    senior_selected = "selected" if school["school_type"] in ("Secondary", "Senior School") else ""
    tertiary_selected = "selected" if school["school_type"] in ("Tertiary", "Tertiary/College") else ""
    university_selected = "selected" if school["school_type"] == "University" else ""
    page = """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Edit School · Mabale_ICT</title><style>
body{margin:0;font-family:Arial;background:#f8fafc;color:#172033}.wrap{max-width:760px;margin:30px auto;padding:16px}.card{background:white;border:1px solid #e2e8f0;border-radius:18px;padding:24px}label{display:block;font-size:12px;font-weight:800;margin:12px 0 5px;color:#475569}input,select{width:100%;box-sizing:border-box;padding:12px;border:1px solid #dbe2e8;border-radius:10px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}button,a{display:inline-block;padding:12px 18px;border-radius:10px;font-weight:800;text-decoration:none}button{border:0;background:#0b3d91;color:white;cursor:pointer}a{border:1px solid #e2e8f0;color:#0b3d91;background:white}@media(max-width:650px){.grid{grid-template-columns:1fr}}</style></head><body><div class='wrap'><div class='card'><h1 style='margin-top:0'>✏️ Edit School</h1><div style='color:#64748b;font-size:13px;margin-bottom:18px'>Update the registered school details and its school administrator account.</div>
<form method='post' action='/schools/edit/__SID__' onsubmit="return confirm('Save these changes to this school?')">
<div class='grid'>
<div><label>School Name</label><input name='school_name' required value='__NAME__'></div>
<div><label>School Email</label><input name='school_email' type='email' required value='__EMAIL__'></div>
<div><label>Location</label><input name='location' required value='__LOCATION__'></div>
<div><label>Phone</label><input name='phone' required value='__PHONE__'></div>
<div><label>Principal / Administrator Name</label><input name='principal' required value='__PRINCIPAL__'></div>
<div><label>School Type</label><select name='school_type'><option __PRIMARY__>Primary</option><option __JUNIOR__>Junior School</option><option __PJS__>Primary & Junior School</option><option __SENIOR__>Senior School</option><option __TERTIARY__>Tertiary/College</option><option __UNIVERSITY__>University</option></select></div>
</div>
<label>New School Administrator Password (optional)</label><input name='new_password' type='password' minlength='8' placeholder='Leave blank to keep current password'>
<div style='display:flex;gap:10px;justify-content:flex-end;margin-top:20px'><a href='/schools/manage'>Cancel</a><button type='submit'>💾 Save Changes</button></div></form></div></div></body></html>"""
    def _safe(value):
        return str(value or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")
    page=page.replace("__SID__",str(sid)).replace("__NAME__",_safe(school["name"])).replace("__EMAIL__",_safe(school["email"])).replace("__LOCATION__",_safe(school["location"])).replace("__PHONE__",_safe(school["phone"])).replace("__PRINCIPAL__",_safe(school["principal"] or full_name)).replace("__PRIMARY__",primary_selected).replace("__JUNIOR__",junior_selected).replace("__SENIOR__",senior_selected).replace("__SECONDARY__",secondary_selected).replace("__PJS__",pjs_selected).replace("__TERTIARY__",tertiary_selected).replace("__UNIVERSITY__",university_selected)
    return HTMLResponse(page)

@app.post("/schools/edit/{sid}")
def update_school(sid: int, request: Request, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...), new_password: str = Form("")):
    if request.session.get("role") != "super_admin":
        return RedirectResponse("/")
    con=get_db(); cur=con.cursor()
    school=cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    user=cur.execute("SELECT * FROM users WHERE school_id=? AND role='school_admin' ORDER BY id LIMIT 1", (sid,)).fetchone()
    if not school:
        con.close()
        return RedirectResponse("/schools/manage")
    duplicate=cur.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND id<>?", (school_email.strip(), user["id"] if user else -1)).fetchone()
    if duplicate:
        con.close()
        return HTMLResponse("<h3 style='font-family:Arial'>That administrator email is already in use. <a href='/schools/manage'>Back</a></h3>", status_code=400)
    cur.execute("UPDATE schools SET name=?,email=?,location=?,phone=?,principal=?,school_type=? WHERE id=?", (school_name.strip(),school_email.strip(),location.strip(),phone.strip(),principal.strip(),school_type.strip(),sid))
    if user:
        if new_password.strip():
            cur.execute("UPDATE users SET email=?,full_name=?,password=?,credential_secret=? WHERE id=?", (school_email.strip(),principal.strip(),hash_password(new_password.strip()),encrypt_credential(new_password.strip()),user["id"]))
        else:
            cur.execute("UPDATE users SET email=?,full_name=? WHERE id=?", (school_email.strip(),principal.strip(),user["id"]))
    else:
        if new_password.strip():
            cur.execute("INSERT INTO users(email,password,role,full_name,school_id,credential_secret) VALUES(?,?,?,?,?,?)",(school_email.strip(),hash_password(new_password.strip()),"school_admin",principal.strip(),sid,encrypt_credential(new_password.strip())))
    ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",(sid,request.session.get("email",""),"SCHOOL_PROFILE_UPDATE","Updated school profile and administrator account",ts))
    con.commit(); con.close()
    return RedirectResponse("/schools/manage?success=updated",303)

@app.get("/registrars/edit/{uid}", response_class=HTMLResponse)
def edit_registrar(uid: int, request: Request):
    if request.session.get("role") != "super_admin":
        return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor()
    user=cur.execute("""SELECT u.*,s.name school_name,t.name teacher_name,t.email teacher_email,t.phone teacher_phone,t.role teacher_role
                        FROM users u
                        LEFT JOIN schools s ON s.id=u.school_id
                        LEFT JOIN teachers t ON t.id=u.teacher_id AND t.school_id=u.school_id
                        WHERE u.id=? AND lower(COALESCE(u.role,''))='registrar'""",(uid,)).fetchone()
    con.close()
    if not user: return RedirectResponse("/schools/manage",303)
    def esc(v): return str(v or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")
    page=f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Edit Registrar · Mabale_ICT</title><style>body{{margin:0;font-family:Arial;background:#f8fafc;color:#172033}}.wrap{{max-width:760px;margin:30px auto;padding:16px}}.card{{background:white;border:1px solid #e2e8f0;border-radius:18px;padding:24px}}label{{display:block;font-size:12px;font-weight:800;margin:12px 0 5px;color:#475569}}input,select{{width:100%;box-sizing:border-box;padding:12px;border:1px solid #dbe2e8;border-radius:10px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}button,a{{display:inline-block;padding:12px 18px;border-radius:10px;font-weight:800;text-decoration:none}}button{{border:0;background:#0b3d91;color:white;cursor:pointer}}a{{border:1px solid #e2e8f0;color:#0b3d91;background:white}}.muted{{color:#64748b;font-size:13px}}@media(max-width:650px){{.grid{{grid-template-columns:1fr}}}}</style></head><body><div class='wrap'><div class='card'><h1 style='margin-top:0'>✏️ Edit Registrar</h1><div class='muted'>Super Admin only. Changes made here are immediately reflected on the Registrar account in the linked school.</div><div style='margin-top:10px;padding:10px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px'><b>School:</b> {esc(user["school_name"] or "—")}</div><form method='post' action='/registrars/edit/{uid}' onsubmit="return confirm('Save these Registrar changes?')"><div class='grid'><div><label>Registrar Name</label><input name='full_name' required value='{esc(user["full_name"])}'></div><div><label>Email / Username</label><input name='email' type='email' required value='{esc(user["email"] or user["username"] or "")}'></div><div><label>Teacher Name</label><input name='teacher_name' value='{esc(user["teacher_name"])}'></div><div><label>Teacher Email</label><input name='teacher_email' type='email' value='{esc(user["teacher_email"])}'></div><div><label>Phone</label><input name='teacher_phone' value='{esc(user["teacher_phone"])}'></div><div><label>Teacher Role</label><input name='teacher_role' value='{esc(user["teacher_role"] or "Registrar")}'></div></div><label>New Password (optional)</label><input name='new_password' type='password' minlength='8' placeholder='Leave blank to keep current password'><div style='display:flex;gap:10px;justify-content:flex-end;margin-top:20px'><a href='/schools/manage'>Cancel</a><button type='submit'>💾 Save Changes</button></div></form></div></div></body></html>"""
    return HTMLResponse(page)

@app.post("/registrars/edit/{uid}")
def update_registrar(uid: int, request: Request, full_name: str=Form(...), email: str=Form(...), teacher_name: str=Form(""), teacher_email: str=Form(""), teacher_phone: str=Form(""), teacher_role: str=Form("Registrar"), new_password: str=Form("")):
    if request.session.get("role") != "super_admin": return RedirectResponse("/",303)
    email_v=email.strip().lower()
    if not email_v: return HTMLResponse("Registrar email is required. <a href='/schools/manage'>Back</a>",400)
    if new_password.strip() and len(new_password.strip())<8: return HTMLResponse("Password must be at least 8 characters. <a href='/schools/manage'>Back</a>",400)
    con=get_db(); cur=con.cursor()
    user=cur.execute("SELECT * FROM users WHERE id=? AND lower(COALESCE(role,''))='registrar'",(uid,)).fetchone()
    if not user: con.close(); return HTMLResponse("Registrar account not found. <a href='/schools/manage'>Back</a>",404)
    duplicate=cur.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND id<>?",(email_v,uid)).fetchone()
    if duplicate: con.close(); return HTMLResponse("That email is already in use. <a href='/schools/manage'>Back</a>",409)
    cur.execute("UPDATE users SET full_name=?,email=? WHERE id=?",(full_name.strip(),email_v,uid))
    if new_password.strip(): cur.execute("UPDATE users SET password=?,credential_secret=? WHERE id=?",(hash_password(new_password.strip()),encrypt_credential(new_password.strip()),uid))
    if user["teacher_id"]:
        teacher=cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(int(user["teacher_id"]),int(user["school_id"]))).fetchone()
        if teacher: cur.execute("UPDATE teachers SET name=?,email=?,phone=?,role=? WHERE id=? AND school_id=?",(teacher_name.strip() or full_name.strip(),teacher_email.strip(),teacher_phone.strip(),teacher_role.strip() or "Registrar",int(user["teacher_id"]),int(user["school_id"])))
    ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",(int(user["school_id"]),request.session.get("email",""),"REGISTRAR_UPDATE",f"Updated Registrar account {email_v}",ts))
    con.commit(); con.close(); return RedirectResponse("/schools/manage?success=registrar_updated",303)

@app.post("/registrars/delete/{uid}")
def delete_registrar(uid: int, request: Request):
    if request.session.get("role") != "super_admin": return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor()
    user=cur.execute("SELECT id,school_id,teacher_id,email,full_name FROM users WHERE id=? AND lower(COALESCE(role,''))='registrar'",(uid,)).fetchone()
    if not user: con.close(); return RedirectResponse("/schools/manage",303)
    ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",(int(user["school_id"]),request.session.get("email",""),"REGISTRAR_DELETE",f"Deleted Registrar account {user['email']}",ts))
    cur.execute("DELETE FROM users WHERE id=? AND lower(COALESCE(role,''))='registrar'",(uid,))
    con.commit(); con.close(); return RedirectResponse("/schools/manage?success=registrar_deleted",303)

@app.post("/schools/delete/{sid}")
def delete_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin":
        return RedirectResponse("/",303)
    con = get_db(); cur = con.cursor()
    school = cur.execute("SELECT id, name FROM schools WHERE id=?", (sid,)).fetchone()
    if not school:
        con.close()
        return RedirectResponse("/schools/manage",303)
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",
                (sid, request.session.get("email",""), "SCHOOL_DELETE", f"Deleted school {school['name']}", ts))
    # Remove unverified registrations for this school as part of permanent deletion.
    cur.execute("DELETE FROM pending_schools WHERE lower(trim(COALESCE(name,'')))=lower(trim(?)) OR lower(trim(COALESCE(email,'')))=lower(trim((SELECT email FROM schools WHERE id=?)))", (school["name"], sid))
    cur.execute("DELETE FROM users WHERE school_id=?", (sid,))
    cur.execute("DELETE FROM schools WHERE id=?", (sid,))
    con.commit(); con.close()
    return RedirectResponse("/schools/manage",303)

@app.get("/schools/delete/{sid}")
def delete_school_get(sid: int, request: Request):
    if request.session.get("role")!="super_admin":
        return RedirectResponse("/",303)
    return RedirectResponse("/schools/manage",303)

@app.get("/super/switch-to-school/{sid}")
def switch_to_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone(); con.close()
    if not s: return RedirectResponse("/schools/manage")
    con=get_db(); cur=con.cursor(); ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",(sid,request.session.get("email",""),"SUPER_ADMIN_SCHOOL_ACCESS","Super Admin entered school workspace",ts)); con.commit(); con.close()
    request.session["school_id"]=sid; request.session["is_impersonating"]=True; return RedirectResponse("/school/dashboard",303)
@app.get("/super/back-to-admin")
def back_to_admin(request: Request):
    sid = request.session.get("school_id")
    if request.session.get("role") == "super_admin" and sid:
        con=get_db(); cur=con.cursor(); ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",(sid,request.session.get("email",""),"SUPER_ADMIN_RETURN_TO_PLATFORM","Super Admin returned to platform management",ts)); con.commit(); con.close()
    request.session["school_id"]=0
    request.session["is_impersonating"]=False
    return RedirectResponse("/dashboard",303)

# === SET MARKS FILTER HELPERS — EXACT ===
def get_set_marks_filter_data(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (school_id,)); subjects = cur.fetchall()
    cur.execute("SELECT name, stream FROM classes WHERE school_id=? GROUP BY name, stream ORDER BY name", (school_id,)); classes_raw = cur.fetchall()
    cur.execute("SELECT DISTINCT stream FROM classes WHERE school_id=? AND stream!='' ORDER BY stream", (school_id,)); streams = [r["stream"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT year FROM terms WHERE school_id=? ORDER BY year DESC", (school_id,)); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years:
        cur.execute("SELECT DISTINCT year FROM exams WHERE school_id=? ORDER BY year DESC", (school_id,)); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years: years = [str(datetime.now().year)]
    cur.execute("SELECT DISTINCT term_name FROM terms WHERE school_id=? ORDER BY term_name", (school_id,)); terms_list = [r["term_name"] for r in cur.fetchall()]
    if not terms_list: terms_list = ["Term 1","Term 2","Term 3"]
    cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school_id,)); exams = cur.fetchall()
    classes_unique = []
    seen = set()
    for c in classes_raw:
        if c["name"] not in seen:
            classes_unique.append(c)
            seen.add(c["name"])
    con.close()
    return subjects, classes_unique, streams, years, terms_list, exams
def school_set_marks(request: Request, year: str = "all", term: str = "all", class_name: str = "all", search: str = ""):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","registrar","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    subjects, classes, streams, years, terms_list, exams = get_set_marks_filter_data(school["id"])
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT cfg.*, s.name as subject_name FROM set_marks_config cfg LEFT JOIN subjects s ON cfg.subject_id=s.id WHERE cfg.school_id=? ORDER BY cfg.year DESC, cfg.term, cfg.class_name""", (school["id"],))
    configs = cur.fetchall(); con.close()
    filters = {"year": year, "term": term, "class": class_name}
    header = school_header(school, name, "set-marks", is_impersonating=is_imp)
    body = set_marks_exact_html(subjects, classes, streams, years, terms_list, exams, configs, school["name"], is_global=False, filters=filters)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{body}</div></div></body></html>")

@app.post("/school/set-marks/save")
def school_set_marks_save(request: Request, subject_id: int = Form(...), class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), exam_id: int = Form(...), out_of: int = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM set_marks_config WHERE school_id=? AND subject_id=? AND class_name=? AND stream=? AND year=? AND term=? AND exam_id=?", (school["id"], subject_id, class_name.strip().upper(), stream.strip().upper(), year.strip(), term.strip(), exam_id))
    existing = cur.fetchone()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        cur.execute("UPDATE set_marks_config SET out_of=?, created_at=? WHERE id=?", (out_of, ts, existing["id"]))
    else:
        cur.execute("INSERT INTO set_marks_config (school_id, subject_id, class_name, stream, year, term, exam_id, out_of, created_at) VALUES (?,?,?,?,?,?,?,?,?)", (school["id"], subject_id, class_name.strip().upper(), stream.strip().upper(), year.strip(), term.strip(), exam_id, out_of, ts))
    cur.execute("INSERT INTO system_audit (school_id, user_email, action, details, timestamp) VALUES (?,?,?,?,?)", (school["id"], request.session.get("email",""), "SET MARKS", f"Class {class_name} Stream {stream} Sub {subject_id} Out {out_of}", ts))
    con.commit(); con.close()
    return RedirectResponse("/school/set-marks",303)

@app.post("/school/set-marks/delete/{cid}")
def school_set_marks_delete(cid: int, request: Request):
    if request.session.get("role") not in {"school_admin","registrar","super_admin"}: return RedirectResponse("/",303)
    school=get_school_obj(request)
    if not school or not _role_permission(request,"marks.edit"): return RedirectResponse("/portal",303)
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM set_marks_config WHERE id=? AND school_id=?", (cid,school["id"]))
    con.commit(); con.close()
    return RedirectResponse("/school/set-marks",303)
    if request.session.get("role") not in ["school_admin","registrar","super_admin"]: return RedirectResponse("/")
    if request.session.get("role")=="super_admin" and request.session.get("school_id",0)==0: return RedirectResponse("/dashboard")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM teachers WHERE school_id=?", (school["id"],)); tc = cur.fetchone()["c"]
    cur.execute("SELECT c.name as class_name, s.gender, COUNT(*) as cnt FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? GROUP BY c.name, s.gender ORDER BY c.name", (school["id"],)); gender_rows = cur.fetchall()
    cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY id DESC LIMIT 5", (school["id"],)); recent_students = cur.fetchall()
    cur.execute("SELECT COUNT(*) c FROM set_marks_config WHERE school_id=?", (school["id"],)); set_cfg_count = cur.fetchone()["c"]
    con.close()
    stats = {}; tb=0; tg=0
    for r in gender_rows:
        cn = (r['school_name'] or 'School') + ' · ' + (r['class_name'] or 'UNASSIGNED').upper() + ' [School ' + str(r['school_id']) + ']'
        if cn not in stats: stats[cn] = {'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys']+=r['cnt']; tb+=r['cnt']
        elif (r['gender'] or '').lower().startswith('f'): stats[cn]['girls']+=r['cnt']; tg+=r['cnt']
    max_v = max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    chart_html = "".join([f"<div style='text-align:center;min-width:90px'><div style='display:flex;gap:10px;align-items:end;justify-content:center;height:170px'><div><div style='width:42px;height:{bh}px;background:#0a84ff;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px;height:{gh}px;background:#ff2d92;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px;font-weight:800;margin-top:8px'>{cn}</div></div>" for cn,v in stats.items() for bh in [int((v['boys']/max_v)*150) if v['boys']>0 else 6] for gh in [int((v['girls']/max_v)*150) if v['girls']>0 else 6]]) or "<div style='padding:30px;color:#94a3b8;text-align:center;width:100%'>No students yet</div>"
    stu_rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{st['name']}</td><td style='padding:10px 12px;font-size:11px'>{st['assessment_no'] or ''}</td><td style='padding:10px 12px;font-size:11px'>{st['gender']}</td><td>Class {st['class_id'] or ''}</td></tr>" for st in recent_students]) or "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No students yet</td></tr>"
    header = school_header(school, name, "dashboard", is_impersonating=is_imp)
    html = f"""<div style='padding:18px;max-width:1400px;margin:auto'><div style='background:linear-gradient(135deg,#0b3d91 0%, #1e3a8a 60%, #1e40af 100%);border-radius:18px;padding:22px 24px;color:white;display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'><div><div style='font-size:22px;font-weight:900'>Mabale_ICT Management System 🚀</div><div style='font-size:12px;color:#bfdbfe;margin-top:4px'>Set Marks Config: {set_cfg_count} | Students: {sc}</div></div><div style='text-align:right'><div style='font-size:34px;font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students</div></div></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px'><a href='/school/students' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🎓 TOTAL STUDENTS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{sc}</div></a><a href='/school/classes' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🏫 CLASSES</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{cc}</div></a><a href='/school/exams' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>📝 EXAMS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{ec}</div></a><a href='/school/teachers' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>👨‍🏫 STAFF</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{tc}</div></a></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='display:flex;justify-content:space-between'><div><div style='font-weight:800;font-size:14px'>👥 Students by Gender</div></div><div style='display:flex;gap:12px;font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex;gap:24px;overflow-x:auto;margin-top:18px'>{chart_html}</div></div><div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:14px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px 16px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><div style='font-weight:800'>🎓 Recent Students</div><a href='/school/students' style='font-size:11px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:10px;color:#64748b'><th style='padding:10px 12px'>Name</th><th>Adm No</th><th>Gender</th><th>Class</th></tr></thead><tbody>{stu_rows}</tbody></table></div><div style='background:#0b3d91;border-radius:14px;padding:16px;color:white;height:fit-content'><div style='font-weight:800;font-size:14px'>📊 LIVE</div><div style='background:#1e293b;border-radius:10px;padding:12px;margin-top:10px'><div style='font-size:11px'>👦 {tb} | 👧 {tg}</div><div style='font-size:11px;margin-top:6px;color:#22c55e'>Out Of Config: {set_cfg_count}</div><a href='/school/set-marks' style='display:block;margin-top:10px;background:white;color:#0b3d91;padding:8px;border-radius:8px;text-align:center;text-decoration:none;font-weight:800;font-size:12px'>📄 Set Marks</a></div></div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall()
    con.close()
    header = school_header(school, name, "students", is_impersonating=is_imp)
    body = students_manager_html(students, classes, school["name"], is_global=False)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), assessment_no: str = Form(""), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), category: str = Form("Day"), guardian_name: str = Form(""), parent_phone: str = Form("")):
    school = get_school_obj(request)
    if not school or not _role_permission(request,"students.create"):
        return RedirectResponse("/portal",303)
    con = get_db(); cur = con.cursor()
    if not cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,school["id"])).fetchone():
        con.close()
        return HTMLResponse("Invalid class for this school.",403)
    adm=admission_no.strip().upper()
    ass=assessment_no.strip().upper()
    if not student_name.strip() or not adm:
        con.close()
        return HTMLResponse("Student name and admission number are required.",400)
    if cur.execute("SELECT id FROM students WHERE school_id=? AND upper(admission_no)=?",(school["id"],adm)).fetchone():
        con.close()
        return HTMLResponse("Admission number already exists in this school.",409)
    if ass and cur.execute("SELECT id FROM students WHERE school_id=? AND upper(assessment_no)=?",(school["id"],ass)).fetchone():
        con.close()
        return HTMLResponse("Assessment number already exists in this school.",409)
    cur.execute("INSERT INTO students (school_id, admission_no, assessment_no, name, class_id, gender, parent_phone, category, guardian_name) VALUES (?,?,?,?,?,?,?,?,?)",(school["id"],adm,ass,student_name.strip().upper(),class_id,gender.strip(),category.strip(),guardian_name.strip().upper(),parent_phone.strip()))
    con.commit(); con.close()
    return RedirectResponse("/school/students",303)
@app.get("/school/students/delete/{sid}")
def del_stud(sid: int, request: Request):
    school = get_school_obj(request)
    if not school: return RedirectResponse("/",303)
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM students WHERE id=? AND school_id=?", (sid, school["id"]))
    con.commit(); con.close()
    return RedirectResponse("/school/students",303)

@app.get("/school/dean-settings", response_class=HTMLResponse)
def dean_settings(request: Request, tab: str = "terms", class_id: int | None = None):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY year DESC, id DESC", (school["id"],)); terms = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (school["id"],)); subjects = cur.fetchall()
    cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name", (school["id"],)); teachers = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall()
    if class_id is not None:
        cur.execute("SELECT ta.*, t.name as tname, s.name as sname, c.name as cname FROM teacher_allocations ta LEFT JOIN teachers t ON ta.teacher_id=t.id LEFT JOIN subjects s ON ta.subject_id=s.id LEFT JOIN classes c ON ta.class_id=c.id WHERE ta.school_id=? AND ta.class_id=? ORDER BY s.name, t.name", (school["id"], class_id))
    else:
        cur.execute("SELECT ta.*, t.name as tname, s.name as sname, c.name as cname FROM teacher_allocations ta LEFT JOIN teachers t ON ta.teacher_id=t.id LEFT JOIN subjects s ON ta.subject_id=s.id LEFT JOIN classes c ON ta.class_id=c.id WHERE ta.school_id=? ORDER BY t.name", (school["id"],))
    allocs = cur.fetchall()
    cur.execute("SELECT COUNT(*) as cnt FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["cnt"]
    con.close()
    header = school_header(school, name, "dean-settings", is_impersonating=is_imp)
    body = dean_manager_html(terms, subjects, teachers, classes, allocs, sc, school["name"], is_global=False, active_tab=tab)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/dean-settings/add-term")
def school_add_term(request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO terms (school_id, term_name, year, start_date, end_date) VALUES (?,?,?,?,?)", (school["id"], term_name, year.strip(), start_date, end_date)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=terms",303)
@app.post("/school/dean-settings/edit-term/{tid}")
def school_edit_term(tid: int, request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("UPDATE terms SET term_name=?, year=?, start_date=?, end_date=? WHERE id=?", (term_name, year.strip(), start_date, end_date, tid)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=terms",303)
@app.get("/school/dean-settings/delete-term/{tid}")
def school_del_term(tid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM terms WHERE id=?", (tid,)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=terms",303)
@app.post("/school/dean-settings/add-subject")
def school_dean_add_subject(request: Request, subject_name: str = Form(...), code: str = Form(""), initial: str = Form("")):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"subjects.create"): return RedirectResponse("/portal",303)
    con=get_db(); cur=con.cursor(); nm=subject_name.strip().upper(); cd=code.strip().upper()
    if not nm: con.close(); return HTMLResponse("Subject name is required.",400)
    if cur.execute("SELECT id FROM subjects WHERE school_id=? AND upper(name)=?",(school["id"],nm)).fetchone() or (cd and cur.execute("SELECT id FROM subjects WHERE school_id=? AND upper(code)=?",(school["id"],cd)).fetchone()):
        con.close(); return HTMLResponse("Subject name or code already exists in this school.",409)
    cur.execute("INSERT INTO subjects (school_id,name,code,initial) VALUES (?,?,?,?)",(school["id"],nm,cd,initial.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=subjects",303)
@app.get("/school/dean-settings/delete-subject/{sid}")
def school_dean_del_subject(sid: int, request: Request):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"subjects.edit"): return RedirectResponse("/portal",303)
    con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?",(sid,school["id"])); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=subjects",303)
@app.post("/school/dean-settings/allocate")
def school_dean_allocate(request: Request, teacher_id: int = Form(...), subject_id: int = Form(...), class_id: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    sid=school["id"]
    valid_teacher=cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone()
    valid_subject=cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    valid_class=cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
    if not (valid_teacher and valid_subject and valid_class):
        con.close(); return HTMLResponse("Invalid teacher, subject or class selection.",400)
    duplicate=cur.execute("SELECT id FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND subject_id=? AND class_id=?",(sid,teacher_id,subject_id,class_id)).fetchone()
    if duplicate:
        con.close(); return HTMLResponse("This teacher allocation already exists.",400)
    cur.execute("INSERT INTO teacher_allocations (school_id, teacher_id, subject_id, class_id) VALUES (?,?,?,?,?)", (sid, teacher_id, subject_id, class_id))
    con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=allocation",303)
@app.get("/school/dean-settings/delete-alloc/{aid}")
def school_del_alloc(request: Request, aid: int):
    school=get_school_obj(request); con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM teacher_allocations WHERE id=? AND school_id=?",(aid,school["id"]))
    con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=allocation",303)
@app.post("/school/dean-settings/promote")
def school_promote(request: Request, from_class: int = Form(...), to_class: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); sid=school["id"]
    if not cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(from_class,sid)).fetchone() or not cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(to_class,sid)).fetchone():
        con.close(); return HTMLResponse("Both classes must belong to this school.",400)
    cur.execute("UPDATE students SET class_id=? WHERE school_id=? AND class_id=?", (to_class, sid, from_class))
    con.commit(); con.close(); return RedirectResponse(f"/school/dean-settings?tab=promote",303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px 12px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><form method='post' action='/school/classes/delete/{c[0]}' style='display:inline'><button type='submit' onclick='return confirm(\"Delete this class?\")' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border:0;border-radius:6px;cursor:pointer'>🗑️</button></form></td></tr>" for c in classes]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No classes</td></tr>"
    header = school_header(school, name, "classes", is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>🏫 Classes & Streams ({len(classes)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0b3d91;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Class</b><form method='post' action='/school/classes/add'><input name='class_name' required placeholder='Class Name *' class='input-field'><input name='stream' required placeholder='Stream *' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Class</button></form></div></div></div></div></div></body></html>")
@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    # Keep the school-admin session attached to the school when this form is
    # submitted. If the session's school_id is missing/stale, recover it from
    # the authenticated school-admin account instead of sending the user to login.
    if request.session.get("role") not in ("school_admin", "registrar", "super_admin") or not request.session.get("email"):
        return RedirectResponse("/", 303)
    school = get_school_obj(request)
    if not school:
        con = get_db(); cur = con.cursor()
        user = cur.execute(
            "SELECT school_id FROM users WHERE lower(email)=lower(?) AND role IN ('school_admin','super_admin') LIMIT 1",
            (request.session.get("email",""),)
        ).fetchone()
        con.close()
        if user and user["school_id"]:
            request.session["school_id"] = user["school_id"]
            school = get_school_obj(request)
    if not school or not _role_permission(request,"classes.create"):
        return RedirectResponse("/school/classes", 303)
    con=get_db(); cur=con.cursor()
    nm=class_name.strip().upper(); st=stream.strip().upper()
    if not nm:
        con.close()
        return HTMLResponse("Class name is required.",400)
    if cur.execute("SELECT id FROM classes WHERE school_id=? AND upper(name)=? AND upper(stream)=?",
                   (school["id"],nm,st)).fetchone():
        con.close()
        return HTMLResponse("That class/stream already exists in this school.",409)
    cur.execute("INSERT INTO classes (school_id,name,stream) VALUES (?,?,?)",(school["id"],nm,st))
    con.commit(); con.close()
    return RedirectResponse("/school/classes",303)

@app.post("/school/classes/delete/{cid}")
def del_class(cid: int, request: Request):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"classes.edit"):
        return RedirectResponse("/school/classes",303)
    con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM classes WHERE id=? AND school_id=?",(cid,school["id"]))
    con.commit(); con.close(); return RedirectResponse("/school/classes",303)

# EXAM SETTINGS RESTORED - EXACT — YOUR PART 2
@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY year DESC, id DESC", (school["id"],))
    exams = cur.fetchall(); con.close()
    header = school_header(school, name, "exams", is_impersonating=is_imp)
    body = exam_manager_html(exams, school["name"], is_global=False)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip()))
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id, user_email, action, details, timestamp) VALUES (?,?,?,?,?)", (school["id"], request.session.get("email",""), "ADD EXAM", f"{exam_name} {year}", ts))
    con.commit(); con.close()
    return RedirectResponse("/school/exams",303)
@app.post("/school/exams/edit/{eid}")
def edit_exam(eid: int, request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE exams SET name=?, term=?, year=?, exam_type=? WHERE id=?", (exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip(), eid))
    con.commit(); con.close()
    return RedirectResponse("/school/exams",303)
@app.get("/school/exams/delete/{eid}")
def del_exam(eid: int, request: Request):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"exams.edit"): return RedirectResponse("/portal",303)
    con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM exams WHERE id=? AND school_id=?",(eid,school["id"])); con.commit(); con.close(); return RedirectResponse("/school/exams",303)

@app.get("/school/teachers", response_class=HTMLResponse)
def teachers_page(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY id DESC", (school["id"],)); teachers = cur.fetchall(); con.close()
    header = school_header(school, name, "teachers", is_impersonating=is_imp)
    body = staff_manager_html(teachers, school["name"], is_global=False)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
def _staff_department_choices(role):
    teaching_roles={'teacher','classteacher','principal','deputy principal'}
    if (role or '').strip().lower() in teaching_roles:
        return ['ECDE / Early Childhood Education','Lower Primary','Upper Primary','Junior School','Senior School','Languages','Mathematics','Sciences','Humanities & Social Sciences','Technical & Vocational Studies','Creative Arts & Sports','Religious Education','Special Needs Education','Academic Coordination']
    return ['School Administration','Registry & Admissions','Finance & Accounts','Human Resources','ICT & Technology','Library Services','Guidance & Counselling','Examinations Department','Laboratory Department','Sports & Physical Education','Transport Department','Security Department','Catering & Nutrition','Health & Medical Services','Maintenance & Facilities','Cleaning & Sanitation','Boarding & Accommodation','Procurement & Stores','Support Services','Other']

@app.post("/school/teachers/add")
def add_teacher(request: Request, name: str = Form(...), tsc_no: str = Form(""), id_no: str = Form(...), gender: str = Form(...), role: str = Form(...), department: str = Form(""), phone: str = Form(...), email: str = Form(""), employment_type: str = Form("Teaching")):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"staff.create"): return RedirectResponse("/portal",303)
    con=get_db(); cur=con.cursor(); nm=name.strip().upper(); ident=id_no.strip(); em=email.strip()
    if not nm or not ident: con.close(); return HTMLResponse("Staff name and ID number are required.",400)
    if cur.execute("SELECT id FROM teachers WHERE school_id=? AND (id_no=? OR (email<>'' AND lower(email)=lower(?)))",(school["id"],ident,em)).fetchone():
        con.close(); return HTMLResponse("A staff record with that ID or email already exists in this school.",409)
    department=department.strip()
    allowed_departments=_staff_department_choices(role)
    if department and department not in allowed_departments: department=''
    cur.execute("INSERT INTO teachers (school_id,name,email,phone,tsc_no,gender,id_no,role,employment_type,department,teacher_color) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(school["id"],nm,em,phone.strip(),tsc_no.strip(),gender.strip(),ident,role.strip(),employment_type.strip(),department,"#2563EB"))
    created_teacher = cur.execute("SELECT id FROM teachers WHERE school_id=? AND id_no=? ORDER BY id DESC LIMIT 1",(school["id"],ident)).fetchone()
    if created_teacher:
        cur.execute("UPDATE teachers SET teacher_color=? WHERE id=? AND school_id=?",(_teacher_timetable_color(created_teacher["id"]),created_teacher["id"],school["id"]))
    con.commit(); con.close(); return RedirectResponse("/school/teachers",303)
@app.get("/school/teachers/delete/{tid}")
def del_teacher(tid: int, request: Request):
    school = get_school_obj(request)
    if not school: return RedirectResponse("/",303)
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM teachers WHERE id=? AND school_id=?", (tid, school["id"]))
    con.commit(); con.close()
    return RedirectResponse("/school/teachers",303)

# === ONLY CHANGED PART — RECORD MARKS EXACT PHOTO ===
@app.get("/school/record-marks", response_class=HTMLResponse)
def school_record_marks(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT DISTINCT stream FROM classes WHERE school_id=? AND stream!='' ORDER BY stream", (school["id"],)); streams = [r["stream"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT year FROM terms WHERE school_id=? ORDER BY year DESC", (school["id"],)); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years: years = [str(datetime.now().year)]
    cur.execute("SELECT DISTINCT term_name FROM terms WHERE school_id=?", (school["id"],)); terms_list = [r["term_name"] for r in cur.fetchall()]
    if not terms_list: terms_list = ["Term 1","Term 2","Term 3"]
    cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school["id"],)); exams = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (school["id"],)); subjects = cur.fetchall()
    con.close()
    header = school_header(school, name, "record-marks", is_impersonating=is_imp)
    opts_class = "".join([f"<option>{c['name']}</option>" for c in classes])
    opts_stream = "".join([f"<option>{s}</option>" for s in streams])
    opts_year = "".join([f"<option>{y}</option>" for y in years])
    opts_term = "".join([f"<option>{t}</option>" for t in terms_list])
    opts_exam = "".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams])
    opts_subj = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    html = f"""<div style='padding:20px;max-width:1400px;margin:auto'><h1 style='margin:0;font-size:22px;font-weight:900'>✏️ Record Marks</h1><p style='color:#64748b;font-size:13px'>Select filters — system checks Out Of from Set Marks</p><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-top:14px;display:grid;grid-template-columns:repeat(3,1fr);gap:12px'><form method='post' action='/school/record-marks/load' style='display:contents'><select name='class_name' required class='input-field'><option value=''>Select Class *</option>{opts_class}</select><select name='stream' required class='input-field'><option value=''>Select Stream *</option>{opts_stream}</select><select name='year' required class='input-field'><option value=''>Select Year *</option>{opts_year}</select><select name='term' required class='input-field'><option value=''>Select Term *</option>{opts_term}</select><select name='exam_id' required class='input-field'><option value=''>Select Exam *</option>{opts_exam}</select><select name='subject_id' required class='input-field'><option value=''>Select Subject *</option>{opts_subj}</select><button style='grid-column:span 3;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;font-weight:800'>🔍 Load Students</button></form></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{html}</div></div></body></html>")

@app.post("/school/record-marks/load", response_class=HTMLResponse)
def school_record_load(request: Request, class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), exam_id: int = Form(...), subject_id: int = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    if not school:
        con.close()
        return RedirectResponse("/",303)
    # Validate the selected academic references before loading the marks window.
    # This is read-time validation: it must use only values available to this route.
    if not cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?", (subject_id, school["id"])).fetchone():
        con.close()
        return HTMLResponse("Invalid subject for this school. <a href='/school/record-marks'>Back</a>", status_code=403)
    if not cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?", (exam_id, school["id"])).fetchone():
        con.close()
        return HTMLResponse("Invalid examination for this school. <a href='/school/record-marks'>Back</a>", status_code=403)
    if request.session.get("role")=="teacher" and not _role_permission(request,"marks.edit"):
        con.close()
        return HTMLResponse("Your account is not permitted to record marks.",403)
    cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (school["id"], class_name.upper(), stream.upper()))
    cl = cur.fetchone()
    if not cl:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? LIMIT 1", (school["id"], class_name.upper()))
        cl = cur.fetchone()
    class_id = cl["id"] if cl else 0
    if not class_id or not _teacher_allocation_allowed(request,school["id"],class_id,subject_id):
        con.close()
        return HTMLResponse("This subject/class is not assigned to your teacher account.",403)
    cur.execute("SELECT * FROM students WHERE school_id=? AND class_id=? ORDER BY name", (school["id"], class_id)); students_raw = cur.fetchall()
    cur.execute("SELECT out_of FROM set_marks_config WHERE school_id=? AND class_name=? AND stream=? AND year=? AND term=? AND exam_id=? AND subject_id=?", (school["id"], class_name.upper(), stream.upper(), year, term, exam_id, subject_id))
    cfg = cur.fetchone()
    out_of = cfg["out_of"] if cfg else 100
    cur.execute("SELECT name FROM subjects WHERE id=?", (subject_id,)); srow = cur.fetchone(); subj_name = srow["name"] if srow else "Subject"
    cur.execute("SELECT name FROM exams WHERE id=?", (exam_id,)); erow = cur.fetchone(); exam_name = erow["name"] if erow else "Exam"
    cur.execute("SELECT student_id, marks FROM marks WHERE school_id=? AND class_id=? AND exam_id=? AND subject_id=?", (school["id"], class_id, exam_id, subject_id))
    existing = {str(r["student_id"]): r["marks"] for r in cur.fetchall()}
    con.close()
    students = []
    filled = 0
    for st in students_raw:
        m = existing.get(str(st["id"]))
        if m is not None and str(m).strip()!="":
            filled+=1
        students.append({"id":st["id"],"name":st["name"],"admission_no":st["admission_no"] or st["assessment_no"] or "","marks": m if m is not None else ""})
    header = school_header(school, name, "record-marks", is_impersonating=is_imp)
    body = record_marks_exact_html(students, subj_name, exam_name, class_name.upper(), stream.upper(), out_of, len(students), filled, school["name"], exam_id, subject_id, year, term)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{body}</div></div></body></html>")

@app.post("/school/record-marks/auto-save")
def school_record_auto_save(request: Request, student_id: int = Form(...), exam_id: int = Form(...), subject_id: int = Form(...), class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), out_of: int = Form(...), marks: str = Form(...)):
    if "email" not in request.session: return JSONResponse({"ok":False})
    school = get_school_obj(request)
    if not school: return JSONResponse({"ok":False})
    if request.session.get("role")=="teacher" and not _role_permission(request,"marks.edit"):
        return JSONResponse({"ok":False,"message":"Your account is not permitted to record marks."},status_code=403)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (school["id"], class_name.upper(), stream.upper()))
    cl = cur.fetchone()
    if not cl:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? LIMIT 1", (school["id"], class_name.upper()))
        cl = cur.fetchone()
    class_id = cl["id"] if cl else 0
    if not class_id or not _teacher_allocation_allowed(request,school["id"],class_id,subject_id):
        con.close()
        return JSONResponse({"ok":False,"message":"This subject/class is not assigned to your teacher account."},status_code=403)
    try:
        # The write endpoint is the authoritative place for mark validation.
        if out_of <= 0:
            con.close()
            return JSONResponse({"ok":False,"message":"Invalid maximum mark."}, status_code=400)
        if not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?", (student_id, school["id"])).fetchone():
            con.close()
            return JSONResponse({"ok":False,"message":"Student is not part of this school."}, status_code=403)
        if not cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?", (subject_id, school["id"])).fetchone():
            con.close()
            return JSONResponse({"ok":False,"message":"Subject is not part of this school."}, status_code=403)
        if not cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?", (exam_id, school["id"])).fetchone():
            con.close()
            return JSONResponse({"ok":False,"message":"Examination is not part of this school."}, status_code=403)
        if marks.strip()=="": cur.close(); con.close(); return JSONResponse({"ok":True})
        m = int(float(marks.strip()))
        if m < 0 or m > out_of:
            con.close()
            return JSONResponse({"ok":False,"message":f"Marks must be between 0 and {out_of}."}, status_code=400)
        cur.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=?", (school["id"], student_id, subject_id, exam_id))
        ex = cur.fetchone()
        if ex:
            cur.execute("UPDATE marks SET marks=?, class_id=?, year=?, term=? WHERE id=?", (m, class_id, year, term, ex["id"]))
        else:
            cur.execute("INSERT INTO marks (school_id, student_id, subject_id, exam_id, class_id, marks, year, term) VALUES (?,?,?,?,?,?,?,?)", (school["id"], student_id, subject_id, exam_id, class_id, m, year, term))
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO system_audit (school_id, user_email, action, details, timestamp) VALUES (?,?,?,?,?)", (school["id"], request.session.get("email",""), "RECORD MARKS AUTO-SAVE", f"{class_name} {stream} {m}/{out_of}", ts))
        con.commit()
    except Exception as e:
        pass
    con.close()
    return JSONResponse({"ok":True})

# === SYSTEM SETTINGS — EXACT YOUR PART 2 ===
@app.get("/school/system-settings/{sub}", response_class=HTMLResponse)
def school_system_settings(sub: str, request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school_obj = get_school_obj(request)
    if not school_obj: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (school_obj["id"],)); school = cur.fetchone()
    cur.execute("SELECT * FROM users WHERE school_id=? ORDER BY id DESC", (school_obj["id"],)); users = cur.fetchall()
    cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name", (school_obj["id"],)); teachers_for_users = cur.fetchall()
    cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY name", (school_obj["id"],)); students_for_users = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school_obj["id"],)); classes = cur.fetchall()
    cur.execute("SELECT * FROM system_audit WHERE school_id=? ORDER BY id DESC LIMIT 200", (school_obj["id"],)); audit = cur.fetchall()
    cur.execute("SELECT * FROM billing WHERE school_id=? ORDER BY id DESC", (school_obj["id"],)); bills = cur.fetchall()
    con.close()
    header = school_header(school_obj, name, f"system-settings/{sub}", is_impersonating=is_imp)
    base_path = "/school/system-settings"
    if sub=="school-profile":
        profile_name=escape(str(school["name"] or ""))
        profile_email=escape(str(school["email"] or ""))
        profile_location=escape(str(school["location"] or ""))
        profile_phone=escape(str(school["phone"] or ""))
        profile_principal=escape(str(school["principal"] or ""))
        profile_type=str(school["school_type"] or "")
        profile_code=escape(str(school["code"] or "—"))
        type_options="".join(f"<option value='{escape(t)}' {'selected' if profile_type==t else ''}>{escape(t)}</option>" for t in ("Primary","Junior School","Primary & Junior School","Senior School","Tertiary/College","University"))
        panel=f"""
        <style>
        .sp-wrap{{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(250px,.75fr);gap:18px;align-items:start}}
        .sp-card{{background:#fff;border:1px solid #dce9de;border-radius:18px;box-shadow:0 8px 26px rgba(30,75,43,.055);overflow:hidden}}
        .sp-card-head{{padding:19px 21px;border-bottom:1px solid #e8f0e9;background:linear-gradient(120deg,#edf7ef,#fff)}}
        .sp-kicker{{font-size:10px;font-weight:900;letter-spacing:1.2px;color:#63866a;text-transform:uppercase}}
        .sp-card-head h2{{font-size:18px;color:#1d5734;margin:5px 0 4px}}
        .sp-card-head p{{font-size:12px;color:#718078;margin:0;line-height:1.55}}
        .sp-form{{padding:21px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}}
        .sp-field{{display:grid;gap:7px;min-width:0}}
        .sp-field label{{font-size:11px;font-weight:800;color:#49634f}}
        .sp-field input,.sp-field select{{width:100%;min-height:43px;border:1px solid #d5e3d7;border-radius:10px;background:#fbfdfb;padding:10px 12px;color:#26372d;font-size:13px;outline:none}}
        .sp-field input:focus,.sp-field select:focus{{border-color:#6fa77c;box-shadow:0 0 0 3px #6fa77c20;background:#fff}}
        .sp-span{{grid-column:1/-1}}
        .sp-actions{{grid-column:1/-1;display:flex;justify-content:flex-end;align-items:center;gap:10px;padding-top:5px}}
        .sp-save{{border:0;border-radius:10px;padding:12px 18px;background:linear-gradient(130deg,#287b49,#145b34);color:white;font-size:12px;font-weight:900;cursor:pointer;box-shadow:0 5px 14px #145b3425}}
        .sp-aside{{padding:19px}}
        .sp-code{{padding:17px;border-radius:14px;background:linear-gradient(135deg,#185b36,#2e8050);color:#fff}}
        .sp-code small{{display:block;color:#d8ecdd;font-size:10px;font-weight:800;letter-spacing:1px;text-transform:uppercase}}
        .sp-code strong{{display:block;margin-top:7px;font-size:25px;letter-spacing:1px}}
        .sp-stat{{display:flex;justify-content:space-between;gap:10px;padding:13px 2px;border-bottom:1px solid #edf2ed;font-size:12px;color:#708075}}
        .sp-stat b{{color:#285b39}}
        .sp-note{{margin-top:14px;padding:13px;border:1px solid #dceade;border-radius:12px;background:#f4faf5;color:#617568;font-size:11px;line-height:1.6}}
        @media(max-width:850px){{.sp-wrap{{grid-template-columns:1fr}}}}
        @media(max-width:560px){{.sp-form{{grid-template-columns:1fr;padding:16px}}.sp-span{{grid-column:auto}}.sp-actions{{grid-column:auto;justify-content:stretch}}.sp-save{{width:100%}}.sp-card-head{{padding:16px}}}}
        </style>
        <div class='sp-wrap'>
          <section class='sp-card'>
            <div class='sp-card-head'><span class='sp-kicker'>Institution identity</span><h2>School profile</h2><p>Keep your school's official details accurate. These details identify your institution across Mabale_ICT.</p></div>
            <form class='sp-form' method='post' action='{base_path}/update-profile'>
              <div class='sp-field sp-span'><label for='sp-name'>School name</label><input id='sp-name' name='name' value="{profile_name}" required maxlength='160' placeholder='Enter registered school name'></div>
              <div class='sp-field'><label for='sp-email'>Official email address</label><input id='sp-email' name='email' type='email' value="{profile_email}" placeholder='school@example.com'></div>
              <div class='sp-field'><label for='sp-phone'>Telephone / mobile</label><input id='sp-phone' name='phone' type='tel' value="{profile_phone}" placeholder='School contact number'></div>
              <div class='sp-field sp-span'><label for='sp-location'>Physical location / address</label><input id='sp-location' name='location' value="{profile_location}" placeholder='Town, county or physical address'></div>
              <div class='sp-field'><label for='sp-principal'>Head of institution</label><input id='sp-principal' name='principal' value="{profile_principal}" placeholder='Name of head of institution'></div>
              <div class='sp-field'><label for='sp-type'>Institution type</label><select id='sp-type' name='school_type' required>{type_options}</select></div>
              <div class='sp-actions'><button class='sp-save' type='submit'>Save School Profile&nbsp; →</button></div>
            </form>
          </section>
          <aside class='sp-card'>
            <div class='sp-card-head'><span class='sp-kicker'>Account overview</span><h2>School identity</h2><p>Quick reference for this registered institution.</p></div>
            <div class='sp-aside'>
              <div class='sp-code'><small>Unique school code</small><strong>{profile_code}</strong></div>
              <div class='sp-stat'><span>Registered school users</span><b>{len(users)}</b></div>
              <div class='sp-stat'><span>Institution type</span><b>{escape(profile_type or "Not set")}</b></div>
              <div class='sp-stat'><span>Account status</span><b>{escape(str(school["status"] or "Active")).title()}</b></div>
              <div class='sp-note'>Use the official school name, email and contact details. Saved profile information remains linked to this school's records.</div>
            </div>
          </aside>
        </div>"""

    elif sub=="classes":
        rows = "".join([f"<tr><td style='padding:10px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><a href='{base_path}/delete-class/{c[0]}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No classes</td></tr>"
        panel = f"""<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>🏫 Classes ({len(classes)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Class</b><form method='post' action='{base_path}/add-class'><input name='class_name' required placeholder='Class' class='input-field'><input name='stream' required placeholder='Stream' class='input-field'><button class='add-btn'>Add</button></form></div></div>"""
    elif sub=="user-management":
        user_rows = []
        for u in users[:100]:
            user_role = str(u["role"] or "")
            creator_role = str(u["created_by_role"] or "")
            owner_label = "Super Admin" if user_role == "school_admin" or (user_role == "registrar" and creator_role == "super_admin") else ("School Admin" if user_role == "registrar" else "—")
            safe_name = escape(str(u["full_name"] or ""))
            safe_email = escape(str(u["email"] or ""))
            edit_url = f"{base_path}/edit-user/{u['id']}"
            delete_url = f"{base_path}/delete-user/{u['id']}"
            user_rows.append(f"""<tr><td style='padding:10px;font-size:12px'>{safe_name}</td><td>{safe_email}</td><td>{escape(user_role)}</td><td>{owner_label}</td><td><a href='{edit_url}' style='background:#e0f2fe;color:#075985;padding:4px 8px;border-radius:6px;text-decoration:none;margin-right:4px'>✏️ Edit</a><a href='{delete_url}' onclick="return confirm('Delete this account? This cannot be undone.')" style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>""")
        urows = "".join(user_rows) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No users</td></tr>"
        school_opts = "".join([f"<option value='{s['id']}'>{escape(str(s['name'] or ''))} ({escape(str(s['email'] or ''))})</option>" for s in global_schools])
        panel = f"""<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px'><b>👥 Global Users ({len(users)})</b></div><div style='overflow-x:auto'><table style='width:100%'><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Owner</th><th>Actions</th></tr></thead><tbody>{urows}</tbody></table></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><b>➕ Create Account</b><div style='font-size:12px;color:#64748b;margin:6px 0 10px'>Super Admin can create a School Admin or Registrar for one selected school.</div><form method='post' action='{base_path}/add-user'><select name='school_id' required class='input-field'>{school_opts}</select><input name='full_name' required placeholder='Full name' class='input-field'><input name='email' type='email' required placeholder='Email / Username' class='input-field'><input name='password' required minlength='8' placeholder='Password' class='input-field'><select name='role' class='input-field'><option value='school_admin'>School Admin</option><option value='registrar'>Registrar</option></select><button class='add-btn'>Create Account</button></form></div></div>"""
    elif sub=="database-backup":
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px'><h3>💾 Backup — {school['name']}</h3><a href='{base_path}/backup/download' style='background:#0b3d91;color:white;padding:12px 18px;border-radius:10px;text-decoration:none'>⬇️ Download</a></div>"""
    elif sub=="system-audit":
        audit_rows = "".join([f"<tr><td style='padding:10px'>{a['timestamp'] or ''}</td><td>{a['user_email'] or ''}</td><td>{a['action'] or ''}</td><td>{a['details'] or ''}</td></tr>" for a in audit[:100]]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No logs</td></tr>"
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px'><div style='padding:14px;display:flex;justify-content:space-between'><b>📈 Audit</b><a href='{base_path}/audit/clear' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:8px;text-decoration:none'>Clear</a></div><table style='width:100%'><tbody>{audit_rows}</tbody></table></div>"""
    elif sub=="billing-payments":
        brows = "".join([f"<tr><td style='padding:10px'>{b['amount']}</td><td>{b['status']}</td><td>{b['due_date'] or ''}</td></tr>" for b in bills]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No invoices</td></tr>"
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px'><h3>💳 Billing</h3><form method='post' action='{base_path}/billing/add'><input name='amount' required placeholder='Amount' class='input-field' style='width:200px'><select name='status' class='input-field' style='width:200px'><option>Paid</option><option>Pending</option></select><input name='due_date' type='date' class='input-field' style='width:200px'><button class='add-btn' style='width:200px'>Add</button></form><table style='width:100%;margin-top:10px'><tbody>{brows}</tbody></table></div>"""
    elif sub=="roles-permissions":
        con2=get_db(); rp=con2.execute("SELECT * FROM roles_permissions WHERE school_id=? ORDER BY role,permission",(school_obj["id"],)).fetchall(); con2.close()
        rows="".join([f"<tr><td style='padding:9px'>{r['role']}</td><td>{r['permission']}</td><td>{'Enabled' if r['enabled'] else 'Disabled'}</td></tr>" for r in rp]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No custom permissions yet.</td></tr>"
        panel=f"<div style='display:grid;grid-template-columns:1.5fr .8fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><h3>🛡️ Roles & Permissions</h3><table style='width:100%'><tr><th align='left'>Role</th><th align='left'>Permission</th><th align='left'>Status</th></tr>{rows}</table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><b>Add Permission</b><form method='post' action='/school/modules/roles/add'><input name='role' required placeholder='Role' class='input-field'><input name='permission' required placeholder='Permission' class='input-field'><button class='add-btn'>Save</button></form></div></div>"
    elif sub=="integrations":
        con2=get_db(); ints=con2.execute("SELECT * FROM integrations WHERE school_id=? ORDER BY id DESC",(school_obj["id"],)).fetchall(); con2.close()
        rows="".join([f"<tr><td style='padding:9px'>{i['name']}</td><td>{i['status']}</td><td>{i['config'] or ''}</td></tr>" for i in ints]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No integrations configured.</td></tr>"
        panel=f"<div style='display:grid;grid-template-columns:1.5fr .8fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><h3>🔌 Integrations</h3><table style='width:100%'><tr><th align='left'>Integration</th><th align='left'>Status</th><th align='left'>Configuration</th></tr>{rows}</table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><b>Add Integration</b><form method='post' action='/school/modules/integrations/add'><input name='name' required placeholder='Integration' class='input-field'><select name='status' class='input-field'><option>Configured</option><option>Pending</option><option>Disabled</option></select><input name='config' placeholder='Configuration note' class='input-field'><button class='add-btn'>Save</button></form></div></div>"
    else:
        panel = f"<div style='background:white;border-radius:16px;padding:40px;text-align:center'><h3>⚙️ {sub.replace('-', ' ').title()}</h3><p style='color:#64748b'>Module window available.</p></div>"
    def pill(tab, label, icon):
        active_style = "background:#0b3d91;color:white" if sub==tab else "background:#f8fafc;color:#475569;border:1px solid #e2e8f0"
        return f"<a href='/school/system-settings/{tab}' style='padding:8px 12px;border-radius:10px;text-decoration:none;font-size:12px;font-weight:700;{active_style}'>{icon} {label}</a>"
    pills = f"<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:12px;margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap'>{pill('school-profile','School Profile','🏢')}{pill('classes','Classes','🏫')}{pill('user-management','User Management','👥+')}{pill('database-backup','Database Backup','💾')}{pill('system-audit','System Audit','📈')}{pill('billing-payments','Billing & Payments','💳')}</div>"
    content = f"<div style='padding:20px;max-width:1450px;margin:auto'><h1 style='margin:0;font-size:26px;font-weight:900'>⚙️ System Settings</h1>{pills}{panel}</div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0b3d91;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{content}</div></div></body></html>")
@app.post("/school/system-settings/update-profile")
def sys_update_profile(request: Request, name: str = Form(...), email: str = Form(""), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (name.strip().upper(), email.strip(), location.strip(), phone.strip(), principal.strip(), school_type.strip(), school_obj["id"])); con.commit(); con.close(); return RedirectResponse("/school/system-settings/school-profile",303)
@app.post("/school/system-settings/add-class")
def sys_add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (school_obj["id"], class_name.strip().upper(), stream.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/system-settings/classes",303)
@app.get("/school/system-settings/delete-class/{cid}")
def sys_del_class(request: Request, cid: int):
    school_obj=get_school_obj(request)
    if not school_obj or request.session.get("role") not in ["school_admin","registrar","super_admin"]: return RedirectResponse("/",303)
    con=get_db(); con.execute("DELETE FROM classes WHERE id=? AND school_id=?",(cid,school_obj["id"])); con.commit(); con.close(); return RedirectResponse("/school/system-settings/classes",303)
@app.post("/school/system-settings/add-user")
def sys_add_user(request: Request, full_name: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form(...), teacher_id: str = Form(""), student_id: str = Form("")):
    school_obj = get_school_obj(request)
    if not school_obj or request.session.get("role") not in ["school_admin","registrar","super_admin"] or not _role_permission(request,"users.manage"):
        return RedirectResponse("/",303)
    role_v=role.strip().lower()
    allowed={"teacher","parent","student","school_admin","accountant","registrar"}
    current_role=str(request.session.get("role") or "")
    if role_v=="school_admin" and current_role!="super_admin":
        return HTMLResponse("Only the Super Admin can create School Admin accounts.",403)
    if role_v=="registrar" and current_role not in ("school_admin","registrar","super_admin"):
        return HTMLResponse("Only the School Admin or Super Admin can create Registrar accounts.",403)
    if role_v not in allowed or not full_name.strip() or not email.strip() or not password.strip():
        return HTMLResponse("Invalid user details.",400)
    con=get_db(); cur=con.cursor()
    if cur.execute("SELECT id FROM users WHERE lower(email)=lower(?)",(email.strip(),)).fetchone():
        con.close()
        return HTMLResponse("That email is already registered.",409)
    tid=int(teacher_id) if teacher_id.strip() else None
    stid=int(student_id) if student_id.strip() else None
    if tid is not None and not cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(tid,school_obj["id"])).fetchone():
        con.close(); return HTMLResponse("Invalid teacher for this school.",403)
    if stid is not None and not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(stid,school_obj["id"])).fetchone():
        con.close(); return HTMLResponse("Invalid student for this school.",403)
    if role_v=="teacher" and tid is None:
        con.close(); return HTMLResponse("A teacher account must be linked to a teacher.",400)
    if role_v in ("student","parent") and stid is None:
        con.close(); return HTMLResponse("A student/parent account must be linked to a student.",400)
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id,teacher_id,student_id,created_by_role,created_by_email) VALUES (?,?,?,?,?,?,?,?,?)",(email.strip(),hash_password(password.strip()),role_v,full_name.strip(),school_obj["id"],tid,stid,current_role,request.session.get("email","")))
    con.commit(); con.close()
    return RedirectResponse("/school/system-settings/user-management",303)
@app.get("/school/system-settings/delete-user/{uid}")
def sys_del_user(request: Request, uid: int):
    school_obj=get_school_obj(request)
    if not school_obj or request.session.get("role") not in ["school_admin","registrar","super_admin"]: return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor()
    user=cur.execute("SELECT role FROM users WHERE id=? AND school_id=?",(uid,school_obj["id"])).fetchone()
    if not user:
        con.close()
        return RedirectResponse("/school/system-settings/user-management",303)
    current_role=str(request.session.get("role") or "")
    if str(user["role"] or "")=="school_admin" and current_role!="super_admin":
        con.close()
        return HTMLResponse("School Admin accounts can only be managed by the Super Admin. <a href='/school/system-settings/user-management'>Back</a>",403)
    if str(user["role"] or "")=="registrar" and not (
        (current_role=="school_admin" and str(user["created_by_role"] or "")=="school_admin") or
        (current_role=="super_admin" and str(user["created_by_role"] or "")=="super_admin")
    ):
        con.close()
        return HTMLResponse("This Registrar account is managed by its creator and cannot be removed here.",403)
    cur.execute("DELETE FROM users WHERE id=? AND school_id=?",(uid,school_obj["id"]))
    con.commit(); con.close(); return RedirectResponse("/school/system-settings/user-management",303)
@app.get("/school/system-settings/backup/download")
def sys_backup_download(request: Request):
    school_obj=get_school_obj(request)
    if not school_obj: return RedirectResponse("/",303)
    # SQLite backup is generated from the live DB without modifying the source database.
    backup_dir=os.path.join(os.path.dirname(DB_PATH) or ".", "backups"); os.makedirs(backup_dir,exist_ok=True)
    stamp=datetime.now(ZoneInfo('Africa/Nairobi')).strftime('%Y%m%d_%H%M%S'); out=os.path.join(backup_dir,f"davischool_backup_{stamp}.db")
    src=get_db(); dst=sqlite3.connect(out); src.backup(dst); dst.close(); src.close()
    return FileResponse(out,filename=os.path.basename(out),media_type='application/octet-stream')
@app.get("/school/system-settings/audit/clear")
def sys_audit_clear(request: Request):
    school_obj = get_school_obj(request)
    if not school_obj or request.session.get("role") not in ["school_admin","registrar","super_admin"] or not _role_permission(request,"settings.manage"):
        return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM system_audit WHERE school_id=?",(school_obj["id"],)); con.commit(); con.close()
    return RedirectResponse("/school/system-settings/system-audit",303)
@app.post("/school/system-settings/billing/add")
def sys_billing_add(request: Request, amount: str = Form(...), status: str = Form(...), due_date: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO billing (school_id, amount, status, due_date, created_at) VALUES (?,?,?,?,?)", (school_obj["id"], amount.strip(), status.strip(), due_date.strip(), ts)); con.commit(); con.close(); return RedirectResponse("/school/system-settings/billing-payments",303)

# === GLOBAL — EXACT YOUR PART 2 ===
    tr=''.join(f"<tr><td>{m['subject']}</td><td>{m['exam']}</td><td>{m['marks']}</td><td>{m['term']} {m['year']}</td></tr>" for m in marks) or '<tr><td colspan=4>No academic records yet.</td></tr>'
    body=f"<div class='card'><b>Student:</b> {st['name'] if st else request.session.get('name','')}<br><b>Admission:</b> {st['admission_no'] if st else ''}<br><b>Class:</b> {st['class_name'] if st else ''} {st['stream'] if st else ''}</div><div class='card'><h3>Academic Record</h3><table><tr><th>Subject</th><th>Exam</th><th>Marks</th><th>Term</th></tr>{tr}</table></div>"; con.close(); return portal_page(request,'🎓 Student Portal',body)

@app.get("/portal/parent", response_class=HTMLResponse)
def parent_portal(request: Request):
    if not portal_guard(request) or request.session.get("role") != "parent":
        return RedirectResponse("/", status_code=303)

    school_id = request.session["school_id"]
    user_id = request.session.get("user_id")
    con = get_db()
    cur = con.cursor()
    try:
        # Prefer the explicit parent-child links so one parent account can
        # switch between siblings. Retain compatibility with older accounts.
        linked_students = []
        if user_id:
            try:
                cur.execute("SAVEPOINT parent_links_lookup")
                linked_students = cur.execute(
                    """SELECT s.id, s.name, s.admission_no, c.name AS class_name, c.stream
                       FROM parent_student_links l
                       JOIN students s ON s.id=l.student_id AND s.school_id=l.school_id
                       LEFT JOIN classes c ON c.id=s.class_id
                       WHERE l.school_id=? AND l.user_id=?
                       ORDER BY s.name""",
                    (school_id, user_id)
                ).fetchall()
                cur.execute("RELEASE SAVEPOINT parent_links_lookup")
            except Exception:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT parent_links_lookup")
                    cur.execute("RELEASE SAVEPOINT parent_links_lookup")
                except Exception:
                    pass
                linked_students = []
        if not linked_students and request.session.get("student_id"):
            linked_students = cur.execute(
                """SELECT s.id, s.name, s.admission_no, c.name AS class_name, c.stream
                   FROM students s LEFT JOIN classes c ON c.id=s.class_id
                   WHERE s.id=? AND s.school_id=?""",
                (request.session.get("student_id"), school_id)
            ).fetchall()

        requested_student = request.query_params.get("student_id", "")
        selected = next(
            (item for item in linked_students if str(item["id"]) == str(requested_student)),
            None
        ) if requested_student else None
        st = selected or (linked_students[0] if linked_students else None)
        if not st:
            con.close()
            return portal_page(
                request, "Parent Portal",
                "<section class='parent-empty'><div class='parent-empty-icon'>⌂</div><h2>No linked learner yet</h2><p>Please contact the school office to confirm that your parent account is linked to your child.</p></section>"
            )

        student_id = int(st["id"])
        marks = cur.execute(
            """SELECT sub.name AS subject, e.name AS exam, m.marks, e.term, e.year
               FROM marks m
               JOIN subjects sub ON sub.id=m.subject_id
               JOIN exams e ON e.id=m.exam_id
               WHERE m.student_id=? AND m.school_id=?
               ORDER BY e.year DESC, e.id DESC, sub.name""",
            (student_id, school_id)
        ).fetchall()
        fee = cur.execute(
            """SELECT COALESCE(SUM(amount),0) AS expected,
                      COALESCE(SUM(paid),0) AS paid
               FROM fees WHERE school_id=? AND student_id=?""",
            (school_id, student_id)
        ).fetchone()
        expected = float(fee["expected"] or 0)
        paid = float(fee["paid"] or 0)
        balance = expected - paid
        money = lambda value: "{:,.2f}".format(value)
        safe = lambda value: escape(str(value if value is not None else ""))
        learner_name = safe(st["name"])
        class_label = safe(st["class_name"] or "Class not assigned")
        stream_label = safe(st["stream"] or "")
        admission = safe(st["admission_no"])
        latest = marks[:5]
        latest_rows = "".join(
            "<tr><td>" + safe(m["subject"]) + "</td><td>" + safe(m["exam"]) +
            "</td><td class='parent-mark'>" + safe(m["marks"]) +
            "</td><td>" + safe((str(m["term"] or "") + " " + str(m["year"] or "")).strip()) +
            "</td></tr>" for m in latest
        ) or "<tr><td colspan='4' class='parent-muted'>No academic results have been published yet.</td></tr>"
        academic_rows = "".join(
            "<tr><td>" + safe(m["subject"]) + "</td><td>" + safe(m["exam"]) +
            "</td><td class='parent-mark'>" + safe(m["marks"]) +
            "</td><td>" + safe(m["term"]) + "</td><td>" + safe(m["year"]) +
            "</td></tr>" for m in marks
        ) or "<tr><td colspan='5' class='parent-muted'>No academic results have been published yet.</td></tr>"

        child_options = "".join(
            "<option value='" + safe(item["id"]) + "'" +
            (" selected" if int(item["id"]) == student_id else "") + ">" +
            safe(item["name"]) + " · " + safe(item["admission_no"]) + "</option>"
            for item in linked_students
        )
        child_switcher = (
            "<form class='parent-child-form' method='get' action='/portal/parent'>"
            "<label for='parent-child'>Viewing learner</label>"
            "<select id='parent-child' name='student_id' onchange='this.form.submit()'>" +
            child_options + "</select></form>"
        ) if len(linked_students) > 1 else ""

        overview = (
            "<section class='parent-panel' id='parent-overview'>"
            "<div class='parent-section-heading'><div><span class='parent-eyebrow'>YOUR CHILD</span>"
            "<h2>" + learner_name + "</h2><p>" + class_label +
            (" · " + stream_label if stream_label else "") + " &nbsp;·&nbsp; Admission " + admission +
            "</p></div><span class='parent-avatar'>"
            + safe("".join(part[0] for part in str(st["name"] or "L").split()[:2]).upper()) +
            "</span></div>"
            "<div class='parent-summary-grid'>"
            "<article class='parent-summary'><span class='parent-summary-label'>Fee balance</span>"
            "<strong>KSh " + money(balance) + "</strong><small>Outstanding amount</small></article>"
            "<article class='parent-summary'><span class='parent-summary-label'>Amount paid</span>"
            "<strong>KSh " + money(paid) + "</strong><small>Recorded payments</small></article>"
            "<article class='parent-summary'><span class='parent-summary-label'>Published results</span>"
            "<strong>" + str(len(marks)) + "</strong><small>Available subject records</small></article>"
            "</div>"
            "<div class='parent-content-card'><div class='parent-card-heading'><div><h3>Recent academic results</h3>"
            "<p>Your child's latest published subject marks</p></div><button class='parent-text-button' type='button' onclick=\"parentShow('academics')\">View all results →</button></div>"
            "<div class='parent-table-wrap'><table><thead><tr><th>Subject</th><th>Assessment</th><th>Marks</th><th>Period</th></tr></thead><tbody>"
            + latest_rows + "</tbody></table></div></div></section>"
        )
        academics = (
            "<section class='parent-panel' id='parent-academics' hidden>"
            "<div class='parent-card-heading'><div><span class='parent-eyebrow'>LEARNING</span><h2>Academic performance</h2>"
            "<p>Published examination results for " + learner_name + ".</p></div></div>"
            "<div class='parent-content-card'><div class='parent-table-wrap'><table><thead><tr>"
            "<th>Subject</th><th>Assessment</th><th>Marks</th><th>Term</th><th>Year</th>"
            "</tr></thead><tbody>" + academic_rows + "</tbody></table></div></div></section>"
        )
        fees = (
            "<section class='parent-panel' id='parent-fees' hidden>"
            "<div class='parent-card-heading'><div><span class='parent-eyebrow'>SCHOOL FINANCE</span><h2>Fee summary</h2>"
            "<p>Current fee position for " + learner_name + ".</p></div></div>"
            "<div class='parent-fee-grid'>"
            "<article class='parent-fee-item'><span>Expected fees</span><strong>KSh " + money(expected) + "</strong></article>"
            "<article class='parent-fee-item'><span>Amount paid</span><strong>KSh " + money(paid) + "</strong></article>"
            "<article class='parent-fee-item parent-fee-balance'><span>Outstanding balance</span><strong>KSh " + money(balance) + "</strong></article>"
            "</div><p class='parent-note'>This summary reflects fee records currently maintained by the school. Contact the school office if you need a payment statement or clarification.</p></section>"
        )
        body = (
            "<div class='parent-dashboard'>"
            "<div class='parent-welcome'><div><span class='parent-eyebrow'>PARENT WORKSPACE</span>"
            "<h1>Welcome, " + safe(request.session.get("name") or "Parent") + "</h1>"
            "<p>Stay connected with your child's school progress.</p></div>" + child_switcher + "</div>"
            "<nav class='parent-nav' aria-label='Parent portal sections'>"
            "<button type='button' class='parent-nav-btn active' data-section='overview' onclick=\"parentShow('overview')\">Overview</button>"
            "<button type='button' class='parent-nav-btn' data-section='academics' onclick=\"parentShow('academics')\">Academics</button>"
            "<button type='button' class='parent-nav-btn' data-section='fees' onclick=\"parentShow('fees')\">Fees</button>"
            "<a class='parent-nav-btn' href='/app/timetable/my' style='text-decoration:none'>My Timetable</a>"
            "</nav>" + overview + academics + fees + "</div>"
            "<script>function parentShow(section){document.querySelectorAll('.parent-panel').forEach(function(p){p.hidden=p.id!=='parent-'+section;});document.querySelectorAll('.parent-nav-btn').forEach(function(b){b.classList.toggle('active',b.dataset.section===section);});window.scrollTo({top:0,behavior:'smooth'});}</script>"
        )
        page = portal_page(request, "Parent Portal", body)
        if isinstance(page, HTMLResponse):
            # Add a scoped visual system without changing teacher/student/admin pages.
            page_html = page.body.decode("utf-8").replace(
                "background:#0b3d91;color:white;padding:16px 20px",
                "background:#07552f;color:white;padding:16px 20px"
            ).replace(
                "</style>",
                """.parent-dashboard{max-width:1080px;margin:0 auto;color:#183b29}
                .parent-welcome{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin:8px 0 22px}
                .parent-welcome h1{margin:5px 0 4px;color:#123d27;font-size:clamp(25px,4vw,34px)}
                .parent-welcome p,.parent-section-heading p,.parent-card-heading p{margin:0;color:#64766c;font-size:13px}
                .parent-eyebrow{font-size:10px;letter-spacing:.12em;font-weight:900;color:#16834a}
                .parent-child-form{min-width:210px}.parent-child-form label{display:block;font-size:11px;font-weight:800;color:#52675a;margin-bottom:6px}
                .parent-child-form select{width:100%;padding:11px 34px 11px 12px;border:1px solid #d5e7db;border-radius:11px;background:#fff;color:#17452d;font-weight:700}
                .parent-nav{display:flex;gap:7px;overflow-x:auto;padding:5px;margin:0 0 18px;border-bottom:1px solid #dce9df}
                .parent-nav-btn{flex:0 0 auto;border:0;background:transparent;color:#607267;padding:11px 17px;border-radius:10px 10px 0 0;font-weight:800;cursor:pointer}
                .parent-nav-btn.active{background:#e7f5eb;color:#086338;box-shadow:inset 0 -3px #16834a}
                .parent-panel[hidden]{display:none!important}.parent-section-heading{display:flex;justify-content:space-between;align-items:center;gap:14px;margin:4px 0 17px}
                .parent-section-heading h2,.parent-card-heading h2{font-size:22px;color:#123d27;margin:4px 0}
                .parent-avatar{width:48px;height:48px;flex:0 0 48px;border-radius:15px;background:#e3f3e8;color:#176b3a;display:grid;place-items:center;font-weight:900;font-size:17px}
                .parent-summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:16px}
                .parent-summary,.parent-fee-item{background:#fff;border:1px solid #e0ebe3;border-radius:14px;padding:16px;min-width:0}
                .parent-summary-label,.parent-fee-item span{display:block;color:#63766a;font-size:12px;font-weight:700}
                .parent-summary strong,.parent-fee-item strong{display:block;color:#17452d;font-size:21px;margin:7px 0 3px;overflow-wrap:anywhere}
                .parent-summary small{color:#819087;font-size:11px}
                .parent-content-card{background:#fff;border:1px solid #e0ebe3;border-radius:15px;padding:17px}
                .parent-card-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}
                .parent-card-heading h3{margin:0 0 4px;color:#17452d;font-size:17px}.parent-card-heading p{font-size:12px}
                .parent-text-button{border:0;background:transparent;color:#08783f;font-weight:800;cursor:pointer;padding:8px;white-space:nowrap}
                .parent-table-wrap{width:100%;overflow-x:auto} .parent-table-wrap table{min-width:560px}
                .parent-table-wrap th{background:#f4faf6;color:#52675a;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
                .parent-table-wrap td{color:#344f3e}.parent-mark{font-weight:900;color:#176b3a!important}
                .parent-muted{color:#819087!important;text-align:center!important;padding:22px!important}
                .parent-fee-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
                .parent-fee-balance{background:#f0f8f2;border-color:#cfe5d5}.parent-note{font-size:12px;color:#718277;margin:14px 2px}
                .parent-empty{max-width:620px;margin:45px auto;text-align:center;background:#fff;border:1px solid #e0ebe3;border-radius:18px;padding:30px}
                .parent-empty-icon{font-size:30px;color:#16834a}.parent-empty h2{color:#123d27}.parent-empty p{color:#64766c}
                @media(max-width:680px){.parent-welcome{display:block}.parent-child-form{margin-top:15px}.parent-summary-grid,.parent-fee-grid{grid-template-columns:1fr 1fr}.parent-summary:last-child{grid-column:1/-1}.parent-summary,.parent-fee-item{padding:13px}.parent-summary strong,.parent-fee-item strong{font-size:18px}.parent-card-heading{align-items:flex-start}.parent-text-button{font-size:11px;padding:4px 0}.parent-section-heading h2,.parent-card-heading h2{font-size:19px}}
                </style>"""
            )
            page = HTMLResponse(page_html)
        return page
    finally:
        try:
            con.close()
        except Exception:
            pass

@app.get("/school/finance", response_class=HTMLResponse)
def school_finance(request: Request):
    school_id=sid(request); con=get_db(); cur=con.cursor()
    fee=cur.execute("SELECT COALESCE(SUM(amount),0) expected,COALESCE(SUM(paid),0) paid FROM fees WHERE school_id=?",(school_id,)).fetchone()
    exp=cur.execute("SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE school_id=?",(school_id,)).fetchone()
    pledge=cur.execute("SELECT COALESCE(SUM(amount),0) total,COALESCE(SUM(paid),0) paid FROM pledges WHERE school_id=?",(school_id,)).fetchone()
    expenses=cur.execute("SELECT * FROM expenses WHERE school_id=? ORDER BY id DESC LIMIT 100",(school_id,)).fetchall()
    pledges=cur.execute("SELECT * FROM pledges WHERE school_id=? ORDER BY id DESC LIMIT 100",(school_id,)).fetchall()
    vouchers=cur.execute("SELECT * FROM payment_vouchers WHERE school_id=? ORDER BY id DESC LIMIT 100",(school_id,)).fetchall()
    lpos=cur.execute("SELECT * FROM lpos WHERE school_id=? ORDER BY id DESC LIMIT 100",(school_id,)).fetchall()
    cashbook=cur.execute("SELECT * FROM cashbook WHERE school_id=? ORDER BY id DESC LIMIT 100",(school_id,)).fetchall()
    payments=cur.execute("SELECT fp.*,st.name student_name FROM fee_payments fp LEFT JOIN students st ON st.id=fp.student_id WHERE fp.school_id=? ORDER BY fp.id DESC LIMIT 100",(school_id,)).fetchall()
    student_opts=''.join(f"<option value='{st['id']}'>{st['name']} ({st['admission_no']})</option>" for st in cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(school_id,)).fetchall())
    con.close()
    er=''.join(f"<tr><td>{e['date']}</td><td>{e['category']}</td><td>{e['description']}</td><td>{e['paid_to']}</td><td>{e['amount']}</td><td>{e['voucher_no']}</td></tr>" for e in expenses) or '<tr><td colspan=6>No expenses.</td></tr>'
    pr=''.join(f"<tr><td>{p['parent_name']}</td><td>{p['purpose']}</td><td>{p['amount']}</td><td>{p['paid']}</td><td>{float(p['amount'] or 0)-float(p['paid'] or 0)}</td><td>{p['status']}</td></tr>" for p in pledges) or '<tr><td colspan=6>No pledges.</td></tr>'
    vr=''.join(f"<tr><td>{v['date']}</td><td>{v['voucher_no']}</td><td>{v['payee']}</td><td>{v['description']}</td><td>{v['amount']}</td><td>{v['status']}</td></tr>" for v in vouchers) or '<tr><td colspan=6>No vouchers.</td></tr>'
    lr=''.join(f"<tr><td>{x['date']}</td><td>{x['lpo_no']}</td><td>{x['supplier']}</td><td>{x['description']}</td><td>{x['amount']}</td><td>{x['status']}</td></tr>" for x in lpos) or '<tr><td colspan=6>No LPOs.</td></tr>'
    cr=''.join(f"<tr><td>{x['date']}</td><td>{x['reference']}</td><td>{x['description']}</td><td>{x['debit']}</td><td>{x['credit']}</td><td>{x['account']}</td></tr>" for x in cashbook) or '<tr><td colspan=6>No cashbook entries.</td></tr>'
    fpr=''.join(f"<tr><td>{x['date']}</td><td>{x['student_name'] or ''}</td><td>{x['amount']}</td><td>{x['reference']}</td><td>{x['method']}</td><td>{x['received_by']}</td></tr>" for x in payments) or '<tr><td colspan=6>No fee payments.</td></tr>'
    balance=float(fee['expected'] or 0)-float(fee['paid'] or 0); net=float(fee['paid'] or 0)-float(exp['total'] or 0)
    body=f"""<div class='card'><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'><div><b>Fees Expected</b><h2>{fee['expected']}</h2></div><div><b>Fees Collected</b><h2>{fee['paid']}</h2></div><div><b>Outstanding</b><h2>{balance}</h2></div><div><b>Net Cash Movement</b><h2>{net}</h2></div></div></div><div class='card'><h3>➕ Expense / Payment Voucher</h3><form method='post' action='/school/modules/finance/expense' style='display:grid;grid-template-columns:repeat(4,1fr);gap:8px'><input name='category' required placeholder='Category' class='input-field'><input name='description' required placeholder='Description' class='input-field'><input name='paid_to' placeholder='Payee' class='input-field'><input name='amount' required type='number' step='0.01' placeholder='Amount' class='input-field'><input name='voucher_no' placeholder='Voucher No.' class='input-field'><input name='date' required type='date' class='input-field'><button class='btn'>Save Expense</button></form></div><div class='card'><h3>📒 Expenses</h3><table><tr><th>Date</th><th>Category</th><th>Description</th><th>Payee</th><th>Amount</th><th>Voucher</th></tr>{er}</table></div><div class='card'><h3>🤝 Pledges</h3><form method='post' action='/school/modules/finance/pledge' style='display:grid;grid-template-columns:repeat(4,1fr);gap:8px'><input name='parent_name' required placeholder='Parent/Guardian' class='input-field'><input name='phone' placeholder='Phone' class='input-field'><input name='amount' required type='number' step='0.01' placeholder='Amount' class='input-field'><input name='purpose' placeholder='Purpose' class='input-field'><input name='due_date' type='date' class='input-field'><button class='btn'>Save Pledge</button></form><table style='margin-top:15px'><tr><th>Parent</th><th>Purpose</th><th>Pledged</th><th>Paid</th><th>Balance</th><th>Status</th></tr>{pr}</table></div><div class='card'><h3>🧾 Payment Vouchers</h3><form method='post' action='/school/modules/finance/voucher' style='display:grid;grid-template-columns:repeat(4,1fr);gap:8px'><input name='voucher_no' required placeholder='Voucher No.' class='input-field'><input name='payee' required placeholder='Payee' class='input-field'><input name='description' required placeholder='Description' class='input-field'><input name='amount' required type='number' step='0.01' placeholder='Amount' class='input-field'><input name='date' required type='date' class='input-field'><select name='status' class='input-field'><option>Draft</option><option>Approved</option><option>Paid</option></select><button class='btn'>Create Voucher</button></form><table><tr><th>Date</th><th>Voucher</th><th>Payee</th><th>Description</th><th>Amount</th><th>Status</th></tr>{vr}</table></div><div class='card'><h3>🛒 Local Purchase Orders (LPO)</h3><form method='post' action='/school/modules/finance/lpo' style='display:grid;grid-template-columns:repeat(4,1fr);gap:8px'><input name='lpo_no' required placeholder='LPO No.' class='input-field'><input name='supplier' required placeholder='Supplier' class='input-field'><input name='description' required placeholder='Description' class='input-field'><input name='amount' required type='number' step='0.01' placeholder='Amount' class='input-field'><input name='date' required type='date' class='input-field'><select name='status' class='input-field'><option>Open</option><option>Approved</option><option>Closed</option></select><button class='btn'>Create LPO</button></form><table><tr><th>Date</th><th>LPO</th><th>Supplier</th><th>Description</th><th>Amount</th><th>Status</th></tr>{lr}</table></div><div class='card'><h3>📚 Cashbook</h3><form method='post' action='/school/modules/finance/cashbook' style='display:grid;grid-template-columns:repeat(4,1fr);gap:8px'><input name='date' required type='date' class='input-field'><input name='reference' required placeholder='Reference' class='input-field'><input name='description' required placeholder='Description' class='input-field'><input name='debit' type='number' step='0.01' value='0' placeholder='Debit' class='input-field'><input name='credit' type='number' step='0.01' value='0' placeholder='Credit' class='input-field'><input name='account' required placeholder='Account' class='input-field'><button class='btn'>Post Cashbook Entry</button></form><table><tr><th>Date</th><th>Reference</th><th>Description</th><th>Debit</th><th>Credit</th><th>Account</th></tr>{cr}</table></div><div class='card'><h3>💳 Fee Payments</h3><form method='post' action='/school/modules/finance/fee-payment' style='display:grid;grid-template-columns:repeat(4,1fr);gap:8px'><select name='student_id' required class='input-field'><option value=''>Select Student</option>{''.join(f"<option value='{st['id']}'>{st['name']} ({st['admission_no']})</option>" for st in cur.execute('SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name',(school_id,)).fetchall())}</select><input name='amount' required type='number' step='0.01' placeholder='Amount' class='input-field'><input name='reference' required placeholder='Receipt/Reference' class='input-field'><select name='method' class='input-field'><option>Cash</option><option>MPesa</option><option>Bank</option><option>Cheque</option></select><input name='date' required type='date' class='input-field'><button class='btn'>Record Payment</button></form><table><tr><th>Date</th><th>Student</th><th>Amount</th><th>Reference</th><th>Method</th><th>Received By</th></tr>{fpr}</table></div><div class='card'><h3>📊 Accounting Summary</h3><p>Fee collection and expense data are stored per school and can be extended into cashbooks/trial balances. Current collected fees: <b>{fee['paid']}</b>; expenses: <b>{exp['total']}</b>; pledge balance: <b>{float(pledge['total'] or 0)-float(pledge['paid'] or 0)}</b>.</p></div>"""
    return module_page(request,'💰 Fees & Finance — Complete Workspace','fees',body)

@app.post("/school/modules/finance/expense")
def finance_expense(request:Request,category:str=Form(...),description:str=Form(...),paid_to:str=Form(''),amount:float=Form(...),voucher_no:str=Form(''),date:str=Form(...)):
    con=get_db(); con.execute("INSERT INTO expenses(school_id,category,description,amount,paid_to,voucher_no,date) VALUES(?,?,?,?,?,?,?)",(sid(request),category,description,amount,paid_to,voucher_no,date)); con.commit(); con.close(); return RedirectResponse('/school/finance',303)
@app.post("/school/modules/finance/pledge")
def finance_pledge(request:Request,parent_name:str=Form(...),phone:str=Form(''),amount:float=Form(...),purpose:str=Form(''),due_date:str=Form('')):
    con=get_db(); con.execute("INSERT INTO pledges(school_id,parent_name,phone,amount,purpose,due_date) VALUES(?,?,?,?,?,?)",(sid(request),parent_name,phone,amount,purpose,due_date)); con.commit(); con.close(); return RedirectResponse('/school/finance',303)

@app.post("/school/modules/finance/voucher")
def finance_voucher(request:Request,voucher_no:str=Form(...),payee:str=Form(...),description:str=Form(...),amount:float=Form(...),date:str=Form(...),status:str=Form(...)):
    con=get_db(); con.execute("INSERT INTO payment_vouchers(school_id,voucher_no,payee,description,amount,date,status) VALUES(?,?,?,?,?,?,?)",(sid(request),voucher_no.strip(),payee.strip(),description.strip(),amount,date,status)); con.commit(); con.close(); return RedirectResponse('/school/finance',303)

@app.post("/school/modules/finance/lpo")
def finance_lpo(request:Request,lpo_no:str=Form(...),supplier:str=Form(...),description:str=Form(...),amount:float=Form(...),date:str=Form(...),status:str=Form(...)):
    con=get_db(); con.execute("INSERT INTO lpos(school_id,lpo_no,supplier,description,amount,date,status) VALUES(?,?,?,?,?,?,?)",(sid(request),lpo_no.strip(),supplier.strip(),description.strip(),amount,date,status)); con.commit(); con.close(); return RedirectResponse('/school/finance',303)

@app.post("/school/modules/finance/cashbook")
def finance_cashbook(request:Request,date:str=Form(...),reference:str=Form(...),description:str=Form(...),debit:float=Form(0),credit:float=Form(0),account:str=Form(...)):
    if debit < 0 or credit < 0 or (debit == 0 and credit == 0) or (debit > 0 and credit > 0): return HTMLResponse("Invalid cashbook entry. Enter either debit or credit.",400)
    con=get_db(); con.execute("INSERT INTO cashbook(school_id,date,reference,description,debit,credit,account) VALUES(?,?,?,?,?,?,?)",(sid(request),date,reference.strip(),description.strip(),debit,credit,account.strip())); con.commit(); con.close(); return RedirectResponse('/school/finance',303)

@app.post("/school/modules/finance/fee-payment")
def finance_fee_payment(request:Request,student_id:int=Form(...),amount:float=Form(...),reference:str=Form(...),method:str=Form(...),date:str=Form(...)):
    school_id=sid(request)
    if amount <= 0: return HTMLResponse("Payment amount must be positive.",400)
    con=get_db(); cur=con.cursor(); st=cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,school_id)).fetchone()
    if not st: con.close(); return HTMLResponse("Invalid student for this school.",403)
    cur.execute("INSERT INTO fee_payments(school_id,student_id,amount,reference,method,date,received_by) VALUES(?,?,?,?,?,?,?)",(school_id,student_id,amount,reference.strip(),method,date,request.session.get('email','')))
    cur.execute("UPDATE fees SET paid=COALESCE(paid,0)+? WHERE student_id=? AND school_id=? AND COALESCE(paid,0)<amount ORDER BY id LIMIT 1",(amount,student_id,school_id))
    con.commit(); con.close(); return RedirectResponse('/school/finance',303)

# === ADDITIVE WORKING MODULE WINDOWS ===
def _role_permission(request, permission):
    """School Admin and Registrar share school-level permissions; Super Admin stays platform-level."""
    role=request.session.get("role")
    if role in ("school_admin","registrar","super_admin"):
        return True
    school_id=request.session.get("school_id")
    if not school_id or not role:
        return False
    con=get_db(); cur=con.cursor()
    row=cur.execute("SELECT enabled FROM roles_permissions WHERE school_id=? AND role=? AND permission=? ORDER BY id DESC LIMIT 1",(school_id,role,permission)).fetchone()
    con.close()
    return True if row is None else bool(row["enabled"])

def _teacher_allocation_allowed(request, school_id, class_id, subject_id):
    if request.session.get("role") != "teacher":
        return True
    teacher_id=request.session.get("teacher_id")
    if not teacher_id:
        return False
    con=get_db(); cur=con.cursor()
    row=cur.execute("SELECT id FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND class_id=? AND subject_id=? LIMIT 1",(school_id,teacher_id,class_id,subject_id)).fetchone()
    con.close()
    return bool(row)

def module_page(request, title, active, body, global_mode=False):
    """Retired /school module wrapper. All current modules live in the /app shell."""
    return RedirectResponse("/app", status_code=303)

def sid(request):
    s=get_school_obj(request); return s["id"] if s else 0

@app.get("/school/fees", response_class=HTMLResponse)
def school_fees(request: Request):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT f.*,s.name student_name FROM fees f LEFT JOIN students s ON f.student_id=s.id WHERE f.school_id=? ORDER BY f.id DESC",(sid(request),)); rows=cur.fetchall(); cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid(request),)); sts=cur.fetchall(); con.close()
    tr="".join([f"<tr><td>{r['student_name'] or '—'}</td><td>{r['amount']}</td><td>{r['paid']}</td><td>{r['description'] or ''}</td><td>{r['due_date'] or ''}</td><td>{r['status']}</td></tr>" for r in rows]) or "<tr><td colspan='6'>No fee records yet.</td></tr>"
    opts=''.join([f"<option value='{x['id']}'>{x['name']} ({x['admission_no'] or ''})</option>" for x in sts])
    body=f"<div class='card'><form method='post' action='/school/modules/fees/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:8px'><select name='student_id' required class='input-field'><option value=''>Student</option>{opts}</select><input name='amount' required type='number' step='0.01' placeholder='Amount' class='input-field'><input name='paid' value='0' type='number' step='0.01' placeholder='Paid' class='input-field'><input name='description' placeholder='Description' class='input-field'><input name='due_date' type='date' class='input-field'><select name='status' class='input-field'><option>Pending</option><option>Paid</option><option>Partial</option></select><button class='btn'>Save Fee Record</button></form><table style='margin-top:16px'><tr><th>Student</th><th>Amount</th><th>Paid</th><th>Description</th><th>Due</th><th>Status</th></tr>{tr}</table></div>"
    return module_page(request,'💰 Fees & Finance','fees',body)
@app.post("/school/modules/fees/add")
def add_fee(request:Request,student_id:int=Form(...),amount:float=Form(...),paid:float=Form(0),description:str=Form(''),due_date:str=Form(''),status:str=Form('Pending')):
    con=get_db(); con.execute("INSERT INTO fees(school_id,student_id,amount,paid,description,due_date,status) VALUES(?,?,?,?,?,?,?)",(sid(request),student_id,amount,paid,description,due_date,status)); con.commit(); con.close(); return RedirectResponse('/school/fees',303)

@app.get("/school/communication", response_class=HTMLResponse)
def school_communication(request:Request):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM announcements WHERE school_id=? ORDER BY id DESC",(sid(request),))
    rows=cur.fetchall(); con.close()
    total=len(rows)
    audience_counts={}
    for row in rows:
        key=str(row["audience"] or "All")
        audience_counts[key]=audience_counts.get(key,0)+1
    audience_summary=" · ".join(f"{escape(k)}: {v}" for k,v in sorted(audience_counts.items())) or "No audience groups yet"
    cards=[]
    details=[]
    for r in rows:
        rid=int(r["id"])
        title=escape(str(r["title"] or "Untitled announcement"))
        message=escape(str(r["message"] or ""))
        audience=escape(str(r["audience"] or "All"))
        created=escape(str(r["created_at"] or ""))
        excerpt=message if len(message)<=150 else message[:147]+"…"
        cards.append(
            f"<tr><td><div class='ann-date'>{created}</div></td>"
            f"<td><b class='ann-title'>{title}</b><small class='ann-sub'>School announcement</small></td>"
            f"<td><span class='ann-audience'>{audience}</span></td>"
            f"<td class='ann-message'>{excerpt}</td>"
            f"<td><a class='ann-view' href='#ann-view-{rid}'>View details</a></td></tr>"
        )
        details.append(
            f"<div id='ann-view-{rid}' class='ann-pop ann-detail'>"
            f"<div class='ann-pop-head'><div><span class='ann-eyebrow'>ANNOUNCEMENT DETAILS</span><h2>{title}</h2></div>"
            f"<a class='ann-close' href='#' aria-label='Close'>×</a></div>"
            f"<div class='ann-detail-meta'><span>{audience}</span><span>{created}</span></div>"
            f"<div class='ann-full-message'>{message}</div>"
            f"<div class='ann-pop-actions'><a class='ann-secondary' href='#'>Close</a></div></div>"
        )
    tr="".join(cards) or "<tr><td colspan='5' class='ann-empty'><b>No announcements yet</b><small>Create your first announcement to keep the school community informed.</small></td></tr>"
    body=f"""
    <style>
    .ann-page{{display:grid;gap:16px;color:#26372d}}
    .ann-kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}
    .ann-kpi{{padding:17px;border:1px solid #dce9de;border-radius:15px;background:linear-gradient(145deg,#fff,#f1f8f2);box-shadow:0 5px 18px #214b2e0a}}
    .ann-kpi small{{display:block;color:#718078;font-size:12px;font-weight:700}}
    .ann-kpi strong{{display:block;margin-top:5px;color:#185633;font-size:27px}}
    .ann-kpi em{{display:block;margin-top:3px;color:#849188;font-size:11px;font-style:normal}}
    .ann-hero{{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:22px;border:1px solid #cfe2d2;border-radius:18px;background:linear-gradient(125deg,#e4f2e6,#f7fbf7 58%,#d8eadb)}}
    .ann-eyebrow{{color:#5e8b69;font-size:10px;font-weight:900;letter-spacing:1.25px}}
    .ann-hero h2{{margin:5px 0;color:#1d5734;font-size:21px}}
    .ann-hero p{{margin:0;max-width:620px;color:#6c7d70;font-size:13px;line-height:1.55}}
    .ann-hero-icon{{display:grid;place-items:center;width:56px;height:56px;flex:0 0 56px;border-radius:17px;background:linear-gradient(145deg,#d4e9d8,#bddcc4);color:#23633c;font-size:29px}}
    .ann-primary,.ann-view,.ann-secondary{{border:0;border-radius:10px;padding:10px 14px;font-size:12px;font-weight:800;cursor:pointer}}
    .ann-primary{{background:linear-gradient(135deg,#267849,#145b34);color:#fff;box-shadow:0 4px 12px #176b3a20}}
    .ann-primary:hover,.ann-view:hover{{filter:brightness(1.07);transform:translateY(-1px)}}
    .ann-toolbar{{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:13px}}
    .ann-toolbar h2{{margin:0;color:#245638;font-size:18px}}
    .ann-toolbar p{{margin:4px 0 0;color:#7a887e;font-size:12px}}
    .ann-search{{width:min(310px,100%);min-height:40px;padding:9px 12px;border:1px solid #dce6df;border-radius:10px;background:#fff;color:#26372d}}
    .ann-table-wrap{{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #e4ede5;border-radius:13px}}
    .ann-table{{width:100%;min-width:760px;border-collapse:separate;border-spacing:0}}
    .ann-table th{{padding:12px;text-align:left;background:#edf5ef;color:#637568;font-size:10px;letter-spacing:.7px;text-transform:uppercase;white-space:nowrap}}
    .ann-table td{{padding:12px;border-bottom:1px solid #edf1ee;vertical-align:middle;font-size:12px;color:#44564a}}
    .ann-table tr:last-child td{{border-bottom:0}}
    .ann-table tbody tr:hover td{{background:#f8fbf8}}
    .ann-date{{color:#728176;font-size:11px;white-space:nowrap}}
    .ann-title{{display:block;color:#28583a;font-size:12px}}
    .ann-sub{{display:block;margin-top:4px;color:#929d94;font-size:10px}}
    .ann-audience{{display:inline-flex;padding:5px 9px;border-radius:20px;background:#edf5ef;color:#28613d;font-size:10px;font-weight:800;white-space:nowrap}}
    .ann-message{{max-width:330px;line-height:1.5;color:#6e7d72!important}}
    .ann-view{{background:#f0f7f1;border:1px solid #d7e7da;color:#28613d;white-space:nowrap}}
    .ann-empty{{padding:30px!important;text-align:center!important;color:#42634c!important}}
    .ann-empty small{{display:block;margin-top:6px;color:#839087}}
    
    
    .ann-pop{{display:none;position:fixed;z-index:99999;inset:0;margin:auto;width:min(680px,calc(100vw - 28px));max-height:min(88vh,820px);overflow:auto;padding:23px;border:1px solid #cfe1d1;border-radius:20px;background:linear-gradient(145deg,#edf6ee 0%,#fff 52%,#f4faf5 100%);color:#26372d;box-shadow:0 0 0 100vmax #14281dcc,0 24px 80px #142f1e45}}.ann-pop:target{{display:block}}
    .ann-toggle:checked+.ann-overlay{{display:block}}
    .ann-toggle:checked~.ann-pop{{display:block}}
    .ann-pop-head{{position:relative;display:flex;justify-content:space-between;gap:14px;padding:4px 48px 15px 0;border-bottom:1px solid #d8e7da;margin-bottom:17px}}
    .ann-pop-head h2{{margin:5px 0 0;color:#205a38;font-size:20px}}
    .ann-close{{position:absolute;right:0;top:0;width:38px;height:38px;border:1px solid #c8ddcb;border-radius:50%;background:#fff;color:#245b39;font-size:25px;line-height:1;cursor:pointer}}
    .ann-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}
    .ann-form label{{display:grid;gap:6px;color:#46604c;font-size:12px;font-weight:800}}
    .ann-form input,.ann-form select,.ann-form textarea{{width:100%;min-height:42px;padding:10px 11px;border:1px solid #cbdccd;border-radius:10px;background:#fff;color:#26372d;font:inherit}}
    .ann-form textarea{{min-height:150px;resize:vertical}}
    .ann-wide{{grid-column:1/-1}}
    .ann-form input:focus,.ann-form select:focus,.ann-form textarea:focus{{outline:2px solid #8fbd9a;outline-offset:1px;border-color:#57966b}}
    .ann-pop-actions{{display:flex;justify-content:flex-end;gap:9px;flex-wrap:wrap;margin-top:17px;padding-top:14px;border-top:1px solid #dceade}}
    .ann-secondary{{background:#edf5ef;border:1px solid #d7e8da;color:#245638}}
    .ann-detail-meta{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}}
    .ann-detail-meta span{{padding:6px 10px;border-radius:20px;background:#eaf4eb;color:#28613d;font-size:11px;font-weight:800}}
    .ann-full-message{{white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;border:1px solid #e0ebe2;border-radius:12px;background:#fff;color:#43564a;font-size:13px;line-height:1.7}}
    @media(max-width:760px){{.ann-kpis{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ann-hero{{align-items:flex-start;flex-wrap:wrap}}}}
    @media(max-width:560px){{.ann-hero{{padding:16px}}.ann-form{{grid-template-columns:1fr}}.ann-wide{{grid-column:auto}}.ann-pop{{padding:16px}}.ann-kpi{{padding:13px}}.ann-kpi strong{{font-size:23px}}}}
    @media(prefers-reduced-motion:reduce){{.ann-primary,.ann-view{{transition:none}}}}
    @media print{{.ann-primary,.ann-view,.ann-search,.ann-pop{{display:none!important}}.ann-table{{min-width:0}}}}
    </style>
    <div class='ann-page'>
      <div class='ann-kpis'>
        <div class='ann-kpi'><small>Total announcements</small><strong>{total}</strong><em>All recorded notices</em></div>
        <div class='ann-kpi'><small>Audience groups</small><strong>{len(audience_counts)}</strong><em>Groups reached</em></div>
        <div class='ann-kpi'><small>Latest announcement</small><strong style='font-size:17px'>{escape(str(rows[0]["created_at"] or "—"))[:10] if rows else "—"}</strong><em>Most recent record</em></div>
        <div class='ann-kpi'><small>All-audience notices</small><strong>{audience_counts.get("All",0)}</strong><em>Shared with the whole community</em></div>
      </div>
      <section class='ann-hero'>
        <div><span class='ann-eyebrow'>SCHOOL COMMUNITY • COMMUNICATIONS</span><h2>Keep everyone informed</h2><p>Create and share important school updates, reminders and notices with the right audience. Review previous announcements in the register below.</p></div>
        <div style='display:flex;align-items:center;gap:12px;flex-wrap:wrap'><span class='ann-hero-icon'>✉</span><a class='ann-primary' href='#ann-create-pop'>＋ Create Announcement</a></div>
      </section>
      <section class='card' style='padding:18px;border:1px solid #dce9de;border-radius:16px'>
        <div class='ann-toolbar'><div><h2>Announcement register</h2><p>{total} records · {audience_summary}</p></div><input id='ann-search' class='ann-search' type='search' placeholder='Search title, audience or message…' aria-label='Search announcements'></div>
        <div class='ann-table-wrap'><table class='ann-table'><thead><tr><th>Date</th><th>Announcement</th><th>Audience</th><th>Message preview</th><th>Action</th></tr></thead><tbody id='ann-table-body'>{tr}</tbody></table></div>
      </section>
    </div>
    {''.join(details)}\n    <div id='ann-create-pop' class='ann-pop'>
      <div class='ann-pop-head'><div><span class='ann-eyebrow'>NEW SCHOOL NOTICE</span><h2>Create Announcement</h2><p style='margin:5px 0 0;color:#718078;font-size:12px'>Compose your message and select who should receive it.</p></div><a class='ann-close' href='#' aria-label='Close popup' title='Close'>×</a></div>
      <form method='post' action='/school/modules/announcements/add' class='ann-form'>
        <label class='ann-wide'>Announcement title *<input name='title' required maxlength='180' placeholder='Enter a clear announcement title'></label>
        <label>Audience<select name='audience' required><option value='All'>All</option><option value='Students'>Students</option><option value='Parents'>Parents</option><option value='Staff'>Staff</option></select></label>
        <label>Publication date<input type='text' value='{datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%d %b %Y")}' readonly></label>
        <label class='ann-wide'>Message *<textarea name='message' required maxlength='10000' placeholder='Write the announcement details…'></textarea></label>
        <div class='ann-pop-actions ann-wide'><button type='submit' class='ann-primary'>Publish Announcement</button><a class='ann-secondary' href='#'>Cancel</a></div>
      </form>
    </div>
    <script>
    (function(){{
      var search=document.getElementById('ann-search');
      if(search)search.addEventListener('input',function(){{
        var q=this.value.toLowerCase();
        document.querySelectorAll('#ann-table-body tr').forEach(function(row){{row.style.display=row.innerText.toLowerCase().includes(q)?'':'none';}});
      }});
    }})();
    </script>
    """
    return module_page(request,'📢 Announcements','communication',body)
@app.post("/school/modules/announcements/add")
def add_announcement(request:Request,title:str=Form(...),message:str=Form(...),audience:str=Form(...)):
    ts=datetime.now(ZoneInfo('Africa/Nairobi')).strftime('%Y-%m-%d %H:%M:%S'); con=get_db(); con.execute("INSERT INTO announcements(school_id,title,message,audience,created_at) VALUES(?,?,?,?,?)",(sid(request),title,message,audience,ts)); con.commit(); con.close(); return RedirectResponse('/school/communication',303)

@app.get("/school/sms", response_class=HTMLResponse)
def school_sms(request:Request):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM sms_logs WHERE school_id=? ORDER BY id DESC",(sid(request),)); rows=cur.fetchall(); con.close()
    tr=''.join([f"<tr><td>{r['created_at']}</td><td>{r['recipient']}</td><td>{r['message']}</td><td>{r['status']}</td></tr>" for r in rows]) or "<tr><td colspan='4'>No SMS records. The window records outgoing messages; live delivery can be connected in Integrations.</td></tr>"
    body=f"<div class='card'><form method='post' action='/school/modules/sms/send'><input name='recipient' required placeholder='Phone number(s)' class='input-field'><textarea name='message' required placeholder='Message' class='input-field'></textarea><button class='btn'>Record SMS</button></form><table style='margin-top:16px'><tr><th>Date</th><th>Recipient</th><th>Message</th><th>Status</th></tr>{tr}</table></div>"
    return module_page(request,'💬 Bulk SMS Parents','sms',body)
@app.post("/school/modules/sms/send")
def send_sms_record(request:Request,recipient:str=Form(...),message:str=Form(...)):
    ts=datetime.now(ZoneInfo('Africa/Nairobi')).strftime('%Y-%m-%d %H:%M:%S'); con=get_db(); con.execute("INSERT INTO sms_logs(school_id,recipient,message,status,created_at) VALUES(?,?,?,?,?)",(sid(request),recipient,message,'Queued',ts)); con.commit(); con.close(); return RedirectResponse('/school/sms',303)

@app.get("/school/my-profile", response_class=HTMLResponse)
def school_profile(request:Request):
    con=get_db(); u=con.execute("SELECT * FROM users WHERE email=?",(request.session.get('email',''),)).fetchone(); con.close(); body=f"<div class='card'><h3>👤 My Profile</h3><p><b>Name:</b> {u['full_name'] if u else ''}</p><p><b>Email:</b> {u['email'] if u else ''}</p><p><b>Role:</b> {u['role'] if u else ''}</p></div>"; return module_page(request,'👤 My Profile','my-profile',body)
@app.get("/school/user-manual", response_class=HTMLResponse)
def school_manual(request:Request):
    body="<div class='card'><h3>❓ Mabale_ICT User Manual</h3><ol><li>Admit students in Students Manager.</li><li>Add staff in Staff Manager.</li><li>Configure terms, subjects, classes and exams.</li><li>Set marks before recording marks.</li><li>Record marks using auto-save.</li><li>Use analysis for subject, student and class results.</li><li>Use finance and communication modules.</li><li>Use System Settings for users, permissions, backups, audit and integrations.</li></ol></div>"; return module_page(request,'❓ User Manual','user-manual',body)

@app.get("/school/analysis", response_class=HTMLResponse)
def school_analysis(request:Request):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT sub.name subject,AVG(CAST(m.marks AS REAL)) avg_mark,COUNT(m.id) entries FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.school_id=? GROUP BY sub.id,sub.name ORDER BY sub.name",(sid(request),)); subjects=cur.fetchall(); cur.execute("SELECT s.name student,AVG(CAST(m.marks AS REAL)) avg_mark,COUNT(m.id) entries FROM marks m JOIN students s ON m.student_id=s.id WHERE m.school_id=? GROUP BY s.id,s.name ORDER BY avg_mark DESC",(sid(request),)); students=cur.fetchall(); cur.execute("SELECT c.name class_name,c.stream,AVG(CAST(m.marks AS REAL)) avg_mark,COUNT(m.id) entries FROM marks m JOIN classes c ON m.class_id=c.id WHERE m.school_id=? GROUP BY c.id,c.name,c.stream ORDER BY c.name",(sid(request),)); classes=cur.fetchall(); con.close()
    sr=''.join([f"<tr><td>{x['subject']}</td><td>{round(x['avg_mark'] or 0,2)}</td><td>{x['entries']}</td></tr>" for x in subjects]) or '<tr><td colspan=3>No marks recorded.</td></tr>'; st=''.join([f"<tr><td>{x['student']}</td><td>{round(x['avg_mark'] or 0,2)}</td><td>{x['entries']}</td></tr>" for x in students[:100]]) or '<tr><td colspan=3>No student analysis yet.</td></tr>'; cr=''.join([f"<tr><td>{x['class_name']} {x['stream'] or ''}</td><td>{round(x['avg_mark'] or 0,2)}</td><td>{x['entries']}</td></tr>" for x in classes]) or '<tr><td colspan=3>No class analysis yet.</td></tr>'
    body=f"<div class='card'><h3>📊 Subject Analysis</h3><table><tr><th>Subject</th><th>Average</th><th>Entries</th></tr>{sr}</table></div><div class='card'><h3>🎓 Student Analysis</h3><table><tr><th>Student</th><th>Average</th><th>Entries</th></tr>{st}</table></div><div class='card'><h3>🏫 Class Analysis</h3><table><tr><th>Class</th><th>Average</th><th>Entries</th></tr>{cr}</table></div>"; return module_page(request,'📊 Exam Analysis','analysis',body)

@app.get("/school/marksheets", response_class=HTMLResponse)
def school_marksheets(request:Request):
    con=get_db(); cur=con.cursor();
    cur.execute("SELECT s.id student_id,s.name student,s.admission_no,COUNT(m.id) entries,ROUND(AVG(CAST(m.marks AS REAL)),2) average FROM marks m JOIN students s ON m.student_id=s.id WHERE m.school_id=? GROUP BY s.id,s.name,s.admission_no ORDER BY s.name",(sid(request),)); rows=cur.fetchall(); con.close()
    tr=''.join([f"<tr><td>{r['student']}</td><td>{r['admission_no'] or ''}</td><td>{r['entries']}</td><td>{r['average'] or 0}</td><td><a class='btn' href='/school/report-cards?student_id={r['student_id']}'>Report Card</a> <a class='btn' href='/school/student-analysis/{r['student_id']}'>Analysis</a></td></tr>" for r in rows]) or '<tr><td colspan=5>No student marks available.</td></tr>'
    body=f"<div class='card'><h3>📄 Marks Status & Report Cards</h3><p>Students with recorded marks are listed below. Open a student to view a full report card or detailed analysis.</p><table><tr><th>Student</th><th>ADM</th><th>Entries</th><th>Average</th><th>Actions</th></tr>{tr}</table></div>"
    return module_page(request,'📄 Marks Status','marksheets',body)
@app.get("/school/edit-marks", response_class=HTMLResponse)
def school_edit_marks(request:Request): return school_marksheets(request)
@app.get("/school/marks-status", response_class=HTMLResponse)
def school_marks_status(request:Request): return school_marksheets(request)

@app.get("/school/student-analysis/{student_id}", response_class=HTMLResponse)
def school_student_analysis(student_id:int, request:Request):
    con=get_db(); cur=con.cursor();
    cur.execute("SELECT * FROM students WHERE id=? AND school_id=?",(student_id,sid(request))); st=cur.fetchone()
    if not st: con.close(); return RedirectResponse('/school/marksheets',303)
    cur.execute("SELECT sub.name subject,ROUND(AVG(CAST(m.marks AS REAL)),2) average,COUNT(m.id) entries FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.student_id=? AND m.school_id=? GROUP BY sub.id,sub.name ORDER BY sub.name",(student_id,sid(request))); rows=cur.fetchall(); con.close()
    tr=''.join([f"<tr><td>{r['subject']}</td><td>{r['average'] or 0}</td><td>{r['entries']}</td></tr>" for r in rows]) or '<tr><td colspan=3>No subject marks.</td></tr>'
    body=f"<div class='card'><h3>🎓 Student Analysis — {st['name']}</h3><p>Admission: {st['admission_no'] or ''}</p><table><tr><th>Subject</th><th>Average</th><th>Entries</th></tr>{tr}</table><div style='margin-top:16px'><a class='btn' href='/school/report-cards?student_id={student_id}'>Open Report Card</a></div></div>"
    return module_page(request,'🎓 Student Analysis','analysis',body)

@app.get("/school/report-cards", response_class=HTMLResponse)
def school_report_cards(request:Request, student_id:int=0, exam_id:int=0):
    con=get_db(); cur=con.cursor();
    students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid(request),)).fetchall()
    exams=cur.execute("SELECT id,name,term,year FROM exams WHERE school_id=? ORDER BY year DESC,id DESC",(sid(request),)).fetchall()
    if not student_id and students: student_id=students[0]['id']
    if not exam_id and exams: exam_id=exams[0]['id']
    st=cur.execute("SELECT * FROM students WHERE id=? AND school_id=?",(student_id,sid(request))).fetchone() if student_id else None
    ex=cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?",(exam_id,sid(request))).fetchone() if exam_id else None
    marks=[]
    if st and ex:
        marks=cur.execute("SELECT sub.name subject,m.marks FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.student_id=? AND m.exam_id=? AND m.school_id=? ORDER BY sub.name",(student_id,exam_id,sid(request))).fetchall()
    total=sum([(m['marks'] or 0) for m in marks]); avg=round(total/len(marks),2) if marks else 0
    trs=''.join([f"<tr><td>{m['subject']}</td><td>{m['marks']}</td><td>{'A' if (m['marks'] or 0)>=80 else 'B' if (m['marks'] or 0)>=60 else 'C' if (m['marks'] or 0)>=50 else 'D'}</td></tr>" for m in marks]) or '<tr><td colspan=3>No marks recorded for this examination.</td></tr>'
    opts=''.join([f"<option value='{x['id']}' {'selected' if x['id']==student_id else ''}>{x['name']} ({x['admission_no'] or ''})</option>" for x in students])
    eopts=''.join([f"<option value='{x['id']}' {'selected' if x['id']==exam_id else ''}>{x['name']} — {x['term']} {x['year']}</option>" for x in exams])
    school=get_school_obj(request)
    legacy_school_logo=str(school['logo_data'] or '') if school and 'logo_data' in school.keys() else ''
    legacy_school_name=escape(str(school['name'] or 'Mabale_ICT')) if school else 'Mabale_ICT'
    legacy_postal=escape('P.O. Box '+str(school['postal_address'])) if school and 'postal_address' in school.keys() and school['postal_address'] else ''
    legacy_postal_code=escape(str(school['postal_code'])) if school and 'postal_code' in school.keys() and school['postal_code'] else ''
    legacy_phone=escape(str(school['phone'] or '')) if school else ''
    legacy_email=escape(str(school['email'] or '')) if school else ''
    legacy_doc_contact="".join((("<div>%s</div>"%x) if x else "") for x in [" ".join(x for x in [legacy_postal,legacy_postal_code] if x),legacy_email,legacy_phone])
    legacy_doc_header="<div class='legacy-doc-header'><div class='legacy-doc-logo'>%s</div><div class='legacy-doc-school'><div class='legacy-doc-name'>%s</div><div class='legacy-doc-contact'>%s</div></div><div class='legacy-doc-student-photo' title='Student photo'>👤</div></div>" % ((("<img src='%s' alt='School logo'>" % escape(legacy_school_logo)) if legacy_school_logo else '🏫'),legacy_school_name,legacy_doc_contact)
    body=f"""<div class='card no-print'><form method='get' style='display:flex;gap:10px;flex-wrap:wrap'><select name='student_id' class='input-field' style='max-width:320px'>{opts}</select><select name='exam_id' class='input-field' style='max-width:260px'>{eopts}</select><button class='btn'>Load Report</button><button type='button' class='btn' onclick='window.print()'>🖨️ Print</button></form></div><div class='card' id='report-card'><div class='legacy-print-document'>{legacy_doc_header}<div class='legacy-report-title'>STUDENT REPORT CARD</div><div class='legacy-report-subtitle'>{ex['name'] if ex else ''} — {ex['term'] if ex else ''} {ex['year'] if ex else ''}</div><div style='display:flex;justify-content:space-between;margin:18px 0'><div><b>Student:</b> {st['name'] if st else ''}<br><b>Admission:</b> {st['admission_no'] if st else ''}</div><div><b>Total:</b> {total}<br><b>Average:</b> {avg}</div></div><table><tr><th>Subject</th><th>Marks</th><th>Grade</th></tr>{trs}</table><p style='margin-top:20px'><b>Teacher/School Comment:</b> ________________________________</p><p><b>Principal/Head Comment:</b> __________________________________</p></div></div><style>.legacy-doc-header{{display:grid;grid-template-columns:86px 1fr 86px;align-items:center;gap:12px;border-top:2px solid #f4b400;border-bottom:3px solid #0b3d91;padding:8px 4px 10px;margin-bottom:10px}}.legacy-doc-logo{{width:86px;height:70px;display:flex;align-items:center;justify-content:center}}.legacy-doc-logo img{{max-width:82px;max-height:66px;object-fit:contain}}.legacy-doc-school{{min-width:0;text-align:center;color:#0b3d91}}.legacy-doc-name{{font-size:18px;line-height:1.15;font-weight:900;text-transform:uppercase}}.legacy-doc-contact{{font-size:10px;color:#334155;line-height:1.45;margin-top:4px}}.legacy-doc-contact div{{display:block;margin:1px 0;text-align:center}}.legacy-doc-student-photo{{width:70px;height:78px;border:1px solid #94a3b8;border-radius:5px;margin-left:auto;display:flex;align-items:center;justify-content:center;font-size:34px;background:#f8fafc;color:#64748b}}.legacy-report-title{{text-align:center;color:#0b3d91;font-size:22px;font-weight:900;padding:5px}}.legacy-report-subtitle{{text-align:center;color:#334155;font-size:11px;margin-bottom:8px}}@media print{{@page{{size:A4;margin:8mm 10mm 12mm}}.legacy-doc-header{{break-inside:avoid}}.legacy-print-document{{display:block!important}}.legacy-print-document table th{{background:#0b3d91!important;color:#fff!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}.legacy-print-document table th,.legacy-print-document table td{{border-color:#0b3d91!important}}.legacy-print-document .legacy-report-title{{color:#0b3d91!important}}}}</style>"""
    con.close(); return module_page(request,'📄 Report Card','marksheets',body)

@app.get("/school/subject-allocation", response_class=HTMLResponse)
def school_subject_allocation(request:Request, class_id: int | None = None):
    return dean_settings(request, tab="allocation", class_id=class_id)

@app.get("/school/spreadsheet", response_class=HTMLResponse)
def school_spreadsheet(request:Request):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT s.name student,sub.name subject,e.name exam,m.marks FROM marks m JOIN students s ON m.student_id=s.id JOIN subjects sub ON m.subject_id=sub.id JOIN exams e ON m.exam_id=e.id WHERE m.school_id=? ORDER BY s.name,sub.name",(sid(request),)); rows=cur.fetchall(); con.close(); tr=''.join([f"<tr><td>{r['student']}</td><td>{r['subject']}</td><td>{r['exam']}</td><td>{r['marks']}</td></tr>" for r in rows]) or '<tr><td colspan=4>No marks data.</td></tr>'; body=f"<div class='card'><table><tr><th>Student</th><th>Subject</th><th>Exam</th><th>Marks</th></tr>{tr}</table></div>"; return module_page(request,'📑 Spreadsheet','spreadsheet',body)
@app.get("/school/sba", response_class=HTMLResponse)
def school_sba(request:Request):
    body="<div class='card'><h3>📋 SBA (KNEC CBA)</h3><p>Assessment workspace connected to the school's students, classes and subjects.</p><table><tr><th>Component</th><th>Status</th></tr><tr><td>Student records</td><td>Connected</td></tr><tr><td>Subjects</td><td>Connected</td></tr><tr><td>Classes</td><td>Connected</td></tr><tr><td>Assessment workspace</td><td>Ready</td></tr></table></div>"; return module_page(request,'📋 SBA (KNEC CBA)','sba',body)

@app.post("/school/modules/roles/add")
def school_role_add(request:Request,role:str=Form(...),permission:str=Form(...)):
    con=get_db(); con.execute("INSERT INTO roles_permissions(school_id,role,permission,enabled) VALUES(?,?,?,1)",(sid(request),role,permission)); con.commit(); con.close(); return RedirectResponse('/school/system-settings/roles-permissions',303)
@app.post("/school/modules/integrations/add")
def school_integration_add(request:Request,name:str=Form(...),status:str=Form(...),config:str=Form('')):
    con=get_db(); con.execute("INSERT INTO integrations(school_id,name,status,config) VALUES(?,?,?,?)",(sid(request),name,status,config)); con.commit(); con.close(); return RedirectResponse('/school/system-settings/integrations',303)

@app.post("/school/modules/fees/payment/{fee_id}")
def record_fee_payment(fee_id:int, request:Request, paid:float=Form(...)):
    con=get_db(); cur=con.cursor(); row=cur.execute("SELECT * FROM fees WHERE id=? AND school_id=?",(fee_id,sid(request))).fetchone()
    if row:
        new_paid=max(0,float(row['paid'] or 0)+paid); status='Paid' if new_paid>=float(row['amount'] or 0) else 'Partial'
        cur.execute("UPDATE fees SET paid=?,status=? WHERE id=? AND school_id=?",(new_paid,status,fee_id,sid(request))); con.commit()
    con.close(); return RedirectResponse('/school/fees',303)

@app.get("/school/attendance", response_class=HTMLResponse)
def school_attendance(request:Request):
    con=get_db(); cur=con.cursor(); students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid(request),)).fetchall(); recent=cur.execute("SELECT a.date,a.status,s.name student FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.school_id=? ORDER BY a.id DESC LIMIT 100",(sid(request),)).fetchall(); con.close()
    opts=''.join([f"<option value='{x['id']}'>{x['name']} — {x['admission_no'] or ''}</option>" for x in students]); tr=''.join([f"<tr><td>{r['date']}</td><td>{r['student']}</td><td>{r['status']}</td></tr>" for r in recent]) or '<tr><td colspan=3>No attendance records.</td></tr>'
    body=f"<div class='card'><h3>🗓️ Attendance</h3><form method='post' action='/school/attendance/record'><select name='student_id' class='input-field'>{opts}</select><input type='date' name='date' required class='input-field'><select name='status' class='input-field'><option>Present</option><option>Absent</option><option>Late</option><option>Excused</option></select><button class='btn'>Record Attendance</button></form><table style='margin-top:16px'><tr><th>Date</th><th>Student</th><th>Status</th></tr>{tr}</table></div>"
    return module_page(request,'🗓️ Attendance','attendance',body)
@app.post("/school/attendance/record")
def school_attendance_record(request:Request,student_id:int=Form(...),date:str=Form(...),status:str=Form(...)):
    if not _role_permission(request,"attendance.edit"):
        return RedirectResponse("/portal",303)
    con=get_db(); con.execute("INSERT INTO attendance(school_id,student_id,date,status) VALUES(?,?,?,?)",(sid(request),student_id,date,status)); con.commit(); con.close(); return RedirectResponse('/school/attendance',303)

# Global mirrors of the school operational windows.
def school_student_profile(student_id: int, request: Request):
    school = _school_user(request)
    if not school: return RedirectResponse("/")
    con=get_db(); cur=con.cursor()
    st=cur.execute("SELECT s.*, c.name class_name, c.stream class_stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(student_id,school["id"])).fetchone()
    if not st:
        con.close(); return RedirectResponse("/school/students",303)
    marks=cur.execute("SELECT sub.name subject,e.name exam,m.marks,e.term,e.year FROM marks m JOIN subjects sub ON sub.id=m.subject_id JOIN exams e ON e.id=m.exam_id WHERE m.student_id=? AND m.school_id=? ORDER BY e.year DESC,e.id DESC,sub.name",(student_id,school["id"])).fetchall()
    fees=cur.execute("SELECT COALESCE(SUM(amount),0) expected, COALESCE(SUM(paid),0) paid FROM fees WHERE student_id=? AND school_id=?",(student_id,school["id"])).fetchone()
    con.close()
    mr=''.join(f"<tr><td>{r['subject']}</td><td>{r['exam']}</td><td>{r['marks']}</td><td>{r['term']} {r['year']}</td></tr>" for r in marks) or '<tr><td colspan=4>No academic records yet.</td></tr>'
    body=f"""<div class='card'><div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap'><div><h2 style='margin:0'>{st['name']}</h2><p>Admission: {st['admission_no'] or '—'} | Assessment: {st['assessment_no'] or '—'}</p><p>Class: {st['class_name'] or '—'} {st['class_stream'] or ''} | Gender: {st['gender'] or '—'} | Category: {st['category'] or '—'}</p><p>Guardian: {st['guardian_name'] or '—'} | Phone: {st['parent_phone'] or '—'}</p></div><div><a class='btn' href='/school/students/{student_id}/edit'>✏️ Edit Student</a> <a class='btn' href='/school/student-analysis/{student_id}'>📊 Analysis</a> <a class='btn' href='/school/report-cards?student_id={student_id}'>📄 Report Card</a></div></div></div>
    <div class='card'><h3>💰 Fee Position</h3><p>Expected: <b>{float(fees['expected'] or 0):,.2f}</b> &nbsp; Paid: <b>{float(fees['paid'] or 0):,.2f}</b> &nbsp; Balance: <b>{float(fees['expected'] or 0)-float(fees['paid'] or 0):,.2f}</b></p></div>
    <div class='card'><h3>📚 Academic Record</h3><table><tr><th>Subject</th><th>Exam</th><th>Marks</th><th>Term</th></tr>{mr}</table></div>"""
    return module_page(request,f"🎓 Student Profile — {st['name']}","students",body)

@app.get("/school/students/{student_id}/edit", response_class=HTMLResponse)
def school_student_edit(student_id:int, request:Request):
    school=_school_user(request)
    if not school: return RedirectResponse("/")
    con=get_db(); cur=con.cursor(); st=cur.execute("SELECT * FROM students WHERE id=? AND school_id=?",(student_id,school["id"])).fetchone(); classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(school["id"],)).fetchall(); con.close()
    if not st: return RedirectResponse("/school/students",303)
    opts=''.join(f"<option value='{c[0]}' {'selected' if c['id']==st['class_id'] else ''}>{c['name']} {c['stream'] or ''}</option>" for c in classes)
    body=f"""<div class='card'><h2>✏️ Edit Student</h2><form method='post' action='/school/students/{student_id}/edit' data-native-post='1' data-no-history-filter='1' class='form-grid'><label>Admission No<input name='admission_no' value='{st['admission_no'] or ''}' required class='input-field'></label><label>Assessment No<input name='assessment_no' value='{st['assessment_no'] or ''}' class='input-field'></label><label style='grid-column:span 2'>Full Name<input name='student_name' value='{st['name'] or ''}' required class='input-field'></label><label>Class<select name='class_id' class='input-field'>{opts}</select></label><label>Gender<select name='gender' class='input-field'><option {'selected' if st['gender']=='Male' else ''}>Male</option><option {'selected' if st['gender']=='Female' else ''}>Female</option></select></label><label>Category<select name='category' class='input-field'><option {'selected' if (st['category'] or 'Day')=='Day' else ''}>Day</option><option {'selected' if st['category']=='Boarding' else ''}>Boarding</option></select></label><label>Guardian<input name='guardian_name' value='{st['guardian_name'] or ''}' class='input-field'></label><label style='grid-column:span 2'>Guardian Phone<input name='parent_phone' value='{st['parent_phone'] or ''}' class='input-field'></label><button type='submit' name='save_student' value='1' class='btn' style='grid-column:span 2'>💾 Save Student</button></form></div>"""
    return module_page(request,"Edit Student","students",body)

@app.post("/school/students/{student_id}/edit")
def school_student_edit_save(student_id:int, request:Request, admission_no:str=Form(...), assessment_no:str=Form(""), student_name:str=Form(...), class_id:int=Form(...), gender:str=Form(...), category:str=Form("Day"), guardian_name:str=Form(""), parent_phone:str=Form("")):
    school=_school_user(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); con.execute("UPDATE students SET admission_no=?,assessment_no=?,name=?,class_id=?,gender=?,category=?,guardian_name=?,parent_phone=? WHERE id=? AND school_id=?",(admission_no.strip().upper(),assessment_no.strip().upper(),student_name.strip().upper(),class_id,gender,category,guardian_name.strip().upper(),parent_phone.strip(),student_id,school["id"])); con.commit(); con.close(); return RedirectResponse(f"/school/students/{student_id}",303)

@app.get("/school/teachers/{teacher_id}/edit", response_class=HTMLResponse)
def school_teacher_edit(teacher_id:int, request:Request):
    school=_school_user(request)
    if not school: return RedirectResponse("/")
    con=get_db(); t=con.execute("SELECT * FROM teachers WHERE id=? AND school_id=?",(teacher_id,school["id"])).fetchone(); con.close()
    if not t: return RedirectResponse("/school/teachers",303)
    role_choices=['Teacher','Classteacher','Principal','Deputy Principal','Administrator','Other']
    current_role=(t['role'] or '').strip()
    if current_role and current_role not in role_choices: role_choices.append(current_role)
    role_options=''.join(f"<option value='{escape(r, quote=True)}' {'selected' if r==current_role else ''}>{escape(r)}</option>" for r in role_choices)
    body=f"""<div class='card'><h2>✏️ Edit Staff Member</h2><form method='post' action='/school/teachers/{teacher_id}/edit' class='form-grid'><label>Full Name<input name='name' value='{escape(t['name'] or '', quote=True)}' required class='input-field'></label><label>TSC No<input name='tsc_no' value='{escape(t['tsc_no'] or '', quote=True)}' class='input-field'></label><label>ID No<input name='id_no' value='{escape(t['id_no'] or '', quote=True)}' class='input-field'></label><label>Gender<select name='gender' class='input-field'><option {'selected' if t['gender']=='Male' else ''}>Male</option><option {'selected' if t['gender']=='Female' else ''}>Female</option></select></label><label>Role<select name='role' id='editStaffRole' class='input-field' onchange="filterStaffDepartments('editStaffRole','editStaffDepartment')">{role_options}</select></label><label>Department<select name='department' id='editStaffDepartment' class='input-field'><option value=''>Select Department</option></select></label><label>Employment Type<select name='employment_type' class='input-field'><option value='Teaching' {'selected' if (t['employment_type'] or 'Teaching')=='Teaching' else ''}>Teaching</option><option value='Non-Teaching' {'selected' if (t['employment_type'] or '')=='Non-Teaching' else ''}>Non-Teaching</option></select></label><label>Phone<input name='phone' value='{escape(t['phone'] or '', quote=True)}' class='input-field'></label><label>Email<input name='email' type='email' value='{escape(t['email'] or '', quote=True)}' class='input-field'></label><button class='btn' style='grid-column:span 2'>💾 Save Changes</button></form></div><script>
function filterStaffDepartments(roleId,deptId,selected){{
 const role=(document.getElementById(roleId)?.value||'').trim().toLowerCase();
 const teaching=['teacher','classteacher','principal','deputy principal'].includes(role);
 const teachingDepartments=['ECDE / Early Childhood Education','Lower Primary','Upper Primary','Junior School','Senior School','Languages','Mathematics','Sciences','Humanities & Social Sciences','Technical & Vocational Studies','Creative Arts & Sports','Religious Education','Special Needs Education','Academic Coordination'];
 const otherDepartments=['School Administration','Registry & Admissions','Finance & Accounts','Human Resources','ICT & Technology','Library Services','Guidance & Counselling','Examinations Department','Laboratory Department','Sports & Physical Education','Transport Department','Security Department','Catering & Nutrition','Health & Medical Services','Maintenance & Facilities','Cleaning & Sanitation','Boarding & Accommodation','Procurement & Stores','Support Services','Other'];
 const select=document.getElementById(deptId); if(!select)return;
 const previous=selected!==undefined?selected:select.value;
 const options=teaching?teachingDepartments:otherDepartments;
 select.innerHTML='<option value="">Select Department</option>'+options.map(v=>'<option value="'+v.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'">'+v+'</option>').join('');
 if(previous&&options.includes(previous))select.value=previous;
 else if(previous&&selected!==undefined){{select.add(new Option(previous,previous));select.value=previous;}}
}}
filterStaffDepartments('editStaffRole','editStaffDepartment',{json.dumps(t['department'] or '')});
</script>"""
    return module_page(request,"Edit Staff","staff",body)

@app.post("/school/teachers/{teacher_id}/edit")
def school_teacher_edit_save(teacher_id:int, request:Request, name:str=Form(...), tsc_no:str=Form(""), id_no:str=Form(""), gender:str=Form(""), role:str=Form(""), department:str=Form(""), phone:str=Form(""), email:str=Form(""), employment_type:str=Form("Teaching")):
    school=_school_user(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); department=department.strip()
    allowed_departments=_staff_department_choices(role)
    if department and department not in allowed_departments: department=''
    con.execute("UPDATE teachers SET name=?,tsc_no=?,id_no=?,gender=?,role=?,department=?,phone=?,email=?,employment_type=? WHERE id=? AND school_id=?",(name.strip().upper(),tsc_no.strip(),id_no.strip(),gender,role.strip(),department,phone.strip(),email.strip(),employment_type.strip(),teacher_id,school["id"])); con.commit(); con.close(); return RedirectResponse("/school/teachers",303)

@app.get("/school/classes/{class_id}/edit", response_class=HTMLResponse)
def school_class_edit(class_id:int, request:Request):
    school=_school_user(request)
    if not school: return RedirectResponse("/")
    con=get_db(); c=con.execute("SELECT * FROM classes WHERE id=? AND school_id=?",(class_id,school["id"])).fetchone(); con.close()
    if not c: return RedirectResponse("/school/classes",303)
    body=f"<div class='card'><h2>✏️ Edit Class</h2><form method='post' action='/school/classes/{class_id}/edit' class='form-grid'><label>Class Name<input name='name' value='{c['name'] or ''}' required class='input-field'></label><label>Level<input name='level' value='{c['level'] or ''}' class='input-field'></label><label>Stream<input name='stream' value='{c['stream'] or ''}' class='input-field'></label><button class='btn'>💾 Save Changes</button></form></div>"
    return module_page(request,"Edit Class","classes",body)

@app.post("/school/classes/{class_id}/edit")
def school_class_edit_save(class_id:int, request:Request, name:str=Form(...), level:str=Form(""), stream:str=Form("")):
    school=_school_user(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); con.execute("UPDATE classes SET name=?,level=?,stream=? WHERE id=? AND school_id=?",(name.strip(),level.strip(),stream.strip(),class_id,school["id"])); con.commit(); con.close(); return RedirectResponse("/school/classes",303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request:Request):
    school=_school_user(request)
    if not school: return RedirectResponse("/")
    con=get_db(); rows=con.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(school["id"],)).fetchall(); con.close()
    tr=''.join(f"<tr><td>{r['name']}</td><td>{r['code'] or ''}</td><td>{r['initial'] or ''}</td><td><a class='btn' href='/school/subjects/{r[0]}/edit'>Edit</a></td></tr>" for r in rows) or '<tr><td colspan=4>No subjects yet.</td></tr>'
    body=f"<div class='card'><h2>📚 Subjects</h2><table><tr><th>Name</th><th>Code</th><th>Initial</th><th>Action</th></tr>{tr}</table></div>"
    return module_page(request,"Subjects","subject-allocation",body)

@app.get("/school/subjects/{subject_id}/edit", response_class=HTMLResponse)
def school_subject_edit(subject_id:int, request:Request):
    school=_school_user(request)
    if not school: return RedirectResponse("/")
    con=get_db(); s=con.execute("SELECT * FROM subjects WHERE id=? AND school_id=?",(subject_id,school["id"])).fetchone(); con.close()
    if not s: return RedirectResponse("/school/subjects",303)
    body=f"<div class='card'><h2>✏️ Edit Subject</h2><form method='post' action='/school/subjects/{subject_id}/edit' class='form-grid'><label>Name<input name='name' value='{s['name'] or ''}' required class='input-field'></label><label>Code<input name='code' value='{s['code'] or ''}' class='input-field'></label><label>Initial<input name='initial' value='{s['initial'] or ''}' class='input-field'></label><button class='btn'>💾 Save Changes</button></form></div>"
    return module_page(request,"Edit Subject","subject-allocation",body)

@app.post("/school/subjects/{subject_id}/edit")
def school_subject_edit_save(subject_id:int, request:Request, name:str=Form(...), code:str=Form(""), initial:str=Form("")):
    school=_school_user(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); con.execute("UPDATE subjects SET name=?,code=?,initial=? WHERE id=? AND school_id=?",(name.strip().upper(),code.strip().upper(),initial.strip().upper(),subject_id,school["id"])); con.commit(); con.close(); return RedirectResponse("/school/subjects",303)

@app.get("/school/terms", response_class=HTMLResponse)
def school_terms(request:Request):
    school=_school_user(request)
    if not school: return RedirectResponse("/")
    con=get_db(); rows=con.execute("SELECT * FROM terms WHERE school_id=? ORDER BY year DESC,id DESC",(school["id"],)).fetchall(); con.close()
    tr=''.join(f"<tr><td>{r['term_name']}</td><td>{r['year']}</td><td>{r['start_date'] or ''}</td><td>{r['end_date'] or ''}</td></tr>" for r in rows) or '<tr><td colspan=4>No terms configured.</td></tr>'
    body=f"<div class='card'><h2>📅 Academic Terms</h2><form method='post' action='/school/terms/new' class='form-grid'><input name='term_name' placeholder='Term 1' required class='input-field'><input name='year' placeholder='2026' required class='input-field'><input name='start_date' type='date' class='input-field'><input name='end_date' type='date' class='input-field'><button class='btn'>+ Add Term</button></form></div><div class='card'><table><tr><th>Term</th><th>Year</th><th>Start</th><th>End</th></tr>{tr}</table></div>"
    return module_page(request,"Academic Terms","dean-settings",body)

@app.post("/school/terms/new")
def school_term_new(request:Request, term_name:str=Form(...), year:str=Form(...), start_date:str=Form(""), end_date:str=Form("")):
    school=_school_user(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); con.execute("INSERT INTO terms(school_id,term_name,year,start_date,end_date) VALUES(?,?,?,?,?)",(school["id"],term_name.strip(),year.strip(),start_date,end_date)); con.commit(); con.close(); return RedirectResponse("/school/terms",303)

@app.get("/school/exams/new", response_class=HTMLResponse)
def school_exam_new(request:Request):
    school=_school_user(request)
    if not school: return RedirectResponse("/")
    con=get_db(); terms=con.execute("SELECT * FROM terms WHERE school_id=? ORDER BY year DESC,id DESC",(school["id"],)).fetchall(); con.close()
    opts=''.join(f"<option value='{t['term_name']}|{t['year']}'>{t['term_name']} {t['year']}</option>" for t in terms)
    fallback="<option value='Term 1|2026'>Term 1 2026</option>"
    body=f"<div class='card'><h2>📝 Add Examination</h2><form method='post' action='/school/exams/add' class='form-grid'><input name='exam_name' placeholder='Exam name' required class='input-field'><select name='term_year' class='input-field'>{opts or fallback}</select><input name='exam_type' placeholder='Exam type e.g. CAT, End Term' class='input-field'><button class='btn'>+ Create Exam</button></form></div>"
    return module_page(request,"Add Examination","exams",body)

@app.get("/school/academics", response_class=HTMLResponse)
def school_academics(request:Request):
    school=_school_user(request)
    if not school: return RedirectResponse("/")
    cards=[("📅 Terms","/school/terms","Academic calendar"),("📝 Exams","/school/exams","Examination setup"),("⚙️ Set Marks","/school/set-marks","Configure assessment limits"),("✏️ Record Marks","/school/record-marks","Enter learner marks"),("📊 Analysis","/school/analysis","Subject and class analysis"),("📄 Report Cards","/school/report-cards","Generate printable reports"),("🗓️ Attendance","/school/attendance","Track attendance"),("👨‍🏫 Allocation","/school/subject-allocation","Allocate teachers and subjects"),("📑 Spreadsheet","/school/spreadsheet","View assessment data")]
    grid=''.join(f"<a href='{u}' class='card' style='text-decoration:none;color:inherit'><h3 style='margin:0 0 8px'>{t}</h3><p style='color:#64748b;margin:0'>{d}</p></a>" for t,u,d in cards)
    return module_page(request,"📚 Academics Workspace","analysis",f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px'>{grid}</div>")


# === DAVISCHOOL ACCOUNTING & ADMIN EXTENSIONS ===
# These additive routes extend the existing school workspace without replacing
# the existing UI. All records are strictly scoped to the logged-in school.

def _school_admin_guard(request: Request):
    school = _school_user(request)
    if not school or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
        return None
    return school

def _accounting_shell(request, title, active, body):
    return module_page(request, title, active, body)

@app.get("/school/accounting", response_class=HTMLResponse)
def school_accounting(request: Request):
    school = _school_admin_guard(request)
    if not school: return RedirectResponse("/", 303)
    con=get_db(); cur=con.cursor(); sid_=school["id"]
    fee=cur.execute("SELECT COALESCE(SUM(paid),0) n FROM fees WHERE school_id=?",(sid_,)).fetchone()["n"]
    expenses=cur.execute("SELECT COALESCE(SUM(amount),0) n FROM expenses WHERE school_id=?",(sid_,)).fetchone()["n"]
    cash_in=cur.execute("SELECT COALESCE(SUM(credit),0) n FROM cashbook WHERE school_id=?",(sid_,)).fetchone()["n"]
    cash_out=cur.execute("SELECT COALESCE(SUM(debit),0) n FROM cashbook WHERE school_id=?",(sid_,)).fetchone()["n"]
    pledges=cur.execute("SELECT COALESCE(SUM(amount),0) n FROM pledges WHERE school_id=?",(sid_,)).fetchone()["n"]
    pledge_paid=cur.execute("SELECT COALESCE(SUM(paid),0) n FROM pledges WHERE school_id=?",(sid_,)).fetchone()["n"]
    vouchers=cur.execute("SELECT * FROM payment_vouchers WHERE school_id=? ORDER BY id DESC LIMIT 50",(sid_,)).fetchall()
    lpos=cur.execute("SELECT * FROM lpos WHERE school_id=? ORDER BY id DESC LIMIT 50",(sid_,)).fetchall()
    con.close()
    vr="".join(f"<tr><td>{v['date']}</td><td>{v['voucher_no']}</td><td>{v['payee']}</td><td>{v['amount']}</td><td>{v['status']}</td></tr>" for v in vouchers) or "<tr><td colspan=5>No vouchers.</td></tr>"
    lr="".join(f"<tr><td>{v['date']}</td><td>{v['lpo_no']}</td><td>{v['supplier']}</td><td>{v['amount']}</td><td>{v['status']}</td></tr>" for v in lpos) or "<tr><td colspan=5>No LPOs.</td></tr>"
    body=f"""<div class='kpis'>
<div class='kpi'><span>FEES RECEIVED</span><b>KES {float(fee or 0):,.2f}</b></div>
<div class='kpi'><span>EXPENSES</span><b>KES {float(expenses or 0):,.2f}</b></div>
<div class='kpi'><span>CASHBOOK NET</span><b>KES {float(cash_in or 0)-float(cash_out or 0):,.2f}</b></div>
<div class='kpi'><span>PLEDGE BALANCE</span><b>KES {float(pledges or 0)-float(pledge_paid or 0):,.2f}</b></div></div>
<div class='grid-2'>
<div class='card'><h3>🧾 Payment Voucher</h3><form method='post' action='/school/accounting/voucher'>
<input name='voucher_no' required placeholder='Voucher number' class='input-field'><input name='payee' required placeholder='Payee' class='input-field'>
<input name='description' required placeholder='Description' class='input-field'><input name='amount' required type='number' min='0.01' step='0.01' placeholder='Amount' class='input-field'>
<input name='date' required type='date' class='input-field'><select name='status' class='input-field'><option>Draft</option><option>Approved</option><option>Paid</option></select><button class='btn'>Save Voucher</button></form></div>
<div class='card'><h3>🛒 Local Purchase Order</h3><form method='post' action='/school/accounting/lpo'>
<input name='lpo_no' required placeholder='LPO number' class='input-field'><input name='supplier' required placeholder='Supplier' class='input-field'>
<input name='description' required placeholder='Description' class='input-field'><input name='amount' required type='number' min='0.01' step='0.01' placeholder='Amount' class='input-field'>
<input name='date' required type='date' class='input-field'><select name='status' class='input-field'><option>Open</option><option>Approved</option><option>Closed</option></select><button class='btn'>Save LPO</button></form></div></div>
<div class='card'><h3>🧾 Payment Vouchers</h3><table><tr><th>Date</th><th>Voucher</th><th>Payee</th><th>Amount</th><th>Status</th></tr>{vr}</table></div>
<div class='card'><h3>🛒 LPO Register</h3><table><tr><th>Date</th><th>LPO</th><th>Supplier</th><th>Amount</th><th>Status</th></tr>{lr}</table></div>
<div class='card'><h3>📊 Trial Balance / Cashbook Summary</h3><p>Debits: <b>KES {float(cash_out or 0):,.2f}</b> &nbsp; Credits: <b>KES {float(cash_in or 0):,.2f}</b> &nbsp; Net: <b>KES {float(cash_in or 0)-float(cash_out or 0):,.2f}</b></p><a class='btn' href='/school/accounting/trial-balance'>Open Trial Balance</a></div>"""
    return _accounting_shell(request,"📚 Accounting & Finance","fees",body)

@app.post("/school/accounting/voucher")
def school_accounting_voucher(request:Request,voucher_no:str=Form(...),payee:str=Form(...),description:str=Form(...),amount:float=Form(...),date:str=Form(...),status:str=Form(...)):
    school=_school_admin_guard(request)
    if not school or amount<=0: return RedirectResponse("/school/accounting",303)
    con=get_db(); con.execute("INSERT INTO payment_vouchers(school_id,voucher_no,payee,description,amount,date,status) VALUES(?,?,?,?,?,?,?)",(school["id"],voucher_no.strip(),payee.strip(),description.strip(),amount,date,status)); con.commit(); con.close()
    return RedirectResponse("/school/accounting",303)

@app.post("/school/accounting/lpo")
def school_accounting_lpo(request:Request,lpo_no:str=Form(...),supplier:str=Form(...),description:str=Form(...),amount:float=Form(...),date:str=Form(...),status:str=Form(...)):
    school=_school_admin_guard(request)
    if not school or amount<=0: return RedirectResponse("/school/accounting",303)
    con=get_db(); con.execute("INSERT INTO lpos(school_id,lpo_no,supplier,description,amount,date,status) VALUES(?,?,?,?,?,?,?)",(school["id"],lpo_no.strip(),supplier.strip(),description.strip(),amount,date,status)); con.commit(); con.close()
    return RedirectResponse("/school/accounting",303)

@app.get("/school/accounting/trial-balance", response_class=HTMLResponse)
def school_trial_balance(request:Request):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor(); sid_=school["id"]
    rows=cur.execute("SELECT account,COALESCE(SUM(debit),0) debit,COALESCE(SUM(credit),0) credit FROM cashbook WHERE school_id=? GROUP BY account ORDER BY account",(sid_,)).fetchall()
    con.close()
    tr="".join(f"<tr><td>{r['account']}</td><td>KES {float(r['debit'] or 0):,.2f}</td><td>KES {float(r['credit'] or 0):,.2f}</td><td>KES {float(r['debit'] or 0)-float(r['credit'] or 0):,.2f}</td></tr>" for r in rows) or "<tr><td colspan=4>No posted accounting entries.</td></tr>"
    body=f"""<div class='card'><h2>📊 Trial Balance</h2><p>School: <b>{school['name']}</b></p><table><tr><th>Account</th><th>Debit</th><th>Credit</th><th>Net</th></tr>{tr}</table></div>
<div class='card'><a class='btn' href='/school/accounting'>← Back to Accounting</a></div>"""
    return _accounting_shell(request,"📊 Trial Balance","fees",body)

@app.get("/school/roles", response_class=HTMLResponse)
def school_roles(request:Request):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); rows=con.execute("SELECT * FROM roles_permissions WHERE school_id=? ORDER BY role,permission",(school["id"],)).fetchall(); con.close()
    tr="".join(f"<tr><td>{r['role']}</td><td>{r['permission']}</td><td>{'Enabled' if r['enabled'] else 'Disabled'}</td></tr>" for r in rows) or "<tr><td colspan=3>No custom permissions configured.</td></tr>"
    body=f"""<div class='card'><h2>🛡️ Roles & Permissions</h2><form method='post' action='/school/roles'>
<input name='role' required placeholder='Role e.g. teacher' class='input-field'><input name='permission' required placeholder='Permission e.g. record_marks' class='input-field'>
<select name='enabled' class='input-field'><option value='1'>Enabled</option><option value='0'>Disabled</option></select><button class='btn'>Save Permission</button></form></div>
<div class='card'><table><tr><th>Role</th><th>Permission</th><th>Status</th></tr>{tr}</table></div>"""
    return _accounting_shell(request,"🛡️ Roles & Permissions","system-settings/roles-permissions",body)

@app.post("/school/roles")
def school_roles_save(request:Request,role:str=Form(...),permission:str=Form(...),enabled:int=Form(1)):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM roles_permissions WHERE school_id=? AND role=? AND permission=?",(school["id"],role.strip(),permission.strip()))
    cur.execute("INSERT INTO roles_permissions(school_id,role,permission,enabled) VALUES(?,?,?,?)",(school["id"],role.strip(),permission.strip(),1 if enabled else 0))
    con.commit(); con.close(); return RedirectResponse("/school/roles",303)

@app.get("/school/system-audit", response_class=HTMLResponse)
def school_system_audit(request:Request):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); rows=con.execute("SELECT * FROM system_audit WHERE school_id=? ORDER BY id DESC LIMIT 200",(school["id"],)).fetchall(); con.close()
    tr="".join(f"<tr><td>{r['timestamp']}</td><td>{r['user_email']}</td><td>{r['action']}</td><td>{r['details']}</td></tr>" for r in rows) or "<tr><td colspan=4>No audit entries yet.</td></tr>"
    return _accounting_shell(request,"📈 System Audit","system-settings/system-audit",f"<div class='card'><table><tr><th>Time</th><th>User</th><th>Action</th><th>Details</th></tr>{tr}</table></div>")

@app.get("/school/attendance-register", response_class=HTMLResponse)
def school_attendance_register(request:Request):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor()
    rows=cur.execute("SELECT a.date,s.name student,c.name class_name,a.status FROM attendance a JOIN students s ON s.id=a.student_id LEFT JOIN classes c ON c.id=s.class_id WHERE a.school_id=? ORDER BY a.date DESC,a.id DESC LIMIT 300",(school["id"],)).fetchall()
    con.close()
    tr="".join(f"<tr><td>{r['date']}</td><td>{r['student']}</td><td>{r['class_name'] or ''}</td><td>{r['status']}</td></tr>" for r in rows) or "<tr><td colspan=4>No attendance records.</td></tr>"
    return _accounting_shell(request,"🗓️ Attendance Register","attendance",f"<div class='card'><table><tr><th>Date</th><th>Student</th><th>Class</th><th>Status</th></tr>{tr}</table></div>")




# === DAVISCHOOL REMAINING MAJOR FUNCTIONALITY ===
@app.get("/school/attendance/bulk", response_class=HTMLResponse)
def school_attendance_bulk(request: Request, date: str = ""):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    if not date: date=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d")
    con=get_db(); cur=con.cursor()
    students=cur.execute("SELECT s.id,s.name,s.admission_no,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY c.name,c.stream,s.name",(school["id"],)).fetchall()
    existing={r["student_id"]:r["status"] for r in cur.execute("SELECT student_id,status FROM attendance WHERE school_id=? AND date=?",(school["id"],date)).fetchall()}
    con.close()
    rows="".join(f"<tr><td>{s['name']}</td><td>{s['admission_no'] or ''}</td><td>{s['class_name'] or ''} {s['stream'] or ''}</td><td><select name='status_{s['id']}' class='input-field'><option {'selected' if existing.get(s['id'])=='Present' else ''}>Present</option><option {'selected' if existing.get(s['id'])=='Absent' else ''}>Absent</option><option {'selected' if existing.get(s['id'])=='Late' else ''}>Late</option><option {'selected' if existing.get(s['id'])=='Excused' else ''}>Excused</option></select></td></tr>" for s in students)
    return module_page(request,"🗓️ Class Attendance","attendance",f"<div class='card'><h2>🗓️ Class Attendance</h2><form method='post' action='/school/attendance/bulk'><input type='date' name='date' value='{date}' required class='input-field'><table><tr><th>Student</th><th>Admission</th><th>Class</th><th>Status</th></tr>{rows or '<tr><td colspan=4>No students.</td></tr>'}</table><button class='btn' style='margin-top:12px'>Save Attendance</button></form></div>")

@app.post("/school/attendance/bulk")
async def school_attendance_bulk_save(request:Request):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    form=await request.form(); date=str(form.get("date") or "")
    if not date: return RedirectResponse("/school/attendance/bulk",303)
    con=get_db(); cur=con.cursor()
    students=cur.execute("SELECT id FROM students WHERE school_id=?",(school["id"],)).fetchall()
    for s in students:
        status=form.get(f"status_{s['id']}")
        if status:
            cur.execute("DELETE FROM attendance WHERE school_id=? AND student_id=? AND date=?",(school["id"],s["id"],date))
            cur.execute("INSERT INTO attendance(school_id,student_id,date,status) VALUES(?,?,?,?)",(school["id"],s["id"],date,str(status)))
    con.commit(); con.close(); return RedirectResponse(f"/school/attendance/bulk?date={date}",303)

@app.post("/school/report-cards/comment")
def school_report_comment(request:Request,student_id:int=Form(...),exam_id:int=Form(...),comment:str=Form(...)):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor()
    valid=cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,school["id"])).fetchone() and cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,school["id"])).fetchone()
    if valid:
        cur.execute("INSERT INTO report_comments(school_id,student_id,exam_id,comment,created_at) VALUES(?,?,?,?,?)",(school["id"],student_id,exam_id,comment.strip(),datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()
    con.close(); return RedirectResponse(f"/school/report-cards?student_id={student_id}&exam_id={exam_id}",303)

@app.get("/school/student-analysis/{student_id}", response_class=HTMLResponse)
def school_student_analysis_printable(student_id:int, request:Request):
    school=_school_admin_guard(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor()
    st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(student_id,school["id"])).fetchone()
    rows=cur.execute("SELECT sub.name subject,AVG(CAST(m.marks AS REAL)) average,COUNT(m.id) entries,MAX(m.marks) best,MIN(m.marks) lowest FROM marks m JOIN subjects sub ON sub.id=m.subject_id WHERE m.student_id=? AND m.school_id=? GROUP BY sub.id,sub.name ORDER BY sub.name",(student_id,school["id"])).fetchall() if st else []
    overall=cur.execute("SELECT AVG(CAST(marks AS REAL)) average,COUNT(id) entries FROM marks WHERE student_id=? AND school_id=?",(student_id,school["id"])).fetchone() if st else {"average":0,"entries":0}
    con.close()
    tr="".join(f"<tr><td>{r['subject']}</td><td>{round(r['average'] or 0,2)}</td><td>{r['best']}</td><td>{r['lowest']}</td><td>{r['entries']}</td></tr>" for r in rows) or "<tr><td colspan=5>No subject marks.</td></tr>"
    body=f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'><div><h2>🎓 Student Performance Analysis</h2><p><b>{st['name'] if st else 'Student not found'}</b> — {st['class_name'] if st else ''} {st['stream'] if st else ''}</p></div><button class='btn' onclick='window.print()'>🖨️ Print</button></div><div class='kpis'><div class='kpi'><span>OVERALL AVERAGE</span><b>{round(overall['average'] or 0,2)}</b></div><div class='kpi'><span>MARK ENTRIES</span><b>{overall['entries'] or 0}</b></div></div><table><tr><th>Subject</th><th>Average</th><th>Best</th><th>Lowest</th><th>Entries</th></tr>{tr}</table></div>"
    return module_page(request,"🎓 Student Analysis","analysis",body)

@app.get("/school/{path:path}", response_class=HTMLResponse)
def school_other(path: str, request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("is_portal_preview") and request.session.get("role") == "accountant":
        return RedirectResponse("/school/finance", 303)
    if request.session.get("role") not in ["school_admin","registrar","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    con=get_db(); cur=con.cursor(); school_id=sid(request)
    configs={"finance":("💰 Fees & Finance","/school/modules/finance/fee-payment","Record Payment"),"fees":("💳 Fees Management","/school/modules/fees/add","Create Fee Charge"),"teachers":("👨‍🏫 Staff Manager","/school/teachers/add","Add Staff"),"students":("🎓 Students Manager","/school/students/add","Add Student"),"attendance":("🗓️ Attendance","/school/attendance/record","Record Attendance"),"communication":("📢 Announcements","/school/modules/announcements/add","Create Announcement"),"sms":("💬 Bulk SMS Parents","/school/modules/sms/send","Send SMS")}
    if path in configs:
        title,action,label=configs[path]
        students=cur.execute("SELECT COUNT(*) n FROM students WHERE school_id=?",(school_id,)).fetchone()["n"]
        teachers=cur.execute("SELECT COUNT(*) n FROM teachers WHERE school_id=?",(school_id,)).fetchone()["n"]
        classes=cur.execute("SELECT COUNT(*) n FROM classes WHERE school_id=?",(school_id,)).fetchone()["n"]
        fees_total=cur.execute("SELECT COALESCE(SUM(amount),0) n FROM fees WHERE school_id=?",(school_id,)).fetchone()["n"]
        if path=="students":
            rows=cur.execute("SELECT s.name,s.admission_no,c.name class_name,c.stream,s.gender FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(school_id,)).fetchall(); table="<div class='card'><div class='toolbar'><b>Student Directory</b><input class='search' type='search' placeholder='Search students'></div><table><tr><th>Name</th><th>Admission</th><th>Class</th><th>Stream</th><th>Gender</th></tr>"+''.join(f"<tr><td>{r['name']}</td><td>{r['admission_no'] or ''}</td><td>{r['class_name'] or ''}</td><td>{r['stream'] or ''}</td><td>{r['gender'] or ''}</td></tr>" for r in rows)+"</table></div>"
        elif path=="teachers":
            rows=cur.execute("SELECT name,email,phone,role FROM teachers WHERE school_id=? ORDER BY name",(school_id,)).fetchall(); table="<div class='card'><div class='toolbar'><b>Staff Directory</b><input class='search' type='search' placeholder='Search staff'></div><table><tr><th>Name</th><th>Email</th><th>Phone</th><th>Subject</th></tr>"+''.join(f"<tr><td>{r['name']}</td><td>{r['email'] or ''}</td><td>{r['phone'] or ''}</td><td>{r['role'] or ''}</td></tr>" for r in rows)+"</table></div>"
        elif path=="fees":
            rows=cur.execute("SELECT f.*,s.name student_name FROM fees f LEFT JOIN students s ON s.id=f.student_id WHERE f.school_id=? ORDER BY f.id DESC LIMIT 100",(school_id,)).fetchall(); table="<div class='card'><div class='toolbar'><b>Fee Register</b><input class='search' type='search' placeholder='Search fee records'></div><table><tr><th>Student</th><th>Amount</th><th>Paid</th><th>Balance</th><th>Status</th></tr>"+''.join(f"<tr><td>{r['student_name'] or ''}</td><td>{r['amount'] or 0}</td><td>{r['paid'] or 0}</td><td>{(r['amount'] or 0)-(r['paid'] or 0)}</td><td><span class='badge'>{r['status'] or 'Pending'}</span></td></tr>" for r in rows)+"</table></div>"
        elif path=="attendance":
            rows=cur.execute("SELECT a.date,s.name student,a.status FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.school_id=? ORDER BY a.id DESC LIMIT 100",(school_id,)).fetchall(); table="<div class='card'><div class='toolbar'><b>Recent Attendance</b><input class='search' type='search' placeholder='Search attendance'></div><table><tr><th>Date</th><th>Student</th><th>Status</th></tr>"+''.join(f"<tr><td>{r['date']}</td><td>{r['student']}</td><td><span class='badge'>{r['status']}</span></td></tr>" for r in rows)+"</table></div>"
        else: table="<div class='card'><h3>Workspace</h3><p>Use the action above to create a new record. Existing records will appear here as soon as they are saved.</p></div>"
        con.close(); body=f"<div class='kpis'><div class='kpi'><span>STUDENTS</span><b>{students}</b></div><div class='kpi'><span>STAFF</span><b>{teachers}</b></div><div class='kpi'><span>CLASSES</span><b>{classes}</b></div><div class='kpi'><span>FEES CHARGED</span><b>{fees_total:,.0f}</b></div></div><div class='card toolbar'><div><b>Quick action</b><div style='font-size:12px;color:#64748b'>Create and manage {path.replace('-',' ')} records.</div></div><a class='btn' href='{action}'>＋ {label}</a></div>{table}"
        return module_page(request,title,path,body)
    con.close(); title=path.replace('/',' • ').replace('-',' ').title(); body=f"<div class='grid-3'><a class='ds-card' href='/school/dashboard'><b>📊 Overview</b><p>Return to the school performance dashboard.</p></a><a class='ds-card' href='/school/students'><b>🎓 Student Records</b><p>Manage enrolment, profiles and academic history.</p></a><a class='ds-card' href='/school/analysis'><b>📈 Analytics</b><p>Review subject, student and class performance.</p></a></div><div class='card'><h3>{title} workspace</h3><p>This workspace is connected to the Mabale_ICT data model. Use the related module links above to create records and review live school data.</p></div>"; return module_page(request,title,path,body)


# === DAVISCHOOL OPERATIONS COMPLETION ===
def _require_school_admin(request: Request):
    school=_school_user(request)
    role = request.session.get('role')
    accountant_preview = (
        role == 'accountant'
        and request.session.get('is_portal_preview')
        and request.session.get('preview_portal') == 'accountant'
    )
    if not school or (role not in ('school_admin','registrar','super_admin') and not accountant_preview): return None
    return school

@app.get('/school/finance', response_class=HTMLResponse)
def school_finance(request: Request):
    school=_require_school_admin(request)
    if not school: return RedirectResponse('/',303)
    con=get_db(); cur=con.cursor()
    fee=cur.execute('SELECT COALESCE(SUM(amount),0) charged,COALESCE(SUM(paid),0) paid FROM fees WHERE school_id=?',(school['id'],)).fetchone()
    exp=cur.execute('SELECT * FROM expenses WHERE school_id=? ORDER BY id DESC',(school['id'],)).fetchall()
    payments=cur.execute('SELECT fp.*,s.name student FROM fee_payments fp LEFT JOIN students s ON s.id=fp.student_id WHERE fp.school_id=? ORDER BY fp.id DESC',(school['id'],)).fetchall()
    cash=cur.execute('SELECT * FROM cashbook WHERE school_id=? ORDER BY id DESC LIMIT 100',(school['id'],)).fetchall()
    students=cur.execute('SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name',(school['id'],)).fetchall()
    expense_total=cur.execute('SELECT COALESCE(SUM(amount),0) n FROM expenses WHERE school_id=?',(school['id'],)).fetchone()['n']
    con.close()
    opts=''.join(f"<option value='{s['id']}'>{s['name']} ({s['admission_no'] or ''})</option>" for s in students)
    payrows=''.join(f"<tr><td>{p['date']}</td><td>{p['student'] or ''}</td><td>{p['amount']}</td><td>{p['reference']}</td><td>{p['method']}</td></tr>" for p in payments) or '<tr><td colspan=5>No payments.</td></tr>'
    exprows=''.join(f"<tr><td>{e['date']}</td><td>{e['category']}</td><td>{e['description']}</td><td>{e['amount']}</td><td>{e['paid_to'] or ''}</td></tr>" for e in exp) or '<tr><td colspan=5>No expenses.</td></tr>'
    cashrows=''.join(f"<tr><td>{x['date']}</td><td>{x['reference']}</td><td>{x['description']}</td><td>{x['debit']}</td><td>{x['credit']}</td></tr>" for x in cash) or '<tr><td colspan=5>No cashbook entries.</td></tr>'
    body=f"""<div class='kpis'><div class='kpi'><span>FEES CHARGED</span><b>KES {float(fee['charged'] or 0):,.2f}</b></div><div class='kpi'><span>FEES RECEIVED</span><b>KES {float(fee['paid'] or 0):,.2f}</b></div><div class='kpi'><span>FEE BALANCE</span><b>KES {float(fee['charged'] or 0)-float(fee['paid'] or 0):,.2f}</b></div><div class='kpi'><span>EXPENSES</span><b>KES {float(expense_total or 0):,.2f}</b></div></div><div class='grid-2'><div class='card'><h3>💳 Fee Payment</h3><form method='post' action='/school/finance/fee-payment'><select name='student_id' required class='input-field'>{opts}</select><input name='amount' type='number' min='0.01' step='0.01' required placeholder='Amount' class='input-field'><input name='reference' required placeholder='Receipt / reference' class='input-field'><select name='method' class='input-field'><option>Cash</option><option>Bank</option><option>Mobile Money</option><option>Cheque</option></select><button class='btn'>Save Payment</button></form></div><div class='card'><h3>💸 Expense</h3><form method='post' action='/school/finance/expense'><input name='category' required placeholder='Category' class='input-field'><input name='description' required placeholder='Description' class='input-field'><input name='amount' type='number' min='0.01' step='0.01' required placeholder='Amount' class='input-field'><input name='paid_to' placeholder='Paid to' class='input-field'><input name='voucher_no' placeholder='Voucher No.' class='input-field'><input name='date' type='date' required class='input-field'><button class='btn'>Save Expense</button></form></div></div><div class='card'><h3>🧾 Fee Payments</h3><table><tr><th>Date</th><th>Student</th><th>Amount</th><th>Reference</th><th>Method</th></tr>{payrows}</table></div><div class='card'><h3>💸 Expenses</h3><table><tr><th>Date</th><th>Category</th><th>Description</th><th>Amount</th><th>Paid To</th></tr>{exprows}</table></div><div class='card'><h3>📒 Cashbook</h3><table><tr><th>Date</th><th>Reference</th><th>Description</th><th>Debit</th><th>Credit</th></tr>{cashrows}</table></div>"""
    return module_page(request,'💰 Finance & Accounting','fees',body)

@app.post('/school/finance/fee-payment')
def school_finance_fee_payment(request:Request,student_id:int=Form(...),amount:float=Form(...),reference:str=Form(...),method:str=Form(...)):
    school=_require_school_admin(request)
    if not school or amount<=0: return RedirectResponse('/',303)
    con=get_db(); cur=con.cursor()
    if not cur.execute('SELECT id FROM students WHERE id=? AND school_id=?',(student_id,school['id'])).fetchone(): con.close(); return RedirectResponse('/school/finance',303)
    ts=datetime.now(ZoneInfo('Africa/Nairobi')).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute('INSERT INTO fee_payments(school_id,student_id,amount,reference,method,date,received_by) VALUES(?,?,?,?,?,?,?)',(school['id'],student_id,amount,reference.strip(),method,ts,request.session.get('email','')))
    remaining=amount
    for row in cur.execute('SELECT id,amount,paid FROM fees WHERE school_id=? AND student_id=? AND amount>paid ORDER BY id',(school['id'],student_id)).fetchall():
        if remaining<=0: break
        add=min(remaining,float(row['amount'] or 0)-float(row['paid'] or 0)); new_paid=float(row['paid'] or 0)+add
        cur.execute('UPDATE fees SET paid=?,status=? WHERE id=?',(new_paid,'Paid' if new_paid>=float(row['amount'] or 0) else 'Partial',row['id'])); remaining-=add
    cur.execute('INSERT INTO cashbook(school_id,date,reference,description,debit,credit,account) VALUES(?,?,?,?,?,?,?)',(school['id'],ts,reference.strip(),'Fee payment',0,amount,'Fees Receivable'))
    con.commit(); con.close(); return RedirectResponse('/school/finance',303)

@app.post('/school/finance/expense')
def school_finance_expense(request:Request,category:str=Form(...),description:str=Form(...),amount:float=Form(...),paid_to:str=Form(''),voucher_no:str=Form(''),date:str=Form(...)):
    school=_require_school_admin(request)
    if not school or amount<=0: return RedirectResponse('/',303)
    con=get_db(); cur=con.cursor(); cur.execute('INSERT INTO expenses(school_id,category,description,amount,paid_to,voucher_no,date,status) VALUES(?,?,?,?,?,?,?,?)',(school['id'],category.strip(),description.strip(),amount,paid_to.strip(),voucher_no.strip(),date,'Paid'))
    cur.execute('INSERT INTO cashbook(school_id,date,reference,description,debit,credit,account) VALUES(?,?,?,?,?,?,?)',(school['id'],date,voucher_no.strip(),'Expense: '+description,amount,0,category.strip()))
    con.commit(); con.close(); return RedirectResponse('/school/finance',303)

@app.get('/portal', response_class=HTMLResponse)
def role_portal(request:Request):
    role = request.session.get('role')
    if request.session.get("is_portal_preview") and role == "accountant":
        return RedirectResponse("/school/finance", 303)
    if request.session.get("is_portal_preview") and role == "registrar":
        return RedirectResponse("/school/dashboard", 303)
    if role not in ('teacher','parent','student'): return RedirectResponse('/',303)
    school=get_school_obj(request)
    if not school: return RedirectResponse('/',303)
    con=get_db(); cur=con.cursor(); role=request.session['role']; student_id=request.session.get('student_id'); teacher_id=request.session.get('teacher_id')
    if role=='teacher':
        t=cur.execute('SELECT * FROM teachers WHERE id=? AND school_id=?',(teacher_id,school['id'])).fetchone() if teacher_id else None
        alloc=cur.execute('SELECT ta.*,s.name subject,c.name class_name,c.stream FROM teacher_allocations ta JOIN subjects s ON s.id=ta.subject_id JOIN classes c ON c.id=ta.class_id WHERE ta.teacher_id=? AND ta.school_id=?',(teacher_id,school['id'])).fetchall() if teacher_id else []
        body=f"<div class='card'><h2>👨‍🏫 Teacher Portal</h2><p>Welcome {t['name'] if t else request.session.get('name','Teacher')}.</p><table><tr><th>Subject</th><th>Class</th><th>Stream</th></tr>"+''.join(f"<tr><td>{a['subject']}</td><td>{a['class_name']}</td><td>{a['stream'] or ''}</td></tr>" for a in alloc)+"</table><div style='margin-top:12px;display:flex;gap:8px;flex-wrap:wrap'><a class='btn' href='/school/record-marks'>✏️ Record Marks</a><a class='btn secondary' href='/app/timetable/my'>📅 My Timetable</a></div></div>"
    else:
        st=cur.execute('SELECT * FROM students WHERE id=? AND school_id=?',(student_id,school['id'])).fetchone() if student_id else None
        marks=cur.execute('SELECT sub.name subject,e.name exam,m.marks,e.term,e.year FROM marks m JOIN subjects sub ON sub.id=m.subject_id JOIN exams e ON e.id=m.exam_id WHERE m.student_id=? AND m.school_id=? ORDER BY e.year DESC,e.id DESC',(student_id,school['id'])).fetchall() if student_id else []
        fee=cur.execute('SELECT COALESCE(SUM(amount),0) expected,COALESCE(SUM(paid),0) paid FROM fees WHERE student_id=? AND school_id=?',(student_id,school['id'])).fetchone() if student_id else {'expected':0,'paid':0}
        body=f"<div class='card'><h2>🎓 {'Parent' if role=='parent' else 'Student'} Portal</h2><p>{st['name'] if st else 'Linked student account'}</p><p>Fee balance: <b>KES {float(fee['expected'] or 0)-float(fee['paid'] or 0):,.2f}</b></p><table><tr><th>Subject</th><th>Exam</th><th>Marks</th><th>Term</th></tr>"+''.join(f"<tr><td>{m['subject']}</td><td>{m['exam']}</td><td>{m['marks']}</td><td>{m['term']} {m['year']}</td></tr>" for m in marks)+"</table><div style='margin-top:12px'><a class='btn' href='/app/timetable'>📅 My Timetable</a></div></div>"
    con.close(); return module_page(request,role.title()+' Portal','dashboard',body)
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never expose database/stack-trace details to users. Keep the full
    # traceback in Render logs for diagnosis and return a stable response.
    request_id = secrets.token_hex(8)
    print(
        f"DAVISCHOOL UNHANDLED ERROR [{request_id}] "
        f"{request.method} {request.url.path}: {exc!r}",
        flush=True,
    )
    traceback.print_exc()
    if request.url.path.startswith("/api") or "application/json" in request.headers.get("accept", ""):
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "request_id": request_id},
        )
    else:
        response = HTMLResponse(
            f"<div style='font-family:system-ui;padding:30px'><h2>Something went wrong</h2>"
            f"<p>The request could not be completed.</p><p>Reference: <code>{request_id}</code></p>"
            f"<p><a href='/app'>Return to Mabale_ICT</a></p></div>",
            status_code=500,
        )
    response.headers["X-Request-ID"] = request_id
    return response

@app.exception_handler(StarletteHTTPException)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        if request.url.path.startswith("/api") or "application/json" in request.headers.get("accept",""):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return RedirectResponse("/", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})




# Compatibility POST route for the live Students form. Some deployed UI versions
# submit directly to /app/students; keep this handler in main.py so that route
# remains functional even when an older new_ui.py is cached/deployed.
@app.post("/app/students")
def main_app_students_post(request: Request, admission_no: str = Form(""), name: str = Form(""), student_name: str = Form(""), class_id: str = Form(""), gender: str = Form(""), parent_name: str = Form(""), parent_phone: str = Form(""), assessment_no: str = Form(""), guardian_name: str = Form("")):
    role = str(request.session.get("role", ""))
    if not request.session.get("email") or role not in {"school_admin", "teacher", "registrar"}:
        return RedirectResponse("/", 303)
    school = get_school_obj(request)
    if not school:
        return RedirectResponse("/", 303)
    if not _role_permission(request, "students.create"):
        return HTMLResponse("You do not have permission to create students.", 403)
    admission = admission_no.strip()
    student_name = (name or student_name).strip()
    if not student_name:
        return HTMLResponse("Full name is required.", 400)
    con = get_db()
    parent_access = None
    try:
        cur = con.cursor()
        if not admission:
            # Older Student Manager forms post to /app/students with a blank,
            # read-only admission field. Use the same configured atomic sequence
            # as the current Student Manager route instead of rejecting the POST.
            from app.new_ui import _ensure_admissions_schema, _admission_academic_year, _next_admission_number
            _ensure_admissions_schema(cur)
            admission_year = _admission_academic_year(cur, int(school["id"]))
            for _ in range(100):
                admission = _next_admission_number(cur, int(school["id"]), admission_year)
                if not cur.execute("SELECT id FROM students WHERE school_id=? AND lower(admission_no)=lower(?)", (school["id"], admission)).fetchone():
                    break
            else:
                raise RuntimeError("Could not issue a unique admission number. Review Admission Number Settings.")
        if cur.execute("SELECT id FROM students WHERE school_id=? AND lower(admission_no)=lower(?)", (school["id"], admission)).fetchone():
            return HTMLResponse("Admission number already exists. <a href='/app/students'>Back to Students</a>", 400)
        cid = int(class_id) if class_id.strip().isdigit() else None
        stream = ""
        if cid is not None:
            row = cur.execute("SELECT id,stream FROM classes WHERE id=? AND school_id=?", (cid, school["id"])).fetchone()
            if not row:
                return HTMLResponse("Invalid class selected.", 400)
            stream = str(row["stream"] or "").strip()
        _ensure_student_parent_name_column(cur)
        saved_parent_name = (parent_name or guardian_name or "").strip()
        cur.execute("INSERT INTO students(school_id,admission_no,assessment_no,name,class_id,gender,parent_name,parent_phone,stream,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (school["id"], admission, assessment_no.strip(), student_name, cid, gender.strip(), saved_parent_name, parent_phone.strip(), stream, "active"))
        student_row = cur.execute("SELECT id FROM students WHERE school_id=? AND lower(admission_no)=lower(?) ORDER BY id DESC LIMIT 1", (school["id"], admission)).fetchone()
        if student_row:
            # Explicitly persist the parent field after insertion so the register
            # always reads the same canonical value submitted by the Add Student form.
            cur.execute("UPDATE students SET parent_name=? WHERE id=? AND school_id=?",
                        (saved_parent_name, int(student_row["id"]), school["id"]))
        if student_row and parent_phone.strip():
            cur.execute("SAVEPOINT parent_access_sync")
            try:
                parent_access = _create_or_link_parent_access(cur, school["id"], int(student_row["id"]), admission, saved_parent_name, parent_phone)
            except Exception as parent_exc:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT parent_access_sync")
                    cur.execute("RELEASE SAVEPOINT parent_access_sync")
                except Exception:
                    pass
                print("DAVISCHOOL PARENT ACCESS SETUP WARNING:", repr(parent_exc), flush=True)
            else:
                cur.execute("RELEASE SAVEPOINT parent_access_sync")
        con.commit()
    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        print(f"DAVISCHOOL APP STUDENT DIRECT CREATE ERROR: {exc!r}", flush=True)
        return HTMLResponse("<h2>Student was not saved</h2><p>Please try again.</p><a href='/app/students'>Back to Students</a>", 500)
    finally:
        con.close()
    # Parent access is provisioned silently; administrators remain on the Students page.
    return RedirectResponse("/app/students", 303)

# Explicit /app student POST handlers kept in app/main.py.
@app.post("/app/students/add")
def main_app_students_add(request: Request, admission_no: str = Form(...), name: str = Form(...), class_id: str = Form(""), gender: str = Form(""), parent_name: str = Form(""), parent_phone: str = Form(""), assessment_no: str = Form(""), guardian_name: str = Form("")):
    role = str(request.session.get("role", ""))
    if not request.session.get("email") or role not in {"school_admin", "teacher", "registrar"}: return RedirectResponse("/", 303)
    school = get_school_obj(request)
    if not school: return RedirectResponse("/", 303)
    if not _role_permission(request, "students.create"): return HTMLResponse("You do not have permission to create students.", 403)
    admission, student_name = admission_no.strip(), name.strip()
    if not admission or not student_name: return HTMLResponse("Admission number and full name are required.", 400)
    con = get_db()
    parent_access = None
    try:
        cur = con.cursor()
        if cur.execute("SELECT id FROM students WHERE school_id=? AND lower(admission_no)=lower(?)", (school["id"], admission)).fetchone():
            return HTMLResponse("Admission number already exists. <a href='/app/students'>Back to Students</a>", 400)
        cid = int(class_id) if class_id.strip().isdigit() else None
        stream = ""
        if cid is not None:
            row = cur.execute("SELECT id,stream FROM classes WHERE id=? AND school_id=?", (cid, school["id"])).fetchone()
            if not row: return HTMLResponse("Invalid class selected.", 400)
            stream = str(row["stream"] or "").strip()
        _ensure_student_parent_name_column(cur)
        cur.execute("INSERT INTO students(school_id,admission_no,assessment_no,name,class_id,gender,parent_name,parent_phone,stream,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (school["id"], admission, assessment_no.strip(), student_name, cid, gender.strip(), parent_name.strip(), parent_phone.strip(), stream, "active"))
        student_row = cur.execute("SELECT id FROM students WHERE school_id=? AND lower(admission_no)=lower(?) ORDER BY id DESC LIMIT 1", (school["id"], admission)).fetchone()
        if student_row and parent_phone.strip():
            cur.execute("SAVEPOINT parent_access_sync")
            try:
                parent_access = _create_or_link_parent_access(cur, school["id"], int(student_row["id"]), admission, parent_name, parent_phone)
            except Exception as parent_exc:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT parent_access_sync")
                    cur.execute("RELEASE SAVEPOINT parent_access_sync")
                except Exception:
                    pass
                print("DAVISCHOOL PARENT ACCESS SETUP WARNING:", repr(parent_exc), flush=True)
            else:
                cur.execute("RELEASE SAVEPOINT parent_access_sync")
        # Keep the live /app/students save path in main.py PostgreSQL-safe.
        # Do not use cursor.lastrowid; the Render PostgreSQL cursor does not expose it.
        con.commit()
    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        print(f"DAVISCHOOL APP STUDENT CREATE ERROR: {exc!r}", flush=True)
        return HTMLResponse("<h2>Student was not saved</h2><p>Please try again.</p><a href='/app/students'>Back to Students</a>", 500)
    finally: con.close()
    # Parent portal account is created/linked in the background of student registration.
    return RedirectResponse("/app/students", 303)

@app.post("/app/students/edit/{student_id}")
def main_app_student_edit(request: Request, student_id: int, admission_no: str = Form(...), name: str = Form(...), assessment_no: str = Form(""), class_id: str = Form(""), gender: str = Form(""), parent_name: str = Form(""), parent_phone: str = Form(""), status: str = Form("active")):
    role = str(request.session.get("role", ""))
    if not request.session.get("email") or role not in {"school_admin", "teacher", "registrar"}: return RedirectResponse("/", 303)
    school = get_school_obj(request)
    if not school: return RedirectResponse("/", 303)
    if not _role_permission(request, "students.edit"): return HTMLResponse("You do not have permission to edit students.", 403)
    admission, student_name = admission_no.strip(), name.strip()
    if not admission or not student_name: return HTMLResponse("Admission number and full name are required.", 400)
    new_status = status.strip().lower()
    if new_status not in {"active","inactive","graduated","transferred"}: new_status = "active"
    con = get_db()
    try:
        cur = con.cursor()
        st = cur.execute("SELECT * FROM students WHERE id=? AND school_id=?", (student_id, school["id"])).fetchone()
        if not st: return HTMLResponse("Student not found.", 404)
        if cur.execute("SELECT id FROM students WHERE school_id=? AND lower(admission_no)=lower(?) AND id<>?", (school["id"], admission, student_id)).fetchone():
            return HTMLResponse("Admission number already exists.", 400)
        cid = int(class_id) if class_id.strip().isdigit() else None
        stream = ""
        if cid is not None:
            row = cur.execute("SELECT id,stream FROM classes WHERE id=? AND school_id=?", (cid, school["id"])).fetchone()
            if not row: return HTMLResponse("Invalid class selected.", 400)
            stream = str(row["stream"] or "").strip()
        _ensure_student_parent_name_column(cur)
        cur.execute("UPDATE students SET admission_no=?,assessment_no=?,name=?,class_id=?,gender=?,parent_name=?,parent_phone=?,stream=?,status=? WHERE id=? AND school_id=?",
                    (admission, assessment_no.strip(), student_name, cid, gender.strip(), parent_name.strip(), parent_phone.strip(), stream, new_status, student_id, school["id"]))
        con.commit()
    except Exception as exc:
        con.rollback(); print(f"DAVISCHOOL APP STUDENT UPDATE ERROR: {exc!r}", flush=True)
        return HTMLResponse("<h2>Student was not saved</h2><p>Please try again.</p><a href='/app/students'>Back to Students</a>", 500)
    finally: con.close()
    return RedirectResponse("/app/students", 303)



# DaviSchool unified application UI
from app.new_ui import router as new_ui_router
app.include_router(new_ui_router)

# HR workspace routes are registered after the shared school UI helpers.
from app.hr_management import router as hr_management_router
app.include_router(hr_management_router)

# Library workspace routes are registered after the shared school UI helpers.
from app.library_management import router as library_management_router
app.include_router(library_management_router)

# Transport workspace routes are registered after the shared school UI helpers.
from app.transport_management import router as transport_management_router
app.include_router(transport_management_router)
from app.inventory_management import router as inventory_management_router
app.include_router(inventory_management_router)

# Health and welfare workspace routes.
from app.health_welfare_management import router as health_welfare_management_router
app.include_router(health_welfare_management_router)

# Facilities and assets management workspace.
from app.facilities_management import router as facilities_management_router
app.include_router(facilities_management_router)

# Parent and student services workspace.
from app.parent_student_services import router as parent_student_services_router
app.include_router(parent_student_services_router)


# Disable the legacy /school interface. The new DaviSchool /app interface is the only school UI.
from app.legacy_redirect import install_legacy_school_redirect
install_legacy_school_redirect(app)


# === SUPER ADMIN PORTAL MANAGEMENT & ISOLATED PREVIEW WORKSPACE ===
def _ensure_davischool_demo_tenant():
    """Create one isolated demo tenant and minimal synthetic portal data."""
    con = get_db()
    cur = con.cursor()
    try:
        demo = cur.execute("SELECT id FROM schools WHERE email=? ORDER BY id LIMIT 1",
                           ("portal-demo@davischool.invalid",)).fetchone()
        if not demo:
            cur.execute("""INSERT INTO schools (name,email,code,location,phone,principal,school_type,status)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        ("Mabale_ICT Demonstration Environment", "portal-demo@davischool.invalid",
                         "DAVI-DEMO", "Demonstration only", "", "Mabale_ICT Platform",
                         "Demonstration", "demo"))
            demo = cur.execute("SELECT id FROM schools WHERE email=? ORDER BY id DESC LIMIT 1",
                               ("portal-demo@davischool.invalid",)).fetchone()
        demo_id = int(demo["id"])
        cur.execute("UPDATE schools SET status='demo' WHERE id=?", (demo_id,))
        klass = cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=? ORDER BY id LIMIT 1",
                            (demo_id, "GRADE 7", "DEMO")).fetchone()
        if not klass:
            cur.execute("INSERT INTO classes (school_id,name,level,stream) VALUES (?,?,?,?)",
                        (demo_id, "GRADE 7", "Junior School", "DEMO"))
            klass = cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=? ORDER BY id DESC LIMIT 1",
                                (demo_id, "GRADE 7", "DEMO")).fetchone()
        class_id = int(klass["id"])
        learner = cur.execute("SELECT id FROM students WHERE school_id=? AND admission_no=? LIMIT 1",
                              (demo_id, "DEMO-001")).fetchone()
        if not learner:
            cur.execute("""INSERT INTO students
                           (school_id,admission_no,assessment_no,name,class_id,gender,parent_phone,stream)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (demo_id, "DEMO-001", "DEMO-001", "Alex Demo Learner",
                         class_id, "Male", "0700000000", "DEMO"))
            learner = cur.execute("SELECT id FROM students WHERE school_id=? AND admission_no=? ORDER BY id DESC LIMIT 1",
                                  (demo_id, "DEMO-001")).fetchone()
        student_id = int(learner["id"])
        teacher = cur.execute("SELECT id FROM teachers WHERE school_id=? AND email=? LIMIT 1",
                              (demo_id, "teacher@davischool.invalid")).fetchone()
        if not teacher:
            cur.execute("""INSERT INTO teachers (school_id,name,email,phone,gender,role,employment_type)
                           VALUES (?,?,?,?,?,?,?)""",
                        (demo_id, "Taylor Demo Teacher", "teacher@davischool.invalid",
                         "0700000001", "Female", "Teacher", "Demonstration"))
            teacher = cur.execute("SELECT id FROM teachers WHERE school_id=? AND email=? ORDER BY id DESC LIMIT 1",
                                  (demo_id, "teacher@davischool.invalid")).fetchone()
        teacher_id = int(teacher["id"])
        subject = cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=? LIMIT 1",
                              (demo_id, "Mathematics")).fetchone()
        if not subject:
            cur.execute("INSERT INTO subjects (school_id,name,code,initial) VALUES (?,?,?,?)",
                        (demo_id, "Mathematics", "MATH", "M"))
            subject = cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=? ORDER BY id DESC LIMIT 1",
                                  (demo_id, "Mathematics")).fetchone()
        subject_id = int(subject["id"])
        exam = cur.execute("SELECT id FROM exams WHERE school_id=? AND name=? LIMIT 1",
                            (demo_id, "Demo Assessment")).fetchone()
        if not exam:
            cur.execute("INSERT INTO exams (school_id,name,term,year,exam_type) VALUES (?,?,?,?,?)",
                        (demo_id, "Demo Assessment", "Term 1", "2026", "Assessment"))
            exam = cur.execute("SELECT id FROM exams WHERE school_id=? AND name=? ORDER BY id DESC LIMIT 1",
                               (demo_id, "Demo Assessment")).fetchone()
        exam_id = int(exam["id"])
        mark = cur.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=? LIMIT 1",
                           (demo_id, student_id, subject_id, exam_id)).fetchone()
        if not mark:
            cur.execute("""INSERT INTO marks (school_id,student_id,subject_id,exam_id,class_id,marks,year,term)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (demo_id, student_id, subject_id, exam_id, class_id, 78, "2026", "Term 1"))
        allocation = cur.execute("SELECT id FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND class_id=? AND subject_id=? LIMIT 1",
                                 (demo_id, teacher_id, class_id, subject_id)).fetchone()
        if not allocation:
            cur.execute("INSERT INTO teacher_allocations (school_id,teacher_id,subject_id,class_id) VALUES (?,?,?,?)",
                        (demo_id, teacher_id, subject_id, class_id))
        try:
            cur.execute("""CREATE TABLE IF NOT EXISTS parent_student_links (
                school_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL, created_at TEXT,
                PRIMARY KEY (school_id,user_id,student_id))""")
        except Exception:
            pass
        con.commit()
        return {"school_id": demo_id, "student_id": student_id, "teacher_id": teacher_id}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@app.get("/super/portal-management", response_class=HTMLResponse)
def super_admin_portal_management(request: Request):
    if request.session.get("role") != "super_admin" or request.session.get("is_portal_preview"):
        return RedirectResponse("/", 303)
    name = escape(str(request.session.get("name") or "Super Administrator"))
    portals = [
        ("school-admin", "School Admin Portal", "SA", "The real school administration workspace and modules."),
        ("registrar", "Registrar Portal", "RG", "The real registrar workspace with school-wide access."),
        ("teacher", "Teacher Portal", "TR", "The real teacher workspace, allocations, marks entry and monitoring."),
        ("parent", "Parent Portal", "PR", "The parent-facing learner progress and school updates portal."),
        ("student", "Student Portal", "ST", "The student-facing academic records portal."),
        ("accountant", "Accountant Portal", "AC", "The finance workspace in the isolated demonstration school."),
    ]
    cards_list = []
    for key, title, icon, description in portals:
        tab_id = secrets.token_hex(16)
        ticket = _make_portal_preview_ticket(key, request.session)
        preview_url = "/super/portal-management/enter/{}?ds_tab={}&ds_tab_shared=1&ticket={}".format(key, tab_id, quote(ticket, safe=""))
        cards_list.append(
            f"""<article class="portal-card"><div class="portal-icon">{icon}</div>
            <div class="portal-copy"><h2>{title}</h2><p>{description}</p></div>
            <a class="open" target="_blank" rel="noopener" href="{preview_url}">Open independent preview →</a></article>"""
        )
    cards = "".join(cards_list)
    return HTMLResponse(f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Portal Management · Mabale_ICT</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f1f8f1;color:#203126;font-family:Arial,sans-serif}}
    .top{{background:#14532d;color:#fff;padding:17px 22px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}
    .top a{{color:#fff;text-decoration:none;font-weight:800;font-size:12px}}main{{max-width:1180px;margin:auto;padding:24px 16px}}
    .hero{{background:linear-gradient(120deg,#14532d,#237b49);color:white;border-radius:18px;padding:23px;margin-bottom:17px}}
    .hero h1{{margin:0;font-size:25px}}.hero p{{color:#d8f0dc;font-size:13px;line-height:1.6;max-width:760px}}
    .notice{{background:#e7f5eb;border:1px solid #c8e5d0;color:#245c37;border-radius:12px;padding:13px 15px;font-size:12px;line-height:1.6;margin-bottom:18px}}
    .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}
    .portal-card{{background:#fff;border:1px solid #dce9dc;border-radius:15px;padding:17px;display:flex;gap:13px;align-items:flex-start;min-width:0;flex-wrap:wrap}}
    .portal-icon{{width:44px;height:44px;border-radius:12px;background:#e7f5eb;color:#14532d;display:grid;place-items:center;font-weight:900;flex:0 0 44px}}
    .portal-copy{{flex:1;min-width:180px}}.portal-copy h2{{font-size:15px;margin:2px 0 6px}}.portal-copy p{{font-size:12px;color:#64766a;line-height:1.5;margin:0}}
    .open{{display:inline-block;background:#14532d;color:#fff;padding:10px 13px;border-radius:9px;text-decoration:none;font-size:12px;font-weight:800;margin-left:auto}}
    .foot{{margin-top:18px;color:#64766a;font-size:11px;line-height:1.6}}
    @media(max-width:680px){{main{{padding:14px 11px}}.grid{{grid-template-columns:1fr}}.hero h1{{font-size:21px}}.portal-card{{gap:10px}}}}
    </style></head><body><header class="top"><b>Mabale_ICT · Global Control Centre</b><a href="/dashboard">← Return to Global Overview</a></header>
    <main><section class="hero"><h1>Portal Management & Design Centre</h1>
    <p>Welcome, {name}. Each portal opens in its own isolated browser tab, using the real role-specific application workspace and a separate demonstration-school identity.</p></section>
    <div class="notice"><b>Protected demonstration environment</b><br>
    Each preview has its own signed-in session and synthetic demo records. Logging out, timing out or encountering an error in one preview cannot sign out the other previews or your Global Control Centre. All data-changing requests are blocked.</div>
    <section class="grid">{cards}</section>
    <p class="foot">Portal previews show the current application experience using demonstration data. Changes to application design are still made centrally in the application source and deployed through the normal release process. Preview access is not a customer account and cannot access customer school records.</p>
    </main></body></html>""")


def _make_portal_preview_ticket(portal: str, admin_session) -> str:
    """Create a short-lived signed handoff for a fresh per-tab preview session."""
    payload = {
        "portal": portal,
        "admin_user_id": int(admin_session.get("user_id") or 0),
        "admin_email": str(admin_session.get("email") or ""),
        "admin_name": str(admin_session.get("name") or "Super Administrator"),
        "expires": int(datetime.now().timestamp()) + 600,
        "nonce": secrets.token_urlsafe(12),
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return raw + "." + signature


def _read_portal_preview_ticket(ticket: str, portal: str):
    try:
        raw, supplied = str(ticket or "").rsplit(".", 1)
        expected = hmac.new(SECRET_KEY.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            return None
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if payload.get("portal") != portal or int(payload.get("expires") or 0) < int(datetime.now().timestamp()):
            return None
        if not payload.get("admin_email"):
            return None
        return payload
    except Exception:
        return None


@app.get("/super/portal-management/enter/{portal}")
def enter_super_admin_portal_preview(portal: str, request: Request, ticket: str = ""):
    allowed = {
        "school-admin": ("school_admin", "/app"),
        "registrar": ("registrar", "/app"),
        "teacher": ("teacher", "/app"),
        "parent": ("parent", "/portal"),
        "student": ("student", "/portal"),
        "accountant": ("accountant", "/school/finance"),
    }
    if portal not in allowed:
        return RedirectResponse("/super/portal-management", 303)
    handoff = _read_portal_preview_ticket(ticket, portal)
    if request.session.get("role") != "super_admin" and not handoff:
        return RedirectResponse("/", 303)
    if request.session.get("is_portal_preview"):
        return RedirectResponse("/", 303)
    try:
        demo = _ensure_davischool_demo_tenant()
    except Exception as exc:
        print("DAVISCHOOL PORTAL DEMO INITIALIZATION FAILED:", repr(exc), flush=True)
        return HTMLResponse("The isolated demo environment could not be prepared. No school data was changed. Please check the application logs.", 500)

    role, destination = allowed[portal]
    admin_user_id = (handoff or {}).get("admin_user_id", request.session.get("user_id", 0))
    admin_email = (handoff or {}).get("admin_email", request.session.get("email", ""))
    admin_name = (handoff or {}).get("admin_name", request.session.get("name", "Super Administrator"))
    request.session["_preview_admin_user_id"] = admin_user_id
    request.session["_preview_admin_email"] = admin_email
    request.session["_preview_admin_name"] = admin_name
    request.session["role"] = role
    request.session["email"] = "preview-" + portal + "@davischool.invalid"
    request.session["name"] = "Super Admin Preview"
    request.session["user_id"] = 0
    request.session["school_id"] = demo["school_id"]
    request.session["teacher_id"] = demo["teacher_id"] if role == "teacher" else None
    request.session["student_id"] = demo["student_id"] if role in ("parent", "student") else None
    request.session["is_impersonating"] = False
    request.session["is_portal_preview"] = True
    request.session["preview_portal"] = portal
    request.session["preview_school_id"] = demo["school_id"]
    con = get_db()
    try:
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        con.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",
                    (demo["school_id"], admin_email, "PORTAL_PREVIEW_ENTER",
                     "Opened isolated " + portal + " portal preview", ts))
        con.commit()
    finally:
        con.close()
    # Preserve the explicit tab handoff through this redirect. The browser controller
    # adopts the fresh tab id from ds_tab_shared before normal navigation begins.
    return RedirectResponse(destination + "?ds_tab_shared=1", 303)


@app.get("/super/portal-management/exit")
def exit_super_admin_portal_preview(request: Request):
    if request.session.get("role") not in ("school_admin","registrar","teacher","parent","student","accountant") or not request.session.get("is_portal_preview"):
        return RedirectResponse("/", 303)
    demo_id = request.session.get("preview_school_id", 0)
    admin_email = request.session.get("_preview_admin_email", "")
    con = get_db()
    try:
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        con.execute("INSERT INTO system_audit (school_id,user_email,action,details,timestamp) VALUES (?,?,?,?,?)",
                    (demo_id, admin_email, "PORTAL_PREVIEW_EXIT",
                     "Returned to Global Control Centre from portal preview", ts))
        con.commit()
    finally:
        con.close()
    request.session["role"] = "super_admin"
    request.session["school_id"] = 0
    request.session["user_id"] = request.session.pop("_preview_admin_user_id", 0)
    request.session["email"] = request.session.pop("_preview_admin_email", "")
    request.session["name"] = request.session.pop("_preview_admin_name", "Super Administrator")
    for key in ("teacher_id","student_id","is_impersonating","is_portal_preview","preview_portal","preview_school_id"):
        request.session.pop(key, None)
    return RedirectResponse("/super/portal-management", 303)

# Render every administrator timetable page inside the active DaviSchool
# application shell. The legacy module_page wrapper belongs to the retired
# blue /school interface and must not be used by the new /app/timetable routes.
def timetable_module_page(request, title, active, body, global_mode=False):
    from app.new_ui import _school_page
    return _school_page(request, title, body)

# Register the isolated timetable workspace after shared helpers exist.
register_timetable_setup_routes(app, get_db, get_school_obj, timetable_module_page)
register_timetable_builder_routes(app, get_db, get_school_obj, timetable_module_page)
register_timetable_generator_routes(app, get_db, get_school_obj, timetable_module_page)
register_timetable_view_routes(app, get_db, get_school_obj, timetable_module_page)
register_timetable_export_routes(app, get_db, get_school_obj)
register_timetable_publishing_routes(app, get_db, get_school_obj, timetable_module_page)
register_timetable_portal_routes(app, get_db)

# Install tab-scoped signed sessions around the fully configured ASGI app.
# This must wrap the app only after every route and FastAPI middleware has been registered.
app = DaviSchoolTabSessionMiddleware(
    app,
    secret_key=SECRET_KEY,
    https_only=SESSION_HTTPS_ONLY,
)