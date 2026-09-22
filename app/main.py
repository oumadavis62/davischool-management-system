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
import traceback
import threading
from starlette.middleware.sessions import SessionMiddleware
import random
from datetime import datetime
from app.schema_compat import ensure_schema_compatibility
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet, InvalidToken

BUILD_COMMIT = "MULTI_ASSESSMENT_ANALYSIS"

app = FastAPI()

# Render/Uvicorn must be able to bind the HTTP port even when PostgreSQL
# migrations take time. Database initialization therefore runs in a background
# thread instead of blocking the ASGI startup/lifespan phase.
DB_INIT_READY = False
DB_INIT_ERROR = None
DB_INIT_THREAD = None

def _initialize_database_background():
    global DB_INIT_READY, DB_INIT_ERROR
    try:
        init_db()
        init_extended_db()
        DB_INIT_READY = True
        print("DAVISCHOOL DATABASE INITIALIZATION COMPLETE", flush=True)
    except Exception as exc:
        DB_INIT_ERROR = repr(exc)
        print("DAVISCHOOL DATABASE INITIALIZATION FAILED:", DB_INIT_ERROR, flush=True)

@app.on_event("startup")
def _startup_database_initialization():
    global DB_INIT_THREAD
    DB_INIT_THREAD = threading.Thread(
        target=_initialize_database_background,
        name="davischool-db-init",
        daemon=True,
    )
    DB_INIT_THREAD.start()
    print("DAVISCHOOL DATABASE INITIALIZATION STARTED IN BACKGROUND", flush=True)

SECRET_KEY = os.environ.get("DAVISCHOOL_SECRET_KEY") or "dev-only-change-this-secret"
SESSION_HTTPS_ONLY = os.environ.get("DAVISCHOOL_HTTPS_ONLY", "0").lower() in {"1", "true", "yes"}
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=SESSION_HTTPS_ONLY, same_site="lax", max_age=60*60*12)

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
DB_PATH = os.environ.get("DAVISCHOOL_DB_PATH", "davischool.db")
REQUIRE_DATABASE = os.environ.get("DAVISCHOOL_REQUIRE_DATABASE", "0").lower() in {"1", "true", "yes"}

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
    if REQUIRE_DATABASE and not database_url:
        raise RuntimeError("DAVISCHOOL_REQUIRE_DATABASE is enabled but DATABASE_URL is not configured; refusing to use local SQLite for production data.")
    if database_url:
        from app.db import connect as pg_connect
        return pg_connect(database_url, connect_timeout=10)

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
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, status TEXT DEFAULT 'active')")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, assessment_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_phone TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT, initial TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY, school_id INTEGER, term_name TEXT, year TEXT, start_date TEXT, end_date TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, email TEXT, phone TEXT, tsc_no TEXT, gender TEXT, id_no TEXT, role TEXT, employment_type TEXT)")
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
    # Remove the obsolete legacy super-admin account once the current
    # configured super-admin has been established. This keeps the platform
    # user list from showing a stale duplicate admin account.
    if SUPER_ADMIN.lower() != "oumadavis62@gmail.com".lower():
        cur.execute("DELETE FROM users WHERE lower(email)=lower(?) AND lower(email)<>lower(?)",
                    ("oumadavis62@gmail.com", SUPER_ADMIN))
    # Remove the obsolete legacy "admin" account. The current platform
    # administrator is represented by the configured super_admin account.
    cur.execute("DELETE FROM users WHERE lower(role)=lower(?)", ("admin",))
    con.commit(); con.close()
def init_extended_db():
    con = get_db(); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS timetable (id INTEGER PRIMARY KEY, school_id INTEGER, day TEXT, start_time TEXT, end_time TEXT, class_name TEXT, stream TEXT, subject TEXT, teacher TEXT, room TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, amount REAL, paid REAL DEFAULT 0, description TEXT, due_date TEXT, status TEXT DEFAULT 'Pending')")
    cur.execute("CREATE TABLE IF NOT EXISTS announcements (id INTEGER PRIMARY KEY, school_id INTEGER, title TEXT, message TEXT, audience TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS sms_logs (id INTEGER PRIMARY KEY, school_id INTEGER, recipient TEXT, message TEXT, status TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS roles_permissions (id INTEGER PRIMARY KEY, school_id INTEGER, role TEXT, permission TEXT, enabled INTEGER DEFAULT 1)")
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
    if status not in ("active", "enabled"):
        return None
    return s

def generate_unique_password(name):
    p = "".join([c for c in name.upper() if c.isalpha()])[:4]
    if len(p)<3: p="SCH"
    return f"{p}@{random.randint(1000,9999)}!"

def header_html(initials, name, email):
    return f"""<style>.do-avatar{{width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #e2e8f0}}.dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#0f172a;color:white}}</style><div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px;color:#64748b'>{name} • Super Admin</div></div><div style='position:relative'><div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div><div id='profileDropdown' style='display:none;position:absolute;right:0;top:44px;background:white;border:1px solid #e2e8f0;border-radius:12px;width:220px;box-shadow:0 10px 25px rgba(0,0,0,0.12);z-index:1000;overflow:hidden'><div style='padding:14px;border-bottom:1px solid #f1f5f9;background:#f8fafc'><div style='font-weight:700;font-size:13px'>{name}</div><div style='font-size:11px;color:#64748b'>{email}</div></div><a href='/super/global-control/dashboard' class='dropdown-item' style='color:#0f172a'>🌍 Global Control</a><a href='/logout' class='dropdown-item' style='color:#dc2626'>🚪 Logout</a></div></div></div><script>function toggleProfileMenu(){{let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none';}}</script>"""

def school_header(school, name, active="dashboard", is_impersonating=False):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    academic_pages = ["dean-settings","exams","marks","set-marks","subject-allocation","record-marks","edit-marks","marksheets","marks-status","analysis","spreadsheet","sba"]
    comm_pages = ["sms","communication","announcements","bulk-sms"]
    system_pages = ["system-settings","school-profile","system-classes","user-management","roles-permissions","database-backup","system-audit","integrations","billing-payments","my-profile","user-manual"]
    is_academic_active = active in academic_pages or active.startswith("marks") or active.startswith("set-marks")
    is_comm_active = active in comm_pages
    is_system_active = active in system_pages or str(active).startswith("system-settings")
    acad_display = "block" if is_academic_active else "none"
    comm_display = "block" if is_comm_active else "none"
    sys_display = "block" if is_system_active else "none"
    acad_arrow = "⌃" if is_academic_active else "⌄"
    comm_arrow = "⌃" if is_comm_active else "⌄"
    sys_arrow = "⌃" if is_system_active else "⌄"
    acad_bg = "background:#0f172a;color:white" if is_academic_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    comm_bg = "background:#0f172a;color:white" if is_comm_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    sys_bg = "background:#0f172a;color:white" if is_system_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    def nav(link, icon, label):
        is_active = "background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569;background:transparent"
        return f"<a href='/school/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active}'>{icon} {label}</a>"
    def sub_nav(link, icon, label):
        is_sel = "background:#e2e8f0;color:#0f172a;font-weight:800;border-radius:8px" if active==link else "color:#475569"
        return f"<a href='/school/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:2px;{is_sel}'>{icon} {label}</a>"
    banner = f"""<div style='background:#f59e0b;color:#0f172a;padding:8px 20px;text-align:center;font-weight:800;font-size:12px'>⚠️ Viewing as {school['name']} — <a href='/super/back-to-admin' style='background:#0f172a;color:white;padding:6px 12px;border-radius:8px;text-decoration:none;font-size:11px'>🔙 Back to Super Admin</a></div>""" if is_impersonating else ""
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 1"); notice = cur.fetchone(); con.close()
    notice_banner = f"""<div style='background:#0f172a;color:white;padding:8px 20px;text-align:center;font-size:12px'>📢 {notice['message']}</div>""" if notice else ""
    return f"""<style>.nav-item:hover{{background:#f1f5f9!important;color:#0f172a!important}}.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.section-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:800;margin-bottom:4px}}.academic-header{{ {acad_bg} }}.comm-header{{ {comm_bg} }}.system-header{{ {sys_bg} }}.section-header:hover{{background:#f1f5f9!important}}</style><div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20].upper()}</b><div style='font-size:10px;color:#64748b'>🔑 {school['code']} | {school['location']}</div></div></div></div>{nav('dashboard','📊','School Overview')}{nav('students','🎓','Students Manager')}{nav('classes','🏫','Classes & Streams')}<div style='margin-bottom:4px'><div class='section-header academic-header' onclick='toggleAcademic()'><span>📖 Academic Manager</span><span id='academicArrow'>{acad_arrow}</span></div><div id='academicDropdown' style='display:{acad_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('dean-settings','⚙️','Dean Settings')}{sub_nav('exams','🔧','Exam Settings')}{sub_nav('set-marks','📄','Set Marks')}{sub_nav('subject-allocation','📋','Subject Allocation')}{sub_nav('record-marks','✏️','Record Marks')}{sub_nav('edit-marks','📄','Edit Marks')}{sub_nav('marksheets','☰','Marks Status')}{sub_nav('analysis','📊','Exam Analysis')}{sub_nav('spreadsheet','📄','Spreadsheet')}{sub_nav('sba','📋','SBA (KNEC CBA)')}{sub_nav('academics','📚','Academics Workspace')}{sub_nav('terms','📅','Academic Terms')}{sub_nav('exams/new','➕','Add Examination')}{sub_nav('report-cards','📄','Report Cards')}</div></div>{nav('teachers','👨‍🏫','Staff Manager')}{nav('timetable','🗓️','Smart Timetable')}{nav('attendance','🗓️','Attendance')}{nav('fees','💰','Fees & Finance')}<div style='margin-bottom:4px'><div class='section-header comm-header' onclick='toggleComm()'><span>💬 Communication</span><span id='commArrow'>{comm_arrow}</span></div><div id='commDropdown' style='display:{comm_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('sms','💬','Bulk SMS Parents')}{sub_nav('communication','📢','Announcements')}</div></div><div style='margin-bottom:4px;margin-top:6px'><div class='section-header system-header' onclick='toggleSystem()'><span>⚙️ System Settings</span><span id='systemArrow'>{sys_arrow}</span></div><div id='systemDropdown' style='display:{sys_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('system-settings/school-profile','🏢','School Profile')}{sub_nav('system-settings/classes','🏫','Classes')}{sub_nav('system-settings/user-management','👤+','User Management')}{sub_nav('system-settings/roles-permissions','🛡️','Roles & Permissi...')}{sub_nav('system-settings/database-backup','💾','Database Backup')}{sub_nav('system-settings/system-audit','📈','System Audit')}{sub_nav('system-settings/integrations','🔌','Integrations')}{sub_nav('system-settings/billing-payments','💳','Billing & Payments')}</div></div>{nav('my-profile','👤','My Profile')}<div style='margin-top:12px;padding-top:12px;border-top:1px solid #f1f5f9'><div style='font-size:11px;color:#94a3b8;font-weight:700;margin-bottom:8px'>Help</div>{nav('user-manual','❓','User Manual')}<div style='margin-top:12px;padding:10px;background:#f8fafc;border-radius:10px;border:1px solid #f1f5f9'><div style='font-size:12px;font-weight:700'>{name}</div><div style='font-size:10px;color:#64748b'>{school['email']}</div><div style='margin-top:8px;font-size:11px'>🌤️ 24°C<br><span style='color:#64748b'>Mostly cloudy</span></div></div></div><div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/logout' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'>{banner}{notice_banner}<div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>{school['name']} (Code: {school['code']})</b></div><div style='display:flex;align-items:center;gap:12px'><div style='width:28px;height:28px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px'>{initials}</div><div style='font-size:11px'><b>{name}</b></div></div></div><script>function toggleAcademic(){{let d=document.getElementById('academicDropdown'); let a=document.getElementById('academicArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}function toggleComm(){{let d=document.getElementById('commDropdown'); let a=document.getElementById('commArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}function toggleSystem(){{let d=document.getElementById('systemDropdown'); let a=document.getElementById('systemArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}</script>"""

