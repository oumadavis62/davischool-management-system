from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-staff-2026")
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
    cur.execute("CREATE TABLE IF NOT EXISTS staff (id INTEGER PRIMARY KEY, school_id INTEGER, staff_id TEXT, name TEXT, role TEXT, phone TEXT, status TEXT DEFAULT 'active')")
    cur.execute("CREATE TABLE IF NOT EXISTS staff_attendance (id INTEGER PRIMARY KEY, school_id INTEGER, staff_id INTEGER, date TEXT, status TEXT)")
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

<a class='nav-item active'>👔 Staff Manager</a>
<div class='sub'>
<a class='nav-item' href='/staff?tab=list' style='""" + ("background:#0f172a; color:white" if active_sub=="list" else "color:#334155") + """'>👥 Staff List</a>
<a class='nav-item' href='/staff?tab=sheet' style='""" + ("background:#0f172a; color:white" if active_sub=="sheet" else "color:#334155") + """'>📋 Attendance Sheet</a>
<a class='nav-item' href='/staff?tab=report' style='""" + ("background:#0f172a; color:white" if active_sub=="report" else "color:#334155") + """'>📊 Attendance Report</a>
<a class='nav-item' href='/staff?tab=former' style='""" + ("background:#0f172a; color:white" if active_sub=="former" else "color:#334155") + """'>👋 Former Staff</a>
</div>

<a class='nav-item' href='/academic-manager?tab=dean' style='color:#334155'>📚 Academic Manager</a>
<a class='nav-item' href='/timetable?tab=periods' style='color:#334155'>📅 Timetable</a>
<a class='nav-item' href='/online-classes' style='color:#334155'>🎥 Online Classes</a>
<a class='nav-item' href='/library' style='color:#334155'>📚 Library Manager</a>
<a class='nav-item' href='/finance' style='color:#334155'>💰 Finance</a>

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
    inner = f"<div class='content'><h1>Dashboard</h1><p>{sname} (Code: 10069)</p><div class='card'><div style='height:180px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No correlation data available for the selected filters</div><div style='margin-top:10px'><span style='color:#ef4444'>● Danger zone (low attendance + low grades)</span> <span style='color:#2563eb; margin-left:10px'>● Other students</span></div></div></div><div class='card'><b>Students Requiring Attention</b><div style='height:100px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No chronic absentees found for the selected period</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "dashboard", ""))

