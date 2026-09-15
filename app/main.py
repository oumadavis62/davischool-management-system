from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3, random
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-final-fixed-v1")
SUPER_ADMIN = "oumadavis62@gmail.com"
PERIODS = ["8:00-8:40","8:40-9:20","9:20-10:00","10:30-11:10","11:10-11:50","11:50-12:30","14:00-14:40","14:40-15:20"]
DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
ROLES = {
    "school_admin": ["dashboard","students","classes","subjects","exams","marks","marksheets","ranking","analysis","reports","timetable","fees","sms","staff","profile"],
    "deputy_principal": ["dashboard","students","classes","subjects","exams","marks","marksheets","ranking","analysis","reports","timetable","fees","sms","profile"],
    "dos": ["dashboard","students","exams","marks","marksheets","ranking","analysis","reports","timetable","profile"],
    "hod": ["dashboard","students","marks","marksheets","analysis","reports","timetable","profile"],
    "teacher": ["dashboard","students","marks","marksheets","timetable","profile"],
    "bursar": ["dashboard","students","fees","profile"],
    "class_teacher": ["dashboard","students","marks","marksheets","timetable","profile"],
}
def has_perm(role, page):
    if role == "super_admin": return True
    return page in ROLES.get(role, [])
def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con
def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, class_name TEXT, stream TEXT, class_teacher_id INTEGER, class_teacher_name TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, name TEXT, class_id INTEGER, parent_phone TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, exam_id INTEGER, student_id INTEGER, subject_id INTEGER, score INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS timetable (id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER, day TEXT, period TEXT, subject TEXT, teacher TEXT, teacher_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit(); con.close()
init_db()
def get_school(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin": return None
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s=cur.fetchone(); con.close(); return s
def school_header(school, name, active, role):
    def nav(link, icon, label):
        if not has_perm(role, link): return ""
        style="background:#0f172a;color:white" if active==link else "color:#475569"
        return f"<a href='/school/{link}' style='display:flex;gap:8px;padding:9px 11px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:3px;{style}'>{icon} {label}</a>"
    staff=""
    if role=="school_admin":
        st="background:#0f172a;color:white" if active=="staff" else "color:#7c3aed"
        staff=f"<a href='/school/staff' style='display:flex;gap:8px;padding:9px 11px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:3px;{st}'>👥 Staff</a>"
    return f"<div style='display:flex;min-height:100vh'><div style='width:230px;background:white;border-right:1px solid #e2e8f0;padding:12px'><div style='padding:8px;border-bottom:1px solid #f1f5f9;margin-bottom:8px'><b>{school['name'][:18]}</b><div style='font-size:10px;color:#64748b'>{role}</div></div>{nav('dashboard','📊','Dashboard')}{nav('students','🎓','Students')}{nav('classes','🏫','Classes')}{nav('subjects','📚','Subjects')}{nav('exams','📝','Exams')}{nav('marks','✍️','Marks')}{nav('timetable','🗓️','Timetable ASC')}{nav('fees','💰','Fees')}{nav('sms','💬','SMS')}{staff}<a href='/logout' style='display:flex;gap:8px;padding:9px 11px;border-radius:8px;text-decoration:none;font-size:13px;color:#dc2626;margin-top:10px'>🚪 Logout</a></div><div style='flex:1;background:#f8fafc'><div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 14px;display:flex;justify-content:space-between'><b>DaviSchool - {role}</b><span style='font-size:11px;background:#ede9fe;color:#5b21b6;padding:4px 8px;border-radius:12px'>{name}</span></div>"

@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.get("/", response_class=HTMLResponse)
def home():
    return "<html><body style='font-family:Arial;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f8fafc'><div style='background:white;padding:28px;border-radius:12px;border:1px solid #e2e8f0;width:340px'><h2 style='text-align:center'>Davischool</h2><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%;padding:10px;margin:5px 0;border:1px solid #e2e8f0;border-radius:8px'><input name='password' type='password' placeholder='Password' required style='width:100%;padding:10px;margin:5px 0 14px;border:1px solid #e2e8f0;border-radius:8px'><button style='width:100%;background:#0f172a;color:white;padding:10px;border:none;border-radius:8px'>Sign In</button></form></div></body></html>"
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
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{s['name']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{s['location']}</td></tr>" for s in recent]) or "<tr><td colspan=2 style='padding:12px;text-align:center'>No schools</td></tr>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'><div style='background:white;padding:10px 16px;border-bottom:1px solid #e2e8f0'><b>🏫 Super Admin - {total} Schools</b></div><div style='padding:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:10px;padding:12px'><table style='width:100%;border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px;text-align:left'>Name</th><th>Location</th></tr>{rows}</table></div><div style='margin-top:12px'><a href='/schools/manage' style='background:#0f172a;color:white;padding:8px 14px;border-radius:8px;text-decoration:none'>Manage Schools</a></div></div></body></html>")

@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    school=get_school(request)
    if not school: return RedirectResponse("/dashboard")
    name=request.session.get("name",""); role=request.session.get("role","")
    con=get_db(); cur=con.cursor(); cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc=cur.fetchone()["c"]; con.close()
    html=school_header(school,name,"dashboard",role)
    html+=f"<div style='padding:14px'><h3>Dashboard - {role}</h3><div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:12px'>Students: {sc} | ASC Timetable Ready</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial'>{html}</body></html>")

@app.get("/school/timetable", response_class=HTMLResponse)
def timetable_page(request: Request, class_id: str = "", teacher_id: str = "", view: str = "class", error: str = ""):
    if not has_perm(request.session.get("role",""), "timetable"): return RedirectResponse("/school/dashboard")
    school=get_school(request); con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes=cur.fetchall()
    cur.execute("SELECT id, full_name FROM users WHERE school_id=? AND role!='school_admin' ORDER BY full_name", (school["id"],)); teachers=cur.fetchall()
    cur.execute("SELECT t.*, c.name as cname FROM timetable t LEFT JOIN classes c ON t.class_id=c.id WHERE t.school_id=?", (school["id"],)); all_tt=cur.fetchall()
    cur.execute("SELECT name FROM subjects WHERE school_id=?", (school["id"],)); subjects=cur.fetchall()
    con.close()
    if not class_id and classes: class_id=str(classes[0]["id"])
    if not teacher_id and teachers: teacher_id=str(teachers[0]["id"])
    class_opts="".join([f"<option value='{c['id']}' {'selected' if str(c['id'])==class_id else ''}>{c['name']}</option>" for c in classes])
    teacher_opts="".join([f"<option value='{t['id']}' {'selected' if str(t['id'])==teacher_id else ''}>{t['full_name']}</option>" for t in teachers])
    subject_opts="".join([f"<option value='{s['name']}'>{s['name']}</option>" for s in subjects])
    sel_teacher_name=""
    for t in teachers:
        if str(t["id"])==teacher_id: sel_teacher_name=t["full_name"]
    cmap={}
    for e in all_tt:
        if str(e["class_id"])==str(class_id): cmap[(e["day"], e["period"])]=e
    grid=""
    for p in PERIODS:
        row=""
        for d in DAYS:
            en=cmap.get((d,p))
            if en: row+=f"<td style='padding:5px;border:1px solid #e2e8f0;background:#dbeafe;text-align:center;font-size:11px'><b>{en['subject']}</b><br>{en['teacher'][:8]}<br><a href='/school/timetable/delete/{en['id']}' style='color:#dc2626;font-size:10px'>x</a></td>"
            else: row+="<td style='padding:5px;border:1px solid #f1f5f9;text-align:center;color:#cbd5e1'>-</td>"
        grid+=f"<tr><td style='padding:6px;border:1px solid #e2e8f0;background:#f8fafc;font-size:11px'>{p}</td>{row}</tr>"
    tmap={}
    for e in all_tt:
        if e["teacher"]==sel_teacher_name or str(e["teacher_id"])==teacher_id: tmap[(e["day"], e["period"])]=e
    tgrid=""
    for p in PERIODS:
        row=""
        for d in DAYS:
            en=tmap.get((d,p))
            if en: row+=f"<td style='padding:5px;border:1px solid #e2e8f0;background:#ede9fe;text-align:center;font-size:11px'><b>{en['subject']}</b><br>{en['cname'] or ''}</td>"
            else: row+="<td style='padding:5px;border:1px solid #f1f5f9;text-align:center;color:#cbd5e1'>-</td>"
        tgrid+=f"<tr><td style='padding:6px;border:1px solid #e2e8f0;background:#f8fafc;font-size:11px'>{p}</td>{row}</tr>"
    err=f"<div style='background:#fef2f2;border:1px solid #fecaca;color:#dc2626;padding:8px;border-radius:6px;margin-bottom:10px'>{error}</div>" if error else ""
    header_days="".join([f"<th style='padding:6px;border:1px solid #1e293b;font-size:11px'>{d}</th>" for d in DAYS])
    if view=="teacher":
        main=f"<div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:10px;overflow-x:auto'><div style='display:flex;justify-content:space-between;margin-bottom:8px'><b>Teacher: {sel_teacher_name}</b><form method='get'><input type='hidden' name='view' value='teacher'><select name='teacher_id' onchange='this.form.submit()' style='padding:5px;border:1px solid #e2e8f0;border-radius:6px'>{teacher_opts}</select></form></div><table style='width:100%;border-collapse:collapse;min-width:600px'><tr style='background:#5b21b6;color:white'><th style='padding:6px;border:1px solid #4c1d95;font-size:11px'>Period</th>{header_days}</tr>{tgrid}</table></div>"
    else:
        main=f"<div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:10px;overflow-x:auto'><div style='display:flex;justify-content:space-between;margin-bottom:8px'><b>Class WallMaster ASC</b><div style='display:flex;gap:6px'><form method='get'><input type='hidden' name='view' value='class'><select name='class_id' onchange='this.form.submit()' style='padding:5px;border:1px solid #e2e8f0;border-radius:6px'>{class_opts}</select></form><a href='/school/timetable/print?class_id={class_id}' target='_blank' style='background:#0f172a;color:white;padding:5px 10px;border-radius:6px;text-decoration:none;font-size:11px'>Print</a></div></div><table style='width:100%;border-collapse:collapse;min-width:600px'><tr style='background:#0f172a;color:white'><th style='padding:6px;border:1px solid #1e293b;font-size:11px'>Period</th>{header_days}</tr>{grid}</table></div>"
    html=school_header(school, request.session.get("name",""), "timetable", request.session.get("role",""))
    html+=f"<div style='padding:12px'>{err}<div style='display:flex;gap:6px;margin-bottom:10px'><a href='/school/timetable?view=class&class_id={class_id}' style='padding:6px 10px;border-radius:6px;text-decoration:none;font-size:12px;background:#0f172a;color:white'>Class WallMaster</a><a href='/school/timetable?view=teacher&teacher_id={teacher_id}' style='padding:6px 10px;border-radius:6px;text-decoration:none;font-size:12px;background:white;border:1px solid #e2e8f0'>Teacher View</a></div><div style='display:grid;grid-template-columns:1fr 320px;gap:12px'><div>{main}</div><div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:10px;position:sticky;top:10px'><b>Add Lesson - ASC Checker</b><form method='post' action='/school/timetable/add' style='display:flex;flex-direction:column;gap:8px;margin-top:8px'><select name='class_id' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><option value=''>Class *</option>{class_opts}</select><select name='day' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><option value=''>Day *</option><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option></select><select name='period' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><option value=''>Period *</option>{''.join([f'<option>{p}</option>' for p in PERIODS])}</select><select name='subject' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><option value=''>Subject *</option>{subject_opts}</select><select name='teacher_id' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><option value=''>Teacher *</option>{teacher_opts}</select><button style='background:#0f172a;color:white;padding:9px;border:none;border-radius:6px'>Add - Check Conflict</button></form></div></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{html}</body></html>")

@app.post("/school/timetable/add")
def add_tt(request: Request, class_id: int = Form(...), day: str = Form(...), period: str = Form(...), subject: str = Form(...), teacher_id: int = Form(...)):
    school=get_school(request); con=get_db(); cur=con.cursor()
    cur.execute("SELECT full_name FROM users WHERE id=?", (teacher_id,)); t=cur.fetchone(); tname=t["full_name"] if t else f"Teacher {teacher_id}"
    cur.execute("SELECT * FROM timetable WHERE school_id=? AND class_id=? AND day=? AND period=?", (school["id"], class_id, day, period))
    if cur.fetchone(): con.close(); return RedirectResponse(f"/school/timetable?error=Class busy at {day} {period}&view=class&class_id={class_id}", status_code=303)
    cur.execute("SELECT * FROM timetable WHERE school_id=? AND day=? AND period=? AND (teacher_id=? OR teacher=?)", (school["id"], day, period, teacher_id, tname))
    if cur.fetchone(): con.close(); return RedirectResponse(f"/school/timetable?error=Teacher {tname} busy at {day} {period}&view=teacher&teacher_id={teacher_id}", status_code=303)
    cur.execute("INSERT INTO timetable (school_id, class_id, day, period, subject, teacher, teacher_id) VALUES (?,?,?,?,?,?,?)", (school["id"], class_id, day, period, subject, tname, teacher_id)); con.commit(); con.close()
    return RedirectResponse(f"/school/timetable?view=class&class_id={class_id}", status_code=303)

@app.get("/school/timetable/delete/{tid}")
def del_tt(tid: int, request: Request):
    school=get_school(request); con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM timetable WHERE id=? AND school_id=?", (tid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/timetable/print")
