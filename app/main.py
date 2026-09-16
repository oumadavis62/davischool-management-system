from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random, json, smtplib, ssl
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage
import os

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v24-zeraki-school-side")
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
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_name TEXT, parent_phone TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, exam_id INTEGER, student_id INTEGER, subject_id INTEGER, score INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, term TEXT, total INTEGER, paid INTEGER, balance INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS timetable (id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER, day TEXT, period TEXT, subject TEXT, teacher TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS sms_logs (id INTEGER PRIMARY KEY, school_id INTEGER, recipient TEXT, message TEXT, timestamp TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit()
    con.close()
init_db()

def generate_unique_password(school_name):
    prefix = "".join([c for c in school_name.upper() if c.isalpha()])[:4]
    if len(prefix) < 3: prefix = "SCH"
    num = random.randint(1000, 9999)
    return f"{prefix}@{num}!"

def send_email(to_email, subject, body):
    if not EMAIL_PASSWORD: return False
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER; msg["To"] = to_email; msg["Subject"] = subject
        msg.set_content(body)
        msg.add_alternative(f"<div style='font-family:Arial; padding:20px'><h3>{subject}</h3><pre style='background:#f8fafc; padding:16px; border-radius:8px'>{body}</pre></div>", subtype="html")
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context); server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.send_message(msg)
        return True
    except: return False

def log_activity(email, action, details=""):
    try:
        con = get_db(); cur = con.cursor()
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO activity_log (email, action, details, timestamp) VALUES (?,?,?,?)", (email, action, details, ts))
        con.commit(); con.close()
    except: pass

def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin": return None
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone(); con.close(); return s

def header_html(initials, name, email):
    return f"""
    <style>
.do-avatar {{ width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; cursor:pointer; border:2px solid #e2e8f0; }}
.dropdown-item {{ display:flex; align-items:center; gap:10px; padding:11px 14px; text-decoration:none; font-size:13px; }}
.dropdown-item-profile {{ color:#0f172a; border-bottom:1px solid #f8fafc; }}
.dropdown-item-profile:hover {{ background:#0f172a; color:white; }}
.dropdown-item-logout {{ color:#dc2626; }}
.dropdown-item-logout:hover {{ background:#0f172a; color:white; }}
    </style>
    <div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center'>
        <div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px; color:#64748b'>{name} • Super Admin</div></div>
        <div style='position:relative'>
            <div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div>
            <div id='profileDropdown' style='display:none; position:absolute; right:0; top:44px; background:white; border:1px solid #e2e8f0; border-radius:12px; width:220px; box-shadow:0 10px 25px rgba(0,0,0,0.12); z-index:1000; overflow:hidden'>
                <div style='padding:14px; border-bottom:1px solid #f1f5f9; background:#f8fafc'><div style='font-weight:700; font-size:13px'>{name}</div><div style='font-size:11px; color:#64748b'>{email}</div></div>
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

def school_header(school, name, active="dashboard"):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    def nav(link, icon, label):
        a = "background:#0f172a; color:white; font-weight:700" if active==link else "color:#475569;"
        return f"<a href='/school/{link}' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; margin-bottom:4px; {a}'>{icon} {label}</a>"
    return f"""
    <div style='display:flex; min-height:100vh'>
    <div style='width:260px; background:white; border-right:1px solid #e2e8f0; padding:16px; position:sticky; top:0; height:100vh; overflow-y:auto'>
        <div style='padding:10px 6px 16px; border-bottom:1px solid #f1f5f9; margin-bottom:12px'><div style='display:flex; align-items:center; gap:10px'><div style='width:40px; height:40px; background:#0f172a; color:white; border-radius:10px; display:flex; align-items:center; justify-content:center; font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20]}</b><div style='font-size:10px; color:#64748b'>🔑 {school['code']} | {school['location']}</div></div></div></div>
        {nav('dashboard','📊','Dashboard')}
        {nav('students','🎓','Students')}
        {nav('classes','🏫','Classes & Streams')}
        {nav('subjects','📚','Subjects')}
        {nav('exams','📝','Exams')}
        {nav('marks','✍️','Enter Marks')}
        {nav('marksheets','📄','MarkSheets')}
        {nav('ranking','🏆','Ranking')}
        {nav('analysis','📈','Exam Analysis')}
        {nav('reports','📑','Student Reports')}
        {nav('timetable','🗓️','Smart Timetable')}
        {nav('fees','💰','Fees & Finance')}
        {nav('sms','💬','Bulk SMS Parents')}
        <div style='margin-top:16px; border-top:1px solid #f1f5f9; padding-top:12px'>
        <a href='/profile?tab=personal' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; color:#475569;'>👤 My Profile</a>
        <a href='/logout' style='display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:10px; text-decoration:none; font-size:13px; color:#dc2626;'>🚪 Logout</a>
        </div>
        <div style='margin-top:12px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:10px'><div style='font-size:10px; font-weight:700; color:#166534'>✅ MATOKEO ANALYTICS</div><div style='font-size:9px; color:#15803d; margin-top:4px'>Works for ALL LEVELS: Pre-Primary, Primary, Junior, Senior | 8-4-4 Supported</div></div>
    </div>
    <div style='flex:1; background:#f8fafc'>
        <div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'>
            <div><b style='font-size:14px'>MATOKEO ANALYTICS 🚀</b><div style='font-size:11px; color:#64748b'>{name} • {school['name']}</div></div>
            <div style='display:flex; align-items:center; gap:10px'><span style='font-size:11px; background:#dbeafe; color:#1e40af; padding:6px 10px; border-radius:20px'>{school['name']}</span><div style='width:36px; height:36px; background:#dcfce7; color:#166534; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800'>{initials}</div></div>
        </div>
    """

@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.get("/ping")
def ping(): return PlainTextResponse("pong")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2><p style='font-size:11px; color:#64748b'>ONE LOGIN FOR ALL ROLES 🔐</p></div><form method='post' action='/login'><input name='email' placeholder='📧 Email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='🔑 Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In</button></form></div></body></html>"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    school_info = None
    if u: cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],)); school_info = cur.fetchone()
    con.close()
    if not u: return HTMLResponse("❌ Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    if u["role"]!= "super_admin" and school_info:
        log_activity(u["email"], f"🏫 School login: {school_info['name']}", "")
        return RedirectResponse("/school/dashboard", status_code=303)
    log_activity(u["email"], "🔓 Super Admin Logged in", "")
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") == "school_admin": return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools"); total = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5"); recent = cur.fetchall(); con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    log_activity(email, "📊 Viewed dashboard", "School Overview")
    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
    if not rows: rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
    content = f"""
    <div style='padding:24px'><div style='margin-bottom:20px'><h2 style='margin:0; font-size:22px; font-weight:800'>📊 School Overview</h2><p style='color:#64748b; font-size:13px'>Welcome {name}</p></div>
    <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:28px; font-weight:800'>{total}</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE</div><div style='font-size:28px; font-weight:800'>{total}</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>💰 REVENUE</div><div style='font-size:28px; font-weight:800'>KES {total*15000:,}</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 STUDENTS</div><div style='font-size:28px; font-weight:800'>{total*350:,}</div></div>
    </div>
    <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>🏫 Recently Added Schools</b><a href='/schools/manage' style='font-size:12px; color:#2563eb; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Location</th><th style='padding:10px; text-align:left'>Status</th><th style='padding:10px; text-align:left'>Date</th></tr>{rows}</table></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><b>⚡ Quick Actions</b><div style='margin-top:12px; display:flex; flex-direction:column; gap:8px'><a href='/schools/manage' style='display:block; background:#0f172a; color:white; padding:10px; border-radius:8px; text-align:center; text-decoration:none'>🏫 Manage Schools</a><a href='/schools/manage?show=add' style='display:block; background:white; border:1px solid #e2e8f0; color:#64748b; padding:10px; border-radius:8px; text-align:center; text-decoration:none'>➕ Register New School</a></div></div></div></div>
    """
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{header_html(initials, name, email)}{content}</body></html>")

# ===== RESTORED FULL MANAGE SCHOOLS WITH 6-DIGIT CODE + AUTO CREDENTIALS + EYE + PROMPT =====
@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = "", success: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools = cur.fetchall()
    cur.execute("SELECT school_id, email, password FROM users WHERE role='school_admin'"); users_map = {r["school_id"]: r for r in cur.fetchall()}
    con.close()
    log_activity(email, "🏫 Viewed schools management", f"{len(schools)} schools listed")
    success_banner = ""
    last_added = None
    if success=="added":
        if schools: last_added = schools[0]
        success_banner = "<div style='background:#dcfce7; border:1px solid #86efac; color:#166534; padding:12px 16px; border-radius:10px; margin-bottom:16px'>✅ <b>Success!</b> School registered with 6-digit code — check prompt window or email.</div>"
    elif success=="updated": success_banner = "<div style='background:#e0f2fe; border:1px solid #7dd3fc; color:#0c4a6e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>✅ <b>Updated!</b> School updated.</div>"
    elif success=="deleted": success_banner = "<div style='background:#fee2e2; border:1px solid #fca5a5; color:#991b1b; padding:12px 16px; border-radius:10px; margin-bottom:16px'>🗑️ <b>Deleted!</b> School removed.</div>"

    rows_html = ""; schools_json = {}
    for s in schools:
        sid = s["id"]
        u = users_map.get(sid)
        pwd = u["password"] if u else "—"
        uname = u["email"] if u else s["email"]
        schools_json[sid] = {"id": sid, "name": s["name"], "email": s["email"], "code": s["code"], "location": s["location"], "phone": s["phone"] or "", "principal": s["principal"] or "", "school_type": s["school_type"] or "", "password": pwd, "username": uname}
        rows_html += f"<tr id='row-{sid}' onclick='selectSchool({sid})' style='cursor:pointer'><td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#0f172a; background:#f1f5f9; display:inline-block; padding:2px 6px; border-radius:4px; margin-top:4px'>🔑 {s['code']} (6-digit)</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📧 {uname}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'><span id='pwd-{sid}' style='letter-spacing:2px'>••••••••</span><span id='pwd-real-{sid}' style='display:none; font-weight:700'>{pwd}</span> <span onclick='togglePwd({sid})' style='cursor:pointer'>👁️</span></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📍 {s['location']}</td></tr>"
    if not rows_html: rows_html = "<tr><td colspan=4 style='padding:24px; text-align:center; color:#999'>No schools yet</td></tr>"
    schools_data = json.dumps(schools_json)
    hl = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"

    cred_modal = ""
    if last_added and success=="added":
        u_last = users_map.get(last_added["id"])
        pwd_last = u_last["password"] if u_last else ""
        email_last = u_last["email"] if u_last else last_added["email"]
        cred_modal = f"""
        <div id='credModal' style='display:flex; position:fixed; inset:0; background:rgba(15,23,42,0.7); z-index:99999; justify-content:center; align-items:center; padding:20px'>
          <div style='background:white; border-radius:16px; width:100%; max-width:460px; padding:24px'>
            <div style='text-align:center'><div style='width:56px; height:56px; background:#dcfce7; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px; margin:0 auto'>✅</div><h3 style='margin:12px 0 4px'>School Registered!</h3><p style='font-size:12px; color:#64748b'>6-digit code sent to your email {SUPER_ADMIN} & school email. If email inactive, use below:</p></div>
            <div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px; font-size:12px; line-height:2; margin-top:14px'>
              <div>🏫 <b>School:</b> {last_added["name"]}</div>
              <div>🔑 <b>Registration Code (6-digit auto):</b> <span style='background:#0f172a; color:white; padding:3px 10px; border-radius:6px; font-size:14px; letter-spacing:1px'>{last_added["code"]}</span></div>
              <div>👤 <b>Username (auto):</b> {email_last}</div>
              <div>🔒 <b>Password (auto):</b> <span id='modalPwd' style='letter-spacing:2px'>••••••••</span><span id='modalPwdReal' style='display:none; font-weight:700'>{pwd_last}</span> <span onclick="let a=document.getElementById('modalPwd'); let b=document.getElementById('modalPwdReal'); if(a.style.display=='none'){{a.style.display='inline'; b.style.display='none';}} else {{a.style.display='none'; b.style.display='inline';}}" style='cursor:pointer'>👁️ Show/Hide</span></div>
              <div style='margin-top:8px; background:#fef3c7; border:1px solid #fde68a; padding:8px; border-radius:8px; font-size:11px'>⚠️ If email is inactive, copy these credentials from this window before closing.</div>
            </div>
            <div style='display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:18px'><div onclick="document.getElementById('credModal').style.display='none'" style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer; font-weight:600'>❌ Cancel</div><div onclick="document.getElementById('credModal').style.display='none'; window.location.href='/schools/manage'" style='background:#0f172a; color:white; padding:11px; border-radius:8px; text-align:center; cursor:pointer; font-weight:600'>✅ OK - Got It</div></div>
          </div>
        </div>
        """

    return HTMLResponse(f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; background:#f8fafc; margin:0'>
{header_html(initials, name, email)}
<div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>
{success_banner}
<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px'><div><b>📚 Registered Schools ({len(schools)}) — Auto 6-Digit Code</b><div style='font-size:11px; color:#64748b'>Click row → blue | 👁️ to show password | Code is 6-digit auto</div></div><div style='display:flex; gap:8px'><button id='editBtn' disabled onclick='openEditModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px'>✏️ Edit</button><button id='deleteBtn' disabled onclick='openDeleteModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px'>🗑️ Delete</button></div></div>
<table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>School + 6-Digit Code</th><th style='padding:10px; text-align:left'>Username</th><th style='padding:10px; text-align:left'>Password 👁️</th><th style='padding:10px; text-align:left'>Location</th></tr>{rows_html}</table>
<div id='selectionInfo' style='margin-top:12px; padding:10px; background:#f8fafc; border-radius:8px; font-size:11px; color:#64748b; text-align:center'>👆 Select row to enable Edit/Delete | Passwords auto-generated with 👁️ eye toggle</div>
</div>
<div style='background:white; {hl}; border-radius:12px; padding:20px; position:sticky; top:20px'><b>➕ Register New School</b><div style='font-size:11px; color:#16a34a; margin-top:4px'>✅ System auto-generates 6-digit code + password + sends email</div><form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='school_name' placeholder='🏫 School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' placeholder='📧 Admin Email (Username) *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' placeholder='📍 Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' placeholder='📱 Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' placeholder='👨‍💼 Principal *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>✅ Create School (Auto 6-Digit Code)</button></form></div>
</div>
{cred_modal}
<div id='editModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'><div style='background:white; border-radius:16px; width:100%; max-width:480px; padding:24px'><div style='display:flex; justify-content:space-between; margin-bottom:16px'><b>✏️ Edit School</b><span onclick='closeEditModal()' style='cursor:pointer'>✖</span></div><p id='editCodeInfo' style='font-size:11px; color:#64748b; margin-bottom:12px'></p><form method='post' id='editForm' style='display:flex; flex-direction:column; gap:10px'><input name='school_name' id='edit_name' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' id='edit_email' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' id='edit_location' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' id='edit_phone' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' id='edit_principal' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' id='edit_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button type='submit' style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>💾 Save Changes</button><div onclick='closeEditModal()' style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer'>❌ Cancel</div></form></div></div>
<div id='deleteModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'><div style='background:white; border-radius:16px; width:100%; max-width:380px; padding:24px; text-align:center'><div style='width:56px; height:56px; background:#fee2e2; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px; margin:0 auto 12px'>⚠️</div><h3 style='margin:0'>Delete School?</h3><p id='deleteInfo' style='font-size:13px; color:#64748b; margin:8px 0 16px'></p><div style='display:grid; grid-template-columns:1fr 1fr; gap:10px'><div onclick='closeDeleteModal()' style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer'>❌ Cancel</div><a id='confirmDeleteBtn' href='#' style='background:#dc2626; color:white; padding:11px; border-radius:8px; text-align:center; text-decoration:none'>🗑️ Yes, Delete</a></div></div></div>
<script>
let selectedId=null; let schools={schools_data};
function selectSchool(id){{document.querySelectorAll('tr[id^="row-"]').forEach(r=>{{r.style.background='white';}}); document.getElementById('row-'+id).style.background='#dbeafe'; selectedId=id; let e=document.getElementById('editBtn'); let d=document.getElementById('deleteBtn'); e.disabled=false; d.disabled=false; e.style.background='#0f172a'; e.style.color='white'; d.style.background='#dc2626'; d.style.color='white'; document.getElementById('selectionInfo').innerHTML='✅ Selected: <b>'+schools[id].name+'</b> — Code: '+schools[id].code;}}
function openEditModal(){{if(!selectedId)return; let s=schools[selectedId]; document.getElementById('edit_name').value=s.name; document.getElementById('edit_email').value=s.email; document.getElementById('edit_location').value=s.location; document.getElementById('edit_phone').value=s.phone; document.getElementById('edit_principal').value=s.principal; document.getElementById('edit_type').value=s.school_type; document.getElementById('editCodeInfo').innerText='6-Digit Code: '+s.code+' | Username: '+s.username+' | Password: '+s.password; document.getElementById('editForm').action='/schools/update/'+selectedId; document.getElementById('editModal').style.display='flex';}}
function closeEditModal(){{document.getElementById('editModal').style.display='none';}}
function openDeleteModal(){{if(!selectedId)return; let s=schools[selectedId]; document.getElementById('deleteInfo').innerHTML='Delete <b>'+s.name+'</b> (Code: '+s.code+')?'; document.getElementById('confirmDeleteBtn').href='/schools/delete/'+selectedId; document.getElementById('deleteModal').style.display='flex';}}
function closeDeleteModal(){{document.getElementById('deleteModal').style.display='none';}}
function togglePwd(id){{let a=document.getElementById('pwd-'+id); let b=document.getElementById('pwd-real-'+id); if(a.style.display==='none'){{a.style.display='inline'; b.style.display='none';}} else {{a.style.display='none'; b.style.display='inline';}}}}
</script>
</body></html>
""")

