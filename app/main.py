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
    try: cur.execute("ALTER TABLE schools ADD COLUMN phone TEXT")
    except: pass
    try: cur.execute("ALTER TABLE schools ADD COLUMN principal TEXT")
    except: pass
    try: cur.execute("ALTER TABLE schools ADD COLUMN school_type TEXT")
    except: pass
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
    </div>
    <div style='flex:1; background:#f8fafc'>
        <div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'>
            <div><b style='font-size:14px'>MATOKEO ANALYTICS 🚀</b><div style='font-size:11px; color:#64748b'>{name} • {school['name']}</div></div>
            <div style='display:flex; align-items:center; gap:10px'><span style='font-size:11px; background:#dbeafe; color:#1e40af; padding:6px 10px; border-radius:20px'>{school['name']}</span><div style='width:36px; height:36px; background:#dcfce7; color:#166534; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800'>{initials}</div></div>
        </div>
    """

@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.get("/ping")
def ping(): return PlainTextResponse("pong")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2><p style='font-size:11px; color:#64748b'>ONE LOGIN FOR ALL ROLES 🔐</p></div><form method='post' action='/login'><input name='email' placeholder='📧 Email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='🔑 Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In → Auto Redirect by Role</button></form></div></body></html>"""

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

# SUPER ADMIN DASHBOARD - UNTOUCHED
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") == "school_admin": return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools"); total = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5"); recent = cur.fetchall(); con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
    if not rows: rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
    content = f"""
    <div style='padding:24px'><h2>📊 School Overview</h2><p>Welcome {name}</p>
    <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px;'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>🏫 TOTAL SCHOOLS<br><b style='font-size:24px'>{total}</b></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>✅ ACTIVE<br><b style='font-size:24px'>{total}</b></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>💰 REVENUE<br><b style='font-size:24px'>KES {total*15000:,}</b></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>🎓 STUDENTS<br><b style='font-size:24px'>{total*350:,}</b></div>
    </div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; margin-top:16px'><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc'><th>Name</th><th>Location</th><th>Status</th><th>Date</th></tr>{rows}</table></div>
    </div>
    """
    return HTMLResponse(f"<html><body style='font-family:Arial; margin:0; background:#f8fafc'>{header_html(initials, name, email)}{content}</body></html>")

@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]
    cur.execute("SELECT SUM(paid) s FROM fees WHERE school_id=?", (school["id"],)); fees_paid = cur.fetchone()["s"] or 0
    cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY id DESC LIMIT 4", (school["id"],)); recent_students = cur.fetchall()
    con.close()
    students_rows = "".join([f"<tr><td>🎓 {s['name']}</td><td>{s['admission_no']}</td><td>{s['gender']}</td><td>Class {s['class_id']}</td></tr>" for s in recent_students]) or "<tr><td colspan=4>No students yet</td></tr>"
    html = school_header(school, name, "dashboard")
    html += f"<div style='padding:20px'><h2>MATOKEO ANALYTICS 🚀</h2><p>Total Students {sc} | Classes {cc} | Exams {ec} | Fees KES {fees_paid:,}</p><table><tr><th>Name</th><th>Adm</th><th>Gender</th><th>Class</th></tr>{students_rows}</table></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

