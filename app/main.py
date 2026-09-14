from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-beautiful-2026")
SUPER_ADMIN_EMAIL = "oumadavis62@gmail.com"
DB_PATH = "davischool.db"

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, approved INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, school_id INTEGER, role TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, name TEXT, class TEXT, gender TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY, school_id INTEGER, date TEXT, present INTEGER, total INTEGER)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit()
    con.close()
init_db()

def base_html(title, body_content):
    return f"<html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{title}</title><style>body{{margin:0; font-family:Inter, Arial, sans-serif; background:#fcfcfc}} .login-center{{display:flex; justify-content:center; align-items:center; min-height:100vh; background:white}}</style></head><body>{body_content}</body></html>"

def dashboard_wrap(school_name, inner, user_email, role_display, active_tab):
    ov_active = "background:#0f172a; color:white" if active_tab=="overview" else "background:#f8fafc; color:#334155"
    ac_active = "background:#0f172a; color:white" if active_tab=="academics" else "color:#334155"
    at_active = "background:#0f172a; color:white" if active_tab=="attendance" else "color:#334155"
    
    html = """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{box-sizing:border-box} body{margin:0; font-family:Arial; background:#fcfcfc; display:flex}
.sidebar{width:270px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}
.logo{padding:18px 20px; border-bottom:1px solid #f1f5f9; display:flex; align-items:center; gap:10px}
.logo-icon{width:38px; height:38px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800}
.nav-section{padding:12px 14px} .nav-label{font-size:11px; color:#94a3b8; font-weight:600; margin:12px 8px 8px; letter-spacing:0.8px}
.nav-item{display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:8px; color:#334155; text-decoration:none; font-size:14px; margin-bottom:2px}
.nav-item.active{background:#0f172a; color:white}
.sub{margin-left:22px; border-left:1px dashed #e2e8f0; padding-left:12px}
.main{margin-left:270px; flex:1; min-height:100vh}
.topbar{background:white; border-bottom:1px solid #e2e8f0; padding:14px 22px; display:flex; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:10}
.content{padding:26px}
.card{background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px}
.grid4{display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:18px}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>D</div><div><b style='color:#0f5b9e'>DaviSchool</b><div style='font-size:9px; color:#64748b; letter-spacing:1px'>SCHOOL MANAGEMENT SYSTEM</div></div></div>
<div class='nav-section'>
<div class='nav-label'>MAIN NAVIGATION</div>
<a class='nav-item active'>Dashboard</a>
<div class='sub'>
<a class='nav-item' href='/dashboard' style='""" + ov_active + """'>System Overview</a>
<a class='nav-item' href='/academics' style='""" + ac_active + """'>Academic Analytics</a>
<a class='nav-item' href='/attendance' style='""" + at_active + """'>Attendance Analytics</a>
<a class='nav-item'>Financial Analytics</a>
</div>
<a class='nav-item' href='/students'>Students Manager</a>
<a class='nav-item'>Staff Manager</a>
</div>
<div style='padding:14px; border-top:1px solid #f1f5f9; margin-top:20px; display:flex; gap:10px; align-items:center'>
<div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700'>DO</div>
<div><div style='font-size:13px; font-weight:600'>Davis Ouma</div><div style='font-size:11px; color:#64748b'>""" + user_email + """</div><div style='font-size:10px; color:#2563eb; font-weight:600'>""" + role_display + """</div></div>
</div>
</div>
<div class='main'>
<div class='topbar'><div><b>""" + school_name.upper() + """</b> <small style='color:#64748b'>(Code: DS-2026)</small></div>
<div style='display:flex; gap:14px; align-items:center; font-size:14px'><span>🔔</span><span>❓</span><div style='display:flex; align-items:center; gap:8px'><div style='width:34px; height:34px; background:#f1f5f9; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700'>DO</div><div><div style='font-weight:600; font-size:13px'>Davis Ouma</div><div style='font-size:11px; color:#64748b'>""" + role_display + """</div></div><span>^</span></div><a href='/logout' style='color:#334155; text-decoration:none; font-size:13px; margin-left:10px'>Logout</a></div></div>
""" + inner + """
</div></body></html>
"""
    return html