@app.post("/schools/update/{school_id}")
def update_school(school_id: int, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...), request: Request = None):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT name FROM schools WHERE id=?", (school_id,)); old = cur.fetchone(); old_name = old["name"] if old else "Unknown"
    cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, school_id))
    cur.execute("UPDATE users SET email=?, full_name=? WHERE school_id=?", (school_email.strip(), principal.strip(), school_id))
    con.commit(); con.close()
    email = request.session.get("email","") if request else ""
    log_activity(email, f"✏️ Edited school: {school_name}", f"From {old_name} to {school_name}")
    return RedirectResponse("/schools/manage?success=updated", status_code=303)

@app.get("/schools/delete/{school_id}")
def delete_school(school_id: int, request: Request):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT name, code FROM schools WHERE id=?", (school_id,)); s = cur.fetchone()
    sname = s["name"] if s else "Unknown"; scode = s["code"] if s else ""
    cur.execute("DELETE FROM schools WHERE id=?", (school_id,)); cur.execute("DELETE FROM users WHERE school_id=?", (school_id,))
    con.commit(); con.close()
    email = request.session.get("email","")
    log_activity(email, f"🗑️ Deleted school: {sname}", f"Code: {scode}")
    return RedirectResponse("/schools/manage?success=deleted", status_code=303)

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...), request: Request = None):
    # 6-DIGIT CODE AUTO + AUTO PASSWORD + EMAIL
    code = str(random.randint(100000, 999999))
    auto_password = generate_unique_password(school_name)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), code, location.strip(), phone.strip(), principal.strip(), school_type))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (school_email.strip(), auto_password, "school_admin", f"{principal.strip() or 'School Admin'}", sid))
    con.commit(); con.close()
    # Send email to super admin + school
    email_body = f"""🏫 NEW SCHOOL REGISTERED - Davischool

School Name: {school_name.upper()}
Location: {location}
Principal: {principal}
Phone: {phone}
Type: {school_type}

🔑 Registration Code (6-digit): {code}
👤 Username (auto): {school_email}
🔒 Password (auto): {auto_password}

Login: https://your-app.onrender.com

If school email inactive, credentials are shown in prompt window after adding.
"""
    # Try send to both
    sent_to_super = send_email(SUPER_ADMIN, f"✅ New School Registered: {school_name} - Code {code}", email_body)
    sent_to_school = send_email(school_email.strip(), f"🎉 Welcome to Davischool - Your School {school_name} Registered! Code: {code}", email_body)
    email = SUPER_ADMIN
    try:
        if request: email = request.session.get("email", SUPER_ADMIN)
    except: email = SUPER_ADMIN
    status_email = "Email sent" if (sent_to_super or sent_to_school) else "Email inactive - shown in prompt window"
    log_activity(email, f"🏫 Registered new school: {school_name} (6-digit Code: {code})", f"Username: {school_email} | Password: {auto_password} | {status_email} | Type: {school_type}")
    return RedirectResponse("/schools/manage?success=added", status_code=303)

