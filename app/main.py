from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-system-settings-2026")
SUPER_ADMIN_EMAIL = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, approved INTEGER DEFAULT 0, code TEXT, motto TEXT, phone TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, school_id INTEGER, role TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, name TEXT, class TEXT, gender TEXT, status TEXT DEFAULT 'active')")
    cur.execute("CREATE TABLE IF NOT EXISTS staff (id INTEGER PRIMARY KEY, school_id INTEGER, staff_id TEXT, name TEXT, role TEXT, phone TEXT, status TEXT DEFAULT 'active')")
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, school_id INTEGER, user TEXT, action TEXT, time TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit()
    con.close()
init_db()

def log_action(school_id, user, action):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO audit_log (school_id, user, action, time) VALUES (?,?,?,?)", (school_id, user, action, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit(); con.close()

def wrap(sname, inner, email, role, active_main="", active_sub=""):
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
table{width:100%; border-collapse:collapse} th,td{padding:8px; border:1px solid #e2e8f0; font-size:13px} th{background:#f8fafc}
.tab-bar{display:flex; gap:6px; flex-wrap:wrap; background:white; border:1px solid #e2e8f0; border-radius:12px; padding:8px; margin-bottom:16px}
.tab-link{padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px}
.grid2{display:grid; grid-template-columns:1fr 1fr; gap:12px}
.grid3{display:grid; grid-template-columns:repeat(3,1fr); gap:12px}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>D</div><div><b>DaviSchool</b><div style='font-size:9px; color:#64748b'>SCHOOL MANAGEMENT</div></div></div>
<div class='nav-label'>MAIN NAVIGATION</div>
<a class='nav-item' href='/dashboard' style='color:#334155'>📊 Dashboard</a>
<a class='nav-item' href='/students?tab=list' style='color:#334155'>🎓 Students Manager</a>
<a class='nav-item' href='/staff?tab=list' style='color:#334155'>👔 Staff Manager</a>
<a class='nav-item' href='/academic-manager?tab=dean' style='color:#334155'>📚 Academic Manager</a>
<a class='nav-item' href='/timetable?tab=periods' style='color:#334155'>📅 Timetable</a>

<div class='nav-label'>OTHER MANAGERS</div>
<a class='nav-item' href='/inventory' style='color:#334155'>📦 Inventory</a>
<a class='nav-item' href='/kitchen' style='color:#334155'>🍳 Kitchen Manager</a>
<a class='nav-item' href='/transport' style='color:#334155'>🚌 Transport</a>
<a class='nav-item' href='/communication' style='color:#334155'>💬 Communication</a>

<a class='nav-item active'>⚙️ System Settings</a>
<div class='sub'>
<a class='nav-item' href='/system-settings?tab=profile' style='""" + ("background:#0f172a; color:white" if active_sub=="profile" else "color:#334155") + """'>🏫 School Profile</a>
<a class='nav-item' href='/system-settings?tab=classes' style='""" + ("background:#0f172a; color:white" if active_sub=="classes" else "color:#334155") + """'>🏛️ Classes</a>
<a class='nav-item' href='/system-settings?tab=users' style='""" + ("background:#0f172a; color:white" if active_sub=="users" else "color:#334155") + """'>👥 User Management</a>
<a class='nav-item' href='/system-settings?tab=roles' style='""" + ("background:#0f172a; color:white" if active_sub=="roles" else "color:#334155") + """'>🛡️ Roles & Permissions</a>
<a class='nav-item' href='/system-settings?tab=backup' style='""" + ("background:#0f172a; color:white" if active_sub=="backup" else "color:#334155") + """'>💾 Database Backup</a>
<a class='nav-item' href='/system-settings?tab=audit' style='""" + ("background:#0f172a; color:white" if active_sub=="audit" else "color:#334155") + """'>📈 System Audit</a>
<a class='nav-item' href='/system-settings?tab=integrations' style='""" + ("background:#2563eb; color:white; font-weight:700" if active_sub=="integrations" else "color:#334155") + """'>🔌 Integrations</a>
<a class='nav-item' href='/system-settings?tab=billing' style='""" + ("background:#0f172a; color:white" if active_sub=="billing" else "color:#334155") + """'>💳 Billing & Payments</a>
</div>

<a class='nav-item' href='/profile' style='margin-top:10px; color:#334155'>👤 My Profile</a>

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
    cur.execute("INSERT INTO schools (name, email, approved, code) VALUES (?,?,?,?)", (school_name, email, 0, "10069"))
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
    log_action(request.session["school_id"], email, "Login")
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dash(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Dashboard</h1><p>{sname} (Code: 10069)</p><div class='card'><div style='height:180px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No correlation data available for the selected filters</div><div style='margin-top:10px'><span style='color:#ef4444'>● Danger zone (low attendance + low grades)</span> <span style='color:#2563eb; margin-left:10px'>● Other students</span></div></div></div><div class='card'><b>Students Requiring Attention</b><div style='display:flex; gap:8px; justify-content:end'><span style='background:#0f172a; color:white; padding:4px 10px; border-radius:20px; font-size:12px'>All (0)</span><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:12px'>Critical (0)</span></div><div style='height:100px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No chronic absentees found</div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "dashboard", ""))

@app.get("/system-settings", response_class=HTMLResponse)
def system_settings(request: Request, tab: str = "profile"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    sid = request.session.get("school_id",0)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    school = cur.fetchone()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (sid,))
    classes = cur.fetchall()
    cur.execute("SELECT * FROM users WHERE school_id=?", (sid,))
    users = cur.fetchall()
    cur.execute("SELECT * FROM audit_log WHERE school_id=? ORDER BY id DESC LIMIT 20", (sid,))
    audits = cur.fetchall()
    con.close()

    if tab=="profile":
        content = f"""
<div class='card'><b>🏫 School Profile</b><div style='color:#64748b; font-size:12px'>MABALE COMPREHENSIVE SCHOOL (Code: 10069)</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:16px'>
<div><label style='font-size:12px; font-weight:600'>School Name</label><input value='{sname}' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>Motto</label><input value='Elimu ni Ufunguo' placeholder='School Motto' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>Phone</label><input value='07...' placeholder='Phone' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'></div>
<div><label style='font-size:12px; font-weight:600'>School Code</label><input value='10069' readonly style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px; background:#f8fafc'><label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>Email</label><input value='{email}' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>Logo</label><div style='width:100%; height:80px; border:1px dashed #cbd5e1; border-radius:8px; display:flex; align-items:center; justify-content:center; color:#94a3b8; margin-top:4px'>Upload Logo</div></div>
</div>
<div style='margin-top:16px'><button class='btn'>Save Profile</button></div>
</div>
"""
    elif tab=="classes":
        rows = "".join([f"<tr><td>{c['name']}</td><td>{c['stream'] or '-'}</td><td><button class='btn2' style='padding:4px 8px'>Edit</button></td></tr>" for c in classes]) or "<tr><td colspan=3 style='padding:20px; text-align:center; color:#94a3b8'>No classes - Add below<br>Example: GRADE 7, GRADE 8, GRADE 9</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>🏛️ Classes</b><div style='color:#64748b; font-size:12px'>{len(classes)} classes in {sname}</div></div><button class='btn2'>Import Classes</button></div>
<table style='margin-top:12px'><tr><th>Class Name</th><th>Stream</th><th>Action</th></tr>{rows}</table>
<form method='post' action='/system-settings/add-class' style='margin-top:16px; display:flex; gap:8px'><input name='name' placeholder='GRADE 7' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='stream' placeholder='Stream e.g East (optional)' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><button class='btn'>Add Class</button></form>
</div>
"""
    elif tab=="users":
        rows = "".join([f"<tr><td>{u['email']}</td><td>{u['role']}</td><td><span style='background:#dcfce7; color:#16a34a; padding:2px 8px; border-radius:12px; font-size:11px'>Active</span></td></tr>" for u in users]) or "<tr><td colspan=3 style='padding:20px; text-align:center; color:#94a3b8'>No users - Only you</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>👥 User Management</b><div style='color:#64748b; font-size:12px'>{len(users)+1} users - MABALE COMPREHENSIVE SCHOOL</div></div><button class='btn'>Add User</button></div>
<table style='margin-top:12px'><tr><th>Email</th><th>Role</th><th>Status</th></tr><tr><td>{email}</td><td>{role}</td><td>Active</td></tr>{rows}</table>
<div style='margin-top:12px; display:grid; grid-template-columns:1fr 1fr 120px; gap:8px'><input placeholder='New User Email' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><select style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><option>Teacher</option><option>Accountant</option><option>Admin</option></select><button class='btn'>Invite</button></div>
</div>
"""
    elif tab=="roles":
        content = """
<div class='card'><b>🛡️ Roles & Permissions</b><div style='color:#64748b; font-size:12px'>Define what each role can access</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px'>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>School Admin</b><div style='font-size:12px; margin-top:8px; color:#16a34a'>✓ All modules<br>✓ Finance<br>✓ Settings<br>✓ User Management</div></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Teacher</b><div style='font-size:12px; margin-top:8px; color:#64748b'>✓ Mark attendance<br>✓ Record marks<br>✓ View students<br>✗ Finance<br>✗ Settings</div></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px'><b>Accountant</b><div style='font-size:12px; margin-top:8px; color:#64748b'>✓ Finance<br>✓ Fee collection<br>✓ Reports<br>✗ Academic Manager<br>✗ Settings</div></div>
</div>
<div style='margin-top:12px'><button class='btn2'>Edit Permissions</button></div>
</div>
"""
    elif tab=="backup":
        content = """
<div class='card'><b>💾 Database Backup</b><div style='color:#64748b; font-size:12px'>Backup and restore school data</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:12px'>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px; text-align:center'><div style='font-size:32px'>💾</div><b>Backup Now</b><div style='font-size:12px; color:#64748b; margin-top:4px'>Last backup: Never (Fresh system)</div><button class='btn' style='margin-top:10px; width:100%'>Create Backup</button></div>
<div style='border:1px solid #e2e8f0; border-radius:10px; padding:14px; text-align:center'><div style='font-size:32px'>♻️</div><b>Restore</b><div style='font-size:12px; color:#64748b; margin-top:4px'>Upload backup file to restore</div><button class='btn2' style='margin-top:10px; width:100%'>Choose File</button></div>
</div>
<div style='margin-top:12px; font-size:12px; color:#64748b'>Auto-backup: Daily at 11:00 PM | Storage: Local + Cloud (optional)</div>
</div>
"""
    elif tab=="audit":
        rows = "".join([f"<tr><td>{a['time']}</td><td>{a['user']}</td><td>{a['action']}</td></tr>" for a in audits]) or f"<tr><td>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td><td>{email}</td><td>Login - Viewed System Settings</td></tr>"
        content = f"""
<div class='card'><div style='display:flex; justify-content:space-between'><div><b>📈 System Audit</b><div style='color:#64748b; font-size:12px'>Track all user activities - {len(audits)} logs</div></div><div><button class='btn2'>Export Audit</button> <button class='btn2'>Clear Logs</button></div></div>
<table style='margin-top:12px'><tr><th>Time</th><th>User</th><th>Action</th></tr>{rows}</table>
</div>
"""
    elif tab=="integrations":
        content = """
<div class='card'><b>🔌 Integrations - BOTTOM LEFT - Your Special Requirement</b><div style='color:#64748b; font-size:12px'>Bulk SMS + M-Pesa - MABALE COMPREHENSIVE SCHOOL</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:16px'>
<div style='border:2px solid #2563eb; border-radius:12px; padding:16px; background:#eff6ff'><div style='display:flex; justify-content:space-between; align-items:center'><b>📱 Bulk SMS Integration</b><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:11px'>Not Connected</span></div><div style='font-size:12px; color:#64748b; margin-top:8px'>Provider: Africa's Talking / Twilio<br>Use: Fee reminders, Attendance alerts, Exam results</div><div style='margin-top:12px'><label style='font-size:12px; font-weight:600'>API Key</label><input placeholder='AT API Key' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; margin-top:8px; display:block'>Sender ID</label><input placeholder='MABALE SCHOOL' value='MABALE' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><button class='btn' style='margin-top:12px; width:100%'>Connect SMS</button><button class='btn2' style='margin-top:8px; width:100%'>Test SMS</button></div></div>
<div style='border:2px solid #16a34a; border-radius:12px; padding:16px; background:#f0fdf4'><div style='display:flex; justify-content:space-between; align-items:center'><b>💚 M-Pesa Daraja API</b><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:11px'>Not Connected</span></div><div style='font-size:12px; color:#64748b; margin-top:8px'>Provider: Safaricom Daraja<br>Use: Fee payments, Till, Paybill, STK Push</div><div style='margin-top:12px'><label style='font-size:12px; font-weight:600'>Consumer Key</label><input placeholder='M-Pesa Consumer Key' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; margin-top:8px; display:block'>Paybill / Till Number</label><input placeholder='e.g 4001009' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><button class='btn' style='margin-top:12px; width:100%; background:#16a34a'>Connect M-Pesa</button><button class='btn2' style='margin-top:8px; width:100%'>Test STK Push</button></div></div>
</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px'>
<div class='card' style='margin:0'><b>📧 Email Integration</b><div style='font-size:11px; color:#64748b; margin-top:4px'>SMTP for reports<br>Status: Not connected</div></div>
<div class='card' style='margin:0'><b>💬 WhatsApp</b><div style='font-size:11px; color:#64748b; margin-top:4px'>WhatsApp Business API<br>Status: Not connected</div></div>
<div class='card' style='margin:0'><b>📊 Google Sheets</b><div style='font-size:11px; color:#64748b; margin-top:4px'>Export reports<br>Status: Not connected</div></div>
</div>
</div>
"""
    elif tab=="billing":
        content = """
<div class='card'><b>💳 Billing & Payments - DaviSchool Subscription</b><div style='color:#64748b; font-size:12px'>MABALE COMPREHENSIVE SCHOOL (Code: 10069) - Plan & Invoices</div>
<div style='margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:16px'>
<div style='border:2px solid #0f172a; border-radius:12px; padding:16px'><b>Current Plan: Premium</b><div style='font-size:13px; margin-top:8px'>Students: Unlimited<br>Staff: Unlimited<br>Storage: 50GB<br>Support: Priority<br>Price: KES 5,000 / month</div><div style='margin-top:12px'><span style='background:#dcfce7; color:#16a34a; padding:4px 10px; border-radius:20px; font-size:11px'>Active until 30 May 2026</span></div></div>
<div style='border:1px solid #e2e8f0; border-radius:12px; padding:16px'><b>Payment History</b><div style='font-size:12px; margin-top:8px; color:#64748b'>13 May 2026 - KES 5,000 - Paid - M-Pesa<br>13 Apr 2026 - KES 5,000 - Paid<br>13 Mar 2026 - KES 5,000 - Paid</div><button class='btn2' style='margin-top:12px; width:100%'>Download Invoices</button></div>
</div>
<div style='margin-top:12px'><button class='btn'>Upgrade Plan</button> <button class='btn2'>Cancel Subscription</button></div>
</div>
"""
    else:
        content = "<div class='card'>Invalid tab</div>"

    inner = f"""
<div class='content'>
<h1 style='margin:0'>System Settings</h1><p style='color:#64748b; margin:6px 0 14px'>MABALE COMPREHENSIVE SCHOOL (Code: 10069) - Bottom left 8 tabs</p>
<div class='tab-bar'>
<a class='tab-link' href='/system-settings?tab=profile' style='{"background:#0f172a; color:white" if tab=="profile" else "background:#f1f5f9; color:#334155"}'>🏫 School Profile</a>
<a class='tab-link' href='/system-settings?tab=classes' style='{"background:#0f172a; color:white" if tab=="classes" else "background:#f1f5f9; color:#334155"}'>🏛️ Classes</a>
<a class='tab-link' href='/system-settings?tab=users' style='{"background:#0f172a; color:white" if tab=="users" else "background:#f1f5f9; color:#334155"}'>👥 User Management</a>
<a class='tab-link' href='/system-settings?tab=roles' style='{"background:#0f172a; color:white" if tab=="roles" else "background:#f1f5f9; color:#334155"}'>🛡️ Roles & Permissions</a>
<a class='tab-link' href='/system-settings?tab=backup' style='{"background:#0f172a; color:white" if tab=="backup" else "background:#f1f5f9; color:#334155"}'>💾 Database Backup</a>
<a class='tab-link' href='/system-settings?tab=audit' style='{"background:#0f172a; color:white" if tab=="audit" else "background:#f1f5f9; color:#334155"}'>📈 System Audit</a>
<a class='tab-link' href='/system-settings?tab=integrations' style='{"background:#2563eb; color:white; font-weight:700" if tab=="integrations" else "background:#f1f5f9; color:#334155"}'>🔌 Integrations</a>
<a class='tab-link' href='/system-settings?tab=billing' style='{"background:#0f172a; color:white" if tab=="billing" else "background:#f1f5f9; color:#334155"}'>💳 Billing & Payments</a>
</div>
{content}
</div>
"""
    return HTMLResponse(wrap(sname, inner, email, role, "system", tab))

@app.post("/system-settings/add-class")
def add_class(request: Request, name: str = Form(...), stream: str = Form("")):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (request.session.get("school_id",0), name, stream))
    con.commit(); con.close()
    log_action(request.session.get("school_id",0), request.session.get("user_email",""), f"Added class {name}")
    return RedirectResponse("/system-settings?tab=classes", status_code=303)

@app.get("/students", response_class=HTMLResponse)
def students(request: Request, tab: str = "list"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    return HTMLResponse(wrap(sname, f"<div class='content'><h1>Students Manager - {tab}</h1></div>", email, role, "students", ""))

@app.get("/staff", response_class=HTMLResponse)
def staff(request: Request, tab: str = "list"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    return HTMLResponse(wrap(sname, f"<div class='content'><h1>Staff Manager - {tab}</h1></div>", email, role, "staff", ""))

@app.get("/academic-manager", response_class=HTMLResponse)
def acad(request: Request, tab: str = "dean"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    return HTMLResponse(wrap(sname, f"<div class='content'><h1>Academic Manager - {tab}</h1></div>", email, role, "academic", ""))

@app.get("/timetable", response_class=HTMLResponse)
def timetable(request: Request, tab: str = "periods"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    return HTMLResponse(wrap(sname, f"<div class='content'><h1>Timetable - {tab}</h1></div>", email, role, "timetable", ""))

@app.get("/dashboard", response_class=HTMLResponse)
def dash2(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "School Admin" if "940" in email else "Super Admin"
    sname = request.session.get("school_name","MABALE COMPREHENSIVE SCHOOL")
    inner = f"<div class='content'><h1>Dashboard</h1><p>{sname} (Code: 10069)</p><div class='card'><div style='height:160px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No correlation data available for the selected filters</div><div style='margin-top:8px'><span style='color:#ef4444'>● Danger zone (low attendance + low grades)</span> <span style='color:#2563eb; margin-left:8px'>● Other students</span></div></div></div></div>"
    return HTMLResponse(wrap(sname, inner, email, role, "dashboard", ""))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
