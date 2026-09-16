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
app.add_middleware(SessionMiddleware, secret_key="davischool-v24-zeraki-school-side")

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
    # SUPER ADMIN TABLES - DONT TOUCH
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
    try:
        cur.execute("ALTER TABLE schools ADD COLUMN phone TEXT")
    except:
        pass
    try:
        cur.execute("ALTER TABLE schools ADD COLUMN principal TEXT")
    except:
        pass
    try:
        cur.execute("ALTER TABLE schools ADD COLUMN school_type TEXT")
    except:
        pass

    # SCHOOL SIDE ZERAKI TABLES
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
    if len(prefix) < 3:
        prefix = "SCH"
    num = random.randint(1000, 9999)
    return f"{prefix}@{num}!"

def send_email(to_email, subject, body):
    if not EMAIL_PASSWORD:
        return False
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER; msg["To"] = to_email; msg["Subject"] = subject
        msg.set_content(body)
        msg.add_alternative(f"<div style='font-family:Arial; padding:20px'><h3>{subject}</h3><pre style='background:#f8fafc; padding:16px; border-radius:8px'>{body}</pre></div>", subtype="html")
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context); server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.send_message(msg)
        return True
    except:
        return False

def log_activity(email, action, details=""):
    try:
        con = get_db(); cur = con.cursor()
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO activity_log (email, action, details, timestamp) VALUES (?,?,?,?)", (email, action, details, ts))
        con.commit(); con.close()
    except:
        pass

def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin":
        return None
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone(); con.close(); return s

# SUPER ADMIN HEADER - UNTOUCHED
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
    function toggleProfileMenu(){{
      let m=document.getElementById('profileDropdown');
      m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none';
    }}
    document.addEventListener('click', function(e){{
      let b=e.target.closest('.do-avatar');
      let menu=document.getElementById('profileDropdown');
      if(!b && menu && !menu.contains(e.target)){{
        menu.style.display='none';
      }}
    }});
    </script>
    """

# SCHOOL SIDE HEADER - ZERAKI STYLE
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
        <div style='margin-top:12px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:10px'><div style='font-size:10px; font-weight:700; color:#166534'>✅ MATOKEO ANALYTICS</div><div style='font-size:9px; color:#15803d; margin-top:4px'>Works for ALL LEVELS: Pre-Primary, Primary, Junior, Senior | 8-4-4 Supported</div></div>
      </div>
      <div style='flex:1; background:#f8fafc'>
        <div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'>
          <div><b style='font-size:14px'>MATOKEO ANALYTICS 🚀</b><div style='font-size:11px; color:#64748b'>{name} • {school['name']} | Revolutionize Your School's Management!</div></div>
          <div style='display:flex; align-items:center; gap:10px'><span style='font-size:11px; background:#dbeafe; color:#1e40af; padding:6px 10px; border-radius:20px'>{school['name']}</span><div style='width:36px; height:36px; background:#dcfce7; color:#166534; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800'>{initials}</div></div>
        </div>
    """

@app.get("/health")
def health():
    return PlainTextResponse("OK")

@app.get("/ping")
def ping():
    return PlainTextResponse("pong")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2><p style='font-size:11px; color:#64748b'>ONE LOGIN FOR ALL ROLES 🔐</p></div><form method='post' action='/login'><input name='email' placeholder='📧 Email (super admin or school)' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='🔑 Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In → Auto Redirect by Role</button></form></div></body></html>"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    school_info = None
    if u:
        cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],)); school_info = cur.fetchone()
    con.close()
    if not u:
        return HTMLResponse("❌ Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    if u["role"]!= "super_admin" and school_info:
        log_activity(u["email"], f"🏫 School login: {school_info['name']}", "")
        return RedirectResponse("/school/dashboard", status_code=303)
    log_activity(u["email"], "🔓 Super Admin Logged in", "")
    return RedirectResponse("/dashboard", status_code=303)

# SUPER ADMIN DASHBOARD - UNTOUCHED ORIGINAL
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    if request.session.get("role") == "school_admin":
        return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools"); total = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5"); recent = cur.fetchall(); con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    log_activity(email, "📊 Viewed dashboard", "School Overview")
    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
    if not rows:
        rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
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

# ==================== SCHOOL SIDE - FULL ZERAKI MATOKEO ANALYTICS ====================
@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin":
        return RedirectResponse("/")
    school = get_school_obj(request)
    if not school:
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
        <div><h2 style='margin:0'>MATOKEO ANALYTICS 🚀</h2><p style='margin:6px 0 0; font-size:13px; color:#bfdbfe'>REVOLUTIONIZE YOUR SCHOOL'S MANAGEMENT!</p><div style='margin-top:10px; font-size:11px; background:rgba(255,255,255,0.15); padding:6px 10px; border-radius:20px; display:inline-block'>WORKS FOR ALL LEVELS: PRE-PRIMARY, PRIMARY, JUNIOR, SENIOR | 8-4-4 SUPPORTED</div></div>
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
        <a href='/school/timetable' style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14p...