# SCHOOL SIDE - UNTOUCHED ZERAKI
@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]
    cur.execute("SELECT SUM(paid) s FROM fees WHERE school_id=?", (school["id"],)); fees_paid = cur.fetchone()["s"] or 0
    con.close()
    html = school_header(school, name, "dashboard")
    html += f"""
        <div style='padding:20px'>
            <div style='background:linear-gradient(135deg,#0f172a,#1e40af); border-radius:16px; padding:20px; color:white;'><h2 style='margin:0'>MATOKEO ANALYTICS 🚀</h2><p style='color:#bfdbfe'>Total Students: {sc} | Classes: {cc} | Exams: {ec}</p></div>
            <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:16px'>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'>🎓 {sc} Students</div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'>🏫 {cc} Classes</div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'>📝 {ec} Exams</div>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'>💰 KES {fees_paid:,}</div>
            </div>
        </div></div></div>
    """
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

def school_list_page(request, title, active, table_html, form_html):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    html = school_header(school, name, active)
    html += f"<div style='padding:20px; display:grid; grid-template-columns:1fr 360px; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>{table_html}</div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><b>{title}</b>{form_html}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['name']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['admission_no']}</td><td><a href='/school/student/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for s in students]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No students</td></tr>"
    table = f"<b>🎓 Students ({len(students)})</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Name</th><th>Adm</th><th>Action</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/students/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='admission_no' placeholder='Admission No *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='student_name' placeholder='Student Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='class_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Select Class</option>{opts}</select><select name='gender' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Male</option><option>Female</option></select><input name='parent_name' placeholder='Parent Name' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='parent_phone' placeholder='Parent Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>➕ Add</button></form>"
    return school_list_page(request, "Add Student", "students", table, form)