def print_tt(request: Request, class_id: str = ""):
    school=get_school(request); con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM classes WHERE id=?", (class_id,)); cls=cur.fetchone()
    if not cls: cur.execute("SELECT * FROM classes WHERE school_id=? LIMIT 1", (school["id"],)); cls=cur.fetchone()
    if not cls: con.close(); return HTMLResponse("No class")
    cur.execute("SELECT * FROM timetable WHERE class_id=?", (cls["id"],)); entries=cur.fetchall(); con.close()
    mp={(e["day"], e["period"]): e for e in entries}
    rows=""
    for p in PERIODS:
        cells=""
        for d in DAYS:
            e=mp.get((d,p))
            cells+=f"<td style='padding:8px;border:2px solid #000;text-align:center'><b>{e['subject'] if e else '-'}</b><br>{e['teacher'] if e else ''}</td>" if e else "<td style='padding:8px;border:2px solid #000;text-align:center'>-</td>"
        rows+=f"<tr><td style='padding:8px;border:2px solid #000;background:#f1f5f9'>{p}</td>{cells}</tr>"
    header="".join([f"<th style='padding:8px;border:2px solid #000'>{d}</th>" for d in DAYS])
    return HTMLResponse(f"<html><body style='font-family:Arial;padding:16px'><h2 style='text-align:center'>{school['name']} - {cls['name']} WallMaster</h2><table style='width:100%;border-collapse:collapse;border:3px solid #000'><tr style='background:#000;color:white'><th style='padding:8px;border:2px solid #000'>Period</th>{header}</tr>{rows}</table><div style='text-align:right;margin-top:12px'><button onclick='window.print()' style='background:#000;color:white;padding:8px 16px;border:none;border-radius:6px'>Print</button></div></body></html>")

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, pending_id: str = "", success: str = "", new_pass: str = "", school_email: str = "", school_name: str = ""):
    if request.session.get("role")!="super_admin": return RedirectResponse("/school/dashboard")
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools=cur.fetchall(); cur.execute("SELECT * FROM users WHERE role='school_admin'"); users=cur.fetchall(); con.close()
    users_by={u["school_id"]: u for u in users}
    banner=f"<div style='background:#dcfce7;padding:10px;border-radius:8px;margin-bottom:10px'><b>{school_name} added!</b> User: {school_email} Pass: <b>{new_pass}</b></div>" if success=="added" else "<div style='background:#fef3c7;padding:10px;border-radius:8px;margin-bottom:10px'>Code sent</div>" if success=="code_sent" else ""
    rows="".join([f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{s['name']}<div style='font-size:10px'>{s['code']}</div></td><td style='padding:8px;border-bottom:1px solid #eee'>{s['email']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{s['location']}</td><td style='padding:8px;border-bottom:1px solid #eee'>{(users_by.get(s['id']) or {}).get('email','-') if isinstance(users_by.get(s['id']), dict) else (users_by.get(s['id'])['email'] if users_by.get(s['id']) else s['email'])}</td><td style='padding:8px;border-bottom:1px solid #eee'><a href='/schools/delete/{s['id']}' style='color:#dc2626'>Delete</a></td></tr>" for s in schools]) or "<tr><td colspan=5 style='padding:16px;text-align:center'>No schools</td></tr>"
    verify=""
    if pending_id:
        con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending=cur.fetchone(); con.close()
        if pending: verify=f"<div style='background:#fffbeb;border:1px solid #f59e0b;padding:10px;border-radius:8px;margin-bottom:10px'><b>Code for {pending['name']}: {pending['auth_code']}</b><form method='post' action='/verify-school-code' style='display:flex;gap:6px;margin-top:6px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='Enter code' required style='flex:1;padding:6px;border:1px solid #e2e8f0;border-radius:6px'><button style='background:#0f172a;color:white;padding:6px 10px;border:none;border-radius:6px'>Verify</button></form></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'><div style='background:white;padding:10px 16px;border-bottom:1px solid #e2e8f0'><b>🏫 Manage Schools</b> <a href='/dashboard' style='margin-left:12px'>Dashboard</a></div><div style='padding:12px;display:grid;grid-template-columns:1fr 320px;gap:12px'><div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:10px;overflow-x:auto'>{banner}{verify}<table style='width:100%;border-collapse:collapse'><tr style='background:#f8fafc;font-size:11px'><th style='padding:8px;text-align:left'>School</th><th>Contact</th><th>Location</th><th>Username</th><th>Action</th></tr>{rows}</table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:12px'><b>Register School</b><form method='post' action='/register-school' style='display:flex;flex-direction:column;gap:6px;margin-top:8px'><input name='school_name' placeholder='School Name *' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><input name='school_email' placeholder='Admin Email *' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><input name='location' placeholder='Location *' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><input name='phone' placeholder='Phone *' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><input name='principal' placeholder='Principal *' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><select name='school_type' required style='padding:8px;border:1px solid #e2e8f0;border-radius:6px'><option value=''>Type *</option><option>Primary</option><option>Secondary</option></select><button style='background:#0f172a;color:white;padding:8px;border:none;border-radius:6px'>Send Code & Create</button></form></div></div></body></html>")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code=str(random.randint(100000,999999)); con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code) VALUES (?,?,?,?,?,?,?)", (school_name.upper(), school_email, location, phone, principal, school_type, auth_code)); pid=cur.lastrowid; con.commit(); con.close(); return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pid}", status_code=303)

