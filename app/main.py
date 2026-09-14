from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-timetable-2026")
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
    cur.execute("CREATE TABLE IF NOT EXISTS timetable_periods (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, start TEXT, end TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS timetable_lessons (id INTEGER PRIMARY KEY, school_id INTEGER, class TEXT, subject TEXT, teacher TEXT, periods INTEGER)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit()
    con.close()
init_db()

def wrap(sname, inner, email, role, active=""):
    def nav_cls(name):
        return "background:#0f172a; color:white" if active==name else "color:#334155"
    
    html = """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{box-sizing:border-box} body{margin:0; font-family:Arial; background:#fcfcfc; display:flex}
.sidebar{width:270px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}
.logo{padding:16px; border-bottom:1px solid #e2e8f0; display:flex; gap:10px; align-items:center}
.logo-icon{width:36px; height:36px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800}
.nav-label{font-size:10px; color:#94a3b8; margin:14px 18px 6px; letter-spacing:1px; font-weight:700}
.nav-item{display:block; padding:9px 14px; margin:2px 10px; border-radius:8px; text-decoration:none; font-size:13px; color:#334155}
.nav-item.active{background:#0f172a; color:white}
.sub{margin-left:18px; border-left:1px dashed #e2e8f0; padding-left:8px}
.main{margin-left:270px; flex:1}
.topbar{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; position:sticky; top:0; z-index:5}
.content{padding:20px}
.card{background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px; margin-bottom:14px}
.btn{background:#2563eb; color:white; border:none; padding:10px 16px; border-radius:8px; font-weight:600; cursor:pointer}
.btn2{background:#f1f5f9; border:1px solid #e2e8f0; padding:8px 12px; border-radius:8px; cursor:pointer}
.grid4{display:grid; grid-template-columns:repeat(4,1fr); gap:12px}
.timetable-grid{display:grid; grid-template-columns:80px repeat(5,1fr); gap:1px; background:#e2e8f0; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden}
.t-cell{background:white; padding:10px; font-size:12px; min-height:50px}
.t-head{background:#0f172a; color:white; font-weight:700; padding:10px; text-align:center}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>D</div><div><b>DaviSchool</b><div style='font-size:9px; color:#64748b'>SCHOOL MANAGEMENT</div></div></div>
<div class='nav-label'>MAIN NAVIGATION</div>
<a class='nav-item' href='/dashboard' style='""" + nav_cls("overview") + """'>System Overview</a>
<a class='nav-item' href='/academics' style='""" + nav_cls("academics") + """'>Academic Analytics</a>
<a class='nav-item' href='/attendance' style='""" + nav_cls("attendance") + """'>Attendance Analytics</a>
<div class='nav-label'>ACADEMIC MANAGER</div>
<a class='nav-item """ + ("active" if active=="timetable" else "") + """' href='/timetable'>📅 Timetable</a>
<div class='sub' style='display:""" + ("block" if active=="timetable" else "none") + """'>
<a class='nav-item' href='/timetable?tab=periods'>⏰ Period Setup</a>
<a class='nav-item' href='/timetable?tab=lessons'>📚 Lesson Cards</a>
<a class='nav-item' href='/timetable?tab=constraints'>⚙️ Constraints</a>
<a class='nav-item' href='/timetable?tab=generate'>💻 Generate</a>
<a class='nav-item' href='/timetable?tab=view'>👁️ View Timetable</a>
<a class='nav-item' href='/timetable?tab=edit'>✏️ Edit Timetable</a>
<a class='nav-item' href='/timetable?tab=relationships'>🔗 Relationships</a>
<a class='nav-item' href='/timetable?tab=substitutions'>👥 Substitutions</a>
</div>
<a class='nav-item' href='/students'>Students Manager</a>
<a class='nav-item'>Financial Analytics</a>
<div style='padding:14px; border-top:1px solid #e2e8f0; margin-top:20px'><b>Davis Ouma</b><br><small>""" + email + """</small><br><small style='color:#2563eb'>""" + role + """</small></div>
</div>
<div class='main'><div class='topbar'><div><b>""" + sname.upper() + """</b> (DS-2026)</div><div>Davis Ouma - """ + role + """ - """ + email + """ | <a href='/logout'>Logout</a></div></div>
""" + inner + """
</div></body></html>
"""
    return html

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:400px'><h1>Welcome Back</h1><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'><button style='width:100%; background:#2563eb; color:white; padding:12px; border:none; border-radius:8px'>Sign In</button></form><p><a href='/register'>Register School</a></p></div></body></html>")

@app.get("/register", response_class=HTMLResponse)
def reg():
    return HTMLResponse("<html><body style='display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:380px; border:1px solid #e2e8f0; padding:24px; border-radius:12px'><h2>Register School</h2><form method='post' action='/register'><input name='school_name' placeholder='School Name' required style='width:100%; padding:10px; margin:6px 0'><input name='email' placeholder='Email' required style='width:100%; padding:10px; margin:6px 0'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:10px; margin:6px 0'><button style='width:100%; background:#2563eb; color:white; padding:10px'>Register</button></form></div></body></html>")

@app.post("/register")
def do_reg(school_name: str = Form(...), email: str = Form(...), password: str = Form(...)):
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
    u = cur.fetchone(); con.close()
    if not u:
        return HTMLResponse("Invalid login <a href='/'>Back</a>")
    request.session["user_email"] = email
    request.session["school_id"] = u["school_id"] if u["school_id"] else 0
    request.session["school_name"] = "DaviSchool Super Admin" if u["role"]=="super_admin" else "DaviSchool"
    request.session["role"] = u["role"]
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dash(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=?", (request.session.get("school_id",0),))
    total = cur.fetchone()["c"]
    con.close()
    inner = f"<div class='content'><h1>School Overview</h1><p>Welcome back, Davis! {sname}</p><div class='grid4'><div class='card'><b>Total Students</b><h2>{total}</h2></div><div class='card'><b>Attendance Today</b><h2>--</h2>Not marked</div><div class='card'><b>Fee Collection</b><h2>0%</h2></div><div class='card'><b>Timetable Status</b><h2>Not Generated</h2></div></div><div class='card'><a href='/timetable'>Go to Timetable - 8 Tabs</a> | <a href='/academics'>Academic Analytics</a> | <a href='/attendance'>Attendance Analytics</a></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "overview"))

@app.get("/academics", response_class=HTMLResponse)
def academics(request: Request, tab: str = "performance"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    if tab=="teacher":
        body = "<div class='card'><b>Top 10 Teachers by Value Added</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No teacher performance data available</div></div><div class='card'><b>Teacher Value-Added Details</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No teacher value-added data available</div></div>"
    elif tab=="student":
        body = "<div class='card'><b>Student Trajectories</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No student trajectory data available</div></div><div class='card'><b>Cohort Tracking</b><br>FLORENCE -><br><br>Select students above to view chart</div>"
    else:
        body = "<div class='card'><b>Class Performance Over Time</b><div style='height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No exam data</div></div>"
    inner = f"<div class='content'><h1>Academic Analytics - {tab}</h1><div style='display:flex; gap:16px; border-bottom:1px solid #e2e8f0; margin-bottom:12px; padding-bottom:8px'><a href='/academics?tab=performance'>Performance Trends</a><a href='/academics?tab=teacher'>Teacher Performance</a><a href='/academics?tab=student'>Student Tracking</a></div>{body}</div>"
    return HTMLResponse(wrap(sname, inner, email, role, "academics"))

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    inner = "<div class='content'><h1>Attendance Analytics</h1><div class='grid4'><div class='card'><b>Overall</b><h2>--</h2></div><div class='card'><b>Present</b><h2>0</h2></div><div class='card'><b>Absent</b><h2>0</h2></div><div class='card'><b>Late</b><h2>0</h2></div></div><div class='card'><b>Daily Attendance Trend</b><div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No attendance data</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "attendance"))

@app.get("/timetable", response_class=HTMLResponse)
def timetable(request: Request, tab: str = "periods"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM timetable_periods WHERE school_id=?", (request.session.get("school_id",0),))
    periods = cur.fetchall()
    cur.execute("SELECT * FROM timetable_lessons WHERE school_id=?", (request.session.get("school_id",0),))
    lessons = cur.fetchall()
    con.close()

    # Build tabs content
    if tab=="periods":
        rows = "".join([f"<tr><td style='padding:8px; border:1px solid #e2e8f0'>{p['name']}</td><td style='padding:8px; border:1px solid #e2e8f0'>{p['start']}-{p['end']}</td></tr>" for p in periods]) or "<tr><td colspan=2 style='padding:20px; text-align:center; color:#94a3b8'>No periods setup yet - Add periods below</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between; align-items:center'><div><b>⏰ Period Setup</b><div style='color:#64748b; font-size:12px'>Define school periods and break times</div></div><span style='background:#f1f5f9; padding:6px 12px; border-radius:20px; font-size:12px'>{len(periods)} periods</span></div>
<table style='width:100%; margin-top:16px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px; border:1px solid #e2e8f0; text-align:left'>Period</th><th style='padding:8px; border:1px solid #e2e8f0'>Time</th></tr>{rows}</table>
<form method='post' action='/timetable/add-period' style='margin-top:16px; display:flex; gap:8px'><input name='name' placeholder='Period 1' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='start' type='time' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='end' type='time' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><button class='btn'>Add Period</button></form>
</div>
<div class='card'><b>Default Template</b><div style='font-size:13px; color:#64748b; margin-top:8px'>8:00-8:40 Period 1, 8:40-9:20 Period 2, 9:20-10:00 Period 3, 10:00-10:30 Break, 10:30-11:10 Period 4, etc.</div></div>
"""
    elif tab=="lessons":
        rows = "".join([f"<tr><td style='padding:8px; border:1px solid #e2e8f0'>{l['class']}</td><td style='padding:8px; border:1px solid #e2e8f0'>{l['subject']}</td><td style='padding:8px; border:1px solid #e2e8f0'>{l['teacher']}</td><td style='padding:8px; border:1px solid #e2e8f0'>{l['periods']}</td></tr>" for l in lessons]) or "<tr><td colspan=4 style='padding:20px; text-align:center; color:#94a3b8'>No lesson cards yet</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>📚 Lesson Cards</b><div style='color:#64748b; font-size:12px'>Create subject-teacher-class allocations</div></div><span style='background:#f1f5f9; padding:6px 12px; border-radius:20px; font-size:12px'>{len(lessons)} lessons</span></div>
<table style='width:100%; margin-top:16px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px; border:1px solid #e2e8f0'>Class</th><th style='padding:8px; border:1px solid #e2e8f0'>Subject</th><th style='padding:8px; border:1px solid #e2e8f0'>Teacher</th><th style='padding:8px; border:1px solid #e2e8f0'>Periods/Week</th></tr>{rows}</table>
<form method='post' action='/timetable/add-lesson' style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr 1fr 80px 100px; gap:8px'><input name='class' placeholder='GRADE 7' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject' placeholder='Mathematics' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='teacher' placeholder='Mr. Ouma' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='periods' type='number' placeholder='4' value='4' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><button class='btn'>Add</button></form>
</div>
"""
    elif tab=="constraints":
        content = """
<div class='card'><b>⚙️ Constraints</b><div style='color:#64748b; font-size:12px; margin-top:4px'>Set rules for timetable generation</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:12px'>
<div style='border:1px solid #e2e8f0; padding:12px; border-radius:8px'><b>Teacher Constraints</b><div style='font-size:12px; color:#64748b; margin-top:6px'>Max periods per day: 6<br>Not available: Weekend<br>Min break between lessons: 1 period</div></div>
<div style='border:1px solid #e2e8f0; padding:12px; border-radius:8px'><b>Class Constraints</b><div style='font-size:12px; color:#64748b; margin-top:6px'>Max periods per day: 8<br>Double periods: Science<br>Lunch break: 12:30-1:30</div></div>
<div style='border:1px solid #e2e8f0; padding:12px; border-radius:8px'><b>Subject Constraints</b><div style='font-size:12px; color:#64748b; margin-top:6px'>Mathematics not last period<br>PE not first period<br>Max 2 same subject per day</div></div>
<div style='border:1px solid #e2e8f0; padding:12px; border-radius:8px'><b>Room Constraints</b><div style='font-size:12px; color:#64748b; margin-top:6px'>Lab for Science only<br>Hall for Assembly Monday</div></div>
</div>
</div>
"""
    elif tab=="generate":
        content = f"""
<div class='card'><b>💻 Generate Timetable</b><div style='color:#64748b; font-size:12px; margin-top:4px'>Auto-generate using constraints</div>
<div style='background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px; padding:24px; margin-top:16px; text-align:center'>
<div style='font-size:32px'>🤖</div><h3>Ready to Generate</h3><div style='color:#64748b; font-size:13px'>{len(periods)} periods, {len(lessons)} lessons, constraints set</div>
<div style='margin-top:16px'><button class='btn' style='padding:12px 24px; font-size:16px'>⚡ Generate Timetable Now</button></div>
<div style='font-size:12px; color:#94a3b8; margin-top:12px'>Estimated time: 15 seconds | Uses Elimikasasa algorithm</div>
</div>
<div style='margin-top:12px; display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px'>
<div class='card' style='margin:0'><b>✅ Checks</b><div style='font-size:12px; color:#16a34a'>No teacher conflicts<br>No class overload</div></div>
<div class='card' style='margin:0'><b>⚠️ Warnings</b><div style='font-size:12px; color:#f59e0b'>No warnings</div></div>
<div class='card' style='margin:0'><b>❌ Errors</b><div style='font-size:12px; color:#16a34a'>0 errors</div></div>
</div>
</div>
"""
    elif tab=="view":
        content = """
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>👁️ View Timetable</b><div style='color:#64748b; font-size:12px'>MABALE COMPREHENSIVE SCHOOL - GRADE 7</div></div><div style='display:flex; gap:8px'><select class='btn2'><option>GRADE 7</option><option>GRADE 8</option><option>GRADE 9</option></select><button class='btn2'>Print</button><button class='btn2'>Export PDF</button></div></div>
<div style='margin-top:16px'>
<div class='timetable-grid'><div class='t-head'>Time</div><div class='t-head'>Monday</div><div class='t-head'>Tuesday</div><div class='t-head'>Wednesday</div><div class='t-head'>Thursday</div><div class='t-head'>Friday</div>
<div class='t-cell'><b>8:00-8:40</b></div><div class='t-cell'>Math - Mr. Ouma</div><div class='t-cell'>Eng - Ms. Akinyi</div><div class='t-cell'>Sci - Mr. Kim</div><div class='t-cell'>Math - Mr. Ouma</div><div class='t-cell'>CRE - Ms. Njeri</div>
<div class='t-cell'><b>8:40-9:20</b></div><div class='t-cell'>Eng - Ms. Akinyi</div><div class='t-cell'>Math - Mr. Ouma</div><div class='t-cell'>Math - Mr. Ouma</div><div class='t-cell'>Agric - Mr. Otieno</div><div class='t-cell'>Math - Mr. Ouma</div>
<div class='t-cell'><b>9:20-10:00</b></div><div class='t-cell'>Sci - Mr. Kim</div><div class='t-cell'>SST - Mr. Barasa</div><div class='t-cell'>Eng - Ms. Akinyi</div><div class='t-cell'>Sci - Mr. Kim</div><div class='t-cell'>PE - Coach</div>
<div class='t-cell' style='background:#fef3c7'><b>10:00-10:30 BREAK</b></div><div class='t-cell' style='background:#fef3c7'></div><div class='t-cell' style='background:#fef3c7'></div><div class='t-cell' style='background:#fef3c7'></div><div class='t-cell' style='background:#fef3c7'></div><div class='t-cell' style='background:#fef3c7'></div>
</div>
</div>
</div>
"""
    elif tab=="edit":
        content = """
<div class='card'><b>✏️ Edit Timetable</b><div style='color:#64748b; font-size:12px'>Drag and drop to edit - Changes auto-save</div>
<div style='margin-top:16px; background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:12px; font-size:13px'>💡 Tip: Click any cell to edit subject/teacher. Red border = conflict, Yellow = warning</div>
<div style='margin-top:12px' class='timetable-grid'><div class='t-head'>Period</div><div class='t-head'>Mon</div><div class='t-head'>Tue</div><div class='t-head'>Wed</div><div class='t-head'>Thu</div><div class='t-head'>Fri</div>
<div class='t-cell'><b>P1</b></div><div class='t-cell' style='border:2px dashed #2563eb; cursor:pointer'>Click to edit</div><div class='t-cell' style='cursor:pointer'>Math</div><div class='t-cell' style='cursor:pointer'>Eng</div><div class='t-cell' style='cursor:pointer'>Sci</div><div class='t-cell' style='cursor:pointer'>CRE</div>
</div>
<div style='margin-top:12px; display:flex; gap:8px'><button class='btn'>Save Changes</button><button class='btn2'>Discard</button><button class='btn2'>Check Conflicts</button></div>
</div>
"""
    elif tab=="relationships":
        content = """
<div class='card'><b>🔗 Relationships</b><div style='color:#64748b; font-size:12px'>Link classes, teachers, subjects, rooms</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:16px'>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Teacher - Subject Relationship</b><div style='margin-top:8px; font-size:13px'><div>Mr. Ouma → Mathematics, Physics</div><div>Ms. Akinyi → English, Literature</div><div>Mr. Kim → Science, Biology</div></div></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Class - Room Relationship</b><div style='margin-top:8px; font-size:13px'><div>GRADE 7 → Room 1</div><div>GRADE 8 → Room 2</div><div>Lab → Science only</div></div></div>
</div>
</div>
"""
    elif tab=="substitutions":
        content = """
<div class='card'><b>👥 Substitutions</b><div style='color:#64748b; font-size:12px'>Manage teacher absence and replacements</div>
<div style='margin-top:16px'><div style='display:flex; gap:8px'><select class='btn2'><option>Select Absent Teacher</option><option>Mr. Ouma</option><option>Ms. Akinyi</option></select><input type='date' class='btn2'><button class='btn'>Find Substitute</button></div>
<div style='margin-top:16px; border:1px solid #e2e8f0; border-radius:8px; padding:20px; text-align:center; color:#94a3b8'><div>No substitutions needed today</div><div style='font-size:12px'>All teachers present</div></div>
<div style='margin-top:12px'><b>Substitution History</b><div style='font-size:12px; color:#64748b; margin-top:6px'>No history - Fresh system</div></div>
</div>
</div>
"""
    else:
        content = "<div class='card'>Select a tab</div>"

    tabs_bar = f"""
<div class='content'>
<h1 style='margin:0'>Timetable Manager</h1><p style='color:#64748b; margin:6px 0 14px'>MABALE COMPREHENSIVE SCHOOL - Academic Manager > Timetable (Elimikasasa style)</p>
<div style='display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px; background:white; border:1px solid #e2e8f0; border-radius:12px; padding:8px'>
<a href='/timetable?tab=periods' style='padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; {"background:#0f172a; color:white" if tab=="periods" else "background:#f1f5f9; color:#334155"}'>⏰ Period Setup</a>
<a href='/timetable?tab=lessons' style='padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; {"background:#0f172a; color:white" if tab=="lessons" else "background:#f1f5f9; color:#334155"}'>📚 Lesson Cards</a>
<a href='/timetable?tab=constraints' style='padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; {"background:#0f172a; color:white" if tab=="constraints" else "background:#f1f5f9; color:#334155"}'>⚙️ Constraints</a>
<a href='/timetable?tab=generate' style='padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; {"background:#2563eb; color:white" if tab=="generate" else "background:#f1f5f9; color:#334155"}'>💻 Generate</a>
<a href='/timetable?tab=view' style='padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; {"background:#0f172a; color:white" if tab=="view" else "background:#f1f5f9; color:#334155"}'>👁️ View</a>
<a href='/timetable?tab=edit' style='padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; {"background:#0f172a; color:white" if tab=="edit" else "background:#f1f5f9; color:#334155"}'>✏️ Edit</a>
<a href='/timetable?tab=relationships' style='padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; {"background:#0f172a; color:white" if tab=="relationships" else "background:#f1f5f9; color:#334155"}'>🔗 Relationships</a>
<a href='/timetable?tab=substitutions' style='padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; {"background:#0f172a; color:white" if tab=="substitutions" else "background:#f1f5f9; color:#334155"}'>👥 Substitutions</a>
</div>
{content}
</div>
"""
    return HTMLResponse(wrap(sname, tabs_bar, email, role, "timetable"))

@app.post("/timetable/add-period")
def add_period(request: Request, name: str = Form(...), start: str = Form(...), end: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO timetable_periods (school_id, name, start, end) VALUES (?,?,?,?)", (request.session.get("school_id",0), name, start, end))
    con.commit(); con.close()
    return RedirectResponse("/timetable?tab=periods", status_code=303)

@app.post("/timetable/add-lesson")
def add_lesson(request: Request, class_: str = Form(..., alias="class"), subject: str = Form(...), teacher: str = Form(...), periods: int = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO timetable_lessons (school_id, class, subject, teacher, periods) VALUES (?,?,?,?,?)", (request.session.get("school_id",0), class_, subject, teacher, periods))
    con.commit(); con.close()
    return RedirectResponse("/timetable?tab=lessons", status_code=303)

@app.get("/students", response_class=HTMLResponse)
def stud_page(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    inner = "<div class='content'><div class='card'><h3>Students Manager</h3><form method='post' action='/students/add' style='display:flex; gap:6px'><input name='adm' placeholder='ADM'><input name='name' placeholder='Name'><input name='class' placeholder='GRADE 7'><select name='gender'><option>Boy</option><option>Girl</option></select><button class='btn'>Add</button></form></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, ""))

@app.post("/students/add")
def add_stu(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class"), gender: str = Form("Boy")):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, adm, name, class, gender) VALUES (?,?,?,?,?)", (request.session.get("school_id",0), adm, name, class_, gender))
    con.commit(); con.close()
    return RedirectResponse("/students", status_code=303)

@app.get("/super-admin", response_class=HTMLResponse)
def sa(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    inner = "<div class='content'><div class='card'><h3>Super Admin - oumadavis62@gmail.com</h3><a href='/dashboard' class='btn'>Dashboard</a></div></div>"
    return HTMLResponse(wrap("Super Admin", inner, SUPER_ADMIN_EMAIL, "Super Admin", ""))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