@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_name: str = Form(...), parent_phone: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO students (school_id, admission_no, name, class_id, gender, parent_name, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], admission_no.strip(), student_name.strip(), class_id, gender, parent_name, parent_phone)); con.commit(); con.close()
    return RedirectResponse("/school/students", status_code=303)

@app.get("/school/student/delete/{sid}")
def del_student(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/students", status_code=303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY id DESC", (school["id"],)); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{c['name']}</td><td>{c['level']}</td><td><a href='/school/class/delete/{c['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No classes</td></tr>"
    table = f"<b>Classes</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Class</th><th>Level</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/classes/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='class_name' placeholder='Class Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='level' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Pre-Primary</option><option>Primary</option><option>Junior School</option><option>Senior School</option><option>8-4-4</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add Class</button></form>"
    return school_list_page(request, "Add Class", "classes", table, form)

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), level: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, level) VALUES (?,?,?)", (school["id"], class_name.strip(), level)); con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/class/delete/{cid}")
def del_class(cid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=? AND school_id=?", (cid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY id DESC", (school["id"],)); subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['name']}</td><td><a href='/school/subject/delete/{s['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan=2 style='padding:20px; text-align:center'>No subjects</td></tr>"
    table = f"<b>Subjects</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Subject</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/subjects/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='subject_name' placeholder='Subject *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject_code' placeholder='Code' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add Subject</button></form>"
    return school_list_page(request, "Add Subject", "subjects", table, form)

