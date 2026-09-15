from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random, json, smtplib, ssl
from datetime import datetime
from zoneinfo import ZoneInfo
import os

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v28-1-fixed-asc")
SUPER_ADMIN = "oumadavis62@gmail.com"
EMAIL_SENDER = SUPER_ADMIN
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

ROLE_PERMISSIONS = {
    "school_admin": ["dashboard","students","classes","subjects","exams","marks","marksheets","ranking","analysis","reports","timetable","fees","sms","staff","profile"],
    "deputy_principal": ["dashboard","students","classes","subjects","exams","marks","marksheets","ranking","analysis","reports","timetable","fees","sms","profile"],
    "dos": ["dashboard","students","exams","marks","marksheets","ranking","analysis","reports","timetable","profile"],
    "hod": ["dashboard","students","marks","marksheets","analysis","reports","timetable","profile"],
    "teacher": ["dashboard","students","marks","marksheets","timetable","profile"],
    "bursar": ["dashboard","students","fees","profile"],
    "class_teacher": ["dashboard","students","marks","marksheets","timetable","profile"],
}
ROLE_LABELS = {
    "school_admin": "Principal", "deputy_principal": "Deputy", "dos": "DOS",
    "hod": "HOD", "teacher": "Teacher", "bursar": "Bursar", "class_teacher": "Class Teacher"
}
ROLE_PASS = {"deputy_principal":"DEPUTY","dos":"DOS","hod":"HOD","teacher":"TEACH","class_teacher":"CTEACH","bursar":"BURSAR"}

PERIODS = ["8:00-8:40","8:40-9:20","9:20-10:00","10:30-11:10","11:10-11:50","11:50-12:30","14:00-14:40","14:40-15:20"]
DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday"]

def has_perm(role, page):
    if role=="super_admin": return True
    return page in ROLE_PERMISSIONS.get(role,[])

def get_db():
    con=sqlite3.connect("davischool.db")
    con.row_factory=sqlite3.Row
    return con

def init_db():
    con=get_db(); cur=con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, class_name TEXT, stream TEXT, class_teacher_id INTEGER, class_teacher_name TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_name TEXT, parent_phone TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, exam_id INTEGER, student_id INTEGER, subject_id INTEGER, score INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, term TEXT, total INTEGER, paid INTEGER, balance INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS timetable (id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER, day TEXT, period TEXT, subject TEXT, teacher TEXT, teacher_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS sms_logs (id INTEGER PRIMARY KEY, school_id INTEGER, recipient TEXT, message TEXT, timestamp TEXT)")
    try: cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    except: pass
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit(); con.close()
init_db()

def gen_staff_pass(role): return f"{ROLE_PASS.get(role,'STAFF')}@{random.randint(1000,9999)}!"
def gen_school_pass(name):
    p="".join([c for c in name.upper() if c.isalpha()])[:4]
    if len(p)<3: p="SCH"
    return f"{p}@{random.randint(1000,9999)}!"

def send_email(to_email, subject, body):
    if not EMAIL_PASSWORD: return False
    try:
        from email.message import EmailMessage
        msg=EmailMessage(); msg["From"]=EMAIL_SENDER; msg["To"]=to_email; msg["Subject"]=subject; msg.set_content(body)
        context=ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context); server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.send_message(msg)
        return True
    except: return False

def get_school_obj(req):
    sid=req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin": return None
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s=cur.fetchone(); con.close(); return s

def header_html(initials, name, email):
    return f"<div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 20px;display:flex;justify-content:space-between'><div><b>🏫 Davischool Platform</b><div style='font-size:11px;color:#64748b'>{name}</div></div><div style='width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800'>{initials}</div></div>"

def school_header(school, name, active="dashboard", role="school_admin"):
    initials="".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    def nav(link, icon, label):
        if not has_perm(role, link): return ""
        a="background:#0f172a;color:white" if active==link else "color:#475569"
        return f"<a href='/school/{link}' style='display:flex;gap:8px;padding:10px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:3px;{a}'>{icon} {label}</a>"
    staff_link=f"<a href='/school/staff' style='display:flex;gap:8px;padding:10px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:3px;{'background:#0f172a;color:white' if active=='staff' else 'color:#7c3aed'}'>👥 Staff & Roles</a>" if role=="school_admin" else ""
    return f"<div style='display:flex;min-height:100vh'><div style='width:240px;background:white;border-right:1px solid #e2e8f0;padding:14px'><div style='padding:10px;border-bottom:1px solid #f1f5f9;margin-bottom:10px'><b style='font-size:13px'>{school['name'][:18]}</b><div style='font-size:10px;color:#64748b'>{ROLE_LABELS.get(role,role)}</div></div>{nav('dashboard','📊','Dashboard')}{nav('students','🎓','Students')}{nav('classes','🏫','Classes')}{nav('subjects','📚','Subjects')}{nav('exams','📝','Exams')}{nav('marks','✍️','Marks')}{nav('marksheets','📄','MarkSheets')}{nav('ranking','🏆','Ranking')}{nav('analysis','📈','Analysis')}{nav('reports','📑','Reports')}{nav('timetable','🗓️','Timetable ASC')}{nav('fees','💰','Fees')}{nav('sms','💬','SMS')}{staff_link}<a href='/logout' style='display:flex;gap:8px;padding:10px 12px;border-radius:8px;text-decoration:none;font-size:13px;color:#dc2626;margin-top:12px'>🚪 Logout</a></div><div style='flex:1;background:#f8fafc'><div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 16px;display:flex;justify-content:space-between'><b>DaviSchool - {ROLE_LABELS.get(role,role)}</b><span style='font-size:11px;background:#ede9fe;color:#5b21b6;padding:4px 8px;border-radius:12px'>{name}</span></div>"