@app.get("/", response_class=HTMLResponse)
def login_page():
    body = """
<div class='login-center'><div style='width:100%; max-width:440px; padding:40px 20px'><h1 style='font-size:32px; font-weight:800; margin:0'>Welcome Back</h1><p style='color:#64748b; margin:6px 0 24px'>Sign in to your DaviSchool account</p>
<form method='post' action='/login'><label style='font-size:14px; font-weight:600'>Username or Email</label><input name='email' required style='width:100%; padding:12px; border:1px solid #e2e8f0; border-radius:10px; margin:8px 0 16px'><label style='font-size:14px; font-weight:600'>Password</label><input name='password' type='password' required style='width:100%; padding:12px; border:1px solid #e2e8f0; border-radius:10px; margin:8px 0 16px'><button style='width:100%; background:#2563eb; color:white; padding:12px; border:none; border-radius:10px; font-weight:600'>Sign In</button></form>
<p style='text-align:center; margin-top:16px; font-size:14px'><a href='/register' style='color:#2563eb; text-decoration:none; font-weight:600'>Register your School</a></p>
</div></div>
"""
    return HTMLResponse(base_html("DaviSchool Login", body))

@app.get("/register", response_class=HTMLResponse)
def reg_page():
    body = "<div class='login-center'><div style='background:white; padding:30px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><h2>Register School - DaviSchool</h2><form method='post' action='/register'><input name='school_name' placeholder='School Name' required style='width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:8px'><input name='email' placeholder='Admin Email' required style='width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:8px'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:8px'><button style='width:100%; background:#2563eb; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>Register</button></form><p><a href='/'>Back to Login</a></p></div></div>"
    return HTMLResponse(base_html("Register", body))

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
    user = cur.fetchone()
    con.close()
    if not user:
        return HTMLResponse(base_html("Error", "<p>Invalid login <a href='/'>Back</a></p>"))
    request.session["user_email"] = email
    request.session["school_id"] = user["school_id"] if user["school_id"] else 0
    request.session["school_name"] = "DaviSchool Super Admin" if user["role"]=="super_admin" else "DaviSchool"
    request.session["role"] = user["role"]
    if user["role"] == "super_admin":
        return RedirectResponse("/super-admin", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name", "DaviSchool")
    con = get_db(); cur = con.cursor()
    sid = request.session.get("school_id",0)
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=?", (sid,))
    sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND gender='Boy'", (sid,))
    boys = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND gender='Girl'", (sid,))
    girls = cur.fetchone()["c"]
    con.close()
    total = boys + girls
    ratio = "0:1"
    if boys>0:
        ratio = str(round(girls/boys,2)) + ":1" if girls>0 else "0:1"

    inner = f"""
<div class='content'>
<h1 style='font-size:28px; font-weight:700; margin:0'>School Overview</h1><p style='color:#475569; margin:6px 0 18px'>Welcome back, Davis! {sname}</p>
<div class='grid4'>
<div class='card'><div style='color:#64748b; font-size:13px'>Total Students</div><h2 style='margin:8px 0; font-size:28px'>{sc}</h2><div style='font-size:12px; color:#16a34a'>+ Fresh system</div></div>
<div class='card'><div style='color:#64748b; font-size:13px'>Total Staff</div><h2 style='margin:8px 0; font-size:28px'>0</h2></div>
<div class='card'><div style='color:#64748b; font-size:13px'>Fee Collection</div><h2 style='margin:8px 0; font-size:28px'>0%</h2></div>
<div class='card'><div style='color:#64748b; font-size:13px'>Attendance</div><h2 style='margin:8px 0; font-size:28px'>--</h2><div style='font-size:12px; color:#64748b'>Not marked yet</div></div>
</div>

<div style='display:grid; grid-template-columns:1.2fr 1fr; gap:16px'>
<div class='card'>
<div style='display:flex; justify-content:space-between'><div><b>Students by Gender</b><div style='color:#64748b; font-size:12px'>Boys vs Girls</div></div></div>
<div style='display:flex; gap:10px; margin-top:18px'>
<div style='background:#eff6ff; border-radius:12px; padding:12px; flex:1; text-align:center'><div style='font-size:12px; color:#64748b'>Total Boys</div><b style='font-size:20px'>{boys}</b></div>
<div style='background:#fdf2f8; border-radius:12px; padding:12px; flex:1; text-align:center'><div style='font-size:12px; color:#64748b'>Total Girls</div><b style='font-size:20px'>{girls}</b></div>
<div style='background:#f8fafc; border-radius:12px; padding:12px; flex:1; text-align:center'><div style='font-size:12px; color:#64748b'>Total Students</div><b style='font-size:20px'>{total}</b></div>
<div style='background:#f8fafc; border-radius:12px; padding:12px; flex:1; text-align:center'><div style='font-size:12px; color:#64748b'>Ratio</div><b style='font-size:14px'>{ratio}</b></div>
</div>
</div>
<div class='card'>
<b>Cumulative Balances by Class</b><div style='color:#64748b; font-size:12px; margin-top:4px'>Total: KES 0</div>
<div style='margin-top:14px; font-size:14px'>
<div style='display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid #f1f5f9'><span>GRADE 7</span><span>{sc} students - KES 0</span></div>
<div style='display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid #f1f5f9'><span>GRADE 8</span><span>0 students - KES 0</span></div>
<div style='display:flex; justify-content:space-between; padding:8px 0'><span>GRADE 9</span><span>0 students - KES 0</span></div>
</div>
</div>
</div>

<div style='display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:16px'>
<div class='card'><b>Recent Activity</b><div style='margin-top:10px; color:#64748b; font-size:13px'>Viewed: dashboard - Davis Ouma</div></div>
<div class='card'><b>Top Fee Defaulters</b><div style='margin-top:10px; color:#64748b; font-size:13px'>No defaulters - Fresh</div></div>
<div class='card'><b>Recent Payments</b><div style='margin-top:10px; color:#64748b; font-size:13px'>No payments yet</div></div>
</div>
</div>
"""
    return HTMLResponse(dashboard_wrap(sname, inner, email, role, "overview"))

@app.get("/academics", response_class=HTMLResponse)
def academics(request: Request, tab: str = "performance"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    
    perf_style = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:600" if tab=="performance" else "color:#64748b"
    subj_style = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:600" if tab=="subject" else "color:#64748b"
    teach_style = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:600" if tab=="teacher" else "color:#64748b"
    stud_style = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:600" if tab=="student" else "color:#64748b"
    
    if tab=="teacher":
        cards = "<div class='card'><b>Top 10 Teachers by Value Added</b><div style='height:220px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No teacher performance data available</div><div style='font-size:12px; margin-top:4px'>Term: Term 1 | Year: 2026 | Grade: GRADE 7</div></div></div><div class='card'><b>Teacher Value-Added Details</b><div style='height:220px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No teacher value-added data available</div></div></div>"
    elif tab=="student":
        cards = "<div class='card'><div style='display:flex; justify-content:space-between'><b>Student Trajectories</b><span style='border:1px solid #e2e8f0; padding:6px 12px; border-radius:20px; font-size:12px'>Show At-Risk Only</span></div><div style='height:220px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No student trajectory data available</div></div><div class='card'><b>Cohort Tracking</b><div style='color:#64748b; font-size:13px'>Select students to track their progression:</div><div style='margin-top:10px'><span style='background:#f1f5f9; border:1px solid #e2e8f0; padding:6px 12px; border-radius:20px; font-size:12px'>FLORENCE -></span></div><div style='height:180px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>Select students above to view their progression chart</div></div>"
    elif tab=="subject":
        cards = "<div class='card'><b>Subject Performance Matrix</b><div style='height:220px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No subject performance data available</div><div style='font-size:12px'>Term: Term 1 | Year: 2026 | Grade: GRADE 7</div></div></div><div class='card'><b>Gender Gap Analysis</b><div style='height:220px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No gender gap data available</div></div>"
    else:
        cards = "<div class='card'><b>Class Performance Over Time</b><div style='height:220px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No exam data available for the selected filters</div><div style='font-size:12px'>Term: Term 1 | Year: 2026 | Grade: GRADE 7</div></div></div><div class='card'><b>Yearly Progression - 2026</b><div style='height:200px; border-left:1px solid #cbd5e1; border-bottom:1px solid #cbd5e1; display:flex; align-items:center; justify-content:center; color:#94a3b8'>Chart - Fresh System</div></div>"

    inner = f"""
<div class='content'>
<h1 style='font-size:26px; font-weight:700; margin:0'>Academic Analytics</h1><p style='color:#64748b; margin:6px 0 16px'>Performance insights across subjects, teachers, and students</p>
<div style='display:flex; gap:10px; margin-bottom:18px'><select style='padding:10px; border:1px solid #e2e8f0; border-radius:10px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><select style='padding:10px; border:1px solid #e2e8f0; border-radius:10px'><option>2026</option><option>2025</option><option>2024</option></select><select style='padding:10px; border:1px solid #e2e8f0; border-radius:10px'><option>GRADE 7</option><option>GRADE 8</option><option>GRADE 9</option></select></div>
<div style='display:flex; gap:24px; border-bottom:1px solid #e2e8f0; margin-bottom:18px; font-size:14px'>
<a href='/academics?tab=performance' style='padding:10px 0; text-decoration:none; {perf_style}'>Performance Trends</a>
<a href='/academics?tab=subject' style='padding:10px 0; text-decoration:none; {subj_style}'>Subject Analysis</a>
<a href='/academics?tab=teacher' style='padding:10px 0; text-decoration:none; {teach_style}'>Teacher Performance</a>
<a href='/academics?tab=student' style='padding:10px 0; text-decoration:none; {stud_style}'>Student Tracking</a>
</div>
{cards}
</div>
"""
    return HTMLResponse(dashboard_wrap(sname, inner, email, role, "academics"))

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    inner = """
<div class='content'>
<h1 style='font-size:26px; font-weight:700; margin:0'>Attendance Analytics</h1><p style='color:#64748b; margin:6px 0 16px'>Track student attendance patterns and trends</p>
<div style='display:flex; gap:10px; margin-bottom:18px'><select style='padding:10px; border:1px solid #e2e8f0; border-radius:10px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><select style='padding:10px; border:1px solid #e2e8f0; border-radius:10px'><option>2026</option></select><select style='padding:10px; border:1px solid #e2e8f0; border-radius:10px'><option>GRADE 7</option><option>GRADE 8</option><option>GRADE 9</option></select></div>
<div class='grid4'><div class='card'><div style='color:#64748b; font-size:13px'>Overall Attendance</div><h2>--</h2><small>Not marked yet</small></div><div class='card'><div style='color:#64748b; font-size:13px'>Present Today</div><h2>0</h2></div><div class='card'><div style='color:#64748b; font-size:13px'>Absent Today</div><h2>0</h2></div><div class='card'><div style='color:#64748b; font-size:13px'>Late Arrivals</div><h2>0</h2></div></div>
<div class='card'><b>Daily Attendance Trend</b><div style='height:220px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8; border-left:1px solid #e2e8f0; border-bottom:1px solid #e2e8f0; margin-top:12px'><div>No attendance data available</div><div style='font-size:12px'>Term: Term 1 | Year: 2026 | Grade: GRADE 7</div></div></div>
<div style='display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px'><div class='card'><b>Class-wise Attendance</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No class data</div></div><div class='card'><b>Gender Attendance Comparison</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No gender data</div></div></div>
</div>
"""
    return HTMLResponse(dashboard_wrap(sname, inner, email, role, "attendance"))

@app.get("/students", response_class=HTMLResponse)
def students_list(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    inner = "<div class='content'><div class='card'><h3>Students Manager - Fresh</h3><form method='post' action='/students/add' style='display:flex; gap:6px; flex-wrap:wrap'><input name='adm' placeholder='ADM' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='name' placeholder='Name' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='class' placeholder='Class' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><select name='gender' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><option>Boy</option><option>Girl</option></select><button style='background:#2563eb; color:white; padding:10px 16px; border:none; border-radius:8px'>Add</button></form></div></div>"
    return HTMLResponse(dashboard_wrap(sname, inner, email, role, ""))

@app.post("/students/add")
def add_student(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class"), gender: str = Form("Boy")):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, adm, name, class, gender) VALUES (?,?,?,?,?)", (request.session.get("school_id",0), adm, name, class_, gender))
    con.commit(); con.close()
    return RedirectResponse("/students", status_code=303)

@app.get("/super-admin", response_class=HTMLResponse)
def super_admin_page(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    inner = "<div class='content'><div class='card'><h3>Super Admin - oumadavis62@gmail.com</h3><p>Role: Super Admin - Top right will show correctly</p><a href='/dashboard' style='background:#2563eb; color:white; padding:10px 16px; border-radius:8px; text-decoration:none'>Dashboard</a> <a href='/super-admin/reset' style='background:#dc2626; color:white; padding:10px 16px; border-radius:8px; text-decoration:none; margin-left:8px'>RESET ALL DATA - Fresh</a></div></div>"
    return HTMLResponse(dashboard_wrap("Super Admin", inner, SUPER_ADMIN_EMAIL, "Super Admin", ""))

@app.get("/super-admin/reset")
def reset_data(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM students")
    cur.execute("DELETE FROM schools WHERE email!=?", (SUPER_ADMIN_EMAIL,))
    cur.execute("DELETE FROM users WHERE email!=?", (SUPER_ADMIN_EMAIL,))
    con.commit(); con.close()
    return RedirectResponse("/super-admin", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