# SCHOOL SIDE TABLES + MARKSHEETS + RANKING + ALL 8 FEATURES
@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],))
    students = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td>{s['name']}</td><td>{s['admission_no']}</td><td>{s['cname']}</td><td>{s['parent_phone']}</td><td><a href='/school/student/delete/{s['id']}'>🗑️</a></td></tr>" for s in students]) or "<tr><td colspan=5>No students</td></tr>"
    html = school_header(school, request.session.get("name",""), "students")
    html += f"<div style='padding:20px'><b>🎓 Students ({len(students)})</b><table><tr><th>Name</th><th>Adm</th><th>Class</th><th>Parent Phone</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/students/add'><input name='admission_no' required placeholder='Adm No'><input name='student_name' required placeholder='Student Name'><select name='class_id'>{opts}</select><select name='gender'><option>Male</option><option>Female</option></select><input name='parent_name' placeholder='Parent'><input name='parent_phone' required placeholder='Parent Phone'><button>Add Student</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_name: str = Form(...), parent_phone: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO students (school_id, admission_no, name, class_id, gender, parent_name, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], admission_no, student_name, class_id, gender, parent_name, parent_phone)); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td>{c['name']}</td><td>{c['level']}</td><td><a href='/school/class/delete/{c['id']}'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan=3>No classes</td></tr>"
    html = school_header(school, request.session.get("name",""), "classes")
    html += f"<div style='padding:20px'><table><tr><th>Class</th><th>Level</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/classes/add'><input name='class_name' required placeholder='Class Name'><select name='level'><option>Primary</option><option>Junior School</option><option>Senior School</option><option>8-4-4</option></select><button>Add Class</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), level: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, level) VALUES (?,?,?)", (school["id"], class_name, level)); con.commit(); con.close(); return RedirectResponse("/school/classes", status_code=303)

# MARKS, FEES, TIMETABLE, SMS, RANKING, ANALYSIS, REPORTS — ZERAKI FULL
@app.get("/school/marks", response_class=HTMLResponse)
def school_marks(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subs = cur.fetchall()
    cur.execute("SELECT s.id, s.name FROM students s WHERE s.school_id=? LIMIT 20", (school["id"],)); students = cur.fetchall()
    con.close()
    html = school_header(school, request.session.get("name",""), "marks")
    html += f"<div style='padding:20px'>Enter Marks - Exams {len(exams)} Subjects {len(subs)} Students {len(students)}</div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

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
        success_banner = f"<div style='background:#dcfce7; padding:16px; border-radius:10px'><b>✅ {school_name} Added!</b><br>Username: {school_email}<br>Password: {new_pass}<br><button onclick=\"this.parentElement.style.display='none'\">OK ✅</button> <button onclick=\"this.parentElement.style.display='none'\">Cancel ❌</button></div>"
    elif success=="code_sent":
        success_banner = f"<div style='background:#fef3c7; padding:12px; border-radius:10px'>📧 Code sent to {SUPER_ADMIN}! 🔐</div><div style='background:white; padding:16px; margin-top:10px'><form method='post' action='/verify-school-code'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='Enter 6-digit code' required maxlength='6'><button>Verify 6-digit</button><a href='/schools/manage'>Cancel</a></form></div>"
    rows_html = ""
    for s in schools:
        sid = s["id"]; u = users_by_school.get(sid); upass = u["password"] if u else "—"; uemail = u["email"] if u else s["email"]
        rows_html += f"<tr><td>🏫 {s['name']} 🔑 {s['code']}</td><td>{uemail}</td><td><span id='pwd-{sid}'>••••</span><span id='pwd-real-{sid}' style='display:none'>{upass}</span> <span onclick=\"togglePwd({sid})\">👁️</span></td><td>{s['location']}</td><td><button onclick=\"editSchool({sid})\">✏️</button><button onclick=\"deleteSchool({sid})\">🗑️</button></td></tr>"
    if not rows_html: rows_html = "<tr><td colspan=5>No schools yet</td></tr>"
    return HTMLResponse(f"<html><body>{header_html(initials, name, email)}<div style='padding:20px'>{success_banner}<table><tr><th>School + Code (6-digit)</th><th>Username (auto)</th><th>Password + 👁️</th><th>Location</th><th>Action</th></tr>{rows_html}</table><form method='post' action='/register-school'><input name='school_name' required placeholder='School Name'><input name='school_email' required placeholder='Admin Email'><input name='location' required placeholder='Location'><input name='phone' required placeholder='Phone'><input name='principal' required placeholder='Principal'><select name='school_type'><option>Primary</option><option>Secondary</option></select><button>Send 6-Digit Code</button></form></div><script>function togglePwd(id){{let a=document.getElementById('pwd-'+id); let b=document.getElementById('pwd-real-'+id); if(a.style.display=='none'){{a.style.display='inline'; b.style.display='none';}} else {{a.style.display='none'; b.style.display='inline';}}}}</script></body></html>")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code = str(random.randint(100000, 999999))
    con = get_db(); cur = con.cursor()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid; con.commit(); con.close()
    send_email(SUPER_ADMIN, f"🔐 Code: {auth_code} - {school_name}", f"🏫 {school_name.upper()}\n🔑 CODE: {auth_code}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    if not pending: con.close(); return HTMLResponse("Invalid <a href='/schools/manage'>Back</a>")
    if pending["auth_code"]!= auth_code.strip(): con.close(); return HTMLResponse(f"<h3>❌ Wrong 6-digit Code!</h3><a href='/schools/manage?pending_id={pending_id}'>Try Again</a>")
    code = str(random.randint(100000,999999)); unique_pass = generate_unique_password(pending["name"])
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid = cur.lastrowid; cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], unique_pass, "school_admin", pending["principal"], sid))
    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,)); con.commit(); con.close()
    send_email(pending["email"], f"Welcome {pending['name']}", f"Username: {pending['email']}\nPassword: {unique_pass}\nCode: {code}")
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}&school_name={pending['name']}", status_code=303)

