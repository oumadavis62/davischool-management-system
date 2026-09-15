from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-final-full-working-2026")
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
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head>
<body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'>
<div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'>
<div style='text-align:center; margin-bottom:24px'>
<div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div>
<h2 style='margin:12px 0 4px; font-size:22px'>Davischool</h2>
<p style='font-size:11px; color:#64748b; margin:0; letter-spacing:1px'>SCHOOL MANAGEMENT SYSTEM</p>
</div>
<form method='post' action='/login'>
<label style='font-size:12px; font-weight:600'>Email</label>
<input name='email' placeholder='Enter email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'>
<label style='font-size:12px; font-weight:600'>Password</label>
<input name='password' type='password' placeholder='Enter password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'>
<button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; font-weight:600'>Sign In</button>
</form>
</div>
</body></html>
"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    con.close()
    if not u:
        return HTMLResponse("Invalid login <a href='/'>Back</a>")
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
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    role_disp = "Super Admin" if is_super else "School Admin"
    add_btn = "<a href='/schools/manage' style='background:#0f172a; color:white; padding:8px 14px; border-radius:8px; text-decoration:none; font-size:12px'>Manage Schools</a>" if is_super else ""
    return HTMLResponse(f"""
<html><body style='font-family:Arial; margin:0; background:#f8fafc'>
<div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'>
<div style='font-weight:700'>{top}</div>
<div style='display:flex; gap:12px; align-items:center; font-size:12px'>
<div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700'>{initials}</div>
<div><div style='font-weight:600'>{name}</div><div style='color:#64748b; font-size:11px'>{role_disp}</div></div>
<a href='/profile?tab=personal' style='border:1px solid #e2e8f0; padding:6px 10px; border-radius:6px; text-decoration:none'>Profile</a>
<a href='/logout' style='color:#dc2626; text-decoration:none'>Logout</a>
</div>
</div>
<div style='padding:24px'>
<h2>School Overview</h2>
<p style='color:#64748b; font-size:13px'>Welcome {name} - {top}</p>
<div style='margin-top:16px'>{add_btn} <a href='/profile?tab=personal' style='border:1px solid #e2e8f0; background:white; padding:8px 14px; border-radius:8px; text-decoration:none; font-size:12px; margin-left:8px'>View Profile (3 Tabs)</a></div>
</div>
</body></html>
""")

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
        sloc = "Platform Owner - Full System Control"
        badge = "Super Admin"
    else:
        top = school["name"] + " (Code: " + school["code"] + ")"
        sname = school["name"]
        scode = school["code"]
        sloc = school["location"]
        badge = "School Admin"
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"

    if tab=="security":
        right = f"""
        <b>Security Settings</b><p style='font-size:11px; color:#64748b'>Manage your password</p>
        <form method='post' action='/update-password'>
        <label style='font-size:12px; display:block; margin-top:14px'>Current Password</label><input name='current_password' type='password' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
        <label style='font-size:12px; display:block; margin-top:12px'>New Password</label><input name='new_password' type='password' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
        <label style='font-size:12px; display:block; margin-top:12px'>Confirm Password</label><input name='confirm_password' type='password' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
        <div style='text-align:right; margin-top:16px'><button type='submit' style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px; cursor:pointer'>Update Password</button></div>
        </form>
        """
    elif tab=="activity":
        right = f"""
        <b>Activity Log</b><p style='font-size:11px; color:#64748b'>Recent activity for {email}</p>
        <div style='border:1px solid #e2e8f0; border-radius:8px; margin-top:12px'>
        <div style='padding:10px; border-bottom:1px solid #f1f5f9; font-size:12px; display:flex; justify-content:space-between'><span>Logged in - {email}</span><span style='color:#64748b'>Today</span></div>
        <div style='padding:10px; border-bottom:1px solid #f1f5f9; font-size:12px; display:flex; justify-content:space-between'><span>Profile viewed - {sname}</span><span style='color:#64748b'>Today</span></div>
        <div style='padding:10px; font-size:12px; display:flex; justify-content:space-between'><span>Password changed</span><span style='color:#64748b'>Yesterday</span></div>
        </div>
        """
    else:
        right = f"""
        <b>Personal Information</b><p style='font-size:11px; color:#64748b'>Update your name, email, and phone number</p>
        <form method='post' action='/update-profile'>
        <label style='font-size:12px; display:block; margin-top:14px'>Full Name</label><input name='full_name' value='{name}' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
        <label style='font-size:12px; display:block; margin-top:12px'>Email Address</label><input name='email_new' value='{email}' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
        <label style='font-size:12px; display:block; margin-top:12px'>Phone Number</label><input name='phone' value='+254748588874' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
        <div style='text-align:right; margin-top:18px'><button type='submit' style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px; cursor:pointer'>Save Changes</button></div>
        </form>
        """

    ap = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="personal" else "color:#64748b"
    ase = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="security" else "color:#64748b"
    aa = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="activity" else "color:#64748b"

    html = f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='margin:0; font-family:Arial; background:#f8fafc'>
