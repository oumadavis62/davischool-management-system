from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random, smtplib, ssl, os
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v32-students-classes-integrated")
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
    con = get_db(); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_name TEXT, parent_phone TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, exam_id INTEGER, student_id INTEGER, subject_id INTEGER, score INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, term TEXT, total INTEGER, paid INTEGER, balance INTEGER)")
    # Add stream column if missing
    try: cur.execute("ALTER TABLE classes ADD COLUMN stream TEXT")
    except: pass
    try: cur.execute("ALTER TABLE students ADD COLUMN stream TEXT")
    except: pass
    try: cur.execute("ALTER TABLE students ADD COLUMN assessment_no TEXT")
    except: pass
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit(); con.close()
init_db()

def generate_unique_password(school_name):
    prefix = "".join([c for c in school_name.upper() if c.isalpha()])[:4]
    if len(prefix) < 3: prefix = "SCH"
    return f"{prefix}@{random.randint(1000,9999)}!"

def send_email(to_email, subject, body):
    if not EMAIL_PASSWORD: return False
    try:
        msg = EmailMessage(); msg["From"]=EMAIL_SENDER; msg["To"]=to_email; msg["Subject"]=subject; msg.set_content(body)
        msg.add_alternative(f"<div style='font-family:Arial;padding:20px'><h3>{subject}</h3><pre>{body}</pre></div>", subtype="html")
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context); server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.send_message(msg)
        return True
    except: return False