def global_header(name, active="dashboard"):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    academic_pages = ["dean-settings","exams","marks","set-marks","subject-allocation","record-marks","edit-marks","marksheets","marks-status","analysis","spreadsheet","sba"]
    comm_pages = ["sms","communication","announcements"]
    system_pages = ["system-settings","school-profile","system-classes","user-management","roles-permissions","database-backup","system-audit","integrations","billing-payments","my-profile","user-manual"]
    is_academic_active = active in academic_pages or active.startswith("marks") or active.startswith("set-marks")
    is_comm_active = active in comm_pages
    is_system_active = active in system_pages or str(active).startswith("system-settings")
    acad_display = "block" if is_academic_active else "none"
    comm_display = "block" if is_comm_active else "none"
    sys_display = "block" if is_system_active else "none"
    acad_arrow = "⌃" if is_academic_active else "⌄"
    comm_arrow = "⌃" if is_comm_active else "⌄"
    sys_arrow = "⌃" if is_system_active else "⌄"
    acad_bg = "background:#0f172a;color:white" if is_academic_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    comm_bg = "background:#0f172a;color:white" if is_comm_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    sys_bg = "background:#0f172a;color:white" if is_system_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    def nav(link, icon, label):
        is_active = "background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569;background:transparent"
        return f"<a href='/super/global-control/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active}'>{icon} {label}</a>"
    def sub_nav(link, icon, label):
        is_sel = "background:#e2e8f0;color:#0f172a;font-weight:800;border-radius:8px" if active==link else "color:#475569"
        return f"<a href='/super/global-control/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:2px;{is_sel}'>{icon} {label}</a>"
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 1"); notice = cur.fetchone(); con.close()
    notice_banner = f"""<div style='background:#0f172a;color:white;padding:8px 20px;text-align:center;font-size:12px'>📢 {notice['message']}</div>""" if notice else ""
    return f"""<style>.nav-item:hover{{background:#f1f5f9!important;color:#0f172a!important}}.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.section-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:800;margin-bottom:4px}}.academic-header{{ {acad_bg} }}.comm-header{{ {comm_bg} }}.system-header{{ {sys_bg} }}.section-header:hover{{background:#f1f5f9!important}}</style><div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🌍</div><div><b style='font-size:13px'>GLOBAL CONTROL</b><div style='font-size:10px;color:#64748b'>ALL SCHOOLS • Automatic</div></div></div></div>{nav('dashboard','📊','School Overview')}{nav('students','🎓','Students Manager')}{nav('classes','🏫','Classes & Streams')}<div style='margin-bottom:4px'><div class='section-header academic-header' onclick='toggleAcademic()'><span>📖 Academic Manager</span><span id='academicArrow'>{acad_arrow}</span></div><div id='academicDropdown' style='display:{acad_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('dean-settings','⚙️','Dean Settings')}{sub_nav('exams','🔧','Exam Settings')}{sub_nav('set-marks','📄','Set Marks')}{sub_nav('subject-allocation','📋','Subject Allocation')}{sub_nav('record-marks','✏️','Record Marks')}{sub_nav('edit-marks','📄','Edit Marks')}{sub_nav('marksheets','☰','Marks Status')}{sub_nav('analysis','📊','Exam Analysis')}{sub_nav('spreadsheet','📄','Spreadsheet')}{sub_nav('sba','📋','SBA (KNEC CBA)')}{sub_nav('report-cards','📄','Report Cards')}</div></div>{nav('teachers','👨‍🏫','Staff Manager')}{nav('timetable','🗓️','Smart Timetable')}{nav('attendance','🗓️','Attendance')}{nav('fees','💰','Fees & Finance')}<div style='margin-bottom:4px'><div class='section-header comm-header' onclick='toggleComm()'><span>💬 Communication</span><span id='commArrow'>{comm_arrow}</span></div><div id='commDropdown' style='display:{comm_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('sms','💬','Bulk SMS Parents')}{sub_nav('communication','📢','Announcements')}</div></div><div style='margin-bottom:4px;margin-top:6px'><div class='section-header system-header' onclick='toggleSystem()'><span>⚙️ System Settings</span><span id='systemArrow'>{sys_arrow}</span></div><div id='systemDropdown' style='display:{sys_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('system-settings/school-profile','🏢','School Profile')}{sub_nav('system-settings/classes','🏫','Classes')}{sub_nav('system-settings/user-management','👤+','User Management')}{sub_nav('system-settings/roles-permissions','🛡️','Roles & Permissi...')}{sub_nav('system-settings/database-backup','💾','Database Backup')}{sub_nav('system-settings/system-audit','📈','System Audit')}{sub_nav('system-settings/integrations','🔌','Integrations')}{sub_nav('system-settings/billing-payments','💳','Billing & Payments')}</div></div>{nav('my-profile','👤','My Profile')}<div style='margin-top:12px;padding-top:12px;border-top:1px solid #f1f5f9'><div style='font-size:11px;color:#94a3b8;font-weight:700;margin-bottom:8px'>Help</div>{nav('user-manual','❓','User Manual')}<div style='margin-top:14px;padding:10px;background:#f8fafc;border-radius:10px;border:1px solid #f1f5f9'><div style='display:flex;gap:8px;align-items:center'><div style='width:28px;height:28px;background:#0f172a;color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800'>DO</div><div><div style='font-size:12px;font-weight:800'>{name}</div><div style='font-size:10px;color:#64748b'>Super Admin</div></div></div><div style='margin-top:10px;font-size:12px'>🌤️ 24°C<br><span style='color:#64748b'>Mostly cloudy</span></div></div></div><div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/dashboard' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#0f172a;background:#f8fafc;font-weight:700'>⬅️ Back to Super Admin</a><a href='/logout' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'>{notice_banner}<div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>GLOBAL CONTROL (ALL SCHOOLS)</b><div style='font-size:10px;color:#64748b'>Any change here updates all schools instantly</div></div><div style='display:flex;align-items:center;gap:12px'><div style='width:28px;height:28px;background:#0f172a;color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px'>{initials}</div><div style='font-size:11px'><b>{name}</b> <span style="background:#0f172a;color:white;padding:2px 6px;border-radius:6px;font-size:9px">SUPER</span></div></div></div><script>function toggleAcademic(){{let d=document.getElementById('academicDropdown'); let a=document.getElementById('academicArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}function toggleComm(){{let d=document.getElementById('commDropdown'); let a=document.getElementById('commArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}function toggleSystem(){{let d=document.getElementById('systemDropdown'); let a=document.getElementById('systemArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}</script>"""

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
        rows_html += f"""<tr class='staff-row' data-role="{(t['role'] or '').lower()}" data-gender="{(t['gender'] or '').lower()}" data-employment="{(t['employment_type'] or ('teaching' if (t['role'] or '').lower() in teaching_roles else 'non-teaching')).lower()}" data-search="{(t['name'] or '').lower()} {(t['id_no'] or '').lower()} {(t['email'] or '').lower()} {(t['tsc_no'] or '').lower()}"><td style='padding:14px 12px;font-size:13px'>{i}</td><td style='padding:14px 12px;font-size:13px;font-weight:600'>{t['id_no'] or t['tsc_no'] or '—'}</td><td style='padding:14px 12px;font-size:13px;font-weight:700'>{t['name']}</td><td style='padding:14px 12px;font-size:13px'>{t['gender'] or '—'}</td><td style='padding:14px 12px;font-size:13px'><span style='background:#f1f5f9;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700'>{t['role'] or 'Teacher'}</span></td><td style='padding:14px 12px;font-size:13px'>{t['phone'] or '—'}</td><td style='padding:14px 12px;font-size:13px;color:#475569'>{t['email'] or '—'}</td><td style='padding:14px 12px'><a href='{delete_url}' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:8px;text-decoration:none;font-size:12px'>🗑️</a></td></tr>"""
    if not rows_html:
        rows_html = "<tr><td colspan='8' style='padding:40px;text-align:center;color:#94a3b8'>No staff yet</td></tr>"
    add_action = "/super/global-control/teachers/add" if is_global else "/school/teachers/add"
    return f"""<style>.staff-card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px;display:flex;justify-content:space-between;align-items:center}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;min-width:140px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-staff-btn{{background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:20px}}.modal.active{{display:flex}}</style><div style='padding:22px;max-width:1500px;margin:auto'><div style='margin-bottom:18px'><h1 style='margin:0;font-size:28px;font-weight:900'>Staff</h1><p style='margin:6px 0 0;color:#64748b;font-size:14px'>Manage staff records — {school_name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px'><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Total Staff</div><div style='font-size:28px;font-weight:900;margin-top:8px'>{total}</div></div></div><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Male / Female</div><div style='font-size:24px;font-weight:900;margin-top:8px'><span style='color:#2563eb'>{male}</span> / <span style='color:#db2777'>{female}</span></div></div></div><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Teaching / Non-Teaching</div><div style='font-size:24px;font-weight:900;margin-top:8px'><span style='color:#059669'>{teaching}</span> / <span style='color:#ea580c'>{non_teaching}</span></div></div></div><div class='staff-card' style='flex-direction:column;align-items:flex-start'><div style='font-size:13px;color:#64748b;font-weight:600;margin-bottom:10px'>By Role</div><div>{role_pills}</div></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center'><input id='searchInput' onkeyup='filterStaff()' placeholder='Search name, ID, email.' style='padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;min-width:200px'><select id='roleFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Roles</option><option value='administrator'>Administrator</option><option value='principal'>Principal</option><option value='deputy principal'>Deputy Principal</option><option value='classteacher'>Classteacher</option><option value='teacher'>Teacher</option></select><select id='genderFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Gender</option><option value='male'>Male</option><option value='female'>Female</option></select><select id='employmentFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Employment</option><option value='teaching'>Teaching</option><option value='non-teaching'>Non-Teaching</option></select><button class='action-btn' onclick='exportCSV()'>📄 CSV</button><button class='action-btn' onclick='window.print()'>⬇️ PDF</button><button class='add-staff-btn' onclick='openModal()'>+ Add Staff</button></div><div style='overflow:auto;max-height:65vh'><table id='staffTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:12px;color:#64748b;border-top:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9'><th style='padding:12px'>#</th><th style='padding:12px'>NATIONAL ID</th><th style='padding:12px'>NAME</th><th style='padding:12px'>GENDER</th><th style='padding:12px'>ROLE</th><th style='padding:12px'>PHONE</th><th style='padding:12px'>EMAIL</th><th style='padding:12px'>ACTIONS</th></tr></thead><tbody>{rows_html}</tbody></table></div></div></div><div id='addStaffModal' class='modal'><div style='background:white;border-radius:16px;width:520px;max-width:95%;max-height:90vh;overflow:auto'><div style='padding:20px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>➕ Add Staff</b><span onclick='closeModal()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_action}' style='padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:12px'><div style='grid-column:span 2'><input name='name' required placeholder='Full Name *' class='input-field'></div><div><input name='id_no' required placeholder='National ID *' class='input-field'></div><div><input name='tsc_no' placeholder='TSC No' class='input-field'></div><div><select name='gender' required class='input-field'><option value='Male'>Male</option><option value='Female'>Female</option></select></div><div><select name='role' required class='input-field'><option value='Teacher'>Teacher</option><option value='Classteacher'>Classteacher</option><option value='Principal'>Principal</option><option value='Deputy Principal'>Deputy Principal</option><option value='Administrator'>Administrator</option></select></div><div><select name='employment_type' required class='input-field'><option value='Teaching'>Teaching</option><option value='Non-Teaching'>Non-Teaching</option></select></div><div><input name='phone' required placeholder='Phone *' class='input-field'></div><div style='grid-column:span 2'><input name='email' placeholder='Email' class='input-field'></div><div style='grid-column:span 2'><button class='add-btn'>➕ Add Staff</button></div></form></div></div><script>function openModal(){{document.getElementById('addStaffModal').classList.add('active');}}function closeModal(){{document.getElementById('addStaffModal').classList.remove('active');}}function filterStaff(){{let s=document.getElementById('searchInput').value.toLowerCase();let r=document.getElementById('roleFilter').value.toLowerCase();let g=document.getElementById('genderFilter').value.toLowerCase();let e=document.getElementById('employmentFilter').value.toLowerCase();document.querySelectorAll('.staff-row').forEach(row=>{{let ok=row.getAttribute('data-search').includes(s);if(r!=='all'&&!row.getAttribute('data-role').includes(r))ok=false;if(g!=='all'&&!row.getAttribute('data-gender').includes(g))ok=false;if(e!=='all'&&!row.getAttribute('data-employment').includes(e))ok=false;row.style.display=ok?'':'none';}});}}function exportCSV(){{let rows=document.querySelectorAll('#staffTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i<7)d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}});csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='staff_{school_name}.csv';a.click();}}</script>"""

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
    return f"""<style>.stu-card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px;display:flex;justify-content:space-between;align-items:center}}.filter-select{{padding:9px 11px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:12px;min-width:130px}}.action-btn{{padding:9px 12px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:12px;font-weight:600;cursor:pointer}}.add-pupil-btn{{background:#0f172a;color:white;padding:11px 16px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div style='margin-bottom:16px'><h1 style='margin:0;font-size:26px;font-weight:900'>Students Manager</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage pupils — {school_name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px'><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Total Students</div><div style='font-size:26px;font-weight:900;margin-top:6px'>{total}</div></div></div><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Male / Female</div><div style='font-size:22px;font-weight:900;margin-top:6px'><span style='color:#2563eb'>{male}</span> / <span style='color:#db2777'>{female}</span></div></div></div><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Boarding / Day</div><div style='font-size:22px;font-weight:900;margin-top:6px'><span style='color:#059669'>{boarding}</span> / <span style='color:#ea580c'>{day}</span></div></div></div><div class='stu-card' style='flex-direction:column;align-items:flex-start'><div style='font-size:12px;color:#64748b;font-weight:600;margin-bottom:8px'>By Class</div><div style='display:flex;flex-wrap:wrap'>{class_pills}</div></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;border-bottom:1px solid #f1f5f9'><div style='display:flex;align-items:center;gap:8px'><span style='font-size:12px;color:#64748b'>Show</span><select id='perPage' class='filter-select' style='min-width:70px' onchange='filterStu()'><option value='10'>10</option><option value='25'>25</option><option value='50'>50</option><option value='100'>100</option><option value='1000'>All</option></select><span style='font-size:12px;color:#64748b'>items</span></div><div style='display:flex;gap:8px;flex-wrap:wrap'><button class='add-pupil-btn' onclick='openStuModal()'>+ Admit Pupil</button></div></div><div style='padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:9px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='stuSearch' onkeyup='filterStu()' placeholder='Search name, ADM, guardian' style='padding:9px 12px 9px 30px;border:1px solid #e2e8f0;border-radius:10px;font-size:12px;min-width:200px'></div><select id='classFilter' class='filter-select' onchange='filterStu()'>{class_filter_opts}</select><select id='genderFilter' class='filter-select' onchange='filterStu()'><option value='all'>All Gender</option><option value='male'>Male</option><option value='female'>Female</option></select><select id='categoryFilter' class='filter-select' onchange='filterStu()'><option value='all'>All Category</option><option value='day'>Day</option><option value='boarding'>Boarding</option></select><button class='action-btn' onclick='exportStuCSV()'>📄 CSV</button><button class='action-btn' onclick='exportPDF()'>⬇️ PDF</button><button class='action-btn' onclick='exportKemis()'>📤 KEMIS Export</button></div><div style='overflow:auto;max-height:68vh'><table id='stuTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-top:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9'><th style='padding:11px 10px'>#</th><th style='padding:11px 10px'>ADM NO</th><th style='padding:11px 10px'>NAME</th><th style='padding:11px 10px'>GENDER</th><th style='padding:11px 10px'>CLASS</th><th style='padding:11px 10px'>CATEGORY</th><th style='padding:11px 10px'>GUARDIAN</th><th style='padding:11px 10px'>PHONE</th><th style='padding:11px 10px'>ACTIONS</th></tr></thead><tbody>{rows_html}</tbody></table></div></div></div><div id='stuModal' class='modal'><div style='background:white;border-radius:16px;width:560px;max-width:96%;max-height:92vh;overflow:auto'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center'><b>➕ Admit Pupil — {school_name}</b><span onclick='closeStuModal()' style='cursor:pointer;font-size:20px'>✕</span></div><form method='post' action='{add_action}' style='padding:18px;display:grid;grid-template-columns:1fr 1fr;gap:12px'><div><label style='font-size:11px;font-weight:700'>🆔 Admission No *</label><input name='admission_no' required placeholder='e.g. 1001' class='input-field'></div><div><label style='font-size:11px;font-weight:700'>📝 Assessment No</label><input name='assessment_no' placeholder='KEMIS' class='input-field'></div><div style='grid-column:span 2'><label style='font-size:11px;font-weight:700'>👤 Full Name *</label><input name='student_name' required placeholder='Full Name *' class='input-field'></div><div><label style='font-size:11px;font-weight:700'>🏫 Class *</label><select name='class_id' required class='input-field'><option value=''>Select Class *</option>{class_opts_form}</select></div><div><label style='font-size:11px;font-weight:700'>⚧️ Gender *</label><select name='gender' required class='input-field'><option value='Male'>Male</option><option value='Female'>Female</option></select></div><div><label style='font-size:11px;font-weight:700'>🏠 Category *</label><select name='category' required class='input-field'><option value='Day'>Day</option><option value='Boarding'>Boarding</option></select></div><div><label style='font-size:11px;font-weight:700'>👨‍👩‍👧 Guardian Name</label><input name='guardian_name' placeholder='Guardian Name' class='input-field'></div><div style='grid-column:span 2'><label style='font-size:11px;font-weight:700'>📞 Guardian Phone</label><input name='parent_phone' placeholder='Phone' class='input-field'></div><div style='grid-column:span 2;margin-top:6px'><button class='add-btn'>✅ Admit Pupil</button></div></form></div></div><script>function openStuModal(){{document.getElementById('stuModal').classList.add('active');}}function closeStuModal(){{document.getElementById('stuModal').classList.remove('active');}}function filterStu(){{let q=document.getElementById('stuSearch').value.toLowerCase();let cf=document.getElementById('classFilter').value.toLowerCase();let gf=document.getElementById('genderFilter').value.toLowerCase();let catf=document.getElementById('categoryFilter').value.toLowerCase();let per=parseInt(document.getElementById('perPage').value);let rows=document.querySelectorAll('.stu-row');let vis=0;rows.forEach(r=>{{let ok=true;if(q&&!r.getAttribute('data-search').includes(q))ok=false;if(cf!=='all'&&!r.getAttribute('data-class').includes(cf))ok=false;if(gf!=='all'&&!r.getAttribute('data-gender').includes(gf))ok=false;if(catf!=='all'&&!r.getAttribute('data-category').includes(catf))ok=false;if(ok){{vis++;r.style.display=(per>=1000||vis<=per)?'':'none';}} else {{r.style.display='none';}}}});}}function exportStuCSV(){{let rows=document.querySelectorAll('#stuTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i<8)d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}});if(d.length)csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='students_{school_name}.csv';a.click();}}function exportKemis(){{let rows=document.querySelectorAll('.stu-row');let out=[['ADM_NO','NAME','GENDER','CLASS','CATEGORY','GUARDIAN','PHONE'].join(',')];rows.forEach(r=>{{if(r.style.display==='none')return;let tds=r.querySelectorAll('td');let vals=[tds[1].innerText,tds[2].innerText,tds[3].innerText,tds[4].innerText,tds[5].innerText,tds[6].innerText,tds[7].innerText].map(v=>'\"'+v.replace(/\"/g,'\"\"')+'\"');out.push(vals.join(','));}});let b=new Blob([out.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='KEMIS_{school_name}.csv';a.click();}}function exportPDF(){{window.print();}}</script>"""

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
    return f"""<style>.dean-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden}}.dean-tab{{padding:10px 16px;border-radius:10px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid transparent;display:inline-flex;align-items:center;gap:6px}}.dean-tab.active{{background:#0f172a;color:white}}.dean-tab:not(.active){{background:#f8fafc;color:#475569;border:1px solid #e2e8f0}}.filter-input{{padding:10px 12px 10px 34px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;width:220px}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-term-btn{{background:#0f172a;color:white;padding:10px 16px;border:none;border-radius:12px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1450px;margin:auto'><div style='margin-bottom:14px'><h1 style='margin:0;font-size:26px;font-weight:900;letter-spacing:-0.5px'>Dean Settings</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage terms, subjects, teacher allocation & promotions</p></div><div class='dean-card'><div style='padding:14px 16px;display:flex;gap:8px;border-bottom:1px solid #f1f5f9;flex-wrap:wrap'><div onclick="switchTab('terms')" id='tab-terms' class='dean-tab {"active" if active_tab=="terms" else ""}'>📅 Terms</div><div onclick="switchTab('subjects')" id='tab-subjects' class='dean-tab {"active" if active_tab=="subjects" else ""}'>📖 Subjects</div><div onclick="switchTab('allocation')" id='tab-allocation' class='dean-tab {"active" if active_tab=="allocation" else ""}'>👥 Teacher Allocation</div><div onclick="switchTab('promote')" id='tab-promote' class='dean-tab {"active" if active_tab=="promote" else ""}'>↗️ Promote</div></div><div id='panel-terms' style='display:{"block" if active_tab=="terms" else "none"}'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='termSearch' onkeyup='filterTerms()' placeholder='Search terms...' class='filter-input'></div><select id='yearFilter' class='filter-select' onchange='filterTerms()'>{year_opts}</select></div><div style='display:flex;gap:8px'><button class='action-btn' onclick='downloadTerms()'>⬇️ Download</button><button class='add-term-btn' onclick='openAddTerm()'>+ Add Term</button></div></div><div style='overflow:auto;max-height:60vh'><table id='termsTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px 12px'><input type='checkbox'></th><th style='padding:12px'>#</th><th style='padding:12px'>TERM ↕️</th><th style='padding:12px'>YEAR ↕️</th><th style='padding:12px'>START DATE ↕️</th><th style='padding:12px'>END DATE ↕️</th><th style='padding:12px;text-align:right'>ACTIONS</th></tr></thead><tbody>{term_rows}</tbody></table></div></div><div id='panel-subjects' style='display:{"block" if active_tab=="subjects" else "none"}'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='subjSearch' onkeyup='filterSubjects()' placeholder='Search subjects...' class='filter-input'></div></div><div style='display:flex;gap:8px'><button class='add-term-btn' onclick='openAddSubject()'>+ Add Subject</button></div></div><div style='overflow:auto;max-height:60vh'><table style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px'><input type='checkbox'></th><th style='padding:12px'>#</th><th style='padding:12px'>NAME</th><th style='padding:12px'>CODE</th><th style='padding:12px'>INITIAL</th><th style='padding:12px'>ACTIONS</th></tr></thead><tbody>{subj_rows}</tbody></table></div></div><div id='panel-allocation' style='display:{"block" if active_tab=="allocation" else "none"}'><div style='padding:16px;display:grid;grid-template-columns:320px 1fr;gap:16px'><div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;height:fit-content'><b style='font-size:13px'>📌 Allocate Teacher</b><form method='post' action='{alloc_action}' style='margin-top:10px'><select name='teacher_id' required class='input-field'><option value=''>Select Teacher *</option>{t_opts}</select><select name='subject_id' required class='input-field'><option value=''>Select Subject *</option>{s_opts}</select><select name='class_id' required class='input-field'><option value=''>Select Class *</option>{c_opts}</select><button class='add-btn' style='margin-top:10px'>Allocate</button></form></div><div style='background:white;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden'><div style='padding:12px 14px;border-bottom:1px solid #f1f5f9'><b>Allocations ({len(allocations)})</b></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>TEACHER</th><th>SUBJECT</th><th>CLASS</th><th>ACTION</th></tr></thead><tbody>{alloc_rows}</tbody></table></div></div></div><div id='panel-promote' style='display:{"block" if active_tab=="promote" else "none"}'><div style='padding:20px;max-width:600px'><div style='background:#fffbeb;border:1px solid #fde68a;padding:12px;border-radius:10px;margin-bottom:16px;font-size:13px'>⚠️ Promotion will move all students from source class to destination class. This action is recorded.</div><form method='post' action='{promote_action}' style='display:grid;gap:12px'><div><label style='font-size:12px;font-weight:700'>From Class *</label><select name='from_class' required class='input-field'><option value=''>Select Source Class *</option>{class_options_promote}</select></div><div><label style='font-size:12px;font-weight:700'>To Class *</label><select name='to_class' required class='input-field'><option value=''>Select Destination Class *</option>{class_options_promote}</select></div><button class='add-btn'>↗️ Promote Students</button></form></div></div></div></div><div id='addTermModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Term</b><span onclick='closeAddTerm()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_term_action}' style='padding:18px;display:grid;gap:10px'><select name='term_name' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='Year e.g. 2026' class='input-field'><label style='font-size:11px;font-weight:700'>Start Date</label><input name='start_date' type='date' required class='input-field'><label style='font-size:11px;font-weight:700'>End Date</label><input name='end_date' type='date' required class='input-field'><button class='add-btn'>Add Term</button></form></div></div><div id='editTermModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>✏️ Edit Term</b><span onclick='closeEditTerm()' style='cursor:pointer'>✕</span></div><form id='editTermForm' method='post' style='padding:18px;display:grid;gap:10px'><select name='term_name' id='e_term_name' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' id='e_year' required class='input-field'><input name='start_date' id='e_start' type='date' required class='input-field'><input name='end_date' id='e_end' type='date' required class='input-field'><button class='add-btn'>Update Term</button></form></div></div><div id='addSubjectModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Subject</b><span onclick='closeAddSubject()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_subject_action}' style='padding:18px;display:grid;gap:10px'><input name='subject_name' required placeholder='Subject Name *' class='input-field'><input name='code' placeholder='Code e.g. MAT' class='input-field'><input name='initial' placeholder='Initial e.g. M' class='input-field'><button class='add-btn'>Add Subject</button></form></div></div><script>function switchTab(t){{document.querySelectorAll('[id^=panel-]').forEach(p=>p.style.display='none');document.querySelectorAll('.dean-tab').forEach(b=>b.classList.remove('active'));document.getElementById('panel-'+t).style.display='block';document.getElementById('tab-'+t).classList.add('active');const url=new URL(window.location); url.searchParams.set('tab',t); history.pushState({{}},'',url);}}function openAddTerm(){{document.getElementById('addTermModal').classList.add('active');}}function closeAddTerm(){{document.getElementById('addTermModal').classList.remove('active');}}function openEditTerm(id,name,year,s,e){{document.getElementById('editTermModal').classList.add('active');document.getElementById('editTermForm').action = (window.location.pathname.includes('global-control')? '/super/global-control/dean-settings/edit-term/' : '/school/dean-settings/edit-term/') + id;document.getElementById('e_term_name').value=name;document.getElementById('e_year').value=year;document.getElementById('e_start').value=s;document.getElementById('e_end').value=e;}}function closeEditTerm(){{document.getElementById('editTermModal').classList.remove('active');}}function openAddSubject(){{document.getElementById('addSubjectModal').classList.add('active');}}function closeAddSubject(){{document.getElementById('addSubjectModal').classList.remove('active');}}function filterTerms(){{let q=document.getElementById('termSearch').value.toLowerCase();let y=document.getElementById('yearFilter').value.toLowerCase();document.querySelectorAll('.term-row').forEach(r=>{{let ok=true;if(q &&!r.getAttribute('data-search').includes(q)) ok=false;if(y!=='all' && r.getAttribute('data-year').toLowerCase()!==y) ok=false;r.style.display=ok?'':'none';}});}}function filterSubjects(){{let q=document.getElementById('subjSearch').value.toLowerCase();document.querySelectorAll('.subj-row').forEach(r=>{{r.style.display=r.getAttribute('data-search').includes(q)?'':'none';}});}}function downloadTerms(){{let rows=document.querySelectorAll('#termsTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i>0 && i<6) d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}}); if(d.length) csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='terms_{school_name}.csv';a.click();}}</script>"""

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
        rows += f"""<tr class='exam-row' data-search="{e['name'].lower()} {e['year']} {e['term'].lower()}" data-year="{e['year']}" data-term="{e['term']}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:13px'>{idx}</td><td style='padding:12px;font-size:13px;font-weight:700'>{e['name']}</td><td style='padding:12px;font-size:13px'>{e['term']}</td><td style='padding:12px;font-size:13px'>{e['year']}</td><td style='padding:12px'><span style='background:#0f172a;color:white;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:700'>{e['exam_type'] or 'Main Exam'}</span></td><td style='padding:12px;display:flex;gap:6px'>{edit_btn}<a href='{del_url}' style='padding:6px 8px;background:#fee2e2;border-radius:8px;text-decoration:none;font-size:12px'>🗑️</a></td></tr>"""
    if not rows:
        rows = "<tr><td colspan='7' style='padding:40px;text-align:center;color:#94a3b8'>No exams — click + Add Exam</td></tr>"
    add_action = "/super/global-control/exams/add" if is_global else "/school/exams/add"
    edit_base = "/super/global-control/exams/edit/" if is_global else "/school/exams/edit/"
    return f"""<style>.exam-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden}}.filter-input{{padding:10px 12px 10px 34px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;width:220px}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;min-width:120px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-exam-btn{{background:#0f172a;color:white;padding:10px 16px;border:none;border-radius:12px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1450px;margin:auto'><div style='margin-bottom:14px'><h1 style='margin:0;font-size:26px;font-weight:900;letter-spacing:-0.5px'>Exam Settings</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage exams — {school_name} • Linked to Set Marks (Out Of)</p></div><div class='exam-card'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='examSearch' onkeyup='filterExams()' placeholder='Search exams...' class='filter-input'></div><select id='yearFilter' class='filter-select' onchange='filterExams()'>{year_opts_filter}</select><select id='termFilter' class='filter-select' onchange='filterExams()'>{term_opts_filter}</select></div><div style='display:flex;gap:8px'><button class='action-btn' onclick='downloadExams()'>⬇️ Download CSV</button><button class='add-exam-btn' onclick='openAddExam()'>+ Add Exam</button></div></div><div style='overflow:auto;max-height:65vh'><table id='examTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px'><input type='checkbox'></th><th style='padding:12px'>#</th><th style='padding:12px'>EXAM NAME ↕️</th><th style='padding:12px'>TERM ↕️</th><th style='padding:12px'>YEAR ↕️</th><th style='padding:12px'>TYPE</th><th style='padding:12px;text-align:right'>ACTIONS</th></tr></thead><tbody>{rows}</tbody></table></div></div></div><div id='addExamModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Exam</b><span onclick='closeAddExam()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_action}' style='padding:18px;display:grid;gap:10px'><input name='exam_name' required placeholder='Exam Name * e.g. OPENER' class='input-field'><select name='term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='Year e.g. 2026' class='input-field'><select name='exam_type' required class='input-field'><option>Main Exam</option><option>End Term Exam</option><option>Mid Term</option><option>CAT</option></select><button class='add-btn'>Add Exam</button></form></div></div><div id='editExamModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>✏️ Edit Exam</b><span onclick='closeEditExam()' style='cursor:pointer'>✕</span></div><form id='editExamForm' method='post' style='padding:18px;display:grid;gap:10px'><input name='exam_name' id='e_name' required class='input-field'><select name='term' id='e_term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' id='e_year' required class='input-field'><select name='exam_type' id='e_type' required class='input-field'><option>Main Exam</option><option>End Term Exam</option><option>Mid Term</option><option>CAT</option></select><button class='add-btn'>Update Exam</button></form></div></div><script>function openAddExam(){{document.getElementById('addExamModal').classList.add('active');}}function closeAddExam(){{document.getElementById('addExamModal').classList.remove('active');}}function openEditExam(id,name,term,year,type){{document.getElementById('editExamModal').classList.add('active');document.getElementById('editExamForm').action = "{edit_base}" + id; document.getElementById('e_name').value=name; document.getElementById('e_term').value=term; document.getElementById('e_year').value=year; document.getElementById('e_type').value=type;}}function closeEditExam(){{document.getElementById('editExamModal').classList.remove('active');}}function filterExams(){{let q=document.getElementById('examSearch').value.toLowerCase();let y=document.getElementById('yearFilter').value.toLowerCase();let t=document.getElementById('termFilter').value.toLowerCase();document.querySelectorAll('.exam-row').forEach(r=>{{let ok=true;if(q &&!r.getAttribute('data-search').includes(q)) ok=false;if(y!=='all' && r.getAttribute('data-year').toLowerCase()!==y) ok=false;if(t!=='all' && r.getAttribute('data-term').toLowerCase()!==t) ok=false;r.style.display=ok?'':'none';}});}}function downloadExams(){{let rows=document.querySelectorAll('#examTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i>0 && i<6) d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}}); if(d.length) csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='exams_{school_name}.csv';a.click();}}</script>"""

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
    return f"""<style>.page-title{{font-size:24px;font-weight:900;margin:0}}.page-sub{{font-size:13px;color:#64748b;margin-top:4px}}.two-col{{display:grid;grid-template-columns:380px 1fr;gap:16px;margin-top:16px}}.card-white{{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px}}.info-blue{{background:#e6f0ff;border:1px solid #bfdbfe;border-radius:12px;padding:12px;font-size:12px;color:#1e40af;display:flex;gap:8px;line-height:1.5}}.label-red{{font-size:11px;font-weight:700;color:#dc2626;display:block;margin-top:10px;margin-bottom:4px}}.select-field{{width:100%;padding:11px 12px;border:1px solid #e5e7eb;border-radius:10px;background:white;font-size:13px}}.save-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer;margin-top:14px;display:flex;justify-content:center;align-items:center;gap:8px}}.filter-bar{{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}}.filter-select{{padding:8px 10px;border:1px solid #e5e7eb;border-radius:10px;background:white;font-size:12px;min-width:110px}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div><h1 class='page-title'>Set Marks</h1><p class='page-sub'>Configure the maximum marks (out of) for each subject per exam</p></div><div class='two-col'><div class='card-white'><h3 style='margin:0 0 12px;font-size:16px;font-weight:800'>Set Marks Options</h3><div class='info-blue'>ℹ️ <span><b>Out Of:</b> This is what the teacher will mark this paper out of e.g. 50 or 100. Marks are not converted. e.g. if the paper is out of 60 set that.</span></div><form method='post' action='{save_action}' style='margin-top:14px'><label class='label-red'>Subject *</label><select name='subject_id' required class='select-field'>{subj_opts}</select><label class='label-red'>Class *</label><select name='class_name' required class='select-field'>{class_opts}</select><label class='label-red'>Stream *</label><select name='stream' required class='select-field'>{stream_opts}</select><label class='label-red'>Year *</label><select name='year' required class='select-field'>{year_opts}</select><label class='label-red'>Term *</label><select name='term' required class='select-field'>{term_opts}</select><label class='label-red'>Exam *</label><select name='exam_id' required class='select-field'>{exam_opts}</select><label class='label-red'>Out Of *</label><input name='out_of' required type='number' min='1' max='500' placeholder='Out Of' class='select-field'><button class='save-btn'>💾 Save Settings</button></form></div><div class='card-white'><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'><h3 style='margin:0;font-size:16px;font-weight:800'>Already Set Marks</h3><span style='font-size:11px;color:#64748b'>{len(configs)} records</span></div><div class='filter-bar'><select id='filterYear' class='filter-select' onchange='filterConfigs()'>{all_years_filter}</select><select id='filterTerm' class='filter-select' onchange='filterConfigs()'>{all_terms_filter}</select><select id='filterClass' class='filter-select' onchange='filterConfigs()'>{all_classes_filter}</select><input id='searchConfig' onkeyup='filterConfigs()' placeholder='🔍 Search...' style='padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;font-size:12px;min-width:130px'></div><div style='overflow:auto;max-height:70vh'><table id='configTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:10px 12px'><input type='checkbox'></th><th style='padding:10px 12px'>#</th><th>YEAR ↓</th><th>TERM</th><th>CLASS</th><th>SUBJECT</th><th>OUT OF</th><th>ACTION</th></tr></thead><tbody>{rows}</tbody></table></div><div style='display:flex;justify-content:space-between;margin-top:12px;font-size:12px;color:#64748b'><span>Show <select id='perPage' onchange='filterConfigs()' style='padding:4px;border:1px solid #e5e7eb;border-radius:6px'><option>10</option><option>25</option><option>50</option><option>100</option></select> items per page</span><span id='showing'>Showing 1-{len(configs)} of {len(configs)}</span></div></div></div></div><script>function filterConfigs(){{let q=document.getElementById('searchConfig').value.toLowerCase();let yf=document.getElementById('filterYear').value.toLowerCase();let tf=document.getElementById('filterTerm').value.toLowerCase();let cf=document.getElementById('filterClass').value.toLowerCase();let rows=document.querySelectorAll('.cfg-row');let visible=0;rows.forEach(r=>{{let ok=true;let txt=r.getAttribute('data-search');if(q &&!txt.includes(q)) ok=false;let tds=r.querySelectorAll('td');let year=tds[2].innerText.toLowerCase();let term=tds[3].innerText.toLowerCase();let cls=tds[4].innerText.toLowerCase();if(yf!=='all' && yf!=='' &&!year.includes(yf)) ok=false;if(tf!=='all' && tf!=='' &&!term.includes(tf)) ok=false;if(cf!=='all' && cf!=='' &&!cls.includes(cf)) ok=false;r.style.display=ok?'':'none';if(ok) visible++;}});document.getElementById('showing').innerText='Showing 1-'+visible+' of '+visible;}}</script>"""

