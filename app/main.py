from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davi-2026")
SUPER_ADMIN_EMAIL = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, approved INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, school_id INTEGER, role TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, name TEXT, class TEXT, gender TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY, school_id INTEGER, date TEXT, class TEXT, present INTEGER, total INTEGER)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit()
    con.close()
init_db()

def wrap(school_name, body, email, role, active="overview"):
    ov = "background:#0f172a; color:white" if active=="overview" else ""
    ac = "background:#0f172a; color:white" if active=="academics" else ""
    at = "background:#0f172a; color:white" if active=="attendance" else ""
    return f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0; font-family:Arial; background:#fcfcfc; display:flex}}.sidebar{{width:260px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}}.main{{margin-left:260px; flex:1}}.topbar{{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; position:sticky; top:0}}.content{{padding:20px}}.nav-item{{display:block; padding:10px 12px; margin:2px 10px; border-radius:8px; color:#334155; text-decoration:none}}.card{{background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:16px}}.grid4{{display:grid; grid-template-columns:repeat(4,1fr); gap:12px}}</style></head><body><div class='sidebar'><div style='padding:16px; border-bottom:1px solid #e2e8f0'><b>DaviSchool</b><br><small>SCHOOL MANAGEMENT</small></div><a class='nav-item' href='/dashboard' style='{ov}'>System Overview</a><a class='nav-item' href='/academics' style='{ac}'>Academic Analytics</a><a class='nav-item' href='/attendance' style='{at}'>Attendance Analytics</a><a class='nav-item' href='/students'>Students Manager</a><a class='nav-item'>Financial Analytics</a><div style='padding:14px; margin-top:30px; border-top:1px solid #e2e8f0'>Davis Ouma<br><small>{email}</small><br><small>{role}</small></div></div><div class='main'><div class='topbar'><div><b>{school_name.upper()}</b> (DS-2026)</div><div>Davis Ouma - {role} - {email} | <a href='/logout'>Logout</a></div></div>{body}</div></body></html>"

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:400px'><h1>Welcome Back</h1><p>Sign in to DaviSchool</p><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%; padding:12px; margin:8px 0'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:8px 0'><button style='width:100%; background:#2563eb; color:white; padding:12px; border:none; border-radius:8px'>Sign In</button></form><p><a href='/register'>Register your School</a></p></div></body></html>")

@app.get("/register", response_class=HTMLResponse)
def reg_page():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:400px; background:white; padding:24px; border-radius:12px'><h2>Register School</h2><form method='post' action='/register'><input name='school_name' placeholder='School Name' required style='width:100%; padding:10px; margin:6px 0'><input name='email' placeholder='Admin Email' required style='width:100%; padding:10px; margin:6px 0'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:10px; margin:6px 0'><button style='width:100%; background:#2563eb; color:white; padding:10px; border:none; border-radius:8px'>Register</button></form></div></body></html>")

