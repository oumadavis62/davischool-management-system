from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-students-2026")
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
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, name TEXT, class TEXT, gender TEXT, status TEXT DEFAULT 'active')")
    cur.execute("CREATE TABLE IF NOT EXISTS timetable_periods (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, start TEXT, end TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS timetable_lessons (id INTEGER PRIMARY KEY, school_id INTEGER, class TEXT, subject TEXT, teacher TEXT, periods INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY, school_id INTEGER, date TEXT, student_id INTEGER, status TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit()
    con.close()
init_db()

def wrap(sname, inner, email, role, active_main="", active_sub=""):
    def main_cls(name):
        return "background:#0f172a; color:white" if active_main==name else "color:#334155"
    def sub_cls(name):
        return "background:#0f172a; color:white; font-weight:600" if active_sub==name else "color:#334155"

    html = """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{box-sizing:border-box} body{margin:0; font-family:Arial; background:#fcfcfc; display:flex}
.sidebar{width:270px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}
.logo{padding:16px; border-bottom:1px solid #e2e8f0; display:flex; gap:10px; align-items:center}
.logo-icon{width:36px; height:36px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800}
.nav-label{font-size:10px; color:#94a3b8; margin:14px 18px 6px; letter-spacing:1px; font-weight:700}
.nav-item{display:block; padding:9px 14px; margin:2px 10px; border-radius:8px; text-decoration:none; font-size:13px}
.sub{margin-left:18px; border-left:1px dashed #e2e8f0; padding-left:8px}
.main{margin-left:270px; flex:1}
.topbar{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; position:sticky; top:0; z-index:5}
.content{padding:20px}
.card{background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px; margin-bottom:14px}
.btn{background:#2563eb; color:white; border:none; padding:9px 14px; border-radius:8px; cursor:pointer; font-weight:600}
.btn2{background:#f1f5f9; border:1px solid #e2e8f0; padding:8px 12px; border-radius:8px; cursor:pointer}
table{width:100%; border-collapse:collapse} th,td{padding:8px; border:1px solid #e2e8f0; font-size:13px; text-align:left} th{background:#f8fafc}
.tab-bar{display:flex; gap:6px; flex-wrap:wrap; background:white; border:1px solid #e2e8f0; border-radius:12px; padding:8px; margin-bottom:16px}
.tab-link{padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>D</div><div><b>DaviSchool</b><div style='font-size:9px; color:#64748b'>SCHOOL MANAGEMENT</div></div></div>
<div class='nav-label'>MAIN NAVIGATION</div>
<a class='nav-item' href='/dashboard' style='""" + main_cls("dashboard") + """'>📊 Dashboard</a>

<a class='nav-item """ + ("active" if active_main=="students" else "") + """' href='/students' style='font-weight:700'>🎓 Students Manager</a>
<div class='sub' style='display:""" + ("block" if active_main=="students" else "none") + """'>
<a class='nav-item' href='/students?tab=list' style='""" + sub_cls("list") + """'>👥 Students List</a>
<a class='nav-item' href='/students?tab=transferred' style='""" + sub_cls("transferred") + """'>⇄ Transferred List</a>
<a class='nav-item' href='/students?tab=class' style='""" + sub_cls("class") + """'>≡ Class List</a>
<a class='nav-item' href='/students?tab=alumni' style='""" + sub_cls("alumni") + """'>🎓 Alumni List</a>
<a class='nav-item' href='/students?tab=sheet' style='""" + sub_cls("sheet") + """'>📋 Attendance Sheet</a>
<a class='nav-item' href='/students?tab=report' style='""" + sub_cls("report") + """'>📊 Attendance Report</a>
<a class='nav-item' href='/students?tab=idcards' style='""" + sub_cls("idcards") + """'>🪪 ID Cards</a>
<a class='nav-item' href='/students?tab=clearance' style='""" + sub_cls("clearance") + """'>✅ Student Clearance</a>
</div>

<a class='nav-item' href='/timetable' style='""" + main_cls("timetable") + """'>📅 Timetable</a>
<a class='nav-item' href='/academics' style='""" + main_cls("academics") + """'>Academic Analytics</a>
<a class='nav-item' href='/attendance' style='""" + main_cls("attendance") + """'>Attendance Analytics</a>

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
        return HTMLResponse("Invalid <a href='/'>Back</a>")
    request.session["user_email"] = email
    request.session["school_id"] = u["school_id"] if u["school_id"] else 0
    request.session["school_name"] = "MABALE COMPREHENSIVE SCHOOL" if "940" in email else "DaviSchool Super Admin"
    request.session["role"] = u["role"]
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dash(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND status='active'", (request.session.get("school_id",0),))
    total = cur.fetchone()["c"]
    con.close()
    inner = f"<div class='content'><h1 style='margin:0'>Dashboard</h1><p style='color:#64748b'>{sname} (Code: 10069)</p><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px'><div class='card'><b>Total Students</b><h2>{total}</h2></div><div class='card'><b>Attendance</b><h2>--</h2></div><div class='card'><b>Fee</b><h2>0%</h2></div><div class='card'><b>Timetable</b><h2>Ready</h2></div></div><div class='card'><div style='height:200px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No correlation data available for the selected filters</div><div style='margin-top:12px'><span style='color:#ef4444'>● Danger zone (low attendance + low grades)</span> <span style='margin-left:12px; color:#2563eb'>● Other students</span></div></div></div><div class='card'><b>Students Requiring Attention</b><div style='display:flex; gap:8px; justify-content:end; margin:8px 0'><span style='background:#0f172a; color:white; padding:4px 10px; border-radius:20px; font-size:12px'>All</span><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:12px'>Critical (0)</span><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:12px'>High (0)</span><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:12px'>Moderate (0)</span></div><div style='height:120px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No chronic absentees found for the selected period</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "dashboard", ""))

@app.get("/students", response_class=HTMLResponse)
def students_page(request: Request, tab: str = "list", class_filter: str = "All"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    sid = request.session.get("school_id",0)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM students WHERE school_id=? AND status='active' ORDER BY id DESC", (sid,))
    students = cur.fetchall()
    cur.execute("SELECT * FROM students WHERE school_id=? AND status='transferred'", (sid,))
    transferred = cur.fetchall()
    cur.execute("SELECT * FROM students WHERE school_id=? AND status='alumni'", (sid,))
    alumni = cur.fetchall()
    con.close()

    # Filter by class if needed
    if class_filter != "All":
        students = [s for s in students if s["class"]==class_filter]

    if tab=="list":
        rows = ""
        for s in students:
            rows += f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td>{s['class']}</td><td>{s['gender']}</td><td><span style='background:#dcfce7; color:#16a34a; padding:2px 8px; border-radius:12px; font-size:11px'>Active</span></td><td><button class='btn2' style='padding:4px 8px; font-size:11px'>View</button></td></tr>"
        if not rows:
            rows = "<tr><td colspan=6 style='padding:30px; text-align:center; color:#94a3b8'>No students yet - Add students below<br>Fresh system - MABALE COMPREHENSIVE SCHOOL</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between; align-items:center'><div><b>👥 Students List</b><div style='color:#64748b; font-size:12px'>{len(students)} active students - {sname} (Code: 10069)</div></div><div style='display:flex; gap:8px'><select class='btn2' onchange="location.href='/students?tab=list&class_filter='+this.value"><option>All Classes</option><option>GRADE 7</option><option>GRADE 8</option><option>GRADE 9</option></select><button class='btn2'>Import CSV</button><button class='btn2'>Export</button></div></div>
<table style='margin-top:14px'><tr><th>ADM</th><th>Name</th><th>Class</th><th>Gender</th><th>Status</th><th>Action</th></tr>{rows}</table>
<form method='post' action='/students/add' style='margin-top:16px; display:grid; grid-template-columns:100px 1fr 120px 100px 100px; gap:8px'><input name='adm' placeholder='ADM e.g 1001' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='name' placeholder='Full Name e.g FLORENCE' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='class' placeholder='GRADE 7' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><select name='gender' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><option>Boy</option><option>Girl</option></select><button class='btn'>Add Student</button></form>
</div>
"""
    elif tab=="transferred":
        rows = "".join([f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td>{s['class']}</td><td>{s['gender']}</td></tr>" for s in transferred]) or "<tr><td colspan=4 style='padding:20px; text-align:center; color:#94a3b8'>No transferred students</td></tr>"
        content = f"<div class='card'><b>⇄ Transferred List</b><div style='color:#64748b; font-size:12px'>{len(transferred)} transferred students</div><table style='margin-top:12px'><tr><th>ADM</th><th>Name</th><th>Last Class</th><th>Gender</th></tr>{rows}</table></div>"
    elif tab=="class":
        # Group by class
        from collections import Counter
        classes = Counter([s["class"] for s in students if s["class"]])
        rows = "".join([f"<tr><td>{cls}</td><td>{cnt}</td><td><a href='/students?tab=list&class_filter={cls}'>View {cnt} students</a></td></tr>" for cls, cnt in classes.items()]) or "<tr><td colspan=3 style='padding:20px; text-align:center; color:#94a3b8'>No classes - Add students first</td></tr>"
        content = f"<div class='card'><b>≡ Class List</b><div style='color:#64748b; font-size:12px'>Classes in {sname}</div><table style='margin-top:12px'><tr><th>Class Name</th><th>Total Students</th><th>Action</th></tr>{rows}</table></div>"
    elif tab=="alumni":
        rows = "".join([f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td>{s['class']}</td></tr>" for s in alumni]) or "<tr><td colspan=3 style='padding:20px; text-align:center; color:#94a3b8'>No alumni yet</td></tr>"
        content = f"<div class='card'><b>🎓 Alumni List</b><div style='color:#64748b; font-size:12px'>Graduated students</div><table style='margin-top:12px'><tr><th>ADM</th><th>Name</th><th>Last Class</th></tr>{rows}</table></div>"
    elif tab=="sheet":
        today = "2026-05-13"
        rows = "".join([f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td>{s['class']}</td><td><select class='btn2'><option>Present</option><option>Absent</option><option>Late</option></select></td></tr>" for s in students]) or "<tr><td colspan=4 style='padding:20px; text-align:center; color:#94a3b8'>No students to mark attendance</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>📋 Attendance Sheet</b><div style='color:#64748b; font-size:12px'>Mark daily attendance - {today}</div></div><div style='display:flex; gap:8px'><input type='date' value='{today}' class='btn2'><select class='btn2'><option>GRADE 7</option><option>GRADE 8</option><option>GRADE 9</option></select><button class='btn'>Save Attendance</button></div></div>
<table style='margin-top:12px'><tr><th>ADM</th><th>Name</th><th>Class</th><th>Status</th></tr>{rows}</table>
</div>
"""
    elif tab=="report":
        content = f"""
<div class='card'><b>📊 Attendance Report</b><div style='color:#64748b; font-size:12px'>Monthly attendance summary</div>
<div style='margin-top:16px; display:flex; gap:8px'><select class='btn2'><option>May 2026</option><option>April 2026</option></select><select class='btn2'><option>All Classes</option><option>GRADE 7</option></select><button class='btn2'>Generate Report</button></div>
<div style='margin-top:16px; height:200px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8; border:1px dashed #e2e8f0; border-radius:12px'><div>No attendance data available for selected filters</div><div style='font-size:12px; margin-top:4px'>{sname} - {len(students)} students</div></div>
</div>
"""
    elif tab=="idcards":
        cards_html = "".join([f"<div style='border:1px solid #e2e8f0; border-radius:10px; padding:12px; width:220px'><div style='background:#0f172a; color:white; padding:8px; border-radius:6px; text-align:center; font-size:12px'>{sname}</div><div style='text-align:center; margin-top:8px'><div style='width:60px; height:60px; background:#f1f5f9; border-radius:50%; margin:0 auto'></div><div style='font-weight:700; margin-top:6px; font-size:13px'>{s['name']}</div><div style='font-size:11px; color:#64748b'>{s['class']} | {s['adm']}</div></div></div>" for s in students[:6]]) or "<div style='color:#94a3b8'>No students for ID cards</div>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>🪪 ID Cards</b><div style='color:#64748b; font-size:12px'>Generate student ID cards - MABALE COMPREHENSIVE SCHOOL</div></div><div><button class='btn2'>Print All</button> <button class='btn'>Download PDF</button></div></div>
<div style='margin-top:16px; display:flex; flex-wrap:wrap; gap:12px'>{cards_html}</div>
</div>
"""
    elif tab=="clearance":
        content = f"""
<div class='card'><b>✅ Student Clearance</b><div style='color:#64748b; font-size:12px'>Clear students for transfer or completion</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:12px'>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Clearance Checklist</b><div style='font-size:13px; margin-top:8px; color:#64748b'>✓ Library - No books<br>✓ Finance - No balance<br>✓ Lab - No equipment<br>✓ Sports - Returned</div></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Generate Clearance Form</b><div style='margin-top:8px'><select class='btn2' style='width:100%; margin-bottom:8px'><option>Select Student</option>{"".join([f"<option>{s['name']} - {s['adm']}</option>" for s in students])}</select><button class='btn' style='width:100%'>Generate Clearance</button></div></div>
</div>
<div style='margin-top:12px; height:120px; display:flex; align-items:center; justify-content:center; color:#94a3b8; border:1px dashed #e2e8f0; border-radius:8px'>No clearance requests - {len(students)} active students</div>
</div>
"""
    else:
        content = "<div class='card'>Invalid tab</div>"

    inner = f"""
<div class='content'>
<h1 style='margin:0'>Students Manager</h1><p style='color:#64748b; margin:6px 0 14px'>MABALE COMPREHENSIVE SCHOOL (Code: 10069) - Elimikasasa style</p>
<div class='tab-bar'>
<a class='tab-link' href='/students?tab=list' style='{"background:#0f172a; color:white" if tab=="list" else "background:#f1f5f9; color:#334155"}'>👥 Students List</a>
<a class='tab-link' href='/students?tab=transferred' style='{"background:#0f172a; color:white" if tab=="transferred" else "background:#f1f5f9; color:#334155"}'>⇄ Transferred List</a>
<a class='tab-link' href='/students?tab=class' style='{"background:#0f172a; color:white" if tab=="class" else "background:#f1f5f9; color:#334155"}'>≡ Class List</a>
<a class='tab-link' href='/students?tab=alumni' style='{"background:#0f172a; color:white" if tab=="alumni" else "background:#f1f5f9; color:#334155"}'>🎓 Alumni List</a>
<a class='tab-link' href='/students?tab=sheet' style='{"background:#0f172a; color:white" if tab=="sheet" else "background:#f1f5f9; color:#334155"}'>📋 Attendance Sheet</a>
<a class='tab-link' href='/students?tab=report' style='{"background:#0f172a; color:white" if tab=="report" else "background:#f1f5f9; color:#334155"}'>📊 Attendance Report</a>
<a class='tab-link' href='/students?tab=idcards' style='{"background:#0f172a; color:white" if tab=="idcards" else "background:#f1f5f9; color:#334155"}'>🪪 ID Cards</a>
<a class='tab-link' href='/students?tab=clearance' style='{"background:#0f172a; color:white" if tab=="clearance" else "background:#f1f5f9; color:#334155"}'>✅ Student Clearance</a>
</div>
{content}
</div>
"""
    return HTMLResponse(wrap(sname, inner, email, role, "students", tab))

@app.post("/students/add")
def add_student(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class"), gender: str = Form("Boy")):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, adm, name, class, gender, status) VALUES (?,?,?,?,?,?)", (request.session.get("school_id",0), adm, name, class_, gender, "active"))
    con.commit(); con.close()
    return RedirectResponse("/students?tab=list", status_code=303)

@app.get("/timetable", response_class=HTMLResponse)
def timetable_page(request: Request, tab: str = "periods"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Timetable - {tab}</h1><p>8 tabs: Period Setup, Lesson Cards, Constraints, Generate, View, Edit, Relationships, Substitutions</p><a href='/students'>Go to Students Manager</a></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "timetable", ""))

@app.get("/academics", response_class=HTMLResponse)
def acad_page(request: Request, tab: str = "performance"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Academic Analytics - {tab}</h1><div class='card'><b>Teacher Performance</b><div>No teacher performance data available</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "academics", ""))

@app.get("/attendance", response_class=HTMLResponse)
def att_page(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = "<div class='content'><h1>Attendance Analytics</h1><div class='card'><b>Overall Attendance</b><h2>--</h2>Not marked yet</div><div class='card'><div>No correlation data available</div><div><span style='color:red'>● Danger zone</span> <span style='color:blue'>● Other students</span></div></div><div class='card'><b>Students Requiring Attention</b><div>No chronic absentees</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "attendance", ""))

@app.get("/super-admin", response_class=HTMLResponse)
def sa_page(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    inner = "<div class='content'><div class='card'><h3>Super Admin - oumadavis62@gmail.com - Role: Super Admin</h3><a href='/dashboard'>Dashboard</a></div></div>"
    return HTMLResponse(wrap("Super Admin", inner, SUPER_ADMIN_EMAIL, "Super Admin", ""))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