# NEW EXACT RECORD MARKS WINDOW - ONLY ADDITION
def record_marks_exact_html(students, subject_name, exam_name, class_name, stream_name, out_of, total_count, filled_count, school_name, exam_id, subject_id, year, term):
    full_class = f"{class_name} {stream_name}".strip()
    rows = ""
    for idx, st in enumerate(students, 1):
        mv = st.get('marks','')
        dv = f"{mv}" if mv!="" and mv is not None else ""
        rows += f"""<tr class='stu-row' data-search="{(st['name'] or '').lower()} {str(st['admission_no'] or '').lower()}"><td style='padding:14px 12px;font-size:13px;color:#64748b'>{idx}</td><td style='padding:14px 12px;font-size:13px;font-weight:700'>{st['admission_no'] or ''}</td><td style='padding:14px 12px;font-size:13px;font-weight:600'>{st['name']}</td><td style='padding:14px 12px'><input type='number' min='0' max='{out_of}' step='0.01' id='mark_{st['id']}' value='{dv}' placeholder='/ {out_of}' onblur='autoSave({st['id']})' onkeydown='if(event.key==="Enter"){{autoSave({st['id']})}}' style='width:110px;padding:9px 12px;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;background:#fcfcfc;text-align:center'></td></tr>"""
    return f"""<style>.record-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden}}.badge{{padding:4px 10px;border-radius:12px;font-size:11px;font-weight:800;display:inline-block}}.badge-total{{background:#e0f2fe;color:#0369a1;border:1px solid #bae6fd}}.badge-filled{{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}}.badge-open{{background:#f1f5f9;color:#475569;border:1px solid #e2e8f0}}.filter-input{{padding:9px 12px 9px 32px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;min-width:200px}}.action-btn{{padding:9px 14px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.save-finish{{background:#0f172a;color:white;padding:10px 18px;border:none;border-radius:10px;font-weight:800;cursor:pointer}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div class='record-card'><div style='padding:14px 18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px'><div style='display:flex;gap:16px;flex-wrap:wrap;font-size:13px'><span><span style='color:#64748b'>Subject:</span> <b>{subject_name}</b></span><span><span style='color:#64748b'>Exam:</span> <b>{exam_name}</b></span><span><span style='color:#64748b'>Class:</span> <b>{full_class}</b></span><span><span style='color:#64748b'>Out of:</span> <b>{out_of}</b></span></div><div style='display:flex;gap:8px'><span class='badge badge-total'>Total: {total_count}</span><span class='badge badge-filled' id='filledBadge'>Filled: {filled_count}</span><span class='badge badge-open'>open</span></div></div><div style='padding:12px 18px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;align-items:center;gap:8px;font-size:13px'><span style='color:#64748b'>Show</span><select id='perPage' onchange='changePerPage()' style='padding:6px 8px;border:1px solid #e2e8f0;border-radius:8px'><option value='10' selected>10</option><option value='25'>25</option><option value='50'>50</option><option value='100'>100</option><option value='1000'>All</option></select><span style='color:#64748b'>items per page</span></div><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='searchInput' onkeyup='filterStudents()' placeholder='Search by name or admno...' class='filter-input'></div><button class='action-btn' onclick='exportCSV()'>⬇️ Export CSV</button></div></div><div style='overflow:auto;max-height:62vh'><table id='marksTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#f8fafc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px'>#</th><th style='padding:12px'>ADMNO ↑</th><th style='padding:12px'>STUDENT NAME ↕️</th><th style='padding:12px'>MARKS ↕️</th></tr></thead><tbody id='tableBody'>{rows}</tbody></table></div><div style='padding:14px 18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;border-top:1px solid #f1f5f9'><div style='font-size:12px;color:#64748b'><span id='showingText'>Showing 1-10 of {total_count}</span><br><span id='enteredText'>{filled_count} of {total_count} marks entered</span><br><span style='font-size:11px'>Marks auto-save when you move to the next field. Click 'Save & Finish' when done to mark as recorded.</span></div><div style='display:flex;gap:10px;align-items:center'><div style='display:flex;gap:6px;align-items:center;font-size:12px'><button onclick='prevPage()' class='action-btn'>‹ Previous</button><span id='pageInfo'>Page 1</span><button onclick='nextPage()' class='action-btn'>Next ›</button></div><button onclick='saveFinish()' class='save-finish'>💾 Save & Finish</button></div></div></div></div><script>let currentPage=1; let perPage=10; let allRows=[]; window.onload=function(){{ allRows=Array.from(document.querySelectorAll('.stu-row')); updatePagination(); }}; function filterStudents(){{ currentPage=1; updatePagination(); }} function changePerPage(){{ perPage=parseInt(document.getElementById('perPage').value); currentPage=1; updatePagination(); }} function updatePagination(){{ let searchQ=document.getElementById('searchInput').value.toLowerCase(); let toShow=allRows.filter(r=>r.getAttribute('data-search').includes(searchQ)); let total=toShow.length; let start=(currentPage-1)*perPage; let end=start+perPage; allRows.forEach(r=>r.style.display='none'); toShow.slice(start,end).forEach(r=>r.style.display=''); document.getElementById('showingText').innerText='Showing '+(total==0?0:start+1)+'-'+Math.min(end,total)+' of {total_count}'; let totalPages=Math.ceil(total/perPage)||1; document.getElementById('pageInfo').innerText='Page '+currentPage+' of '+totalPages; }} function prevPage(){{ if(currentPage>1){{currentPage--; updatePagination();}} }} function nextPage(){{ let searchQ=document.getElementById('searchInput').value.toLowerCase(); let toShow=allRows.filter(r=>r.getAttribute('data-search').includes(searchQ)); let totalPages=Math.ceil(toShow.length/perPage)||1; if(currentPage<totalPages){{currentPage++; updatePagination();}} }} function autoSave(studentId){{ let input=document.getElementById('mark_'+studentId); let val=input.value; if(val==='' ) return; let num=parseFloat(val); if(num>{out_of}){{ input.value={out_of}; num={out_of}; }} input.style.border='1px solid #22c55e'; fetch('/school/record-marks/auto-save',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'student_id='+studentId+'&exam_id={exam_id}&subject_id={subject_id}&class_name={class_name}&stream={stream_name}&year={year}&term={term}&out_of={out_of}&marks='+num}}).then(r=>r.json()).then(data=>{{ if(data.ok){{ let filledCount=0; document.querySelectorAll('input[id^=mark_]').forEach(i=>{{if(i.value!=='') filledCount++;}}); document.getElementById('filledBadge').innerText='Filled: '+filledCount; document.getElementById('enteredText').innerText=filledCount+' of {total_count} marks entered'; }} }}); }} function saveFinish(){{ window.location.href='/school/dashboard'; }} function exportCSV(){{ let rows=document.querySelectorAll('.stu-row'); let csv=['#,ADMNO,STUDENT NAME,MARKS']; rows.forEach((r,i)=>{{ let tds=r.querySelectorAll('td'); let adm=tds[1].innerText; let name=tds[2].innerText; let inp=r.querySelector('input'); let mark=inp?inp.value:''; csv.push([i+1,adm,'"'+name+'"',mark].join(',')); }}); let b=new Blob([csv.join('\\n')],{{type:'text/csv'}}); let u=URL.createObjectURL(b); let a=document.createElement('a'); a.href=u; a.download='marks_{class_name}_{subject_name}_{exam_name}.csv'; a.click(); }}</script>"""
    # === CORE ROUTES — EXACT FROM YOUR PART 1 ===