@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.get("/", response_class=HTMLResponse)
def home():
    return "<html><body style='font-family:Arial;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f8fafc'><div style='background:white;padding:30px;border-radius:12px;border:1px solid #e2e8f0;width:360px'><h2 style='text-align:center'>Davischool</h2><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%;padding:11px;margin:6px 0;border:1px solid #e2e8f0;border-radius:8px'><input name='password' type='password' placeholder='Password' required style='width:100%;padding:11px;margin:6px 0 16px;border:1px solid #e2e8f0;border-radius:8px'><button style='width:100%;background:#0f172a;color:white;padding:11px;border:none;border-radius:8px'>Sign In</button></form></div></body></html>"

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password)); u=cur.fetchone(); con.close()
    if not u: return HTMLResponse("Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    if u["role"]!="super_admin": return RedirectResponse("/school/dashboard", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/school/dashboard")
    con=get_db(); cur=con.cursor(); cur.execute("SELECT COUNT(*) c FROM schools"); total=cur.fetchone()["c"]; cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5"); recent=cur.fetchall(); con.close()
    name=request.session.get("name","Davis"); initials="".join([p[0] for p in name.split()][:2]).upper()
    rows="".join([f"<tr><td style='padding:10px;border-bottom:1px solid #eee'>🏫 {s['name']}</td><td style='padding:10px;border-bottom:1px solid #eee'>{s['location']}</td><td style='padding:10px;border-bottom:1px solid #eee'>✅ Active</td></tr>" for s in recent]) or "<tr><td colspan=3 style='padding:20px;text-align:center'>No schools</td></tr>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{header_html(initials,name,request.session.get('email',''))}<div style='padding:20px'><h2>📊 Overview - {total} Schools</h2><div style='background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px'><table style='width:100%;border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:10px;text-align:left'>Name</th><th style='padding:10px;text-align:left'>Location</th><th>Status</th></tr>{rows}</table></div><div style='margin-top:16px'><a href='/schools/manage' style='background:#0f172a;color:white;padding:10px 16px;border-radius:8px;text-decoration:none'>🏫 Manage Schools</a></div></div></body></html>")

def list_page(request, title, active, table, form):
    school=get_school_obj(request); name=request.session.get("name",""); role=request.session.get("role","")
    html=school_header(school,name,active,role)
    html+=f"<div style='padding:16px;display:grid;grid-template-columns:1fr 360px;gap:14px'><div style='background:white;border:1px solid #e2e8f0;border-radius:12px;padding:14px'>{table}</div><div style='background:white;border:1px solid #e2e8f0;border-radius:12px;padding:14px;position:sticky;top:16px'><b>{title}</b>{form}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{html}</body></html>")

@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school=get_school_obj(request)
    if not school:
        if request.session.get("role")=="super_admin": return RedirectResponse("/dashboard")
        return RedirectResponse("/")
    name=request.session.get("name",""); role=request.session.get("role","")
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc=cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc=cur.fetchone()["c"]
    today=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%A")
    cur.execute("SELECT t.*, c.name as cname FROM timetable t LEFT JOIN classes c ON t.class_id=c.id WHERE t.school_id=? AND t.day=? AND t.teacher LIKE? ORDER BY t.period", (school["id"], today, f"%{name}%"))
    todays=cur.fetchall(); con.close()
    today_html="".join([f"<div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:8px;margin-bottom:6px'><b style='font-size:12px'>{t['period']}</b><div style='font-size:11px;color:#64748b'>{t['cname']} - {t['subject']}</div></div>" for t in todays]) or f"<div style='padding:10px;text-align:center;color:#999;font-size:12px'>No lessons today ({today})</div>"
    html=school_header(school,name,"dashboard",role)
    html+=f"<div style='padding:16px'><div style='background:linear-gradient(135deg,#0f172a,#1e40af);border-radius:14px;padding:16px;color:white'><h2 style='margin:0'>DaviSchool ASC - {ROLE_LABELS.get(role,role)}</h2><p style='font-size:12px;color:#bfdbfe'>Today {today} | {len(todays)} lessons</p></div><div style='display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-top:14px'><div style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px'><div style='font-size:11px'>Students</div><div style='font-size:22px;font-weight:800'>{sc}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px'><div style='font-size:11px'>Classes</div><div style='font-size:22px;font-weight:800'>{cc}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px'><div style='font-size:11px'>Today</div><div style='font-size:22px;font-weight:800'>{len(todays)}</div></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px'><b>🔔 Today's Lessons - {today}</b><div style='margin-top:10px'>{today_html}</div></div></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial'>{html}</body></html>")

@app.get("/school/staff", response_class=HTMLResponse)
def school_staff(request: Request, success: str = "", new_email: str = "", new_pass: str = "", new_name: str = "", new_role: str = ""):
    if request.session.get("role")!="school_admin": return HTMLResponse("Only Principal <a href='/school/dashboard'>Back</a>")
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM users WHERE school_id=? ORDER BY full_name", (school["id"],)); staff=cur.fetchall(); con.close()
    banner=f"<div style='background:#dcfce7;border:1px solid #16a34a;padding:12px;border-radius:8px;margin-bottom:10px'><b>✅ {new_name} added!</b><div>Username: {new_email}</div><div>Password: <b>{new_pass}</b></div></div>" if success=="added" else ""
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee;font-size:12px'><b>{s['full_name']}</b><div style='font-size:10px'>{s['email']}</div></td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{ROLE_LABELS.get(s['role'],s['role'])}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{s['password']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{'' if s['role']=='school_admin' else f'<a href=/school/staff/delete/{s[\"id\"]} style=color:#dc2626>🗑️</a>'}</td></tr>" for s in staff])
    table=f"{banner}<b>👥 Staff ({len(staff)})</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc;font-size:11px'><th style='padding:8px;text-align:left'>Name</th><th>Role</th><th>Pass</th><th>Action</th></tr>{rows}</table>"
    form="<form method='post' action='/school/staff/add' style='display:flex;flex-direction:column;gap:10px;margin-top:12px'><input name='full_name' placeholder='Full Name *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='email' type='email' placeholder='Email (username) *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><select name='role' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Select Role *</option><option value='deputy_principal'>Deputy Principal</option><option value='dos'>DOS</option><option value='hod'>HOD</option><option value='teacher'>Teacher</option><option value='class_teacher'>Class Teacher</option><option value='bursar'>Bursar</option></select><button style='background:#7c3aed;color:white;padding:11px;border:none;border-radius:8px'>➕ Add - Auto Password</button></form>"
    return list_page(request, "Add Staff", "staff", table, form)

