from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random, json, smtplib, ssl, string
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage
import os

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v21-unique-pass")
SUPER_ADMIN = "oumadavis62@gmail.com"

EMAIL_SENDER = SUPER_ADMIN
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
    try: cur.execute("ALTER TABLE schools ADD COLUMN phone TEXT")
    except: pass
    try: cur.execute("ALTER TABLE schools ADD COLUMN principal TEXT")
    except: pass
    try: cur.execute("ALTER TABLE schools ADD COLUMN school_type TEXT")
    except: pass
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit()
    con.close()
init_db()

def generate_unique_password(school_name):
    # Creates unique password like DEMO@4829! or STTHO@1937!
    prefix = "".join([c for c in school_name.upper() if c.isalpha()])[:4]
    if len(prefix) < 3:
        prefix = "SCH"
    num = random.randint(1000, 9999)
    suffix = random.choice(["!", "@", "#"])
    return f"{prefix}@{num}{suffix}"

def send_email(to_email, subject, body):
    if not EMAIL_PASSWORD:
        return False
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        msg.add_alternative(f"<div style='font-family:Arial; padding:20px'><h3>{subject}</h3><div style='background:#f8fafc; border:1px solid #e2e8f0; padding:16px; border-radius:8px; white-space:pre-wrap'>{body}</div><p style='font-size:11px; color:#64748b'>🏫 Davischool - {datetime.now(ZoneInfo('Africa/Nairobi')).strftime('%Y-%m-%d %I:%M %p')} EAT</p></div>", subtype="html")
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except:
        return False

def log_activity(email, action, details=""):
    try:
        con = get_db()
        cur = con.cursor()
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO activity_log (email, action, details, timestamp) VALUES (?,?,?,?)", (email, action, details, ts))
        con.commit()
        con.close()
    except:
        pass

def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin":
        return None
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    s = cur.fetchone()
    con.close()
    return s

def header_html(initials, name, email):
    return f"""
    <style>
.do-avatar {{ width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; cursor:pointer; border:2px solid #e2e8f0; user-select:none; -webkit-user-select:none; caret-color:transparent; outline:none; }}
.dropdown-item {{ display:flex; align-items:center; gap:10px; padding:11px 14px; text-decoration:none; font-size:13px; transition:0.2s; cursor:pointer; }}
.dropdown-item-profile {{ color:#0f172a; border-bottom:1px solid #f8fafc; }}
.dropdown-item-profile:hover {{ background:#0f172a; color:white; }}
.dropdown-item-logout {{ color:#dc2626; }}
.dropdown-item-logout:hover {{ background:#0f172a; color:white; }}
    </style>
    <div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; position:relative'>
        <div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px; color:#64748b'>{name} • Super Admin</div></div>
        <div style='position:relative'>
            <div onclick='toggleProfileMenu()' class='do-avatar' tabindex='-1'>{initials}</div>
            <div id='profileDropdown' style='display:none; position:absolute; right:0; top:44px; background:white; border:1px solid #e2e8f0; border-radius:12px; width:220px; box-shadow:0 10px 25px rgba(0,0,0,0.12); z-index:1000; overflow:hidden'>
                <div style='padding:14px; border-bottom:1px solid #f1f5f9; background:#f8fafc'><div style='font-weight:700; font-size:13px'>{name}</div><div style='font-size:11px; color:#64748b'>{email}</div><div style='margin-top:6px'><span style='background:#e0f2fe; color:#0369a1; padding:3px 8px; border-radius:20px; font-size:10px'>Super Admin</span></div></div>
                <a href='/profile?tab=personal' class='dropdown-item dropdown-item-profile'>👤 Profile</a>
                <a href='/logout' class='dropdown-item dropdown-item-logout'>🚪 Logout</a>
            </div>
        </div>
    </div>
    <script>
    function toggleProfileMenu(){{ let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none'; }}
    document.addEventListener('click', function(e){{ let b=e.target.closest('.do-avatar'); let menu=document.getElementById('profileDropdown'); if(!b && menu &&!menu.contains(e.target)){{ menu.style.display='none'; }} }});
    </script>
    """

@app.get("/health")
def health():
    return PlainTextResponse("OK")

