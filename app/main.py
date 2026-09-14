from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-super-admin-final-2026")
SUPER_ADMIN_EMAIL = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, approved INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, school_id INTEGER, role TEXT, full_name TEXT, phone TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, name TEXT, class TEXT, gender TEXT, status TEXT DEFAULT 'active')")
    cur.execute("CREATE TABLE IF NOT EXISTS staff (id INTEGER PRIMARY KEY, school_id INTEGER, staff_id TEXT, name TEXT, role TEXT, status TEXT DEFAULT 'active')")
    cur.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, school_id INTEGER, user TEXT, action TEXT, time TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role, full_name, phone) VALUES (?,?,?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin", "Davis Ouma", "+254748588874"))
    con.commit()
    con.close()
init_db()

def wrap(sname, inner, email, role, active_main="", active_sub=""):
    # For Super Admin, sname = DaviSchool Super Admin Platform, NOT MABALE
    html = """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{box-sizing:border-box} body{margin:0; font-family:Arial; background:#fcfcfc; display:flex}
.sidebar{width:290px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}
.logo{padding:16px; border-bottom:1px solid #e2e8f0; display:flex; gap:10px; align-items:center}
.logo-icon{width:36px; height:36px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800}
.nav-label{font-size:10px; color:#94a3b8; margin:14px 18px 6px; letter-spacing:1px; font-weight:700}
.nav-item{display:block; padding:9px 14px; margin:2px 10px; border-radius:8px; text-decoration:none; font-size:13px; color:#334155}
.nav-item.active{background:#0f172a; color:white}
.sub{margin-left:18px; border-left:1px dashed #e2e8f0; padding-left:8px}
.main{margin-left:290px; flex:1}
.topbar{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; position:sticky; top:0; z-index:5}
.content{padding:20px}
.card{background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px; margin-bottom:14px}
.btn{background:#2563eb; color:white; border:none; padding:9px 14px; border-radius:8px; cursor:pointer; font-weight:600}
.btn2{background:#f1f5f9; border:1px solid #e2e8f0; padding:8px 12px; border-radius:8px; cursor:pointer}
.input{width:100%; padding:12px; border:1px solid #e2e8f0; border-radius:10px; margin-top:6px; background:#f8fafc}
.label{font-size:13px; font-weight:600; color:#334155; margin-top:14px; display:block}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>D</div><div><b>DaviSchool</b><div style='font-size:9px; color:#64748b'>SUPER ADMIN PLATFORM</div></div></div>
<div class='nav-label'>SUPER ADMIN NAV</div>
<a class='nav-item' href='/super-admin' style='color:#334155'>🏢 All Schools</a>
<a class='nav-item' href='/dashboard' style='color:#334155'>📊 Platform Dashboard</a>
<a class='nav-item' href='/system-settings?tab=integrations' style='color:#334155'>🔌 Integrations (SMS + M-Pesa)</a>
<a class='nav-item' href='/system-settings?tab=billing' style='color:#334155'>💳 Billing Overview</a>

<div class='nav-label'>DEMO VIEW (How schools see it)</div>
<a class='nav-item' href='/students?tab=list' style='color:#334155; font-size:12px'>🎓 Students Manager (Demo)</a>
<a class='nav-item' href='/staff?tab=list' style='color:#334155; font-size:12px'>👔 Staff Manager (Demo)</a>
<a class='nav-item' href='/academic-manager?tab=dean' style='color:#334155; font-size:12px'>📚 Academic Manager (Demo)</a>
<a class='nav-item' href='/system-settings?tab=profile' style='color:#334155; font-size:12px'>⚙️ System Settings (Demo)</a>

<a class='nav-item active' style='margin-top:10px'>👤 My Profile</a>

<div style='padding:14px; border-top:1px solid #e2e8f0; margin-top:10px'><div style='display:flex; gap:8px; align-items:center'><div style='width:32px; height:32px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700'>DO</div><div><b style='font-size:13px'>Davis Ouma</b><br><small style='color:#64748b'>""" + email + """</small><br><small style='color:#2563eb'>Super Admin</small></div></div></div>
</div>
<div class='main'><div class='topbar'><div><b>""" + sname + """</b></div><div style='display:flex; align-items:center; gap:8px'><div style='width:28px; height:28px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:11px'>DO</div><div><div style='font-size:12px; font-weight:600'>Davis Ouma</div><div style='font-size:10px; color:#2563eb'>Super Admin</div></div> | <a href='/logout'>Logout</a></div></div>
""" + inner + """
</div></body></html>
"""
    return html

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:400px'><h1>DaviSchool - Super Admin</h1><p style='color:#64748b'>oumadavis62@gmail.com login</p><form method='post' action='/login'><input name='email' required placeholder='Super Admin Email' style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'><input name='password' type='password' required placeholder='Password' style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Sign In as Super Admin</button></form><a href='/register'>Register New School (Demo)</a></div></body></html>")

@app.get("/register", response_class=HTMLResponse)
def reg():
    return HTMLResponse("<html><body style='display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:380px; border:1px solid #e2e8f0; padding:24px; border-radius:12px'><h2>Register School (Demo Flow)</h2><p style='font-size:12px; color:#64748b'>This is how new schools will register. Their school name will appear where MABALE was appearing in screenshots.</p><form method='post' action='/register'><input name='school_name' placeholder='e.g MABALE COMPREHENSIVE SCHOOL' required style='width:100%; padding:10px; margin:6px 0'><input name='email' placeholder='School Admin Email' required style='width:100%; padding:10px; margin:6px 0'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:10px; margin:6px 0'><button style='width:100%; background:#2563eb; color:white; padding:10px'>Register School</button></form></div></body></html>")

@app.post("/register")
def do_reg(school_name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    code = "100" + str(int(datetime.now().timestamp()) % 1000)
    cur.execute("INSERT INTO schools (name, email, code, location, approved) VALUES (?,?,?,?,1)", (school_name, email, code, "Busia,BUSIA"))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email, password, school_id, role, full_name) VALUES (?,?,?,?,?)", (email, password, sid, "admin", "School Admin"))
    con.commit(); con.close()
    return RedirectResponse("/", status_code=303)

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    u = cur.fetchone()
    if not u:
        con.close()
        return HTMLResponse("Invalid <a href='/'>Back</a>")
    # Get school name if exists
    school_name = "DaviSchool Super Admin Platform"
    if u["school_id"]:
        cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],))
        sch = cur.fetchone()
        if sch:
            school_name = f"{sch['name']} (Code: {sch['code']})"
    con.close()
    request.session["user_email"] = email
    request.session["school_id"] = u["school_id"] if u["school_id"] else 0
    request.session["school_name"] = school_name
    request.session["role"] = u["role"]
    request.session["full_name"] = u["full_name"] or "Davis Ouma"
    if u["role"] == "super_admin":
        return RedirectResponse("/super-admin", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/super-admin", response_class=HTMLResponse)
def super_admin_dashboard(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC")
    schools = cur.fetchall()
    cur.execute("SELECT COUNT(*) as c FROM schools")
    total_schools = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM users WHERE role='admin'")
    total_admins = cur.fetchone()["c"]
    con.close()
    inner = f"""
<div class='content'>
<h1 style='margin:0'>Super Admin Dashboard</h1><p style='color:#64748b'>DaviSchool Platform - All Registered Schools</p>
<div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px'>
<div class='card' style='margin:0'><b>Total Schools</b><h2>{total_schools}</h2><small>Demo schools included</small></div>
<div class='card' style='margin:0'><b>Active Admins</b><h2>{total_admins}</h2></div>
<div class='card' style='margin:0'><b>Revenue</b><h2>KES 5k x {total_schools}</h2></div>
<div class='card' style='margin:0'><b>Platform Status</b><h2 style='color:#16a34a'>Live</h2></div>
</div>
<div class='card'><b>🏢 Registered Schools (MABALE was just one demo example)</b><div style='margin-top:12px'><table><tr><th>School Name</th><th>Code</th><th>Email</th><th>Action</th></tr>
{"".join([f"<tr><td>{s['name']}</td><td>{s['code']}</td><td>{s['email']}</td><td><span style='background:#dcfce7; padding:2px 8px; border-radius:12px; font-size:11px'>Active</span></td></tr>" for s in schools]) or "<tr><td colspan=4 style='padding:20px; text-align:center; color:#94a3b8'>No schools yet - Register a demo school to see how name appears for clients</td></tr>"}
</table></div>
<div style='margin-top:12px; font-size:12px; color:#64748b'>Note: For super admin view, we show "DaviSchool Super Admin Platform" at top. For school admins, their own school name (like MABALE COMPREHENSIVE SCHOOL) appears at top - that is the demo you saw in screenshots.</div>
</div>
<div class='card'><b>What School Admins See (Demo explanation)</b><div style='font-size:13px; color:#64748b; margin-top:8px'>When a school like MABALE COMPREHENSIVE SCHOOL (Code: 10069) logs in with oumadavis940@gmail.com, they see THEIR school name at top bar and in My Profile left card: MABALE COMPREHENSIVE SCHOOL, Busia,BUSIA. That was just an example. Your super admin view NEVER shows MABALE - it shows "DaviSchool Super Admin Platform"</div></div>
</div>
"""
    return HTMLResponse(wrap("DaviSchool Super Admin Platform - oumadavis62@gmail.com", inner, email, "Super Admin", "super", ""))

@app.get("/dashboard", response_class=HTMLResponse)
def dash(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    sname = request.session.get("school_name","DaviSchool Platform")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    if role=="Super Admin":
        return RedirectResponse("/super-admin")
    # For school admin demo
    inner = f"<div class='content'><h1>School Dashboard</h1><p>{sname} - This is how a registered school sees their dashboard</p><div class='card'><div style='height:160px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No correlation data available for the selected filters</div><div style='margin-top:8px'><span style='color:#ef4444'>● Danger zone</span> <span style='color:#2563eb; margin-left:8px'>● Other students</span></div></div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "dashboard", ""))

@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, tab: str = "personal"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role_display = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    full_name = request.session.get("full_name","Davis Ouma")
    sname_raw = request.session.get("school_name","DaviSchool Super Admin Platform")
    # Clean sname for display
    if role_display=="Super Admin":
        display_sname = "DaviSchool Super Admin Platform"
        location = "Nairobi, Kenya - Platform Owner"
    else:
        display_sname = sname_raw
        location = "Busia,BUSIA - Demo School Location (This is how it appears for clients)"

    inner = f"""
<div class='content'>
<h2 style='margin:0'>{display_sname}</h2><p style='color:#64748b; font-size:13px; margin:4px 0 12px'>{'Super Admin Account - MABALE word removed everywhere' if role_display=='Super Admin' else 'School Admin Account - Your school name appears here (Demo was MABALE)'}</p>

<div style='display:flex; gap:6px; border-bottom:1px solid #e2e8f0; padding-bottom:12px; margin-bottom:16px; font-size:14px'>
<a href='/profile?tab=personal' style='padding:8px 16px; border-bottom:2px solid #0f172a; font-weight:600; text-decoration:none; color:#0f172a'>👤 Personal Info</a>
<a href='/profile?tab=security' style='padding:8px 16px; text-decoration:none; color:#64748b'>🔒 Security</a>
<a href='/profile?tab=activity' style='padding:8px 16px; text-decoration:none; color:#64748b'>📊 Activity Log</a>
</div>

<div style='display:grid; grid-template-columns:320px 1fr; gap:16px'>
<div class='card' style='text-align:center; height:fit-content'>
<div style='width:90px; height:90px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:32px; font-weight:800; margin:0 auto; position:relative'>DO<div style='position:absolute; bottom:-2px; right:-2px; background:white; border-radius:50%; width:28px; height:28px; display:flex; align-items:center; justify-content:center; border:2px solid #e2e8f0; font-size:14px'>📷</div></div>
<h3 style='margin:16px 0 4px'>{full_name}</h3>
<span style='background:{"#0f172a; color:white" if role_display=="Super Admin" else "#e0f2fe; color:#0369a1"}; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600'>{role_display}</span>
<div style='margin-top:16px; font-size:13px; color:#64748b; text-align:left; border-top:1px solid #f1f5f9; padding-top:12px'><div style='display:flex; align-items:center; gap:8px; padding:6px 0'><span>✉️</span> {email}</div></div>
<div style='margin-top:16px; border-top:1px solid #f1f5f9; padding-top:12px; text-align:center'><div style='font-size:13px; font-weight:600; color:#334155'>{display_sname}</div><div style='font-size:12px; color:#64748b; margin-top:2px'>{location}</div></div>
</div>

<div class='card'>
<h3 style='margin:0'>Personal Information</h3><p style='color:#64748b; font-size:13px; margin:4px 0 16px'>Update your name, email, and phone number - Super Admin profile</p>
<label class='label'>Full Name</label><input value='{full_name}' class='input'>
<label class='label'>Email Address</label><input value='{email}' class='input'>
<label class='label'>Phone Number</label><input value='+254748588874' class='input'>
<label class='label'>Role</label><input value='{role_display} - oumadavis62@gmail.com' readonly class='input' style='background:#f1f5f9'>
<div style='margin-top:20px'><button class='btn'>Save Changes</button> <span style='font-size:12px; color:#64748b; margin-left:8px'>MABALE removed - Shows {display_sname} now</span></div>
</div>
</div>
</div>
"""
    return HTMLResponse(wrap(display_sname, inner, email, role_display, "profile", "personal"))

@app.get("/system-settings", response_class=HTMLResponse)
def sys_settings(request: Request, tab: str = "integrations"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool Super Admin Platform")
    if role=="Super Admin":
        sname = "DaviSchool Super Admin Platform"
    inner = f"<div class='content'><h1>System Settings - {tab}</h1><p>{sname}</p><div class='card'><b>Integrations at bottom left - Bulk SMS + M-Pesa - Works for all schools</b><div style='font-size:12px; color:#64748b; margin-top:8px'>No MABALE word here - Clean super admin view</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "system", tab))

@app.get("/students", response_class=HTMLResponse)
def students(request: Request, tab: str = "list"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    sname = request.session.get("school_name","DaviSchool Platform")
    if request.session.get("role")=="super_admin":
        sname = "DaviSchool Super Admin Platform (Demo View of Students Manager)"
    return HTMLResponse(wrap(sname, f"<div class='content'><h1>Students Manager (Demo) - {tab}</h1><p>For real schools, their school name appears here. MABALE was just example. For you as super admin, this is demo view.</p></div>", email, "Super Admin", "students", tab))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