@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), subject_code: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO subjects (school_id, name, code) VALUES (?,?,?)", (school["id"], subject_name.strip(), subject_code.strip())); con.commit(); con.close()
    return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/subject/delete/{sid}")
def del_sub(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school["id"],)); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{e['name']}</td><td>{e['term']}</td><td><a href='/school/exam/delete/{e['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No exams</td></tr>"
    table = f"<b>Exams</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Exam</th><th>Term</th><th>Action</th></tr>{rows}</table>"
    form = "<form method='post' action='/school/exams/add' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='exam_name' placeholder='Exam Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='term' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' value='2026' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='exam_type' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Main Exam</option><option>CAT</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add Exam</button></form>"
    return school_list_page(request, "Add Exam", "exams", table, form)

@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip(), term, year, exam_type)); con.commit(); con.close()
    return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/exam/delete/{eid}")
def del_exam(eid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM exams WHERE id=? AND school_id=?", (eid, school["id"])); con.commit(); con.close()
    return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/marks", response_class=HTMLResponse)
def school_marks(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall()
    cur.execute("SELECT id, name FROM students WHERE school_id=? LIMIT 20", (school["id"],)); students = cur.fetchall()
    con.close()
    e_opts = "".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams])
    sub_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    st_opts = "".join([f"<option value='{st['id']}'>{st['name']}</option>" for st in students])
    form = f"<form method='post' action='/school/marks/add' style='display:flex; flex-direction:column; gap:10px'><select name='exam_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Exam</option>{e_opts}</select><select name='subject_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Subject</option>{sub_opts}</select><select name='student_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Student</option>{st_opts}</select><input name='score' type='number' placeholder='Score' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Save</button></form>"
    return school_list_page(request, "Enter Marks", "marks", "<b>Enter Marks</b>", form)