@app.post("/school/staff/add")
def add_staff(request: Request, full_name: str = Form(...), email: str = Form(...), role: str = Form(...)):
    if request.session.get("role")!="school_admin": return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); auto_pass=gen_staff_pass(role)
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM users WHERE email=?", (email.strip(),))
    if cur.fetchone(): con.close(); return HTMLResponse("Email exists <a href='/school/staff'>Back</a>")
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (email.strip(), auto_pass, role, full_name.strip(), school["id"])); con.commit(); con.close()
    return RedirectResponse(f"/school/staff?success=added&new_email={email}&new_pass={auto_pass}&new_name={full_name}&new_role={role}", status_code=303)

@app.get("/school/staff/delete/{uid}")
def del_staff(uid: int, request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM users WHERE id=? AND school_id=? AND role!='school_admin'", (uid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/staff", status_code=303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    if not has_perm(request.session.get("role",""), "classes"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY id DESC", (school["id"],)); classes=cur.fetchall()
    cur.execute("SELECT id, full_name, role FROM users WHERE school_id=? AND role!='school_admin' ORDER BY full_name", (school["id"],)); teachers=cur.fetchall()
    cur.execute("SELECT c.id, COUNT(s.id) cnt FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.school_id=? WHERE c.school_id=? GROUP BY c.id", (school["id"], school["id"])); counts={r[0]:r[1] for r in cur.fetchall()}
    con.close()
    teacher_opts="".join([f"<option value='{t['id']}|{t['full_name']}'>{t['full_name']} ({t['role']})</option>" for t in teachers]) or "<option value=''>No teachers - add staff first</option>"
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'><b>{c['class_name'] or c['name']}</b></td><td style='padding:8px;border-bottom:1px solid #eee'>{c['stream'] or '-'}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{c['class_teacher_name'] or 'Not assigned'}</td><td style='padding:8px;border-bottom:1px solid #eee'>{c['level']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{counts.get(c['id'],0)}</td><td style='padding:8px;border-bottom:1px solid #eee'><a href='/school/class/delete/{c['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan=6 style='padding:20px;text-align:center;color:#999'>No classes</td></tr>"
    table=f"<b>🏫 Classes ({len(classes)})</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc;font-size:11px'><th style='padding:8px;text-align:left'>Class</th><th>Stream</th><th>Class Teacher</th><th>Level</th><th>Students</th><th>Action</th></tr>{rows}</table>"
    form=f"<form method='post' action='/school/classes/add' style='display:flex;flex-direction:column;gap:10px;margin-top:12px'><input name='class_name' placeholder='Class e.g. Class 8' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='stream' placeholder='Stream e.g. East' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><select name='class_teacher' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Select Class Teacher *</option>{teacher_opts}</select><select name='level' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Level *</option><option>Pre-Primary</option><option>Primary</option><option>Junior School</option><option>Senior School</option><option>8-4-4</option></select><button style='background:#0f172a;color:white;padding:11px;border:none;border-radius:8px'>➕ Add Class</button></form>"
    return list_page(request, "Add Class/Stream", "classes", table, form)

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), stream: str = Form(...), class_teacher: str = Form(...), level: str = Form(...)):
    school=get_school_obj(request)
    try: tid,tname=class_teacher.split("|",1); tid=int(tid)
    except: tid=0; tname=class_teacher
    full=f"{class_name.strip()} {stream.strip()}"
    con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO classes (school_id, name, level, class_name, stream, class_teacher_id, class_teacher_name) VALUES (?,?,?,?,?,?,?)", (school["id"], full, level, class_name.strip(), stream.strip(), tid, tname.strip())); con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/class/delete/{cid}")
def del_class(cid: int, request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM classes WHERE id=? AND school_id=?", (cid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/classes", status_code=303)

