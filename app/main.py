from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random, json, smtplib, ssl
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage
import os

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v26-roles")
SUPER_ADMIN = "oumadavis62@gmail.com"
EMAIL_SENDER = SUPER_ADMIN
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# === ROLES PERMISSION MAP - ZERAKI STYLE ===
ROLE_PERMISSIONS = {
    "school_admin": ["dashboard","students","classes","subjects","exams","marks","marksheets","ranking","analysis","reports","timetable","fees","sms","staff","profile"],
    "deputy_principal": ["dashboard","students","classes","subjects","exams","marks","marksheets","ranking","analysis","reports","timetable","fees","sms","profile"],
    "dos": ["dashboard","students","exams","marks","marksheets","ranking","analysis","reports","profile"],
    "hod": ["dashboard","students","marks","marksheets","analysis","reports","profile"],
    "teacher": ["dashboard","students","marks","marksheets","profile"],
    "bursar": ["dashboard","students","fees","profile"],
    "class_teacher": ["dashboard","students","marks","marksheets","profile"],
}

ROLE_LABELS = {
    "school_admin": "Principal - Full Control",
    "deputy_principal": "Deputy Principal",
    "dos": "Director of Studies",
    "hod": "HOD",
    "teacher": "Teacher - Limited",
    "bursar": "Bursar - Fees Only",
    "class_teacher": "Class Teacher"
}