@app.post("/school/marks/add")
def add_marks(request: Request, exam_id: int = Form(...), subject_id: int = Form(...), student_id: int = Form(...), score: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO marks (school_id, exam_id, student_id, subject_id, score) VALUES (?,?,?,?,?)", (school["id"], exam_id, student_id, subject_id, score)); con.commit(); con.close()
    return RedirectResponse("/school/marks", status_code=303)

@app.get("/school/marksheets", response_class=HTMLResponse)
def school_marksheets(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); con.close()
    cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><b>{e['name']}</b><a href='/school/marksheets/{e['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none'>View</a></div>" for e in exams]) or "No exams"
    html = school_header(school, request.session.get("name",""), "marksheets") + f"<div style='padding:20px'><h3>MarkSheets</h3><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/marksheets/{exam_id}", response_class=HTMLResponse)
def view_marksheet(exam_id: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE id=?", (exam_id,)); exam = cur.fetchone(); cur.execute("SELECT id, name, admission_no FROM students WHERE school_id=?", (school["id"],)); students = cur.fetchall(); cur.execute("SELECT id, name FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall(); marks_map={}; cur.execute("SELECT student_id, subject_id, score FROM marks WHERE exam_id=?", (exam_id,));
    for r in cur.fetchall(): marks_map[(r["student_id"], r["subject_id"])] = r["score"]
    con.close()
    th="".join([f"<th style='padding:8px; border:1px solid #e2e8f0'>{sub['name'][:6]}</th>" for sub in subjects])
    rows=""
    for st in students:
        scores=[]; total=0
        for sub in subjects:
            sc=marks_map.get((st["id"], sub["id"]), "-")
            scores.append(f"<td style='padding:8px; border:1px solid #eee; text-align:center'>{sc}</td>")
            if isinstance(sc,int): total+=sc
        rows+=f"<tr><td style='padding:8px; border:1px solid #eee'>{st['name']}</td><td style='padding:8px; border:1px solid #eee'>{st['admission_no']}</td>{''.join(scores)}<td style='padding:8px; border:1px solid #eee; font-weight:700'>{total}</td></tr>"
    html = school_header(school, request.session.get("name",""), "marksheets") + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><b>{exam['name']}</b><button onclick='window.print()' style='float:right; background:#0f172a; color:white; padding:8px 14px; border:none; border-radius:8px'>Print</button><table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc'><th style='padding:8px; border:1px solid #e2e8f0'>Student</th><th style='padding:8px; border:1px solid #e2e8f0'>Adm</th>{th}<th style='padding:8px; border:1px solid #e2e8f0'>Total</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

@app.get("/school/ranking", response_class=HTMLResponse)
def school_ranking(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM exams WHERE school_id=? LIMIT 1", (school["id"],)); e = cur.fetchone(); ranking_rows=""
    if e:
        cur.execute("SELECT s.id, s.name, SUM(m.score) total FROM students s JOIN marks m ON s.id=m.student_id WHERE m.exam_id=? GROUP BY s.id ORDER BY total DESC", (e["id"],));
        for idx,r in enumerate(cur.fetchall(),1): ranking_rows+=f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{idx}</td><td style='padding:10px; border-bottom:1px solid #eee'>{r['name']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-weight:700'>{r['total']}</td></tr>"
    con.close()
    if not ranking_rows: ranking_rows="<tr><td colspan=3 style='padding:20px; text-align:center'>No marks</td></tr>"
    html = school_header(school, request.session.get("name",""), "ranking") + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'><table style='width:100%'><tr style='background:#f8fafc'><th>Rank</th><th>Student</th><th>Total</th></tr>{ranking_rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/analysis", response_class=HTMLResponse)
def school_analysis(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT AVG(score) avg FROM marks WHERE school_id=?", (school["id"],)); avg = cur.fetchone()["avg"] or 0; con.close()
    html = school_header(school, request.session.get("name",""), "analysis") + f"<div style='padding:20px'><b>Analysis Avg: {int(avg)}%</b></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/reports", response_class=HTMLResponse)
def school_reports(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT id, name FROM students WHERE school_id=?", (school["id"],)); students = cur.fetchall(); con.close()
    cards = "".join([f"<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px'><b>{s['name']}</b><a href='/school/report/{s['id']}' style='display:block; margin-top:10px; background:#0f172a; color:white; padding:8px; border-radius:8px; text-align:center; text-decoration:none'>Report</a></div>" for s in students]) or "No students"
    html = school_header(school, request.session.get("name",""), "reports") + f"<div style='padding:20px'><h3>Reports</h3><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px'>{cards}</div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{html}</body></html>")

@app.get("/school/report/{student_id}", response_class=HTMLResponse)
def student_report(student_id: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM students WHERE id=?", (student_id,)); st = cur.fetchone(); cur.execute("SELECT sub.name, m.score FROM marks m JOIN subjects sub ON m.subject_id=sub.id WHERE m.student_id=?", (student_id,)); marks = cur.fetchall(); total=sum([m["score"] for m in marks]); con.close()
    rows="".join([f"<tr><td style='padding:8px; border:1px solid #eee'>{m['name']}</td><td style='padding:8px; border:1px solid #eee; text-align:center'>{m['score']}</td></tr>" for m in marks])
    html = school_header(school, request.session.get("name",""), "reports") + f"<div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px'><h2>{school['name']} Report</h2><div>{st['name']} | Total: {total}</div><table style='width:100%; margin-top:16px; border-collapse:collapse'><tr style='background:#f8fafc'><th>Subject</th><th>Score</th></tr>{rows}</table></div></div></div></div>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial'>{html}</body></html>")

@app.get("/school/fees", response_class=HTMLResponse)
def school_fees(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT f.*, s.name as sname FROM fees f JOIN students s ON f.student_id=s.id WHERE f.school_id=?", (school["id"],)); fees = cur.fetchall(); cur.execute("SELECT id, name FROM students WHERE school_id=?", (school["id"],)); students = cur.fetchall(); con.close()
    st_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in students])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{f['sname']}</td><td>{f['term']}</td><td>KES {f['total']}</td><td>KES {f['paid']}</td><td>KES {f['balance']}</td></tr>" for f in fees]) or "<tr><td colspan=5 style='padding:20px; text-align:center'>No fees</td></tr>"
    table = f"<b>Fees</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Student</th><th>Term</th><th>Total</th><th>Paid</th><th>Balance</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/fees/add' style='display:flex; flex-direction:column; gap:10px'><select name='student_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Student</option>{st_opts}</select><select name='term' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='total' type='number' placeholder='Total' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='paid' type='number' placeholder='Paid' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Save</button></form>"
    return school_list_page(request, "Record Fees", "fees", table, form)

@app.post("/school/fees/add")
def add_fees(request: Request, student_id: int = Form(...), term: str = Form(...), total: int = Form(...), paid: int = Form(...)):
    school = get_school_obj(request); balance = total - paid; con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO fees (school_id, student_id, term, total, paid, balance) VALUES (?,?,?,?,?,?)", (school["id"], student_id, term, total, paid, balance)); con.commit(); con.close(); return RedirectResponse("/school/fees", status_code=303)

@app.get("/school/timetable", response_class=HTMLResponse)
def school_timetable(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT t.*, c.name as cname FROM timetable t LEFT JOIN classes c ON t.class_id=c.id WHERE t.school_id=?", (school["id"],)); tt = cur.fetchall(); cur.execute("SELECT id, name FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    c_opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{t['day']}</td><td>{t['period']}</td><td>{t['cname']}</td><td>{t['subject']}</td><td>{t['teacher']}</td><td><a href='/school/timetable/delete/{t['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for t in tt]) or "<tr><td colspan=6 style='padding:20px; text-align:center'>No timetable</td></tr>"
    table = f"<b>Timetable</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>Day</th><th>Period</th><th>Class</th><th>Subject</th><th>Teacher</th><th>Action</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/timetable/add' style='display:flex; flex-direction:column; gap:10px'><select name='class_id' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Class</option>{c_opts}</select><select name='day' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option></select><input name='period' placeholder='Period' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='subject' placeholder='Subject' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='teacher' placeholder='Teacher' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Add</button></form>"
    return school_list_page(request, "Add Lesson", "timetable", table, form)

@app.post("/school/timetable/add")
def add_tt(request: Request, class_id: int = Form(...), day: str = Form(...), period: str = Form(...), subject: str = Form(...), teacher: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO timetable (school_id, class_id, day, period, subject, teacher) VALUES (?,?,?,?,?,?)", (school["id"], class_id, day, period, subject, teacher)); con.commit(); con.close(); return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/timetable/delete/{tid}")
def del_tt(tid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM timetable WHERE id=? AND school_id=?", (tid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/timetable", status_code=303)

@app.get("/school/sms", response_class=HTMLResponse)
def school_sms(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM sms_logs WHERE school_id=? ORDER BY id DESC LIMIT 20", (school["id"],)); logs = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>{s['recipient']}</td><td>{s['message'][:60]}</td><td>{s['timestamp']}</td></tr>" for s in logs]) or "<tr><td colspan=3 style='padding:20px; text-align:center'>No SMS</td></tr>"
    table = f"<b>SMS Logs</b><table style='width:100%; margin-top:12px'><tr style='background:#f8fafc'><th>To</th><th>Message</th><th>Time</th></tr>{rows}</table>"
    form = f"<form method='post' action='/school/sms/send' style='display:flex; flex-direction:column; gap:10px'><textarea name='message' placeholder='Message' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px; height:100px'></textarea><button style='background:#16a34a; color:white; padding:12px; border:none; border-radius:8px'>Send</button></form>"
    return school_list_page(request, "Send SMS", "sms", table, form)

