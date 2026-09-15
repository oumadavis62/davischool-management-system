from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="clean-final-2026")
SUPER_ADMIN = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit()
    con.close()

init_db()

def get_school(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin":
        return None
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    s = cur.fetchone()
    con.close()
    return s

@app.get("/", response_class=HTMLResponse)
def home():
    return """
<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc'>
<div style='background:white; padding:24px; border-radius:12px; border:1px solid #e2e8f0; width:420px'>
<h3>Davischool - Clean Deploy</h3>
<form method='post' action='/login'>
<input name='email' value='oumadavis62@gmail.com' style='width:100%; padding:10px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'>
<input name='password' type='password' value='DaviSchool@2026!' style='width:100%; padding:10px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'>
<button style='width:100%; background:#0f172a; color:white; padding:10px; border:none; border-radius:8px'>Sign In Super Admin</button>
</form>
<hr style='margin:16px 0'>
<b style='font-size:12px'>Register New School (Dynamic - No Mabale):</b>
<form method='post' action='/register-school' style='margin-top:8px'>
<input name='school_name' placeholder='School Name' required style='width:100%; padding:8px; margin:4px 0; border:1px solid #e2e8f0; border-radius:6px'>
<input name='school_email' placeholder='Admin Email' required style='width:100%; padding:8px; margin:4px 0; border:1px solid #e2e8f0; border-radius:6px'>
<input name='location' placeholder='Location' required style='width:100%; padding:8px; margin:4px 0; border:1px solid #e2e8f0; border-radius:6px'>
<button style='width:100%; background:#16a34a; color:white; padding:8px; border:none; border-radius:6px; margin-top:4px'>Register</button>
</form>
</div></body></html>
"""

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...)):
    code = str(random.randint(10000,99999))
    con = get_db()
    cur = con.cursor()
    cur.execute("INSERT INTO schools (name,email,code,location) VALUES (?,?,?,?)", (school_name.strip().upper(), school_email.strip(), code, location.strip()))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (school_email.strip(), "School@2026!", "school_admin", "School Admin", sid))
    con.commit()
    con.close()
    return HTMLResponse(f"<h3>School Registered: {school_name} Code {code}</h3><p>Email {school_email} Pass School@2026!</p><a href='/'>Login</a>")

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    con.close()
    if not u:
        return HTMLResponse("Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]
    request.session["role"]=u["role"]
    request.session["name"]=u["full_name"]
    request.session["school_id"]=u["school_id"] or 0
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    school = get_school(request)
    is_super = school is None
    if is_super:
        top = "Davischool Platform (Super Admin)"
    else:
        top = school["name"] + " (Code: " + school["code"] + ")"
    name = request.session.get("name","")
    return HTMLResponse(f"<html><body style='font-family:Arial'><div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px; display:flex; justify-content:space-between'><b>{top}</b><div><a href='/profile?tab=personal'>Profile</a> | <a href='/logout'>Logout</a></div></div><div style='padding:20px'><h2>Dashboard</h2><p>Welcome {name}</p><p>Top: {top} - Dynamic per school</p><a href='/profile?tab=personal' style='background:#0f172a; color:white; padding:10px 16px; border-radius:8px; text-decoration:none'>Go to Profile with 3 Tabs</a></div></body></html>")

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
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
        sloc = "Platform Owner - Full Control"
        badge = "Super Admin"
    else:
        top = school["name"] + " (Code: " + school["code"] + ")"
        sname = school["name"]
        scode = school["code"]
        sloc = school["location"]
        badge = "School Admin"

    initials = ""
    parts = name.split()
    for p in parts[:2]:
        if p:
            initials += p[0].upper()

    if tab=="security":
        right = """
        <b>Security Settings</b><p style='font-size:11px; color:#64748b'>Manage password</p>
        <label style='font-size:12px; display:block; margin-top:12px'>Current Password</label><input type='password' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
        <label style='font-size:12px; display:block; margin-top:12px'>New Password</label><input type='password' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
        <label style='font-size:12px; display:block; margin-top:12px'>Confirm New Password</label><input type='password' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
        <div style='text-align:right; margin-top:16px'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px'>Update Password</button></div>
        """
    elif tab=="activity":
        right = f"""
        <b>Activity Log</b><p style='font-size:11px; color:#64748b'>Recent activity for {email}</p>
        <div style='border:1px solid #e2e8f0; border-radius:8px; margin-top:12px'>
        <div style='padding:10px; border-bottom:1px solid #f1f5f9; font-size:12px; display:flex; justify-content:space-between'><span>Logged in</span><span style='color:#64748b'>Today</span></div>
        <div style='padding:10px; border-bottom:1px solid #f1f5f9; font-size:12px; display:flex; justify-content:space-between'><span>Viewed profile - {sname}</span><span style='color:#64748b'>Today</span></div>
        <div style='padding:10px; font-size:12px; display:flex; justify-content:space-between'><span>Password changed</span><span style='color:#64748b'>Yesterday</span></div>
        </div>
        """
    else:
        right = f"""
        <b>Personal Information</b><p style='font-size:11px; color:#64748b'>Update your name, email, and phone number</p>
        <label style='font-size:12px; display:block; margin-top:14px'>Full Name</label><input value='{name}' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
        <label style='font-size:12px; display:block; margin-top:12px'>Email Address</label><input value='{email}' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
        <label style='font-size:12px; display:block; margin-top:12px'>Phone Number</label><input value='+254748588874' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
        <div style='text-align:right; margin-top:18px'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px'>Save Changes</button></div>
        """

    active_personal = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="personal" else "color:#64748b"
    active_security = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="security" else "color:#64748b"
    active_activity = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="activity" else "color:#64748b"

    html = f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
body{{margin:0; font-family:Arial; background:#f8fafc}}
.top{{background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between}}
.content{{padding:20px}}
.card{{background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px}}
.grid{{display:grid; grid-template-columns:340px 1fr; gap:16px}}
.big{{width:80px; height:80px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:26px; font-weight:800; margin:0 auto}}
.tab{{padding:8px 4px; margin-right:16px; text-decoration:none; font-size:13px; border-bottom:2px solid transparent}}
</style></head><body>
<div class='top'><div style='font-weight:700'>{top}</div><div><a href='/dashboard'>Dashboard</a> | <a href='/logout'>Logout</a></div></div>
<div class='content'>
<div style='font-size:18px; font-weight:700'>My Profile</div><div style='font-size:12px; color:#64748b; margin-bottom:12px'>Manage your personal information and security settings</div>
<div style='display:flex; border-bottom:1px solid #e2e8f0; margin-bottom:16px'>
<a href='/profile?tab=personal' class='tab' style='{active_personal}'>Personal Info</a>
<a href='/profile?tab=security' class='tab' style='{active_security}'>Security</a>
<a href='/profile?tab=activity' class='tab' style='{active_activity}'>Activity Log</a>
</div>
<div class='grid'>
<div class='card' style='text-align:center; height:fit-content'>
<div class='big'>{initials}</div>
<div style='font-weight:700; margin-top:12px'>{name}</div>
<div style='margin-top:6px'><span style='background:#e0f2fe; color:#0369a1; padding:4px 10px; border-radius:20px; font-size:11px'>{badge}</span></div>
<div style='margin-top:10px; font-size:12px'>{email}</div>
<div style='margin-top:12px; border-top:1px solid #f1f5f9; padding-top:10px'><div style='font-size:12px; font-weight:600'>{sname}</div><div style='font-size:11px; color:#64748b'>{sloc}</div><div style='font-size:10px; color:#94a3b8'>Code: {scode}</div></div>
</div>
<div class='card'>{right}</div>
</div>
</div>
</body></html>
"""
    return HTMLResponse(html)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