@app.get("/staff", response_class=HTMLResponse)
def staff_page(request: Request, tab: str = "list"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    sid = request.session.get("school_id",0)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM staff WHERE school_id=? AND status='active' ORDER BY id DESC", (sid,))
    staff_list = cur.fetchall()
    cur.execute("SELECT * FROM staff WHERE school_id=? AND status='former'", (sid,))
    former = cur.fetchall()
    con.close()

    if tab=="list":
        rows = "".join([f"<tr><td>{s['staff_id']}</td><td>{s['name']}</td><td>{s['role']}</td><td>{s['phone']}</td><td><span style='background:#dcfce7; color:#16a34a; padding:2px 8px; border-radius:12px; font-size:11px'>Active</span></td><td><button class='btn2' style='padding:4px 8px; font-size:11px'>View</button></td></tr>" for s in staff_list]) or "<tr><td colspan=6 style='padding:30px; text-align:center; color:#94a3b8'>No staff yet - Add staff below<br>MABALE COMPREHENSIVE SCHOOL - Fresh system</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between; align-items:center'><div><b>👥 Staff List</b><div style='color:#64748b; font-size:12px'>{len(staff_list)} active staff - {sname}</div></div><div style='display:flex; gap:8px'><button class='btn2'>Import CSV</button><button class='btn2'>Export</button></div></div>
<table style='margin-top:14px'><tr><th>Staff ID</th><th>Name</th><th>Role</th><th>Phone</th><th>Status</th><th>Action</th></tr>{rows}</table>
<form method='post' action='/staff/add' style='margin-top:16px; display:grid; grid-template-columns:100px 1fr 140px 120px 100px; gap:8px'><input name='staff_id' placeholder='T001' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='name' placeholder='Full Name e.g Mr. Ouma' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='role' placeholder='Teacher' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' placeholder='07...' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><button class='btn'>Add Staff</button></form>
</div>
"""
    elif tab=="sheet":
        today = "2026-05-13"
        rows = "".join([f"<tr><td>{s['staff_id']}</td><td>{s['name']}</td><td>{s['role']}</td><td><select class='btn2'><option>Present</option><option>Absent</option><option>Late</option><option>Leave</option></select></td></tr>" for s in staff_list]) or "<tr><td colspan=4 style='padding:20px; text-align:center; color:#94a3b8'>No staff to mark attendance</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>📋 Staff Attendance Sheet</b><div style='color:#64748b; font-size:12px'>Mark daily staff attendance - {today}</div></div><div style='display:flex; gap:8px'><input type='date' value='{today}' class='btn2'><button class='btn'>Save Attendance</button></div></div>
<table style='margin-top:12px'><tr><th>Staff ID</th><th>Name</th><th>Role</th><th>Status</th></tr>{rows}</table>
</div>
"""
    elif tab=="report":
        content = f"""
<div class='card'><b>📊 Staff Attendance Report</b><div style='color:#64748b; font-size:12px'>Monthly staff attendance summary - {sname}</div>
<div style='margin-top:16px; display:flex; gap:8px'><select class='btn2'><option>May 2026</option><option>April 2026</option></select><select class='btn2'><option>All Staff</option><option>Teachers</option><option>Non-Teaching</option></select><button class='btn2'>Generate Report</button></div>
<div style='margin-top:16px; height:200px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8; border:1px dashed #e2e8f0; border-radius:12px'><div>No staff attendance data available for selected period</div><div style='font-size:12px; margin-top:4px'>{len(staff_list)} active staff members</div></div>
</div>
"""
    elif tab=="former":
        rows = "".join([f"<tr><td>{s['staff_id']}</td><td>{s['name']}</td><td>{s['role']}</td><td>{s['phone']}</td><td>Former</td></tr>" for s in former]) or "<tr><td colspan=5 style='padding:20px; text-align:center; color:#94a3b8'>No former staff</td></tr>"
        content = f"""
<div class='card'><b>👋 Former Staff</b><div style='color:#64748b; font-size:12px'>{len(former)} former staff members</div>
<table style='margin-top:12px'><tr><th>Staff ID</th><th>Name</th><th>Last Role</th><th>Phone</th><th>Status</th></tr>{rows}</table>
<div style='margin-top:12px; font-size:12px; color:#64748b'>Former staff are kept for records - Clearance, NSSF, pension etc.</div>
</div>
"""
    else:
        content = "<div class='card'>Invalid tab</div>"

    inner = f"""
<div class='content'>
<h1 style='margin:0'>Staff Manager</h1><p style='color:#64748b; margin:6px 0 14px'>MABALE COMPREHENSIVE SCHOOL (Code: 10069) - Staff Management</p>
<div class='tab-bar'>
<a class='tab-link' href='/staff?tab=list' style='{"background:#0f172a; color:white" if tab=="list" else "background:#f1f5f9; color:#334155"}'>👥 Staff List</a>
<a class='tab-link' href='/staff?tab=sheet' style='{"background:#0f172a; color:white" if tab=="sheet" else "background:#f1f5f9; color:#334155"}'>📋 Attendance Sheet</a>
<a class='tab-link' href='/staff?tab=report' style='{"background:#0f172a; color:white" if tab=="report" else "background:#f1f5f9; color:#334155"}'>📊 Attendance Report</a>
<a class='tab-link' href='/staff?tab=former' style='{"background:#0f172a; color:white" if tab=="former" else "background:#f1f5f9; color:#334155"}'>👋 Former Staff</a>
</div>
{content}
</div>
"""
    return HTMLResponse(wrap(sname, inner, email, role, "staff", tab))

@app.post("/staff/add")
def add_staff(request: Request, staff_id: str = Form(...), name: str = Form(...), role: str = Form(...), phone: str = Form("")):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO staff (school_id, staff_id, name, role, phone, status) VALUES (?,?,?,?,?,?)", (request.session.get("school_id",0), staff_id, name, role, phone, "active"))
    con.commit(); con.close()
    return RedirectResponse("/staff?tab=list", status_code=303)

@app.get("/students", response_class=HTMLResponse)
def students(request: Request, tab: str = "list"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Students Manager</h1><p>8 tabs built - Go to Staff Manager</p></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "students", ""))

@app.get("/academic-manager", response_class=HTMLResponse)
def acad_mgr(request: Request, tab: str = "dean"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Academic Manager - 10 tabs built</h1></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "academic", ""))

@app.get("/timetable", response_class=HTMLResponse)
def timetable(request: Request, tab: str = "periods"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Timetable - 8 tabs built</h1></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "timetable", ""))

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Dashboard</h1><p>{sname} (Code: 10069)</p><div class='card'><div style='height:180px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No correlation data available for the selected filters</div><div style='margin-top:10px'><span style='color:#ef4444'>● Danger zone (low attendance + low grades)</span> <span style='color:#2563eb; margin-left:10px'>● Other students</span></div></div></div><div class='card'><b>Students Requiring Attention</b><div style='height:100px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No chronic absentees found for the selected period</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "dashboard", ""))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