@app.get("/resend-code/{pending_id}")
def resend_code(pending_id: str):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); p = cur.fetchone()
    if p: send_email(SUPER_ADMIN, f"🔐 Code: {p['auth_code']} - {p['name']}", f"Code: {p['auth_code']}")
    con.close()
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
    # ================= PART 2 CONTINUATION - PASTE BELOW PART 1 IN SAME main.py =================

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    school = get_school_obj(request)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY id DESC", (school["id"],))
    subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td>{s['name']}</td><td>{s['code']}</td><td><a href='/school/subject/delete/{s['id']}' onclick=\"return confirm('Delete?')\">🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan=3>No subjects</td></tr>"
    html = school_header(school, request.session.get("name",""), "subjects")
    html += f"<div style='padding:20px'><b>📚 Subjects ({len(subs)})</b><table><tr><th>Subject</th><th>Code</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/subjects/add'><input name='subject_name' required placeholder='Subject e.g. Mathematics'><input name='subject_code' placeholder='Code e.g. MATH'><button>Add Subject</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), subject_code: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO subjects (school_id, name, code) VALUES (?,?,?)", (school["id"], subject_name.strip(), subject_code.strip()))
    con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/subject/delete/{sid}")
def del_sub(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school["id"],)); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td>{e['name']}</td><td>{e['term']}</td><td>{e['year']}</td><td>{e['exam_type']}</td><td><a href='/school/exam/delete/{e['id']}'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan=5>No exams</td></tr>"
    html = school_header(school, request.session.get("name",""), "exams")
    html += f"<div style='padding:20px'><b>📝 Exams ({len(exams)})</b><table><tr><th>Exam</th><th>Term</th><th>Year</th><th>Type</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/exams/add'><input name='exam_name' required placeholder='Exam Name e.g. End Term 2'><select name='term'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' value='2026'><select name='exam_type'><option>Main Exam</option><option>CAT</option><option>Opener</option></select><button>Add Exam</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip(), term, year, exam_type))
    con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/exam/delete/{eid}")
