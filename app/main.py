from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-personal-info-final")
SUPER_ADMIN_EMAIL = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, school_id INTEGER, role TEXT, full_name TEXT, phone TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role, full_name, phone, school_id) VALUES (?,?,?,?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin", "Davis Ouma", "+254748588874", 0))
    con.commit()
    con.close()
init_db()

def wrap(sname, inner, email, role):
    html = """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{box-sizing:border-box} body{margin:0; font-family:Arial; background:#f8fafc; display:flex}
.sidebar{width:270px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed}
.logo{padding:16px; border-bottom:1px solid #e2e8f0; display:flex; gap:10px; align-items:center}
.logo-icon{width:32px; height:32px; background:#0f172a; color:white; border-radius:6px; display:flex; align-items:center; justify-content:center; font-weight:800}
.nav-item{display:block; padding:10px 14px; margin:2px 10px; border-radius:8px; text-decoration:none; font-size:13px; color:#334155}
.nav-item.active{background:#0f172a; color:white}
.main{margin-left:270px; flex:1}
.topbar{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; position:sticky; top:0}
.content{padding:24px}
.card{background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px}
.input{width:100%; padding:12px 12px 12px 38px; border:1px solid #e2e8f0; border-radius:10px; background:#f8fafc; font-size:14px; margin-top:6px}
.label{font-size:13px; font-weight:600; color:#1e293b; margin-top:16px; display:block}
.btn-dark{background:#0f172a; color:white; border:none; padding:12px 20px; border-radius:10px; font-weight:600; cursor:pointer}
.badge{background:#e0f2fe; color:#0369a1; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>E</div><div><b>Elimikasasa</b><div style='font-size:8px; color:#64748b'>SCHOOL MANAGEMENT SYSTEM</div></div></div>
<a class='nav-item' href='/dashboard'>Dashboard</a>
<a class='nav-item active'>👤 My Profile</a>
<div style='padding:14px; border-top:1px solid #e2e8f0; margin-top:20px'><b>Davis Ouma</b><br><small>""" + email + """</small><br><small style='color:#2563eb'>""" + role + """</small></div>
</div>
<div class='main'><div class='topbar'><div style='font-weight:700'>""" + sname + """</div><div>DO Davis Ouma - """ + role + """</div></div>
""" + inner + """
</div></body></html>
"""
    return html

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:400px'><h2>DaviSchool Login</h2><p style='font-size:12px; color:#64748b'>Super Admin: oumadavis62@gmail.com<br>Demo School: Use registered school email</p><form method='post' action='/login'><input name='email' required placeholder='Email' style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'><input name='password' type='password' required placeholder='Password' style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:8px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Sign In</button></form></div></body></html>")

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    u = cur.fetchone()
    school_name_display = "DaviSchool Super Admin Platform"
    school_location = "Nairobi, Kenya"
    school_code = "ADMIN"

    if u and u["school_id"]:
        cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],))
        sch = cur.fetchone()
        if sch:
            school_name_display = f"{sch['name']} (Code: {sch['code']})"
            school_location = sch["location"]
            school_code = sch["code"]
    con.close()

    if not u:
        return HTMLResponse("Invalid login <a href='/'>Back</a>")

    request.session["user_email"] = email
    request.session["school_id"] = u["school_id"] or 0
    request.session["school_name_full"] = school_name_display
    request.session["school_location"] = school_location
    request.session["school_code"] = school_code
    request.session["school_name_simple"] = school_name_display.split(" (")[0] if "(" in school_name_display else school_name_display
    request.session["role"] = u["role"]
    request.session["full_name"] = u["full_name"] or "Davis Ouma"
    request.session["phone"] = u["phone"] or "+254748588874"

    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "user_email" not in request.session:
        return RedirectResponse("/")

    email = request.session.get("user_email")
    role = request.session.get("role")
    full_name = request.session.get("full_name","Davis Ouma")
    phone = request.session.get("phone","+254748588874")

    # DYNAMIC SCHOOL NAME - NO HARDCODED MABALE
    if role == "super_admin":
        sname_top = "DaviSchool Super Admin Platform"
        sname_left = "DaviSchool Platform"
        location_left = "Nairobi, Kenya - Platform Owner"
        role_badge = "Super Admin"
        badge_style = "background:#0f172a; color:white"
        email_display = SUPER_ADMIN_EMAIL
    else:
        # For school admins, show THEIR school (MABALE in screenshot is just example of how it looks for them)
        sname_top = request.session.get("school_name_full","MABALE COMPREHENSIVE SCHOOL (Code: 10069)")
        sname_left = request.session.get("school_name_simple","MABALE COMPREHENSIVE SCHOOL")
        location_left = request.session.get("school_location","Busia,BUSIA")
        role_badge = "School Admin"
        badge_style = "background:#e0f2fe; color:#0369a1"
        email_display = email

    # EXACT UI FROM YOUR SCREENSHOT - Personal Info tab
    if tab == "personal":
        inner = f"""
<div class='content'>
<div style='font-weight:800; font-size:16px; margin-bottom:20px; letter-spacing:0.3px'>{sname_top}</div>

<div style='display:grid; grid-template-columns:360px 1fr; gap:20px'>
<!-- LEFT CARD - EXACT LIKE SCREENSHOT -->
<div class='card' style='text-align:center; height:fit-content; padding:32px 24px'>
<div style='width:100px; height:100px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:36px; font-weight:800; margin:0 auto; position:relative'>DO
<div style='position:absolute; bottom:0; right:0; background:white; border-radius:50%; width:32px; height:32px; display:flex; align-items:center; justify-content:center; border:2px solid #e2e8f0; font-size:16px'>📷</div>
</div>
<div style='font-weight:700; font-size:18px; margin-top:20px'>{full_name}</div>
<div style='margin-top:8px'><span class='badge' style='{badge_style}'>{role_badge}</span></div>
<div style='margin-top:20px; display:flex; align-items:center; justify-content:center; gap:6px; font-size:14px; color:#64748b'><span>✉️</span> {email_display}</div>
<div style='margin-top:24px; border-top:1px solid #e2e8f0; padding-top:20px'>
<div style='font-size:13px; font-weight:500; color:#475569; letter-spacing:0.5px'>{sname_left}</div>
<div style='font-size:13px; color:#94a3b8; margin-top:4px'>{location_left}</div>
</div>
</div>

<!-- RIGHT CARD - Personal Information - EXACT LIKE SCREENSHOT -->
<div class='card' style='padding:28px'>
<div style='font-weight:700; font-size:16px'>Personal Information</div>
<div style='font-size:13px; color:#64748b; margin-top:4px'>Update your name, email, and phone number</div>

<form method='post' action='/profile/update' style='margin-top:24px'>
<label class='label'>Full Name</label>
<div style='position:relative'><span style='position:absolute; left:12px; top:17px; color:#94a3b8; font-size:14px'>👤</span><input name='full_name' value='{full_name}' class='input'></div>

<label class='label'>Email Address</label>
<div style='position:relative'><span style='position:absolute; left:12px; top:17px; color:#94a3b8; font-size:14px'>✉️</span><input name='email' value='{email_display}' class='input'></div>

<label class='label'>Phone Number</label>
<div style='position:relative'><span style='position:absolute; left:12px; top:17px; color:#94a3b8; font-size:14px'>📞</span><input name='phone' value='{phone}' class='input'></div>

<div style='margin-top:32px; display:flex; justify-content:flex-end'><button type='submit' class='btn-dark'>Save Changes</button></div>
</form>
</div>
</div>
</div>
"""
    else:
        inner = f"<div class='content'><h3>{tab}</h3><p>Other tabs: Security, Activity Log</p><a href='/profile?tab=personal'>Back to Personal Info</a></div>"

    role_display = "Super Admin" if role=="super_admin" else "School Admin"
    top_name = "DaviSchool Super Admin Platform" if role=="super_admin" else sname_top

    return HTMLResponse(wrap(top_name, inner, email, role_display))

@app.post("/profile/update")
def update_profile(request: Request, full_name: str = Form(...), email: str = Form(...), phone: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET full_name=?, phone=? WHERE email=?", (full_name, phone, request.session.get("user_email")))
    con.commit(); con.close()
    request.session["full_name"] = full_name
    request.session["phone"] = phone
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    return RedirectResponse("/profile?tab=personal")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
