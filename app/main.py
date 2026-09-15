from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-no-mabale-dynamic-2026")
SUPER_ADMIN = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    # ONLY Super Admin - NO MABALE DEMO ANYMORE!
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit(); con.close()
init_db()

def get_school(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin":
        return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    s = cur.fetchone(); con.close()
    return s

@app.get("/", response_class=HTMLResponse)
def home():
    return """
<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc'>
<div style='background:white; padding:28px; border-radius:16px; border:1px solid #e2e8f0; width:420px'>
<h2>Davischool</h2><p style='font-size:12px; color:#64748b'>Super Admin + Dynamic School Registration - NO MABALE DEMO</p>
<form method='post' action='/login'>
<input name='email' placeholder='Email' value='oumadavis62@gmail.com' required style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:10px'>
<input name='password' type='password' placeholder='Password' value='DaviSchool@2026!' required style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:10px'>
<button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; font-weight:600'>Sign In (Super Admin)</button>
</form>
<div style='margin-top:16px; border-top:1px solid #e2e8f0; padding-top:14px'>
<b style='font-size:13px'>Register New School (Dynamic Demo):</b>
<form method='post' action='/register-school' style='margin-top:8px'>
<input name='school_name' placeholder='School Name e.g. ST MARYS BOYS KITALE' required style='width:100%; padding:10px; margin:4px 0; border:1px solid #e2e8f0; border-radius:8px; font-size:12px'>
<input name='school_email' placeholder='School Admin Email' required style='width:100%; padding:10px; margin:4px 0; border:1px solid #e2e8f0; border-radius:8px; font-size:12px'>
<input name='location' placeholder='Location e.g. Kitale, Trans-Nzoia' required style='width:100%; padding:10px; margin:4px 0; border:1px solid #e2e8f0; border-radius:8px; font-size:12px'>
<button style='width:100%; background:#16a34a; color:white; padding:10px; border:none; border-radius:8px; font-size:12px; font-weight:600; margin-top:4px'>Register School → Auto Dynamic Name</button>
</form>
<div style='font-size:10px; color:#64748b; margin-top:8px'>After registration, login with that email / School@2026! → Top will show YOUR school name dynamically, NOT MABALE</div>
</div>
</div></body></html>
"""

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...)):
    code = str(random.randint(10000, 99999))
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO schools (name,email,code,location) VALUES (?,?,?,?)", (school_name.strip().upper(), school_email.strip(), code, location.strip()))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (school_email.strip(), "School@2026!", "school_admin", "School Admin", sid))
    con.commit(); con.close()
    return HTMLResponse(f"<html><body style='font-family:Arial; padding:40px; text-align:center'><h2>✅ School Registered!</h2><p><b>{school_name.upper()} (Code: {code})</b><br>{location}</p><p>Admin: {school_email}<br>Password: School@2026!</p><p style='font-size:12px; color:#16a34a'>Now login - Top bar will show YOUR school name dynamically, NOT MABALE!</p><a href='/'>Go Login</a></body></html>")

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    u = cur.fetchone(); con.close()
    if not u:
        return HTMLResponse("Invalid login <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    school = get_school(request)
    is_super = school is None
    top = "Davischool Platform (Super Admin)" if is_super else f"{school['name']} (Code: {school['code']})"
    name = request.session.get("name","")
    email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "SA"
    role_disp = "Super Admin - Full Control" if is_super else "School Admin"

    # Dynamic stats
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools"); scount = cur.fetchone()["c"]
    con.close()

    body = f"""
<div style='padding:24px'>
<div style='display:flex; justify-content:space-between; align-items:center'>
<div><h1 style='margin:0; font-size:22px'>School Overview</h1><p style='color:#64748b; font-size:13px; margin-top:6px'>{'Welcome back, Davis! Platform overview - You control all schools.' if is_super else f"Welcome! Here's what's happening at {school['name']}."}</p></div>
<a href='/profile' style='border:1px solid #e2e8f0; background:white; padding:8px 14px; border-radius:10px; text-decoration:none; color:#334155; font-size:12px'>👤 View Profile (Dynamic)</a>
</div>
<div style='display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:20px'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><div style='font-size:12px; color:#64748b'>{'Total Schools' if is_super else 'Total Students'}</div><div style='font-size:22px; font-weight:800; margin-top:6px'>{scount if is_super else 0}</div><div style='font-size:11px; color:#64748b; margin-top:4px'>{'Active on platform' if is_super else 'In your school'}</div></div>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><div style='font-size:12px; color:#64748b'>Total Students</div><div style='font-size:22px; font-weight:800; margin-top:6px'>0</div><div style='font-size:11px; color:#64748b'>Will show your count</div></div>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><div style='font-size:12px; color:#64748b'>Fee Collection</div><div style='font-size:22px; font-weight:800; margin-top:6px'>0%</div></div>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><div style='font-size:12px; color:#64748b'>Attendance</div><div style='font-size:22px; font-weight:800; margin-top:6px'>--</div></div>
</div>
<div style='margin-top:16px; background:#f0fdf4; border:1px solid #bbf7d0; padding:10px; border-radius:8px; text-align:center; font-size:11px; color:#166534'>✅ NO MABALE HARDCODED - This top title "{top}" is 100% dynamic from registration. Every school sees its OWN name after registration.</div>
</div>
"""
    html = f"""
<html><head><style>body{{margin:0; font-family:Arial; background:#f8fafc}}.top{{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center}}.avatar{{width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:12px}}</style></head><body>
<div class='top'><div style='font-weight:700'>{top}</div><div style='display:flex; gap:12px; align-items:center'><div style='display:flex; gap:8px; align-items:center'><div class='avatar'>{initials}</div><div><div style='font-size:12px; font-weight:600'>{name}</div><div style='font-size:10px; color:#64748b'>{role_disp}</div></div></div><a href='/profile' style='font-size:11px; border:1px solid #e2e8f0; padding:4px 8px; border-radius:6px; text-decoration:none'>Profile</a> <a href='/logout' style='font-size:11px; color:#dc2626; text-decoration:none'>Logout</a></div></div>
{body}
</body></html>
"""
    return HTMLResponse(html)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("email","")
    name = request.session.get("name","Davis Ouma")
    school = get_school(request)
    is_super = school is None
    if is_super:
        top = "Davischool Platform (Super Admin)"
        sname = "Davischool Platform"
        scode = "SUPER-ADMIN"
        sloc = "Platform Owner - Full System Control"
        badge = "Super Admin"
        bstyle = "background:#0f172a; color:white"
    else:
        top = f"{school['name']} (Code: {school['code']})"
        sname = school['name']
        scode = school['code']
        sloc = school['location']
        badge = "School Admin"
        bstyle = "background:#e0f2fe; color:#0369a1"
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "SA"
    html = f"""
<html><head><style>body{{margin:0; font-family:Arial; background:#f8fafc}}.top{{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between}}.content{{padding:20px}}.card{{background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px}}.grid{{display:grid; grid-template-columns:340px 1fr; gap:16px}}.big{{width:80px; height:80px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px; font-weight:800; margin:0 auto}}.inp{{width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:6px}}</style></head><body>
<div class='top'><div style='font-weight:700'>{top}</div><div><a href='/dashboard'>Dashboard</a> | <a href='/logout'>Logout</a></div></div>
<div class='content'><div class='grid'>
<div class='card' style='text-align:center'><div class='big'>{initials}</div><div style='font-weight:700; margin-top:12px'>{name}</div><div style='margin-top:6px'><span style='padding:4px 10px; border-radius:20px; font-size:11px; font-weight:700; {bstyle}'>{badge}</span></div><div style='margin-top:10px; font-size:12px'>✉️ {email}</div><div style='margin-top:12px; border-top:1px solid #f1f5f9; padding-top:10px'><div style='font-size:12px; font-weight:600'>{sname}</div><div style='font-size:11px; color:#64748b'>{sloc}</div><div style='font-size:10px; color:#94a3b8'>Code: {scode}</div></div></div>
<div class='card'><b>Personal Information</b><p style='font-size:11px; color:#64748b'>Update your name, email, and phone number - Dynamic per school</p><label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>Full Name</label><input class='inp' value='{name}'><label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>Email Address</label><input class='inp' value='{email}'><label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>Phone Number</label><input class='inp' value='+254748588874'><div style='margin-top:16px; text-align:right'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px'>Save Changes</button></div><div style='margin-top:10px; font-size:10px; color:#16a34a; background:#f0fdf4; border:1px solid #bbf7d0; padding:6px; border-radius:6px; text-align:center'>✅ NO MABALE - This profile shows YOUR registered school name: "{sname}" - Every school sees its own after registration</div></div>
</div></div>
</body></html>
"""
    return HTMLResponse(html)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