def del_exam(eid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM exams WHERE id=? AND school_id=?", (eid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/marks", response_class=HTMLResponse)
def school_marks_full(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall()
    cur.execute("SELECT s.id, s.name, s.admission_no, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? LIMIT 50", (school["id"],)); students = cur.fetchall()
    cur.execute("SELECT m.*, s.name as sname, sub.name as subname, e.name as ename FROM marks m JOIN students s ON m.student_id=s.id JOIN subjects sub ON m.subject_id=sub.id JOIN exams e ON m.exam_id=e.id WHERE m.school_id=? ORDER BY m.id DESC LIMIT 15", (school["id"],)); recent = cur.fetchall()
    con.close()
    e_opts = "".join([f"<option value='{e['id']}'>{e['name']} - {e['term']} {e['year']}</option>" for e in exams])
    sub_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    st_opts = "".join([f"<option value='{st['id']}'>{st['name']} ({st['admission_no']})</option>" for st in students])
    rows = "".join([f"<tr><td>{r['sname']}</td><td>{r['subname']}</td><td>{r['ename']}</td><td><b>{r['score']}</b></td></tr>" for r in recent]) or "<tr><td colspan=4>No marks yet</td></tr>"
    html = school_header(school, request.session.get("name",""), "marks")
    html += f"<div style='padding:20px'><b>✍️ Enter Marks - Recent</b><table><tr><th>Student</th><th>Subject</th><th>Exam</th><th>Score</th></tr>{rows}</table><form method='post' action='/school/marks/add'><select name='exam_id' required><option value=''>Select Exam</option>{e_opts}</select><select name='subject_id' required><option value=''>Select Subject</option>{sub_opts}</select><select name='student_id' required><option value=''>Select Student</option>{st_opts}</select><input name='score' type='number' min='0' max='100' required placeholder='Score 0-100'><button>💾 Save Marks</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/marks/add")
def add_marks(request: Request, exam_id: int = Form(...), subject_id: int = Form(...), student_id: int = Form(...), score: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO marks (school_id, exam_id, student_id, subject_id, score) VALUES (?,?,?,?,?)", (school["id"], exam_id, student_id, subject_id, score))
    con.commit(); con.close(); return RedirectResponse("/school/marks", status_code=303)

@app.get("/school/marksheets", response_class=HTMLResponse)
def school_marksheets(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); con.close()
    if not exams: content = "<div style='padding:20px; background:white; border-radius:12px; text-align:center'>No exams yet</div>"
    else: content = "".join([f"<div style='background:white; border:1px solid #e2e8f0; padding:14px; border-radius:12px'><b>📄 {e['name']}</b><div>{e['term']} {e['year']}</div><a href='/school/marksheets/{e['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none'>Generate MarkSheet</a></div>" for e in exams])
    html = school_header(school, request.session.get("name",""), "marksheets")
    html += f"<div style='padding:20px'><h3>📄 Generates MarkSheets</h3><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px'>{content}</div></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

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
    th = "".join([f"<th>{sub['name'][:6]}</th>" for sub in subjects])
    rows = ""
    for st in students:
        scores = []; total = 0
        for sub in subjects:
            sc = marks_map.get((st["id"], sub["id"]), "-")
            scores.append(f"<td style='text-align:center'>{sc}</td>")
            if isinstance(sc, int): total += sc
        rows += f"<tr><td>{st['name']}</td><td>{st['admission_no']}</td>{''.join(scores)}<td><b>{total}</b></td></tr>"
    html = school_header(school, request.session.get("name",""), "marksheets")
    html += f"<div style='padding:20px'><div style='background:white; padding:16px; border-radius:12px'><b>📄 MarkSheet - {exam['name']}</b> <button onclick='window.print()'>🖨️ Print</button><table><tr><th>Student</th><th>Adm</th>{th}<th>Total</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/ranking", response_class=HTMLResponse)
def school_ranking(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM exams WHERE school_id=? LIMIT 1", (school["id"],)); ex = cur.fetchone()
    ranking_rows = ""
    if ex:
        cur.execute("SELECT s.name, s.admission_no, SUM(m.score) total FROM students s JOIN marks m ON s.id=m.student_id WHERE m.exam_id=? AND m.school_id=? GROUP BY s.id ORDER BY total DESC", (ex["id"], school["id"]))
        for idx, r in enumerate(cur.fetchall(), 1):
            medal = "🥇" if idx==1 else "🥈" if idx==2 else "🥉" if idx==3 else f"{idx}."
            ranking_rows += f"<tr><td>{medal} {idx}</td><td>{r['name']}</td><td>{r['admission_no']}</td><td><b>{r['total']}</b></td><td>{'A' if r['total']>350 else 'B' if r['total']>250 else 'C'}</td></tr>"
    con.close()
    if not ranking_rows: ranking_rows = "<tr><td colspan=5>No marks yet</td></tr>"
    html = school_header(school, request.session.get("name",""), "ranking")
    html += f"<div style='padding:20px'><div style='background:linear-gradient(135deg,#f59e0b,#eab308); padding:16px; border-radius:12px; color:white; text-align:center'><b>🏆 ACCURATE RANKING</b></div><table><tr><th>Rank</th><th>Student</th><th>Adm</th><th>Total</th><th>Grade</th></tr>{ranking_rows}</table></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/analysis", response_class=HTMLResponse)