# === ASC TIMETABLE - FIXED & LEAN ===
@app.get("/school/timetable", response_class=HTMLResponse)
def school_timetable(request: Request, class_id: str = "", teacher_id: str = "", view: str = "class", error: str = ""):
    if not has_perm(request.session.get("role",""), "timetable"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes=cur.fetchall()
    cur.execute("SELECT id, full_name, role FROM users WHERE school_id=? AND role!='school_admin' ORDER BY full_name", (school["id"],)); teachers=cur.fetchall()
    cur.execute("SELECT t.*, c.name as cname FROM timetable t LEFT JOIN classes c ON t.class_id=c.id WHERE t.school_id=? ORDER BY t.day, t.period", (school["id"],)); all_tt=cur.fetchall()
    cur.execute("SELECT name FROM subjects WHERE school_id=?", (school["id"],)); subjects=cur.fetchall()
    con.close()

    if not class_id and classes: class_id=str(classes[0]["id"])
    if not teacher_id and teachers: teacher_id=str(teachers[0]["id"])

    class_opts="".join([f"<option value='{c['id']}' {'selected' if str(c['id'])==class_id else ''}>{c['name']}</option>" for c in classes])
    teacher_opts="".join([f"<option value='{t['id']}' {'selected' if str(t['id'])==teacher_id else ''}>{t['full_name']}</option>" for t in teachers])
    subject_opts="".join([f"<option value='{s['name']}'>{s['name']}</option>" for s in subjects])
    period_opts="".join([f"<option value='{p}'>{p}</option>" for p in PERIODS])
    day_opts="".join([f"<option value='{d}'>{d}</option>" for d in DAYS])

    # Build grid for selected class - ASC style
    tt_map={}
    for e in all_tt:
        if str(e["class_id"])==str(class_id):
            tt_map[(e["day"], e["period"])]=e

    grid_html=""
    for period in PERIODS:
        cells=""
        for day in DAYS:
            entry=tt_map.get((day, period))
            if entry:
                cells+=f"<td style='padding:6px;border:1px solid #e2e8f0;background:#dbeafe;text-align:center'><div style='font-size:11px;font-weight:700'>{entry['subject']}</div><div style='font-size:9px'>{entry['teacher'][:10]}</div><a href='/school/timetable/delete/{entry['id']}' style='font-size:9px;color:#dc2626'>x</a></td>"
            else:
                cells+=f"<td style='padding:8px;border:1px solid #f1f5f9;text-align:center;color:#cbd5e1'>-</td>"
        grid_html+=f"<tr><td style='padding:8px;border:1px solid #e2e8f0;background:#f8fafc;font-size:11px;font-weight:600'>{period}</td>{cells}</tr>"

    # Teacher grid
    teacher_map={}
    sel_teacher_name=""
    for t in teachers:
        if str(t["id"])==str(teacher_id): sel_teacher_name=t["full_name"]
    for e in all_tt:
        if e["teacher"]==sel_teacher_name or str(e["teacher_id"])==str(teacher_id):
            teacher_map[(e["day"], e["period"])]=e

    teacher_grid=""
    for period in PERIODS:
        cells=""
        for day in DAYS:
            entry=teacher_map.get((day, period))
            if entry:
                cells+=f"<td style='padding:6px;border:1px solid #e2e8f0;background:#ede9fe;text-align:center'><div style='font-size:11px;font-weight:700'>{entry['subject']}</div><div style='font-size:9px'>{entry['cname'] or ''}</div></td>"
            else:
                cells+=f"<td style='padding:8px;border:1px solid #f1f5f9;text-align:center;color:#cbd5e1'>-</td>"
        teacher_grid+=f"<tr><td style='padding:8px;border:1px solid #e2e8f0;background:#f8fafc;font-size:11px'>{period}</td>{cells}</tr>"

    list_rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{t['day']}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{t['period']}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{t['cname']}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{t['subject']}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{t['teacher']}</td><td style='padding:8px;border-bottom:1px solid #eee'><a href='/school/timetable/delete/{t['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for t in all_tt]) or "<tr><td colspan=6 style='padding:20px;text-align:center;color:#999'>No lessons yet</td></tr>"

    error_banner=f"<div style='background:#fef2f2;border:1px solid #fecaca;color:#dc2626;padding:10px;border-radius:8px;margin-bottom:10px;font-size:13px'>⚠️ {error}</div>" if error else ""

    # Tabs content - simple if
    if view=="teacher":
        main_content=f"<div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;overflow-x:auto'><div style='display:flex;justify-content:space-between;margin-bottom:10px'><b>👨‍🏫 Teacher: {sel_teacher_name}</b><form method='get'><input type='hidden' name='view' value='teacher'><select name='teacher_id' onchange='this.form.submit()' style='padding:6px;border:1px solid #e2e8f0;border-radius:6px'><option value=''>Select Teacher</option>{teacher_opts}</select></form></div><table style='width:100%;border-collapse:collapse;min-width:600px'><tr style='background:#5b21b6;color:white'><th style='padding:8px;border:1px solid #4c1d95;font-size:11px'>Period</th>{''.join([f'<th style=padding:8px;border:1px solid #4c1d95;font-size:11px>{d}</th>' for d in DAYS])}</tr>{teacher_grid}</table></div>"
    elif view=="list":
        main_content=f"<div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px'><b>📋 All Lessons ({len(all_tt)})</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc;font-size:11px'><th style='padding:8px;text-align:left'>Day</th><th>Period</th><th>Class</th><th>Subject</th><th>Teacher</th><th>Action</th></tr>{list_rows}</table></div>"
    else:
        main_content=f"<div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;overflow-x:auto'><div style='display:flex;justify-content:space-between;margin-bottom:10px'><b>🏫 Class WallMaster</b><div style='display:flex;gap:6px'><form method='get'><input type='hidden' name='view' value='class'><select name='class_id' onchange='this.form.submit()' style='padding:6px;border:1px solid #e2e8f0;border-radius:6px'><option value=''>Select Class</option>{class_opts}</select></form><a href='/school/timetable/print?class_id={class_id}' target='_blank' style='background:#0f172a;color:white;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px'>🖨️ Print</a></div></div><table style='width:100%;border-collapse:collapse;min-width:600px'><tr style='background:#0f172a;color:white'><th style='padding:8px;border:1px solid #1e293b;font-size:11px'>Period</th>{''.join([f'<th style=padding:8px;border:1px solid #1e293b;font-size:11px>{d}</th>' for d in DAYS])}</tr>{grid_html}</table></div>"

    html=school_header(school, request.session.get("name",""), "timetable", request.session.get("role",""))
    html+=f"<div style='padding:14px'>{error_banner}<div style='display:flex;gap:6px;margin-bottom:12px'><a href='/school/timetable?view=class&class_id={class_id}' style='padding:8px 12px;border-radius:8px;text-decoration:none;font-size:12px;{'background:#0f172a;color:white' if view=='class' else 'background:white;border:1px solid #e2e8f0;color:#64748b'}'>🏫 Class WallMaster</a><a href='/school/timetable?view=teacher&teacher_id={teacher_id}' style='padding:8px 12px;border-radius:8px;text-decoration:none;font-size:12px;{'background:#0f172a;color:white' if view=='teacher' else 'background:white;border:1px solid #e2e8f0;color:#64748b'}'>👨‍🏫 Teacher</a><a href='/school/timetable?view=list' style='padding:8px 12px;border-radius:8px;text-decoration:none;font-size:12px;{'background:#0f172a;color:white' if view=='list' else 'background:white;border:1px solid #e2e8f0;color:#64748b'}'>📋 List</a></div><div style='display:grid;grid-template-columns:1fr 340px;gap:14px'><div>{main_content}</div><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;position:sticky;top:14px'><b>➕ Add Lesson - ASC Checker</b><div style='font-size:10px;color:#64748b;margin-top:4px'>Checks teacher & class clash</div><form method='post' action='/school/timetable/add' style='display:flex;flex-direction:column;gap:8px;margin-top:10px'><select name='class_id' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Select Class *</option>{class_opts}</select><select name='day' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Day *</option>{day_opts}</select><select name='period' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Period *</option>{period_opts}</select><select name='subject' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Subject *</option>{subject_opts}</select><select name='teacher_id' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Teacher *</option>{teacher_opts}</select><button style='background:#0f172a;color:white;padding:11px;border:none;border-radius:8px;font-weight:700'>Add Lesson</button></form></div></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{html}</body></html>")