@app.get("/ping")
def ping():
    return PlainTextResponse("pong")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2><p style='font-size:11px; color:#64748b'>ONE LOGIN FOR ALL ROLES 🔐</p></div><form method='post' action='/login'><input name='email' placeholder='📧 Email (super admin or school)' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='🔑 Password (unique per school)' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In → Auto Redirect by Role</button></form><div style='margin-top:16px; font-size:10px; color:#94a3b8; text-align:center'>Super admin → 📊 Dashboard<br>School → 🏫 School Portal<br>Same window, smart redirect!</div></div></body></html>"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    school_info = None
    if u:
        cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],))
        school_info = cur.fetchone()
    con.close()
    if not u:
        return HTMLResponse("❌ Invalid email or password <a href='/'>Back</a>")
    request.session["email"]=u["email"]
    request.session["role"]=u["role"]
    request.session["name"]=u["full_name"]
    request.session["school_id"]=u["school_id"] or 0
    if u["role"]!= "super_admin" and school_info:
        time_now = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%b %d, %Y %I:%M %p EAT")
        send_email(SUPER_ADMIN, f"🏫 Login: {school_info['name']}", f"🏫 {school_info['name']} logged in at {time_now}")
        log_activity(u["email"], f"🏫 School login: {school_info['name']}", f"{u['full_name']} logged in")
        return RedirectResponse("/school/dashboard", status_code=303)
    else:
        log_activity(u["email"], "🔓 Super Admin Logged in", f"{u['email']}")
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    if request.session.get("role") == "school_admin":
        return RedirectResponse("/school/dashboard")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools")
    total = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5")
    recent = cur.fetchall()
    con.close()
    name = request.session.get("name","Davis Ouma")
    email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    log_activity(email, "📊 Viewed dashboard", "School Overview")
    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
    if not rows:
        rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
    content = f"""
    <style>.quick-btn{{display:block; background:white; border:1px solid #e2e8f0; color:#0f172a; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600; transition:0.2s;}}.quick-btn:hover{{background:#0f172a; color:white;}}.quick-btn-light{{display:block; background:white; border:1px solid #e2e8f0; color:#64748b; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600; transition:0.2s;}}.quick-btn-light:hover{{background:#0f172a; color:white; border-color:#0f172a;}}</style>
    <div style='padding:24px'><div style='margin-bottom:20px'><h2 style='margin:0; font-size:22px; font-weight:800'>📊 School Overview</h2><p style='color:#64748b; font-size:13px'>Welcome {name}</p></div>
    <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div><div style='font-size:11px; color:#16a34a; margin-top:6px'>📈 Up 12% from last month</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div><div style='font-size:11px; color:#16a34a; margin-top:6px'>🟢 100% operational</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>💰 TOTAL REVENUE</div><div style='font-size:28px; font-weight:800; margin-top:8px'>KES {total*15000:,}</div><div style='font-size:11px; color:#16a34a; margin-top:6px'>💹 +8% monthly growth</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total*350:,}</div><div style='font-size:11px; color:#64748b; margin-top:6px'>👥 Avg 350 per school</div></div>
    </div>
    <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>🏫 Recently Added Schools</b><a href='/schools/manage' style='font-size:12px; color:#2563eb; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Location</th><th style='padding:10px; text-align:left'>Status</th><th style='padding:10px; text-align:left'>Date</th></tr>{rows}</table></div>
    <div style='display:flex; flex-direction:column; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><b>⚡ Quick Actions</b><div style='margin-top:12px; display:flex; flex-direction:column; gap:8px'><a href='/schools/manage' class='quick-btn'>🏫 Manage Schools</a><a href='/schools/manage?show=add' class='quick-btn-light'>➕ Register New School</a></div></div>
    <div style='background:#0f172a; border-radius:14px; padding:18px; color:white'><div style='font-size:13px; font-weight:700'>📊 Davischool Analytics</div><div style='font-size:11px; color:#94a3b8; margin-top:6px'>🛠️ All {total} schools are active</div><div style='margin-top:12px; background:#1e293b; border-radius:8px; padding:10px'><div style='font-size:10px; color:#94a3b8'>🔧 PLATFORM HEALTH</div><div style='font-size:18px; font-weight:700; color:#4ade80; margin-top:4px'>✅ 99.9% Uptime</div><div style='font-size:10px; color:#64748b; margin-top:4px'>⚡ System running smoothly</div></div></div></div></div></div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; margin:0; background:#f8fafc'>{header_html(initials, name, email)}{content}</body></html>")

@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin":
        return RedirectResponse("/")
    school_obj = get_school_obj(request)
    if not school_obj:
        return RedirectResponse("/")
    name = request.session.get("name","")
    email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    header = f"""
    <style>.do-avatar{{width:36px; height:36px; background:#dcfce7; color:#166534; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; cursor:pointer; border:2px solid #e2e8f0; user-select:none; caret-color:transparent;}}.dropdown-item{{display:flex; align-items:center; gap:10px; padding:11px 14px; text-decoration:none; font-size:13px; transition:0.2s;}}.dropdown-item-profile{{color:#0f172a; border-bottom:1px solid #f8fafc;}}.dropdown-item-profile:hover{{background:#0f172a; color:white;}}.dropdown-item-logout{{color:#dc2626;}}.dropdown-item-logout:hover{{background:#0f172a; color:white;}}</style>
    <div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center'><div><b style='font-size:14px'>🏫 {school_obj['name']}</b><div style='font-size:11px; color:#64748b'>{name} • School Admin • 🔑 {school_obj['code']}</div></div><div style='position:relative'><div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div><div id='profileDropdown' style='display:none; position:absolute; right:0; top:44px; background:white; border:1px solid #e2e8f0; border-radius:12px; width:220px; box-shadow:0 10px 25px rgba(0,0,0,0.12); z-index:1000; overflow:hidden'><div style='padding:14px; border-bottom:1px solid #f1f5f9; background:#f0fdf4'><div style='font-weight:700; font-size:13px'>{name}</div><div style='font-size:11px; color:#64748b'>{email}</div><div style='margin-top:6px'><span style='background:#dcfce7; color:#166534; padding:3px 8px; border-radius:20px; font-size:10px'>{school_obj['name']}</span></div></div><a href='/profile?tab=personal' class='dropdown-item dropdown-item-profile'>👤 Profile</a><a href='/logout' class='dropdown-item dropdown-item-logout'>🚪 Logout</a></div></div></div><script>function toggleProfileMenu(){{let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none';}} document.addEventListener('click', function(e){{let b=e.target.closest('.do-avatar'); let menu=document.getElementById('profileDropdown'); if(!b && menu &&!menu.contains(e.target)){{menu.style.display='none';}}}});</script>
    """
    content = f"""
    <div style='padding:24px; max-width:1100px; margin:0 auto'>
        <div style='margin-bottom:20px'><h2 style='margin:0; font-size:22px; font-weight:800'>🏫 Welcome, {school_obj['name']}!</h2><p style='color:#64748b; font-size:13px'>👋 Hello {name} — Your isolated school portal 🔒</p></div>
        <div style='display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:20px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🔑 SCHOOL CODE</div><div style='font-size:24px; font-weight:800; margin-top:8px'>🔑 {school_obj['code']}</div><div style='font-size:11px; color:#16a34a; margin-top:6px'>✅ Active & Verified</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>👥 STUDENTS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>350</div><div style='font-size:11px; color:#64748b; margin-top:6px'>📚 Demo data — will be real later</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>📍 LOCATION & TYPE</div><div style='font-size:14px; font-weight:700; margin-top:8px'>📍 {school_obj['location']}</div><div style='font-size:11px; color:#64748b; margin-top:6px'>🎓 {school_obj['school_type']}</div></div>
        </div>
        <div style='display:grid; grid-template-columns:1fr 1fr; gap:16px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:20px'><b>🏫 School Information</b><div style='margin-top:16px; display:flex; flex-direction:column; gap:10px'><div style='display:flex; justify-content:space-between; padding:10px; background:#f8fafc; border-radius:8px'><span style='font-size:12px; color:#64748b'>🏫 Name</span><span style='font-size:12px; font-weight:600'>{school_obj['name']}</span></div><div style='display:flex; justify-content:space-between; padding:10px; background:#f8fafc; border-radius:8px'><span style='font-size:12px; color:#64748b'>📧 Email</span><span style='font-size:12px; font-weight:600'>{school_obj['email']}</span></div><div style='display:flex; justify-content:space-between; padding:10px; background:#f8fafc; border-radius:8px'><span style='font-size:12px; color:#64748b'>📱 Phone</span><span style='font-size:12px; font-weight:600'>{school_obj['phone']}</span></div><div style='display:flex; justify-content:space-between; padding:10px; background:#f8fafc; border-radius:8px'><span style='font-size:12px; color:#64748b'>👨‍💼 Principal</span><span style='font-size:12px; font-weight:600'>{school_obj['principal']}</span></div><div style='display:flex; justify-content:space-between; padding:10px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px'><span style='font-size:12px; color:#166534'>🔑 Your Password</span><span style='font-size:12px; font-weight:700'>•••••• (unique, private)</span></div></div><div style='margin-top:16px; background:#f0fdf4; border:1px solid #bbf7d0; padding:12px; border-radius:8px; font-size:11px; color:#166534'>✅ <b>Isolated:</b> This portal is 100% separate — Super admin untouched! 🔒</div></div>
            <div style='background:#0f172a; border-radius:14px; padding:20px; color:white'><div style='font-size:14px; font-weight:700'>🚀 Modules Coming Soon</div><div style='font-size:11px; color:#94a3b8; margin-top:8px'>We will build these WITHOUT touching super admin:</div><div style='margin-top:16px; display:flex; flex-direction:column; gap:10px'><div style='background:#1e293b; padding:10px; border-radius:8px; font-size:12px'>👥 Student Management</div><div style='background:#1e293b; padding:10px; border-radius:8px; font-size:12px'>💰 Fee & Payments</div><div style='background:#1e293b; padding:10px; border-radius:8px; font-size:12px'>📊 Exams & Results</div><div style='background:#1e293b; padding:10px; border-radius:8px; font-size:12px'>📅 Attendance Tracking</div></div><div style='margin-top:16px; font-size:10px; color:#64748b'>⚡ Super admin side remains untouched!</div></div>
        </div>
    </div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; margin:0; background:#f8fafc'>{header}{content}</body></html>")

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("email","")
    name = request.session.get("name","Davis Ouma")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    school_obj = get_school_obj(request)
    is_super = school_obj is None
    sname = "Davischool Platform" if is_super else school_obj["name"]
    scode = "SUPER-ADMIN" if is_super else school_obj["code"]
    sloc = "Platform Owner" if is_super else school_obj["location"]
    badge = "Super Admin" if is_super else "School Admin"
    if is_super:
        hdr = header_html(initials, name, email)
        initials_style = "background:#0f172a; color:white;"
    else:
        initials_style = "background:#dcfce7; color:#166534;"
        hdr = f"<div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center'><div><b style='font-size:14px'>🏫 {sname}</b><div style='font-size:11px; color:#64748b'>{name} • {badge}</div></div><div style='width:36px; height:36px; {initials_style} border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800'>{initials}</div></div>"
    log_activity(email, f"👀 Viewed profile tab: {tab}", f"{tab}")
    if tab=="security":
        right = f"<div><b style='font-size:15px'>🔒 Security Settings</b><form method='post' action='/update-password' style='margin-top:18px'><label style='font-size:12px; font-weight:600; display:block; margin-top:14px'>🔑 Current Password</label><input name='current_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>🆕 New Password</label><input name='new_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>✅ Confirm New Password</label><input name='confirm_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><div style='text-align:right; margin-top:16px'><button type='submit' style='background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:8px; font-weight:600'>🔐 Update Password</button></div></form></div>"
    elif tab=="activity":
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 50", (email,))
        logs = cur.fetchall()
        con.close()
        log_rows = "".join([f"<div style='padding:12px 14px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><div><div style='font-size:12px; font-weight:600'>{l['action']}</div><div style='font-size:11px; color:#64748b'>{l['details']}</div></div><span style='font-size:10px; color:#94a3b8'>{l['timestamp']}</span></div>" for l in logs]) or "<div style='padding:24px; text-align:center; color:#999'>No activity yet</div>"
        right = f"<div><div style='display:flex; justify-content:space-between; align-items:center'><div><b style='font-size:15px'>📜 Activity Log</b><p style='font-size:11px; color:#64748b'>{len(logs)} events — EAT 🇰🇪</p></div><a href='/clear-activity' style='font-size:11px; color:#dc2626; border:1px solid #fecaca; padding:6px 10px; border-radius:6px; text-decoration:none'>🧹 Clear</a></div><div style='border:1px solid #e2e8f0; border-radius:10px; margin-top:16px; overflow:hidden; max-height:500px; overflow-y:auto'>{log_rows}</div></div>"
    else:
        right = f"<div><b style='font-size:15px'>👤 Personal Information</b><form method='post' action='/update-profile' style='margin-top:18px'><label style='font-size:12px; font-weight:600; display:block; margin-top:14px'>👨‍💼 Full Name</label><input name='full_name' value='{name}' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>📧 Email</label><input name='email_new' value='{email}' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>📱 Phone</label><input name='phone' value='+254748588874' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'><label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>🏫 Organization</label><input value='{sname}' disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f1f5f9; color:#64748b; margin-top:4px'><div style='text-align:right; margin-top:20px'><button type='submit' style='background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:8px; font-weight:600'>💾 Save Changes</button></div></form></div>"
    ap = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="personal" else "color:#64748b; border-bottom:2px solid transparent"
    ase = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="security" else "color:#64748b; border-bottom:2px solid transparent"
    aa = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="activity" else "color:#64748b; border-bottom:2px solid transparent"
    html = f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='margin:0; font-family:Arial; background:#f8fafc'>{hdr}<div style='padding:20px; max-width:1100px; margin:0 auto'><div style='margin-bottom:16px'><h2 style='margin:0; font-size:20px; font-weight:800'>👤 My Profile</h2></div><div style='display:flex; border-bottom:1px solid #e2e8f0; margin-bottom:20px; background:white; border-radius:10px 10px 0 0; padding:0 16px'><a href='/profile?tab=personal' style='padding:14px 4px; margin-right:24px; text-decoration:none; font-size:13px; {ap}'>👤 Personal</a><a href='/profile?tab=security' style='padding:14px 4px; margin-right:24px; text-decoration:none; font-size:13px; {ase}'>🔒 Security</a><a href='/profile?tab=activity' style='padding:14px 4px; text-decoration:none; font-size:13px; {aa}'>📜 Activity</a></div><div style='display:grid; grid-template-columns:340px 1fr; gap:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; text-align:center'><div style='width:88px; height:88px; {initials_style} border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px; font-weight:800; margin:0 auto'>{initials}</div><div style='font-weight:700; margin-top:14px'>{name}</div><div style='margin-top:8px'><span style='background:#e0f2fe; color:#0369a1; padding:5px 12px; border-radius:20px; font-size:11px'>{badge}</span></div><div style='margin-top:12px; font-size:12px'>{email}</div><div style='margin-top:16px; border-top:1px solid #f1f5f9; padding-top:16px; text-align:left'><div style='font-size:12px; font-weight:700'>🏫 {sname}</div><div style='font-size:11px; color:#64748b'>📍 {sloc}</div><div style='font-size:10px; color:#94a3b8; margin-top:6px; background:#f8fafc; padding:6px 8px; border-radius:6px'>🔑 Code: {scode}</div></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px'>{right}</div></div></div></body></html>"
    return HTMLResponse(html)

@app.post("/update-password")
def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if "email" not in request.session:
        return RedirectResponse("/")
    if new_password!= confirm_password:
        return HTMLResponse("<h3>❌ Passwords don't match</h3><a href='/profile?tab=security'>Back</a>")
    email = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_password))
    u = cur.fetchone()
    if not u:
        con.close()
        return HTMLResponse("<h3>❌ Wrong current password</h3><a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_password, email))
    con.commit()
    con.close()
    log_activity(email, "🔑 Changed password", "Updated ✅")
    return HTMLResponse("<h3>✅ Password Updated!</h3><a href='/profile?tab=security'>Back</a> | <a href='/dashboard'>📊 Dashboard</a>")

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
    log_activity(email_new.strip(), "👤 Updated profile", f"{full_name}")
    request.session["email"] = email_new.strip()
    request.session["name"] = full_name.strip()
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = "", success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = ""):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/school/dashboard")
    name = request.session.get("name","")
    email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC")
    schools = cur.fetchall()
    con.close()
    log_activity(email, "🏫 Viewed schools management", f"{len(schools)} schools")
    success_banner = ""
    if success=="added":
        # NEW: Show unique password once
        if new_pass and school_email:
            success_banner = f"<div style='background:#dcfce7; border:2px solid #16a34a; color:#166534; padding:16px; border-radius:10px; margin-bottom:16px'><b>✅ Success! 🏫 School Added + Unique Password Created!</b><div style='background:white; border:1px dashed #16a34a; border-radius:8px; padding:12px; margin-top:10px'><div style='font-size:11px; color:#64748b'>📧 School Email:</div><div style='font-weight:700'>{school_email}</div><div style='font-size:11px; color:#64748b; margin-top:8px'>🔑 Unique Password (active now):</div><div style='font-size:20px; font-weight:800; letter-spacing:2px; color:#0f172a'>🔑 {new_pass}</div><div style='font-size:10px; color:#dc2626; margin-top:6px'>⚠️ Copy & save — Share with school! Different from super admin password! Will not show again!</div></div><div style='margin-top:8px; font-size:11px'>School can login now at / with this password 🔐 Same login window, auto redirect!</div></div>"
        else:
            success_banner = "<div style='background:#dcfce7; border:1px solid #86efac; color:#166534; padding:12px 16px; border-radius:10px; margin-bottom:16px'>✅ <b>Success! 🏫</b> School registered!</div>"
    elif success=="code_sent":
        if EMAIL_PASSWORD:
            success_banner = f"<div style='background:#fef3c7; border:1px solid #fcd34d; color:#92400e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>📧 <b>Code sent to {SUPER_ADMIN}! 🔐</b></div>"
        else:
            success_banner = f"<div style='background:#fef3c7; border:1px solid #fcd34d; color:#92400e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>⚠️ <b>Email not configured — Code shown below! 🔓</b></div>"
    elif success=="updated":
        success_banner = "<div style='background:#e0f2fe; border:1px solid #7dd3fc; color:#0c4a6e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>✅ <b>Updated! ✏️</b></div>"
    elif success=="deleted":
        success_banner = "<div style='background:#fee2e2; border:1px solid #fca5a5; color:#991b1b; padding:12px 16px; border-radius:10px; margin-bottom:16px'>🗑️ <b>Deleted!</b></div>"
    rows_html = ""
    schools_json = {}
    for s in schools:
        sid = s["id"]
        schools_json[sid] = {"id": sid, "name": s["name"], "email": s["email"], "code": s["code"], "location": s["location"], "phone": s["phone"] or "", "principal": s["principal"] or "", "school_type": s["school_type"] or ""}
        rows_html += f"<tr id='row-{sid}' onclick='selectSchool({sid})' style='cursor:pointer'><td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#64748b'>🔑 {s['code']}</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📧 {s['email']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📍 {s['location']}</td></tr>"
    if not rows_html:
        rows_html = "<tr><td colspan=3 style='padding:24px; text-align:center; color:#999'>No schools yet 🏫</td></tr>"
    schools_data = json.dumps(schools_json)
    hl = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"
    verify_html = ""
    if pending_id:
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,))
        pending = cur.fetchone()
        con.close()
        if pending:
            code_display = ""
            if not EMAIL_PASSWORD:
                code_display = f"<div style='background:white; border:2px dashed #f59e0b; border-radius:10px; padding:14px; margin-top:12px; text-align:center'><div style='font-size:11px; color:#92400e; font-weight:600'>🔓 Email not set — Your code:</div><div style='font-size:32px; font-weight:800; letter-spacing:8px; color:#0f172a; margin-top:6px'>🔑 {pending['auth_code']}</div></div>"
            verify_html = f"<div style='background:#fffbeb; border:2px solid #f59e0b; border-radius:12px; padding:20px; margin-bottom:16px'><b>🔐 Enter Code for 🏫 {pending['name']}</b><p style='font-size:11px; color:#92400e'>{'📧 Check inbox' if EMAIL_PASSWORD else '⚠️ Code below 👇'}</p>{code_display}<form method='post' action='/verify-school-code' style='display:flex; gap:8px; margin-top:14px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='🔢 Enter 6-digit code' required style='flex:1; padding:12px; border:1px solid #fcd34d; border-radius:8px; font-size:18px; letter-spacing:4px; text-align:center; font-weight:700'><button style='background:#0f172a; color:white; padding:12px 20px; border:none; border-radius:8px; font-weight:600'>✅ Verify & Create Unique Password</button></form><div style='margin-top:8px; display:flex; gap:8px'><a href='/resend-code/{pending_id}' style='font-size:11px; color:#2563eb; text-decoration:none'>📧 Resend</a><a href='/schools/manage' style='font-size:11px; color:#64748b; text-decoration:none'>❌ Cancel</a></div></div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; background:#f8fafc; margin:0'>{header_html(initials, name, email)}<div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>{success_banner}{verify_html}<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px'><div><b>📚 Registered Schools ({len(schools)})</b><div style='font-size:11px; color:#64748b'>👆 Click row — blue highlight 💙 — Each has unique password 🔑</div></div><div style='display:flex; gap:8px'><button id='editBtn' disabled onclick='openEditModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px; font-weight:600'>✏️ Edit</button><button id='deleteBtn' disabled onclick='openDeleteModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px; font-weight:600'>🗑️ Delete</button></div></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>🏫 School (Unique Pass)</th><th style='padding:10px; text-align:left'>📧 Contact</th><th style='padding:10px; text-align:left'>📍 Location</th></tr>{rows_html}</table><div id='selectionInfo' style='margin-top:12px; padding:10px; background:#f8fafc; border-radius:8px; font-size:11px; color:#64748b; text-align:center'>👆 Select row to enable Edit/Delete — Each school has different password from super admin 🔐</div></div><div style='background:white; {hl}; border-radius:12px; padding:20px; position:sticky; top:20px'><b>➕ Register New School 🏫</b><p style='font-size:11px; color:#64748b'>Unique password auto-created 🔑 Different from admin!</p><form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='school_name' placeholder='🏫 School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' placeholder='📧 Admin Email *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' placeholder='📍 Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' placeholder='📱 Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' placeholder='👨‍💼 Principal *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>📧 Send Code & Create Unique Pass</button><a href='/schools/manage' style='background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:13px; display:block'>❌ Cancel</a></form></div></div><div id='editModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'><div style='background:white; border-radius:16px; width:100%; max-width:480px; padding:24px'><div style='display:flex; justify-content:space-between; margin-bottom:16px'><b>✏️ Edit School 🏫</b><span onclick='closeEditModal()' style='cursor:pointer'>✖️</span></div><p id='editCodeInfo' style='font-size:11px; color:#64748b; margin-bottom:12px'></p><form method='post' id='editForm' style='display:flex; flex-direction:column; gap:10px'><input name='school_name' id='edit_name' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' id='edit_email' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' id='edit_location' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' id='edit_phone' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' id='edit_principal' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' id='edit_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button type='submit' style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>💾 Save Changes</button><div onclick='closeEditModal()' style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer'>❌ Cancel</div></form></div></div><div id='deleteModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'><div style='background:white; border-radius:16px; width:100%; max-width:380px; padding:24px; text-align:center'><div style='width:56px; height:56px; background:#fee2e2; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px; margin:0 auto 12px'>⚠️</div><h3 style='margin:0'>Delete School? 🗑️</h3><p id='deleteInfo' style='font-size:13px; color:#64748b; margin:8px 0 16px'></p><div style='display:grid; grid-template-columns:1fr 1fr; gap:10px'><div onclick='closeDeleteModal()' style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer; font-weight:600'>❌ Cancel</div><a id='confirmDeleteBtn' href='#' style='background:#dc2626; color:white; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-weight:600'>🗑️ Yes, Delete</a></div></div></div><script>let selectedId=null; let schools={schools_data}; function selectSchool(id){{document.querySelectorAll('tr[id^="row-"]').forEach(r=>{{r.style.background='white';}}); document.getElementById('row-'+id).style.background='#dbeafe'; selectedId=id; let e=document.getElementById('editBtn'); let d=document.getElementById('deleteBtn'); e.disabled=false; d.disabled=false; e.style.background='#0f172a'; e.style.color='white'; e.style.cursor='pointer'; d.style.background='#dc2626'; d.style.color='white'; d.style.cursor='pointer'; document.getElementById('selectionInfo').innerHTML='✅ Selected: <b>'+schools[id].name+'</b> 🏫 — Unique password 🔑';}} function openEditModal(){{if(!selectedId)return; let s=schools[selectedId]; document.getElementById('edit_name').value=s.name; document.getElementById('edit_email').value=s.email; document.getElementById('edit_location').value=s.location; document.getElementById('edit_phone').value=s.phone; document.getElementById('edit_principal').value=s.principal; document.getElementById('edit_type').value=s.school_type; document.getElementById('editCodeInfo').innerText='🔑 Code: '+s.code; document.getElementById('editForm').action='/schools/update/'+selectedId; document.getElementById('editModal').style.display='flex';}} function closeEditModal(){{document.getElementById('editModal').style.display='none';}} function openDeleteModal(){{if(!selectedId)return; let s=schools[selectedId]; document.getElementById('deleteInfo').innerHTML='Delete <b>'+s.name+'</b> 🏫? Cannot be undone.'; document.getElementById('confirmDeleteBtn').href='/schools/delete/'+selectedId; document.getElementById('deleteModal').style.display='flex';}} function closeDeleteModal(){{document.getElementById('deleteModal').style.display='none';}}</script></body></html>""")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...), request: Request = None):
    auth_code = str(random.randint(100000, 999999))
    con = get_db()
    cur = con.cursor()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid
    con.commit()
    con.close()
    send_email(SUPER_ADMIN, f"🔐 Code: {auth_code} - {school_name}", f"🏫 {school_name.upper()}\n🔑 CODE: {auth_code}")
    log_activity(SUPER_ADMIN, f"📧 Auth code sent for {school_name} 🔐", f"Code {auth_code}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,))
    pending = cur.fetchone()
    if not pending:
        con.close()
        return HTMLResponse("Invalid <a href='/schools/manage'>Back</a>")
    if pending["auth_code"]!= auth_code.strip():
        con.close()
        return HTMLResponse(f"<h3>❌ Wrong Code! Expected {pending['auth_code']}</h3><a href='/schools/manage?pending_id={pending_id}'>Try Again</a>")
    code = str(random.randint(10000,99999))
    # NEW: Generate UNIQUE password for this school
    unique_pass = generate_unique_password(pending["name"])
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], unique_pass, "school_admin", pending["principal"], sid))
    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,))
    con.commit()
    con.close()
    # Send unique password to school email
    send_email(pending["email"], f"🏫 Welcome {pending['name']} - Your Login Credentials 🔑", f"🏫 Welcome to Davischool!\n\n🏫 School: {pending['name']}\n🔑 Code: {code}\n📧 Email: {pending['email']}\n🔑 Password: {unique_pass}\n\n🔐 This password is UNIQUE for your school - Different from super admin!\n🌐 Login at: https://your-render-url.onrender.com\n\nSame login window, auto redirect to your portal!\n\n👨‍💼 Principal: {pending['principal']}\n📍 {pending['location']}")
    send_email(SUPER_ADMIN, f"✅ School Added: {pending['name']} - Pass {unique_pass} 🏫", f"✅ Added!\n🏫 {pending['name']}\n🔑 Code: {code}\n📧 {pending['email']}\n🔑 Unique Pass: {unique_pass}\n\nDifferent from super admin password!")
    log_activity(SUPER_ADMIN, f"🏫 Registered new school: {pending['name']} ✅", f"Code: {code} | Unique pass created 🔑")
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}", status_code=303)

