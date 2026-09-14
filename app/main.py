from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-academic-2026")
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
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, max_marks INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, exam_id INTEGER, subject TEXT, marks INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS subject_allocation (id INTEGER PRIMARY KEY, school_id INTEGER, class TEXT, subject TEXT, teacher TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit()
    con.close()
init_db()

def wrap(sname, inner, email, role, active_main="", active_sub=""):
    html = """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{box-sizing:border-box} body{margin:0; font-family:Arial; background:#fcfcfc; display:flex}
.sidebar{width:280px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}
.logo{padding:16px; border-bottom:1px solid #e2e8f0; display:flex; gap:10px; align-items:center}
.logo-icon{width:36px; height:36px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800}
.nav-label{font-size:10px; color:#94a3b8; margin:14px 18px 6px; letter-spacing:1px; font-weight:700}
.nav-item{display:block; padding:9px 14px; margin:2px 10px; border-radius:8px; text-decoration:none; font-size:13px; color:#334155}
.nav-item.active{background:#0f172a; color:white}
.sub{margin-left:18px; border-left:1px dashed #e2e8f0; padding-left:8px}
.main{margin-left:280px; flex:1}
.topbar{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; position:sticky; top:0; z-index:5}
.content{padding:20px}
.card{background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px; margin-bottom:14px}
.btn{background:#2563eb; color:white; border:none; padding:9px 14px; border-radius:8px; cursor:pointer; font-weight:600}
.btn2{background:#f1f5f9; border:1px solid #e2e8f0; padding:8px 12px; border-radius:8px; cursor:pointer}
table{width:100%; border-collapse:collapse} th,td{padding:8px; border:1px solid #e2e8f0; font-size:13px} th{background:#f8fafc}
.tab-bar{display:flex; gap:6px; flex-wrap:wrap; background:white; border:1px solid #e2e8f0; border-radius:12px; padding:8px; margin-bottom:16px}
.tab-link{padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>D</div><div><b>DaviSchool</b><div style='font-size:9px; color:#64748b'>SCHOOL MANAGEMENT</div></div></div>
<div class='nav-label'>MAIN NAVIGATION</div>
<a class='nav-item' href='/dashboard' style='color:#334155'>📊 Dashboard</a>

<a class='nav-item' href='/students?tab=list' style='color:#334155'>🎓 Students Manager</a>
<a class='nav-item' href='/staff' style='color:#334155'>👔 Staff Manager</a>

<a class='nav-item active'>📚 Academic Manager</a>
<div class='sub'>
<a class='nav-item' href='/academic-manager?tab=dean' style='""" + ("background:#0f172a; color:white" if active_sub=="dean" else "color:#334155") + """'>⚙️ Dean Settings</a>
<a class='nav-item' href='/academic-manager?tab=exam' style='""" + ("background:#0f172a; color:white" if active_sub=="exam" else "color:#334155") + """'>🔧 Exam Settings</a>
<a class='nav-item' href='/academic-manager?tab=setmarks' style='""" + ("background:#0f172a; color:white" if active_sub=="setmarks" else "color:#334155") + """'>📝 Set Marks</a>
<a class='nav-item' href='/academic-manager?tab=allocation' style='""" + ("background:#0f172a; color:white" if active_sub=="allocation" else "color:#334155") + """'>📋 Subject Allocation</a>
<a class='nav-item' href='/academic-manager?tab=record' style='""" + ("background:#0f172a; color:white" if active_sub=="record" else "color:#334155") + """'>✏️ Record Marks</a>
<a class='nav-item' href='/academic-manager?tab=edit' style='""" + ("background:#0f172a; color:white" if active_sub=="edit" else "color:#334155") + """'>✏️ Edit Marks</a>
<a class='nav-item' href='/academic-manager?tab=status' style='""" + ("background:#0f172a; color:white" if active_sub=="status" else "color:#334155") + """'>📊 Marks Status</a>
<a class='nav-item' href='/academic-manager?tab=analysis' style='""" + ("background:#0f172a; color:white" if active_sub=="analysis" else "color:#334155") + """'>📈 Exam Analysis</a>
<a class='nav-item' href='/academic-manager?tab=spreadsheet' style='""" + ("background:#0f172a; color:white" if active_sub=="spreadsheet" else "color:#334155") + """'>📄 Spreadsheet</a>
<a class='nav-item' href='/academic-manager?tab=sba' style='""" + ("background:#0f172a; color:white" if active_sub=="sba" else "color:#334155") + """'>✅ SBA (KNEC CBA)</a>
</div>

<a class='nav-item' href='/timetable?tab=periods' style='color:#334155'>📅 Timetable</a>
<a class='nav-item' href='/academics' style='color:#334155'>📈 Academic Analytics</a>

<div style='padding:14px; border-top:1px solid #e2e8f0; margin-top:20px'><b>Davis Ouma</b><br><small>""" + email + """</small><br><small style='color:#2563eb'>""" + role + """</small></div>
</div>
<div class='main'><div class='topbar'><div><b>""" + sname.upper() + """</b> (Code: 10069)</div><div>Davis Ouma - """ + role + """ - """ + email + """ | <a href='/logout'>Logout</a></div></div>
""" + inner + """
</div></body></html>
"""
    return html

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:400px'><h1>Welcome Back</h1><form method='post' action='/login'><input name='email' required placeholder='Email' style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'><input name='password' type='password' required placeholder='Password' style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'><button style='width:100%; background:#2563eb; color:white; padding:12px; border:none; border-radius:8px'>Sign In</button></form><a href='/register'>Register School</a></div></body></html>")

@app.get("/register", response_class=HTMLResponse)
def reg():
    return HTMLResponse("<html><body style='display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:380px; border:1px solid #e2e8f0; padding:24px; border-radius:12px'><h2>Register</h2><form method='post' action='/register'><input name='school_name' placeholder='School Name' required style='width:100%; padding:10px; margin:6px 0'><input name='email' placeholder='Email' required style='width:100%; padding:10px; margin:6px 0'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:10px; margin:6px 0'><button style='width:100%; background:#2563eb; color:white; padding:10px'>Register</button></form></div></body></html>")

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
    request.session["school_name"] = "MABALE COMPREHENSIVE SCHOOL"
    request.session["role"] = u["role"]
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dash(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Dashboard</h1><p>{sname} (Code: 10069)</p><div class='card'><div style='height:180px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No correlation data available for the selected filters</div><div style='margin-top:10px'><span style='color:#ef4444'>● Danger zone (low attendance + low grades)</span> <span style='margin-left:10px; color:#2563eb'>● Other students</span></div></div></div><div class='card'><b>Students Requiring Attention</b><div style='display:flex; gap:8px; justify-content:end'><span style='background:#0f172a; color:white; padding:4px 10px; border-radius:20px; font-size:12px'>All (0)</span><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:12px'>Critical (0)</span><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:12px'>High (0)</span><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:12px'>Moderate (0)</span></div><div style='height:100px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No chronic absentees found for the selected period</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "dashboard", ""))

@app.get("/academic-manager", response_class=HTMLResponse)
def academic_manager(request: Request, tab: str = "dean"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    sid = request.session.get("school_id",0)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=?", (sid,))
    exams = cur.fetchall()
    cur.execute("SELECT * FROM subject_allocation WHERE school_id=?", (sid,))
    allocs = cur.fetchall()
    cur.execute("SELECT * FROM students WHERE school_id=? AND status='active'", (sid,))
    students = cur.fetchall()
    con.close()

    if tab=="dean":
        content = """
<div class='card'><b>⚙️ Dean Settings</b><div style='color:#64748b; font-size:12px'>Configure academic year and dean office</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:12px'>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Current Academic Year</b><div style='margin-top:8px'><select class='btn2' style='width:100%'><option>2026</option><option>2025</option><option>2024</option></select></div><div style='font-size:12px; color:#64748b; margin-top:8px'>Year: 2026 | Term: Term 1</div></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Dean of Studies</b><div style='margin-top:8px; font-size:13px'>Name: Davis Ouma<br>Email: oumadavis940@gmail.com<br>Role: School Admin</div></div>
</div>
<div style='margin-top:12px; display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px'>
<div class='card' style='margin:0'><b>Classes</b><div style='font-size:12px'>GRADE 7, 8, 9 - CBC</div></div>
<div class='card' style='margin:0'><b>Grading System</b><div style='font-size:12px'>CBC - Exceeding, Meeting, Approaching</div></div>
<div class='card' style='margin:0'><b>Promotion</b><div style='font-size:12px'>Auto-promote: Enabled</div></div>
</div>
</div>
"""
    elif tab=="exam":
        rows = "".join([f"<tr><td>{e['name']}</td><td>{e['term']}</td><td>{e['year']}</td><td>{e['max_marks']}</td></tr>" for e in exams]) or "<tr><td colspan=4 style='padding:20px; text-align:center; color:#94a3b8'>No exams setup yet</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>🔧 Exam Settings</b><div style='color:#64748b; font-size:12px'>Define exams, terms, weightage</div></div><span style='background:#f1f5f9; padding:6px 12px; border-radius:20px; font-size:12px'>{len(exams)} exams</span></div>
<table style='margin-top:12px'><tr><th>Exam Name</th><th>Term</th><th>Year</th><th>Max Marks</th></tr>{rows}</table>
<form method='post' action='/academic-manager/add-exam' style='margin-top:16px; display:grid; grid-template-columns:1fr 120px 80px 100px 100px; gap:8px'><input name='name' placeholder='Mid Term 1' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><select name='term' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' placeholder='2026' value='2026' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='max_marks' type='number' placeholder='100' value='100' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><button class='btn'>Add Exam</button></form>
</div>
"""
    elif tab=="setmarks":
        content = f"""
<div class='card'><b>📝 Set Marks</b><div style='color:#64748b; font-size:12px'>Set maximum marks per subject per exam</div>
<div style='margin-top:12px; display:flex; gap:8px'><select class='btn2'><option>Mid Term 1 - 2026</option><option>End Term - 2026</option></select><select class='btn2'><option>GRADE 7</option><option>GRADE 8</option><option>GRADE 9</option></select><button class='btn2'>Load Subjects</button></div>
<div style='margin-top:12px'>
<table><tr><th>Subject</th><th>Max Marks</th><th>Pass Marks</th><th>Weight</th></tr>
<tr><td>Mathematics</td><td><input value='100' style='width:60px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td><input value='40' style='width:60px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td>100%</td></tr>
<tr><td>English</td><td><input value='100' style='width:60px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td><input value='40' style='width:60px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td>100%</td></tr>
<tr><td>Science</td><td><input value='100' style='width:60px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td><input value='40' style='width:60px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td>100%</td></tr>
</table>
<div style='margin-top:12px'><button class='btn'>Save Set Marks</button></div>
</div>
</div>
"""
    elif tab=="allocation":
        rows = "".join([f"<tr><td>{a['class']}</td><td>{a['subject']}</td><td>{a['teacher']}</td></tr>" for a in allocs]) or "<tr><td colspan=3 style='padding:20px; text-align:center; color:#94a3b8'>No allocations yet</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>📋 Subject Allocation</b><div style='color:#64748b; font-size:12px'>Allocate teachers to subjects per class</div></div><span style='background:#f1f5f9; padding:6px 12px; border-radius:20px; font-size:12px'>{len(allocs)} allocations</span></div>
<table style='margin-top:12px'><tr><th>Class</th><th>Subject</th><th>Teacher</th></tr>{rows}</table>
<form method='post' action='/academic-manager/add-allocation' style='margin-top:16px; display:grid; grid-template-columns:120px 1fr 1fr 100px; gap:8px'><input name='class' placeholder='GRADE 7' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject' placeholder='Mathematics' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='teacher' placeholder='Mr. Ouma' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><button class='btn'>Allocate</button></form>
</div>
"""
    elif tab=="record":
        rows = "".join([f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td><input style='width:70px; padding:6px; border:1px solid #e2e8f0; border-radius:6px' placeholder='0-100'></td></tr>" for s in students]) or "<tr><td colspan=3 style='padding:20px; text-align:center; color:#94a3b8'>No students - Add in Students Manager first</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>✏️ Record Marks</b><div style='color:#64748b; font-size:12px'>Enter marks per student per subject</div></div><div style='display:flex; gap:8px'><select class='btn2'><option>Mid Term 1</option></select><select class='btn2'><option>Mathematics</option><option>English</option><option>Science</option></select><select class='btn2'><option>GRADE 7</option></select></div></div>
<table style='margin-top:12px'><tr><th>ADM</th><th>Name</th><th>Marks (0-100)</th></tr>{rows}</table>
<div style='margin-top:12px'><button class='btn'>Save Marks</button> <span style='font-size:12px; color:#64748b; margin-left:8px'>{len(students)} students in GRADE 7</span></div>
</div>
"""
    elif tab=="edit":
        content = """
<div class='card'><b>✏️ Edit Marks</b><div style='color:#64748b; font-size:12px'>Edit already recorded marks</div>
<div style='margin-top:12px; display:flex; gap:8px'><select class='btn2'><option>Select Exam</option><option>Mid Term 1 - 2026</option></select><select class='btn2'><option>Select Subject</option><option>Mathematics</option></select><button class='btn2'>Load Marks</button></div>
<div style='margin-top:12px; height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8; border:1px dashed #e2e8f0; border-radius:12px'>Select exam and subject to edit marks<br>No marks recorded yet</div>
</div>
"""
    elif tab=="status":
        content = f"""
<div class='card'><b>📊 Marks Status</b><div style='color:#64748b; font-size:12px'>Track entry progress per class/subject</div>
<div style='margin-top:12px; display:grid; grid-template-columns:repeat(3,1fr); gap:12px'>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:12px'><b>GRADE 7</b><div style='font-size:12px; color:#64748b; margin-top:4px'>Mathematics: 0/{len(students)} entered<br>English: 0/{len(students)}<br>Science: 0/{len(students)}</div><div style='background:#f1f5f9; height:6px; border-radius:3px; margin-top:8px'><div style='background:#ef4444; height:6px; width:0%; border-radius:3px'></div></div><div style='font-size:11px; color:#ef4444; margin-top:4px'>0% complete</div></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:12px'><b>GRADE 8</b><div style='font-size:12px; color:#64748b; margin-top:4px'>Mathematics: 0/0 entered<br>English: 0/0<br>Science: 0/0</div><div style='background:#f1f5f9; height:6px; border-radius:3px; margin-top:8px'><div style='background:#ef4444; height:6px; width:0%; border-radius:3px'></div></div><div style='font-size:11px; color:#ef4444; margin-top:4px'>0% complete</div></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:12px'><b>GRADE 9</b><div style='font-size:12px; color:#64748b; margin-top:4px'>Mathematics: 0/0 entered<br>English: 0/0<br>Science: 0/0</div><div style='background:#f1f5f9; height:6px; border-radius:3px; margin-top:8px'><div style='background:#ef4444; height:6px; width:0%; border-radius:3px'></div></div><div style='font-size:11px; color:#ef4444; margin-top:4px'>0% complete</div></div>
</div>
</div>
"""
    elif tab=="analysis":
        content = """
<div class='card'><b>📈 Exam Analysis</b><div style='color:#64748b; font-size:12px'>Performance analysis per exam - No correlation data style</div>
<div style='margin-top:16px'>
<div style='height:200px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8; border:1px solid #e2e8f0; border-radius:12px'><div>No correlation data available for the selected filters</div><div style='margin-top:8px; font-size:13px'><span style='color:#ef4444'>● Danger zone (low attendance + low grades)</span> <span style='color:#2563eb; margin-left:12px'>● Other students</span></div></div>
<div style='margin-top:12px; display:grid; grid-template-columns:1fr 1fr; gap:12px'>
<div class='card' style='margin:0'><b>Top Performers</b><div style='color:#94a3b8; font-size:12px; margin-top:8px'>No exam data</div></div>
<div class='card' style='margin:0'><b>Low Performers</b><div style='color:#94a3b8; font-size:12px; margin-top:8px'>No exam data</div></div>
</div>
</div>
</div>
"""
    elif tab=="spreadsheet":
        content = """
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>📄 Spreadsheet</b><div style='color:#64748b; font-size:12px'>Excel-like marks entry - All subjects at once</div></div><div style='display:flex; gap:8px'><button class='btn2'>Import Excel</button><button class='btn2'>Export Excel</button><button class='btn'>Save All</button></div></div>
<div style='margin-top:12px; overflow-x:auto'>
<table><tr><th>ADM</th><th>Name</th><th>Math</th><th>Eng</th><th>Sci</th><th>CRE</th><th>SST</th><th>Total</th><th>Mean</th></tr>
<tr><td>1001</td><td>FLORENCE</td><td><input style='width:50px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td><input style='width:50px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td><input style='width:50px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td><input style='width:50px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td><input style='width:50px; padding:4px; border:1px solid #e2e8f0; border-radius:4px'></td><td>0</td><td>0</td></tr>
<tr><td colspan=9 style='padding:20px; text-align:center; color:#94a3b8'>No students - Add in Students Manager</td></tr>
</table>
</div>
</div>
"""
    elif tab=="sba":
        content = """
<div class='card'><b>✅ SBA (KNEC CBA) - Competency Based Assessment</b><div style='color:#64748b; font-size:12px'>CBC SBA Records for KNEC - MABALE COMPREHENSIVE SCHOOL</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:12px'>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Strand Assessment</b><div style='font-size:12px; color:#64748b; margin-top:6px'>Exceeding Expectation (EE)<br>Meeting Expectation (ME)<br>Approaching Expectation (AE)<br>Below Expectation (BE)</div></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>KNEC Upload</b><div style='font-size:12px; color:#64748b; margin-top:6px'>Term 1 2026 SBA<br>Status: Not Uploaded<br>Deadline: 30th May 2026</div><button class='btn' style='margin-top:8px; width:100%'>Generate KNEC CSV</button></div>
</div>
<div style='margin-top:12px; height:160px; display:flex; align-items:center; justify-content:center; color:#94a3b8; border:1px dashed #e2e8f0; border-radius:12px'>No SBA records - Record marks first in Record Marks tab</div>
</div>
"""
    else:
        content = "<div class='card'>Invalid</div>"

    inner = f"""
<div class='content'>
<h1 style='margin:0'>Academic Manager</h1><p style='color:#64748b; margin:6px 0 14px'>MABALE COMPREHENSIVE SCHOOL (Code: 10069) - Elimikasasa style - 10 tabs</p>
<div class='tab-bar'>
<a class='tab-link' href='/academic-manager?tab=dean' style='{"background:#0f172a; color:white" if tab=="dean" else "background:#f1f5f9; color:#334155"}'>⚙️ Dean Settings</a>
<a class='tab-link' href='/academic-manager?tab=exam' style='{"background:#0f172a; color:white" if tab=="exam" else "background:#f1f5f9; color:#334155"}'>🔧 Exam Settings</a>
<a class='tab-link' href='/academic-manager?tab=setmarks' style='{"background:#0f172a; color:white" if tab=="setmarks" else "background:#f1f5f9; color:#334155"}'>📝 Set Marks</a>
<a class='tab-link' href='/academic-manager?tab=allocation' style='{"background:#0f172a; color:white" if tab=="allocation" else "background:#f1f5f9; color:#334155"}'>📋 Subject Allocation</a>
<a class='tab-link' href='/academic-manager?tab=record' style='{"background:#0f172a; color:white" if tab=="record" else "background:#f1f5f9; color:#334155"}'>✏️ Record Marks</a>
<a class='tab-link' href='/academic-manager?tab=edit' style='{"background:#0f172a; color:white" if tab=="edit" else "background:#f1f5f9; color:#334155"}'>✏️ Edit Marks</a>
<a class='tab-link' href='/academic-manager?tab=status' style='{"background:#0f172a; color:white" if tab=="status" else "background:#f1f5f9; color:#334155"}'>📊 Marks Status</a>
<a class='tab-link' href='/academic-manager?tab=analysis' style='{"background:#0f172a; color:white" if tab=="analysis" else "background:#f1f5f9; color:#334155"}'>📈 Exam Analysis</a>
<a class='tab-link' href='/academic-manager?tab=spreadsheet' style='{"background:#0f172a; color:white" if tab=="spreadsheet" else "background:#f1f5f9; color:#334155"}'>📄 Spreadsheet</a>
<a class='tab-link' href='/academic-manager?tab=sba' style='{"background:#2563eb; color:white" if tab=="sba" else "background:#f1f5f9; color:#334155"}'>✅ SBA (KNEC CBA)</a>
</div>
{content}
</div>
"""
    return HTMLResponse(wrap(sname, inner, email, role, "academic", tab))

@app.post("/academic-manager/add-exam")
def add_exam(request: Request, name: str = Form(...), term: str = Form(...), year: str = Form(...), max_marks: int = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO exams (school_id, name, term, year, max_marks) VALUES (?,?,?,?,?)", (request.session.get("school_id",0), name, term, year, max_marks))
    con.commit(); con.close()
    return RedirectResponse("/academic-manager?tab=exam", status_code=303)

@app.post("/academic-manager/add-allocation")
def add_alloc(request: Request, class_: str = Form(..., alias="class"), subject: str = Form(...), teacher: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO subject_allocation (school_id, class, subject, teacher) VALUES (?,?,?,?)", (request.session.get("school_id",0), class_, subject, teacher))
    con.commit(); con.close()
    return RedirectResponse("/academic-manager?tab=allocation", status_code=303)

@app.get("/students", response_class=HTMLResponse)
def students_page(request: Request, tab: str = "list"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Students Manager - {tab}</h1><p>8 tabs: Students List, Transferred, Class List, Alumni, Attendance Sheet, Report, ID Cards, Clearance</p><a href='/academic-manager?tab=dean'>Go to Academic Manager - 10 tabs</a></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "students", ""))

@app.get("/timetable", response_class=HTMLResponse)
def timetable(request: Request, tab: str = "periods"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Timetable - {tab}</h1><p>8 tabs built</p></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "timetable", ""))

@app.get("/academics", response_class=HTMLResponse)
def academics(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = "<div class='content'><h1>Academic Analytics</h1><div class='card'>Teacher Performance - No data available</div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "academics", ""))

@app.get("/attendance", response_class=HTMLResponse)
def att(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = "<div class='content'><h1>Attendance Analytics</h1><div class='card'>No correlation data available - Danger zone + Other students</div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "attendance", ""))

@app.get("/super-admin", response_class=HTMLResponse)
def sa(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    inner = "<div class='content'><div class='card'><h3>Super Admin - oumadavis62@gmail.com - Role: Super Admin</h3><a href='/dashboard'>Dashboard</a></div></div>"
    return HTMLResponse(wrap("Super Admin", inner, SUPER_ADMIN_EMAIL, "Super Admin", ""))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