@app.get("/school/timetable/print")
def print_tt(request: Request, class_id: str = ""):
    school=get_school_obj(request); con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?", (class_id, school["id"])); cls=cur.fetchone()
    if not cls: cur.execute("SELECT * FROM classes WHERE school_id=? LIMIT 1", (school["id"],)); cls=cur.fetchone()
    if cls: class_id=cls["id"]
    cur.execute("SELECT * FROM timetable WHERE class_id=? AND school_id=?", (class_id, school["id"])); entries=cur.fetchall(); con.close()
    if not cls: return HTMLResponse("No class <a href='/school/timetable'>Back</a>")
    mp={(e["day"], e["period"]): e for e in entries}
    rows=""
    for p in PERIODS:
        cells=""
        for d in DAYS:
            e=mp.get((d,p))
            cells+=f"<td style='padding:10px;border:2px solid #000;text-align:center'><b>{e['subject'] if e else '-'}</b><div style='font-size:11px'>{e['teacher'] if e else ''}</div></td>" if e else "<td style='padding:10px;border:2px solid #000;text-align:center;color:#ccc'>-</td>"
        rows+=f"<tr><td style='padding:10px;border:2px solid #000;background:#f1f5f9;font-weight:700'>{p}</td>{cells}</tr>"
    return HTMLResponse(f"<html><body style='font-family:Arial;padding:20px'><h2 style='text-align:center'>{school['name']} - {cls['name']} WallMaster</h2><p style='text-align:center'>Level: {cls['level']} | Class Teacher: {cls['class_teacher_name'] or '-'}</p><table style='width:100%;border-collapse:collapse;border:3px solid #000'><tr style='background:#000;color:white'><th style='padding:10px;border:2px solid #000'>Period</th>{''.join([f'<th style=padding:10px;border:2px solid #000>{d}</th>' for d in DAYS])}</tr>{rows}</table><div style='text-align:right;margin-top:16px'><button onclick='window.print()' style='background:#000;color:white;padding:10px 20px;border:none;border-radius:8px'>🖨️ Print</button></div></body></html>")