@app.post("/register")
def do_register(school_name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO schools (name, email, approved) VALUES (?,?,0)", (school_name, email))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email, password, school_id, role) VALUES (?,?,?,?)", (email, password, sid, "admin"))
    con.commit(); con.close()
    return RedirectResponse("/", status_code=303)

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    u = cur.fetchone()
    con.close()
    if not u:
        return HTMLResponse("Invalid login <a href='/'>Back</a>")
    request.session["user_email"] = email
    request.session["school_id"] = u["school_id"] if u["school_id"] else 0
    request.session["school_name"] = "DaviSchool"
    request.session["role"] = u["role"]
    if u["role"] == "super_admin":
        request.session["school_name"] = "DaviSchool Super Admin"
        return RedirectResponse("/super-admin", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=?", (request.session.get("school_id",0),))
    sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND gender='Boy'", (request.session.get("school_id",0),))
    boys = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND gender='Girl'", (request.session.get("school_id",0),))
    girls = cur.fetchone()["c"]
    con.close()
    body = f"""
    <div class='content'>
        <h1>School Overview</h1><p>Welcome back, Davis! {sname}</p>
        <div class='grid4'><div class='card'><h4>Total Students</h4><h2>{sc}</h2></div><div class='card'><h4>Boys</h4><h2>{boys}</h2></div><div class='card'><h4>Girls</h4><h2>{girls}</h2></div><div class='card'><h4>Attendance Today</h4><h2>--</h2><small>Not marked yet</small></div></div>
        <div class='card'><b>Top right:</b> Davis Ouma - {role} - {email} (Shows Super Admin role)<br><b>Settings:</b> 7 cards at bottom left - User Management, Roles, School Profile, Classes, Backup, Audit, Integrations (Bulk SMS + M-Pesa)</div>
        <div class='card'><a href='/academics'>Academic Analytics (4 tabs done)</a> | <a href='/attendance'>Attendance Analytics (NEW)</a></div>
    </div>
    """
    return HTMLResponse(wrap(sname, body, email, role, "overview"))

@app.get("/academics", response_class=HTMLResponse)
def academics(request: Request, term: str = "Term 1", year: str = "2026", grade: str = "GRADE 7", tab: str = "performance"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")

    if tab == "teacher":
        cards = "<div class='card'><b>Top 10 Teachers by Value Added</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No teacher performance data available</div></div><div class='card'><b>Teacher Value-Added Details</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No teacher value-added data available</div></div>"
    elif tab == "student":
        cards = "<div class='card'><div style='display:flex; justify-content:space-between'><b>Student Trajectories</b><span style='border:1px solid #e2e8f0; padding:4px 10px; border-radius:20px; font-size:12px'>Show At-Risk Only</span></div><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No student trajectory data available</div></div><div class='card'><b>Cohort Tracking</b><br>Select students to track:<br><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px'>FLORENCE -></span><br><br>Select students above to view chart</div>"
    elif tab == "subject":
        cards = "<div class='card'><b>Subject Performance Matrix</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No subject performance data available</div></div><div class='card'><b>Gender Gap Analysis</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No gender gap data available</div></div>"
    else:
        cards = f"<div class='card'><b>Class Performance Over Time</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No exam data - Term: {term} | Year: {year} | Grade: {grade}</div></div><div class='card'><b>Yearly Progression</b><div style='height:160px; border-left:1px solid #ccc; border-bottom:1px solid #ccc'></div>{year}</div><div class='card'><b>Subject Trends Across Terms</b><div>T3 2026 - AGRICULTURE, CRE, ENGLISH, MATH etc</div></div>"

    body = f"""
    <div class='content'>
        <h1>Academic Analytics</h1>
        <div style='display:flex; gap:8px; margin:12px 0'><select><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><select><option>2026</option></select><select><option>GRADE 7</option></select></div>
        <div style='display:flex; gap:16px; border-bottom:1px solid #e2e8f0; padding-bottom:8px; margin-bottom:12px'>
            <a href='/academics?tab=performance'>Performance Trends</a>
            <a href='/academics?tab=subject'>Subject Analysis</a>
            <a href='/academics?tab=teacher' style='font-weight:bold'>Teacher Performance</a>
            <a href='/academics?tab=student'>Student Tracking</a>
        </div>
        {cards}
    </div>
    """
    return HTMLResponse(wrap(sname, body, email, role, "academics"))

@app.get("/attendance", response_class=HTMLResponse)
def attendance(request: Request, term: str = "Term 1", year: str = "2026", grade: str = "GRADE 7"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")

    body = f"""
    <div class='content'>
        <h1>Attendance Analytics</h1>
        <div style='color:#64748b; margin-bottom:16px'>Track student attendance patterns and trends</div>
        
        <div style='display:flex; gap:8px; margin-bottom:16px'>
            <select style='padding:8px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select>
            <select style='padding:8px; border:1px solid #e2e8f0; border-radius:8px'><option>2026</option><option>2025</option><option>2024</option></select>
            <select style='padding:8px; border:1px solid #e2e8f0; border-radius:8px'><option>GRADE 7</option><option>GRADE 8</option><option>GRADE 9</option></select>
        </div>

        <div class='grid4'>
            <div class='card'><h4 style='margin:0; color:#64748b'>Overall Attendance</h4><h2 style='margin:8px 0'>--</h2><small style='color:#94a3b8'>Not marked yet</small></div>
            <div class='card'><h4 style='margin:0; color:#64748b'>Present Today</h4><h2 style='margin:8px 0'>0</h2><small style='color:#22c55e'>0 students</small></div>
            <div class='card'><h4 style='margin:0; color:#64748b'>Absent Today</h4><h2 style='margin:8px 0'>0</h2><small style='color:#ef4444'>0 students</small></div>
            <div class='card'><h4 style='margin:0; color:#64748b'>Late Arrivals</h4><h2 style='margin:8px 0'>0</h2><small style='color:#f59e0b'>0 students</small></div>
        </div>

        <div class='card'>
            <b>Daily Attendance Trend</b>
            <div style='height:220px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8; border-left:1px solid #e2e8f0; border-bottom:1px solid #e2e8f0; margin-top:16px'>
                <div style='font-size:32px'>📅</div>
                <div>No attendance data available for the selected filters</div>
                <div style='font-size:12px; margin-top:4px'>Term: {term} | Year: {year} | Grade: {grade}</div>
            </div>
        </div>

        <div style='display:grid; grid-template-columns:1fr 1fr; gap:16px'>
            <div class='card'>
                <b>Class-wise Attendance</b>
                <div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8; margin-top:12px'>
                    No class attendance data
                </div>
            </div>
            <div class='card'>
                <b>Gender Attendance Comparison</b>
                <div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8; margin-top:12px'>
                    No gender data
                </div>
            </div>
        </div>

        <div class='card'>
            <b>Top Absentees</b>
            <div style='height:120px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>
                No absentee data - Attendance not marked yet
            </div>
        </div>
    </div>
    """
    return HTMLResponse(wrap(sname, body, email, role, "attendance"))

@app.get("/students", response_class=HTMLResponse)
def students_page(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    body = "<div class='content'><div class='card'><h3>Students</h3><form method='post' action='/students/add'><input name='adm' placeholder='ADM'><input name='name' placeholder='Name'><input name='class' placeholder='Class'><select name='gender'><option>Boy</option><option>Girl</option></select><button>Add Student</button></form></div></div>"
    return HTMLResponse(wrap(sname, body, email, role))

@app.post("/students/add")
def add_stu(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class"), gender: str = Form("Boy")):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, adm, name, class, gender) VALUES (?,?,?,?,?)", (request.session.get("school_id",0), adm, name, class_, gender))
    con.commit(); con.close()
    return RedirectResponse("/students", status_code=303)

@app.get("/super-admin", response_class=HTMLResponse)
def super_admin(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    return HTMLResponse(wrap("Super Admin", "<div class='content'><div class='card'><h3>Super Admin - oumadavis62@gmail.com - Role: Super Admin</h3><a href='/dashboard'>Dashboard</a> | <a href='/logout'>Logout</a></div></div>", SUPER_ADMIN_EMAIL, "Super Admin"))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
