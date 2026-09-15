Perfect — *Step 1: Delete ZERAKI & MATOKEO → Replace with DaviSchool* ✅

I have renamed *EVERYWHERE* in school side. Super admin side 100% untouched.

*FULL CODE v25 - STEP 1 - RENAMED TO DaviSchool — Delete old → Paste this → Commit:*
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
app.add_middleware(SessionMiddleware, secret_key="davischool-v25-renamed-step1")
SUPER_ADMIN = "oumadavis62@gmail.com"
EMAIL_SENDER = SUPER_ADMIN
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

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
        msg.add_alternative(f"<div style='font-family:Arial; padding:20px'><h3>{subject}</h3><pre style='background:#f8fafc; padding:16px; border-radius:8px'>{body}</pre></div>", subtype="html")
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
.do-avatar {{ width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; cursor:pointer; border:2px solid #e2e8f0; user-select:none; caret-color:transparent; outline:none; }}
.dropdown-item {{ display:flex; align-items:center; gap:10px; padding:11px 14px; text-decoration:none; font-size:13px; transition:0.2s; cursor:pointer; }}
.dropdown-item-profile {{ color:#0f172a; border-bottom:1px solid #f8fafc; }}
.dropdown-item-profile:hover {{ background:#0f172a; color:white; }}
.dropdown-item-logout {{ color:#dc2626; }}
.dropdown-item-logout:hover {{ background:#0f172a; color:white; }}
    </style>
    <div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; position:relative'>
        <div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px; color:#64748b'>{name} • Super Admin</div></div>
        <div style='position:relative'>
            <div onclick='toggleProfileMenu()' class='do-avatar' tabindex='-1'>{initials}</div>
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

def school_header(school, name, active="dashboard"):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    def nav(link, icon, label):
        a = "background:#0f172a; color:white; font-weight:700" if active==link else "color:#475569;"
        return f"<a href='/school/{link}' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; margin-bottom:4px; {a}'>{icon} {label}</a>"
    return f"""
    <div style='display:flex; min-height:100vh'>
    <div style='width:260px; background:white; border-right:1px solid #e2e8f0; padding:16px; position:sticky; top:0; height:100vh; overflow-y:auto'>
        <div style='padding:10px 6px 16px; border-bottom:1px solid #f1f5f9; margin-bottom:12px'><div style='display:flex; align-items:center; gap:10px'><div style='width:40px; height:40px; background:#0f172a; color:white; border-radius:10px; display:flex; align-items:center; justify-content:center; font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20]}</b><div style='font-size:10px; color:#64748b'>🔑 {school['code']} | {school['location']}</div></div></div></div>
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
        <div style='margin-top:16px; border-top:1px solid #f1f5f9; padding-top:12px'>
        <a href='/profile?tab=personal' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; color:#475569;'>👤 My Profile</a>
        <a href='/logout' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; color:#dc2626;'>🚪 Logout</a>
        </div>
        <div style='margin-top:12px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:10px'><div style='font-size:10px; font-weight:700; color:#166534'>✅ DaviSchool Analytics</div><div style='font-size:9px; color:#15803d; margin-top:4px'>Works for ALL LEVELS: Pre-Primary, Primary, Junior, Senior | 8-4-4 Supported</div></div>
    </div>
    <div style='flex:1; background:#f8fafc'>
        <div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'>
            <div><b style='font-size:14px'>DaviSchool Analytics 🚀</b><div style='font-size:11px; color:#64748b'>{name} • {school['name']} | Revolutionize Your School's Management!</div></div>
            <div style='display:flex; align-items:center; gap:10px'><span style='font-size:11px; background:#dbeafe; color:#1e40af; padding:6px 10px; border-radius:20px'>{school['name']}</span><div style='width:36px; height:36px; background:#dcfce7; color:#166534; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800'>{initials}</div></div>
        </div>
    """

@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.get("/ping")
def ping(): return PlainTextResponse("pong")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2><p style='font-size:11px; color:#64748b'>ONE LOGIN FOR ALL ROLES 🔐</p></div><form method='post' action='/login'><input name='email' placeholder='📧 Email (super admin or school)' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='🔑 Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In → Auto Redirect by Role</button></form></div></body></html>"""

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
        log_activity(u["email"], f"🏫 School login: {school_info['name']}", "")
        return RedirectResponse("/school/dashboard", status_code=303)
    log_activity(u["email"], "🔓 Super Admin Logged in", "")
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") == "school_admin": return RedirectResponse("/school/dashboard")
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

# SCHOOL DASHBOARD - RENAMED TO DaviSchool
@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role") not in ["school_admin","teacher","deputy_principal","dos","hod"]:
        if request.session.get("role")!="school_admin":
            pass
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school:
        if request.session.get("role")=="super_admin": return RedirectResponse("/dashboard")
        return RedirectResponse("/")
    name = request.session.get("name","")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]
    cur.execute("SELECT SUM(paid) s FROM fees WHERE school_id=?", (school["id"],)); fees_paid = cur.fetchone()["s"] or 0
    cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY id DESC LIMIT 4", (school["id"],)); recent_students = cur.fetchall()
    con.close()
    students_rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #f1f5f9'>🎓 {s['name']}</td><td style='padding:10px; border-bottom:1px solid #f1f5f9'>{s['admission_no']}</td><td style='padding:10px; border-bottom:1px solid #f1f5f9'>{s['gender']}</td><td style='padding:10px; border-bottom:1px solid #f1f5f9'>Class {s['class_id']}</td></tr>" for s in recent_students]) or "<tr><td colspan=4 style='padding:16px; text-align:center; color:#999'>No students yet - Add students to start</td></tr>"
    html = school_header(school, name, "dashboard")
    html += f"""
        <div style='padding:20px'>
            <div style='background:linear-gradient(135deg,#0f172a,#1e40af); border-radius:16px; padding:20px; color:white; display:flex; justify-content:space-between; align-items:center'>
                <div><h2 style='margin:0'>DaviSchool Analytics 🚀</h2><p style='margin:6px 0 0; font-size:13px; color:#bfdbfe'>REVOLUTIONIZE YOUR SCHOOL'S MANAGEMENT!</p><div style='margin-top:10px; font-size:11px; background:rgba(255,255,255,0.15); padding:6px 10px; border-radius:20px; display:inline-block'>WORKS FOR ALL LEVELS: PRE-PRIMARY, PRIMARY, JUNIOR, SENIOR | 8-4-4 SUPPORTED</div></div>
                <div style='text-align:right'><div style='font-size:28px; font-weight:800'>{sc}</div><div style='font-size:11px'>Total Students</div><div style='margin-top:8px; font-size:12px; background:#16a34a; padding:6px 12px; border-radius:20px'>✅ GET EVERYTHING DONE IN MINUTES!</div></div>
            </div>
            <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:16px'>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-size:11px; color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:24px; font-weight:800; margin-top:6px'>{sc}</div><div style='font-size:11px; color:#16a34a; margin-top:4px'>📈 Active</div></div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-size:11px; color:#64748b'>🏫 CLASSES</div><div style='font-size:24px; font-weight:800; margin-top:6px'>{cc}</div><div style='font-size:11px; color:#64748b; margin-top:4px'>Streams & Levels</div></div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-size:11px; color:#64748b'>📝 EXAMS</div><div style='font-size:24px; font-weight:800; margin-top:6px'>{ec}</div><div style='font-size:11px; color:#2563eb; margin-top:4px'>Deep Insights</div></div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-size:11px; color:#64748b'>💰 FEES COLLECTED</div><div style='font-size:24px; font-weight:800; margin-top:6px'>KES {fees_paid:,}</div><div style='font-size:11px; color:#16a34a; margin-top:4px'>💹 Managed</div></div>
            </div>
            <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:16px'>
                <a href='/school/analysis' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px; text-decoration:none; color:#0f172a'><div style='font-size:22px'>📊</div><b style='font-size:12px'>EXAM MARKS ANALYSIS</b><div style='font-size:10px; color:#64748b; margin-top:4px'>DEEP PERFORMANCE INSIGHTS</div></a>
                <a href='/school/ranking' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px; text-decoration:none; color:#0f172a'><div style='font-size:22px'>🏆</div><b style='font-size:12px'>ACCURATE RANKING</b><div style='font-size:10px; color:#64748b; margin-top:4px'>INSTANT CLASS & LEVEL RANKING</div></a>
                <a href='/school/marksheets' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px; text-decoration:none; color:#0f172a'><div style='font-size:22px'>📄</div><b style='font-size:12px'>GENERATES MARKSHEETS</b><div style='font-size:10px; color:#64748b; margin-top:4px'>CREATE RECORD SHEETS QUICKLY</div></a>
                <a href='/school/reports' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px; text-decoration:none; color:#0f172a'><div style='font-size:22px'>📑</div><b style='font-size:12px'>STUDENT REPORTS</b><div style='font-size:10px; color:#64748b; margin-top:4px'>AUTOMATED REPORT CARD GENERATION</div></a>
                <a href='/school/marksheets' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px; text-decoration:none; color:#0f172a'><div style='font-size:22px'>🗂️</div><b style='font-size:12px'>GENERATES MARKSHEETS</b><div style='font-size:10px; color:#64748b; margin-top:4px'>CREATE ACCURATE RECORD SHEETS</div></a>
                <a href='/school/timetable' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px; text-decoration:none; color:#0f172a'><div style='font-size:22px'>🗓️</div><b style='font-size:12px'>SMART TIMETABLING</b><div style='font-size:10px; color:#64748b; margin-top:4px'>LESSON ALERTS FOR TEACHERS</div></a>
                <a href='/school/fees' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px; text-decoration:none; color:#0f172a'><div style='font-size:22px'>💰</div><b style='font-size:12px'>FINANCING & FEES</b><div style='font-size:10px; color:#64748b; margin-top:4px'>MANAGE ACCOUNTS & FEES</div></a>
                <a href='/school/sms' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px; text-decoration:none; color:#0f172a'><div style='font-size:22px'>💬</div><b style='font-size:12px'>BULK SMS TO PARENTS</b><div style='font-size:10px; color:#64748b; margin-top:4px'>EASY BULK SMS NOTIFICATIONS</div></a>
            </div>
            <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px; margin-top:16px'>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>🎓 Recently Added Students</b><a href='/school/students' style='font-size:12px; color:#2563eb; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Adm No</th><th style='padding:10px; text-align:left'>Gender</th><th style='padding:10px; text-align:left'>Class</th></tr>{students_rows}</table></div>
                <div style='background:#0f172a; border-radius:14px; padding:16px; color:white'><b>📊 DaviSchool Analytics</b><div style='margin-top:12px; background:#1e293b; border-radius:10px; padding:12px'><div style='font-size:11px; color:#94a3b8'>STUDENT REPORT</div><div style='margin-top:8px'><div style='display:flex; align-items:center; gap:8px; margin-bottom:6px'><span style='width:24px; height:24px; background:#3b82f6; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:10px'>👤</span><span style='font-size:11px'>Top Student</span><span style='margin-left:auto; background:#22c55e; padding:2px 6px; border-radius:4px; font-size:10px'>G</span></div><div style='display:flex; align-items:center; gap:8px; margin-bottom:6px'><span style='width:24px; height:24px; background:#ec4899; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:10px'>👤</span><span style='font-size:11px'>Second</span><span style='margin-left:auto; background:#3b82f6; padding:2px 6px; border-radius:4px; font-size:10px'>B</span></div><div style='display:flex; align-items:center; gap:8px'><span style='width:24px; height:24px; background:#f59e0b; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:10px'>👤</span><span style='font-size:11px'>Third</span><span style='margin-left:auto; background:#f59e0b; padding:2px 6px; border-radius:4px; font-size:10px'>C</span></div></div></div><div style='margin-top:12px; font-size:10px; color:#94a3b8'>CONTACT US: 0111392013 | WhatsApp: 0111392013 — GET EVERYTHING DONE IN MINUTES!</div></div>
            </div>
        </div>
    </div></div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='margin:0; font-family:Arial'>{html}</body></html>")

def school_list_page(request, title, active, table_html, form_html):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school:
        if request.session.get("role")=="super_admin": return RedirectResponse("/dashboard")
        return RedirectResponse("/")
    name = request.session.get("name","")
    html = school_header(school, name, active)
    html += f"<div style='padding:20px; display:grid; grid-template-columns:1fr 360px; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>{table_html}</div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; position:sticky; top:20px'><b>{title}</b>{form_html}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    school = get_school_obj(request)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],))
    students = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],))
    classes = cur.fetchall()
    con.close()
    opts = "".join([f"<option value='{c['id']}'>{c['name']} - {c['level']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'>{s['name']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{s['admission_no']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{s['cname'] or s['class_id']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{s['parent_phone']}</td><td style='padding:10px; border-bottom:1px solid #eee'><a href='/school/student/delete/{s['id']}' onclick=\"return confirm('🗑️ Delete {s['name']}?')\" style='color:#dc2626; font-size:11px'>🗑️</a></td></tr>" for s in students]) or "<tr><td colspan=5 style='padding:20px; text-align:center; color:#999'>No students yet</td></tr>"
    table = f"<b>🎓 Students ({len(students)}) - DaviSchool</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Adm</th><th style='padding:10px; text-align:left'>Class</th><th style='padding:10px; text-align:left'>Parent Phone</th><th>Action</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/students/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='admission_no' placeholder='🎫 Admission No *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='student_name' placeholder='👤 Student Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='class_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🏫 Select Class *</option>{opts}</select><select name='gender' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Male</option><option>Female</option></select><input name='parent_name' placeholder='👨‍👩‍👧 Parent Name' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='parent_phone' placeholder='📱 Parent Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>➕ Add Student</button></form>"
    return school_list_page(request, "➕ Add New Student", "students", table, form)

@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_name: str = Form(...), parent_phone: str = Form(...)):
    school = get_school_obj(request)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, admission_no, name, class_id, gender, parent_name, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], admission_no.strip(), student_name.strip(), class_id, gender, parent_name, parent_phone))
    con.commit(); con.close()
    return RedirectResponse("/school/students", status_code=303)

@app.get("/school/student/delete/{sid}")
def del_student(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/students", status_code=303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY id DESC", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT c.id, COUNT(s.id) cnt FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.school_id=? WHERE c.school_id=? GROUP BY c.id", (school["id"], school["id"])); counts = {r[0]: r[1] for r in cur.fetchall()}
    con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{c['name']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{c['level']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{counts.get(c['id'],0)} students</td><td style='padding:10px; border-bottom:1px solid #eee'><a href='/school/class/delete/{c['id']}' onclick=\"return confirm('Delete?')\" style='color:#dc2626'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No classes yet</td></tr>"
    table = f"<b>🏫 Classes ({len(classes)}) - DaviSchool</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>Class Name</th><th style='padding:10px; text-align:left'>Level</th><th style='padding:10px; text-align:left'>Students</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/classes/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='class_name' placeholder='🏫 Class Name e.g. Class 8 East *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='level' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Level *</option><option>Pre-Primary</option><option>Primary</option><option>Junior School</option><option>Senior School</option><option>8-4-4</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>➕ Add Class</button></form>"
    return school_list_page(request, "➕ Add Class/Stream", "classes", table, form)

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), level: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, level) VALUES (?,?,?)", (school["id"], class_name.strip(), level)); con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/class/delete/{cid}")
def del_class(cid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=? AND school_id=?", (cid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY id DESC", (school["id"],)); subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['name']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['code']}</td><td style='padding:10px; border-bottom:1px solid #eee'><a href='/school/subject/delete/{s['id']}' onclick=\"return confirm('Delete?')\" style='color:#dc2626'>🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan=3 style='padding:20px; text-align:center; color:#999'>No subjects yet</td></tr>"
    table = f"<b>📚 Subjects ({len(subs)}) - DaviSchool</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:10px; text-align:left'>Subject</th><th style='padding:10px; text-align:left'>Code</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/subjects/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='subject_name' placeholder='📚 Subject e.g. Mathematics *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject_code' placeholder='🔢 Code e.g. MATH' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>➕ Add Subject</button></form>"
    return school_list_page(request, "➕ Add Subject", "subjects", table, form)

@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), subject_code: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO subjects (school_id, name, code) VALUES (?,?,?)", (school["id"], subject_name.strip(), subject_code.strip())); con.commit(); con.close()
    return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/subject/delete/{sid}")
def del_sub(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school["id"],)); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{e['name']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{e['term']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{e['year']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{e['exam_type']}</td><td style='padding:10px; border-bottom:1px solid #eee'><a href='/school/exam/delete/{e['id']}' onclick=\"return confirm('Delete?')\" style='color:#dc2626'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan=5 style='padding:20px; text-align:center; color:#999'>No exams yet</td></tr>"
    table = f"<b>📝 Exams ({len(exams)}) - DaviSchool</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>Exam</th><th style='padding:10px; text-align:left'>Term</th><th style='padding:10px; text-align:left'>Year</th><th style='padding:10px; text-align:left'>Type</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/exams/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='exam_name' placeholder='📝 Exam Name e.g. End Term 2 *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='term' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' placeholder='📅 Year e.g. 2026' value='2026' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='exam_type' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Main Exam</option><option>CAT</option><option>Opener</option><option>Mid-Term</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>➕ Add Exam</button></form>"
    return school_list_page(request, "➕ Add Exam", "exams", table, form)

@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip(), term, year, exam_type)); con.commit(); con.close()
    return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/exam/delete/{eid}")
def del_exam(eid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM exams WHERE id=? AND school_id=?", (eid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/marks", response_class=HTMLResponse)
def school_marks(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall()
    cur.execute("SELECT s.id, s.name, s.admission_no, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? LIMIT 20", (school["id"],)); students = cur.fetchall()
    cur.execute("SELECT m.*, s.name as sname, sub.name as subname, e.name as ename FROM marks m JOIN students s ON m.student_id=s.id JOIN subjects sub ON m.subject_id=sub.id JOIN exams e ON m.exam_id=e.id WHERE m.school_id=? ORDER BY m.id DESC LIMIT 10", (school["id"],)); recent = cur.fetchall()
    con.close()
    e_opts = "".join([f"<option value='{e['id']}'>{e['name']} - {e['term']} {e['year']}</option>" for e in exams])
    sub_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    st_opts = "".join([f"<option value='{st['id']}'>{st['name']} ({st['admission_no']}) - {st['cname']}</option>" for st in students])
    rows = "".join([f"<tr><td style='padding:8px; border-bottom:1px solid #eee; font-size:11px'>{r['sname']}</td><td style='padding:8px; border-bottom:1px solid #eee; font-size:11px'>{r['subname']}</td><td style='padding:8px; border-bottom:1px solid #eee; font-size:11px'>{r['ename']}</td><td style='padding:8px; border-bottom:1px solid #eee; font-size:12px; font-weight:700'>{r['score']}</td></tr>" for r in recent]) or "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No marks yet</td></tr>"
    table = f"<b>✍️ Recent Marks Entry - DaviSchool</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:8px; text-align:left'>Student</th><th style='padding:8px; text-align:left'>Subject</th><th style='padding:8px; text-align:left'>Exam</th><th style='padding:8px; text-align:left'>Score</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/marks/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><select name='exam_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>📝 Select Exam *</option>{e_opts}</select><select name='subject_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>📚 Select Subject *</option>{sub_opts}</select><select name='student_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Select Student *</option>{st_opts}</select><input name='score' type='number' min='0' max='100' placeholder='🔢 Score 0-100 *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>💾 Save Marks</button></form>"
    return school_list_page(request, "✍️ Enter Marks", "marks", table, form)

@app.post("/school/marks/add")
def add_marks(request: Request, exam_id: int = Form(...), subject_id: int = Form(...), student_id: int = Form(...), score: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO marks (school_id, exam_id, student_id, subject_id, score) VALUES (?,?,?,?,?)", (school["id"], exam_id, student_id, subject_id, score))
    con.commit(); con.close()
    return RedirectResponse("/school/marks", status_code=303)

@app.get("/school/marksheets", response_class=HTMLResponse)
def school_marksheets(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT e.id, e.name, e.term, e.year FROM exams e WHERE school_id=?", (school["id"],)); exams = cur.fetchall()
    con.close()
    if not exams: content = "<div style='padding:20px; background:white; border:1px solid #e2e8f0; border-radius:12px; text-align:center'>No exams yet — Add exams first in 📝 Exams</div>"
    else:
        exam_cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><b>📄 {e['name']}</b><div style='font-size:11px; color:#64748b'>{e['term']} {e['year']}</div><a href='/school/marksheets/{e['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px'>Generate MarkSheet 📊</a></div>" for e in exams])
        content = f"<div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px'>{exam_cards}</div>"
    html = school_header(school, request.session.get("name",""), "marksheets")
    html += f"<div style='padding:20px'><h3>📄 Generates MarkSheets - DaviSchool</h3><p style='font-size:12px; color:#64748b'>Select exam to generate class-wise marksheets - DaviSchool Analytics</p><div style='margin-top:16px'>{content}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/marksheets/{exam_id}", response_class=HTMLResponse)
def view_marksheet(exam_id: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?", (exam_id, school["id"])); exam = cur.fetchone()
    cur.execute("SELECT s.id, s.name, s.admission_no FROM students s WHERE s.school_id=? ORDER BY s.name", (school["id"],)); students = cur.fetchall()
    cur.execute("SELECT id, name FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall()
    marks_map = {}
    cur.execute("SELECT student_id, subject_id, score FROM marks WHERE exam_id=? AND school_id=?", (exam_id, school["id"]))
    for r in cur.fetchall(): marks_map[(r["student_id"], r["subject_id"])] = r["score"]
    con.close()
    th = "".join([f"<th style='padding:8px; border:1px solid #e2e8f0; font-size:11px'>{sub['name'][:6]}</th>" for sub in subjects])
    rows = ""
    for st in students:
        scores = []; total = 0
        for sub in subjects:
            sc = marks_map.get((st["id"], sub["id"]), "-")
            scores.append(f"<td style='padding:8px; border:1px solid #eee; text-align:center; font-size:11px'>{sc}</td>")
            if isinstance(sc, int): total += sc
        rows += f"<tr><td style='padding:8px; border:1px solid #eee; font-size:11px'>{st['name']}</td><td style='padding:8px; border:1px solid #eee; font-size:10px'>{st['admission_no']}</td>{''.join(scores)}<td style='padding:8px; border:1px solid #eee; font-weight:700; text-align:center'>{total}</td></tr>"
    html = school_header(school, request.session.get("name",""), "marksheets")
    html += f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; overflow-x:auto'><div style='display:flex; justify-content:space-between; margin-bottom:12px'><b>📄 DaviSchool MarkSheet - {exam['name']} | {exam['term']} {exam['year']}</b><button onclick='window.print()' style='background:#0f172a; color:white; padding:8px 14px; border:none; border-radius:8px'>🖨️ Print / PDF</button></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px; border:1px solid #e2e8f0'>Student</th><th style='padding:8px; border:1px solid #e2e8f0'>Adm</th>{th}<th style='padding:8px; border:1px solid #e2e8f0'>Total</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/ranking", response_class=HTMLResponse)
def school_ranking(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT id, name FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall()
    exam_id = exams[0]["id"] if exams else None
    ranking_rows = ""
    if exam_id:
        cur.execute("SELECT s.id, s.name, s.admission_no, SUM(m.score) total FROM students s JOIN marks m ON s.id=m.student_id WHERE m.exam_id=? AND m.school_id=? GROUP BY s.id ORDER BY total DESC", (exam_id, school["id"]))
        ranked = cur.fetchall()
        for idx, r in enumerate(ranked, 1):
            medal = "🥇" if idx==1 else "🥈" if idx==2 else "🥉" if idx==3 else f"{idx}."
            ranking_rows += f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{medal} {idx}</td><td style='padding:10px; border-bottom:1px solid #eee'>{r['name']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{r['admission_no']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-weight:700'>{r['total']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{'A' if r['total']>350 else 'B' if r['total']>250 else 'C'}</td></tr>"
    con.close()
    if not ranking_rows: ranking_rows = "<tr><td colspan=5 style='padding:20px; text-align:center; color:#999'>No marks yet - Enter marks to see ranking</td></tr>"
    html = school_header(school, request.session.get("name",""), "ranking")
    html += f"<div style='padding:20px'><div style='background:linear-gradient(135deg,#f59e0b,#eab308); border-radius:12px; padding:16px; color:white; text-align:center'><b style='font-size:18px'>🏆 ACCURATE RANKING - DaviSchool</b><div style='font-size:12px; margin-top:4px'>⭐ 1st 🥈 2nd 🥉 3rd - Automated ranking - DaviSchool Analytics</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; margin-top:16px; padding:16px'><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>Rank</th><th style='padding:10px; text-align:left'>Student</th><th style='padding:10px; text-align:left'>Adm</th><th style='padding:10px; text-align:left'>Total</th><th style='padding:10px; text-align:left'>Grade</th></tr>{ranking_rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/analysis", response_class=HTMLResponse)
def school_analysis(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT AVG(score) avg, MAX(score) mx, MIN(score) mn FROM marks WHERE school_id=?", (school["id"],)); stats = cur.fetchone()
    avg = int(stats["avg"] or 0); mx = stats["mx"] or 0; mn = stats["mn"] or 0
    cur.execute("SELECT sub.name, AVG(m.score) av FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.school_id=? GROUP BY sub.id", (school["id"],)); subj_avgs = cur.fetchall()
    con.close()
    subj_rows = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:10px; padding:12px; text-align:center'><div style='font-size:11px; color:#64748b'>{s['name']}</div><div style='font-size:20px; font-weight:800; margin-top:6px'>{int(s['av'] or 0)}%</div><div style='margin-top:8px; background:#e2e8f0; height:6px; border-radius:4px'><div style='background:#0f172a; height:6px; width:{int(s['av'] or 0)}%; border-radius:4px'></div></div></div>" for s in subj_avgs]) or "<div style='padding:20px; text-align:center; color:#999'>No data yet - Enter marks</div>"
    html = school_header(school, request.session.get("name",""), "analysis")
    html += f"<div style='padding:20px'><div style='background:linear-gradient(135deg,#0f172a,#2563eb); border-radius:12px; padding:16px; color:white'><b>📈 EXAM MARKS ANALYSIS - DaviSchool Analytics</b><div style='font-size:11px; color:#bfdbfe; margin-top:4px'>Charts, trends, subject performance - DaviSchool</div></div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><div style='font-size:11px; color:#64748b'>Average Score</div><div style='font-size:24px; font-weight:800'>{avg}%</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><div style='font-size:11px; color:#64748b'>Highest Score</div><div style='font-size:24px; font-weight:800; color:#16a34a'>{mx}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><div style='font-size:11px; color:#64748b'>Lowest Score</div><div style='font-size:24px; font-weight:800; color:#dc2626'>{mn}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><div style='font-size:11px; color:#64748b'>Total Students Analyzed</div><div style='font-size:24px; font-weight:800'>{sc}</div></div></div><div style='margin-top:16px'><b>📊 Subject Performance - DaviSchool</b><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:10px'>{subj_rows}</div></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/reports", response_class=HTMLResponse)
def school_reports(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.id, s.name, s.admission_no, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.name", (school["id"],)); students = cur.fetchall()
    con.close()
    cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><div style='display:flex; align-items:center; gap:10px'><div style='width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800'>{s['name'][:2].upper()}</div><div><b style='font-size:12px'>{s['name']}</b><div style='font-size:10px; color:#64748b'>{s['admission_no']} | {s['cname']}</div></div></div><a href='/school/report/{s['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none; font-size:11px'>📑 Generate Report Card - DaviSchool</a></div>" for s in students]) or "<div style='padding:20px; text-align:center; color:#999'>No students yet</div>"
    html = school_header(school, request.session.get("name",""), "reports")
    html += f"<div style='padding:20px'><h3>📑 STUDENT REPORTS - DaviSchool Analytics</h3><p style='font-size:11px; color:#64748b'>One click report cards with grades, ranking, remarks - DaviSchool</p><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/report/{student_id}", response_class=HTMLResponse)
def student_report(student_id: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=? AND s.school_id=?", (student_id, school["id"])); st = cur.fetchone()
    cur.execute("SELECT sub.name, m.score, e.name as ename FROM marks m JOIN subjects sub ON m.subject_id=sub.id JOIN exams e ON m.exam_id=e.id WHERE m.student_id=? AND m.school_id=? ORDER BY e.id DESC LIMIT 10", (student_id, school["id"])); marks = cur.fetchall()
    total = sum([m["score"] for m in marks]); avg = int(total / len(marks)) if marks else 0
    grade = "A" if avg>=80 else "B" if avg>=60 else "C" if avg>=40 else "D"
    con.close()
    rows = "".join([f"<tr><td style='padding:8px; border:1px solid #eee; font-size:11px'>{m['name']}</td><td style='padding:8px; border:1px solid #eee; text-align:center'>{m['score']}</td><td style='padding:8px; border:1px solid #eee; text-align:center'>{'A' if m['score']>=80 else 'B' if m['score']>=60 else 'C'}</td><td style='padding:8px; border:1px solid #eee; font-size:10px'>{m['ename']}</td></tr>" for m in marks]) or "<tr><td colspan=4 style='padding:20px; text-align:center'>No marks yet</td></tr>"
    html = school_header(school, request.session.get("name",""), "reports")
    html += f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px; max-width:800px; margin:0 auto'><div style='text-align:center; border-bottom:2px solid #0f172a; padding-bottom:12px'><h2 style='margin:0'>🏫 {school['name']} - DaviSchool</h2><p style='font-size:11px; color:#64748b'>{school['location']} | STUDENT REPORT CARD - DaviSchool Analytics</p></div><div style='display:flex; justify-content:space-between; margin-top:16px; font-size:12px'><div><b>Student:</b> {st['name']}<br><b>Adm No:</b> {st['admission_no']}<br><b>Class:</b> {st['cname']}</div><div><b>Term:</b> Term 2 2026<br><b>Total:</b> {total}<br><b>Average:</b> {avg}% | Grade {grade}</div></div><table style='width:100%; margin-top:16px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px; border:1px solid #e2e8f0; text-align:left'>Subject</th><th style='padding:8px; border:1px solid #e2e8f0'>Score</th><th style='padding:8px; border:1px solid #e2e8f0'>Grade</th><th style='padding:8px; border:1px solid #e2e8f0'>Exam</th></tr>{rows}</table><div style='margin-top:16px; display:flex; justify-content:space-between'><div style='font-size:11px'><b>Class Teacher Remarks:</b> Good progress. Keep up! - DaviSchool</div><button onclick='window.print()' style='background:#0f172a; color:white; padding:8px 16px; border:none; border-radius:8px'>🖨️ Print / Save as PDF</button></div></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/fees", response_class=HTMLResponse)
def school_fees(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT f.*, s.name as sname, s.admission_no FROM fees f JOIN students s ON f.student_id=s.id WHERE f.school_id=? ORDER BY f.id DESC", (school["id"],)); fees = cur.fetchall()
    cur.execute("SELECT id, name FROM students WHERE school_id=?", (school["id"],)); students = cur.fetchall()
    con.close()
    st_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in students])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{f['sname']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{f['admission_no']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{f['term']}</td><td style='padding:10px; border-bottom:1px solid #eee'>KES {f['total']:,}</td><td style='padding:10px; border-bottom:1px solid #eee; color:#16a34a'>KES {f['paid']:,}</td><td style='padding:10px; border-bottom:1px solid #eee; color:{'#dc2626' if f['balance']>0 else '#16a34a'}'>KES {f['balance']:,}</td></tr>" for f in fees]) or "<tr><td colspan=6 style='padding:20px; text-align:center; color:#999'>No fees records yet</td></tr>"
    table = f"<b>💰 Financing & Fees - DaviSchool</b><div style='margin-top:12px; overflow-x:auto'><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>Student</th><th style='padding:10px; text-align:left'>Adm</th><th style='padding:10px; text-align:left'>Term</th><th style='padding:10px; text-align:left'>Total</th><th style='padding:10px; text-align:left'>Paid</th><th style='padding:10px; text-align:left'>Balance</th></tr>{rows}</table></div>"
    form = f"<form method='post' action='/school/fees/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><select name='student_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Select Student *</option>{st_opts}</select><select name='term' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='total' type='number' placeholder='💰 Total Fees e.g. 15000 *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='paid' type='number' placeholder='✅ Amount Paid *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>💾 Save Fees</button></form>"
    return school_list_page(request, "➕ Record Fees Payment", "fees", table, form)

@app.post("/school/fees/add")
def add_fees(request: Request, student_id: int = Form(...), term: str = Form(...), total: int = Form(...), paid: int = Form(...)):
    school = get_school_obj(request); balance = total - paid
    con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO fees (school_id, student_id, term, total, paid, balance) VALUES (?,?,?,?,?,?)", (school["id"], student_id, term, total, paid, balance)); con.commit(); con.close()
    return RedirectResponse("/school/fees", status_code=303)

@app.get("/school/timetable", response_class=HTMLResponse)
def school_timetable(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT t.*, c.name as cname FROM timetable t LEFT JOIN classes c ON t.class_id=c.id WHERE t.school_id=? ORDER BY t.day, t.period", (school["id"],)); tt = cur.fetchall()
    cur.execute("SELECT id, name FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall()
    con.close()
    c_opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{t['day']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{t['period']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{t['cname']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{t['subject']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{t['teacher']}</td><td style='padding:10px; border-bottom:1px solid #eee'><a href='/school/timetable/delete/{t['id']}' onclick=\"return confirm('Delete?')\" style='color:#dc2626'>🗑️</a></td></tr>" for t in tt]) or "<tr><td colspan=6 style='padding:20px; text-align:center; color:#999'>No timetable yet</td></tr>"
    table = f"<b>🗓️ Smart Timetabling - DaviSchool</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>Day</th><th style='padding:10px; text-align:left'>Period</th><th style='padding:10px; text-align:left'>Class</th><th style='padding:10px; text-align:left'>Subject</th><th style='padding:10px; text-align:left'>Teacher</th><th>Action</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/timetable/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><select name='class_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🏫 Select Class *</option>{c_opts}</select><select name='day' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option></select><input name='period' placeholder='⏰ Period e.g. 8:00-9:00 *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject' placeholder='📚 Subject *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='teacher' placeholder='👨‍🏫 Teacher Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>➕ Add to Timetable</button></form>"
    return school_list_page(request, "➕ Add Lesson", "timetable", table, form)

@app.post("/school/timetable/add")
def add_tt(request: Request, class_id: int = Form(...), day: str = Form(...), period: str = Form(...), subject: str = Form(...), teacher: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO timetable (school_id, class_id, day, period, subject, teacher) VALUES (?,?,?,?,?,?)", (school["id"], class_id, day, period, subject, teacher)); con.commit(); con.close()
    return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/timetable/delete/{tid}")
def del_tt(tid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM timetable WHERE id=? AND school_id=?", (tid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/sms", response_class=HTMLResponse)
def school_sms(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM sms_logs WHERE school_id=? ORDER BY id DESC LIMIT 20", (school["id"],)); logs = cur.fetchall()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{s['recipient']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>{s['message'][:60]}...</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:10px'>{s['timestamp']}</td></tr>" for s in logs]) or "<tr><td colspan=3 style='padding:20px; text-align:center; color:#999'>No SMS sent yet</td></tr>"
    table = f"<b>💬 Bulk SMS to Parents - DaviSchool ({sc} parents)</b><div style='margin-top:8px; background:#f0fdf4; border:1px solid #bbf7d0; padding:8px; border-radius:8px; font-size:11px'>✅ Will send to all {sc} parents - DaviSchool</div><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px'><th style='padding:10px; text-align:left'>To</th><th style='padding:10px; text-align:left'>Message</th><th style='padding:10px; text-align:left'>Time</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/sms/send' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><select name='target' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value='all'>📢 All Parents ({sc})</option><option value='fees'>💰 Fees Defaulters</option><option value='exam'>📝 Exam Notifications</option></select><textarea name='message' placeholder='💬 Type SMS message e.g. Dear Parent, Term 2 fees balance is KES 2000. - {school['name']} DaviSchool' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px; height:100px'></textarea><button style='background:#16a34a; color:white; padding:12px; border:none; border-radius:8px; font-weight:700'>📤 Send Bulk SMS Now - DaviSchool</button></form>"
    return school_list_page(request, "💬 Send Bulk SMS", "sms", table, form)

@app.post("/school/sms/send")
def send_sms(request: Request, target: str = Form(...), message: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT parent_phone FROM students WHERE school_id=?", (school["id"],)); parents = cur.fetchall()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    for p in parents:
        cur.execute("INSERT INTO sms_logs (school_id, recipient, message, timestamp) VALUES (?,?,?,?)", (school["id"], p["parent_phone"], message, ts))
    con.commit(); con.close()
    return RedirectResponse("/school/sms", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email",""); name = request.session.get("name","Davis Ouma")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    school_obj = get_school_obj(request); is_super = school_obj is None
    sname = "Davischool Platform" if is_super else school_obj["name"]; scode = "SUPER-ADMIN" if is_super else school_obj["code"]
    sloc = "Platform Owner" if is_super else school_obj["location"]; badge = "Super Admin" if is_super else request.session.get("role","School Admin")
    hdr = header_html(initials, name, email) if is_super else school_header(school_obj, name, "profile") + "<div style='padding:0'>"
    log_activity(email, f"👀 Viewed profile tab: {tab}", f"{tab}")
    if tab=="security":
        right = f"""<div><b style='font-size:15px'>🔒 Security Settings</b><form method='post' action='/update-password' style='margin-top:18px'><label style='font-size:12px; font-weight:600; display:block; margin-top:14px'>🔑 Current Password</label><input name='current_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>🆕 New Password</label><input name='new_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>✅ Confirm New Password</label><input name='confirm_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><div style='text-align:right; margin-top:16px'><button type='submit' style='background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:8px; font-weight:600'>🔐 Update Password</button></div></form></div>"""
    elif tab=="activity":
        con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 50", (email,)); logs = cur.fetchall(); con.close()
        log_rows = "".join([f"<div style='padding:12px 14px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><div><div style='font-size:12px; font-weight:600'>{l['action']}</div><div style='font-size:11px; color:#64748b'>{l['details']}</div></div><span style='font-size:10px; color:#94a3b8'>{l['timestamp']}</span></div>" for l in logs]) or "<div style='padding:24px; text-align:center; color:#999'>No activity yet</div>"
        right = f"<div><div style='display:flex; justify-content:space-between; align-items:center'><div><b style='font-size:15px'>📜 Activity Log</b><p style='font-size:11px; color:#64748b'>{len(logs)} events — EAT 🇰🇪</p></div><a href='#' onclick=\"if(confirm('🧹 Confirm Clear?\\n\\nAre you sure you want to clear ALL activity logs?\\nThis cannot be undone!')){{if(confirm('⚠️ Final confirm: Clear logs permanently?')){{window.location='/clear-activity'}}}} return false;\" style='font-size:11px; color:#dc2626; border:1px solid #fecaca; padding:6px 10px; border-radius:6px; text-decoration:none'>🧹 Clear</a></div><div style='border:1px solid #e2e8f0; border-radius:10px; margin-top:16px; overflow:hidden; max-height:500px; overflow-y:auto'>{log_rows}</div></div>"
    else:
        right = f"<div><b style='font-size:15px'>👤 Personal Information</b><form method='post' action='/update-profile' style='margin-top:18px'><label style='font-size:12px; font-weight:600; display:block; margin-top:14px'>👨‍💼 Full Name</label><input name='full_name' value='{name}' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>📧 Email</label><input name='email_new' value='{email}' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>🏫 Organization</label><input value='{sname}' disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f1f5f9; color:#64748b; margin-top:4px'><div style='text-align:right; margin-top:20px'><button type='submit' style='background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:8px; font-weight:600'>💾 Save Changes</button></div></form></div>"
    ap = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="personal" else "color:#64748b; border-bottom:2px solid transparent"
    ase = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="security" else "color:#64748b; border-bottom:2px solid transparent"
    aa = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="activity" else "color:#64748b; border-bottom:2px solid transparent"
    if is_super:
        html = f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='margin:0; font-family:Arial; background:#f8fafc'>{hdr}<div style='padding:20px; max-width:1100px; margin:0 auto'><h2>👤 My Profile</h2><div style='display:flex; border-bottom:1px solid #e2e8f0; margin-bottom:20px; background:white; border-radius:10px 10px 0 0; padding:0 16px; margin-top:16px'><a href='/profile?tab=personal' style='padding:14px 4px; margin-right:24px; text-decoration:none; font-size:13px; {ap}'>👤 Personal</a><a href='/profile?tab=security' style='padding:14px 4px; margin-right:24px; text-decoration:none; font-size:13px; {ase}'>🔒 Security</a><a href='/profile?tab=activity' style='padding:14px 4px; text-decoration:none; font-size:13px; {aa}'>📜 Activity Log</a></div><div style='display:grid; grid-template-columns:340px 1fr; gap:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; text-align:center'><div style='width:88px; height:88px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px; font-weight:800; margin:0 auto'>{initials}</div><div style='font-weight:700; margin-top:14px'>{name}</div><div style='margin-top:8px'><span style='background:#e0f2fe; color:#0369a1; padding:5px 12px; border-radius:20px; font-size:11px'>{badge}</span></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px'>{right}</div></div></div></body></html>"
    else:
        html = f"{hdr}<div style='padding:20px'><h2>👤 My Profile - DaviSchool</h2><div style='display:flex; border-bottom:1px solid #e2e8f0; margin-bottom:20px; background:white; border-radius:10px 10px 0 0; padding:0 16px; margin-top:16px'><a href='/profile?tab=personal' style='padding:14px 4px; margin-right:24px; text-decoration:none; font-size:13px; {ap}'>👤 Personal</a><a href='/profile?tab=security' style='padding:14px 4px; margin-right:24px; text-decoration:none; font-size:13px; {ase}'>🔒 Security</a><a href='/profile?tab=activity' style='padding:14px 4px; text-decoration:none; font-size:13px; {aa}'>📜 Activity Log</a></div><div style='display:grid; grid-template-columns:340px 1fr; gap:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; text-align:center'><div style='width:88px; height:88px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px; font-weight:800; margin:0 auto'>{initials}</div><div style='font-weight:700; margin-top:14px'>{name}</div><div style='margin-top:8px'><span style='background:#e0f2fe; color:#0369a1; padding:5px 12px; border-radius:20px; font-size:11px'>{badge}</span></div><div style='margin-top:16px; border-top:1px solid #f1f5f9; padding-top:16px; text-align:left'><div style='font-size:12px; font-weight:700'>🏫 {sname}</div><div style='font-size:11px; color:#64748b'>📍 {sloc}</div></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px'>{right}</div></div></div></div></div>"
    return HTMLResponse(html)

@app.post("/update-password")
def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    if new_password!= confirm_password: return HTMLResponse("<h3>❌ Mismatch</h3><a href='/profile?tab=security'>Back</a>")
    email = request.session.get("email"); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_password)); u = cur.fetchone()
    if not u: con.close(); return HTMLResponse("<h3>❌ Wrong current</h3><a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_password, email)); con.commit(); con.close()
    log_activity(email, "🔑 Changed password", "Updated ✅")
    return HTMLResponse("<h3>✅ Updated!</h3><a href='/profile?tab=security'>Back</a>")

@app.post("/update-profile")
def update_profile(request: Request, full_name: str = Form(...), email_new: str = Form(...), phone: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    old_email = request.session.get("email"); con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET full_name=?, email=? WHERE email=?", (full_name.strip(), email_new.strip(), old_email)); con.commit(); con.close()
    request.session["email"] = email_new.strip(); request.session["name"] = full_name.strip()
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/clear-activity")
def clear_activity(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email"); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM activity_log WHERE email=?", (email,)); con.commit(); con.close()
    log_activity(email, "🧹 Cleared activity log", "Deleted")
    return RedirectResponse("/profile?tab=activity", status_code=303)

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
        success_banner = f"""<div id='successBanner' style='background:#dcfce7; border:2px solid #16a34a; color:#166534; padding:16px; border-radius:10px; margin-bottom:16px'><b>✅ Success! 🏫 {school_name}</b><div style='background:white; border:1px dashed #16a34a; border-radius:8px; padding:12px; margin-top:10px'><div style='font-size:11px; color:#64748b'>👤 Username:</div><div style='font-weight:700'>{school_email}</div><div style='font-size:11px; color:#64748b; margin-top:6px'>🔑 Password:</div><div style='font-size:20px; font-weight:800'>{new_pass}</div></div><div style='text-align:right; margin-top:12px'><button onclick="document.getElementById('successBanner').style.display='none'" style='background:#0f172a; color:white; padding:8px 18px; border:none; border-radius:8px; font-weight:600'>OK ✅</button></div></div>"""
    elif success=="code_sent":
        success_banner = f"<div style='background:#fef3c7; border:1px solid #fcd34d; color:#92400e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>📧 <b>Code sent to {SUPER_ADMIN}! 🔐</b> Check inbox</div>"
    rows_html = ""; schools_json = {}
    for s in schools:
        sid = s["id"]; u = users_by_school.get(sid); upass = u["password"] if u else "—"; uemail = u["email"] if u else s["email"]
        schools_json[sid] = {"id": sid, "name": s["name"], "email": s["email"], "code": s["code"], "location": s["location"], "phone": s["phone"] or "", "principal": s["principal"] or "", "school_type": s["school_type"] or ""}
        rows_html += f"""
        <tr id='row-{sid}' onclick='selectSchool({sid})' style='cursor:pointer; user-select:none;'>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#64748b'>🔑 {s['code']}</div></td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📧 {s['email']}</td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📍 {s['location']}</td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>👤 {uemail}</td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'><span id='pwd-dot-{sid}'>••••••</span><span id='pwd-real-{sid}' style='display:none; font-weight:700'>{upass}</span> <span onclick="event.stopPropagation(); togglePwd({sid})" style='cursor:pointer; margin-left:6px'>👁️</span></td>
            <td style='padding:10px; border-bottom:1px solid #eee; text-align:center'>
                <button id='edit-{sid}' disabled onclick="event.stopPropagation(); handleEdit({sid})" style='padding:6px 8px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; opacity:0.3; cursor:not-allowed; margin-right:4px'>✏️</button>
                <button id='del-{sid}' disabled onclick="event.stopPropagation(); handleDelete({sid})" style='padding:6px 8px; background:#fef2f2; border:1px solid #fecaca; border-radius:6px; opacity:0.3; cursor:not-allowed'>🗑️</button>
            </td>
        </tr>
        """
    if not rows_html: rows_html = "<tr><td colspan=6 style='padding:24px; text-align:center; color:#999'>No schools yet 🏫</td></tr>"
    schools_data = json.dumps(schools_json)
    hl = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"
    verify_html = ""
    if pending_id:
        con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone(); con.close()
        if pending:
            code_display = f"<div style='background:white; border:2px dashed #f59e0b; border-radius:10px; padding:14px; margin-top:12px; text-align:center'><div style='font-size:11px; color:#92400e; font-weight:600'>🔓 Your code:</div><div style='font-size:32px; font-weight:800; letter-spacing:8px; color:#0f172a; margin-top:6px'>🔑 {pending['auth_code']}</div></div>"
            verify_html = f"<div style='background:#fffbeb; border:2px solid #f59e0b; border-radius:12px; padding:20px; margin-bottom:16px'><b>🔐 Enter Code for 🏫 {pending['name']}</b>{code_display}<form method='post' action='/verify-school-code' style='display:flex; gap:8px; margin-top:14px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='🔢 Enter 6-digit code' required style='flex:1; padding:12px; border:1px solid #fcd34d; border-radius:8px; font-size:18px; letter-spacing:4px; text-align:center; font-weight:700'><button style='background:#0f172a; color:white; padding:12px 20px; border:none; border-radius:8px; font-weight:600'>✅ Verify & Create Login</button></form><div style='margin-top:8px; display:flex; gap:8px'><a href='/resend-code/{pending_id}' style='font-size:11px; color:#2563eb; text-decoration:none'>📧 Resend</a><a href='/schools/manage' style='font-size:11px; color:#64748b; text-decoration:none'>❌ Cancel</a></div></div>"
    return HTMLResponse(f"""
    <html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>*{{ caret-color: transparent; }} input, textarea {{ caret-color: auto!important; }}.no-caret{{ caret-color:transparent; user-select:none; outline:none; }}</style></head><body style='font-family:Arial; background:#f8fafc; margin:0'>{header_html(initials, name, email)}
    <div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; overflow-x:auto' class='no-caret'>{success_banner}{verify_html}
            <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px'><div><b>📚 Registered Schools ({len(schools)})</b><div style='font-size:11px; color:#64748b'>👆 Click row to highlight 💙 → then ✏️ Edit / 🗑️ Delete becomes active</div></div></div>
            <table style='width:100%; border-collapse:collapse; min-width:800px' class='no-caret'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>🏫 School</th><th style='padding:10px; text-align:left'>📧 Contact</th><th style='padding:10px; text-align:left'>📍 Location</th><th style='padding:10px; text-align:left'>👤 Username</th><th style='padding:10px; text-align:left'>🔑 Password</th><th style='padding:10px; text-align:center'>⚙️ Action</th></tr>{rows_html}</table>
        </div>
        <div style='background:white; {hl}; border-radius:12px; padding:20px; position:sticky; top:20px'><b>➕ Register New School 🏫</b><p style='font-size:11px; color:#64748b'>Unique password auto-created 🔑</p><form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='school_name' placeholder='🏫 School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' placeholder='📧 Admin Email *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' placeholder='📍 Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' placeholder='📱 Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' placeholder='👨‍💼 Principal *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>📧 Send Code & Create Login</button><a href='/schools/manage' style='background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:13px; display:block'>❌ Cancel</a></form></div>
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
    function handleEdit(id){{
        let name=schools[id].name;
        if(confirm('✏️ Confirm Editing\\n\\nAre you sure you want to edit 🏫 ' + name + '?')){{
            if(confirm('⚠️ Proceed to edit ' + name + '?')){{
                alert('✏️ Edit ' + name + ' - edit modal coming');
            }}
        }}
    }}
    function handleDelete(id){{
        let name=schools[id].name;
        if(confirm('🗑️ Confirm Deletion\\n\\nAre you sure you want to delete 🏫 ' + name + '?\\nThis will remove school + login forever!')){{
            if(confirm('⚠️ Final confirm: Delete ' + name + ' permanently? This cannot be undone!')){{
                window.location='/schools/delete/' + id;
            }}
        }}
    }}
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
    send_email(SUPER_ADMIN, f"🔐 Code: {auth_code} - {school_name}", f"🏫 {school_name.upper()}\n🔑 CODE: {auth_code}")
    log_activity(SUPER_ADMIN, f"📧 Auth code sent for {school_name} 🔐", f"Code {auth_code}")
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
    send_email(pending["email"], f"🏫 Welcome {pending['name']} - Login", f"🏫 {pending['name']}\nUsername: {pending['email']}\nPassword: {unique_pass}\nCode: {code}")
    log_activity(SUPER_ADMIN, f"🏫 Registered new school: {pending['name']} ✅", f"Code: {code} | Pass {unique_pass}")
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}&school_name={pending['name']}", status_code=303)

@app.get("/resend-code/{pending_id}")
def resend_code(pending_id: str):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    if not pending: con.close(); return RedirectResponse("/schools/manage")
    new_code = str(random.randint(100000, 999999)); cur.execute("UPDATE pending_schools SET auth_code=? WHERE id=?", (new_code, pending_id)); con.commit(); con.close()
    send_email(SUPER_ADMIN, f"🔐 New Code: {new_code}", f"🔑 New code: {new_code} for {pending['name']}")
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
✅ *DONE — All Zeraki/Matokeo deleted → Now DaviSchool only:*

- `MATOKEO ANALYTICS 🚀` → `DaviSchool Analytics 🚀`
- `Zeraki Analytics` → `DaviSchool Analytics`
- Footer text → `DaviSchool`
- All cards, reports, marksheets → `DaviSchool`

Super admin overview untouched ✅

*Ready for Step 2?* Next I will add *roles: Principal (full control), Deputy Principal, Director of Studies, HOD, Teacher (limited to marks + student lists), Bursar* + auto username/password generation when school admin adds staff + staff management page.

Say *"next step"* to proceed!