@app.post("/school/timetable/add")
def add_tt(request: Request, class_id: int = Form(...), day: str = Form(...), period: str = Form(...), subject: str = Form(...), teacher_id: int = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=con.cursor()
    cur.execute("SELECT full_name FROM users WHERE id=? AND school_id=?", (teacher_id, school["id"])); t=cur.fetchone(); tname=t["full_name"] if t else f"Teacher {teacher_id}"
    cur.execute("SELECT * FROM timetable WHERE school_id=? AND class_id=? AND day=? AND period=?", (school["id"], class_id, day, period))
    if cur.fetchone(): con.close(); return RedirectResponse(f"/school/timetable?error=Class already has lesson at {day} {period}&view=class&class_id={class_id}", status_code=303)
    cur.execute("SELECT * FROM timetable WHERE school_id=? AND day=? AND period=? AND (teacher_id=? OR teacher=?)", (school["id"], day, period, teacher_id, tname))
    cf=cur.fetchone()
    if cf:
        cur.execute("SELECT name FROM classes WHERE id=?", (cf["class_id"],)); cn=cur.fetchone(); cname=cn["name"] if cn else "other class"
        con.close(); return RedirectResponse(f"/school/timetable?error=Teacher {tname} already teaching {cname} at {day} {period}&view=teacher&teacher_id={teacher_id}", status_code=303)
    cur.execute("INSERT INTO timetable (school_id, class_id, day, period, subject, teacher, teacher_id) VALUES (?,?,?,?,?,?,?)", (school["id"], class_id, day, period, subject, tname, teacher_id)); con.commit(); con.close()
    return RedirectResponse(f"/school/timetable?view=class&class_id={class_id}", status_code=303)

@app.get("/school/timetable/delete/{tid}")
def del_tt(tid: int, request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM timetable WHERE id=? AND school_id=?", (tid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/timetable", status_code=303)

# OTHER PAGES - keep same lean
@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if not has_perm(request.session.get("role",""), "students"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students=cur.fetchall(); cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes=cur.fetchall(); con.close()
    opts="".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{s['name']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{s['admission_no']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{s['cname'] or ''}</td><td style='padding:8px;border-bottom:1px solid #eee'><a href='/school/student/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for s in students]) or "<tr><td colspan=4 style='padding:20px;text-align:center'>No students</td></tr>"
    table=f"<b>🎓 Students ({len(students)})</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px;text-align:left'>Name</th><th>Adm</th><th>Class</th><th>Action</th></tr>{rows}</table>"
    form=f"<form method='post' action='/school/students/add' style='display:flex;flex-direction:column;gap:8px;margin-top:10px'><input name='admission_no' placeholder='Adm No *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='student_name' placeholder='Student Name *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><select name='class_id' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Class *</option>{opts}</select><select name='gender' style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option>Male</option><option>Female</option></select><input name='parent_name' placeholder='Parent Name' style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='parent_phone' placeholder='Parent Phone *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><button style='background:#0f172a;color:white;padding:10px;border:none;border-radius:8px'>Add Student</button></form>"
    return list_page(request, "Add Student", "students", table, form)

@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_name: str = Form(...), parent_phone: str = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO students (school_id, admission_no, name, class_id, gender, parent_name, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], admission_no.strip(), student_name.strip(), class_id, gender, parent_name, parent_phone)); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/student/delete/{sid}")
def del_student(sid: int, request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM students WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    if not has_perm(request.session.get("role",""), "subjects"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subs=cur.fetchall(); con.close()
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{s['name']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{s['code']}</td><td><a href='/school/subject/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan=3 style='padding:20px;text-align:center'>No subjects</td></tr>"
    table=f"<b>📚 Subjects ({len(subs)})</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px;text-align:left'>Subject</th><th>Code</th><th>Action</th></tr>{rows}</table>"
    form="<form method='post' action='/school/subjects/add' style='display:flex;flex-direction:column;gap:8px;margin-top:10px'><input name='subject_name' placeholder='Subject *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='subject_code' placeholder='Code' style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><button style='background:#0f172a;color:white;padding:10px;border:none;border-radius:8px'>Add</button></form>"
    return list_page(request, "Add Subject", "subjects", table, form)

@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), subject_code: str = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO subjects (school_id, name, code) VALUES (?,?,?)", (school["id"], subject_name.strip(), subject_code.strip())); con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/subject/delete/{sid}")
def del_sub(sid: int, request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    if not has_perm(request.session.get("role",""), "exams"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams=cur.fetchall(); con.close()
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{e['name']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{e['term']}</td><td style='padding:8px;border-bottom:1px solid #eee'><a href='/school/exam/delete/{e['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan=3 style='padding:20px;text-align:center'>No exams</td></tr>"
    table=f"<b>📝 Exams ({len(exams)})</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px;text-align:left'>Exam</th><th>Term</th><th>Action</th></tr>{rows}</table>"
    form="<form method='post' action='/school/exams/add' style='display:flex;flex-direction:column;gap:8px;margin-top:10px'><input name='exam_name' placeholder='Exam Name *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><select name='term' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' value='2026' style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><button style='background:#0f172a;color:white;padding:10px;border:none;border-radius:8px'>Add Exam</button></form>"
    return list_page(request, "Add Exam", "exams", table, form)

@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO exams (school_id, name, term, year) VALUES (?,?,?,?)", (school["id"], exam_name.strip(), term, year)); con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/exam/delete/{eid}")
def del_exam(eid: int, request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM exams WHERE id=? AND school_id=?", (eid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/marks", response_class=HTMLResponse)
def school_marks(request: Request):
    if not has_perm(request.session.get("role",""), "marks"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams=cur.fetchall(); cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subjects=cur.fetchall(); cur.execute("SELECT id, name FROM students WHERE school_id=? LIMIT 30", (school["id"],)); students=cur.fetchall(); cur.execute("SELECT m.*, s.name as sname FROM marks m JOIN students s ON m.student_id=s.id WHERE m.school_id=? ORDER BY m.id DESC LIMIT 10", (school["id"],)); recent=cur.fetchall(); con.close()
    e_opts="".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams]); sub_opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects]); st_opts="".join([f"<option value='{st['id']}'>{st['name']}</option>" for st in students])
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{r['sname']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{r['score']}</td></tr>" for r in recent]) or "<tr><td colspan=2 style='padding:20px;text-align:center'>No marks</td></tr>"
    table=f"<b>✍️ Recent Marks</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px;text-align:left'>Student</th><th>Score</th></tr>{rows}</table>"
    form=f"<form method='post' action='/school/marks/add' style='display:flex;flex-direction:column;gap:8px;margin-top:10px'><select name='exam_id' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Exam *</option>{e_opts}</select><select name='subject_id' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Subject *</option>{sub_opts}</select><select name='student_id' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Student *</option>{st_opts}</select><input name='score' type='number' min='0' max='100' placeholder='Score *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><button style='background:#0f172a;color:white;padding:10px;border:none;border-radius:8px'>Save</button></form>"
    return list_page(request, "Enter Marks", "marks", table, form)

@app.post("/school/marks/add")
def add_marks(request: Request, exam_id: int = Form(...), subject_id: int = Form(...), student_id: int = Form(...), score: int = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO marks (school_id, exam_id, student_id, subject_id, score) VALUES (?,?,?,?,?)", (school["id"], exam_id, student_id, subject_id, score)); con.commit(); con.close(); return RedirectResponse("/school/marks", status_code=303)

@app.get("/school/marksheets", response_class=HTMLResponse)
def school_marksheets(request: Request):
    if not has_perm(request.session.get("role",""), "marksheets"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams=cur.fetchall(); con.close()
    cards="".join([f"<div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:12px'><b>{e['name']}</b><div style='font-size:11px'>{e['term']}</div><a href='/school/marksheets/{e['id']}' style='display:block;margin-top:8px;background:#0f172a;color:white;padding:6px;border-radius:6px;text-align:center;text-decoration:none'>View</a></div>" for e in exams]) or "No exams"
    html=school_header(school, request.session.get("name",""), "marksheets", request.session.get("role","")) + f"<div style='padding:16px'><h3>📄 MarkSheets</h3><div style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{html}</body></html>")

@app.get("/school/marksheets/{exam_id}", response_class=HTMLResponse)
def view_marksheet(exam_id: int, request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM exams WHERE id=?", (exam_id,)); exam=cur.fetchone(); cur.execute("SELECT id, name, admission_no FROM students WHERE school_id=?", (school["id"],)); students=cur.fetchall(); cur.execute("SELECT id, name FROM subjects WHERE school_id=?", (school["id"],)); subjects=cur.fetchall(); marks_map={}; cur.execute("SELECT student_id, subject_id, score FROM marks WHERE exam_id=?", (exam_id,))
    for r in cur.fetchall(): marks_map[(r["student_id"], r["subject_id"])]=r["score"]
    con.close()
    th="".join([f"<th style='padding:6px;border:1px solid #e2e8f0'>{sub['name'][:5]}</th>" for sub in subjects])
    rows=""
    for st in students:
        scores=[]; total=0
        for sub in subjects:
            sc=marks_map.get((st["id"], sub["id"]), "-")
            scores.append(f"<td style='padding:6px;border:1px solid #eee;text-align:center'>{sc}</td>")
            if isinstance(sc,int): total+=sc
        rows+=f"<tr><td style='padding:6px;border:1px solid #eee'>{st['name']}</td><td style='padding:6px;border:1px solid #eee'>{st['admission_no']}</td>{''.join(scores)}<td style='padding:6px;border:1px solid #eee;font-weight:700'>{total}</td></tr>"
    html=school_header(school, request.session.get("name",""), "marksheets", request.session.get("role","")) + f"<div style='padding:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px'><b>{exam['name']}</b><button onclick='window.print()' style='float:right;background:#0f172a;color:white;padding:6px 12px;border:none;border-radius:6px'>Print</button><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:6px;border:1px solid #e2e8f0'>Student</th><th style='padding:6px;border:1px solid #e2e8f0'>Adm</th>{th}<th style='padding:6px;border:1px solid #e2e8f0'>Total</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial'>{html}</body></html>")

@app.get("/school/fees", response_class=HTMLResponse)
def school_fees(request: Request):
    if not has_perm(request.session.get("role",""), "fees"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT f.*, s.name as sname FROM fees f JOIN students s ON f.student_id=s.id WHERE f.school_id=?", (school["id"],)); fees=cur.fetchall(); cur.execute("SELECT id, name FROM students WHERE school_id=?", (school["id"],)); students=cur.fetchall(); con.close()
    st_opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in students])
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{f['sname']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{f['term']}</td><td style='padding:8px;border-bottom:1px solid #eee'>KES {f['total']}</td><td>KES {f['balance']}</td></tr>" for f in fees]) or "<tr><td colspan=4 style='padding:20px;text-align:center'>No fees</td></tr>"
    table=f"<b>💰 Fees</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px;text-align:left'>Student</th><th>Term</th><th>Total</th><th>Balance</th></tr>{rows}</table>"
    form=f"<form method='post' action='/school/fees/add' style='display:flex;flex-direction:column;gap:8px;margin-top:10px'><select name='student_id' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Student *</option>{st_opts}</select><select name='term' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='total' type='number' placeholder='Total *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='paid' type='number' placeholder='Paid *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><button style='background:#0f172a;color:white;padding:10px;border:none;border-radius:8px'>Save</button></form>"
    return list_page(request, "Record Fees", "fees", table, form)

@app.post("/school/fees/add")
def add_fees(request: Request, student_id: int = Form(...), term: str = Form(...), total: int = Form(...), paid: int = Form(...)):
    school=get_school_obj(request); bal=total-paid; con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO fees (school_id, student_id, term, total, paid, balance) VALUES (?,?,?,?,?,?)", (school["id"], student_id, term, total, paid, bal)); con.commit(); con.close(); return RedirectResponse("/school/fees", status_code=303)

@app.get("/school/sms", response_class=HTMLResponse)
def school_sms(request: Request):
    if not has_perm(request.session.get("role",""), "sms"): return RedirectResponse("/school/dashboard")
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM sms_logs WHERE school_id=? ORDER BY id DESC LIMIT 20", (school["id"],)); logs=cur.fetchall(); cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc=cur.fetchone()["c"]; con.close()
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{s['recipient']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{s['message'][:50]}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:10px'>{s['timestamp']}</td></tr>" for s in logs]) or "<tr><td colspan=3 style='padding:20px;text-align:center'>No SMS</td></tr>"
    table=f"<b>💬 SMS ({sc} parents)</b><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc'><th>To</th><th>Message</th><th>Time</th></tr>{rows}</table>"
    form=f"<form method='post' action='/school/sms/send' style='display:flex;flex-direction:column;gap:8px;margin-top:10px'><textarea name='message' placeholder='Message' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px;height:80px'></textarea><button style='background:#16a34a;color:white;padding:10px;border:none;border-radius:8px'>Send to All Parents ({sc})</button></form>"
    return list_page(request, "Send SMS", "sms", table, form)

@app.post("/school/sms/send")
def send_sms(request: Request, message: str = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT parent_phone FROM students WHERE school_id=?", (school["id"],)); parents=cur.fetchall(); ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    for p in parents: cur.execute("INSERT INTO sms_logs (school_id, recipient, message, timestamp) VALUES (?,?,?,?)", (school["id"], p["parent_phone"], message, ts))
    con.commit(); con.close(); return RedirectResponse("/school/sms", status_code=303)

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = "", success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = ""):
    if request.session.get("role")!="super_admin": return RedirectResponse("/school/dashboard")
    name=request.session.get("name",""); email=request.session.get("email",""); initials="".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools=cur.fetchall(); cur.execute("SELECT * FROM users WHERE role='school_admin'"); users=cur.fetchall(); con.close()
    users_by={u["school_id"]: u for u in users}
    banner=f"<div style='background:#dcfce7;border:1px solid #16a34a;padding:12px;border-radius:8px;margin-bottom:10px'><b>✅ {school_name} added!</b><div>Username: {school_email}</div><div>Password: <b>{new_pass}</b></div></div>" if success=="added" else f"<div style='background:#fef3c7;padding:10px;border-radius:8px;margin-bottom:10px'>📧 Code sent!</div>" if success=="code_sent" else ""
    rows_html=""
    for s in schools:
        u=users_by.get(s["id"]); upass=u["password"] if u else "-"; uemail=u["email"] if u else s["email"]
        rows_html+=f"<tr><td style='padding:8px;border-bottom:1px solid #eee'><b>🏫 {s['name']}</b><div style='font-size:10px'>🔑 {s['code']}</div></td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{s['email']}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{s['location']}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{uemail}</td><td style='padding:8px;border-bottom:1px solid #eee;font-size:11px'>{upass}</td><td style='padding:8px;border-bottom:1px solid #eee'><a href='/schools/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>"
    if not rows_html: rows_html="<tr><td colspan=6 style='padding:20px;text-align:center'>No schools</td></tr>"
    verify_html=""
    if pending_id:
        con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending=cur.fetchone(); con.close()
        if pending:
            verify_html=f"<div style='background:#fffbeb;border:1px solid #f59e0b;border-radius:10px;padding:14px;margin-bottom:10px'><b>🔐 Code for {pending['name']}: {pending['auth_code']}</b><form method='post' action='/verify-school-code' style='display:flex;gap:6px;margin-top:8px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='Enter code' required style='flex:1;padding:8px;border:1px solid #e2e8f0;border-radius:6px'><button style='background:#0f172a;color:white;padding:8px 12px;border:none;border-radius:6px'>Verify</button></form></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{header_html(initials,name,email)}<div style='padding:16px;display:grid;grid-template-columns:1fr 360px;gap:14px'><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;overflow-x:auto'>{banner}{verify_html}<b>📚 Schools ({len(schools)})</b><table style='width:100%;margin-top:10px;border-collapse:collapse;min-width:700px'><tr style='background:#f8fafc;font-size:11px'><th style='padding:8px;text-align:left'>School</th><th>Contact</th><th>Location</th><th>Username</th><th>Password</th><th>Action</th></tr>{rows_html}</table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;position:sticky;top:16px'><b>➕ Register New School</b><form method='post' action='/register-school' style='display:flex;flex-direction:column;gap:8px;margin-top:10px'><input name='school_name' placeholder='School Name *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='school_email' placeholder='Admin Email *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='location' placeholder='Location *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='phone' placeholder='Phone *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><input name='principal' placeholder='Principal *' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><select name='school_type' required style='padding:10px;border:1px solid #e2e8f0;border-radius:8px'><option value=''>Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button style='background:#0f172a;color:white;padding:10px;border:none;border-radius:8px'>Send Code & Create</button></form></div></div></body></html>")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code=str(random.randint(100000,999999)); con=get_db(); cur=con.cursor(); ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pid=cur.lastrowid; con.commit(); con.close(); send_email(SUPER_ADMIN, f"Code: {auth_code} - {school_name}", f"CODE: {auth_code}"); return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pid}", status_code=303)

@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending=cur.fetchone()
    if not pending: con.close(); return HTMLResponse("Invalid <a href='/schools/manage'>Back</a>")
    if pending["auth_code"]!=auth_code.strip(): con.close(); return HTMLResponse(f"Wrong code <a href='/schools/manage?pending_id={pending_id}'>Try again</a>")
    code=str(random.randint(10000,99999)); upass=gen_school_pass(pending["name"])
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid=cur.lastrowid; cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], upass, "school_admin", pending["principal"], sid))
    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,)); con.commit(); con.close()
    return RedirectResponse(f"/schools/manage?success=added&new_pass={upass}&school_email={pending['email']}&school_name={pending['name']}", status_code=303)