@app.get("/resend-code/{pending_id}")
def resend_code(pending_id: str):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,))
    pending = cur.fetchone()
    if not pending:
        con.close()
        return RedirectResponse("/schools/manage")
    new_code = str(random.randint(100000, 999999))
    cur.execute("UPDATE pending_schools SET auth_code=? WHERE id=?", (new_code, pending_id))
    con.commit()
    con.close()
    send_email(SUPER_ADMIN, f"🔐 New Code: {new_code}", f"🔑 New code: {new_code} for {pending['name']}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.post("/schools/update/{school_id}")
def update_school(school_id: int, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...), request: Request = None):
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, school_id))
    cur.execute("UPDATE users SET email=?, full_name=? WHERE school_id=?", (school_email.strip(), principal.strip(), school_id))
    con.commit()
    con.close()
    log_activity(request.session.get("email",""), f"✏️ Edited school: {school_name}", f"{school_type}")
    return RedirectResponse("/schools/manage?success=updated", status_code=303)

@app.get("/schools/delete/{school_id}")
def delete_school(school_id: int, request: Request):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/school/dashboard")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT name, code FROM schools WHERE id=?", (school_id,))
    s = cur.fetchone()
    sname = s["name"] if s else "Unknown"
    cur.execute("DELETE FROM schools WHERE id=?", (school_id,))
    cur.execute("DELETE FROM users WHERE school_id=?", (school_id,))
    con.commit()
    con.close()
    log_activity(request.session.get("email",""), f"🗑️ Deleted school: {sname}", f"Code: {s['code'] if s else ''}")
    return RedirectResponse("/schools/manage?success=deleted", status_code=303)

@app.get("/clear-activity")
def clear_activity(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM activity_log WHERE email=?", (email,))
    con.commit()
    con.close()
    log_activity(email, "🧹 Cleared activity log", "Deleted")
    return RedirectResponse("/profile?tab=activity", status_code=303)

@app.get("/logout")
def logout(request: Request):
    email = request.session.get("email","")
    if email:
        log_activity(email, "🚪 Logged out", "Ended")
    request.session.clear()
    return RedirectResponse("/", status_code=303)