@app.post("/school/sms/send")
def send_sms(request: Request, message: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT parent_phone FROM students WHERE school_id=?", (school["id"],)); parents = cur.fetchall(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    for p in parents: cur.execute("INSERT INTO sms_logs (school_id, recipient, message, timestamp) VALUES (?,?,?,?)", (school["id"], p["parent_phone"], message, ts))
    con.commit(); con.close(); return RedirectResponse("/school/sms", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email",""); name = request.session.get("name",""); role = request.session.get("role","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    if tab=="activity":
        con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 50", (email,)); logs = cur.fetchall(); con.close()
        log_rows = "".join([f"<div style='padding:10px; border-bottom:1px solid #f1f5f9'><b style='font-size:12px'>{log['action']}</b><div style='font-size:11px; color:#64748b'>{log['details']}</div><div style='font-size:10px; color:#94a3b8'>{log['timestamp']}</div></div>" for log in logs]) or "<div style='padding:24px; text-align:center'>No activity</div>"
        right = f"<div><b>📜 Activity Log - Kenya Time</b><div style='border:1px solid #e2e8f0; border-radius:10px; margin-top:12px; max-height:500px; overflow-y:auto'>{log_rows}</div></div>"
    elif tab=="security":
        right = f"<div><b>🔒 Security</b><form method='post' action='/update-password' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='current_password' type='password' placeholder='Current' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='new_password' type='password' placeholder='New' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='confirm_password' type='password' placeholder='Confirm' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:11px; border:none; border-radius:8px'>Update Password</button></form></div>"
    else:
        right = f"<div><b>👤 Personal Info</b><form method='post' action='/update-profile' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='full_name' value='{name}' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='email_new' value='{email}' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:11px; border:none; border-radius:8px'>Save</button></form></div>"
    ap = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="personal" else "color:#64748b"
    ase = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="security" else "color:#64748b"
    aa = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="activity" else "color:#64748b"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'>{header_html(initials, name, email)}<div style='padding:20px; max-width:1100px; margin:0 auto'><div style='display:flex; border-bottom:1px solid #e2e8f0; background:white; border-radius:10px 10px 0 0; padding:0 16px'><a href='/profile?tab=personal' style='padding:14px 4px; margin-right:24px; text-decoration:none; {ap}'>Personal</a><a href='/profile?tab=security' style='padding:14px 4px; margin-right:24px; text-decoration:none; {ase}'>Security</a><a href='/profile?tab=activity' style='padding:14px 4px; text-decoration:none; {aa}'>Activity</a></div><div style='display:grid; grid-template-columns:340px 1fr; gap:20px; margin-top:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; text-align:center'><div style='width:88px; height:88px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px; font-weight:800; margin:0 auto'>{initials}</div><div style='font-weight:700; margin-top:14px'>{name}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px'>{right}</div></div></div></body></html>")

@app.post("/update-password")
def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    if new_password!= confirm_password: return HTMLResponse("<h3>Passwords don't match</h3><a href='/profile?tab=security'>Back</a>")
    email = request.session.get("email"); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_password)); u = cur.fetchone()
    if not u: con.close(); return HTMLResponse("<h3>Current password wrong</h3><a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_password, email)); con.commit(); con.close()
    log_activity(email, "🔑 Changed password", "Password updated"); return HTMLResponse("<h3>✅ Password Updated!</h3><a href='/dashboard'>Dashboard</a>")

@app.post("/update-profile")
def update_profile(request: Request, full_name: str = Form(...), email_new: str = Form(...), phone: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    old_email = request.session.get("email"); con = get_db(); cur = con.cursor(); cur.execute("UPDATE users SET full_name=?, email=? WHERE email=?", (full_name.strip(), email_new.strip(), old_email)); con.commit(); con.close()
    request.session["email"] = email_new.strip(); request.session["name"] = full_name.strip()
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