@app.get("/schools/delete/{school_id}")
def delete_school(school_id: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM schools WHERE id=?", (school_id,)); cur.execute("DELETE FROM users WHERE school_id=?", (school_id,)); con.commit(); con.close(); return RedirectResponse("/schools/manage", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/", status_code=303)

@app.get("/school/ranking", response_class=HTMLResponse)
def school_ranking(request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT id FROM exams WHERE school_id=? LIMIT 1", (school["id"],)); e=cur.fetchone(); rows=""
    if e:
        cur.execute("SELECT s.name, SUM(m.score) total FROM students s JOIN marks m ON s.id=m.student_id WHERE m.exam_id=? GROUP BY s.id ORDER BY total DESC", (e["id"],))
        for idx,r in enumerate(cur.fetchall(),1): rows+=f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{idx}</td><td style='padding:8px;border-bottom:1px solid #eee'>{r['name']}</td><td style='padding:8px;border-bottom:1px solid #eee;font-weight:700'>{r['total']}</td></tr>"
    con.close()
    if not rows: rows="<tr><td colspan=3 style='padding:20px;text-align:center'>No marks</td></tr>"
    html=school_header(school, request.session.get("name",""), "ranking", request.session.get("role","")) + f"<div style='padding:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px'><table style='width:100%'><tr style='background:#f8fafc'><th>Rank</th><th>Student</th><th>Total</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{html}</body></html>")