@app.post("/verify-school-code")
def verify_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending=cur.fetchone()
    if not pending or pending["auth_code"]!=auth_code.strip(): con.close(); return HTMLResponse(f"Wrong code <a href='/schools/manage?pending_id={pending_id}'>Try again</a>")
    code=str(random.randint(10000,99999)); upass=f"{pending['name'][:4].upper()}@{random.randint(1000,9999)}!"
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"])); sid=cur.lastrowid
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], upass, "school_admin", pending["principal"], sid)); cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,)); con.commit(); con.close()
    return RedirectResponse(f"/schools/manage?success=added&new_pass={upass}&school_email={pending['email']}&school_name={pending['name']}", status_code=303)

@app.get("/schools/delete/{school_id}")
def delete_school(school_id: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM schools WHERE id=?", (school_id,)); cur.execute("DELETE FROM users WHERE school_id=?", (school_id,)); con.commit(); con.close(); return RedirectResponse("/schools/manage", status_code=303)

@app.get("/school/{page}", response_class=HTMLResponse)
def generic(page: str, request: Request):
    school=get_school(request)
    if not school: return RedirectResponse("/dashboard")
    html=school_header(school, request.session.get("name",""), page, request.session.get("role",""))
    html+=f"<div style='padding:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:20px;text-align:center'><h3>{page.title()} - Working</h3><p>Go to Timetable ASC - now fixed and deploys</p><a href='/school/timetable' style='background:#0f172a;color:white;padding:8px 14px;border-radius:6px;text-decoration:none'>Open ASC Timetable</a></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0;font-family:Arial;background:#f8fafc'>{html}</body></html>")

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/", status_code=303)