<div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between'><div style='font-weight:700'>{top}</div><div><a href='/dashboard'>Dashboard</a> | <a href='/logout'>Logout</a></div></div>
<div style='padding:20px'>
<div style='font-size:18px; font-weight:700'>My Profile</div><div style='font-size:12px; color:#64748b; margin-bottom:14px'>Manage your personal information and security settings</div>
<div style='display:flex; border-bottom:1px solid #e2e8f0; margin-bottom:16px'>
<a href='/profile?tab=personal' style='padding:8px 4px; margin-right:16px; text-decoration:none; font-size:13px; {ap}'>Personal Info</a>
<a href='/profile?tab=security' style='padding:8px 4px; margin-right:16px; text-decoration:none; font-size:13px; {ase}'>Security</a>
<a href='/profile?tab=activity' style='padding:8px 4px; text-decoration:none; font-size:13px; {aa}'>Activity Log</a>
</div>
<div style='display:grid; grid-template-columns:340px 1fr; gap:16px'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px; text-align:center; height:fit-content'>
<div style='width:80px; height:80px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:26px; font-weight:800; margin:0 auto'>{initials}</div>
<div style='font-weight:700; margin-top:12px'>{name}</div>
<div style='margin-top:6px'><span style='background:#e0f2fe; color:#0369a1; padding:4px 10px; border-radius:20px; font-size:11px'>{badge}</span></div>
<div style='margin-top:10px; font-size:12px'>{email}</div>
<div style='margin-top:12px; border-top:1px solid #f1f5f9; padding-top:10px'><div style='font-size:12px; font-weight:600'>{sname}</div><div style='font-size:11px; color:#64748b'>{sloc}</div><div style='font-size:10px; color:#94a3b8'>Code: {scode}</div></div>
</div>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px'>{right}</div>
</div>
</div>
</body></html>
"""
    return HTMLResponse(html)

@app.post("/update-password")
def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if "email" not in request.session:
        return RedirectResponse("/")
    if new_password!= confirm_password:
        return HTMLResponse("<h3>Error: New passwords do not match</h3><a href='/profile?tab=security'>Back</a>")
    email = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_password))
    u = cur.fetchone()
    if not u:
        con.close()
        return HTMLResponse("<h3>Error: Current password is incorrect</h3><a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_password, email))
    con.commit()
    con.close()
    return HTMLResponse("<h3>Password Updated Successfully!</h3><p>Your password has been changed.</p><a href='/profile?tab=security'>Back to Security</a> | <a href='/logout'>Login again</a>")

@app.post("/update-profile")
def update_profile(request: Request, full_name: str = Form(...), email_new: str = Form(...), phone: str = Form(...)):
    if "email" not in request.session:
        return RedirectResponse("/")
    old_email = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE users SET full_name=?, email=? WHERE email=?", (full_name.strip(), email_new.strip(), old_email))
    con.commit()
    con.close()
    request.session["email"] = email_new.strip()
    request.session["name"] = full_name.strip()
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools")
    schools = cur.fetchall()
    con.close()
    rows = ""
    for s in schools:
        rows += f"<tr><td style='padding:8px; border-bottom:1px solid #eee; font-size:12px'>{s['name']}</td><td style='padding:8px; border-bottom:1px solid #eee; font-size:12px'>{s['code']}</td><td style='padding:8px; border-bottom:1px solid #eee; font-size:12px'>{s['email']}</td><td style='padding:8px; border-bottom:1px solid #eee; font-size:12px'>{s['location']}</td></tr>"
    if not rows:
        rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999; font-size:12px'>No schools yet</td></tr>"
    return HTMLResponse(f"""
<html><body style='font-family:Arial; background:#f8fafc; margin:0'>
<div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between'><b>Davischool Platform - Schools Management (Super Admin Only)</b><div><a href='/dashboard'>Dashboard</a></div></div>
<div style='padding:20px; display:grid; grid-template-columns:1fr 360px; gap:16px'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><b>Registered Schools</b><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; text-align:left'><th style='padding:8px'>Name</th><th style='padding:8px'>Code</th><th style='padding:8px'>Email</th><th style='padding:8px'>Location</th></tr>{rows}</table></div>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><b>Add New School</b>
<form method='post' action='/register-school' style='margin-top:12px'>
<input name='school_name' placeholder='School Name' required style='width:100%; padding:10px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'>
<input name='school_email' placeholder='Admin Email' required style='width:100%; padding:10px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'>
<input name='location' placeholder='Location' required style='width:100%; padding:10px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'>
<button style='width:100%; background:#0f172a; color:white; padding:10px; border:none; border-radius:8px; margin-top:8px'>Create School</button>
</form></div>
</div>
</body></html>
""")

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
    return HTMLResponse(f"<h3>School {school_name} Code {code} Created</h3><p>Login: {school_email} / School@2026!</p><a href='/schools/manage'>Back</a>")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