@app.get("/school/analysis", response_class=HTMLResponse)
def school_analysis(request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT AVG(score) avg FROM marks WHERE school_id=?", (school["id"],)); avg=cur.fetchone()["avg"] or 0; con.close()
    html=school_header(school, request.session.get("name",""), "analysis", request.session.get("role","")) + f"<div style='padding:16px'><b>📈 Analysis - Avg {int(avg)}%</b></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{html}</body></html>")

@app.get("/school/reports", response_class=HTMLResponse)
def school_reports(request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT id, name FROM students WHERE school_id=?", (school["id"],)); students=cur.fetchall(); con.close()
    cards="".join([f"<div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:12px'><b>{s['name']}</b><a href='/school/report/{s['id']}' style='display:block;margin-top:8px;background:#0f172a;color:white;padding:6px;border-radius:6px;text-align:center;text-decoration:none'>Report</a></div>" for s in students]) or "No students"
    html=school_header(school, request.session.get("name",""), "reports", request.session.get("role","")) + f"<div style='padding:16px'><h3>Reports</h3><div style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{html}</body></html>")

@app.get("/school/report/{sid}", response_class=HTMLResponse)
def report(sid: int, request: Request):
    school=get_school_obj(request); con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM students WHERE id=?", (sid,)); st=cur.fetchone(); cur.execute("SELECT sub.name, m.score FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.student_id=?", (sid,)); marks=cur.fetchall(); total=sum([m["score"] for m in marks]); con.close()
    rows="".join([f"<tr><td style='padding:6px;border:1px solid #eee'>{m['name']}</td><td style='padding:6px;border:1px solid #eee;text-align:center'>{m['score']}</td></tr>" for m in marks])
    html=school_header(school, request.session.get("name",""), "reports", request.session.get("role","")) + f"<div style='padding:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:16px'><h2>{school['name']} Report</h2><div>{st['name']} | Total {total}</div><table style='width:100%;margin-top:10px;border-collapse:collapse'><tr style='background:#f8fafc'><th>Subject</th><th>Score</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial'>{html}</body></html>")