def school_analysis(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT AVG(score) avg, MAX(score) mx, MIN(score) mn FROM marks WHERE school_id=?", (school["id"],)); stats = cur.fetchone()
    avg = int(stats["avg"] or 0); mx = stats["mx"] or 0; mn = stats["mn"] or 0
    cur.execute("SELECT sub.name, AVG(m.score) av FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.school_id=? GROUP BY sub.id", (school["id"],)); subj_avgs = cur.fetchall()
    con.close()
    subj_rows = "".join([f"<div style='background:white; border:1px solid #e2e8f0; padding:12px; border-radius:10px; text-align:center'><div>{s['name']}</div><b style='font-size:20px'>{int(s['av'] or 0)}%</b></div>" for s in subj_avgs]) or "No data yet"
    html = school_header(school, request.session.get("name",""), "analysis")
    html += f"<div style='padding:20px'><b>📈 EXAM MARKS ANALYSIS</b><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px'><div>Average {avg}%</div><div>Highest {mx}</div><div>Lowest {mn}</div><div>Students {sc}</div></div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:12px'>{subj_rows}</div></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/reports", response_class=HTMLResponse)
def school_reports(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.id, s.name, s.admission_no, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=?", (school["id"],)); students = cur.fetchall(); con.close()
    cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; padding:14px; border-radius:12px'><b>{s['name']}</b><div>{s['admission_no']} | {s['cname']}</div><a href='/school/report/{s['id']}' style='display:block; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; margin-top:10px; text-decoration:none'>📑 Report Card</a></div>" for s in students]) or "No students"
    html = school_header(school, request.session.get("name",""), "reports")
    html += f"<div style='padding:20px'><h3>📑 STUDENT REPORTS</h3><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/report/{student_id}", response_class=HTMLResponse)
def student_report(student_id: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=? AND s.school_id=?", (student_id, school["id"])); st = cur.fetchone()
    cur.execute("SELECT sub.name, m.score, e.name as ename FROM marks m JOIN subjects sub ON m.subject_id=sub.id JOIN exams e ON m.exam_id=e.id WHERE m.student_id=? AND m.school_id=? LIMIT 10", (student_id, school["id"])); marks = cur.fetchall()
    total = sum([m["score"] for m in marks]); avg = int(total / len(marks)) if marks else 0
    con.close()
    rows = "".join([f"<tr><td>{m['name']}</td><td>{m['score']}</td><td>{'A' if m['score']>=80 else 'B' if m['score']>=60 else 'C'}</td><td>{m['ename']}</td></tr>" for m in marks]) or "<tr><td colspan=4>No marks</td></tr>"
    html = school_header(school, request.session.get("name",""), "reports")
    html += f"<div style='padding:20px'><div style='background:white; padding:20px; border-radius:12px; max-width:800px; margin:auto'><h2 style='text-align:center'>🏫 {school['name']} - REPORT CARD</h2><div>Student: {st['name']} | Adm: {st['admission_no']} | Class: {st['cname']} | Total: {total} | Avg: {avg}%</div><table><tr><th>Subject</th><th>Score</th><th>Grade</th><th>Exam</th></tr>{rows}</table><button onclick='window.print()'>🖨️ Print</button></div></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/fees", response_class=HTMLResponse)
