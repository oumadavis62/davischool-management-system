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
.do-avatar {{ width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; cursor:pointer; border:2px solid #e2e8f0; }}
.dropdown-item {{ display:flex; align-items:center; gap:10px; padding:11px 14px; text-decoration:none; font-size:13px; }}
.dropdown-item-profile {{ color:#0f172a; border-bottom:1px solid #f8fafc; }}
.dropdown-item-profile:hover {{ background:#0f172a; color:white; }}
.dropdown-item-logout {{ color:#dc2626; }}
.dropdown-item-logout:hover {{ background:#0f172a; color:white; }}
    </style>
    <div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; position:relative'>
        <div><b>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px; color:#64748b'>{name} • Super Admin</div></div>
        <div style='position:relative'>
            <div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div>
            <div id='profileDropdown' style='display:none; position:absolute; right:0; top:44px; background:white; border:1px solid #e2e8f0; border-radius:12px; width:220px; box-shadow:0 10px 25px rgba(0,0,0,0.12); z-index:1000; overflow:hidden'>
                <div style='padding:14px; border-bottom:1px solid #f1f5f9; background:#f8fafc'><div style='font-weight:700; font-size:13px'>{name}</div><div style='font-size:11px; color:#64748b'>{email}</div></div>
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

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2></div><form method='post' action='/login'><input name='email' placeholder='📧 Email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='🔑 Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In</button></form></div></body></html>"""

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
        return RedirectResponse("/school/dashboard", status_code=303)
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
    rows = "".join([f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td>Today</td></tr>" for s in recent]) or "<tr><td colspan=4 style='padding:20px; text-align:center'>No schools</td></tr>"
    content = f"<div style='padding:24px'><h2>📊 School Overview - {total} schools</h2><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc'><th>Name</th><th>Location</th><th>Status</th><th>Date</th></tr>{rows}</table><br><a href='/schools/manage'>Manage Schools</a></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{header_html(initials, name, email)}{content}</body></html>")

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
    con.close()
    html = school_header(school, name, "dashboard")
    html += f"""
        <div style='padding:20px'>
            <div style='background:linear-gradient(135deg,#0f172a,#1e40af); border-radius:16px; padding:20px; color:white'><h2 style='margin:0'>MATOKEO ANALYTICS 🚀</h2><p>Works for all levels</p></div>
            <div style='display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-top:16px'>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'>🎓 Students: {sc}</div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'>🏫 Classes: {cc}</div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'>📝 Exams: {ec}</div>
            </div>
        </div></div></div>
    """
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

def school_list_page(request, title, active, table_html, form_html):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    html = school_header(school, name, active)
    html += f"<div style='padding:20px; display:grid; grid-template-columns:1fr 360px; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>{table_html}</div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><b>{title}</b>{form_html}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['name']}</td><td>{s['admission_no']}</td><td>{s['cname'] or ''}</td><td><a href='/school/student/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for s in students]) or "<tr><td colspan=4 style='padding:20px; text-align:center'>No students</td></tr>"
    table = f"<b>Students ({len(students)})</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Name</th><th>Adm</th><th>Class</th><th>Action</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/students/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='admission_no' placeholder='Adm *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='student_name' placeholder='Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='class_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Class</option>{opts}</select><select name='gender' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Male</option><option>Female</option></select><input name='parent_name' placeholder='Parent' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='parent_phone' placeholder='Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add Student</button></form>"
    return school_list_page(request, "Add Student", "students", table, form)

@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_name: str = Form(...), parent_phone: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO students (school_id, admission_no, name, class_id, gender, parent_name, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], admission_no.strip(), student_name.strip(), class_id, gender, parent_name, parent_phone)); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/student/delete/{sid}")
def del_student(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY id DESC", (school["id"],)); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{c['name']}</td><td>{c['level']}</td><td><a href='/school/class/delete/{c['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No classes</td></tr>"
    table = f"<b>Classes ({len(classes)})</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Class</th><th>Level</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/classes/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='class_name' placeholder='Class *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='level' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Primary</option><option>Junior School</option><option>Senior School</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add Class</button></form>"
    return school_list_page(request, "Add Class", "classes", table, form)

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), level: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, level) VALUES (?,?,?)", (school["id"], class_name.strip(), level)); con.commit(); con.close(); return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/class/delete/{cid}")
def del_class(cid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=? AND school_id=?", (cid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['name']}</td><td>{s['code']}</td><td><a href='/school/subject/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No subjects</td></tr>"
    table = f"<b>Subjects ({len(subs)})</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Subject</th><th>Code</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/subjects/add' style='display:flex; flex-direction:column; gap:10px'><input name='subject_name' placeholder='Subject *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject_code' placeholder='Code' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add</button></form>"
    return school_list_page(request, "Add Subject", "subjects", table, form)

@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), subject_code: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO subjects (school_id, name, code) VALUES (?,?,?)", (school["id"], subject_name.strip(), subject_code.strip())); con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/subject/delete/{sid}")
def del_sub(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{e['name']}</td><td>{e['term']}</td><td>{e['year']}</td><td><a href='/school/exam/delete/{e['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan=4 style='padding:20px; text-align:center'>No exams</td></tr>"
    table = f"<b>Exams ({len(exams)})</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Exam</th><th>Term</th><th>Year</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/exams/add' style='display:flex; flex-direction:column; gap:10px'><input name='exam_name' placeholder='Exam *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='term' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' value='2026' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='exam_type' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Main Exam</option><option>CAT</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add</button></form>"
    return school_list_page(request, "Add Exam", "exams", table, form)

@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip(), term, year, exam_type)); con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/exam/delete/{eid}")
def del_exam(eid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM exams WHERE id=? AND school_id=?", (eid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/marks", response_class=HTMLResponse)
def school_marks(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall(); cur.execute("SELECT id, name FROM students WHERE school_id=? LIMIT 50", (school["id"],)); students = cur.fetchall(); con.close()
    e_opts = "".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams]); sub_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects]); st_opts = "".join([f"<option value='{st['id']}'>{st['name']}</option>" for st in students])
    form = f"<form method='post' action='/school/marks/add' style='display:flex; flex-direction:column; gap:10px'><select name='exam_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Exam</option>{e_opts}</select><select name='subject_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Subject</option>{sub_opts}</select><select name='student_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Student</option>{st_opts}</select><input name='score' type='number' placeholder='Score' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Save</button></form>"
    return school_list_page(request, "Enter Marks", "marks", "<b>Marks Entry</b>", form)

@app.post("/school/marks/add")
def add_marks(request: Request, exam_id: int = Form(...), subject_id: int = Form(...), student_id: int = Form(...), score: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO marks (school_id, exam_id, student_id, subject_id, score) VALUES (?,?,?,?,?)", (school["id"], exam_id, student_id, subject_id, score)); con.commit(); con.close(); return RedirectResponse("/school/marks", status_code=303)

@app.get("/school/marksheets", response_class=HTMLResponse)
def school_marksheets(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); con.close()
    cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><b>{e['name']}</b><a href='/school/marksheets/{e['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none'>View</a></div>" for e in exams]) or "No exams"
    html = school_header(school, request.session.get("name",""), "marksheets") + f"<div style='padding:20px'><h3>MarkSheets</h3><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px'>{cards}</div></div></div></div>"
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
    html = school_header(school, request.session.get("name",""), "marksheets") + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><b>{exam['name']}</b><button onclick='window.print()' style='float:right; background:#0f172a; color:white; padding:8px 14px; border:none; border-radius:8px'>Print</button><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px; border:1px solid #e2e8f0'>Student</th><th style='padding:8px; border:1px solid #e2e8f0'>Adm</th>{th}<th style='padding:8px; border:1px solid #e2e8f0'>Total</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

@app.get("/school/ranking", response_class=HTMLResponse)
def school_ranking(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM exams WHERE school_id=? LIMIT 1", (school["id"],)); e = cur.fetchone(); ranking_rows=""
    if e:
        cur.execute("SELECT s.id, s.name, SUM(m.score) total FROM students s JOIN marks m ON s.id=m.student_id WHERE m.exam_id=? GROUP BY s.id ORDER BY total DESC", (e["id"],));
        for idx,r in enumerate(cur.fetchall(),1): ranking_rows+=f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{idx}</td><td style='padding:10px; border-bottom:1px solid #eee'>{r['name']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-weight:700'>{r['total']}</td></tr>"
    con.close()
    if not ranking_rows: ranking_rows="<tr><td colspan=3 style='padding:20px; text-align:center'>No marks</td></tr>"
    html = school_header(school, request.session.get("name",""), "ranking") + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><table style='width:100%'><tr style='background:#f8fafc'><th>Rank</th><th>Student</th><th>Total</th></tr>{ranking_rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/analysis", response_class=HTMLResponse)
def school_analysis(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT AVG(score) avg FROM marks WHERE school_id=?", (school["id"],)); avg = cur.fetchone()["avg"] or 0; con.close()
    html = school_header(school, request.session.get("name",""), "analysis") + f"<div style='padding:20px'><b>Analysis Avg: {int(avg)}%</b></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/reports", response_class=HTMLResponse)
def school_reports(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT s.id, s.name FROM students s WHERE s.school_id=?", (school["id"],)); students = cur.fetchall(); con.close()
    cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><b>{s['name']}</b><a href='/school/report/{s['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none'>Report</a></div>" for s in students]) or "No students"
    html = school_header(school, request.session.get("name",""), "reports") + f"<div style='padding:20px'><h3>Reports</h3><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/report/{student_id}", response_class=HTMLResponse)
def student_report(student_id: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?", (student_id,)); st = cur.fetchone(); cur.execute("SELECT sub.name, m.score FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.student_id=?", (student_id,)); marks = cur.fetchall(); total=sum([m["score"] for m in marks]); con.close()
    rows="".join([f"<tr><td style='padding:8px; border:1px solid #eee'>{m['name']}</td><td style='padding:8px; border:1px solid #eee; text-align:center'>{m['score']}</td></tr>" for m in marks])
    html = school_header(school, request.session.get("name",""), "reports") + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px'><h2>{school['name']} Report</h2><div>{st['name']} | Total: {total}</div><table style='width:100%; margin-top:16px; border-collapse:collapse'><tr style='background:#f8fafc'><th>Subject</th><th>Score</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

@app.get("/school/timetable", response_class=HTMLResponse)
def school_timetable(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT t.*, c.name as cname FROM timetable t LEFT JOIN classes c ON t.class_id=c.id WHERE t.school_id=?", (school["id"],)); tt = cur.fetchall(); cur.execute("SELECT id, name FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    c_opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{t['day']}</td><td>{t['period']}</td><td>{t['cname']}</td><td>{t['subject']}</td><td>{t['teacher']}</td><td><a href='/school/timetable/delete/{t['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for t in tt]) or "<tr><td colspan=6 style='padding:20px; text-align:center'>No timetable</td></tr>"
    table = f"<b>Timetable</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Day</th><th>Period</th><th>Class</th><th>Subject</th><th>Teacher</th><th>Action</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/timetable/add' style='display:flex; flex-direction:column; gap:10px'><select name='class_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Class</option>{c_opts}</select><select name='day' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option></select><input name='period' placeholder='Period' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject' placeholder='Subject' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='teacher' placeholder='Teacher' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add</button></form>"
    return school_list_page(request, "Add Lesson", "timetable", table, form)

@app.post("/school/timetable/add")
def add_tt(request: Request, class_id: int = Form(...), day: str = Form(...), period: str = Form(...), subject: str = Form(...), teacher: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO timetable (school_id, class_id, day, period, subject, teacher) VALUES (?,?,?,?,?,?)", (school["id"], class_id, day, period, subject, teacher)); con.commit(); con.close(); return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/timetable/delete/{tid}")
def del_tt(tid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM timetable WHERE id=? AND school_id=?", (tid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/fees", response_class=HTMLResponse)
def school_fees(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT f.*, s.name as sname FROM fees f JOIN students s ON f.student_id=s.id WHERE f.school_id=?", (school["id"],)); fees = cur.fetchall(); cur.execute("SELECT id, name FROM students WHERE school_id=?", (school["id"],)); students = cur.fetchall(); con.close()
    st_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in students])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{f['sname']}</td><td>{f['term']}</td><td>KES {f['total']}</td><td>KES {f['paid']}</td><td>KES {f['balance']}</td></tr>" for f in fees]) or "<tr><td colspan=5 style='padding:20px; text-align:center'>No fees</td></tr>"
    table = f"<b>Fees</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Student</th><th>Term</th><th>Total</th><th>Paid</th><th>Balance</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/fees/add' style='display:flex; flex-direction:column; gap:10px'><select name='student_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Student</option>{st_opts}</select><select name='term' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='total' type='number' placeholder='Total' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='paid' type='number' placeholder='Paid' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Save</button></form>"
    return school_list_page(request, "Record Fees", "fees", table, form)

@app.post("/school/fees/add")
def add_fees(request: Request, student_id: int = Form(...), term: str = Form(...), total: int = Form(...), paid: int = Form(...)):
    school = get_school_obj(request); balance = total - paid; con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO fees (school_id, student_id, term, total, paid, balance) VALUES (?,?,?,?,?,?)", (school["id"], student_id, term, total, paid, balance)); con.commit(); con.close(); return RedirectResponse("/school/fees", status_code=303)

@app.get("/school/sms", response_class=HTMLResponse)
def school_sms(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM sms_logs WHERE school_id=? ORDER BY id DESC LIMIT 20", (school["id"],)); logs = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['recipient']}</td><td>{s['message'][:60]}</td><td>{s['timestamp']}</td></tr>" for s in logs]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No SMS</td></tr>"
    table = f"<b>SMS Logs</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>To</th><th>Message</th><th>Time</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/sms/send' style='display:flex; flex-direction:column; gap:10px'><textarea name='message' placeholder='Message' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px; height:100px'></textarea><button style='background:#16a34a; color:white; padding:12px; border:none; border-radius:8px'>Send to All Parents</button></form>"
    return school_list_page(request, "Send SMS", "sms", table, form)

@app.post("/school/sms/send")
def send_sms(request: Request, message: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT parent_phone FROM students WHERE school_id=?", (school["id"],)); parents = cur.fetchall(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    for p in parents: cur.execute("INSERT INTO sms_logs (school_id, recipient, message, timestamp) VALUES (?,?,?,?)", (school["id"], p["parent_phone"], message, ts))
    con.commit(); con.close(); return RedirectResponse("/school/sms", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email",""); name = request.session.get("name",""); role = request.session.get("role","")
    return HTMLResponse(f"<html><body style='font-family:Arial; padding:20px'><h2>{name}</h2><p>{email}</p><p>Role: {role}</p><a href='/school/dashboard'>Back</a> | <a href='/logout'>Logout</a></body></html>")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

@app.get("/schools/manage", response_class=HTMLResponse)
def schools_manage(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools"); schools = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['name']}</td><td>{s['email']}</td><td>{s['code']}</td><td>{s['location']}</td></tr>" for s in schools])
    return HTMLResponse(f"<html><body style='font-family:Arial; padding:20px'><h2>Schools</h2><table style='width:100%'><tr style='background:#f8fafc'><th>Name</th><th>Email</th><th>Code</th><th>Location</th></tr>{rows}</table><br><a href='/dashboard'>Back</a></body></html>")