def has_permission(role, page):
    if role == "super_admin": return True
    perms = ROLE_PERMISSIONS.get(role, [])
    return page in perms

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
    try: cur.execute("ALTER TABLE schools ADD COLUMN phone TEXT")
    except: pass
    try: cur.execute("ALTER TABLE schools ADD COLUMN principal TEXT")
    except: pass
    try: cur.execute("ALTER TABLE schools ADD COLUMN school_type TEXT")
    except: pass
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT)")
    try: cur.execute("ALTER TABLE classes ADD COLUMN class_name TEXT")
    except: pass
    try: cur.execute("ALTER TABLE classes ADD COLUMN stream TEXT")
    except: pass
    try: cur.execute("ALTER TABLE classes ADD COLUMN class_teacher_id INTEGER")
    except: pass
    try: cur.execute("ALTER TABLE classes ADD COLUMN class_teacher_name TEXT")
    except: pass
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_name TEXT, parent_phone TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, exam_id INTEGER, student_id INTEGER, subject_id INTEGER, score INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, term TEXT, total INTEGER, paid INTEGER, balance INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS timetable (id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER, day TEXT, period TEXT, subject TEXT, teacher TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS sms_logs (id INTEGER PRIMARY KEY, school_id INTEGER, recipient TEXT, message TEXT, timestamp TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit()
    con.close()
init_db()

def generate_unique_password(school_name):
    prefix = "".join([c for c in school_name.upper() if c.isalpha()])[:4]
    if len(prefix) < 3: prefix = "SCH"
    num = random.randint(1000, 9999)
    return f"{prefix}@{num}!"

def send_email(to_email, subject, body):
    if not EMAIL_PASSWORD: return False
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER; msg["To"] = to_email; msg["Subject"] = subject
        msg.set_content(body)
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context); server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.send_message(msg)
        return True
    except: return False

def log_activity(email, action, details=""):
    try:
        con = get_db(); cur = con.cursor()
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO activity_log (email, action, details, timestamp) VALUES (?,?,?,?)", (email, action, details, ts))
        con.commit(); con.close()
    except: pass

def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin": return None
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone(); con.close(); return s

def header_html(initials, name, email):
    return f"""
    <style>
.do-avatar {{ width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; cursor:pointer; border:2px solid #e2e8f0; user-select:none; }}
.dropdown-item {{ display:flex; align-items:center; gap:10px; padding:11px 14px; text-decoration:none; font-size:13px; }}
.dropdown-item-profile {{ color:#0f172a; border-bottom:1px solid #f8fafc; }}
.dropdown-item-profile:hover {{ background:#0f172a; color:white; }}
.dropdown-item-logout {{ color:#dc2626; }}
.dropdown-item-logout:hover {{ background:#0f172a; color:white; }}
    </style>
    <div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; position:relative'>
        <div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px; color:#64748b'>{name} • Super Admin</div></div>
        <div style='position:relative'>
            <div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div>
            <div id='profileDropdown' style='display:none; position:absolute; right:0; top:44px; background:white; border:1px solid #e2e8f0; border-radius:12px; width:220px; box-shadow:0 10px 25px rgba(0,0,0,0.12); z-index:1000; overflow:hidden'>
                <div style='padding:14px; border-bottom:1px solid #f1f5f9; background:#f8fafc'><div style='font-weight:700; font-size:13px'>{name}</div><div style='font-size:11px; color:#64748b'>{email}</div><div style='margin-top:6px'><span style='background:#e0f2fe; color:#0369a1; padding:3px 8px; border-radius:20px; font-size:10px'>Super Admin</span></div></div>
                <a href='/profile?tab=personal' class='dropdown-item dropdown-item-profile'>👤 Profile</a>
                <a href='/logout' class='dropdown-item dropdown-item-logout'>🚪 Logout</a>
            </div>
        </div>
    </div>
    <script>
    function toggleProfileMenu(){{ let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none'; }}
    document.addEventListener('click', function(e){{ let b=e.target.closest('.do-avatar'); let menu=document.getElementById('profileDropdown'); if(!b && menu &&!menu.contains(e.target)){{ menu.style.display='none'; }} }});
    </script>
    """

def school_header(school, name, active="dashboard", role="school_admin"):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    role_label = ROLE_LABELS.get(role, role)
    def nav(link, icon, label):
        if not has_permission(role, link): return ""
        a = "background:#0f172a; color:white; font-weight:700" if active==link else "color:#475569;"
        return f"<a href='/school/{link}' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; margin-bottom:4px; {a}'>{icon} {label}</a>"
    staff_link = ""
    if role == "school_admin":
        sa = "background:#0f172a; color:white; font-weight:700" if active=="staff" else "color:#7c3aed;"
        staff_link = f"<a href='/school/staff' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; margin-bottom:4px; {sa}'>👥 Staff & Roles</a>"
    return f"""
    <div style='display:flex; min-height:100vh'>
    <div style='width:260px; background:white; border-right:1px solid #e2e8f0; padding:16px; position:sticky; top:0; height:100vh; overflow-y:auto'>
        <div style='padding:10px 6px 16px; border-bottom:1px solid #f1f5f9; margin-bottom:12px'><div style='display:flex; align-items:center; gap:10px'><div style='width:40px; height:40px; background:#0f172a; color:white; border-radius:10px; display:flex; align-items:center; justify-content:center; font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20]}</b><div style='font-size:10px; color:#64748b'>🔑 {school['code']} | {role_label}</div></div></div></div>
        {nav('dashboard','📊','Dashboard')}
        {nav('students','🎓','Students')}
        {nav('classes','🏫','Classes & Streams')}
        {nav('subjects','📚','Subjects')}
        {nav('exams','📝','Exams')}
        {nav('marks','✍️','Enter Marks')}
        {nav('marksheets','📄','MarkSheets')}
        {nav('ranking','🏆','Ranking')}
        {nav('analysis','📈','Exam Analysis')}
        {nav('reports','📑','Student Reports')}
        {nav('timetable','🗓️','Smart Timetable')}
        {nav('fees','💰','Fees & Finance')}
        {nav('sms','💬','Bulk SMS Parents')}
        {staff_link}
        <div style='margin-top:16px; border-top:1px solid #f1f5f9; padding-top:12px'>
        <a href='/profile?tab=personal' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; color:#475569;'>👤 My Profile ({role_label})</a>
        <a href='/logout' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; color:#dc2626;'>🚪 Logout</a>
        </div>
        <div style='margin-top:12px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:10px'><div style='font-size:10px; font-weight:700; color:#166534'>✅ DaviSchool - {role_label}</div><div style='font-size:9px; color:#15803d; margin-top:4px'>Role limited access - Zeraki style</div></div>
    </div>
    <div style='flex:1; background:#f8fafc'>
        <div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'>
            <div><b style='font-size:14px'>DaviSchool Analytics 🚀 - {role_label}</b><div style='font-size:11px; color:#64748b'>{name} • {school['name']}</div></div>
            <div style='display:flex; align-items:center; gap:10px'><span style='font-size:11px; background:#ede9fe; color:#5b21b6; padding:6px 10px; border-radius:20px'>{role_label}</span><div style='width:36px; height:36px; background:#dcfce7; color:#166534; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800'>{initials}</div></div>
        </div>
    """

@app.get("/health")
def health(): return PlainTextResponse("OK")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2><p style='font-size:11px; color:#64748b'>ONE LOGIN FOR ALL ROLES 🔐</p></div><form method='post' action='/login'><input name='email' placeholder='📧 Email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='🔑 Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In → Auto by Role</button></form></div></body></html>"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    school_info = None
    if u: cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],)); school_info = cur.fetchone()
    con.close()
    if not u: return HTMLResponse("❌ Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    if u["role"]!= "super_admin" and school_info:
        log_activity(u["email"], f"🏫 {u['role']} login: {school_info['name']}", "")
        return RedirectResponse("/school/dashboard", status_code=303)
    log_activity(u["email"], "🔓 Super Admin Logged in", "")
    return RedirectResponse("/dashboard", status_code=303)

# SUPER ADMIN - UNTOUCHED
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools"); total = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5"); recent = cur.fetchall(); con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    log_activity(email, "📊 Viewed dashboard", "School Overview")
    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
    if not rows: rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
    content = f"""
    <style>.quick-btn{{display:block; background:white; border:1px solid #e2e8f0; color:#0f172a; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600;}}.quick-btn:hover{{background:#0f172a; color:white;}}.quick-btn-light{{display:block; background:white; border:1px solid #e2e8f0; color:#64748b; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600;}}.quick-btn-light:hover{{background:#0f172a; color:white;}}</style>
    <div style='padding:24px'><div style='margin-bottom:20px'><h2 style='margin:0; font-size:22px; font-weight:800'>📊 School Overview</h2><p style='color:#64748b; font-size:13px'>Welcome {name}</p></div>
    <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div><div style='font-size:11px; color:#16a34a; margin-top:6px'>📈 Up 12% from last month</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div><div style='font-size:11px; color:#16a34a; margin-top:6px'>🟢 100% operational</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>💰 TOTAL REVENUE</div><div style='font-size:28px; font-weight:800; margin-top:8px'>KES {total*15000:,}</div><div style='font-size:11px; color:#16a34a; margin-top:6px'>💹 +8% monthly growth</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total*350:,}</div><div style='font-size:11px; color:#64748b; margin-top:6px'>👥 Avg 350 per school</div></div>
    </div>
    <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>🏫 Recently Added Schools</b><a href='/schools/manage' style='font-size:12px; color:#2563eb; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Location</th><th style='padding:10px; text-align:left'>Status</th><th style='padding:10px; text-align:left'>Date</th></tr>{rows}</table></div>
    <div style='display:flex; flex-direction:column; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><b>⚡ Quick Actions</b><div style='margin-top:12px; display:flex; flex-direction:column; gap:8px'><a href='/schools/manage' class='quick-btn'>🏫 Manage Schools</a><a href='/schools/manage?show=add' class='quick-btn-light'>➕ Register New School</a></div></div>
    <div style='background:#0f172a; border-radius:14px; padding:18px; color:white'><div style='font-size:13px; font-weight:700'>📊 Davischool Analytics</div><div style='font-size:11px; color:#94a3b8; margin-top:6px'>🛠️ All {total} schools are active</div><div style='margin-top:12px; background:#1e293b; border-radius:8px; padding:10px'><div style='font-size:10px; color:#94a3b8'>🔧 PLATFORM HEALTH</div><div style='font-size:18px; font-weight:700; color:#4ade80; margin-top:4px'>✅ 99.9% Uptime</div><div style='font-size:10px; color:#64748b; margin-top:4px'>⚡ System running smoothly</div></div></div></div></div></div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; margin:0; background:#f8fafc'>{header_html(initials, name, email)}{content}</body></html>")

def school_list_page(request, title, active, table_html, form_html):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name",""); role = request.session.get("role","school_admin")
    html = school_header(school, name, active, role)
    html += f"<div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>{table_html}</div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; position:sticky; top:20px'><b>{title}</b>{form_html}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

def require_perm(page):
    def decorator(func):
        def wrapper(request: Request, *args, **kwargs):
            role = request.session.get("role","")
            if not has_permission(role, page):
                return HTMLResponse(f"<html><body style='font-family:Arial; text-align:center; padding:40px'><h2>🚫 Access Denied</h2><p>Your role <b>{ROLE_LABELS.get(role, role)}</b> cannot access <b>{page}</b></p><p style='font-size:12px; color:#64748b'>Zeraki style: Teachers limited to marks only</p><a href='/school/dashboard' style='background:#0f172a; color:white; padding:10px 18px; border-radius:8px; text-decoration:none'>← Back to Dashboard</a></body></html>")
            return func(request, *args, **kwargs)
        return wrapper
    return decorator

# SCHOOL DASHBOARD WITH ROLE
@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school:
        if request.session.get("role")=="super_admin": return RedirectResponse("/dashboard")
        return RedirectResponse("/")
    name = request.session.get("name",""); role = request.session.get("role","school_admin")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]
    con.close()
    html = school_header(school, name, "dashboard", role)
    html += f"""
        <div style='padding:20px'>
            <div style='background:linear-gradient(135deg,#0f172a,#1e40af); border-radius:16px; padding:20px; color:white'>
                <h2 style='margin:0'>DaviSchool Analytics 🚀 - {ROLE_LABELS.get(role, role)}</h2>
                <p style='margin:6px 0 0; font-size:13px; color:#bfdbfe'>Role: {role} | Permissions: {', '.join(ROLE_PERMISSIONS.get(role, []))}</p>
            </div>
            <div style='display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-top:16px'>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-size:11px'>🎓 Students</div><div style='font-size:24px; font-weight:800'>{sc}</div></div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-size:11px'>🏫 Classes</div><div style='font-size:24px; font-weight:800'>{cc}</div></div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-size:11px'>📝 Exams</div><div style='font-size:24px; font-weight:800'>{ec}</div></div>
            </div>
            <div style='margin-top:16px; background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>
                <b>Your Access - Zeraki Style</b>
                <div style='margin-top:10px; display:flex; flex-wrap:wrap; gap:8px'>
                {''.join([f"<span style='background:#f1f5f9; border:1px solid #e2e8f0; padding:6px 10px; border-radius:20px; font-size:11px'>{p}</span>" for p in ROLE_PERMISSIONS.get(role, [])])}
                </div>
                <div style='margin-top:12px; font-size:11px; color:#64748b'>Principal sees Staff & Roles to add you. Teachers see only limited menu.</div>
            </div>
        </div></div></div>
    """
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

# ========== STAFF & ROLES PAGE - ONLY PRINCIPAL ==========
@app.get("/school/staff", response_class=HTMLResponse)
def school_staff(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    role = request.session.get("role","")
    if role!= "school_admin":
        return HTMLResponse(f"<html><body style='font-family:Arial; text-align:center; padding:40px'><h2>🚫 Only Principal Can Manage Staff</h2><p>Your role: {ROLE_LABELS.get(role, role)}</p><a href='/school/dashboard'>← Back</a></body></html>")
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE school_id=? ORDER BY role, full_name", (school["id"],)); staff = cur.fetchall()
    con.close()
    rows = ""
    for s in staff:
        is_principal = s["role"] == "school_admin"
        del_btn = "" if is_principal else f"<a href='/school/staff/delete/{s['id']}' onclick=\"return confirm('Delete {s['full_name']}?')\" style='color:#dc2626; font-size:11px'>🗑️ Delete</a>"
        rows += f"<tr><td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>{s['full_name']}</b><div style='font-size:10px; color:#64748b'>{s['email']}</div></td><td style='padding:10px; border-bottom:1px solid #eee'><span style='background:#ede9fe; color:#5b21b6; padding:4px 8px; border-radius:20px; font-size:10px'>{ROLE_LABELS.get(s['role'], s['role'])}</span></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{s['password']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{del_btn}</td></tr>"
    table = f"<b>👥 Staff & Roles ({len(staff)}) - Principal Control</b><div style='font-size:11px; color:#64748b; margin-top:4px'>Only Principal can add/edit/delete. Teachers limited.</div><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>Name / Email</th><th style='padding:10px; text-align:left'>Role</th><th style='padding:10px; text-align:left'>Password</th><th style='padding:10px; text-align:left'>Action</th></tr>{rows}</table>"
    form = """
    <form method='post' action='/school/staff/add' style='display:flex; flex-direction:column; gap:12px; margin-top:12px'>
        <div><label style='font-size:11px; font-weight:600'>👤 Full Name *</label><input name='full_name' placeholder='e.g. John Otieno' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'></div>
        <div><label style='font-size:11px; font-weight:600'>📧 Email (Username) *</label><input name='email' placeholder='teacher@school.com' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'></div>
        <div><label style='font-size:11px; font-weight:600'>🎭 Role *</label><select name='role' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px; background:white'>
            <option value=''>Select Role *</option>
            <option value='deputy_principal'>Deputy Principal</option>
            <option value='dos'>Director of Studies (DOS)</option>
            <option value='hod'>HOD</option>
            <option value='teacher'>Teacher - Limited (Marks Only)</option>
            <option value='class_teacher'>Class Teacher</option>
            <option value='bursar'>Bursar - Fees Only</option>
        </select></div>
        <div><label style='font-size:11px; font-weight:600'>🔑 Password (manual for now) *</label><input name='password' placeholder='e.g. Teach@1234' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'></div>
        <button style='background:#7c3aed; color:white; padding:13px; border:none; border-radius:10px; font-weight:700'>➕ Add Staff - Manual Password</button>
        <div style='background:#f5f3ff; border:1px solid #ddd6fe; border-radius:8px; padding:10px; font-size:10px; color:#5b21b6'>Next step: auto generate username & password</div>
    </form>
    """
    return school_list_page(request, "👥 Add Staff (Principal Only)", "staff", table, form)

@app.post("/school/staff/add")
def add_staff(request: Request, full_name: str = Form(...), email: str = Form(...), role: str = Form(...), password: str = Form(...)):
    if request.session.get("role")!= "school_admin": return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (email.strip(), password.strip(), role, full_name.strip(), school["id"]))
    con.commit(); con.close()
    log_activity(request.session.get("email",""), f"👥 Principal added staff: {full_name} as {role}", "")
    return RedirectResponse("/school/staff", status_code=303)

@app.get("/school/staff/delete/{uid}")
def del_staff(uid: int, request: Request):
    if request.session.get("role")!= "school_admin": return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id=? AND school_id=?", (uid, school["id"])); u = cur.fetchone()
    if u and u["role"]!= "school_admin":
        cur.execute("DELETE FROM users WHERE id=? AND school_id=?", (uid, school["id"]))
    con.commit(); con.close()
    return RedirectResponse("/school/staff", status_code=303)

# ========== CLASSES WITH CLASS TEACHER DROPDOWN ==========
@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    role = request.session.get("role","")
    if not has_permission(role, "classes"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY id DESC", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT id, full_name, role FROM users WHERE school_id=? AND role IN ('teacher','class_teacher','hod','deputy_principal','dos') ORDER BY full_name", (school["id"],)); teachers = cur.fetchall()
    cur.execute("SELECT id, full_name FROM users WHERE school_id=? ORDER BY full_name", (school["id"],)); all_staff = cur.fetchall()
    cur.execute("SELECT c.id, COUNT(s.id) cnt FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.school_id=? WHERE c.school_id=? GROUP BY c.id", (school["id"], school["id"])); counts = {r[0]: r[1] for r in cur.fetchall()}
    con.close()
    if teachers:
        teacher_options = "".join([f"<option value='{t['id']}|{t['full_name']}'>👨‍🏫 {t['full_name']} ({ROLE_LABELS.get(t['role'], t['role'])})</option>" for t in teachers])
    else:
        teacher_options = "".join([f"<option value='{s['id']}|{s['full_name']}'>👨‍🏫 {s['full_name']}</option>" for s in all_staff]) or "<option value=''>⚠️ No teachers yet - Add in Staff & Roles first</option>"
    rows = ""
    for c in classes:
        ct = c["class_teacher_name"] or "Not Assigned"
        cname = c["class_name"] or c["name"]
        stream = c["stream"] or "-"
        rows += f"<tr><td style='padding:10px; border-bottom:1px solid #eee'><b>{cname}</b></td><td style='padding:10px; border-bottom:1px solid #eee'>{stream}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>👨‍🏫 {ct}</td><td style='padding:10px; border-bottom:1px solid #eee'>{c['level']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{counts.get(c['id'],0)}</td><td style='padding:10px; border-bottom:1px solid #eee'><a href='/school/class/delete/{c['id']}' style='color:#dc2626'>🗑️</a></td></tr>"
    if not rows: rows = "<tr><td colspan=6 style='padding:20px; text-align:center; color:#999'>No classes yet</td></tr>"
    table = f"<b>🏫 Classes & Streams ({len(classes)})</b><div style='font-size:11px; color:#64748b'>Class Teacher from dropdown of teachers you added</div><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>Class</th><th style='padding:10px; text-align:left'>Stream</th><th style='padding:10px; text-align:left'>Class Teacher</th><th style='padding:10px; text-align:left'>Level</th><th>Students</th><th>Action</th></tr>{rows}</table>"
    form = f"""
    <form method='post' action='/school/classes/add' style='display:flex; flex-direction:column; gap:12px; margin-top:12px'>
        <div><label style='font-size:11px; font-weight:600'>🏫 Class *</label><input name='class_name' placeholder='e.g. Class 8, Form 2' required style='width:100%; padding:12px; border:1px solid #e2e8f0; border-radius:10px; margin-top:4px'></div>
        <div><label style='font-size:11px; font-weight:600'>🔀 Stream *</label><input name='stream' placeholder='e.g. East, West' required style='width:100%; padding:12px; border:1px solid #e2e8f0; border-radius:10px; margin-top:4px'></div>
        <div><label style='font-size:11px; font-weight:600'>👨‍🏫 Class Teacher *</label><select name='class_teacher' required style='width:100%; padding:12px; border:1px solid #e2e8f0; border-radius:10px; margin-top:4px; background:white'><option value=''>Select Teacher *</option>{teacher_options}</select><div style='font-size:10px; color:#64748b; margin-top:4px'>From Staff list - automated</div></div>
        <div><label style='font-size:11px; font-weight:600'>🎓 Level *</label><select name='level' required style='width:100%; padding:12px; border:1px solid #e2e8f0; border-radius:10px; margin-top:4px; background:white'><option value=''>Select Level *</option><option>Pre-Primary</option><option>Primary</option><option>Junior School</option><option>Senior School</option><option>8-4-4</option></select></div>
        <button style='background:#0f172a; color:white; padding:13px; border:none; border-radius:10px; font-weight:700'>➕ Add Class</button>
    </form>
    """
    return school_list_page(request, "➕ Add Class/Stream", "classes", table, form)

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), stream: str = Form(...), class_teacher: str = Form(...), level: str = Form(...)):
    school = get_school_obj(request)
    try: tid, tname = class_teacher.split("|",1); tid=int(tid)
    except: tid=0; tname=class_teacher
    full_name = f"{class_name.strip()} {stream.strip()}"
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO classes (school_id, name, level, class_name, stream, class_teacher_id, class_teacher_name) VALUES (?,?,?,?,?,?,?)", (school["id"], full_name, level, class_name.strip(), stream.strip(), tid, tname.strip()))
    con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/class/delete/{cid}")
def del_class(cid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=? AND school_id=?", (cid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)

# ===== KEEP OTHER ROUTES WITH PERMISSION CHECK =====
@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if not has_permission(request.session.get("role",""), "students"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['name']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['admission_no']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['cname'] or s['class_id']}</td><td><a href='/school/student/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for s in students]) or "<tr><td colspan=4 style='padding:20px; text-align:center'>No students</td></tr>"
    table = f"<b>🎓 Students ({len(students)})</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Adm</th><th>Class</th><th>Action</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/students/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='admission_no' placeholder='Adm No *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='student_name' placeholder='Student Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='class_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Class *</option>{opts}</select><select name='gender' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Male</option><option>Female</option></select><input name='parent_name' placeholder='Parent Name' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='parent_phone' placeholder='Parent Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add Student</button></form>"
    return school_list_page(request, "Add Student", "students", table, form)

@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_name: str = Form(...), parent_phone: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO students (school_id, admission_no, name, class_id, gender, parent_name, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], admission_no.strip(), student_name.strip(), class_id, gender, parent_name, parent_phone)); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/student/delete/{sid}")
def del_student(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    if not has_permission(request.session.get("role",""), "subjects"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['name']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['code']}</td><td><a href='/school/subject/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No subjects</td></tr>"
    table = f"<b>📚 Subjects ({len(subs)})</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:10px; text-align:left'>Subject</th><th>Code</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/subjects/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='subject_name' placeholder='Subject *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject_code' placeholder='Code' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add</button></form>"
    return school_list_page(request, "Add Subject", "subjects", table, form)

@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), subject_code: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO subjects (school_id, name, code) VALUES (?,?,?)", (school["id"], subject_name.strip(), subject_code.strip())); con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/subject/delete/{sid}")
def del_sub(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    if not has_permission(request.session.get("role",""), "exams"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{e['name']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{e['term']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{e['year']}</td><td><a href='/school/exam/delete/{e['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan=4 style='padding:20px; text-align:center'>No exams</td></tr>"
    table = f"<b>📝 Exams ({len(exams)})</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:10px; text-align:left'>Exam</th><th>Term</th><th>Year</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/exams/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='exam_name' placeholder='Exam Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='term' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' value='2026' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='exam_type' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Main Exam</option><option>CAT</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add Exam</button></form>"
    return school_list_page(request, "Add Exam", "exams", table, form)

@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip(), term, year, exam_type)); con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/exam/delete/{eid}")
def del_exam(eid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM exams WHERE id=? AND school_id=?", (eid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/marks", response_class=HTMLResponse)
def school_marks(request: Request):
    if not has_permission(request.session.get("role",""), "marks"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall(); cur.execute("SELECT id, name FROM students WHERE school_id=? LIMIT 30", (school["id"],)); students = cur.fetchall(); cur.execute("SELECT m.*, s.name as sname, sub.name as subname FROM marks m JOIN students s ON m.student_id=s.id JOIN subjects sub ON m.subject_id=sub.id WHERE m.school_id=? ORDER BY m.id DESC LIMIT 10", (school["id"],)); recent = cur.fetchall(); con.close()
    e_opts = "".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams]); sub_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects]); st_opts = "".join([f"<option value='{st['id']}'>{st['name']}</option>" for st in students])
    rows = "".join([f"<tr><td style='padding:8px; border-bottom:1px solid #eee'>{r['sname']}</td><td style='padding:8px; border-bottom:1px solid #eee'>{r['subname']}</td><td style='padding:8px; border-bottom:1px solid #eee'>{r['score']}</td></tr>" for r in recent]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No marks</td></tr>"
    table = f"<b>✍️ Recent Marks</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px; text-align:left'>Student</th><th>Subject</th><th>Score</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/marks/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><select name='exam_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Exam *</option>{e_opts}</select><select name='subject_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Subject *</option>{sub_opts}</select><select name='student_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Student *</option>{st_opts}</select><input name='score' type='number' min='0' max='100' placeholder='Score *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Save</button></form>"
    return school_list_page(request, "Enter Marks", "marks", table, form)

@app.post("/school/marks/add")
def add_marks(request: Request, exam_id: int = Form(...), subject_id: int = Form(...), student_id: int = Form(...), score: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO marks (school_id, exam_id, student_id, subject_id, score) VALUES (?,?,?,?,?)", (school["id"], exam_id, student_id, subject_id, score)); con.commit(); con.close(); return RedirectResponse("/school/marks", status_code=303)

@app.get("/school/fees", response_class=HTMLResponse)
def school_fees(request: Request):
    if not has_permission(request.session.get("role",""), "fees"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT f.*, s.name as sname FROM fees f JOIN students s ON f.student_id=s.id WHERE f.school_id=?", (school["id"],)); fees = cur.fetchall(); cur.execute("SELECT id, name FROM students WHERE school_id=?", (school["id"],)); students = cur.fetchall(); con.close()
    st_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in students])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{f['sname']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{f['term']}</td><td style='padding:10px; border-bottom:1px solid #eee'>KES {f['total']}</td><td style='padding:10px; border-bottom:1px solid #eee'>KES {f['paid']}</td><td>KES {f['balance']}</td></tr>" for f in fees]) or "<tr><td colspan=5 style='padding:20px; text-align:center'>No fees</td></tr>"
    table = f"<b>💰 Fees</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:10px; text-align:left'>Student</th><th>Term</th><th>Total</th><th>Paid</th><th>Balance</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/fees/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><select name='student_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Student *</option>{st_opts}</select><select name='term' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='total' type='number' placeholder='Total *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='paid' type='number' placeholder='Paid *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Save</button></form>"
    return school_list_page(request, "Record Fees", "fees", table, form)

@app.post("/school/fees/add")
def add_fees(request: Request, student_id: int = Form(...), term: str = Form(...), total: int = Form(...), paid: int = Form(...)):
    school = get_school_obj(request); balance = total - paid; con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO fees (school_id, student_id, term, total, paid, balance) VALUES (?,?,?,?,?,?)", (school["id"], student_id, term, total, paid, balance)); con.commit(); con.close(); return RedirectResponse("/school/fees", status_code=303)

@app.get("/school/marksheets", response_class=HTMLResponse)
def school_marksheets(request: Request):
    if not has_permission(request.session.get("role",""), "marksheets"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); con.close()
    cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><b>{e['name']}</b><div style='font-size:11px'>{e['term']}</div><a href='/school/marksheets/{e['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none'>View</a></div>" for e in exams]) or "No exams"
    html = school_header(school, request.session.get("name",""), "marksheets", request.session.get("role","")) + f"<div style='padding:20px'><h3>📄 MarkSheets</h3><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/marksheets/{exam_id}", response_class=HTMLResponse)
def view_marksheet(exam_id: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE id=?", (exam_id,)); exam = cur.fetchone(); cur.execute("SELECT id, name, admission_no FROM students WHERE school_id=?", (school["id"],)); students = cur.fetchall(); cur.execute("SELECT id, name FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall(); marks_map={}; cur.execute("SELECT student_id, subject_id, score FROM marks WHERE exam_id=?", (exam_id,));
    for r in cur.fetchall(): marks_map[(r["student_id"], r["subject_id"])] = r["score"]
    con.close()
    th="".join([f"<th style='padding:8px; border:1px solid #e2e8f0'>{sub['name'][:6]}</th>" for sub in subjects])
    rows=""
    for st in students:
        scores=[]; total=0
        for sub in subjects:
            sc=marks_map.get((st["id"], sub["id"]), "-")
            scores.append(f"<td style='padding:8px; border:1px solid #eee; text-align:center'>{sc}</td>")
            if isinstance(sc,int): total+=sc
        rows+=f"<tr><td style='padding:8px; border:1px solid #eee'>{st['name']}</td><td style='padding:8px; border:1px solid #eee'>{st['admission_no']}</td>{''.join(scores)}<td style='padding:8px; border:1px solid #eee; font-weight:700'>{total}</td></tr>"
    html = school_header(school, request.session.get("name",""), "marksheets", request.session.get("role","")) + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><b>{exam['name']}</b><button onclick='window.print()' style='float:right; background:#0f172a; color:white; padding:8px 14px; border:none; border-radius:8px'>Print</button><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px; border:1px solid #e2e8f0'>Student</th><th style='padding:8px; border:1px solid #e2e8f0'>Adm</th>{th}<th style='padding:8px; border:1px solid #e2e8f0'>Total</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

@app.get("/school/ranking", response_class=HTMLResponse)
def school_ranking(request: Request):
    if not has_permission(request.session.get("role",""), "ranking"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM exams WHERE school_id=? LIMIT 1", (school["id"],)); e = cur.fetchone(); ranking_rows=""
    if e:
        cur.execute("SELECT s.id, s.name, SUM(m.score) total FROM students s JOIN marks m ON s.id=m.student_id WHERE m.exam_id=? GROUP BY s.id ORDER BY total DESC", (e["id"],));
        for idx,r in enumerate(cur.fetchall(),1): ranking_rows+=f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{idx}</td><td style='padding:10px; border-bottom:1px solid #eee'>{r['name']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-weight:700'>{r['total']}</td></tr>"
    con.close()
    if not ranking_rows: ranking_rows="<tr><td colspan=3 style='padding:20px; text-align:center'>No marks</td></tr>"
    html = school_header(school, request.session.get("name",""), "ranking", request.session.get("role","")) + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><table style='width:100%'><tr style='background:#f8fafc'><th>Rank</th><th>Student</th><th>Total</th></tr>{ranking_rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/analysis", response_class=HTMLResponse)
def school_analysis(request: Request):
    if not has_permission(request.session.get("role",""), "analysis"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT AVG(score) avg FROM marks WHERE school_id=?", (school["id"],)); avg = cur.fetchone()["avg"] or 0; con.close()
    html = school_header(school, request.session.get("name",""), "analysis", request.session.get("role","")) + f"<div style='padding:20px'><b>📈 Analysis</b><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; margin-top:12px'>Avg: {int(avg)}%</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/reports", response_class=HTMLResponse)
def school_reports(request: Request):
    if not has_permission(request.session.get("role",""), "reports"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT s.id, s.name FROM students s WHERE s.school_id=?", (school["id"],)); students = cur.fetchall(); con.close()
    cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><b>{s['name']}</b><a href='/school/report/{s['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none'>Report</a></div>" for s in students]) or "No students"
    html = school_header(school, request.session.get("name",""), "reports", request.session.get("role","")) + f"<div style='padding:20px'><h3>Reports</h3><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/report/{student_id}", response_class=HTMLResponse)
def student_report(student_id: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?", (student_id,)); st = cur.fetchone(); cur.execute("SELECT sub.name, m.score FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.student_id=?", (student_id,)); marks = cur.fetchall(); total=sum([m["score"] for m in marks]); con.close()
    rows="".join([f"<tr><td style='padding:8px; border:1px solid #eee'>{m['name']}</td><td style='padding:8px; border:1px solid #eee; text-align:center'>{m['score']}</td></tr>" for m in marks])
    html = school_header(school, request.session.get("name",""), "reports", request.session.get("role","")) + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px'><h2>{school['name']} Report</h2><div>{st['name']} | Total: {total}</div><table style='width:100%; margin-top:16px; border-collapse:collapse'><tr style='background:#f8fafc'><th>Subject</th><th>Score</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

@app.get("/school/timetable", response_class=HTMLResponse)
def school_timetable(request: Request):
    if not has_permission(request.session.get("role",""), "timetable"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT t.*, c.name as cname FROM timetable t LEFT JOIN classes c ON t.class_id=c.id WHERE t.school_id=?", (school["id"],)); tt = cur.fetchall(); cur.execute("SELECT id, name FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    c_opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{t['day']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{t['period']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{t['cname']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{t['subject']}</td><td>{t['teacher']}</td><td><a href='/school/timetable/delete/{t['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for t in tt]) or "<tr><td colspan=6 style='padding:20px; text-align:center'>No timetable</td></tr>"
    table = f"<b>🗓️ Timetable</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th>Day</th><th>Period</th><th>Class</th><th>Subject</th><th>Teacher</th><th>Action</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/timetable/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><select name='class_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Class *</option>{c_opts}</select><select name='day' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option></select><input name='period' placeholder='Period *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject' placeholder='Subject *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='teacher' placeholder='Teacher *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add</button></form>"
    return school_list_page(request, "Add Lesson", "timetable", table, form)

@app.post("/school/timetable/add")
def add_tt(request: Request, class_id: int = Form(...), day: str = Form(...), period: str = Form(...), subject: str = Form(...), teacher: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO timetable (school_id, class_id, day, period, subject, teacher) VALUES (?,?,?,?,?,?)", (school["id"], class_id, day, period, subject, teacher)); con.commit(); con.close(); return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/timetable/delete/{tid}")
def del_tt(tid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM timetable WHERE id=? AND school_id=?", (tid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/sms", response_class=HTMLResponse)
def school_sms(request: Request):
    if not has_permission(request.session.get("role",""), "sms"): return RedirectResponse("/school/dashboard")
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM sms_logs WHERE school_id=? ORDER BY id DESC LIMIT 20", (school["id"],)); logs = cur.fetchall(); cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]; con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['recipient']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['message'][:60]}</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['timestamp']}</td></tr>" for s in logs]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No SMS</td></tr>"
    table = f"<b>💬 Bulk SMS ({sc} parents)</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th>To</th><th>Message</th><th>Time</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/sms/send' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><select name='target' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value='all'>All Parents ({sc})</option></select><textarea name='message' placeholder='Message' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px; height:100px'></textarea><button style='background:#16a34a; color:white; padding:12px; border:none; border-radius:8px'>Send</button></form>"
    return school_list_page(request, "Send SMS", "sms", table, form)

@app.post("/school/sms/send")
def send_sms(request: Request, target: str = Form(...), message: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT parent_phone FROM students WHERE school_id=?", (school["id"],)); parents = cur.fetchall(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    for p in parents: cur.execute("INSERT INTO sms_logs (school_id, recipient, message, timestamp) VALUES (?,?,?,?)", (school["id"], p["parent_phone"], message, ts))
    con.commit(); con.close(); return RedirectResponse("/school/sms", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email",""); name = request.session.get("name",""); role = request.session.get("role","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    school_obj = get_school_obj(request); is_super = school_obj is None
    hdr = header_html(initials, name, email) if is_super else school_header(school_obj, name, "profile", role) + "<div style='padding:0'>"
    if tab=="security":
        right = f"<div><b>🔒 Security - {ROLE_LABELS.get(role, role)}</b><form method='post' action='/update-password' style='margin-top:18px'><input name='current_password' type='password' placeholder='Current' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:8px'><input name='new_password' type='password' placeholder='New Password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:8px'><input name='confirm_password' type='password' placeholder='Confirm' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:8px'><button style='margin-top:12px; background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:8px'>Update</button></form></div>"
    elif tab=="activity":
        con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 50", (email,)); logs = cur.fetchall(); con.close()
        log_rows = "".join([f"<div style='padding:12px; border-bottom:1px solid #f1f5f9'><div style='font-size:12px; font-weight:600'>{l['action']}</div><div style='font-size:10px; color:#94a3b8'>{l['timestamp']}</div></div>" for l in logs]) or "No activity"
        right = f"<div><b>📜 Activity - {ROLE_LABELS.get(role, role)}</b><div style='border:1px solid #e2e8f0; border-radius:10px; margin-top:12px'>{log_rows}</div></div>"
    else:
        right = f"<div><b>👤 Personal - {ROLE_LABELS.get(role, role)} (Principal Profile)</b><form method='post' action='/update-profile' style='margin-top:18px'><input name='full_name' value='{name}' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='email_new' value='{email}' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:8px'><div style='margin-top:8px; font-size:11px; color:#64748b'>Role: {ROLE_LABELS.get(role, role)} - Principal has full control to add/edit/delete users</div><button style='margin-top:12px; background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:8px'>Save</button></form></div>"
    ap = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="personal" else "color:#64748b"
    ase = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="security" else "color:#64748b"
    aa = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="activity" else "color:#64748b"
    if is_super:
        html = f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{hdr}<div style='padding:20px; max-width:1100px; margin:0 auto'><h2>Profile</h2><div style='display:flex; border-bottom:1px solid #e2e8f0; background:white; border-radius:10px 10px 0 0; padding:0 16px'><a href='/profile?tab=personal' style='padding:14px 4px; margin-right:24px; text-decoration:none; {ap}'>Personal</a><a href='/profile?tab=security' style='padding:14px 4px; margin-right:24px; text-decoration:none; {ase}'>Security</a><a href='/profile?tab=activity' style='padding:14px 4px; text-decoration:none; {aa}'>Activity</a></div><div style='display:grid; grid-template-columns:340px 1fr; gap:20px; margin-top:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; text-align:center'><div style='width:88px; height:88px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px; font-weight:800; margin:0 auto'>{initials}</div><div style='font-weight:700; margin-top:14px'>{name}</div><div style='margin-top:8px'><span style='background:#e0f2fe; color:#0369a1; padding:5px 12px; border-radius:20px; font-size:11px'>{ROLE_LABELS.get(role, role)}</span></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px'>{right}</div></div></div></body></html>"
    else:
        html = f"{hdr}<div style='padding:20px'><h2>👤 Principal Profile - {ROLE_LABELS.get(role, role)}</h2><div style='display:flex; border-bottom:1px solid #e2e8f0; background:white; border-radius:10px 10px 0 0; padding:0 16px'><a href='/profile?tab=personal' style='padding:14px 4px; margin-right:24px; text-decoration:none; {ap}'>Personal</a><a href='/profile?tab=security' style='padding:14px 4px; margin-right:24px; text-decoration:none; {ase}'>Security</a><a href='/profile?tab=activity' style='padding:14px 4px; text-decoration:none; {aa}'>Activity</a></div><div style='display:grid; grid-template-columns:340px 1fr; gap:20px; margin-top:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; text-align:center'><div style='width:88px; height:88px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px; font-weight:800; margin:0 auto'>{initials}</div><div style='font-weight:700; margin-top:14px'>{name}</div><div style='margin-top:8px'><span style='background:#ede9fe; color:#5b21b6; padding:5px 12px; border-radius:20px; font-size:11px'>{ROLE_LABELS.get(role, role)}</span></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px'>{right}</div></div></div></div></div>"
    return HTMLResponse(html)

@app.post("/update-password")
def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    if new_password!= confirm_password: return HTMLResponse("<h3>❌ Mismatch</h3><a href='/profile?tab=security'>Back</a>")
    email = request.session.get("email"); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_password)); u = cur.fetchone()
    if not u: con.close(); return HTMLResponse("<h3>❌ Wrong current</h3><a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_password, email)); con.commit(); con.close(); return HTMLResponse("<h3>✅ Updated!</h3><a href='/profile?tab=security'>Back</a>")

@app.post("/update-profile")
def update_profile(request: Request, full_name: str = Form(...), email_new: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    old_email = request.session.get("email"); con = get_db(); cur = con.cursor(); cur.execute("UPDATE users SET full_name=?, email=? WHERE email=?", (full_name.strip(), email_new.strip(), old_email)); con.commit(); con.close(); request.session["email"] = email_new.strip(); request.session["name"] = full_name.strip(); return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = "", success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    name = request.session.get("name",""); email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools = cur.fetchall()
    cur.execute("SELECT * FROM users WHERE role='school_admin'"); users = cur.fetchall(); con.close()
    users_by_school = {u["school_id"]: u for u in users}
    success_banner = ""
    if success=="added":
        success_banner = f"""<div id='successBanner' style='background:#dcfce7; border:2px solid #16a34a; color:#166534; padding:16px; border-radius:10px; margin-bottom:16px'><b>✅ Success! 🏫 {school_name}</b><div style='background:white; border:1px dashed #16a34a; border-radius:8px; padding:12px; margin-top:10px'><div style='font-size:11px'>Username:</div><div style='font-weight:700'>{school_email}</div><div style='font-size:11px; margin-top:6px'>Password:</div><div style='font-size:20px; font-weight:800'>{new_pass}</div></div><div style='text-align:right; margin-top:12px'><button onclick="document.getElementById('successBanner').style.display='none'" style='background:#0f172a; color:white; padding:8px 18px; border:none; border-radius:8px'>OK ✅</button></div></div>"""
    elif success=="code_sent":
        success_banner = f"<div style='background:#fef3c7; border:1px solid #fcd34d; color:#92400e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>📧 Code sent to {SUPER_ADMIN}!</div>"
    rows_html = ""; schools_json = {}
    for s in schools:
        sid = s["id"]; u = users_by_school.get(sid); upass = u["password"] if u else "—"; uemail = u["email"] if u else s["email"]
        schools_json[sid] = {"id": sid, "name": s["name"]}
        rows_html += f"""<tr id='row-{sid}' onclick='selectSchool({sid})' style='cursor:pointer'><td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#64748b'>🔑 {s['code']}</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{s['email']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{s['location']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{uemail}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'><span id='pwd-dot-{sid}'>••••••</span><span id='pwd-real-{sid}' style='display:none; font-weight:700'>{upass}</span> <span onclick="event.stopPropagation(); togglePwd({sid})" style='cursor:pointer'>👁️</span></td><td style='padding:10px; border-bottom:1px solid #eee; text-align:center'><button id='edit-{sid}' disabled style='padding:6px 8px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; opacity:0.3'>✏️</button><button id='del-{sid}' disabled onclick="event.stopPropagation(); handleDelete({sid})" style='padding:6px 8px; background:#fef2f2; border:1px solid #fecaca; border-radius:6px; opacity:0.3'>🗑️</button></td></tr>"""
    if not rows_html: rows_html = "<tr><td colspan=6 style='padding:24px; text-align:center; color:#999'>No schools yet</td></tr>"
    schools_data = json.dumps(schools_json)
    hl = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"
    verify_html = ""
    if pending_id:
        con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone(); con.close()
        if pending:
            code_display = f"<div style='background:white; border:2px dashed #f59e0b; border-radius:10px; padding:14px; margin-top:12px; text-align:center'><div style='font-size:11px; font-weight:600'>Your code:</div><div style='font-size:32px; font-weight:800; letter-spacing:8px; margin-top:6px'>🔑 {pending['auth_code']}</div></div>"
            verify_html = f"<div style='background:#fffbeb; border:2px solid #f59e0b; border-radius:12px; padding:20px; margin-bottom:16px'><b>🔐 Enter Code for 🏫 {pending['name']}</b>{code_display}<form method='post' action='/verify-school-code' style='display:flex; gap:8px; margin-top:14px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='Enter code' required style='flex:1; padding:12px; border:1px solid #fcd34d; border-radius:8px; text-align:center; font-weight:700'><button style='background:#0f172a; color:white; padding:12px 20px; border:none; border-radius:8px'>Verify</button></form><div style='margin-top:8px; display:flex; gap:8px'><a href='/resend-code/{pending_id}' style='font-size:11px; color:#2563eb'>Resend</a><a href='/schools/manage' style='font-size:11px; color:#64748b'>Cancel</a></div></div>"
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; background:#f8fafc; margin:0'>{header_html(initials, name, email)}
    <div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; overflow-x:auto'>{success_banner}{verify_html}
            <div style='display:flex; justify-content:space-between; margin-bottom:12px'><div><b>📚 Registered Schools ({len(schools)})</b><div style='font-size:11px; color:#64748b'>Click row to highlight → Edit/Delete</div></div></div>
            <table style='width:100%; border-collapse:collapse; min-width:800px'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>School</th><th style='padding:10px; text-align:left'>Contact</th><th style='padding:10px; text-align:left'>Location</th><th style='padding:10px; text-align:left'>Username</th><th style='padding:10px; text-align:left'>Password</th><th style='padding:10px; text-align:center'>Action</th></tr>{rows_html}</table>
        </div>
        <div style='background:white; {hl}; border-radius:12px; padding:20px; position:sticky; top:20px'><b>➕ Register New School</b><form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='school_name' placeholder='School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' placeholder='Admin Email *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' placeholder='Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' placeholder='Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' placeholder='Principal *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Send Code & Create</button><a href='/schools/manage' style='background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; text-decoration:none; display:block'>Cancel</a></form></div>
    </div>
    <script>
    let selectedId=null; let schools={schools_data};
    function selectSchool(id){{
        document.querySelectorAll('tr[id^="row-"]').forEach(r=>{{r.style.background='white';}});
        document.querySelectorAll('button[id^="edit-"], button[id^="del-"]').forEach(b=>{{b.disabled=true; b.style.opacity='0.3'; b.style.cursor='not-allowed';}});
        document.getElementById('row-'+id).style.background='#dbeafe';
        let eBtn=document.getElementById('edit-'+id); let dBtn=document.getElementById('del-'+id);
        eBtn.disabled=false; eBtn.style.opacity='1'; eBtn.style.cursor='pointer';
        dBtn.disabled=false; dBtn.style.opacity='1'; dBtn.style.cursor='pointer';
        selectedId=id;
    }}
    function togglePwd(id){{ let dot=document.getElementById('pwd-dot-'+id); let real=document.getElementById('pwd-real-'+id); if(dot.style.display==='none'){{dot.style.display='inline'; real.style.display='none';}} else {{dot.style.display='none'; real.style.display='inline';}} }}
    function handleDelete(id){{ let name=schools[id].name; if(confirm('Delete '+name+'?')){{ if(confirm('Final confirm: Delete '+name+' permanently?')){{ window.location='/schools/delete/' + id; }} }} }}
    </script>
    </body></html>
    """)

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code = str(random.randint(100000, 999999))
    con = get_db(); cur = con.cursor()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid; con.commit(); con.close()
    send_email(SUPER_ADMIN, f"🔐 Code: {auth_code} - {school_name}", f"🏫 {school_name.upper()}\nCODE: {auth_code}")
    log_activity(SUPER_ADMIN, f"📧 Auth code sent for {school_name}", f"Code {auth_code}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    if not pending: con.close(); return HTMLResponse("Invalid <a href='/schools/manage'>Back</a>")
    if pending["auth_code"]!= auth_code.strip(): con.close(); return HTMLResponse(f"<h3>❌ Wrong Code!</h3><a href='/schools/manage?pending_id={pending_id}'>Try Again</a>")
    code = str(random.randint(10000,99999)); unique_pass = generate_unique_password(pending["name"])
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid = cur.lastrowid; cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], unique_pass, "school_admin", pending["principal"], sid))
    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,)); con.commit(); con.close()
    send_email(pending["email"], f"Welcome {pending['name']}", f"Username: {pending['email']}\nPassword: {unique_pass}\nCode: {code}")
    log_activity(SUPER_ADMIN, f"🏫 Registered new school: {pending['name']}", f"Code: {code}")
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}&school_name={pending['name']}", status_code=303)

@app.get("/resend-code/{pending_id}")
def resend_code(pending_id: str):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    if not pending: con.close(); return RedirectResponse("/schools/manage")
    new_code = str(random.randint(100000, 999999)); cur.execute("UPDATE pending_schools SET auth_code=? WHERE id=?", (new_code, pending_id)); con.commit(); con.close()
    send_email(SUPER_ADMIN, f"New Code: {new_code}", f"New code: {new_code} for {pending['name']}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.get("/schools/delete/{school_id}")
def delete_school(school_id: int, request: Request):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM schools WHERE id=?", (school_id,)); cur.execute("DELETE FROM users WHERE school_id=?", (school_id,)); con.commit(); con.close()
    log_activity(request.session.get("email",""), f"🗑️ Deleted school {school_id}", "")
    return RedirectResponse("/schools/manage", status_code=303)

@app.get("/logout")
def logout(request: Request):
    email = request.session.get("email","")
    if email: log_activity(email, "🚪 Logged out", "Ended")
    request.session.clear()
    return RedirectResponse("/", status_code=303)