def school_fees(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT f.*, s.name as sname, s.admission_no FROM fees f JOIN students s ON f.student_id=s.id WHERE f.school_id=? ORDER BY f.id DESC", (school["id"],)); fees = cur.fetchall()
    cur.execute("SELECT id, name FROM students WHERE school_id=?", (school["id"],)); students = cur.fetchall(); con.close()
    st_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in students])
    rows = "".join([f"<tr><td>{f['sname']}</td><td>{f['admission_no']}</td><td>{f['term']}</td><td>KES {f['total']:,}</td><td>KES {f['paid']:,}</td><td>KES {f['balance']:,}</td></tr>" for f in fees]) or "<tr><td colspan=6>No fees</td></tr>"
    html = school_header(school, request.session.get("name",""), "fees")
    html += f"<div style='padding:20px'><b>💰 Fees</b><table><tr><th>Student</th><th>Adm</th><th>Term</th><th>Total</th><th>Paid</th><th>Balance</th></tr>{rows}</table><form method='post' action='/school/fees/add'><select name='student_id'>{st_opts}</select><select name='term'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='total' type='number' required placeholder='Total'><input name='paid' type='number' required placeholder='Paid'><button>Save Fees</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/fees/add")
def add_fees(request: Request, student_id: int = Form(...), term: str = Form(...), total: int = Form(...), paid: int = Form(...)):
    school = get_school_obj(request); balance = total - paid
    con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO fees (school_id, student_id, term, total, paid, balance) VALUES (?,?,?,?,?,?)", (school["id"], student_id, term, total, paid, balance)); con.commit(); con.close()
    return RedirectResponse("/school/fees", status_code=303)

@app.get("/school/timetable", response_class=HTMLResponse)
def school_timetable(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT t.*, c.name as cname FROM timetable t LEFT JOIN classes c ON t.class_id=c.id WHERE t.school_id=?", (school["id"],)); tt = cur.fetchall()
    cur.execute("SELECT id, name FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    c_opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td>{t['day']}</td><td>{t['period']}</td><td>{t['cname']}</td><td>{t['subject']}</td><td>{t['teacher']}</td><td><a href='/school/timetable/delete/{t['id']}'>🗑️</a></td></tr>" for t in tt]) or "<tr><td colspan=6>No timetable</td></tr>"
    html = school_header(school, request.session.get("name",""), "timetable")
    html += f"<div style='padding:20px'><b>🗓️ Smart Timetabling</b><table><tr><th>Day</th><th>Period</th><th>Class</th><th>Subject</th><th>Teacher</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/timetable/add'><select name='class_id'>{c_opts}</select><select name='day'><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option></select><input name='period' required placeholder='8:00-9:00'><input name='subject' required placeholder='Subject'><input name='teacher' required placeholder='Teacher'><button>Add Lesson</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

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
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]; con.close()
    rows = "".join([f"<tr><td>{s['recipient']}</td><td>{s['message'][:60]}</td><td>{s['timestamp']}</td></tr>" for s in logs]) or "<tr><td colspan=3>No SMS</td></tr>"
    html = school_header(school, request.session.get("name",""), "sms")
    html += f"<div style='padding:20px'><b>💬 Bulk SMS ({sc} parents)</b><table><tr><th>To</th><th>Message</th><th>Time</th></tr>{rows}</table><form method='post' action='/school/sms/send'><select name='target'><option value='all'>All Parents ({sc})</option><option value='fees'>Fees Defaulters</option></select><textarea name='message' required placeholder='Type SMS'></textarea><button style='background:#16a34a; color:white'>📤 Send Bulk SMS Now</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/sms/send")
def send_sms(request: Request, target: str = Form(...), message: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT parent_phone FROM students WHERE school_id=?", (school["id"],)); parents = cur.fetchall()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    for p in parents:
        cur.execute("INSERT INTO sms_logs (school_id, recipient, message, timestamp) VALUES (?,?,?,?)", (school["id"], p["parent_phone"], message, ts))
    con.commit(); con.close(); return RedirectResponse("/school/sms", status_code=303)

@app.get("/school/student/delete/{sid}")
def del_student(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/students", status_code=303)

@app.get("/school/class/delete/{cid}")
def del_class(cid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=? AND school_id=?", (cid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)