@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{margin:0;font-family:Arial;background:#f0f2f5;display:flex;height:100vh}.blue-bar{width:32px;background:#0d8bf2;flex-shrink:0}.main{flex:1;display:flex;justify-content:center;align-items:center;padding:20px}.card{background:white;width:540px;max-width:100%;padding:48px 48px 40px;border-radius:6px;box-shadow:0 0 0 1px #e2e8f0;text-align:center}.logo-box{width:72px;height:72px;background:#0f172a;color:white;border-radius:18px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:32px;margin:0 auto}.input{width:100%;padding:14px 16px;border:1px solid #e2e8f0;border-radius:10px;background:#fcfcfc;font-size:14px;outline:none;box-sizing:border-box}.sign{background:#0d8bf2;color:white;width:100%;padding:15px;border:none;border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;margin-top:10px}</style></head><body><div class="blue-bar"></div><div class="main"><div class="card"><div class="logo-box">D</div><h1 style="margin:16px 0 0;font-size:40px;font-weight:900;color:#0f172a">DaviSchool</h1><div style="margin-top:12px;color:#334155;font-size:15px">Sign in to your Davischool account</div><form method="post" action="/login" style="margin-top:30px;text-align:left"><label style="font-size:13px;font-weight:700;display:block;margin-bottom:8px">Username or Email</label><input name="email" class="input" required style="margin-bottom:20px"><label style="font-size:13px;font-weight:700;display:block;margin-bottom:8px">Password</label><input name="password" type="password" class="input" required style="margin-bottom:18px"><button class="sign">Sign In</button></form></div></div></body></html>"""
@app.head("/")
def home_head(): return PlainTextResponse("OK")
@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    try:
        cur = con.cursor()
        u = cur.execute("SELECT * FROM users WHERE lower(email)=lower(?) LIMIT 1", (email.strip(),)).fetchone()
        if not u:
            return HTMLResponse("❌ Invalid username or password. <a href='/'>Back</a>", status_code=401)
        valid, _ = verify_password(password, u["password"])
        if not valid:
            return HTMLResponse("❌ Invalid username or password. <a href='/'>Back</a>", status_code=401)
        user_id=u["id"]; user_email=u["email"]; role=u["role"]; full_name=u["full_name"]; school_id=u["school_id"] or 0
        # Every school-linked account is blocked when its school is suspended.
        # Super Admin accounts are platform-level and may not have a school_id.
        if school_id and role != "super_admin":
            school = cur.execute("SELECT status FROM schools WHERE id=?", (school_id,)).fetchone()
            school_status = str(school["status"] or "active").strip().lower() if school else "suspended"
            if school_status not in ("active", "enabled"):
                return HTMLResponse("❌ This school account is suspended. Please contact the DaviSchool administrator. <a href='/'>Back</a>", status_code=403)
    except Exception as exc:
        print("DAVISCHOOL LOGIN ERROR:", repr(exc), flush=True)
        return HTMLResponse("DaviSchool could not complete the sign-in request. Please try again.", status_code=500)
    finally:
        con.close()
    request.session["user_id"]=user_id; request.session["email"]=user_email; request.session["role"]=role
    request.session["name"]=full_name; request.session["school_id"]=school_id
    # Preserve the linked profile created in School Users so dedicated portals
    # can identify the correct teacher/student/parent after sign-in.
    request.session["teacher_id"]=u["teacher_id"] if "teacher_id" in u.keys() else None
    request.session["student_id"]=u["student_id"] if "student_id" in u.keys() else None
    request.session["is_impersonating"]=False
    return RedirectResponse("/app", status_code=303)
@app.get("/account/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    return HTMLResponse("""<html><body style='font-family:Arial;background:#f8fafc;padding:30px'><div style='max-width:520px;margin:auto;background:white;padding:24px;border-radius:16px;border:1px solid #e2e8f0'><h2>Change Password</h2><form method='post'><input name='current_password' type='password' required placeholder='Current password' style='width:100%;padding:12px;margin:6px 0;box-sizing:border-box'><input name='new_password' type='password' required minlength='10' placeholder='New password (10+ characters)' style='width:100%;padding:12px;margin:6px 0;box-sizing:border-box'><input name='confirm_password' type='password' required minlength='10' placeholder='Confirm new password' style='width:100%;padding:12px;margin:6px 0;box-sizing:border-box'><button style='background:#0f172a;color:white;border:0;border-radius:10px;padding:12px 18px;margin-top:8px'>Update Password</button></form></div></body></html>""")
@app.post("/account/change-password")
def change_password(request: Request,current_password:str=Form(...),new_password:str=Form(...),confirm_password:str=Form(...)):
    if "email" not in request.session: return RedirectResponse("/",303)
    if len(new_password) < 10 or new_password != confirm_password: return HTMLResponse("Invalid new password. Use at least 10 characters and ensure both fields match. <a href='/account/change-password'>Back</a>",400)
    con=get_db(); cur=con.cursor(); u=cur.execute("SELECT * FROM users WHERE id=?",(request.session.get('user_id',0),)).fetchone()
    if not u: u=cur.execute("SELECT * FROM users WHERE lower(email)=lower(?)",(request.session.get('email',''),)).fetchone()
    if not u or not verify_password(current_password,u['password'])[0]: con.close(); return HTMLResponse("Current password is incorrect. <a href='/account/change-password'>Back</a>",403)
    cur.execute("UPDATE users SET password=? WHERE id=?",(hash_password(new_password),u['id']))
    ts=datetime.now(ZoneInfo('Africa/Nairobi')).strftime('%Y-%m-%d %H:%M:%S'); cur.execute("INSERT INTO system_audit(school_id,user_email,action,details,timestamp) VALUES(?,?,?,?,?)",(u['school_id'] or 0,u['email'],'PASSWORD_CHANGE','Password changed',ts)); con.commit(); con.close(); return RedirectResponse('/account/change-password',303)

@app.get("/logout")
def logout(request: Request): request.session.clear(); return RedirectResponse("/")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") == "school_admin": return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools"); total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM schools WHERE lower(COALESCE(status,'active')) IN ('active','enabled')"); active_total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM students"); total_students = cur.fetchone()["c"]
    try:
        cur.execute("SELECT COALESCE(SUM(CASE WHEN lower(COALESCE(status,'')) IN ('paid','complete','completed') THEN CAST(amount AS REAL) ELSE 0 END),0) as total FROM billing")
        revenue_total = float(cur.fetchone()["total"] or 0)
    except Exception:
        revenue_total = 0.0
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 10"); recent = cur.fetchall(); con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com"); initials = "".join([p[0] for p in name.split()][:2]).upper()
    rows = ""
    for s in recent:
        st = str(s["status"] or "active").strip().lower()
        active = st in ("active","enabled")
        label = "Active" if active else "Suspended"
        bg = "#dcfce7" if active else "#fee2e2"
        fg = "#166534" if active else "#991b1b"
        rows += f"<tr><td style='padding:10px 14px;font-size:12px;font-weight:600'>{s['name']}</td><td style='padding:10px 14px;font-size:12px'>{s['location']}</td><td><span style='background:{bg};color:{fg};padding:3px 8px;border-radius:12px;font-size:10px'>{label}</span></td><td style='padding:10px 14px;font-size:11px;color:#64748b'>Registered</td></tr>"
    if not rows:
        rows = "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No schools yet</td></tr>"
    content = f"""<div style='padding:20px;max-width:1400px;margin:auto'><div style='margin-bottom:18px'><h2 style='margin:0;font-size:22px;font-weight:800'>📊 School Overview</h2><p style='margin:4px 0 0;color:#64748b;font-size:13px'>Welcome {name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:32px;font-weight:900;margin:12px 0 8px'>{total}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:32px;font-weight:900;margin:12px 0 8px'>{active_total}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🔥 TOTAL REVENUE</div><div style='font-size:26px;font-weight:900;margin:12px 0 8px'>KES {revenue_total:,.2f}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:32px;font-weight:900;margin:10px 0 8px'>{total_students}</div></div></div><div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px 16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='font-weight:800;font-size:14px'>🏫 Recently Added Schools</div><a href='/schools/manage' style='font-size:12px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 14px'>Name</th><th>Location</th><th>Status</th><th>Date</th></tr></thead><tbody>{rows}</tbody></table></div><div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='font-weight:800;font-size:14px;margin-bottom:12px'>⚡ Quick Actions</div><a href='/schools/manage' style='display:block;text-align:center;background:white;border:1px solid #e2e8f0;padding:10px;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:600;font-size:13px;margin-bottom:10px'>🏫 Manage Schools</a><a href='/super/global-control/dashboard' style='display:block;text-align:center;background:#0f172a;color:white;padding:10px;border-radius:10px;text-decoration:none;font-weight:700;font-size:13px'>🌍 Global Control</a></div></div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials, name, email)}{content}</body></html>")

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = "", message: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com"); initials = "".join([p[0] for p in name.split()][:2]).upper()
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools = cur.fetchall(); cur.execute("SELECT * FROM users WHERE role='school_admin'"); users = cur.fetchall(); pending=None
    if pending_id: cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    con.close(); users_by_school = {u["school_id"]: u for u in users}
    popup=""
    if success=="invalid_code":
        popup=f"""<div style='margin-bottom:16px;background:#fff1f2;border:2px solid #fb7185;border-radius:14px;padding:18px'><div style='font-size:18px;font-weight:900;color:#9f1239'>❌ Verification code is incorrect</div><div style='margin-top:8px;color:#475569'>Please enter the 6-digit code shown for this school.</div></div>"""
    elif success=="verify_error":
        safe = (message or "The school account could not be created.").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        popup=f"""<div style='margin-bottom:16px;background:#fff1f2;border:2px solid #fb7185;border-radius:14px;padding:18px'><div style='font-size:18px;font-weight:900;color:#9f1239'>❌ Verification failed</div><div style='margin-top:8px;color:#475569'>The school was not partially created. Try the verification again.</div><div style='margin-top:10px;font-family:monospace;font-size:12px;word-break:break-word'>{safe}</div></div>"""
    elif success=="already_added":
        popup=f"""<div style='margin-bottom:16px;background:#fef3c7;border:2px solid #f59e0b;border-radius:14px;padding:18px'><div style='font-size:18px;font-weight:900;color:#92400e'>⚠️ School account already exists</div><div style='margin-top:8px;color:#475569'>{school_email}</div></div>"""
    elif success=="status_updated":
        popup="""<div style='margin-bottom:16px;background:#eff6ff;border:2px solid #60a5fa;border-radius:14px;padding:16px'><div style='font-size:17px;font-weight:900;color:#1d4ed8'>🔄 School status updated</div><div style='margin-top:6px;color:#475569'>The school can now sign in only when its status is Active.</div></div>"""
    if success=="code_sent" and pending: popup=f"""<div style='margin-bottom:16px;background:white;border:1.5px solid #fb923c;border-radius:12px;padding:16px'><div style='font-weight:800'>🔓 Code for {pending["name"]}</div><div style='border:1.5px dashed #fb923c;border-radius:10px;padding:18px;text-align:center;background:#fffbeb;margin:12px 0'><div style='font-size:28px;font-weight:900;letter-spacing:10px'>{" ".join(list(pending["auth_code"]))}</div></div><form method='post' action='/verify-school-code' style='display:flex;gap:10px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' value='{pending["auth_code"]}' required style='flex:1;padding:12px;border:1px solid #e2e8f0;border-radius:10px;text-align:center;font-weight:700'><button style='background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px'>✅ Verify</button></form></div>"""
    elif success=="added" and new_pass:
        popup=f"""<div id='daviSuccessOverlay' style='position:fixed;inset:0;background:rgba(15,23,42,.28);display:flex;align-items:center;justify-content:center;padding:20px;z-index:99999'><div style='width:min(760px,96vw);background:#dcfce7;border:3px solid #16a34a;border-radius:18px;padding:28px;font-family:Arial,sans-serif'><div style='font-size:25px;font-weight:900;color:#166534;margin-bottom:18px'>✅ Success! 🏫 {school_name}</div><div style='background:white;border:1.5px dashed #22c55e;border-radius:14px;padding:18px;margin-bottom:18px'><div style='font-size:15px;color:#64748b'>👤 Username:</div><div style='font-size:25px;font-weight:900;color:#166534;word-break:break-word'>{school_email}</div><div style='font-size:15px;color:#64748b;margin-top:12px'>🔑 Password:</div><div style='font-size:25px;font-weight:900;color:#166534;word-break:break-word'>{new_pass}</div></div><button type='button' onclick="document.getElementById('daviSuccessOverlay').remove()" style='display:block;margin-left:auto;background:#0f172a;color:white;border:0;border-radius:12px;padding:13px 30px;font-size:17px;font-weight:900;cursor:pointer'>OK ✅</button></div></div>"""
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
        rows.append(f"""<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:12px 10px'><div style='font-weight:700'>🏫 {s['name']}</div><div style='font-size:10px;color:#64748b'>🔑 {s['code']}</div></td><td style='padding:12px 10px;font-size:12px'>{s['phone'] or ''}</td><td style='padding:12px 10px;font-size:11px'>{s['email']}</td><td style='padding:12px 10px;font-size:12px'>{s['location']}</td><td style='padding:12px 10px;font-size:11px'>{admin_email}</td><td style='padding:12px 10px;font-size:12px'><button type='button' onclick='viewSchoolPassword({sid})' title='View password' style='border:0;background:#eff6ff;color:#1d4ed8;border-radius:7px;padding:6px 10px;cursor:pointer;font-size:15px'>👁️</button></td><td style='padding:12px 10px'><form method='post' action='/schools/status/{sid}' style='display:inline'><button type='submit' style='border:0;background:{status_bg};color:{status_fg};border-radius:7px;padding:6px 9px;cursor:pointer;font-size:11px;font-weight:800'>{status_text}</button></form></td><td style='padding:12px 10px;display:flex;gap:6px'><a href='/schools/edit/{sid}' onclick="return confirm('Open edit screen for {school_name_js}?')" style='background:#e0f2fe;color:#075985;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px;font-weight:700'>✏️ Edit</a><form method='post' action='/schools/delete/{sid}' style='display:inline' onsubmit="return confirm('Delete {school_name_js} and its school administrator account? This cannot be undone.')"><button type='submit' style='border:0;background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px;font-weight:700;cursor:pointer'>🗑️</button></form></td></tr>""")
    rows="".join(rows) or "<tr><td colspan='8' style='padding:40px;text-align:center'>No schools</td></tr>"
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px}}input,select{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px}}</style></head><body>{header_html(initials, name, email)}<script>
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
</script><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px;padding:16px;max-width:1500px;margin:auto'><div><div class='card'>{popup}<div style='font-weight:800'>📚 Registered Schools ({len(schools)})</div><div style='overflow:auto;max-height:65vh;border:1px solid #f1f5f9;border-radius:10px;margin-top:10px'><table style='width:100%;border-collapse:collapse;font-size:13px'><thead style='position:sticky;top:0;background:#f8fafc'><tr style='text-align:left;font-size:11px'><th style='padding:10px'>School</th><th>Contact</th><th>Email</th><th>Location</th><th>Username</th><th>Password</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div><a href='/dashboard' style='margin-top:14px;display:inline-block;padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div class='card' style='height:fit-content'><div style='font-weight:800'>➕ Register New School</div><form method='post' action='/register-school'><input name='school_name' required placeholder='🏫 School Name *'><input name='school_email' required type='email' placeholder='📧 Admin Email *'><input name='location' required placeholder='📍 Location *'><input name='phone' required placeholder='📱 Phone *'><input name='principal' required placeholder='👤 Principal *'><select name='school_type' required><option>Primary</option><option>Secondary</option><option>Primary & Junior Secondary</option></select><button style='width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;margin-top:10px'>📧 Send Code</button></form></div></div></body></html>""")
@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code = str(random.randint(100000, 999999)); con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid; con.commit(); con.close(); return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}",303)
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
            "SELECT id, school_id FROM users WHERE lower(email)=lower(?) AND role='school_admin'",
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

        cur.execute(
            "INSERT INTO users (email,password,role,full_name,school_id,credential_secret) VALUES (?,?,?,?,?,?)",
            (
                email,
                hash_password(unique_pass),
                "school_admin",
                str(pending["principal"] or "").strip(),
                school_id,
                encrypt_credential(unique_pass),
            )
        )

        cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,))
        con.commit()

        # Return the success screen directly. This avoids losing the generated
        # credentials during a redirect and guarantees the OK button is shown.
        safe_name = str(pending["name"] or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        safe_email = email.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        safe_pass = unique_pass.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        return HTMLResponse(f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>School Created - DaviSchool</title></head>
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
<a href="/schools/manage" style="background:#0f172a;color:white;text-decoration:none;border-radius:12px;padding:13px 30px;font-size:16px;font-weight:900">OK ✅</a>
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
    new_pass=generate_unique_password(str(school["name"] or "DaviSchool"))
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
    secondary_selected = "selected" if school["school_type"] == "Secondary" else ""
    pjs_selected = "selected" if school["school_type"] == "Primary & Junior Secondary" else ""
    page = """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Edit School · DaviSchool</title><style>
body{margin:0;font-family:Arial;background:#f8fafc;color:#172033}.wrap{max-width:760px;margin:30px auto;padding:16px}.card{background:white;border:1px solid #e2e8f0;border-radius:18px;padding:24px}label{display:block;font-size:12px;font-weight:800;margin:12px 0 5px;color:#475569}input,select{width:100%;box-sizing:border-box;padding:12px;border:1px solid #dbe2e8;border-radius:10px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}button,a{display:inline-block;padding:12px 18px;border-radius:10px;font-weight:800;text-decoration:none}button{border:0;background:#0f172a;color:white;cursor:pointer}a{border:1px solid #e2e8f0;color:#0f172a;background:white}@media(max-width:650px){.grid{grid-template-columns:1fr}}</style></head><body><div class='wrap'><div class='card'><h1 style='margin-top:0'>✏️ Edit School</h1><div style='color:#64748b;font-size:13px;margin-bottom:18px'>Update the registered school details and its school administrator account.</div>
<form method='post' action='/schools/edit/__SID__' onsubmit="return confirm('Save these changes to this school?')">
<div class='grid'>
<div><label>School Name</label><input name='school_name' required value='__NAME__'></div>
<div><label>School Email</label><input name='school_email' type='email' required value='__EMAIL__'></div>
<div><label>Location</label><input name='location' required value='__LOCATION__'></div>
<div><label>Phone</label><input name='phone' required value='__PHONE__'></div>
<div><label>Principal / Administrator Name</label><input name='principal' required value='__PRINCIPAL__'></div>
<div><label>School Type</label><select name='school_type'><option __PRIMARY__>Primary</option><option __SECONDARY__>Secondary</option><option __PJS__>Primary & Junior Secondary</option></select></div>
</div>
<label>New School Administrator Password (optional)</label><input name='new_password' type='password' minlength='8' placeholder='Leave blank to keep current password'>
<div style='display:flex;gap:10px;justify-content:flex-end;margin-top:20px'><a href='/schools/manage'>Cancel</a><button type='submit'>💾 Save Changes</button></div></form></div></div></body></html>"""
    def _safe(value):
        return str(value or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")
    page=page.replace("__SID__",str(sid)).replace("__NAME__",_safe(school["name"])).replace("__EMAIL__",_safe(school["email"])).replace("__LOCATION__",_safe(school["location"])).replace("__PHONE__",_safe(school["phone"])).replace("__PRINCIPAL__",_safe(school["principal"] or full_name)).replace("__PRIMARY__",primary_selected).replace("__SECONDARY__",secondary_selected).replace("__PJS__",pjs_selected)
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
    con.commit(); con.close()
    return RedirectResponse("/schools/manage?success=updated",303)

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
    request.session["school_id"]=sid; request.session["is_impersonating"]=True; return RedirectResponse("/school/dashboard",303)
@app.get("/super/back-to-admin")
def back_to_admin(request: Request): request.session["school_id"]=0; request.session["is_impersonating"]=False; return RedirectResponse("/dashboard",303)

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

def get_global_set_marks_filter_data():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM subjects GROUP BY name ORDER BY name"); subjects = cur.fetchall()
    cur.execute("SELECT name, stream FROM classes GROUP BY name, stream ORDER BY name"); classes_raw = cur.fetchall()
    cur.execute("SELECT DISTINCT stream FROM classes WHERE stream!='' ORDER BY stream"); streams = [r["stream"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT year FROM terms ORDER BY year DESC"); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years:
        cur.execute("SELECT DISTINCT year FROM exams ORDER BY year DESC"); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years: years = [str(datetime.now().year)]
    cur.execute("SELECT DISTINCT term_name FROM terms ORDER BY term_name"); terms_list = [r["term_name"] for r in cur.fetchall()]
    if not terms_list: terms_list = ["Term 1","Term 2","Term 3"]
    cur.execute("SELECT * FROM exams GROUP BY name ORDER BY id DESC"); exams = cur.fetchall()
    classes_unique = []
    seen = set()
    for c in classes_raw:
        if c["name"] not in seen:
            classes_unique.append(c)
            seen.add(c["name"])
    con.close()
    return subjects, classes_unique, streams, years, terms_list, exams

@app.get("/school/set-marks", response_class=HTMLResponse)
@app.get("/school/marks", response_class=HTMLResponse)
def school_set_marks(request: Request, year: str = "all", term: str = "all", class_name: str = "all", search: str = ""):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
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
    if request.session.get("role") not in {"school_admin","super_admin"}: return RedirectResponse("/",303)
    school=get_school_obj(request)
    if not school or not _role_permission(request,"marks.edit"): return RedirectResponse("/portal",303)
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM set_marks_config WHERE id=? AND school_id=?", (cid,school["id"]))
    con.commit(); con.close()
    return RedirectResponse("/school/set-marks",303)

@app.get("/super/global-control/set-marks", response_class=HTMLResponse)
@app.get("/super/global-control/marks", response_class=HTMLResponse)
def global_set_marks(request: Request, year: str = "all", term: str = "all", class_name: str = "all"):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","")
    subjects, classes, streams, years, terms_list, exams = get_global_set_marks_filter_data()
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT cfg.*, s.name as subject_name FROM set_marks_config cfg LEFT JOIN subjects s ON cfg.subject_id=s.id GROUP BY cfg.subject_id, cfg.class_name, cfg.stream, cfg.year, cfg.term ORDER BY cfg.year DESC""")
    configs = cur.fetchall(); con.close()
    filters = {"year": year, "term": term, "class": class_name}
    header = global_header(name, "set-marks")
    body = set_marks_exact_html(subjects, classes, streams, years, terms_list, exams, configs, "ALL SCHOOLS", is_global=True, filters=filters)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{body}</div></div></body></html>")

@app.post("/super/global-control/set-marks/save")
def global_set_marks_save(request: Request, subject_id: int = Form(...), class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), exam_id: int = Form(...), out_of: int = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("SELECT name FROM subjects WHERE id=?", (subject_id,)); srow = cur.fetchone()
    sname = srow["name"] if srow else ""
    for sch in schools:
        cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=?", (sch["id"], sname))
        sub_real = cur.fetchone()
        sub_id_real = sub_real["id"] if sub_real else subject_id
        cur.execute("SELECT id FROM set_marks_config WHERE school_id=? AND subject_id=? AND class_name=? AND stream=? AND year=? AND term=? AND exam_id=?", (sch["id"], sub_id_real, class_name.strip().upper(), stream.strip().upper(), year.strip(), term.strip(), exam_id))
        existing = cur.fetchone()
        if existing:
            cur.execute("UPDATE set_marks_config SET out_of=?, created_at=? WHERE id=?", (out_of, ts, existing["id"]))
        else:
            cur.execute("INSERT INTO set_marks_config (school_id, subject_id, class_name, stream, year, term, exam_id, out_of, created_at) VALUES (?,?,?,?,?,?,?,?,?)", (sch["id"], sub_id_real, class_name.strip().upper(), stream.strip().upper(), year.strip(), term.strip(), exam_id, out_of, ts))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/set-marks",303)

@app.post("/super/global-control/set-marks/delete/{cid}")
def global_set_marks_delete(cid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM set_marks_config WHERE id=?", (cid,))
    if cur.fetchone():
        cur.execute("DELETE FROM set_marks_config WHERE id=?", (cid,))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/set-marks",303)
    # === SCHOOL DASHBOARD — EXACT YOUR PART 2 ===
@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
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
        cn = (r['class_name'] or 'UNASSIGNED').upper()
        if cn not in stats: stats[cn] = {'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys']=r['cnt']; tb+=r['cnt']
        else: stats[cn]['girls']=r['cnt']; tg+=r['cnt']
    max_v = max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    chart_html = "".join([f"<div style='text-align:center;min-width:90px'><div style='display:flex;gap:10px;align-items:end;justify-content:center;height:170px'><div><div style='width:42px;height:{bh}px;background:#0a84ff;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px;height:{gh}px;background:#ff2d92;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px;font-weight:800;margin-top:8px'>{cn}</div></div>" for cn,v in stats.items() for bh in [int((v['boys']/max_v)*150) if v['boys']>0 else 6] for gh in [int((v['girls']/max_v)*150) if v['girls']>0 else 6]]) or "<div style='padding:30px;color:#94a3b8;text-align:center;width:100%'>No students yet</div>"
    stu_rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{st['name']}</td><td style='padding:10px 12px;font-size:11px'>{st['assessment_no'] or ''}</td><td style='padding:10px 12px;font-size:11px'>{st['gender']}</td><td>Class {st['class_id'] or ''}</td></tr>" for st in recent_students]) or "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No students yet</td></tr>"
    header = school_header(school, name, "dashboard", is_impersonating=is_imp)
    html = f"""<div style='padding:18px;max-width:1400px;margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%);border-radius:18px;padding:22px 24px;color:white;display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'><div><div style='font-size:22px;font-weight:900'>DaviSchool Management System 🚀</div><div style='font-size:12px;color:#bfdbfe;margin-top:4px'>Set Marks Config: {set_cfg_count} | Students: {sc}</div></div><div style='text-align:right'><div style='font-size:34px;font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students</div></div></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px'><a href='/school/students' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🎓 TOTAL STUDENTS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{sc}</div></a><a href='/school/classes' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🏫 CLASSES</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{cc}</div></a><a href='/school/exams' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>📝 EXAMS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{ec}</div></a><a href='/school/teachers' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>👨‍🏫 STAFF</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{tc}</div></a></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='display:flex;justify-content:space-between'><div><div style='font-weight:800;font-size:14px'>👥 Students by Gender</div></div><div style='display:flex;gap:12px;font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex;gap:24px;overflow-x:auto;margin-top:18px'>{chart_html}</div></div><div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:14px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px 16px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><div style='font-weight:800'>🎓 Recent Students</div><a href='/school/students' style='font-size:11px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:10px;color:#64748b'><th style='padding:10px 12px'>Name</th><th>Adm No</th><th>Gender</th><th>Class</th></tr></thead><tbody>{stu_rows}</tbody></table></div><div style='background:#0f172a;border-radius:14px;padding:16px;color:white;height:fit-content'><div style='font-weight:800;font-size:14px'>📊 LIVE</div><div style='background:#1e293b;border-radius:10px;padding:12px;margin-top:10px'><div style='font-size:11px'>👦 {tb} | 👧 {tg}</div><div style='font-size:11px;margin-top:6px;color:#22c55e'>Out Of Config: {set_cfg_count}</div><a href='/school/set-marks' style='display:block;margin-top:10px;background:white;color:#0f172a;padding:8px;border-radius:8px;text-align:center;text-decoration:none;font-weight:800;font-size:12px'>📄 Set Marks</a></div></div></div></div>"""
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
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
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
def dean_settings(request: Request, tab: str = "terms"):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY year DESC, id DESC", (school["id"],)); terms = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (school["id"],)); subjects = cur.fetchall()
    cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name", (school["id"],)); teachers = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT ta.*, t.name as tname, s.name as sname, c.name as cname FROM teacher_allocations ta LEFT JOIN teachers t ON ta.teacher_id=t.id LEFT JOIN subjects s ON ta.subject_id=s.id LEFT JOIN classes c ON ta.class_id=c.id WHERE ta.school_id=? ORDER BY t.name", (school["id"],)); allocs = cur.fetchall()
    cur.execute("SELECT COUNT(*) as cnt FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["cnt"]
    con.close()
    header = school_header(school, name, "dean-settings", is_impersonating=is_imp)
    body = dean_manager_html(terms, subjects, teachers, classes, allocs, sc, school["name"], is_global=False, active_tab=tab)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
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
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>🏫 Classes & Streams ({len(classes)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Class</b><form method='post' action='/school/classes/add'><input name='class_name' required placeholder='Class Name *' class='input-field'><input name='stream' required placeholder='Stream *' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Class</button></form></div></div></div></div></div></body></html>")
@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"classes.create"): return RedirectResponse("/portal",303)
    con=get_db(); cur=con.cursor(); nm=class_name.strip().upper(); st=stream.strip().upper()
    if not nm: con.close(); return HTMLResponse("Class name is required.",400)
    if cur.execute("SELECT id FROM classes WHERE school_id=? AND upper(name)=? AND upper(stream)=?",(school["id"],nm,st)).fetchone(): con.close(); return HTMLResponse("That class/stream already exists in this school.",409)
    cur.execute("INSERT INTO classes (school_id,name,stream) VALUES (?,?,?)",(school["id"],nm,st)); con.commit(); con.close(); return RedirectResponse("/school/classes",303)
@app.post("/school/classes/delete/{cid}")
def del_class(cid: int, request: Request):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"classes.edit"): return RedirectResponse("/portal",303)
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
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
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
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/teachers/add")
def add_teacher(request: Request, name: str = Form(...), tsc_no: str = Form(""), id_no: str = Form(...), gender: str = Form(...), role: str = Form(...), phone: str = Form(...), email: str = Form(""), employment_type: str = Form("Teaching")):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"staff.create"): return RedirectResponse("/portal",303)
    con=get_db(); cur=con.cursor(); nm=name.strip().upper(); ident=id_no.strip(); em=email.strip()
    if not nm or not ident: con.close(); return HTMLResponse("Staff name and ID number are required.",400)
    if cur.execute("SELECT id FROM teachers WHERE school_id=? AND (id_no=? OR (email<>'' AND lower(email)=lower(?)))",(school["id"],ident,em)).fetchone():
        con.close(); return HTMLResponse("A staff record with that ID or email already exists in this school.",409)
    cur.execute("INSERT INTO teachers (school_id,name,email,phone,tsc_no,gender,id_no,role,employment_type) VALUES (?,?,?,?,?,?,?,?,?)",(school["id"],nm,em,phone.strip(),tsc_no.strip(),gender.strip(),role.strip(),employment_type.strip()))
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
    html = f"""<div style='padding:20px;max-width:1400px;margin:auto'><h1 style='margin:0;font-size:22px;font-weight:900'>✏️ Record Marks</h1><p style='color:#64748b;font-size:13px'>Select filters — system checks Out Of from Set Marks</p><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-top:14px;display:grid;grid-template-columns:repeat(3,1fr);gap:12px'><form method='post' action='/school/record-marks/load' style='display:contents'><select name='class_name' required class='input-field'><option value=''>Select Class *</option>{opts_class}</select><select name='stream' required class='input-field'><option value=''>Select Stream *</option>{opts_stream}</select><select name='year' required class='input-field'><option value=''>Select Year *</option>{opts_year}</select><select name='term' required class='input-field'><option value=''>Select Term *</option>{opts_term}</select><select name='exam_id' required class='input-field'><option value=''>Select Exam *</option>{opts_exam}</select><select name='subject_id' required class='input-field'><option value=''>Select Subject *</option>{opts_subj}</select><button style='grid-column:span 3;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:800'>🔍 Load Students</button></form></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{html}</div></div></body></html>")

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
        panel = f"""<div style='display:grid;grid-template-columns:1.2fr 0.8fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><h3 style='margin:0 0 12px'>🏢 School Profile</h3><form method='post' action='{base_path}/update-profile' style='display:grid;gap:10px'><input name='name' value="{school['name']}" class='input-field'><input name='email' value="{school['email']}" class='input-field'><input name='location' value="{school['location']}" class='input-field'><input name='phone' value="{school['phone']}" class='input-field'><input name='principal' value="{school['principal']}" class='input-field'><input name='school_type' value="{school['school_type']}" class='input-field'><button class='add-btn'>💾 Update Profile</button></form></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><h3>📊 Info</h3><div style='font-size:13px;line-height:1.8'><div>🔑 Code: <b>{school['code']}</b></div><div>📧 {school['email']}</div><div>👥 Users: <b>{len(users)}</b></div></div></div></div>"""
    elif sub=="classes":
        rows = "".join([f"<tr><td style='padding:10px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><a href='{base_path}/delete-class/{c[0]}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No classes</td></tr>"
        panel = f"""<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>🏫 Classes ({len(classes)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Class</b><form method='post' action='{base_path}/add-class'><input name='class_name' required placeholder='Class' class='input-field'><input name='stream' required placeholder='Stream' class='input-field'><button class='add-btn'>Add</button></form></div></div>"""
    elif sub=="user-management":
        urows = "".join([f"<tr><td style='padding:10px'>{u['full_name']}</td><td>{u['email']}</td><td>{u['role']}</td><td><a href='{base_path}/delete-user/{u['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for u in users]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No users</td></tr>"
        teacher_opts=''.join([f"<option value='{x['id']}'>{x['name']} — {x['id_no'] or ''}</option>" for x in teachers_for_users])
        student_opts=''.join([f"<option value='{x['id']}'>{x['name']} — {x['admission_no'] or ''}</option>" for x in students_for_users])
        panel = f"""<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px'><div style='padding:14px'><b>👥 Users ({len(users)})</b></div><table style='width:100%'><tbody>{urows}</tbody></table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><b>➕ Add User / Portal Account</b><form method='post' action='{base_path}/add-user'><input name='full_name' required class='input-field' placeholder='Name'><input name='email' required class='input-field' placeholder='Email'><input name='password' required class='input-field' placeholder='Password'><select name='role' class='input-field'><option value='teacher'>Teacher</option><option value='parent'>Parent</option><option value='student'>Student</option><option value='school_admin'>School Admin</option></select><select name='teacher_id' class='input-field'><option value=''>Link Teacher (optional)</option>{teacher_opts}</select><select name='student_id' class='input-field'><option value=''>Link Student (for parent/student)</option>{student_opts}</select><button class='add-btn'>Create Account</button></form></div></div>"""
    elif sub=="database-backup":
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px'><h3>💾 Backup — {school['name']}</h3><a href='{base_path}/backup/download' style='background:#0f172a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none'>⬇️ Download</a></div>"""
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
        active_style = "background:#0f172a;color:white" if sub==tab else "background:#f8fafc;color:#475569;border:1px solid #e2e8f0"
        return f"<a href='/school/system-settings/{tab}' style='padding:8px 12px;border-radius:10px;text-decoration:none;font-size:12px;font-weight:700;{active_style}'>{icon} {label}</a>"
    pills = f"<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:12px;margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap'>{pill('school-profile','School Profile','🏢')}{pill('classes','Classes','🏫')}{pill('user-management','User Management','👥+')}{pill('database-backup','Database Backup','💾')}{pill('system-audit','System Audit','📈')}{pill('billing-payments','Billing & Payments','💳')}</div>"
    content = f"<div style='padding:20px;max-width:1450px;margin:auto'><h1 style='margin:0;font-size:26px;font-weight:900'>⚙️ System Settings</h1>{pills}{panel}</div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{content}</div></div></body></html>")
@app.post("/school/system-settings/update-profile")
def sys_update_profile(request: Request, name: str = Form(...), email: str = Form(""), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (name.strip().upper(), email.strip(), location.strip(), phone.strip(), principal.strip(), school_type.strip(), school_obj["id"])); con.commit(); con.close(); return RedirectResponse("/school/system-settings/school-profile",303)
@app.post("/school/system-settings/add-class")
def sys_add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (school_obj["id"], class_name.strip().upper(), stream.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/system-settings/classes",303)
@app.get("/school/system-settings/delete-class/{cid}")
def sys_del_class(request: Request, cid: int):
    school_obj=get_school_obj(request)
    if not school_obj or request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/",303)
    con=get_db(); con.execute("DELETE FROM classes WHERE id=? AND school_id=?",(cid,school_obj["id"])); con.commit(); con.close(); return RedirectResponse("/school/system-settings/classes",303)
@app.post("/school/system-settings/add-user")
def sys_add_user(request: Request, full_name: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form(...), teacher_id: str = Form(""), student_id: str = Form("")):
    school_obj = get_school_obj(request)
    if not school_obj or request.session.get("role") not in ["school_admin","super_admin"] or not _role_permission(request,"users.manage"):
        return RedirectResponse("/",303)
    role_v=role.strip().lower()
    allowed={"teacher","parent","student","school_admin","accountant","registrar"}
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
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id,teacher_id,student_id) VALUES (?,?,?,?,?,?,?)",(email.strip(),hash_password(password.strip()),role_v,full_name.strip(),school_obj["id"],tid,stid))
    con.commit(); con.close()
    return RedirectResponse("/school/system-settings/user-management",303)
@app.get("/school/system-settings/delete-user/{uid}")
def sys_del_user(request: Request, uid: int):
    school_obj=get_school_obj(request)
    if not school_obj or request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/",303)
    con=get_db(); con.execute("DELETE FROM users WHERE id=? AND school_id=?",(uid,school_obj["id"])); con.commit(); con.close(); return RedirectResponse("/school/system-settings/user-management",303)
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
    if not school_obj or request.session.get("role") not in ["school_admin","super_admin"] or not _role_permission(request,"settings.manage"):
        return RedirectResponse("/",303)
    con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM system_audit WHERE school_id=?",(school_obj["id"],)); con.commit(); con.close()
    return RedirectResponse("/school/system-settings/system-audit",303)
@app.post("/school/system-settings/billing/add")
def sys_billing_add(request: Request, amount: str = Form(...), status: str = Form(...), due_date: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO billing (school_id, amount, status, due_date, created_at) VALUES (?,?,?,?,?)", (school_obj["id"], amount.strip(), status.strip(), due_date.strip(), ts)); con.commit(); con.close(); return RedirectResponse("/school/system-settings/billing-payments",303)

# === GLOBAL — EXACT YOUR PART 2 ===
@app.get("/super/global-control/dashboard", response_class=HTMLResponse)
def global_dashboard(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students"); sc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM classes"); cc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM exams"); ec = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM teachers"); tc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM set_marks_config"); setc = cur.fetchone()["c"]
    cur.execute("SELECT c.name as class_name, s.gender, COUNT(*) as cnt FROM students s LEFT JOIN classes c ON s.class_id=c.id GROUP BY c.name, s.gender ORDER BY c.name"); gender_rows = cur.fetchall()
    con.close()
    stats = {}; tb=0; tg=0
    for r in gender_rows:
        cn = (r['class_name'] or 'UNASSIGNED').upper()
        if cn not in stats: stats[cn] = {'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys']=r['cnt']; tb+=r['cnt']
        else: stats[cn]['girls']=r['cnt']; tg+=r['cnt']
    max_v = max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    chart_html = "".join([f"<div style='text-align:center;min-width:90px'><div style='display:flex;gap:10px;align-items:end;justify-content:center;height:170px'><div><div style='width:42px;height:{bh}px;background:#0a84ff;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px;height:{gh}px;background:#ff2d92;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px;font-weight:800;margin-top:8px'>{cn}</div></div>" for cn,v in stats.items() for bh in [int((v['boys']/max_v)*150) if v['boys']>0 else 6] for gh in [int((v['girls']/max_v)*150) if v['girls']>0 else 6]]) or "<div style='padding:30px;color:#94a3b8;text-align:center;width:100%'>No students yet</div>"
    header = global_header(name, "dashboard")
    html = f"""<div style='padding:18px;max-width:1400px;margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%);border-radius:18px;padding:22px 24px;color:white;display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'><div><div style='font-size:22px;font-weight:900'>DaviSchool — GLOBAL CONTROL 🚀</div><div style='font-size:12px;color:#bfdbfe;margin-top:4px'>Set Marks Config: {setc} | All Schools Automatic Sync</div></div><div style='text-align:right'><div style='font-size:34px;font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students (ALL)</div></div></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px'><a href='/super/global-control/students' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🎓 TOTAL STUDENTS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{sc}</div></a><a href='/super/global-control/classes' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🏫 CLASSES</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{cc}</div></a><a href='/super/global-control/exams' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>📝 EXAMS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{ec}</div></a><a href='/super/global-control/teachers' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>👨‍🏫 STAFF</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{tc}</div></a></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='display:flex;justify-content:space-between'><div><div style='font-weight:800;font-size:14px'>👥 Students by Gender — ALL Schools</div></div><div style='display:flex;gap:12px;font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex;gap:24px;overflow-x:auto;margin-top:18px'>{chart_html}</div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

@app.get("/super/global-control/exams", response_class=HTMLResponse)
def global_exams(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams GROUP BY name, year ORDER BY year DESC, id DESC")
    exams = cur.fetchall(); con.close()
    header = global_header(name, "exams")
    body = exam_manager_html(exams, "ALL SCHOOLS — Global Control", is_global=True)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/super/global-control/exams/add")
def global_add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM exams WHERE school_id=? AND name=? AND year=?", (sch["id"], exam_name.strip().upper(), year.strip()))
        if not cur.fetchone():
            cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (sch["id"], exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip()))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/exams",303)
@app.post("/super/global-control/exams/edit/{eid}")
def global_edit_exam(eid: int, request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name, year FROM exams WHERE id=?", (eid,)); old = cur.fetchone()
    if old:
        cur.execute("UPDATE exams SET name=?, term=?, year=?, exam_type=? WHERE name=? AND year=?", (exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip(), old["name"], old["year"]))
    else:
        cur.execute("UPDATE exams SET name=?, term=?, year=?, exam_type=? WHERE id=?", (exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip(), eid))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/exams",303)
@app.get("/super/global-control/exams/delete/{eid}")
def global_del_exam(eid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name, year FROM exams WHERE id=?", (eid,)); old = cur.fetchone()
    if old:
        cur.execute("DELETE FROM exams WHERE name=? AND year=?", (old["name"], old["year"]))
    else:
        cur.execute("DELETE FROM exams WHERE id=?", (eid,))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/exams",303)

@app.get("/super/global-control/students", response_class=HTMLResponse)
def global_students(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "students")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes GROUP BY name, stream ORDER BY name"); classes = cur.fetchall()
    cur.execute("SELECT s.*, c.name as class_name, sc.name as school_name FROM students s LEFT JOIN classes c ON s.class_id=c.id LEFT JOIN schools sc ON s.school_id=sc.id ORDER BY s.id DESC LIMIT 500"); students = cur.fetchall()
    con.close()
    body = students_manager_html(students, classes, "ALL SCHOOLS — Global Control", is_global=True)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/super/global-control/students/add")
def global_add_student(request: Request, admission_no: str = Form(...), assessment_no: str = Form(""), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), category: str = Form("Day"), guardian_name: str = Form(""), parent_phone: str = Form("")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    cur.execute("SELECT name, stream FROM classes WHERE id=? LIMIT 1", (class_id,)); cl = cur.fetchone()
    if not cl: con.close(); return RedirectResponse("/super/global-control/students",303)
    cname = cl["name"]; cstream = cl["stream"] or ""
    for sch in schools:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (sch["id"], cname, cstream))
        real = cur.fetchone()
        if not real:
            cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (sch["id"], cname, cstream))
            class_real_id = cur.lastrowid
        else:
            class_real_id = real["id"]
        cur.execute("SELECT id FROM students WHERE school_id=? AND admission_no=?", (sch["id"], admission_no.strip().upper()))
        if not cur.fetchone():
            cur.execute("INSERT INTO students (school_id, admission_no, assessment_no, name, class_id, gender, parent_phone, category, guardian_name) VALUES (?,?,?,?,?,?,?,?,?)", (sch["id"], admission_no.strip().upper(), assessment_no.strip().upper(), student_name.strip().upper(), class_real_id, gender.strip(), parent_phone.strip(), category.strip(), guardian_name.strip().upper()))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/students",303)
@app.get("/super/global-control/students/delete/{sid}")
def global_del_stud(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=?", (sid,)); con.commit(); con.close(); return RedirectResponse("/super/global-control/students",303)
@app.get("/super/global-control/teachers", response_class=HTMLResponse)
def global_teachers(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "teachers")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM teachers ORDER BY id DESC"); teachers = cur.fetchall(); con.close()
    body = staff_manager_html(teachers, "ALL SCHOOLS — Global Control", is_global=True)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/super/global-control/teachers/add")
def global_add_teacher(request: Request, name: str = Form(...), tsc_no: str = Form(""), id_no: str = Form(...), gender: str = Form(...), role: str = Form(...), phone: str = Form(...), email: str = Form(""), employment_type: str = Form("Teaching")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM teachers WHERE school_id=? AND id_no=?", (sch["id"], id_no.strip()))
        if not cur.fetchone():
            cur.execute("INSERT INTO teachers (school_id, name, email, phone, tsc_no, gender, id_no, role, employment_type) VALUES (?,?,?,?,?,?,?,?,?)", (sch["id"], name.strip().upper(), email.strip(), phone.strip(), tsc_no.strip(), gender.strip(), id_no.strip(), role.strip(), employment_type.strip()))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/teachers",303)
@app.get("/super/global-control/teachers/delete/{tid}")
def global_del_teacher(tid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id_no FROM teachers WHERE id=?", (tid,)); t = cur.fetchone()
    if t and t["id_no"]: cur.execute("DELETE FROM teachers WHERE id_no=?", (t["id_no"],))
    else: cur.execute("DELETE FROM teachers WHERE id=?", (tid,))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/teachers",303)
@app.get("/super/global-control/classes", response_class=HTMLResponse)
def global_classes(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "classes")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT name, stream, COUNT(*) cnt FROM classes GROUP BY name, stream ORDER BY name"); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px 12px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><span style='background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:10px'>In {c['cnt']} schools</span></td><td><a href='/super/global-control/classes/delete/{c['name']}/{c['stream'] or ''}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No classes</td></tr>"
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>🏫 Classes & Streams ({len(classes)}) — Automatic</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/super/global-control/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Class</b><form method='post' action='/super/global-control/classes/add'><input name='class_name' required placeholder='Class Name *' class='input-field'><input name='stream' required placeholder='Stream *' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Class</button></form></div></div></div></div></div></body></html>")
@app.post("/super/global-control/classes/add")
def global_add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (sch["id"], class_name.strip().upper(), stream.strip().upper()))
        if not cur.fetchone(): cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (sch["id"], class_name.strip().upper(), stream.strip().upper()))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/classes",303)
@app.get("/super/global-control/classes/delete/{cname}/{stream}")
def global_del_class(cname: str, stream: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE name=? AND stream=?", (cname, stream)); con.commit(); con.close(); return RedirectResponse("/super/global-control/classes",303)

@app.get("/super/global-control/system-settings/{sub}", response_class=HTMLResponse)
def global_system_settings(sub: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools LIMIT 1"); school = cur.fetchone()
    if not school:
        con.close()
        header = global_header(name, f"system-settings/{sub}")
        return HTMLResponse(f"<html><body>{header}<div style='padding:40px;text-align:center'>No school yet</div></div></div></body></html>")
    cur.execute("SELECT * FROM users ORDER BY id DESC"); users = cur.fetchall()
    cur.execute("SELECT * FROM classes GROUP BY name, stream ORDER BY name"); classes = cur.fetchall()
    cur.execute("SELECT * FROM system_audit ORDER BY id DESC LIMIT 200"); audit = cur.fetchall()
    cur.execute("SELECT * FROM billing ORDER BY id DESC"); bills = cur.fetchall()
    con.close()
    header = global_header(name, f"system-settings/{sub}")
    base_path = "/super/global-control/system-settings"
    if sub=="school-profile":
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><h3>🏢 Global — School Profiles</h3><form method='post' action='{base_path}/update-profile' style='display:grid;gap:10px;margin-top:12px;max-width:500px'><input name='name' placeholder='New School Name (ALL)' class='input-field'><input name='location' placeholder='Location (ALL)' class='input-field'><input name='phone' placeholder='Phone (ALL)' class='input-field'><button class='add-btn'>Update ALL Schools</button></form></div>"""
    elif sub=="classes":
        rows = "".join([f"<tr><td style='padding:10px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><a href='{base_path}/delete-class/{c['name']}/{c['stream'] or ''}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No classes</td></tr>"
        panel = f"""<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px'><b>🏫 Global Classes — Automatic Sync</b></div><table style='width:100%'><tbody>{rows}</tbody></table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><b>➕ Add Class (ALL schools)</b><form method='post' action='{base_path}/add-class'><input name='class_name' required placeholder='Class' class='input-field'><input name='stream' required placeholder='Stream' class='input-field'><button class='add-btn'>Add Global Class</button></form></div></div>"""
    elif sub=="user-management":
        urows = "".join([f"<tr><td style='padding:10px;font-size:12px'>{u['full_name']}</td><td>{u['email']}</td><td>{u['role']}</td><td><a href='{base_path}/delete-user/{u['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for u in users[:100]]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No users</td></tr>"
        panel = f"""<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px'><b>👥 Global Users ({len(users)})</b></div><table style='width:100%'><tbody>{urows}</tbody></table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><b>➕ Add User (ALL schools)</b><form method='post' action='{base_path}/add-user'><input name='full_name' required placeholder='Name' class='input-field'><input name='email' required placeholder='Email' class='input-field'><input name='password' required placeholder='Password' class='input-field'><select name='role' class='input-field'><option>teacher</option><option>school_admin</option></select><button class='add-btn'>Create Global User</button></form></div></div>"""
    elif sub=="database-backup":
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px'><h3>💾 Global Database Backup — ALL Schools</h3><div style='display:flex;gap:12px;margin-top:16px'><a href='{base_path}/backup/download' style='background:#0f172a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:700'>⬇️ Download Full Backup</a></div></div>"""
    elif sub=="system-audit":
        audit_rows = "".join([f"<tr><td style='padding:10px;font-size:12px'>{a['timestamp'] or ''}</td><td>{a['user_email'] or ''}</td><td style='font-weight:600'>{a['action'] or ''}</td><td style='color:#64748b;font-size:12px'>{a['details'] or ''}</td></tr>" for a in audit[:100]]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No logs</td></tr>"
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px;display:flex;justify-content:space-between'><b>📈 Global Audit — ALL Schools</b><a href='{base_path}/audit/clear' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:8px;text-decoration:none'>Clear</a></div><div style='overflow:auto;max-height:60vh'><table style='width:100%'><tbody>{audit_rows}</tbody></table></div></div>"""
    elif sub=="billing-payments":
        brows = "".join([f"<tr><td style='padding:10px'>{b['amount']}</td><td>{b['status']}</td><td>{b['due_date'] or ''}</td></tr>" for b in bills]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No invoices</td></tr>"
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px'><h3>💳 Global Billing — ALL Schools</h3><form method='post' action='{base_path}/billing/add' style='display:flex;gap:10px;margin-top:12px'><input name='amount' required placeholder='Amount' class='input-field' style='width:200px'><select name='status' class='input-field' style='width:200px'><option>Paid</option><option>Pending</option></select><input name='due_date' type='date' class='input-field' style='width:200px'><button class='add-btn' style='width:200px'>Add</button></form><table style='width:100%;margin-top:16px'><tbody>{brows}</tbody></table></div>"""
    elif sub=="roles-permissions":
        con2=get_db(); rp=con2.execute("SELECT * FROM roles_permissions WHERE school_id=0 ORDER BY role,permission").fetchall(); con2.close()
        rows="".join([f"<tr><td style='padding:9px'>{r['role']}</td><td>{r['permission']}</td><td>{'Enabled' if r['enabled'] else 'Disabled'}</td></tr>" for r in rp]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No global permissions yet.</td></tr>"
        panel=f"<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><h3>🛡️ Global Roles & Permissions</h3><table style='width:100%'><tr><th align='left'>Role</th><th align='left'>Permission</th><th align='left'>Status</th></tr>{rows}</table><form method='post' action='/super/global-control/modules/roles/add' style='margin-top:14px;display:flex;gap:8px'><input name='role' required placeholder='Role' class='input-field'><input name='permission' required placeholder='Permission' class='input-field'><button class='add-btn'>Save</button></form></div>"
    elif sub=="integrations":
        con2=get_db(); ints=con2.execute("SELECT * FROM integrations WHERE school_id=0 ORDER BY id DESC").fetchall(); con2.close()
        rows="".join([f"<tr><td style='padding:9px'>{i['name']}</td><td>{i['status']}</td><td>{i['config'] or ''}</td></tr>" for i in ints]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No global integrations configured.</td></tr>"
        panel=f"<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><h3>🔌 Global Integrations</h3><table style='width:100%'><tr><th align='left'>Integration</th><th align='left'>Status</th><th align='left'>Configuration</th></tr>{rows}</table><form method='post' action='/super/global-control/modules/integrations/add' style='margin-top:14px;display:flex;gap:8px'><input name='name' required placeholder='Integration' class='input-field'><select name='status' class='input-field'><option>Configured</option><option>Pending</option><option>Disabled</option></select><input name='config' placeholder='Configuration note' class='input-field'><button class='add-btn'>Save</button></form></div>"
    else:
        panel = f"<div style='padding:40px;text-align:center;background:white;border-radius:16px'><h3>⚙️ {sub.replace('-', ' ').title()}</h3><p style='color:#64748b'>Global module window available.</p></div>"
    def pill(tab, label, icon):
        active_style = "background:#0f172a;color:white" if sub==tab else "background:#f8fafc;color:#475569;border:1px solid #e2e8f0"
        return f"<a href='/super/global-control/system-settings/{tab}' style='padding:8px 12px;border-radius:10px;text-decoration:none;font-size:12px;font-weight:700;{active_style}'>{icon} {label}</a>"
    pills = f"<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:12px;margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap'>{pill('school-profile','School Profile','🏢')}{pill('classes','Classes','🏫')}{pill('user-management','User Management','👥+')}{pill('database-backup','Database Backup','💾')}{pill('system-audit','System Audit','📈')}{pill('billing-payments','Billing & Payments','💳')}</div>"
    content = f"<div style='padding:20px;max-width:1450px;margin:auto'><h1 style='margin:0;font-size:26px;font-weight:900'>⚙️ System Settings — GLOBAL</h1>{pills}{panel}</div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{content}</div></div></body></html>")
@app.post("/super/global-control/system-settings/update-profile")
def global_sys_update_profile(request: Request, name: str = Form(""), location: str = Form(""), phone: str = Form("")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    if name.strip(): cur.execute("UPDATE schools SET name=?", (name.strip().upper(),))
    if location.strip(): cur.execute("UPDATE schools SET location=?", (location.strip(),))
    if phone.strip(): cur.execute("UPDATE schools SET phone=?", (phone.strip(),))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/system-settings/school-profile",303)
@app.post("/super/global-control/system-settings/add-class")
def global_sys_add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (sch["id"], class_name.strip().upper(), stream.strip().upper()))
        if not cur.fetchone(): cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (sch["id"], class_name.strip().upper(), stream.strip().upper()))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/system-settings/classes",303)
@app.get("/super/global-control/system-settings/delete-class/{cname}/{stream}")
def global_sys_del_class(cname: str, stream: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE name=? AND stream=?", (cname, stream)); con.commit(); con.close(); return RedirectResponse("/super/global-control/system-settings/classes",303)
@app.post("/super/global-control/system-settings/add-user")
def global_sys_add_user(request: Request, full_name: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (email.strip(), hash_password(password.strip()), role.strip(), full_name.strip(), sch["id"]))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/system-settings/user-management",303)
@app.get("/super/global-control/system-settings/delete-user/{uid}")
def global_sys_del_user(uid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT email FROM users WHERE id=?", (uid,)); u = cur.fetchone()
    if u: cur.execute("DELETE FROM users WHERE email=?", (u["email"],))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/system-settings/user-management",303)
@app.get("/super/global-control/system-settings/backup/download")
def global_sys_backup_download(request: Request): return RedirectResponse("/super/global-control/system-settings/database-backup",303)
@app.get("/super/global-control/system-settings/audit/clear")
def global_sys_audit_clear(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM system_audit"); con.commit(); con.close(); return RedirectResponse("/super/global-control/system-settings/system-audit",303)
@app.post("/super/global-control/system-settings/billing/add")
def global_sys_billing_add(request: Request, amount: str = Form(...), status: str = Form(...), due_date: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("INSERT INTO billing (school_id, amount, status, due_date, created_at) VALUES (?,?,?,?,?)", (sch["id"], amount.strip(), status.strip(), due_date.strip(), ts))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/system-settings/billing-payments",303)

@app.get("/super/global-control/dean-settings", response_class=HTMLResponse)
def global_dean_settings(request: Request, tab: str = "terms"):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms GROUP BY term_name, year ORDER BY year DESC"); terms = cur.fetchall()
    cur.execute("SELECT * FROM subjects GROUP BY name ORDER BY name"); subjects = cur.fetchall()
    cur.execute("SELECT * FROM teachers GROUP BY id_no ORDER BY name"); teachers = cur.fetchall()
    cur.execute("SELECT * FROM classes GROUP BY name, stream ORDER BY name"); classes = cur.fetchall()
    cur.execute("SELECT ta.id, t.name as tname, s.name as sname, c.name as cname FROM teacher_allocations ta LEFT JOIN teachers t ON ta.teacher_id=t.id LEFT JOIN subjects s ON ta.subject_id=s.id LEFT JOIN classes c ON ta.class_id=c.id GROUP BY t.name, s.name, c.name"); allocs = cur.fetchall()
    con.close()
    header = global_header(name, "dean-settings")
    body = dean_manager_html(terms, subjects, teachers, classes, allocs, 0, "ALL SCHOOLS — Global Control", is_global=True, active_tab=tab)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/super/global-control/dean-settings/add-term")
def global_add_term(request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM terms WHERE school_id=? AND term_name=? AND year=?", (sch["id"], term_name, year))
        if not cur.fetchone(): cur.execute("INSERT INTO terms (school_id, term_name, year, start_date, end_date) VALUES (?,?,?,?,?)", (sch["id"], term_name, year, start_date, end_date))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings?tab=terms",303)
@app.post("/super/global-control/dean-settings/edit-term/{tid}")
def global_edit_term(tid: int, request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT term_name, year FROM terms WHERE id=?", (tid,)); old = cur.fetchone()
    if old: cur.execute("UPDATE terms SET term_name=?, year=?, start_date=?, end_date=? WHERE term_name=? AND year=?", (term_name, year, start_date, end_date, old["term_name"], old["year"]))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings?tab=terms",303)
@app.get("/super/global-control/dean-settings/delete-term/{tid}")
def global_del_term(tid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT term_name, year FROM terms WHERE id=?", (tid,)); old = cur.fetchone()
    if old: cur.execute("DELETE FROM terms WHERE term_name=? AND year=?", (old["term_name"], old["year"]))
    else: cur.execute("DELETE FROM terms WHERE id=?", (tid,))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings?tab=terms",303)
@app.post("/super/global-control/dean-settings/add-subject")
def global_dean_add_subject(request: Request, subject_name: str = Form(...), code: str = Form(""), initial: str = Form("")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=?", (sch["id"], subject_name.strip().upper()))
        if not cur.fetchone(): cur.execute("INSERT INTO subjects (school_id, name, code, initial) VALUES (?,?,?,?)", (sch["id"], subject_name.strip().upper(), code.strip().upper(), initial.strip().upper()))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings?tab=subjects",303)
@app.get("/super/global-control/dean-settings/delete-subject/{sid}")
def global_dean_del_subject(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT name FROM subjects WHERE id=?", (sid,)); old = cur.fetchone()
    if old: cur.execute("DELETE FROM subjects WHERE name=?", (old["name"],))
    else: cur.execute("DELETE FROM subjects WHERE id=?", (sid,))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings?tab=subjects",303)
@app.post("/super/global-control/dean-settings/allocate")
def global_dean_allocate(request: Request, teacher_id: int = Form(...), subject_id: int = Form(...), class_id: int = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    cur.execute("SELECT * FROM teachers WHERE id=?", (teacher_id,)); t = cur.fetchone()
    cur.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)); s = cur.fetchone()
    cur.execute("SELECT * FROM classes WHERE id=?", (class_id,)); c = cur.fetchone()
    if t and s and c:
        for sch in schools:
            cur.execute("SELECT id FROM teachers WHERE school_id=? AND id_no=?", (sch["id"], t["id_no"])); tt = cur.fetchone()
            cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=?", (sch["id"], s["name"])); ss = cur.fetchone()
            cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (sch["id"], c["name"], c["stream"])); cc = cur.fetchone()
            if tt and ss and cc:
                cur.execute("INSERT INTO teacher_allocations (school_id, teacher_id, subject_id, class_id) VALUES (?,?,?,?)", (sch["id"], tt["id"], ss["id"], cc["id"]))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings?tab=allocation",303)
@app.get("/super/global-control/dean-settings/delete-alloc/{aid}")
def global_del_alloc(aid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM teacher_allocations WHERE id=?", (aid,)); con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings?tab=allocation",303)
@app.post("/super/global-control/dean-settings/promote")
def global_promote(request: Request, from_class: int = Form(...), to_class: int = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name, stream FROM classes WHERE id=?", (from_class,)); fc = cur.fetchone()
    cur.execute("SELECT name, stream FROM classes WHERE id=?", (to_class,)); tc = cur.fetchone()
    if fc and tc:
        cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
        for sch in schools:
            cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (sch["id"], fc["name"], fc["stream"])); f_real = cur.fetchone()
            cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (sch["id"], tc["name"], tc["stream"])); t_real = cur.fetchone()
            if f_real and t_real:
                cur.execute("UPDATE students SET class_id=? WHERE school_id=? AND class_id=?", (t_real["id"], sch["id"], f_real["id"]))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings?tab=promote",303)


# === ADDITIVE PORTALS + FINANCE MODULES ===
def portal_guard(request):
    return request.session.get("role") in ["teacher", "parent", "student"] and request.session.get("school_id", 0) != 0

@app.get("/portal", response_class=HTMLResponse)
def portal(request: Request):
    if not portal_guard(request):
        return RedirectResponse("/school/dashboard" if request.session.get("school_id") else "/")
    role=request.session.get("role"); name=request.session.get("name",""); school=get_school_obj(request)
    if role == "parent":
        return RedirectResponse("/portal/parent",303)
    if role == "student":
        return RedirectResponse("/portal/student",303)
    return RedirectResponse("/portal/teacher",303)

def portal_page(request, title, body):
    if not portal_guard(request): return RedirectResponse("/")
    school=get_school_obj(request); name=request.session.get("name",""); role=request.session.get("role","")
    nav=f"<div style='background:#0f172a;color:white;padding:16px 20px;display:flex;justify-content:space-between'><div><b>🏫 DaviSchool</b><div style='font-size:11px;opacity:.75'>{school['name'] if school else ''}</div></div><div>{name} • {role.title()} &nbsp; <a href='/logout' style='color:white'>Logout</a></div></div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc;color:#0f172a}}.wrap{{max-width:1200px;margin:auto;padding:22px}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-bottom:14px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #f1f5f9;text-align:left;font-size:13px}}h1{{font-size:25px}}</style></head><body>{nav}<div class='wrap'><h1>{title}</h1>{body}</div></body></html>")

@app.get("/portal/teacher", response_class=HTMLResponse)
def teacher_portal(request: Request):
    if not portal_guard(request) or request.session.get("role")!="teacher": return RedirectResponse("/")
    school_id=request.session["school_id"]; con=get_db(); cur=con.cursor()
    teacher_id=request.session.get("teacher_id")
    if teacher_id:
        allocations=cur.execute("SELECT c.name class_name,c.stream,s.name subject FROM teacher_allocations ta JOIN classes c ON c.id=ta.class_id JOIN subjects s ON s.id=ta.subject_id WHERE ta.school_id=? AND ta.teacher_id=? ORDER BY c.name,s.name",(school_id,teacher_id)).fetchall()
    else:
        allocations=[]
    rows=''.join(f"<tr><td>{r['class_name']}</td><td>{r['stream'] or ''}</td><td>{r['subject']}</td></tr>" for r in allocations) or '<tr><td colspan=3>No subject allocations linked to this account yet.</td></tr>'
    body=f"<div class='card'><h3>My Teaching Allocation</h3><table><tr><th>Class</th><th>Stream</th><th>Subject</th></tr>{rows}</table></div><div class='card'><h3>Quick actions</h3><a href='/school/record-marks'>Record Marks</a> &nbsp; | &nbsp; <a href='/school/attendance'>Attendance</a> &nbsp; | &nbsp; <a href='/school/analysis'>Analysis</a></div>"; con.close(); return portal_page(request,'👨‍🏫 Teacher Portal',body)

@app.get("/portal/student", response_class=HTMLResponse)
def student_portal(request: Request):
    if not portal_guard(request) or request.session.get("role")!="student": return RedirectResponse("/")
    con=get_db(); cur=con.cursor(); st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(request.session.get('student_id'),request.session['school_id'])).fetchone()
    marks=cur.execute("SELECT sub.name subject,e.name exam,m.marks,e.term,e.year FROM marks m JOIN subjects sub ON sub.id=m.subject_id JOIN exams e ON e.id=m.exam_id WHERE m.student_id=? AND m.school_id=? ORDER BY e.year DESC,e.id DESC,sub.name",(request.session.get('student_id'),request.session['school_id'])).fetchall() if st else []
    tr=''.join(f"<tr><td>{m['subject']}</td><td>{m['exam']}</td><td>{m['marks']}</td><td>{m['term']} {m['year']}</td></tr>" for m in marks) or '<tr><td colspan=4>No academic records yet.</td></tr>'
    body=f"<div class='card'><b>Student:</b> {st['name'] if st else request.session.get('name','')}<br><b>Admission:</b> {st['admission_no'] if st else ''}<br><b>Class:</b> {st['class_name'] if st else ''} {st['stream'] if st else ''}</div><div class='card'><h3>Academic Record</h3><table><tr><th>Subject</th><th>Exam</th><th>Marks</th><th>Term</th></tr>{tr}</table></div>"; con.close(); return portal_page(request,'🎓 Student Portal',body)

@app.get("/portal/parent", response_class=HTMLResponse)
def parent_portal(request: Request):
    if not portal_guard(request) or request.session.get("role")!="parent": return RedirectResponse("/")
    con=get_db(); cur=con.cursor(); student_id=request.session.get('student_id'); st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(student_id,request.session['school_id'])).fetchone()
    marks=cur.execute("SELECT sub.name subject,e.name exam,m.marks,e.term,e.year FROM marks m JOIN subjects sub ON sub.id=m.subject_id JOIN exams e ON e.id=m.exam_id WHERE m.student_id=? AND m.school_id=? ORDER BY e.year DESC,e.id DESC,sub.name",(student_id,request.session['school_id'])).fetchall() if st else []
    fee=cur.execute("SELECT COALESCE(SUM(amount),0) expected,COALESCE(SUM(paid),0) paid FROM fees WHERE school_id=? AND student_id=?",(request.session['school_id'],student_id)).fetchone() if st else {'expected':0,'paid':0}
    tr=''.join(f"<tr><td>{m['subject']}</td><td>{m['exam']}</td><td>{m['marks']}</td><td>{m['term']} {m['year']}</td></tr>" for m in marks) or '<tr><td colspan=4>No academic records yet.</td></tr>'
    balance=float(fee['expected'] or 0)-float(fee['paid'] or 0)
    body=f"<div class='card'><h3>👨‍👩‍👧 Child Record</h3><b>{st['name'] if st else 'No linked student'}</b><br>Admission: {st['admission_no'] if st else ''}<br>Class: {st['class_name'] if st else ''} {st['stream'] if st else ''}</div><div class='card'><h3>💰 Fee Balance</h3>Expected: {fee['expected'] if st else 0} &nbsp; Paid: {fee['paid'] if st else 0} &nbsp; <b>Balance: {balance}</b></div><div class='card'><h3>📊 Academic Performance</h3><table><tr><th>Subject</th><th>Exam</th><th>Marks</th><th>Term</th></tr>{tr}</table></div>"; con.close(); return portal_page(request,'👨‍👩‍👧 Parent Portal',body)

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
    """Check a school role permission; missing rules remain enabled for compatibility."""
    role=request.session.get("role")
    if role in ("school_admin","super_admin"):
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
    if "email" not in request.session: return RedirectResponse("/")
    if global_mode:
        if request.session.get("role") != "super_admin": return RedirectResponse("/")
        header = global_header(request.session.get("name","Davis Ouma"), active)
    else:
        role=request.session.get("role")
        school = get_school_obj(request)
        if not school: return RedirectResponse("/dashboard")
        role_modules={"teacher":{"record-marks":"marks.edit","attendance":"attendance.edit","analysis":"reports.view","timetable":"timetable.view"},"accountant":{"fees":"fees.view","finance":"finance.view"},"registrar":{"students":"students.view","staff":"staff.view"}}
        if role not in ["school_admin","super_admin"]:
            permission=role_modules.get(role,{}).get(active)
            if not permission or not _role_permission(request,permission):
                return RedirectResponse("/portal" if role in ("teacher","accountant","registrar","parent","student") else "/")
        header = school_header(school, request.session.get("name",""), active, request.session.get("is_impersonating",False))
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,Arial,sans-serif;background:#f4f7fb;color:#0f172a}}.mod{{padding:24px;max-width:1600px;margin:auto}}
.page-head{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:20px;flex-wrap:wrap}}.eyebrow{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;font-weight:800}}
h1{{font-size:26px;margin:2px 0 5px;letter-spacing:-.02em}}h2,h3{{margin-top:0}}p{{color:#64748b;font-size:13px}}.card{{background:white;border:1px solid #e5eaf1;border-radius:16px;padding:18px;margin-bottom:16px;box-shadow:0 2px 8px rgba(15,23,42,.03)}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}}.kpi{{background:white;border:1px solid #e5eaf1;border-radius:14px;padding:16px}}.kpi b{{font-size:24px;display:block;margin-top:7px}}.kpi span{{font-size:11px;color:#64748b}}
.toolbar{{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:12px}}.input-field,select,input,textarea{{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #dbe2ea;border-radius:10px;font-size:13px;background:white}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;background:#0f172a;color:white;padding:10px 14px;border:0;border-radius:10px;font-weight:700;cursor:pointer;text-decoration:none;font-size:12px}}.btn.secondary{{background:#eef2f7;color:#0f172a}}.btn.success{{background:#15803d}}.btn.danger{{background:#dc2626}}
table{{width:100%;border-collapse:collapse;overflow:hidden}}th{{background:#f8fafc;color:#475569;font-size:11px;text-transform:uppercase;letter-spacing:.04em}}th,td{{padding:11px 10px;border-bottom:1px solid #edf1f5;text-align:left;font-size:12px;vertical-align:middle}}tr:hover td{{background:#fafcff}}
.grid-2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.grid-3{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}.badge{{display:inline-block;padding:4px 8px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:10px;font-weight:800}}.search{{max-width:280px}}
@media(max-width:900px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.grid-2,.grid-3{{grid-template-columns:1fr}}.mod{{padding:14px}}table{{display:block;overflow-x:auto;white-space:nowrap}}}}@media(max-width:600px){{.kpis{{grid-template-columns:1fr 1fr}}h1{{font-size:21px}}.search{{max-width:100%}}}}
</style></head><body>{header}<div class='mod'><div class='page-head'><div><div class='eyebrow'>DaviSchool Management System</div><h1>{title}</h1><p>Manage, analyse and act on your school's data from one workspace.</p></div><div style='display:flex;gap:8px'><a class='btn secondary' href='/school/dashboard'>← Dashboard</a><a class='btn' href='/school/my-profile'>👤 Profile</a></div></div>{body}</div></div></div>
<script>document.querySelectorAll('table').forEach(function(t){{var w=document.createElement('div');w.style.overflowX='auto';t.parentNode.insertBefore(w,t);w.appendChild(t);}});document.querySelectorAll('input[type=search]').forEach(function(input){{input.addEventListener('input',function(){{var q=this.value.toLowerCase();var table=this.closest('.card')?.querySelector('table')||document.querySelector('table');if(!table)return;table.querySelectorAll('tr').forEach(function(r,i){{if(i===0)return;r.style.display=r.innerText.toLowerCase().includes(q)?'':'none';}})}})}});</script></body></html>""")

def sid(request):
    s=get_school_obj(request); return s["id"] if s else 0

@app.get("/school/timetable", response_class=HTMLResponse)
def school_timetable(request: Request):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM timetable WHERE school_id=? ORDER BY id DESC",(sid(request),)); rows=cur.fetchall(); con.close()
    tr="".join([f"<tr><td>{r['day']}</td><td>{r['start_time']}-{r['end_time']}</td><td>{r['class_name']} {r['stream'] or ''}</td><td>{r['subject']}</td><td>{r['teacher'] or ''}</td><td>{r['room'] or ''}</td><td><form method='post' action='/school/modules/timetable/delete/{r[0]}' style='display:inline'><button type='submit' onclick='return confirm(\"Delete this timetable entry?\")' style='border:0;background:none;color:#b91c1c;cursor:pointer'>Delete</button></form></td></tr>" for r in rows]) or "<tr><td colspan='7'>No timetable entries yet.</td></tr>"
    body=f"<div class='card'><form method='post' action='/school/modules/timetable/add' style='display:grid;grid-template-columns:repeat(4,1fr);gap:8px'><select name='day' class='input-field'><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option></select><input name='start_time' required type='time' class='input-field'><input name='end_time' required type='time' class='input-field'><input name='class_name' required placeholder='Class' class='input-field'><input name='stream' placeholder='Stream' class='input-field'><input name='subject' required placeholder='Subject' class='input-field'><input name='teacher' placeholder='Teacher' class='input-field'><input name='room' placeholder='Room' class='input-field'><button class='btn'>Add Period</button></form><table style='margin-top:16px'><tr><th>Day</th><th>Time</th><th>Class</th><th>Subject</th><th>Teacher</th><th>Room</th><th>Action</th></tr>{tr}</table></div>"
    return module_page(request,'🗓️ Smart Timetable','timetable',body)
@app.post("/school/modules/timetable/add")
def add_timetable(request:Request,day:str=Form(...),start_time:str=Form(...),end_time:str=Form(...),class_name:str=Form(...),stream:str=Form(''),subject:str=Form(...),teacher:str=Form(''),room:str=Form('')):
    con=get_db(); con.execute("INSERT INTO timetable(school_id,day,start_time,end_time,class_name,stream,subject,teacher,room) VALUES(?,?,?,?,?,?,?,?,?)",(sid(request),day,start_time,end_time,class_name,stream,subject,teacher,room)); con.commit(); con.close(); return RedirectResponse('/school/timetable',303)
@app.post("/school/modules/timetable/delete/{rid}")
def del_timetable(request:Request,rid:int):
    school=get_school_obj(request)
    if not school or not _role_permission(request,"timetable.edit"): return RedirectResponse("/portal",303)
    con=get_db(); con.execute("DELETE FROM timetable WHERE id=? AND school_id=?",(rid,school["id"])); con.commit(); con.close(); return RedirectResponse('/school/timetable',303)

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
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM announcements WHERE school_id=? ORDER BY id DESC",(sid(request),)); rows=cur.fetchall(); con.close()
    tr=''.join([f"<tr><td>{r['created_at']}</td><td>{r['title']}</td><td>{r['audience']}</td><td>{r['message']}</td></tr>" for r in rows]) or "<tr><td colspan='4'>No announcements yet.</td></tr>"
    body=f"<div class='card'><form method='post' action='/school/modules/announcements/add'><input name='title' required placeholder='Announcement title' class='input-field'><textarea name='message' required placeholder='Message' class='input-field' style='min-height:100px'></textarea><select name='audience' class='input-field'><option>All</option><option>Students</option><option>Parents</option><option>Staff</option></select><button class='btn'>Publish Announcement</button></form><table style='margin-top:16px'><tr><th>Date</th><th>Title</th><th>Audience</th><th>Message</th></tr>{tr}</table></div>"
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
    body="<div class='card'><h3>❓ DaviSchool User Manual</h3><ol><li>Admit students in Students Manager.</li><li>Add staff in Staff Manager.</li><li>Configure terms, subjects, classes and exams.</li><li>Set marks before recording marks.</li><li>Record marks using auto-save.</li><li>Use analysis for subject, student and class results.</li><li>Use timetable, finance and communication modules.</li><li>Use System Settings for users, permissions, backups, audit and integrations.</li></ol></div>"; return module_page(request,'❓ User Manual','user-manual',body)

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
    body=f"""<div class='card'><form method='get' style='display:flex;gap:10px;flex-wrap:wrap'><select name='student_id' class='input-field' style='max-width:320px'>{opts}</select><select name='exam_id' class='input-field' style='max-width:260px'>{eopts}</select><button class='btn'>Load Report</button><button type='button' class='btn' onclick='window.print()'>🖨️ Print</button></form></div><div class='card' id='report-card'><div style='text-align:center'><h2 style='margin-bottom:4px'>{school['name'] if school else 'DaviSchool'}</h2><h3 style='margin:4px'>STUDENT REPORT CARD</h3><p>{ex['name'] if ex else ''} — {ex['term'] if ex else ''} {ex['year'] if ex else ''}</p></div><div style='display:flex;justify-content:space-between;margin:18px 0'><div><b>Student:</b> {st['name'] if st else ''}<br><b>Admission:</b> {st['admission_no'] if st else ''}</div><div><b>Total:</b> {total}<br><b>Average:</b> {avg}</div></div><table><tr><th>Subject</th><th>Marks</th><th>Grade</th></tr>{trs}</table><p style='margin-top:20px'><b>Teacher/School Comment:</b> ________________________________</p><p><b>Principal/Head Comment:</b> __________________________________</p></div>"""
    con.close(); return module_page(request,'📄 Report Card','marksheets',body)

@app.get("/school/subject-allocation", response_class=HTMLResponse)
def school_subject_allocation(request:Request): return dean_settings(request,tab='allocation')

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
def global_table_page(request,title,query,headers,active):
    if request.session.get('role')!='super_admin': return RedirectResponse('/')
    con=get_db(); rows=con.execute(query).fetchall(); con.close(); tr=''.join(['<tr>'+''.join(f"<td>{r[k] or ''}</td>" for k in headers.keys())+'</tr>' for r in rows]) or f"<tr><td colspan='{len(headers)}'>No records.</td></tr>"; body=f"<div class='card'><table><tr>{''.join(f'<th>{v}</th>' for v in headers.values())}</tr>{tr}</table></div>"; return module_page(request,title,active,body,True)
@app.get("/super/global-control/timetable",response_class=HTMLResponse)
def global_timetable(request:Request): return global_table_page(request,'🗓️ Smart Timetable — Global',"SELECT t.day,t.start_time,t.end_time,t.class_name,t.subject,s.name school_name FROM timetable t LEFT JOIN schools s ON t.school_id=s.id ORDER BY t.id DESC",{'school_name':'School','day':'Day','start_time':'Start','end_time':'End','class_name':'Class','subject':'Subject'},'timetable')
@app.get("/super/global-control/fees",response_class=HTMLResponse)
def global_fees(request:Request): return global_table_page(request,'💰 Fees & Finance — Global',"SELECT s.name school_name,st.name student_name,f.amount,f.paid,f.status FROM fees f LEFT JOIN schools s ON f.school_id=s.id LEFT JOIN students st ON f.student_id=st.id ORDER BY f.id DESC",{'school_name':'School','student_name':'Student','amount':'Amount','paid':'Paid','status':'Status'},'fees')
@app.get("/super/global-control/communication",response_class=HTMLResponse)
def global_communication(request:Request): return global_table_page(request,'📢 Communication — Global',"SELECT s.name school_name,a.title,a.audience,a.message FROM announcements a LEFT JOIN schools s ON a.school_id=s.id ORDER BY a.id DESC",{'school_name':'School','title':'Title','audience':'Audience','message':'Message'},'communication')
@app.post("/super/global-control/modules/roles/add")
def global_role_add(request:Request,role:str=Form(...),permission:str=Form(...)):
    if request.session.get('role')!='super_admin': return RedirectResponse('/')
    con=get_db(); con.execute("INSERT INTO roles_permissions(school_id,role,permission,enabled) VALUES(0,?,?,1)",(role,permission)); con.commit(); con.close(); return RedirectResponse('/super/global-control/system-settings/roles-permissions',303)
@app.post("/super/global-control/modules/integrations/add")
def global_integration_add(request:Request,name:str=Form(...),status:str=Form(...),config:str=Form('')):
    if request.session.get('role')!='super_admin': return RedirectResponse('/')
    con=get_db(); con.execute("INSERT INTO integrations(school_id,name,status,config) VALUES(0,?,?,?)",(name,status,config)); con.commit(); con.close(); return RedirectResponse('/super/global-control/system-settings/integrations',303)


@app.get("/super/global-control/analysis",response_class=HTMLResponse)
def global_analysis(request:Request):
    return global_table_page(request,'📊 Exam Analysis — Global',"SELECT sub.name subject,ROUND(AVG(CAST(m.marks AS REAL)),2) average,COUNT(m.id) entries FROM marks m JOIN subjects sub ON m.subject_id=sub.id GROUP BY sub.id,sub.name ORDER BY sub.name",{'subject':'Subject','average':'Average','entries':'Entries'},'analysis')
@app.get("/super/global-control/spreadsheet",response_class=HTMLResponse)
def global_spreadsheet(request:Request):
    return global_table_page(request,'📑 Spreadsheet — Global',"SELECT s.name student,sub.name subject,e.name exam,m.marks FROM marks m JOIN students s ON m.student_id=s.id JOIN subjects sub ON m.subject_id=sub.id JOIN exams e ON m.exam_id=e.id ORDER BY s.name,sub.name",{'student':'Student','subject':'Subject','exam':'Exam','marks':'Marks'},'spreadsheet')
@app.get("/super/global-control/sba",response_class=HTMLResponse)
def global_sba(request:Request):
    return global_table_page(request,'📋 SBA (KNEC CBA) — Global',"SELECT s.name school,COUNT(DISTINCT st.id) students,COUNT(DISTINCT sub.id) subjects,COUNT(m.id) assessments FROM schools s LEFT JOIN students st ON st.school_id=s.id LEFT JOIN subjects sub ON sub.school_id=s.id LEFT JOIN marks m ON m.school_id=s.id GROUP BY s.id,s.name ORDER BY s.name",{'school':'School','students':'Students','subjects':'Subjects','assessments':'Assessments'},'sba')
@app.get("/super/global-control/sms",response_class=HTMLResponse)
def global_sms(request:Request):
    return global_table_page(request,'💬 Bulk SMS Parents — Global',"SELECT s.name school,x.recipient,x.message,x.status FROM sms_logs x LEFT JOIN schools s ON x.school_id=s.id ORDER BY x.id DESC",{'school':'School','recipient':'Recipient','message':'Message','status':'Status'},'sms')
@app.get("/super/global-control/subject-allocation",response_class=HTMLResponse)
def global_subject_allocation(request:Request):
    return global_dean_settings(request,tab='allocation')
@app.get("/super/global-control/edit-marks",response_class=HTMLResponse)
def global_edit_marks(request:Request):
    return global_table_page(request,'📄 Edit Marks — Global',"SELECT s.name student,sub.name subject,e.name exam,m.marks FROM marks m JOIN students s ON m.student_id=s.id JOIN subjects sub ON m.subject_id=sub.id JOIN exams e ON m.exam_id=e.id ORDER BY s.name,sub.name",{'student':'Student','subject':'Subject','exam':'Exam','marks':'Marks'},'edit-marks')
@app.get("/super/global-control/marks-status",response_class=HTMLResponse)
def global_marks_status(request:Request):
    return global_table_page(request,'☰ Marks Status — Global',"SELECT s.name student,sub.name subject,e.name exam,m.marks FROM marks m JOIN students s ON m.student_id=s.id JOIN subjects sub ON m.subject_id=sub.id JOIN exams e ON m.exam_id=e.id ORDER BY s.name,sub.name",{'student':'Student','subject':'Subject','exam':'Exam','marks':'Marks'},'marks-status')

@app.get("/super/global-control/report-cards", response_class=HTMLResponse)
def global_report_cards(request:Request):
    return global_table_page(request,'📄 Report Cards — Global',"SELECT sc.name school,s.name student,e.name exam,COUNT(m.id) subjects,ROUND(AVG(CAST(m.marks AS REAL)),2) average FROM marks m JOIN schools sc ON sc.id=m.school_id JOIN students s ON s.id=m.student_id JOIN exams e ON e.id=m.exam_id GROUP BY sc.id,s.id,e.id ORDER BY sc.name,s.name",{'school':'School','student':'Student','exam':'Exam','subjects':'Subjects','average':'Average'},'report-cards')
@app.get("/super/global-control/attendance", response_class=HTMLResponse)
def global_attendance(request:Request):
    return global_table_page(request,'🗓️ Attendance — Global',"SELECT sc.name school,s.name student,a.date,a.status FROM attendance a JOIN schools sc ON sc.id=a.school_id JOIN students s ON s.id=a.student_id ORDER BY a.id DESC",{'school':'School','student':'Student','date':'Date','status':'Status'},'attendance')

@app.get("/super/global-control/{path}", response_class=HTMLResponse)
def global_other(path: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma"); header = global_header(name, path)
    body=f"<div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:30px'><h3 style='margin:0'>{path.replace('-', ' ').title()}</h3><p style='color:#64748b;font-size:13px'>This navigation window is active and reserved for the module's detailed workspace. Existing data modules remain available from the sidebar.</p></div>"
    return HTMLResponse(f"<html><body>{header}<div style='padding:30px'>{body}</div></div></div></body></html>")

# ============================================================
# DAVISCHOOL COMPLETE RECORD MANAGEMENT EXTENSION
# These routes are additive: existing working routes/design are preserved.
# ============================================================

def _school_user(request: Request):
    # Legacy /school routes are retained for compatibility, but the unified
    # /app workspace and dedicated role portals are now the supported workflow.
    # Do not expose legacy school controls to teacher/accountant/registrar/
    # parent/student sessions.
    role = str(request.session.get("role", ""))
    if role not in {"school_admin", "super_admin"}:
        return None
    school = get_school_obj(request)
    if not school or not request.session.get("email"):
        return None
    return school

def _safe_school_redirect(request: Request, fallback="/school/dashboard"):
    return fallback if _school_user(request) else "/"

@app.get("/school/staff", response_class=HTMLResponse)
def school_staff_alias(request: Request):
    return teachers_page(request)

@app.get("/school/students/{student_id}", response_class=HTMLResponse)
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
    body=f"""<div class='card'><h2>✏️ Edit Student</h2><form method='post' action='/school/students/{student_id}/edit' class='form-grid'><label>Admission No<input name='admission_no' value='{st['admission_no'] or ''}' required class='input-field'></label><label>Assessment No<input name='assessment_no' value='{st['assessment_no'] or ''}' class='input-field'></label><label style='grid-column:span 2'>Full Name<input name='student_name' value='{st['name'] or ''}' required class='input-field'></label><label>Class<select name='class_id' class='input-field'>{opts}</select></label><label>Gender<select name='gender' class='input-field'><option {'selected' if st['gender']=='Male' else ''}>Male</option><option {'selected' if st['gender']=='Female' else ''}>Female</option></select></label><label>Category<select name='category' class='input-field'><option {'selected' if (st['category'] or 'Day')=='Day' else ''}>Day</option><option {'selected' if st['category']=='Boarding' else ''}>Boarding</option></select></label><label>Guardian<input name='guardian_name' value='{st['guardian_name'] or ''}' class='input-field'></label><label style='grid-column:span 2'>Guardian Phone<input name='parent_phone' value='{st['parent_phone'] or ''}' class='input-field'></label><button class='btn' style='grid-column:span 2'>💾 Save Changes</button></form></div>"""
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
    body=f"""<div class='card'><h2>✏️ Edit Staff Member</h2><form method='post' action='/school/teachers/{teacher_id}/edit' class='form-grid'><label>Full Name<input name='name' value='{t['name'] or ''}' required class='input-field'></label><label>TSC No<input name='tsc_no' value='{t['tsc_no'] or ''}' class='input-field'></label><label>ID No<input name='id_no' value='{t['id_no'] or ''}' class='input-field'></label><label>Gender<select name='gender' class='input-field'><option {'selected' if t['gender']=='Male' else ''}>Male</option><option {'selected' if t['gender']=='Female' else ''}>Female</option></select></label><label>Role<input name='role' value='{t['role'] or ''}' class='input-field'></label><label>Employment Type<input name='employment_type' value='{t['employment_type'] or 'Teaching'}' class='input-field'></label><label>Phone<input name='phone' value='{t['phone'] or ''}' class='input-field'></label><label>Email<input name='email' type='email' value='{t['email'] or ''}' class='input-field'></label><button class='btn' style='grid-column:span 2'>💾 Save Changes</button></form></div>"""
    return module_page(request,"Edit Staff","staff",body)

@app.post("/school/teachers/{teacher_id}/edit")
def school_teacher_edit_save(teacher_id:int, request:Request, name:str=Form(...), tsc_no:str=Form(""), id_no:str=Form(""), gender:str=Form(""), role:str=Form(""), phone:str=Form(""), email:str=Form(""), employment_type:str=Form("Teaching")):
    school=_school_user(request)
    if not school: return RedirectResponse("/",303)
    con=get_db(); con.execute("UPDATE teachers SET name=?,tsc_no=?,id_no=?,gender=?,role=?,phone=?,email=?,employment_type=? WHERE id=? AND school_id=?",(name.strip().upper(),tsc_no.strip(),id_no.strip(),gender,role.strip(),phone.strip(),email.strip(),employment_type.strip(),teacher_id,school["id"])); con.commit(); con.close(); return RedirectResponse("/school/teachers",303)

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
    if not school or request.session.get("role") not in ("school_admin", "super_admin"):
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
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
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
    con.close(); title=path.replace('/',' • ').replace('-',' ').title(); body=f"<div class='grid-3'><a class='ds-card' href='/school/dashboard'><b>📊 Overview</b><p>Return to the school performance dashboard.</p></a><a class='ds-card' href='/school/students'><b>🎓 Student Records</b><p>Manage enrolment, profiles and academic history.</p></a><a class='ds-card' href='/school/analysis'><b>📈 Analytics</b><p>Review subject, student and class performance.</p></a></div><div class='card'><h3>{title} workspace</h3><p>This workspace is connected to the DaviSchool data model. Use the related module links above to create records and review live school data.</p></div>"; return module_page(request,title,path,body)


# === DAVISCHOOL OPERATIONS COMPLETION ===
def _require_school_admin(request: Request):
    school=_school_user(request)
    if not school or request.session.get('role') not in ('school_admin','super_admin'): return None
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
    if request.session.get('role') not in ('teacher','parent','student'): return RedirectResponse('/',303)
    school=get_school_obj(request)
    if not school: return RedirectResponse('/',303)
    con=get_db(); cur=con.cursor(); role=request.session['role']; student_id=request.session.get('student_id'); teacher_id=request.session.get('teacher_id')
    if role=='teacher':
        t=cur.execute('SELECT * FROM teachers WHERE id=? AND school_id=?',(teacher_id,school['id'])).fetchone() if teacher_id else None
        alloc=cur.execute('SELECT ta.*,s.name subject,c.name class_name,c.stream FROM teacher_allocations ta JOIN subjects s ON s.id=ta.subject_id JOIN classes c ON c.id=ta.class_id WHERE ta.teacher_id=? AND ta.school_id=?',(teacher_id,school['id'])).fetchall() if teacher_id else []
        body=f"<div class='card'><h2>👨‍🏫 Teacher Portal</h2><p>Welcome {t['name'] if t else request.session.get('name','Teacher')}.</p><table><tr><th>Subject</th><th>Class</th><th>Stream</th></tr>"+''.join(f"<tr><td>{a['subject']}</td><td>{a['class_name']}</td><td>{a['stream'] or ''}</td></tr>" for a in alloc)+"</table><div style='margin-top:12px'><a class='btn' href='/school/record-marks'>✏️ Record Marks</a></div></div>"
    else:
        st=cur.execute('SELECT * FROM students WHERE id=? AND school_id=?',(student_id,school['id'])).fetchone() if student_id else None
        marks=cur.execute('SELECT sub.name subject,e.name exam,m.marks,e.term,e.year FROM marks m JOIN subjects sub ON sub.id=m.subject_id JOIN exams e ON e.id=m.exam_id WHERE m.student_id=? AND m.school_id=? ORDER BY e.year DESC,e.id DESC',(student_id,school['id'])).fetchall() if student_id else []
        fee=cur.execute('SELECT COALESCE(SUM(amount),0) expected,COALESCE(SUM(paid),0) paid FROM fees WHERE student_id=? AND school_id=?',(student_id,school['id'])).fetchone() if student_id else {'expected':0,'paid':0}
        body=f"<div class='card'><h2>🎓 {'Parent' if role=='parent' else 'Student'} Portal</h2><p>{st['name'] if st else 'Linked student account'}</p><p>Fee balance: <b>KES {float(fee['expected'] or 0)-float(fee['paid'] or 0):,.2f}</b></p><table><tr><th>Subject</th><th>Exam</th><th>Marks</th><th>Term</th></tr>"+''.join(f"<tr><td>{m['subject']}</td><td>{m['exam']}</td><td>{m['marks']}</td><td>{m['term']} {m['year']}</td></tr>" for m in marks)+"</table></div>"
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
            f"<p><a href='/app'>Return to DaviSchool</a></p></div>",
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




# DaviSchool unified application UI
from app.new_ui import router as new_ui_router
app.include_router(new_ui_router)


# Disable the legacy /school interface. The new DaviSchool /app interface is the only school UI.
from app.legacy_redirect import install_legacy_school_redirect
install_legacy_school_redirect(app)