def log_activity(email, action, details=""):
    try:
        con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
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
 .do-avatar{{width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #e2e8f0}}
 .dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#0f172a;color:white}}
 .back-btn{{display:inline-flex; align-items:center; gap:6px; padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px; text-align:center; transition:all 0.2s ease; cursor:pointer}}
 .back-btn:hover{{background:#0f172a!important; color:white!important; border-color:#0f172a!important; transform:translateY(-1px); box-shadow:0 4px 12px rgba(15,23,42,0.25)}}
    </style>
    <div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 20px;display:flex;justify-content:space-between;align-items:center'>
        <div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px;color:#64748b'>{name} • Super Admin</div></div>
        <div style='position:relative'><div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div>
            <div id='profileDropdown' style='display:none;position:absolute;right:0;top:44px;background:white;border:1px solid #e2e8f0;border-radius:12px;width:220px;box-shadow:0 10px 25px rgba(0,0,0,0.12);z-index:1000;overflow:hidden'>
                <div style='padding:14px;border-bottom:1px solid #f1f5f9;background:#f8fafc'><div style='font-weight:700;font-size:13px'>{name}</div><div style='font-size:11px;color:#64748b'>{email}</div></div>
                <a href='/profile?tab=personal' class='dropdown-item' style='color:#0f172a'>👤 Profile</a>
                <a href='/logout' class='dropdown-item' style='color:#dc2626'>🚪 Logout</a>
            </div>
        </div>
    </div>
    <script>function toggleProfileMenu(){{let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none';}} document.addEventListener('click',function(e){{let b=e.target.closest('.do-avatar'); let menu=document.getElementById('profileDropdown'); if(!b && menu &&!menu.contains(e.target)){{menu.style.display='none';}}}});</script>
    """

def school_header(school, name, active="dashboard"):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    def nav(link, icon, label):
        a = "background:#0f172a;color:white;font-weight:700" if active==link else "color:#475569;"
        return f"<a href='/school/{link}' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{a};transition:all 0.2s' onmouseover=\"if(this.style.background!=='rgb(15, 23, 42)'){{this.style.background='#0f172a'; this.style.color='white'}}\" onmouseout=\"if('{active}'!='{link}'){{this.style.background='transparent'; this.style.color='#475569'}}\">{icon} {label}</a>"
    return f"""
    <style>
 .ds-card{{background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; text-decoration:none; color:#0f172a; display:block; transition:all 0.25s ease; cursor:pointer}}
 .ds-card:hover{{background:#0f172a!important; color:white!important; transform:translateY(-2px); box-shadow:0 8px 20px rgba(15,23,42,0.3)}}
 .ds-card:hover div{{color:white!important}}
 .input-field{{width:100%; padding:11px 12px; border:1px solid #e2e8f0; border-radius:10px; margin:6px 0; font-size:13px; background:white}}
 .add-btn{{width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; font-weight:700; cursor:pointer; transition:all 0.2s}}
 .add-btn:hover{{background:#1e3a8a}}
    </style>
    <div style='display:flex;min-height:100vh'>
    <div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'>
      <div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'>
        <div style='display:flex;align-items:center;gap:10px'>
          <div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div>
          <div><b style='font-size:13px'>{school['name'][:20].upper()}</b><div style='font-size:10px;color:#64748b'>🔑 {school['code']} | {school['location']}</div></div>
        </div>
      </div>
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
      <div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/logout' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div>
    </div>
    <div style='flex:1;background:#f8fafc'>
      <div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'>
        <div>
          <b style='font-size:14px'>DaviSchool Management System 🚀</b>
          <div style='font-size:11px;color:#64748b'>{name} • {school['name']} | Revolutionize Your School's Management!</div>
        </div>
        <div style='display:flex;align-items:center;gap:10px'>
          <span style='font-size:11px;background:#dbeafe;color:#1e40af;padding:6px 10px;border-radius:20px'>{school['name']}</span>
          <div style='width:36px;height:36px;background:#dcfce7;color:#166534;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800'>{initials}</div>
        </div>
      </div>
    """

@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, tab: str = "personal"):
    if "email" not in request.session: return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM activity_log WHERE email=?", (email,)); total_events = cur.fetchone()["c"]
    cur.execute("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 20", (email,)); logs = cur.fetchall()
    con.close()
    log_activity(email, f"Viewed profile tab: {tab}", tab)
    active_personal = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="personal" else "color:#64748b"
    active_security = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="security" else "color:#64748b"
    active_log = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="activity" else "color:#64748b"
    left_card = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; text-align:center; height:fit-content; display:flex; flex-direction:column'><div><div style='width:80px; height:80px; background:#a8d8ff; color:#1e3a8a; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:900; font-size:28px; margin:0 auto 12px'>{initials}</div><div style='font-weight:800; font-size:16px'>{name}</div><div style='background:#e0f2fe; color:#0369a1; padding:4px 12px; border-radius:20px; font-size:11px; font-weight:700; display:inline-block; margin:6px 0'>Super Admin</div><div style='font-size:12px; color:#64748b; margin-top:4px; word-break:break-all'>{email}</div><div style='margin-top:18px; text-align:left; border-top:1px solid #f1f5f9; padding-top:14px'><div style='font-weight:700; font-size:13px'>🏫 Davischool Platform</div><div style='font-size:11px; color:#ec4899'>📍 Platform Owner</div><div style='font-size:11px; color:#64748b; margin-top:10px'>🔑 Code: SUPER-ADMIN</div></div></div><a href='/dashboard' class='back-btn' style='margin-top:20px; justify-content:center'>⬅️ Back to Dashboard</a></div>"""
    if tab == "personal":
        right_card = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='font-weight:800; margin-bottom:16px; font-size:14px'>👤 Personal Information</div><form method='post' action='/profile/update'><label style='font-size:11px; font-weight:700; color:#475569'>👤 Full Name</label><input name='full_name' value="{name}" style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'><label style='font-size:11px; font-weight:700; color:#475569'>📧 Email</label><input value="{email}" disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'><label style='font-size:11px; font-weight:700; color:#475569'>📱 Phone</label><input name='phone' value="+254748588874" style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'><label style='font-size:11px; font-weight:700; color:#475569'>🏫 Organization</label><input value="Davischool Platform" disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'><div style='text-align:right; margin-top:16px'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:10px; font-weight:700; font-size:12px'>💾 Save Changes</button></div></form></div>"""
    elif tab == "security":
        right_card = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='font-weight:800; margin-bottom:16px; font-size:14px'>🔒 Security Settings</div><form method='post' action='/profile/change-password'><label style='font-size:11px; font-weight:700; color:#475569'>🔑 Current Password</label><input type='password' name='current_pass' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 14px; background:#f8fafc'><label style='font-size:11px; font-weight:700; color:#475569'>🆕 New Password</label><input type='password' name='new_pass' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 14px; background:#f8fafc'><label style='font-size:11px; font-weight:700; color:#475569'>✅ Confirm New Password</label><input type='password' name='confirm_pass' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 14px; background:#f8fafc'><div style='text-align:right; margin-top:16px'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:10px; font-weight:700; font-size:12px'>🔒 Update Password</button></div></form></div>"""
    else:
        log_rows_html = ""
        for l in logs:
            icon = "👁️" if "Viewed" in l['action'] else "🏫" if "Registered" in l['action'] else "🔐" if "Auth code" in l['action'] else "📊"
            log_rows_html += f"""<div style='padding:12px 0; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; gap:12px'><div style='flex:1'><div style='font-weight:700; font-size:12px'>{icon} {l['action']}</div><div style='font-size:11px; color:#64748b'>{l['details']}</div></div><div style='font-size:10px; color:#64748b; white-space:nowrap'>{l['timestamp']}</div></div>"""
        if not log_rows_html: log_rows_html = "<div style='padding:30px; text-align:center; color:#94a3b8'>No activity yet 📭</div>"
        right_card = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:4px'><div style='font-weight:800; font-size:14px'>📜 Activity Log</div><a href='/profile/clear-logs' style='border:1px solid #e2e8f0; padding:4px 10px; border-radius:8px; font-size:11px; text-decoration:none; color:#475569'>🧹 Clear</a></div><div style='font-size:11px; color:#64748b; margin-bottom:14px'>{total_events} events — EAT</div><div style='border-top:1px solid #f1f5f9; padding-top:8px; max-height:65vh; overflow:auto'>{log_rows_html}</div></div>"""
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials, name, email)}<div style='padding:20px; max-width:1100px; margin:auto'><div style='margin-bottom:16px'><h2 style='margin:0; font-size:20px'>👤 My Profile</h2></div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:0 16px; display:flex; gap:20px; margin-bottom:16px'><a href='/profile?tab=personal' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_personal}'>👤 Personal</a><a href='/profile?tab=security' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_security}'>🔒 Security</a><a href='/profile?tab=activity' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_log}'>📜 Activity Log</a></div><div style='display:grid; grid-template-columns:300px 1fr; gap:20px'>{left_card}{right_card}</div></div></body></html>""")

@app.get("/profile/clear-logs")
def clear_logs(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM activity_log WHERE email=?", (request.session.get("email"),)); con.commit(); con.close()
    return RedirectResponse("/profile?tab=activity", status_code=303)

@app.post("/profile/update")
def profile_update(request: Request, full_name: str = Form(...), phone: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email")
    con = get_db(); cur = con.cursor(); cur.execute("UPDATE users SET full_name=? WHERE email=?", (full_name, email)); con.commit(); con.close()
    request.session["name"] = full_name
    log_activity(email, "✏️ Updated profile", f"Name: {full_name}")
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.post("/profile/change-password")
def change_password(request: Request, current_pass: str = Form(...), new_pass: str = Form(...), confirm_pass: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email")
    if new_pass!= confirm_pass: return HTMLResponse(f"❌ Passwords don't match <a href='/profile?tab=security'>Back</a>")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_pass)); u = cur.fetchone()
    if not u: con.close(); return HTMLResponse(f"❌ Wrong current password <a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_pass, email)); con.commit(); con.close()
    log_activity(email, "🔒 Changed password", "Password updated")
    return RedirectResponse("/profile?tab=security", status_code=303)

@app.get("/health")
def health(): return PlainTextResponse("OK")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f8fafc;margin:0'><div style='background:white;padding:36px 32px;border-radius:16px;border:1px solid #e2e8f0;width:400px'><div style='text-align:center;margin-bottom:24px'><div style='width:52px;height:52px;background:#0f172a;color:white;border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:22px;margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2><p style='font-size:11px;color:#64748b'>ONE LOGIN FOR ALL ROLES 🔐</p></div><form method='post' action='/login'><input name='email' placeholder='📧 Email' required style='width:100%;padding:12px;margin:6px 0 12px;border:1px solid #e2e8f0;border-radius:10px'><input name='password' type='password' placeholder='🔑 Password' required style='width:100%;padding:12px;margin:6px 0 20px;border:1px solid #e2e8f0;border-radius:10px'><button style='width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px'>Sign In → Auto Redirect by Role</button></form></div></body></html>"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password)); u = cur.fetchone()
    school_info = None
    if u: cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],)); school_info = cur.fetchone()
    con.close()
    if not u: return HTMLResponse("❌ Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    if u["role"]!= "super_admin" and school_info: log_activity(u["email"], f"🏫 School login: {school_info['name']}", ""); return RedirectResponse("/school/dashboard", status_code=303)
    log_activity(u["email"], "🔓 Super Admin Logged in", "Viewed dashboard"); return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") == "school_admin": return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools"); total = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 10"); recent = cur.fetchall()
    con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:10px 14px; font-size:12px; font-weight:600'>{s['name']}</td><td style='padding:10px 14px; font-size:12px'>{s['location']}</td><td style='padding:10px 14px'><span style='background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:10px'>Active</span></td><td style='padding:10px 14px; font-size:11px; color:#64748b'>Today</td></tr>"
    if not rows: rows = "<tr><td colspan='4' style='padding:30px; text-align:center; color:#94a3b8'>No schools yet</td></tr>"
    content = f"""<div style='padding:20px; max-width:1400px; margin:auto'><div style='margin-bottom:18px'><h2 style='margin:0; font-size:22px; font-weight:800'>📊 School Overview</h2><p style='margin:4px 0 0; color:#64748b; font-size:13px'>Welcome {name}</p></div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:18px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>{total}</div><div style='font-size:11px; color:#16a34a'>📈 Up 12% from last month</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>{total}</div><div style='font-size:11px; color:#16a34a'>🟢 100% operational</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🔥 TOTAL REVENUE</div><div style='font-size:26px; font-weight:900; margin:12px 0 8px'>KES {total*15000 if total>0 else 0}</div><div style='font-size:11px; color:#16a34a'>💹 +8% monthly growth</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>0</div><div style='font-size:11px; color:#64748b'>👥 Avg 350 per school</div></div></div><div style='display:grid; grid-template-columns:1.9fr 0.8fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #f1f5f9'><div style='font-weight:800; font-size:14px'>🏫 Recently Added Schools</div><a href='/schools/manage' style='font-size:12px; color:#3b82f6; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 14px'>Name</th><th style='padding:10px 14px'>Location</th><th style='padding:10px 14px'>Status</th><th style='padding:10px 14px'>Date</th></tr></thead><tbody>{rows}</tbody></table></div><div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; margin-bottom:16px'><div style='font-weight:800; font-size:14px; margin-bottom:12px'>⚡ Quick Actions</div><a href='/schools/manage' style='display:block; text-align:center; background:white; border:1px solid #e2e8f0; padding:10px; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:600; font-size:13px; margin-bottom:10px; transition:all 0.2s' onmouseover="this.style.background='#0f172a'; this.style.color='white'" onmouseout="this.style.background='white'; this.style.color='#0f172a'">🏫 Manage Schools</a><a href='/schools/manage' style='display:block; text-align:center; background:white; border:1px solid #e2e8f0; padding:10px; border-radius:10px; text-decoration:none; color:#6366f1; font-weight:600; font-size:13px; transition:all 0.2s' onmouseover="this.style.background='#0f172a'; this.style.color='white'" onmouseout="this.style.background='white'; this.style.color='#6366f1'">➕ Register New School</a></div><div style='background:#0f172a; border-radius:14px; padding:16px; color:white'><div style='font-weight:800; font-size:14px; margin-bottom:4px'>📊 Davischool Analytics</div><div style='font-size:11px; color:#94a3b8; margin-bottom:14px'>🛠️ All {total} schools are active</div><div style='background:#1e293b; border-radius:10px; padding:12px'><div style='font-size:10px; color:#94a3b8; letter-spacing:0.5px; margin-bottom:6px'>🔧 PLATFORM HEALTH</div><div style='color:#22c55e; font-weight:800; font-size:14px'>✅ 99.9% Uptime</div><div style='height:4px; background:#334155; border-radius:10px; margin-top:8px'><div style='width:99%; height:100%; background:#22c55e; border-radius:10px'></div></div></div></div></div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials, name, email)}{content}</body></html>")

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools = cur.fetchall()
    cur.execute("SELECT * FROM users WHERE role='school_admin'"); users = cur.fetchall()
    pending = None
    if pending_id:
        cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    con.close()
    users_by_school = {u["school_id"]: u for u in users}
    popup_html = ""
    if success == "code_sent" and pending:
        code_display = " ".join(list(pending["auth_code"]))
        email_active = bool(os.getenv("EMAIL_PASSWORD"))
        if email_active:
            popup_html = f"""<div style='margin-bottom:16px'><div style='background:#fef3c7;border:1px solid #fde68a;padding:12px 16px;border-radius:10px;font-size:13px;font-weight:600;color:#92400e;margin-bottom:12px'>📧 Code sent to oumadavis62@gmail.com! 🔐 Check inbox</div><div style='background:white;border:1.5px solid #fb923c;border-radius:12px;padding:16px'><div style='font-weight:800;font-size:14px;margin-bottom:12px'>🔓 Enter Code for 🏫 {pending["name"]}</div><form method='post' action='/verify-school-code' style='display:flex;gap:10px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='Enter 6-digit code from email' required maxlength='6' style='flex:1;padding:12px;border:1px solid #e2e8f0;border-radius:10px;font-size:18px;letter-spacing:6px;text-align:center;font-weight:700'><button style='background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px;font-weight:700'>✅ Verify</button></form></div></div>"""
        else:
            popup_html = f"""<div style='margin-bottom:16px'><div style='background:white;border:1.5px solid #fb923c;border-radius:12px;padding:16px'><div style='font-weight:800;font-size:14px;margin-bottom:12px'>🔓 Enter Code for 🏫 {pending["name"]}</div><div style='border:1.5px dashed #fb923c;border-radius:10px;padding:18px;text-align:center;background:#fffbeb;margin-bottom:12px'><div style='font-size:28px;font-weight:900;letter-spacing:10px'>🔑 {code_display}</div></div><form method='post' action='/verify-school-code' style='display:flex;gap:10px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' value='{pending["auth_code"]}' required maxlength='6' style='flex:1;padding:12px;border:1px solid #e2e8f0;border-radius:10px;font-size:18px;letter-spacing:6px;text-align:center;font-weight:700'><button style='background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px;font-weight:700'>✅ Verify & Create Login</button></form></div></div>"""
    elif success == "added" and new_pass:
        popup_html = f"""<div id='successModal' style='position:fixed;inset:0;background:rgba(0,0,0,0.45);display:flex;align-items:center;justify-content:center;z-index:9999'><div style='background:white;padding:24px;border-radius:16px;width:420px'><div style='font-size:18px;font-weight:800;margin-bottom:8px'>✅ {school_name} Added!</div><div style='background:#f8fafc;padding:12px;border-radius:10px;font-size:13px;border:1px solid #e2e8f0'><div>🏫 <b>{school_name}</b></div><div>👤 Username: <b>{school_email}</b></div><div>🔑 Password: <b>{new_pass}</b></div></div><div style='display:flex;gap:10px;margin-top:16px'><button onclick="document.getElementById('successModal').style.display='none'" style='flex:1;background:#0f172a;color:white;padding:10px;border:none;border-radius:10px'>OK ✅</button></div></div></div>"""
    rows_html = ""
    for s in schools:
        sid = s["id"]; u = users_by_school.get(sid); upass = u["password"] if u else "—"; uemail = u["email"] if u else s["email"]
        rows_html += f"""<tr onclick="highlightRow(this, {sid})" style='cursor:pointer; border-bottom:1px solid #f1f5f9; user-select:none; caret-color:transparent'><td style='padding:12px 10px; user-select:none'><div style='font-weight:700'>🏫 {s['name']}</div><div style='font-size:10px; color:#64748b'>🔑 Code: <b>{s['code']}</b></div></td><td style='padding:12px 10px; font-size:12px; user-select:none'>📞 {s['phone'] or ''}</td><td style='padding:12px 10px; font-size:11px; user-select:none; max-width:140px; overflow:hidden; text-overflow:ellipsis'>📧 {s['email']}</td><td style='padding:12px 10px; font-size:12px; user-select:none'>📍 {s['location']}</td><td style='padding:12px 10px; font-size:11px; user-select:none'>👤 {uemail}</td><td style='padding:12px 10px; font-size:12px; user-select:none'><span id='pwd-dot-{sid}'>••••••••</span><span id='pwd-real-{sid}' style='display:none; font-weight:700'>{upass}</span> <span onclick="event.stopPropagation(); togglePwd({sid})" style='cursor:pointer'>👁️</span></td><td style='padding:12px 10px; user-select:none'><span id='actions-{sid}' style='display:none; gap:6px'><a href='/schools/edit/{sid}' style='background:#dbeafe; color:#1e40af; padding:6px 10px; border-radius:6px; text-decoration:none; font-size:11px; font-weight:700'>✏️ Edit</a><a href='/schools/delete/{sid}' style='background:#fee2e2; color:#991b1b; padding:6px 10px; border-radius:6px; text-decoration:none; font-size:11px; font-weight:700'>🗑️ Delete</a></span><span id='hint-{sid}' style='font-size:10px; color:#94a3b8'>Click to activate</span></td></tr>"""
    if not rows_html: rows_html = "<tr><td colspan='7' style='padding:40px; text-align:center; color:#94a3b8'>No schools yet</td></tr>"
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc;caret-color:transparent}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px}}.highlight{{background:#e0f2fe!important;border-left:4px solid #0ea5e9!important}}input,select{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px}}table{{user-select:none}}</style></head><body>{header_html(initials, name, email)}<div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px; padding:16px; max-width:1500px; margin:auto'><div><div class='card'>{popup_html}<div style='font-weight:800; font-size:15px'>📚 Registered Schools ({len(schools)})</div><div style='font-size:11px; color:#64748b; margin-bottom:8px'>👉 Click row to highlight 💙</div><div style='overflow:auto; max-height:65vh; border:1px solid #f1f5f9; border-radius:10px'><table style='width:100%; border-collapse:collapse; font-size:13px'><thead style='position:sticky; top:0; background:#f8fafc'><tr style='text-align:left; color:#475569; font-size:11px'><th style='padding:10px'>🏫 School</th><th style='padding:10px'>📞 Contact</th><th style='padding:10px'>📧 Email</th><th style='padding:10px'>📍 Location</th><th style='padding:10px'>👤 Username</th><th style='padding:10px'>🔑 Password</th><th style='padding:10px'>⚙️ Action</th></tr></thead><tbody>{rows_html}</tbody></table></div><a href='/dashboard' class='back-btn' style='margin-top:14px'>⬅️ Back to Dashboard</a></div></div><div class='card' style='height:fit-content; position:sticky; top:16px'><div style='font-weight:800'>➕ Register New School 🏫</div><form method='post' action='/register-school'><input name='school_name' required placeholder='🏫 School Name *'><input name='school_email' required type='email' placeholder='📧 Admin Email *'><input name='location' required placeholder='📍 Location *'><input name='phone' required placeholder='📱 Phone *'><input name='principal' required placeholder='👤 Principal *'><select name='school_type' required><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Primary & Junior Secondary</option></select><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; margin-top:10px'>📧 Send Code & Create Login</button></form></div></div><script>let lastRow=null; function highlightRow(row,id){{if(lastRow) lastRow.classList.remove('highlight'); row.classList.add('highlight'); lastRow=row; document.querySelectorAll('[id^=actions-]').forEach(el=>el.style.display='none'); document.querySelectorAll('[id^=hint-]').forEach(el=>el.style.display='inline'); let act=document.getElementById('actions-'+id); let hint=document.getElementById('hint-'+id); if(act) act.style.display='flex'; if(hint) hint.style.display='none'; window.getSelection().removeAllRanges(); if(document.activeElement) document.activeElement.blur();}} function togglePwd(id){{let d=document.getElementById('pwd-dot-'+id); let r=document.getElementById('pwd-real-'+id); if(d.style.display=='none'){{d.style.display='inline'; r.style.display='none';}} else {{d.style.display='none'; r.style.display='inline';}}}}</script></body></html>""")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code = str(random.randint(100000, 999999))
    con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid; con.commit(); con.close()
    log_activity(SUPER_ADMIN, f"🔐 Auth code sent for {school_name.upper()}", f"Code {auth_code}")
    send_email(SUPER_ADMIN, f"🔐 Code: {auth_code} - {school_name}", f"🏫 {school_name.upper()}\n🔑 CODE: {auth_code}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    if not pending: con.close(); return HTMLResponse("Invalid <a href='/schools/manage'>Back</a>")
    if pending["auth_code"]!= auth_code.strip(): con.close(); return HTMLResponse(f"<h3>❌ Wrong Code!</h3><a href='/schools/manage?success=code_sent&pending_id={pending_id}'>Try Again</a>")
    code = str(random.randint(100000,999999)); unique_pass = generate_unique_password(pending["name"])
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid = cur.lastrowid; cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], unique_pass, "school_admin", pending["principal"], sid))
    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,)); con.commit(); con.close()
    log_activity(SUPER_ADMIN, f"🏫 Registered new school: {pending['name']} ✅", f"Code: {code} | Pass {unique_pass}")
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}&school_name={pending['name']}", status_code=303)

@app.get("/resend-code/{pending_id}")
def resend_code(pending_id: str):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); p = cur.fetchone()
    if p: send_email(SUPER_ADMIN, f"🔐 Code: {p['auth_code']} - {p['name']}", f"🔑 CODE: {p['auth_code']}")
    con.close(); return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.get("/schools/delete/{sid}")
def delete_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM schools WHERE id=?", (sid,)); cur.execute("DELETE FROM users WHERE school_id=?", (sid,)); con.commit(); con.close()
    return RedirectResponse("/schools/manage", status_code=303)

@app.get("/schools/edit/{sid}", response_class=HTMLResponse)
def edit_school_page(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone()
    cur.execute("SELECT * FROM users WHERE school_id=? AND role='school_admin'", (sid,)); u = cur.fetchone(); con.close()
    if not s: return RedirectResponse("/schools/manage")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper()
    stype = s['school_type']
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}} input,select{{width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px;max-width:500px;margin:30px auto}}</style></head><body>{header_html(initials, name, email)}<div class='card'><h3>✏️ Edit School - {s['name']}</h3><form method='post' action='/schools/edit/{sid}'><input name='school_name' value="{s['name']}" required><input name='school_email' value="{s['email']}" required><input name='location' value="{s['location']}" required><input name='phone' value="{s['phone']}" required><input name='principal' value="{s['principal']}" required><select name='school_type' required><option {"selected" if stype=="Primary" else ""}>Primary</option><option {"selected" if stype=="Secondary" else ""}>Secondary</option><option {"selected" if stype in ["Primary & Secondary", "Primary & Junior Secondary"] else ""}>Primary & Junior Secondary</option></select><input name='new_password' placeholder='New Password (blank keep old)'><div style='display:flex;gap:10px;margin-top:12px'><button style='flex:1;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px'>💾 Save Changes</button><a href='/schools/manage' class='back-btn' style='flex:1; justify-content:center'>❌ Cancel</a></div><a href='/dashboard' class='back-btn' style='margin-top:14px; width:100%; justify-content:center; box-sizing:border-box'>⬅️ Back to Dashboard</a></form></div></body></html>""")

@app.post("/schools/edit/{sid}")
def edit_school_save(sid: int, request: Request, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...), new_password: str = Form("")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, sid))
    if new_password.strip():
        cur.execute("UPDATE users SET email=?, full_name=?, password=? WHERE school_id=? AND role='school_admin'", (school_email.strip(), principal.strip(), new_password.strip(), sid))
    else:
        cur.execute("UPDATE users SET email=?, full_name=? WHERE school_id=? AND role='school_admin'", (school_email.strip(), principal.strip(), sid))
    con.commit(); con.close()
    log_activity(request.session.get("email",""), f"✏️ Edited School {school_name}", f"ID {sid}")
    return RedirectResponse("/schools/manage", status_code=303)

# ========== SCHOOL DASHBOARD - OVERVIEW ==========
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
    cur.execute("SELECT SUM(paid) as t FROM fees WHERE school_id=?", (school["id"],))
    fees_row = cur.fetchone(); fees_total = fees_row["t"] if fees_row and fees_row["t"] else 0
    cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY id DESC LIMIT 5", (school["id"],)); recent_students = cur.fetchall()
    con.close()
    stu_rows = ""
    for st in recent_students:
        stu_rows += f"<tr><td style='padding:10px 12px; font-size:12px'>{st['name']}</td><td style='padding:10px 12px; font-size:11px'>{st['admission_no'] or st['assessment_no'] or ''}</td><td style='padding:10px 12px; font-size:11px'>{st['gender']}</td><td style='padding:10px 12px; font-size:11px'>Class {st['class_id'] or ''}</td></tr>"
    if not stu_rows:
        stu_rows = "<tr><td colspan='4' style='padding:30px; text-align:center; color:#94a3b8; font-size:13px'>No students yet - Add students to start</td></tr>"
    html = school_header(school, name, "dashboard")
    html += f"""
    <div style='padding:18px'>
        <div style='background:linear-gradient(135deg,#0f172a,#1e3a8a); border-radius:16px; padding:18px 20px; color:white; display:flex; justify-content:space-between; align-items:center; margin-bottom:16px'>
          <div><div style='font-size:20px; font-weight:900'>DaviSchool Management System 🚀</div><div style='font-size:12px; color:#bfdbfe; margin-top:2px'>REVOLUTIONIZE YOUR SCHOOL'S MANAGEMENT!</div><div style='font-size:10px; background:rgba(255,255,255,0.15); display:inline-block; padding:4px 10px; border-radius:20px; margin-top:8px'>WORKS FOR ALL LEVELS: PRE-PRIMARY, PRIMARY, JUNIOR, SENIOR | 8-4-4 SUPPORTED</div></div>
          <div style='text-align:right'><div style='font-size:28px; font-weight:900'>{sc}</div><div style='font-size:10px; color:#94a3b8'>Total Students</div><div style='font-size:10px; background:#16a34a; color:white; padding:4px 8px; border-radius:12px; margin-top:6px; display:inline-block'>✅ GET EVERYTHING DONE IN MINUTES!</div></div>
        </div>
        <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:12px'>
          <a href='/school/students' class='ds-card'><div style='font-size:10px; color:#64748b; font-weight:700'>🎓 TOTAL STUDENTS</div><div style='font-size:26px; font-weight:900; margin:8px 0'>{sc}</div><div style='font-size:10px; color:#3b82f6'>📊 Active</div></a>
          <a href='/school/classes' class='ds-card'><div style='font-size:10px; color:#64748b; font-weight:700'>🏫 CLASSES</div><div style='font-size:26px; font-weight:900; margin:8px 0'>{cc}</div><div style='font-size:10px; color:#64748b'>Streams & Levels</div></a>
          <a href='/school/exams' class='ds-card'><div style='font-size:10px; color:#64748b; font-weight:700'>📝 EXAMS</div><div style='font-size:26px; font-weight:900; margin:8px 0'>{ec}</div><div style='font-size:10px; color:#3b82f6'>Deep Insights</div></a>
          <a href='/school/fees' class='ds-card'><div style='font-size:10px; color:#64748b; font-weight:700'>💰 FEES COLLECTED</div><div style='font-size:18px; font-weight:900; margin:8px 0'>KES {fees_total}</div><div style='font-size:10px; color:#16a34a'>✅ Managed</div></a>
        </div>
        <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:12px'>
          <a href='/school/analysis' class='ds-card'><div style='font-size:20px'>📊</div><div style='font-size:11px; font-weight:800; margin-top:4px'>EXAM MARKS ANALYSIS</div><div style='font-size:9px; color:#64748b; margin-top:2px'>DEEP PERFORMANCE INSIGHTS</div></a>
          <a href='/school/ranking' class='ds-card'><div style='font-size:20px'>🏆</div><div style='font-size:11px; font-weight:800; margin-top:4px'>ACCURATE RANKING</div><div style='font-size:9px; color:#64748b; margin-top:2px'>INSTANT CLASS & LEVEL RANKING</div></a>
          <a href='/school/marksheets' class='ds-card'><div style='font-size:20px'>📄</div><div style='font-size:11px; font-weight:800; margin-top:4px'>GENERATES MARKSHEETS</div><div style='font-size:9px; color:#64748b; margin-top:2px'>CREATE RECORD SHEETS QUICKLY</div></a>
          <a href='/school/reports' class='ds-card'><div style='font-size:20px'>📑</div><div style='font-size:11px; font-weight:800; margin-top:4px'>STUDENT REPORTS</div><div style='font-size:9px; color:#64748b; margin-top:2px'>AUTOMATED REPORT CARD GENERATION</div></a>
        </div>
        <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px'>
          <a href='/school/marksheets' class='ds-card'><div style='font-size:20px'>📁</div><div style='font-size:11px; font-weight:800; margin-top:4px'>GENERATES MARKSHEETS</div><div style='font-size:9px; color:#64748b; margin-top:2px'>CREATE ACCURATE RECORD SHEETS</div></a>
          <a href='/school/timetable' class='ds-card'><div style='font-size:20px'>🗓️</div><div style='font-size:11px; font-weight:800; margin-top:4px'>SMART TIMETABLING</div><div style='font-size:9px; color:#64748b; margin-top:2px'>LESSON ALERTS FOR TEACHERS</div></a>
          <a href='/school/fees' class='ds-card'><div style='font-size:20px'>💰</div><div style='font-size:11px; font-weight:800; margin-top:4px'>FINANCING & FEES</div><div style='font-size:9px; color:#64748b; margin-top:2px'>MANAGE ACCOUNTS & FEES</div></a>
          <a href='/school/sms' class='ds-card'><div style='font-size:20px'>💬</div><div style='font-size:11px; font-weight:800; margin-top:4px'>BULK SMS TO PARENTS</div><div style='font-size:9px; color:#64748b; margin-top:2px'>EASY BULK SMS NOTIFICATIONS</div></a>
        </div>
        <div style='display:grid; grid-template-columns:1.9fr 0.8fr; gap:14px'>
          <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #f1f5f9'><div style='font-weight:800; font-size:14px'>🎓 Recently Added Students</div><a href='/school/students' style='font-size:11px; color:#3b82f6; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:10px; color:#64748b'><th style='padding:10px 12px'>Name</th><th style='padding:10px 12px'>Adm No</th><th style='padding:10px 12px'>Gender</th><th style='padding:10px 12px'>Class</th></tr></thead><tbody>{stu_rows}</tbody></table></div>
          <div style='background:#0f172a; border-radius:14px; padding:16px; color:white; height:fit-content'><div style='font-weight:800; font-size:14px; margin-bottom:12px'>📊 DaviSchool Management System</div><div style='font-size:10px; color:#94a3b8; letter-spacing:0.5px; margin-bottom:12px'>STUDENT REPORT</div><div style='display:flex; flex-direction:column; gap:10px'><div style='display:flex; justify-content:space-between; align-items:center; background:#1e293b; padding:8px 10px; border-radius:8px'><div style='display:flex; align-items:center; gap:8px'><div style='width:24px; height:24px; background:#3b82f6; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px'>👤</div><div style='font-size:11px'>Top Student</div></div><div style='background:#22c55e; color:white; font-size:10px; padding:2px 6px; border-radius:6px'>G</div></div><div style='display:flex; justify-content:space-between; align-items:center; background:#1e293b; padding:8px 10px; border-radius:8px'><div style='display:flex; align-items:center; gap:8px'><div style='width:24px; height:24px; background:#ec4899; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px'>👤</div><div style='font-size:11px'>Second</div></div><div style='background:#3b82f6; color:white; font-size:10px; padding:2px 6px; border-radius:6px'>B</div></div><div style='display:flex; justify-content:space-between; align-items:center; background:#1e293b; padding:8px 10px; border-radius:8px'><div style='display:flex; align-items:center; gap:8px'><div style='width:24px; height:24px; background:#f59e0b; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px'>👤</div><div style='font-size:11px'>Third</div></div><div style='background:#f59e0b; color:white; font-size:10px; padding:2px 6px; border-radius:6px'>G</div></div></div><div style='font-size:8px; color:#64748b; margin-top:14px; line-height:1.3'>CONTACT US: 0111392013 | WhatsApp: 0111392013 — GET EVERYTHING DONE IN MINUTES!</div></div>
        </div>
    </div>
    </div></div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{html}</body></html>")

# ========== CLASSES & STREAMS - INTEGRATED ==========
@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall()
    con.close()
    rows = ""
    for c in classes:
        rows += f"<tr><td style='padding:10px 12px; font-size:12px; font-weight:600'>🏫 {c['name']}</td><td style='padding:10px 12px; font-size:12px'>🔀 {c['stream'] or c['level'] or ''}</td><td style='padding:10px 12px'><a href='/school/classes/delete/{c['id']}' style='background:#fee2e2; color:#991b1b; padding:4px 8px; border-radius:6px; text-decoration:none; font-size:11px'>🗑️ Delete</a></td></tr>"
    if not rows: rows = "<tr><td colspan='3' style='padding:30px; text-align:center; color:#94a3b8'>No classes yet — Add classes to populate Student dropdowns</td></tr>"
    header = school_header(school, name, "classes")
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}
    <div style='padding:18px; max-width:1200px; margin:auto'>
      <div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'>
          <div style='padding:14px 16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>🏫 Classes & Streams ({len(classes)})</b><span style='font-size:11px; color:#64748b'>These populate Students → Select Class dropdown</span></div>
          <table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 12px'>Class</th><th style='padding:10px 12px'>Stream</th><th style='padding:10px 12px'>Action</th></tr></thead><tbody>{rows}</tbody></table>
        </div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; height:fit-content'>
          <b>➕ Add Class & Stream</b>
          <form method='post' action='/school/classes/add' style='margin-top:10px'>
            <input name='class_name' required placeholder='🏫 Class Name * e.g. Form 1, Class 4, Grade 5' class='input-field'>
            <input name='stream' required placeholder='🔀 Stream * e.g. East, West, Blue, Red' class='input-field'>
            <button class='add-btn' style='margin-top:8px'>➕ Add Class</button>
          </form>
          <div style='font-size:11px; color:#64748b; margin-top:10px'>This class & stream will appear in Students tab → Select Class & Select Stream dropdowns</div>
          <a href='/school/students' style='display:block; text-align:center; margin-top:12px; padding:10px; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:600; font-size:12px'>🎓 Go to Students →</a>
        </div>
      </div>
    </div></div></div></body></html>""")

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO classes (school_id, name, level, stream) VALUES (?,?,?,?)", (school["id"], class_name.strip().upper(), stream.strip(), stream.strip()))
    con.commit(); con.close()
    log_activity(request.session.get("email",""), f"🏫 Added class {class_name} - {stream}", "")
    return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/classes/delete/{cid}")
def delete_class(cid: int, request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=?", (cid,)); con.commit(); con.close()
    return RedirectResponse("/school/classes", status_code=303)

# ========== STUDENTS TAB - AUTOMATED AS PER SCREENSHOT ==========
@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT s.*, c.name as class_name, c.stream as class_stream FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall()
    con.close()

    # Class dropdown options from classes table
    class_options = ""
    stream_options_set = set()
    class_names_set = set()
    for cl in classes:
        cname = cl['name']; sname = cl['stream'] or cl['level'] or ''
        class_options += f"<option value='{cname}|{sname}|{cl['id']}'>🏫 {cname} - {sname}</option>"
        stream_options_set.add(sname)
        class_names_set.add(cname)

    # Build distinct class dropdown and stream dropdown
    distinct_class_opts = ""
    for cn in sorted(class_names_set):
        distinct_class_opts += f"<option value='{cn}'>{cn}</option>"
    distinct_stream_opts = ""
    for st in sorted(stream_options_set):
        if st:
            distinct_stream_opts += f"<option value='{st}'>{st}</option>"

    if not class_options:
        class_options = "<option value=''>⚠️ No classes — Add in Classes & Streams first</option>"

    student_rows = ""
    for st in students:
        assessment_no = st['assessment_no'] or st['admission_no'] or ''
        student_rows += f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px; font-size:12px; font-weight:600'>🎓 {st['name']}</td><td style='padding:10px 12px; font-size:11px'>{assessment_no}</td><td style='padding:10px 12px; font-size:11px'>{st['class_name'] or ''}</td><td style='padding:10px 12px; font-size:11px'>{st['stream'] or st['class_stream'] or ''}</td><td style='padding:10px 12px; font-size:11px'>{st['gender']}</td><td style='padding:10px 12px; font-size:11px'>{st['parent_phone'] or ''}</td><td style='padding:10px 12px'><a href='/school/students/delete/{st['id']}' style='background:#fee2e2; color:#991b1b; padding:4px 8px; border-radius:6px; text-decoration:none; font-size:11px'>🗑️</a></td></tr>"
    if not student_rows:
        student_rows = "<tr><td colspan='7' style='padding:40px; text-align:center; color:#94a3b8'>No students yet</td></tr>"

    header = school_header(school, name, "students")
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style>
    <script>
    function updateStreamDropdown() {{
      let classSelect = document.getElementById('classSelect');
      let streamSelect = document.getElementById('streamSelect');
      // Filter streams based on class - data from server
      let allClasses = {str([dict(c) for c in classes])};
      let selectedClass = classSelect.value;
      streamSelect.innerHTML = '<option value=\"\">🔀 Select Stream *</option>';
      let streams = [];
      for (let cl of allClasses) {{
        if (cl.name === selectedClass) {{
          if (!streams.includes(cl.stream)) streams.push(cl.stream);
        }}
      }}
      if (streams.length===0) {{
        // If no streams filtered, show all streams
        for (let cl of allClasses) {{
          if (cl.stream &&!streams.includes(cl.stream)) streams.push(cl.stream);
        }}
      }}
      for (let s of streams) {{
        let opt = document.createElement('option');
        opt.value = s; opt.textContent = '🔀 ' + s;
        streamSelect.appendChild(opt);
      }}
    }}
    </script>
    </head><body>{header}
    <div style='padding:18px; max-width:1400px; margin:auto'>
      <div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'>
          <div style='padding:14px 16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; align-items:center'>
            <b>🎓 Students ({len(students)})</b>
            <span style='font-size:11px; color:#64748b'>DaviSchool Management System</span>
          </div>
          <div style='overflow:auto; max-height:75vh'>
            <table style='width:100%; border-collapse:collapse'>
              <thead style='position:sticky; top:0; background:#f0f9ff; text-align:left; font-size:11px; color:#475569'><tr><th style='padding:10px 12px'>Name</th><th style='padding:10px 12px'>Assessment No</th><th style='padding:10px 12px'>Class</th><th style='padding:10px 12px'>Stream</th><th style='padding:10px 12px'>Gender</th><th style='padding:10px 12px'>Parent Phone</th><th style='padding:10px 12px'>Action</th></tr></thead>
              <tbody>{student_rows}</tbody>
            </table>
          </div>
        </div>

        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; height:fit-content; position:sticky; top:18px'>
          <div style='font-weight:800; margin-bottom:12px'>➕ Add New Student</div>
          <form method='post' action='/school/students/add'>
            <input name='assessment_no' required placeholder='🆔 Assessment No *' class='input-field'>
            <input name='student_name' required placeholder='👤 Student Name *' class='input-field'>
            <select id='classSelect' name='class_name' required class='input-field' onchange='updateStreamDropdown()'>
              <option value=''>🏫 Select Class *</option>
              {distinct_class_opts}
            </select>
            <select id='streamSelect' name='stream' required class='input-field'>
              <option value=''>🔀 Select Stream *</option>
              {distinct_stream_opts}
            </select>
            <select name='gender' required class='input-field'>
              <option value=''>⚧️ Gender *</option>
              <option value='Male'>Male</option>
              <option value='Female'>Female</option>
            </select>
            <input name='parent_name' placeholder='👨‍👩‍👧 Parent Name' class='input-field'>
            <input name='parent_phone' required placeholder='📞 Parent Phone *' class='input-field'>
            <button class='add-btn' style='margin-top:8px'>➕ Add Student</button>
          </form>
          <div style='font-size:10px; color:#64748b; margin-top:8px'>Class & Stream dropdowns auto-populate from Classes & Streams you add. <a href='/school/classes' style='color:#3b82f6; text-decoration:none'>Go add classes →</a></div>
        </div>
      </div>
    </div></div></div></body></html>""")

@app.post("/school/students/add")
def add_student(request: Request, assessment_no: str = Form(...), student_name: str = Form(...), class_name: str = Form(...), stream: str = Form(...), gender: str = Form(...), parent_name: str = Form(""), parent_phone: str = Form(...)):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    # Find or create class_id matching class_name + stream
    cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND (stream=? OR level=?)", (school["id"], class_name.strip().upper(), stream.strip(), stream.strip()))
    cls = cur.fetchone()
    if cls:
        class_id = cls["id"]
    else:
        # Auto create class if not exists
        cur.execute("INSERT INTO classes (school_id, name, level, stream) VALUES (?,?,?,?)", (school["id"], class_name.strip().upper(), stream.strip(), stream.strip()))
        class_id = cur.lastrowid
    cur.execute("INSERT INTO students (school_id, admission_no, assessment_no, name, class_id, gender, parent_name, parent_phone, stream) VALUES (?,?,?,?,?,?,?,?,?)", (school["id"], assessment_no.strip(), assessment_no.strip(), student_name.strip().upper(), class_id, gender, parent_name.strip(), parent_phone.strip(), stream.strip()))
    con.commit(); con.close()
    log_activity(request.session.get("email",""), f"🎓 Added student {student_name}", f"Assessment {assessment_no} Class {class_name} Stream {stream}")
    return RedirectResponse("/school/students", status_code=303)

@app.get("/school/students/delete/{sid}")
def delete_student(sid: int, request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=?", (sid,)); con.commit(); con.close()
    return RedirectResponse("/school/students", status_code=303)

@app.get("/school/{page}", response_class=HTMLResponse)
def school_generic(page: str, request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    if page in ["students","classes","dashboard"]: return RedirectResponse(f"/school/{page}")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    header = school_header(school, name, page)
    return HTMLResponse(f"<html><head><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.back-btn{{display:inline-flex; padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px}}.back-btn:hover{{background:#0f172a!important; color:white!important}}</style></head><body>{header}<div style='padding:20px'><h2>{page.title()} — {school['name']}</h2><p style='color:#64748b'>This module is part of DaviSchool Management System</p><a href='/school/dashboard' class='back-btn'>⬅️ Back to Overview</a></div></div></body></html>")

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/")
