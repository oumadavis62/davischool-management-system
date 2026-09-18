from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi import status
from starlette.exceptions import HTTPException as StarletteHTTPException
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random
from datetime import datetime
from zoneinfo import ZoneInfo

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v45-live-fix-final")
SUPER_ADMIN = "oumadavis62@gmail.com"

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
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, assessment_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_phone TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT, initial TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY, school_id INTEGER, term_name TEXT, year TEXT, start_date TEXT, end_date TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, email TEXT, phone TEXT, tsc_no TEXT, gender TEXT, id_no TEXT, role TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teacher_allocations (id INTEGER PRIMARY KEY, school_id INTEGER, teacher_id INTEGER, subject_id INTEGER, class_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS global_notices (id INTEGER PRIMARY KEY, message TEXT, created_at TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit(); con.close()
init_db()

def log_activity(email, action, details=""):
    try:
        con = get_db(); cur = con.cursor()
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO activity_log (email, action, details, timestamp) VALUES (?,?,?,?)", (email, action, details, ts))
        con.commit(); con.close()
    except: pass

def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0: return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    s = cur.fetchone(); con.close(); return s

def generate_unique_password(name):
    p = "".join([c for c in name.upper() if c.isalpha()])[:4]
    if len(p)<3: p="SCH"
    return f"{p}@{random.randint(1000,9999)}!"

def header_html(initials, name, email):
    return f"""
    <style>.do-avatar{{width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #e2e8f0}}.dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#0f172a;color:white}}</style>
    <div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px;color:#64748b'>{name} • Super Admin • 🌍 Global Control Active</div></div><div style='position:relative'><div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div><div id='profileDropdown' style='display:none;position:absolute;right:0;top:44px;background:white;border:1px solid #e2e8f0;border-radius:12px;width:220px;box-shadow:0 10px 25px rgba(0,0,0,0.12);z-index:1000;overflow:hidden'><div style='padding:14px;border-bottom:1px solid #f1f5f9;background:#f8fafc'><div style='font-weight:700;font-size:13px'>{name}</div><div style='font-size:11px;color:#64748b'>{email}</div></div><a href='/profile?tab=personal' class='dropdown-item' style='color:#0f172a'>👤 Profile</a><a href='/super/global-control' class='dropdown-item' style='color:#0f172a'>🌍 Global Control</a><a href='/logout' class='dropdown-item' style='color:#dc2626'>🚪 Logout</a></div></div></div><script>function toggleProfileMenu(){{let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none';}}</script>
    """

def school_header(school, name, active="dashboard", is_impersonating=False):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    def nav(link, icon, label):
        is_active = "background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569;background:transparent"
        return f"<a href='/school/{link}' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active}'>{icon} {label}</a>"
    def sub_nav(link, icon, label):
        is_sel = "background:#e2e8f0;color:#0f172a;font-weight:800;border-radius:8px" if active==link else "color:#475569"
        return f"<a href='/school/{link}' style='display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:2px;{is_sel}'>{icon} {label}</a>"
    impersonate_banner = f"""<div style='background:#f59e0b;color:#0f172a;padding:8px 20px;text-align:center;font-weight:800;font-size:12px;display:flex;justify-content:center;gap:12px;align-items:center'>⚠️ Super Admin viewing as {school['name']} — <a href='/super/back-to-admin' style='background:#0f172a;color:white;padding:6px 12px;border-radius:8px;text-decoration:none;font-size:11px'>🔙 Back to Super Admin</a></div>""" if is_impersonating else ""
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 1"); notice = cur.fetchone(); con.close()
    notice_banner = f"""<div style='background:#0f172a;color:white;padding:8px 20px;text-align:center;font-size:12px'>📢 {notice['message']} — {notice['created_at']}</div>""" if notice else ""
    return f"""<style>.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.academic-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:800;margin-bottom:4px;background:#0f172a;color:white}}</style><div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20].upper()}</b><div style='font-size:10px;color:#64748b'>🔑 {school['code']} | {school['location']}</div></div></div></div>{nav('dashboard','📊','Dashboard')}{nav('students','🎓','Students')}{nav('classes','🏫','Classes & Streams')}{nav('subjects','📚','Subjects')}<div style='margin-bottom:4px'><div class='academic-header' onclick='toggleAcademic()'><span>📖 Academic Manager</span><span id='academicArrow'>⌃</span></div><div id='academicDropdown' style='display:block;margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('dean-settings','⚙️','Dean Settings')}{sub_nav('exams','🔧','Exam Settings')}{sub_nav('marks','📄','Set Marks')}{sub_nav('subject-allocation','📋','Subject Allocation')}{sub_nav('marks','✏️','Record Marks')}{sub_nav('marks','📄','Edit Marks')}{sub_nav('marksheets','☰','Marks Status')}{sub_nav('analysis','📊','Exam Analysis')}{sub_nav('spreadsheet','📄','Spreadsheet')}{sub_nav('sba','📋','SBA (KNEC CBA)')}</div></div>{nav('ranking','🏆','Ranking')}{nav('reports','📑','Student Reports')}{nav('teachers','👨‍🏫','Staff Manager')}{nav('timetable','🗓️','Smart Timetable')}{nav('fees','💰','Fees & Finance')}{nav('sms','💬','Bulk SMS Parents')}<div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/logout' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'>{impersonate_banner}{notice_banner}<div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>{school['name']} (Code: {school['code']})</b></div><div style='display:flex;align-items:center;gap:12px'><div style='width:28px;height:28px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px'>{initials}</div><div style='font-size:11px'><b>{name}</b>{' <span style="background:#f59e0b;color:#0f172a;padding:2px 6px;border-radius:6px;font-size:9px;margin-left:4px">SUPER</span>' if is_impersonating else ''}</div></div></div><script>function toggleAcademic(){{let d=document.getElementById('academicDropdown'); let a=document.getElementById('academicArrow'); if(d.style.display==='none'){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}</script>"""

# ===== ROOT — MUST BE FIRST FOR RENDER =====
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f0f2f5;display:flex;height:100vh}
.blue-bar{width:32px;background:#0d8bf2;flex-shrink:0}
.main{flex:1;display:flex;justify-content:center;align-items:center;padding:20px;position:relative}
.card{background:white;width:540px;max-width:100%;padding:48px 48px 40px;border-radius:6px;box-shadow:0 0 0 1px #e2e8f0;text-align:center}
.logo-box{width:72px;height:72px;background:#0f172a;color:white;border-radius:18px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:32px;margin:0 auto}
.input{width:100%;padding:14px 16px;border:1px solid #e2e8f0;border-radius:10px;background:#fcfcfc;font-size:14px;outline:none;box-sizing:border-box;text-align:left}
.input:focus{border-color:#0f172a;background:white}
.pw{position:relative}
.eye{position:absolute;right:14px;top:50%;transform:translateY(-50%);cursor:pointer;color:#94a3b8;font-size:18px}
.sign{background:#0d8bf2;color:white;width:100%;padding:15px;border:none;border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;margin-top:10px}
.sign:hover{background:#0f172a}
.help{position:fixed;right:0;top:45%;background:#0a7a42;color:white;padding:14px 10px;border-radius:12px 0 0 12px;font-weight:800;font-size:13px;writing-mode:vertical-rl;cursor:pointer;z-index:20}
.ask{position:fixed;right:24px;bottom:24px;background:#0d8bf2;color:white;padding:14px 20px;border-radius:28px;font-weight:800;font-size:14px;display:flex;align-items:center;gap:8px;box-shadow:0 8px 24px rgba(13,139,242,0.35);cursor:pointer;z-index:20}
</style>
</head>
<body>
<div class="blue-bar"></div>
<div class="main">
  <div class="card">
    <div class="logo-box">D</div>
    <h1 style="margin:16px 0 0;font-size:40px;font-weight:900;color:#0f172a">DaviSchool</h1>
    <div style="margin-top:12px;color:#334155;font-size:15px">Sign in to your Davischool account</div>
    <form method="post" action="/login" style="margin-top:30px;text-align:left">
      <label style="font-size:13px;font-weight:700;display:block;margin-bottom:8px">Username or Email</label>
      <input name="email" class="input" placeholder="Enter your username or email" required style="margin-bottom:20px">
      <label style="font-size:13px;font-weight:700;display:block;margin-bottom:8px">Password</label>
      <div class="pw" style="margin-bottom:18px">
        <input id="pwd" name="password" type="password" class="input" placeholder="Enter your password" required style="padding-right:44px">
        <span class="eye" id="eye" onclick="togglePwd()">👁️</span>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px">
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:#475569;cursor:pointer"><input type="checkbox" style="width:16px;height:16px"> Remember me</label>
        <a href="#" style="font-size:13px;color:#0a7a42;text-decoration:none;font-weight:700">Forgot Password?</a>
      </div>
      <button class="sign">Sign In</button>
    </form>
  </div>
</div>
<div class="help">💬 Help</div>
<div class="ask">💬 Ask Davis</div>
<script>
function togglePwd(){
  let p=document.getElementById('pwd');
  let e=document.getElementById('eye');
  if(p.type==='password'){p.type='text'; e.textContent='🙈';}
  else {p.type='password'; e.textContent='👁️';}
}
</script>
</body></html>
"""

@app.head("/")
def home_head():
    return PlainTextResponse("OK")

@app.get("/health")
def health(): return PlainTextResponse("OK")

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password)); u = cur.fetchone()
    school_info = None
    if u: cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],)); school_info = cur.fetchone()
    con.close()
    if not u: return HTMLResponse("❌ Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    request.session["is_impersonating"]=False
    if u["role"]!= "super_admin" and school_info: log_activity(u["email"], f"🏫 School login: {school_info['name']}", ""); return RedirectResponse("/school/dashboard", status_code=303)
    log_activity(u["email"], "🔓 Super Admin Logged in", "Viewed dashboard"); return RedirectResponse("/dashboard", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/")

@app.get("/super/switch-to-school/{sid}")
def switch_to_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone(); con.close()
    if not s: return RedirectResponse("/schools/manage")
    request.session["school_id"]=sid; request.session["is_impersonating"]=True
    return RedirectResponse("/school/dashboard", status_code=303)

@app.get("/super/back-to-admin")
def back_to_admin(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    request.session["school_id"]=0; request.session["is_impersonating"]=False
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, tab: str = "personal"):
    if "email" not in request.session: return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM activity_log WHERE email=?", (email,)); total_events = cur.fetchone()["c"]
    cur.execute("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 20", (email,)); logs = cur.fetchall()
    con.close()
    active_personal = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="personal" else "color:#64748b"
    active_security = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="security" else "color:#64748b"
    active_log = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="activity" else "color:#64748b"
    left_card = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; text-align:center; height:fit-content'><div style='width:80px; height:80px; background:#a8d8ff; color:#1e3a8a; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:900; font-size:28px; margin:0 auto 12px'>{initials}</div><div style='font-weight:800; font-size:16px'>{name}</div><div style='background:#e0f2fe; color:#0369a1; padding:4px 12px; border-radius:20px; font-size:11px; font-weight:700; display:inline-block; margin:6px 0'>Super Admin</div><div style='font-size:12px; color:#64748b; margin-top:4px'>{email}</div><a href='/dashboard' style='margin-top:20px; justify-content:center; display:flex; padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px'>⬅️ Back to Dashboard</a></div>"""
    if tab == "personal":
        right_card = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='font-weight:800; margin-bottom:16px; font-size:14px'>👤 Personal Information</div><form method='post' action='/profile/update'><label style='font-size:11px; font-weight:700'>👤 Full Name</label><input name='full_name' value="{name}" style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'><label style='font-size:11px; font-weight:700'>📧 Email</label><input value="{email}" disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'><label style='font-size:11px; font-weight:700'>📱 Phone</label><input name='phone' value="+254748588874" style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'><label style='font-size:11px; font-weight:700'>🏫 Organization</label><input value="Davischool Platform" disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'><div style='text-align:right; margin-top:16px'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:10px; font-weight:700; font-size:12px'>💾 Save Changes</button></div></form></div>"""
    elif tab == "security":
        right_card = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='font-weight:800; margin-bottom:16px; font-size:14px'>🔒 Security Settings</div><form method='post' action='/profile/change-password'><label style='font-size:11px; font-weight:700'>🔑 Current Password</label><input type='password' name='current_pass' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 14px; background:#f8fafc'><label style='font-size:11px; font-weight:700'>🆕 New Password</label><input type='password' name='new_pass' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 14px; background:#f8fafc'><label style='font-size:11px; font-weight:700'>✅ Confirm New Password</label><input type='password' name='confirm_pass' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 14px; background:#f8fafc'><div style='text-align:right; margin-top:16px'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:10px; font-weight:700; font-size:12px'>🔒 Update Password</button></div></form></div>"""
    else:
        log_rows = "".join([f"""<div style='padding:12px 0; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; gap:12px'><div style='flex:1'><div style='font-weight:700; font-size:12px'>📊 {l['action']}</div><div style='font-size:11px; color:#64748b'>{l['details']}</div></div><div style='font-size:10px; color:#64748b; white-space:nowrap'>{l['timestamp']}</div></div>""" for l in logs]) or "<div style='padding:30px; text-align:center; color:#94a3b8'>No activity yet 📭</div>"
        right_card = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:4px'><div style='font-weight:800; font-size:14px'>📜 Activity Log</div><a href='/profile/clear-logs' style='border:1px solid #e2e8f0; padding:4px 10px; border-radius:8px; font-size:11px; text-decoration:none; color:#475569'>🧹 Clear</a></div><div style='font-size:11px; color:#64748b; margin-bottom:14px'>{total_events} events — EAT</div><div style='border-top:1px solid #f1f5f9; padding-top:8px; max-height:65vh; overflow:auto'>{log_rows}</div></div>"""
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials, name, email)}<div style='padding:20px; max-width:1100px; margin:auto'><div style='margin-bottom:16px'><h2 style='margin:0; font-size:20px'>👤 My Profile</h2></div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:0 16px; display:flex; gap:20px; margin-bottom:16px'><a href='/profile?tab=personal' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_personal}'>👤 Personal</a><a href='/profile?tab=security' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_security}'>🔒 Security</a><a href='/profile?tab=activity' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_log}'>📜 Activity Log</a></div><div style='display:grid; grid-template-columns:300px 1fr; gap:20px'>{left_card}{right_card}</div></div></body></html>""")

@app.get("/profile/clear-logs")
def clear_logs(request: Request):
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM activity_log WHERE email=?", (request.session.get("email"),)); con.commit(); con.close()
    return RedirectResponse("/profile?tab=activity", status_code=303)
@app.post("/profile/update")
def profile_update(request: Request, full_name: str = Form(...), phone: str = Form(...)):
    email = request.session.get("email"); con = get_db(); cur = con.cursor(); cur.execute("UPDATE users SET full_name=? WHERE email=?", (full_name, email)); con.commit(); con.close()
    request.session["name"] = full_name; return RedirectResponse("/profile?tab=personal", status_code=303)
@app.post("/profile/change-password")
def change_password(request: Request, current_pass: str = Form(...), new_pass: str = Form(...), confirm_pass: str = Form(...)):
    email = request.session.get("email")
    if new_pass!=confirm_pass: return HTMLResponse("Mismatch <a href='/profile?tab=security'>Back</a>")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_pass)); u = cur.fetchone()
    if not u: con.close(); return HTMLResponse("Wrong <a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_pass, email)); con.commit(); con.close()
    return RedirectResponse("/profile?tab=security", status_code=303)

@app.get("/super/global-control", response_class=HTMLResponse)
def global_control(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM schools"); total_schools = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM students"); total_students = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes"); total_classes = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM subjects"); total_subjects = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM teachers"); total_teachers = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams"); total_exams = cur.fetchone()["c"]
    cur.execute("SELECT c.name as class_name, s.gender, COUNT(*) as cnt FROM students s LEFT JOIN classes c ON s.class_id=c.id GROUP BY c.name, s.gender ORDER BY c.name")
    gender_rows = cur.fetchall()
    cur.execute("SELECT s.*, sc.name as school_name FROM students s LEFT JOIN schools sc ON s.school_id=sc.id ORDER BY s.id DESC LIMIT 5")
    recent_students = cur.fetchall()
    cur.execute("SELECT name, stream, COUNT(*) cnt FROM classes GROUP BY name, stream ORDER BY name LIMIT 20"); g_classes = cur.fetchall()
    cur.execute("SELECT name, code, initial, COUNT(*) cnt FROM subjects GROUP BY name ORDER BY name LIMIT 20"); g_subjects = cur.fetchall()
    cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 5"); notices = cur.fetchall()
    cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 1"); latest_notice = cur.fetchone()
    con.close()
    stats = {}; tb=0; tg=0
    for r in gender_rows:
        cn = (r['class_name'] or 'UNASSIGNED').upper()
        if cn not in stats: stats[cn] = {'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys'] = r['cnt']; tb += r['cnt']
        else: stats[cn]['girls'] = r['cnt']; tg += r['cnt']
    total = tb+tg; ratio = round(tg/tb,2) if tb>0 else 0; max_v = max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    chart_html = ""
    for cls_name, v in stats.items():
        bh = int((v['boys']/max_v)*150) if v['boys']>0 else 6
        gh = int((v['girls']/max_v)*150) if v['girls']>0 else 6
        chart_html += f"<div style='text-align:center; min-width:90px'><div style='display:flex; gap:10px; align-items:end; justify-content:center; height:170px'><div><div style='width:42px; height:{bh}px; background:#0a84ff; border-radius:6px 6px 0 0'></div><div style='font-size:10px; font-weight:700; color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px; height:{gh}px; background:#ff2d92; border-radius:6px 6px 0 0'></div><div style='font-size:10px; font-weight:700; color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px; font-weight:800; margin-top:8px'>{cls_name}</div></div>"
    if not chart_html: chart_html = "<div style='padding:30px; color:#94a3b8; text-align:center; width:100%'>No students yet</div>"
    stu_rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px; font-size:12px'>{st['name']} <span style='font-size:10px;color:#64748b'>({st['school_name'] or ''})</span></td><td style='padding:10px 12px; font-size:11px'>{st['assessment_no'] or st['admission_no'] or ''}</td><td style='padding:10px 12px; font-size:11px'>{st['gender']}</td><td>Class {st['class_id'] or ''}</td></tr>" for st in recent_students]) or "<tr><td colspan='4' style='padding:30px; text-align:center; color:#94a3b8'>No students yet</td></tr>"
    class_rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{c['name']}</td><td style='padding:10px 12px;font-size:12px'>{c['stream'] or ''}</td><td style='padding:10px 12px'><span style='background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:10px'>In {c['cnt']} schools</span></td></tr>" for c in g_classes]) or "<tr><td colspan='3' style='padding:20px;text-align:center;color:#94a3b8'>No classes yet</td></tr>"
    subj_rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{s['name']}</td><td style='padding:10px 12px;font-size:12px'>{s['code'] or ''}</td><td style='padding:10px 12px;font-size:12px'>{s['initial'] or ''}</td><td style='padding:10px 12px'><span style='background:#dbeafe;color:#1e40af;padding:3px 8px;border-radius:12px;font-size:10px'>{s['cnt']} schools</span></td></tr>" for s in g_subjects]) or "<tr><td colspan='4' style='padding:20px;text-align:center;color:#94a3b8'>No subjects yet</td></tr>"
    notice_banner = f"""<div style='background:#0f172a;color:white;padding:8px 20px;text-align:center;font-size:12px'>📢 {latest_notice['message']} — {latest_notice['created_at']}</div>""" if latest_notice else ""
    def g_nav(link, icon, label, active=False):
        is_active = "background:#0f172a;color:white;font-weight:800" if active else "color:#475569;background:transparent"
        href = f"/super/global-control#{link}" if link!="dashboard" else "/super/global-control"
        return f"<a href='{href}' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active}'>{icon} {label}</a>"
    def g_sub_nav(link, icon, label):
        return f"<a href='/super/global-control#{link}' style='display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:2px;color:#475569'>{icon} {label}</a>"
    sidebar = f"""
    <div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'>
      <div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div><div><b style='font-size:13px'>GLOBAL CONTROL</b><div style='font-size:10px;color:#64748b'>🔑 ALL | ALL SCHOOLS</div></div></div></div>
      {g_nav('dashboard','📊','Dashboard', active=True)}{g_nav('students','🎓','Students')}{g_nav('classes','🏫','Classes & Streams')}{g_nav('subjects','📚','Subjects')}<div style='margin-bottom:4px'><div class='academic-header' onclick='toggleAcademic()'><span>📖 Academic Manager</span><span id='academicArrow'>⌃</span></div><div id='academicDropdown' style='display:block;margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{g_sub_nav('dean-settings','⚙️','Dean Settings')}{g_sub_nav('exams','🔧','Exam Settings')}{g_sub_nav('marks','📄','Set Marks')}{g_sub_nav('subject-allocation','📋','Subject Allocation')}</div></div>{g_nav('ranking','🏆','Ranking')}{g_nav('reports','📑','Student Reports')}{g_nav('teachers','👨‍🏫','Staff Manager')}{g_nav('timetable','🗓️','Smart Timetable')}{g_nav('fees','💰','Fees & Finance')}{g_nav('sms','💬','Bulk SMS Parents')}<div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/dashboard' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#0f172a;background:#f8fafc;font-weight:700'>⬅️ Back to Super Admin</a><a href='/logout' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div>
    """
    return HTMLResponse(f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.push-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:800;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px}}.academic-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:800;margin-bottom:4px;background:#0f172a;color:white}}</style></head><body><div style='display:flex;min-height:100vh'>{sidebar}<div style='flex:1;background:#f8fafc'>{notice_banner}<div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>GLOBAL CONTROL (Code: ALL) — Photocopy of School Side</b><div style='font-size:10px;color:#64748b'>🌍 {total_schools} schools • Edit once → updates ALL</div></div><div style='display:flex;align-items:center;gap:12px'><div style='width:28px;height:28px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px'>{initials}</div><div style='font-size:11px'><b>{name}</b> <span style="background:#0f172a;color:white;padding:2px 6px;border-radius:6px;font-size:9px">SUPER</span></div></div></div><script>function toggleAcademic(){{let d=document.getElementById('academicDropdown'); let a=document.getElementById('academicArrow'); if(d.style.display==='none'){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}</script><div style='padding:18px; max-width:1400px; margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%); border-radius:18px; padding:22px 24px; color:white; display:flex; justify-content:space-between; align-items:center; margin-bottom:16px'><div><div style='font-size:22px; font-weight:900'>DaviSchool Management System 🚀 — GLOBAL</div><div style='font-size:12px; color:#bfdbfe; margin-top:4px'>Same as School Overview</div></div><div style='text-align:right'><div style='font-size:34px; font-weight:900'>{total_students}</div><div style='font-size:11px'>Total Students (ALL)</div></div></div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:14px'><a class='ds-card'><div style='font-size:11px; color:#64748b; font-weight:700'>🎓 TOTAL STUDENTS (ALL)</div><div style='font-size:30px; font-weight:900; margin:10px 0'>{total_students}</div></a><a class='ds-card'><div style='font-size:11px; color:#64748b; font-weight:700'>🏫 CLASSES (ALL)</div><div style='font-size:30px; font-weight:900; margin:10px 0'>{total_classes}</div></a><a class='ds-card'><div style='font-size:11px; color:#64748b; font-weight:700'>📝 EXAMS (ALL)</div><div style='font-size:30px; font-weight:900; margin:10px 0'>{total_exams}</div></a><a class='ds-card'><div style='font-size:11px; color:#64748b; font-weight:700'>👨‍🏫 STAFF (ALL)</div><div style='font-size:30px; font-weight:900; margin:10px 0'>{total_teachers}</div></a></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; margin-bottom:16px'><div style='display:flex; justify-content:space-between'><div><div style='font-weight:800; font-size:14px'>👥 Students by Gender — ALL Schools</div></div><div style='display:flex; gap:12px; font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex; gap:24px; overflow-x:auto; margin-top:18px'>{chart_html}</div></div><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px; margin-bottom:16px'><div id='classes' style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between;'><b>🏫 Global Classes — Same as School Classes Window</b><span style='background:#0f172a;color:white;padding:4px 10px;border-radius:12px;font-size:10px'>🌍 Push to ALL</span></div><div style='overflow:auto; max-height:280px'><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 12px'>CLASS</th><th style='padding:10px 12px'>STREAM</th><th style='padding:10px 12px'>SCHOOLS</th></tr></thead><tbody>{class_rows}</tbody></table></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; height:fit-content'><div style='font-weight:800; margin-bottom:10px'>➕ Add Global Class</div><form method='post' action='/super/global-control/add-class'><input name='class_name' required placeholder='Class e.g. GRADE 7' class='input-field'><input name='stream' required placeholder='Stream e.g. EAST' class='input-field'><button class='push-btn'>🌍 Push to ALL {total_schools} Schools</button></form></div></div><div id='subjects' style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px; margin-bottom:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>📚 Global Subjects — Same as School Subjects</b><span style='background:#0f172a;color:white;padding:4px 10px;border-radius:12px;font-size:10px'>🌍 Push to ALL</span></div><div style='overflow:auto; max-height:280px'><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 12px'>NAME</th><th style='padding:10px 12px'>CODE</th><th style='padding:10px 12px'>INITIAL</th><th style='padding:10px 12px'>SCHOOLS</th></tr></thead><tbody>{subj_rows}</tbody></table></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; height:fit-content'><div style='font-weight:800; margin-bottom:10px'>➕ Add Global Subject</div><form method='post' action='/super/global-control/add-subject'><input name='subject_name' required placeholder='Subject' class='input-field'><input name='code' placeholder='Code' class='input-field'><input name='initial' placeholder='Initial' class='input-field'><button class='push-btn'>🌍 Push to ALL {total_schools} Schools</button></form></div></div><div id='broadcast' style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-weight:800; margin-bottom:10px'>📢 Broadcast Notice to ALL Schools</div><form method='post' action='/super/global-control/add-notice'><input name='message' required placeholder='Type notice e.g. System maintenance tonight 10pm' class='input-field'><button class='push-btn'>📢 Broadcast to ALL {total_schools} Schools</button></form><div style='margin-top:12px; border:1px solid #f1f5f9; border-radius:10px; padding:0 12px; max-height:200px; overflow:auto'>{"".join([f"<div style='padding:10px 0;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><div><b style='font-size:12px'>📢 {n['message']}</b><div style='font-size:10px;color:#64748b'>{n['created_at']}</div></div><a href='/super/global-control/delete-notice/{n['id']}' style='color:#dc2626;text-decoration:none'>🗑️</a></div>" for n in notices]) or "<div style='padding:20px;text-align:center;color:#94a3b8'>No notices yet</div>"}</div></div><div style='background:#0f172a; border-radius:14px; padding:16px; color:white; height:fit-content'><div style='font-weight:800'>✅ Photocopy Complete</div><div style='font-size:11px; color:#94a3b8; margin-top:8px; line-height:1.6'>Sidebar = same as school side<br>Dashboard = same<br>Each has Push to ALL button<br>Broadcast shows as banner on all schools</div><a href='/dashboard' style='display:block; margin-top:12px; text-align:center; background:white; color:#0f172a; padding:10px; border-radius:10px; text-decoration:none; font-weight:700'>⬅️ Back to Super Admin</a></div></div></div></div></div></body></html>
""")

@app.post("/super/global-control/add-class")
def global_add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (sch["id"], class_name.strip().upper(), stream.strip().upper()))
        if not cur.fetchone():
            cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (sch["id"], class_name.strip().upper(), stream.strip().upper()))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control#classes",303)

@app.post("/super/global-control/add-subject")
def global_add_subject(request: Request, subject_name: str = Form(...), code: str = Form(""), initial: str = Form("")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=?", (sch["id"], subject_name.strip().upper()))
        if not cur.fetchone():
            cur.execute("INSERT INTO subjects (school_id, name, code, initial) VALUES (?,?,?,?)", (sch["id"], subject_name.strip().upper(), code.strip().upper(), initial.strip().upper()))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control#subjects",303)

@app.post("/super/global-control/add-term")
def global_add_term(request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM terms WHERE school_id=? AND term_name=? AND year=?", (sch["id"], term_name, year))
        if not cur.fetchone():
            cur.execute("INSERT INTO terms (school_id, term_name, year, start_date, end_date) VALUES (?,?,?,?,?)", (sch["id"], term_name, year, start_date, end_date))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control",303)

@app.post("/super/global-control/add-exam")
def global_add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM exams WHERE school_id=? AND name=? AND year=?", (sch["id"], exam_name.strip().upper(), year))
        if not cur.fetchone():
            cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (sch["id"], exam_name.strip().upper(), term, year, exam_type))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control",303)

@app.post("/super/global-control/add-notice")
def global_add_notice(request: Request, message: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M")
    cur.execute("INSERT INTO global_notices (message, created_at) VALUES (?,?)", (message.strip(), ts))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control#broadcast",303)

@app.get("/super/global-control/delete-notice/{nid}")
def delete_notice(nid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM global_notices WHERE id=?", (nid,)); con.commit(); con.close()
    return RedirectResponse("/super/global-control#broadcast",303)

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
    content = f"""<div style='padding:20px; max-width:1400px; margin:auto'><div style='margin-bottom:18px'><h2 style='margin:0; font-size:22px; font-weight:800'>📊 School Overview</h2><p style='margin:4px 0 0; color:#64748b; font-size:13px'>Welcome {name}</p></div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:18px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>{total}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>{total}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🔥 TOTAL REVENUE</div><div style='font-size:26px; font-weight:900; margin:12px 0 8px'>KES {total*15000 if total>0 else 0}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>0</div></div></div><div style='display:grid; grid-template-columns:1.9fr 0.8fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #f1f5f9'><div style='font-weight:800; font-size:14px'>🏫 Recently Added Schools</div><a href='/schools/manage' style='font-size:12px; color:#3b82f6; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 14px'>Name</th><th style='padding:10px 14px'>Location</th><th style='padding:10px 14px'>Status</th><th style='padding:10px 14px'>Date</th></tr></thead><tbody>{rows}</tbody></table></div><div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; margin-bottom:16px'><div style='font-weight:800; font-size:14px; margin-bottom:12px'>⚡ Quick Actions</div><a href='/schools/manage' style='display:block; text-align:center; background:white; border:1px solid #e2e8f0; padding:10px; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:600; font-size:13px; margin-bottom:10px'>🏫 Manage Schools</a><a href='/super/global-control' style='display:block; text-align:center; background:#0f172a; color:white; padding:10px; border-radius:10px; text-decoration:none; font-weight:700; font-size:13px; margin-bottom:10px'>🌍 Global School Control — Photocopy</a></div></div></div></div>"""
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
    if pending_id: cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    con.close()
    users_by_school = {u["school_id"]: u for u in users}
    popup_html = ""
    if success == "code_sent" and pending:
        code_display = " ".join(list(pending["auth_code"]))
        popup_html = f"""<div style='margin-bottom:16px'><div style='background:white;border:1.5px solid #fb923c;border-radius:12px;padding:16px'><div style='font-weight:800;margin-bottom:12px'>🔓 Enter Code for {pending["name"]}</div><div style='border:1.5px dashed #fb923c;border-radius:10px;padding:18px;text-align:center;background:#fffbeb;margin-bottom:12px'><div style='font-size:28px;font-weight:900;letter-spacing:10px'>{code_display}</div></div><form method='post' action='/verify-school-code' style='display:flex;gap:10px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' value='{pending["auth_code"]}' required style='flex:1;padding:12px;border:1px solid #e2e8f0;border-radius:10px;text-align:center;font-weight:700'><button style='background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px'>✅ Verify</button></form></div></div>"""
    elif success == "added" and new_pass:
        popup_html = f"""<div style='position:fixed;inset:0;background:rgba(0,0,0,0.45);display:flex;align-items:center;justify-content:center;z-index:9999'><div style='background:white;padding:24px;border-radius:16px;width:420px'><div style='font-size:18px;font-weight:800'>✅ {school_name} Added!</div><div style='background:#f8fafc;padding:12px;border-radius:10px;margin:12px 0;font-size:13px'><div>🏫 {school_name}</div><div>👤 {school_email}</div><div>🔑 {new_pass}</div></div><button onclick="this.closest('div').parentElement.style.display='none'" style='width:100%;background:#0f172a;color:white;padding:10px;border:none;border-radius:10px'>OK</button></div></div>"""
    rows_html = ""
    for s in schools:
        u = users_by_school.get(s['id'])
        rows_html += f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:12px 10px'><div style='font-weight:700'>🏫 {s['name']}</div><div style='font-size:10px; color:#64748b'>🔑 {s['code']}</div></td><td style='padding:12px 10px; font-size:12px'>{s['phone'] or ''}</td><td style='padding:12px 10px; font-size:11px'>{s['email']}</td><td style='padding:12px 10px; font-size:12px'>{s['location']}</td><td style='padding:12px 10px; font-size:11px'>{u['email'] if u else s['email']}</td><td style='padding:12px 10px; font-size:12px'>{u['password'] if u else '—'}</td><td style='padding:12px 10px; display:flex; gap:6px; flex-wrap:wrap'><a href='/super/switch-to-school/{s['id']}' style='background:#0f172a; color:white; padding:6px 10px; border-radius:6px; text-decoration:none; font-size:11px; font-weight:700'>👁️ View</a><a href='/schools/edit/{s['id']}' style='background:#dbeafe; color:#1e40af; padding:6px 10px; border-radius:6px; text-decoration:none; font-size:11px'>✏️ Edit</a><a href='/schools/delete/{s['id']}' style='background:#fee2e2; color:#991b1b; padding:6px 10px; border-radius:6px; text-decoration:none; font-size:11px'>🗑️</a></td></tr>"
    if not rows_html: rows_html = "<tr><td colspan='7' style='padding:40px; text-align:center'>No schools</td></tr>"
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px}}input,select{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px}}</style></head><body>{header_html(initials, name, email)}<div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px; padding:16px; max-width:1500px; margin:auto'><div><div class='card'>{popup_html}<div style='font-weight:800'>📚 Registered Schools ({len(schools)})</div><div style='overflow:auto; max-height:65vh; border:1px solid #f1f5f9; border-radius:10px; margin-top:10px'><table style='width:100%; border-collapse:collapse; font-size:13px'><thead style='position:sticky; top:0; background:#f8fafc'><tr style='text-align:left; font-size:11px'><th style='padding:10px'>School</th><th>Contact</th><th>Email</th><th>Location</th><th>Username</th><th>Password</th><th>Action</th></tr></thead><tbody>{rows_html}</tbody></table></div><a href='/dashboard' style='margin-top:14px; display:inline-block; padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px'>⬅️ Back</a></div></div><div class='card' style='height:fit-content'><div style='font-weight:800'>➕ Register New School</div><form method='post' action='/register-school'><input name='school_name' required placeholder='🏫 School Name *'><input name='school_email' required type='email' placeholder='📧 Admin Email *'><input name='location' required placeholder='📍 Location *'><input name='phone' required placeholder='📱 Phone *'><input name='principal' required placeholder='👤 Principal *'><select name='school_type' required><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Primary & Junior Secondary</option></select><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; margin-top:10px'>📧 Send Code</button></form><a href='/super/global-control' style='display:block; text-align:center; margin-top:12px; background:#0f172a; color:white; padding:12px; border-radius:10px; text-decoration:none; font-weight:700'>🌍 Global Control Photocopy</a></div></div></body></html>""")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code = str(random.randint(100000, 999999)); con = get_db(); cur = con.cursor()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid; con.commit(); con.close()
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    if not pending: con.close(); return HTMLResponse("Invalid <a href='/schools/manage'>Back</a>")
    if pending["auth_code"]!= auth_code.strip(): con.close(); return HTMLResponse(f"❌ Wrong Code <a href='/schools/manage?success=code_sent&pending_id={pending_id}'>Back</a>")
    code = str(random.randint(100000,999999)); unique_pass = generate_unique_password(pending["name"])
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid = cur.lastrowid; cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], unique_pass, "school_admin", pending["principal"], sid))
    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,)); con.commit(); con.close()
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}&school_name={pending['name']}", status_code=303)

@app.get("/schools/delete/{sid}")
def delete_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM schools WHERE id=?", (sid,)); cur.execute("DELETE FROM users WHERE school_id=?", (sid,)); con.commit(); con.close()
    return RedirectResponse("/schools/manage", status_code=303)

@app.get("/schools/edit/{sid}", response_class=HTMLResponse)
def edit_school_page(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone(); con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com"); initials = "".join([p[0] for p in name.split()][:2]).upper()
    return HTMLResponse(f"""<html><body>{header_html(initials, name, email)}<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; max-width:500px; margin:30px auto'><h3>✏️ Edit {s['name']}</h3><form method='post' action='/schools/edit/{sid}'><input name='school_name' value="{s['name']}" required><input name='school_email' value="{s['email']}" required><input name='location' value="{s['location']}" required><input name='phone' value="{s['phone']}" required><input name='principal' value="{s['principal']}" required><input name='new_password' placeholder='New Password blank keep old'><div style='display:flex; gap:10px; margin-top:12px'><button style='flex:1; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>💾 Save</button><a href='/schools/manage' style='flex:1; text-align:center; padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700'>❌ Cancel</a></div></form></div></body></html>""")

@app.post("/schools/edit/{sid}")
def edit_school_save(sid: int, request: Request, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), new_password: str = Form("")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=? WHERE id=?", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), sid))
    if new_password.strip(): cur.execute("UPDATE users SET email=?, full_name=?, password=? WHERE school_id=? AND role='school_admin'", (school_email.strip(), principal.strip(), new_password.strip(), sid))
    else: cur.execute("UPDATE users SET email=?, full_name=? WHERE school_id=? AND role='school_admin'", (school_email.strip(), principal.strip(), sid))
    con.commit(); con.close(); return RedirectResponse("/schools/manage", status_code=303)

@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    if request.session.get("role")=="super_admin" and request.session.get("school_id",0)==0:
        return RedirectResponse("/dashboard")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM teachers WHERE school_id=?", (school["id"],)); tc = cur.fetchone()["c"]
    cur.execute("SELECT c.name as class_name, s.gender, COUNT(*) as cnt FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? GROUP BY c.name, s.gender ORDER BY c.name", (school["id"],))
    gender_rows = cur.fetchall()
    cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY id DESC LIMIT 5", (school["id"],)); recent_students = cur.fetchall()
    con.close()
    stats = {}; tb=0; tg=0
    for r in gender_rows:
        cn = (r['class_name'] or 'UNASSIGNED').upper()
        if cn not in stats: stats[cn] = {'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys'] = r['cnt']; tb += r['cnt']
        else: stats[cn]['girls'] = r['cnt']; tg += r['cnt']
    total = tb+tg; ratio = round(tg/tb,2) if tb>0 else 0; max_v = max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    chart_html = ""
    for cls_name, v in stats.items():
        bh = int((v['boys']/max_v)*150) if v['boys']>0 else 6
        gh = int((v['girls']/max_v)*150) if v['girls']>0 else 6
        chart_html += f"<div style='text-align:center; min-width:90px'><div style='display:flex; gap:10px; align-items:end; justify-content:center; height:170px'><div><div style='width:42px; height:{bh}px; background:#0a84ff; border-radius:6px 6px 0 0'></div><div style='font-size:10px; font-weight:700; color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px; height:{gh}px; background:#ff2d92; border-radius:6px 6px 0 0'></div><div style='font-size:10px; font-weight:700; color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px; font-weight:800; margin-top:8px'>{cls_name}</div></div>"
    if not chart_html: chart_html = "<div style='padding:30px; color:#94a3b8; text-align:center; width:100%'>No students yet</div>"
    stu_rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px; font-size:12px'>{st['name']}</td><td style='padding:10px 12px; font-size:11px'>{st['assessment_no'] or st['admission_no'] or ''}</td><td style='padding:10px 12px; font-size:11px'>{st['gender']}</td><td>Class {st['class_id'] or ''}</td></tr>" for st in recent_students]) or "<tr><td colspan='4' style='padding:30px; text-align:center; color:#94a3b8'>No students yet</td></tr>"
    header = school_header(school, name, "dashboard", is_impersonating=is_imp)
    html = f"""<div style='padding:18px; max-width:1400px; margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%); border-radius:18px; padding:22px 24px; color:white; display:flex; justify-content:space-between; align-items:center; margin-bottom:16px'><div><div style='font-size:22px; font-weight:900'>DaviSchool Management System 🚀</div><div style='font-size:12px; color:#bfdbfe; margin-top:4px'>REVOLUTIONIZE YOUR SCHOOL'S MANAGEMENT!</div></div><div style='text-align:right'><div style='font-size:34px; font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students</div></div></div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:14px'><a href='/school/students' class='ds-card'><div style='font-size:11px; color:#64748b; font-weight:700'>🎓 TOTAL STUDENTS</div><div style='font-size:30px; font-weight:900; margin:10px 0'>{sc}</div></a><a href='/school/classes' class='ds-card'><div style='font-size:11px; color:#64748b; font-weight:700'>🏫 CLASSES</div><div style='font-size:30px; font-weight:900; margin:10px 0'>{cc}</div></a><a href='/school/exams' class='ds-card'><div style='font-size:11px; color:#64748b; font-weight:700'>📝 EXAMS</div><div style='font-size:30px; font-weight:900; margin:10px 0'>{ec}</div></a><a href='/school/teachers' class='ds-card'><div style='font-size:11px; color:#64748b; font-weight:700'>👨‍🏫 STAFF</div><div style='font-size:30px; font-weight:900; margin:10px 0'>{tc}</div></a></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; margin-bottom:16px'><div style='display:flex; justify-content:space-between'><div><div style='font-weight:800; font-size:14px'>👥 Students by Gender</div><div style='font-size:11px; color:#64748b'>Boys vs Girls enrollment per form — auto updates</div></div><div style='display:flex; gap:12px; font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex; gap:24px; overflow-x:auto; margin-top:18px'>{chart_html}</div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:18px; border-top:1px solid #f1f5f9; padding-top:14px'><div style='background:#f0f9ff; padding:12px; border-radius:10px; text-align:center'><div style='font-size:11px'>Total Boys</div><div style='font-size:20px; font-weight:900; color:#0a84ff'>{tb}</div></div><div style='background:#fdf2f8; padding:12px; border-radius:10px; text-align:center'><div style='font-size:11px'>Total Girls</div><div style='font-size:20px; font-weight:900; color:#ff2d92'>{tg}</div></div><div style='background:#f8fafc; padding:12px; border-radius:10px; text-align:center'><div style='font-size:11px'>Total</div><div style='font-size:20px; font-weight:900'>{total}</div></div><div style='background:#f0fdf4; padding:12px; border-radius:10px; text-align:center'><div style='font-size:11px'>Ratio</div><div style='font-size:20px; font-weight:900'>{ratio}:1</div></div></div></div><div style='display:grid; grid-template-columns:1.9fr 0.8fr; gap:14px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><div style='font-weight:800'>🎓 Recent Students</div><a href='/school/students' style='font-size:11px; color:#3b82f6; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:10px; color:#64748b'><th style='padding:10px 12px'>Name</th><th>Adm No</th><th>Gender</th><th>Class</th></tr></thead><tbody>{stu_rows}</tbody></table></div><div style='background:#0f172a; border-radius:14px; padding:16px; color:white; height:fit-content'><div style='font-weight:800; font-size:14px'>📊 LIVE</div><div style='background:#1e293b; border-radius:10px; padding:12px; margin-top:10px'><div style='font-size:11px'>👦 {tb} | 👧 {tg}</div><div style='font-size:11px; margin-top:6px; color:#22c55e'>Auto ✅</div></div></div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall()
    con.close()
    total = len(students)
    class_opts = "".join([f"<option value='{c['id']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px; font-size:12px'>{st['assessment_no'] or st['admission_no'] or ''}</td><td style='padding:10px 12px; font-size:12px'>{st['name']}</td><td style='padding:10px 12px; font-size:12px'>{st['gender'] or ''}</td><td style='padding:10px 12px; font-size:12px'>{st['class_name'] or ''}</td><td style='padding:10px 12px; font-size:12px'>{st['parent_phone'] or ''}</td><td style='padding:10px 12px'><a href='/school/students/delete/{st['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️ Delete</a></td></tr>" for st in students]) or "<tr><td colspan='6' style='padding:30px; text-align:center; color:#94a3b8'>No students yet</td></tr>"
    header = school_header(school, name, "students", is_impersonating=is_imp)
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px; max-width:1400px; margin:auto'><h2 style='margin:0; font-size:20px; font-weight:800'>🎓 Students ({total})</h2><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px; margin-top:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px'><b>📚 Students List</b></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 12px'>ADM NO</th><th style='padding:10px 12px'>NAME</th><th style='padding:10px 12px'>GENDER</th><th style='padding:10px 12px'>CLASS</th><th style='padding:10px 12px'>PHONE</th><th style='padding:10px 12px'>ACTION</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px'>⬅️ Back to Overview</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; height:fit-content'><div style='font-weight:800; margin-bottom:10px'>➕ Add Student</div><form method='post' action='/school/students/add'><input name='assessment_no' required placeholder='🆔 Assessment No *' class='input-field'><input name='student_name' required placeholder='👤 Student Name *' class='input-field'><select name='class_id' required class='input-field'><option value=''>🏫 Select Class *</option>{class_opts}</select><select name='gender' required class='input-field'><option value=''>⚧️ Gender *</option><option value='Male'>Male</option><option value='Female'>Female</option></select><input name='parent_phone' placeholder='📞 Parent Phone' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Student</button></form></div></div></div></div></div></body></html>""")

@app.post("/school/students/add")
def add_student_simple(request: Request, assessment_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_phone: str = Form("")):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, admission_no, assessment_no, name, class_id, gender, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], assessment_no.strip().upper(), assessment_no.strip().upper(), student_name.strip().upper(), class_id, gender, parent_phone.strip())); con.commit(); con.close()
    return RedirectResponse("/school/students", status_code=303)

@app.get("/school/students/delete/{sid}")
def delete_student_simple(sid: int):
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=?", (sid,)); con.commit(); con.close()
    return RedirectResponse("/school/students",303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY id DESC", (school["id"],)); subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px; font-size:12px'>{s['name']}</td><td style='padding:10px 12px; font-size:12px'>{s['code'] or ''}</td><td style='padding:10px 12px; font-size:12px'>{s['initial'] or ''}</td><td style='padding:10px 12px'><a href='/school/subjects/delete/{s['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️ Delete</a></td></tr>" for s in subs]) or "<tr><td colspan='4' style='padding:30px; text-align:center; color:#94a3b8'>No subjects yet</td></tr>"
    header = school_header(school, name, "subjects", is_impersonating=is_imp)
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px; max-width:1200px; margin:auto'><h2 style='margin:0; font-size:20px; font-weight:800'>📚 Subjects ({len(subs)})</h2><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px; margin-top:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px'><b>📚 Subjects List</b></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 12px'>NAME</th><th style='padding:10px 12px'>CODE</th><th style='padding:10px 12px'>INITIAL</th><th style='padding:10px 12px'>ACTION</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px'>⬅️ Back</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; height:fit-content'><div style='font-weight:800; margin-bottom:10px'>➕ Add Subject</div><form method='post' action='/school/subjects/add'><input name='subject_name' required placeholder='📚 Subject Name *' class='input-field'><input name='code' placeholder='🔢 Code' class='input-field'><input name='initial' placeholder='🔤 Initial' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Subject</button></form></div></div></div></div></div></body></html>""")

@app.post("/school/subjects/add")
def add_subject_simple(request: Request, subject_name: str = Form(...), code: str = Form(""), initial: str = Form("")):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO subjects (school_id, name, code, initial) VALUES (?,?,?,?)", (school["id"], subject_name.strip().upper(), code.strip().upper(), initial.strip().upper())); con.commit(); con.close()
    return RedirectResponse("/school/subjects",303)

@app.get("/school/subjects/delete/{sid}")
def delete_subject_simple(sid: int):
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE id=?", (sid,)); con.commit(); con.close()
    return RedirectResponse("/school/subjects",303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px 12px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><a href='/school/classes/delete/{c['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No classes</td></tr>"
    header = school_header(school, name, "classes", is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px'><div style='padding:14px'><b>🏫 Classes ({len(classes)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px'>⬅️ Back</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><b>➕ Add Class</b><form method='post' action='/school/classes/add'><input name='class_name' required placeholder='Class Name *' class='input-field'><input name='stream' required placeholder='Stream *' class='input-field'><button class='add-btn' style='margin-top:8px'>Add</button></form></div></div></div></div></div></body></html>")

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (school["id"], class_name.strip().upper(), stream.strip().upper())); con.commit(); con.close()
    return RedirectResponse("/school/classes",303)

@app.get("/school/classes/delete/{cid}")
def delete_class(cid: int):
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=?", (cid,)); con.commit(); con.close()
    return RedirectResponse("/school/classes",303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school["id"],)); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px 12px'>{e['name']}</td><td>{e['term']}</td><td>{e['year']}</td><td><span style='background:#0f172a;color:white;padding:3px 8px;border-radius:12px;font-size:10px'>{e['exam_type'] or ''}</span></td><td><a href='/school/exams/delete/{e['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No exams</td></tr>"
    header = school_header(school, name, "exams", is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px'><div style='padding:14px'><b>📝 Exams ({len(exams)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px'>⬅️ Back</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><b>➕ Add Exam</b><form method='post' action='/school/exams/add'><input name='exam_name' required placeholder='Exam Name *' class='input-field'><select name='term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='2026' class='input-field'><select name='exam_type' required class='input-field'><option>Main Exam</option><option>Opening Exam</option><option>Mid Term Exam</option><option>End Term Exam</option></select><button class='add-btn' style='margin-top:8px'>Add</button></form></div></div></div></div></div></body></html>")

@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip())); con.commit(); con.close()
    return RedirectResponse("/school/exams",303)

@app.get("/school/exams/delete/{eid}")
def del_exam(eid: int):
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM exams WHERE id=?", (eid,)); con.commit(); con.close()
    return RedirectResponse("/school/exams",303)

@app.get("/school/dean-settings", response_class=HTMLResponse)
def dean_settings(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY id DESC", (school["id"],)); terms = cur.fetchall()
    con.close()
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px; font-size:12px'>{t['term_name']}</td><td style='padding:10px 12px; font-size:12px'>{t['year']}</td><td style='padding:10px 12px; font-size:12px'>{t['start_date']}</td><td style='padding:10px 12px; font-size:12px'>{t['end_date']}</td><td style='padding:10px 12px'><a href='/school/dean-settings/delete-term/{t['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️ Delete</a></td></tr>" for t in terms]) or "<tr><td colspan='5' style='padding:30px; text-align:center; color:#94a3b8'>No terms yet</td></tr>"
    header = school_header(school, name, "dean-settings", is_impersonating=is_imp)
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px; max-width:1200px; margin:auto'><h2 style='margin:0; font-size:20px; font-weight:800'>⚙️ Dean Settings</h2><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px; margin-top:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px'><b>📅 Terms List</b></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 12px'>TERM</th><th style='padding:10px 12px'>YEAR</th><th style='padding:10px 12px'>START</th><th style='padding:10px 12px'>END</th><th style='padding:10px 12px'>ACTION</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px'>⬅️ Back to Overview</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; height:fit-content'><div style='font-weight:800; margin-bottom:10px'>➕ Add Term</div><form method='post' action='/school/dean-settings/add-term'><select name='term_name' required class='input-field'><option value=''>Select Term *</option><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='📅 Year e.g. 2026' class='input-field'><input name='start_date' type='date' required class='input-field'><input name='end_date' type='date' required class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Term</button></form></div></div></div></div></div></body></html>""")

@app.post("/school/dean-settings/add-term")
def add_term(request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO terms (school_id, term_name, year, start_date, end_date) VALUES (?,?,?,?,?)", (school["id"], term_name, year, start_date, end_date)); con.commit(); con.close()
    return RedirectResponse("/school/dean-settings", status_code=303)

@app.get("/school/dean-settings/delete-term/{tid}")
def delete_term(tid: int):
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM terms WHERE id=?", (tid,)); con.commit(); con.close()
    return RedirectResponse("/school/dean-settings", status_code=303)

@app.get("/school/teachers", response_class=HTMLResponse)
def teachers_page(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY id DESC", (school["id"],)); teachers = cur.fetchall(); con.close()
    total = len(teachers)
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:12px; font-size:12px'>{i}</td><td style='padding:12px; font-size:12px'>{t['name']}</td><td style='padding:12px; font-size:12px'>{t['role'] or 'Teacher'}</td><td style='padding:12px; font-size:12px'>{t['phone'] or '—'}</td><td style='padding:12px'><a href='/school/teachers/delete/{t['id']}' style='color:#dc2626'>🗑️</a></td></tr>" for i,t in enumerate(teachers,1)]) or "<tr><td colspan='5' style='padding:40px; text-align:center'>No staff yet</td></tr>"
    header = school_header(school, name, "teachers", is_impersonating=is_imp)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.black-btn{{padding:10px 16px;background:#0f172a;color:white;border:none;border-radius:10px;font-weight:700}}</style></head><body>{header}<div style='padding:18px; max-width:1500px; margin:auto'><h2 style='margin:0; font-size:22px; font-weight:800'>Staff ({total})</h2><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:16px'><div style='padding:12px 16px; border-bottom:1px solid #f1f5f9'><button class='black-btn' onclick=\"document.getElementById('addStaffForm').style.display='block'\">+ Add Staff</button></div><div id='addStaffForm' style='display:none; padding:16px; border-bottom:1px solid #f1f5f9; background:#f8fafc'><form method='post' action='/school/teachers/add' style='display:grid; grid-template-columns:1fr 1fr; gap:10px'><input name='name' placeholder='Full Name *' required class='input-field'><input name='tsc_no' placeholder='TSC No *' required class='input-field'><input name='id_no' placeholder='National ID' class='input-field'><select name='gender' class='input-field'><option>Male</option><option>Female</option></select><select name='role' required class='input-field'><option>Administrator</option><option>Teacher</option></select><input name='phone' placeholder='Phone *' required class='input-field'><input name='email' placeholder='Email' class='input-field'><div style='grid-column:span 2'><button class='add-btn'>Add Staff</button></div></form></div><div style='overflow:auto'><table style='width:100%; border-collapse:collapse'><thead style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><tr><th style='padding:12px'>#</th><th>NAME</th><th>ROLE</th><th>PHONE</th><th>ACTIONS</th></tr></thead><tbody>{rows}</tbody></table></div></div></div></div></div></body></html>")

@app.post("/school/teachers/add")
def add_teacher(request: Request, name: str = Form(...), tsc_no: str = Form(...), id_no: str = Form(""), gender: str = Form(...), role: str = Form(...), phone: str = Form(...), email: str = Form("")):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO teachers (school_id, name, email, phone, tsc_no, gender, id_no, role) VALUES (?,?,?,?,?,?,?,?)", (school["id"], name.strip().upper(), email.strip(), phone.strip(), tsc_no.strip(), gender, id_no.strip(), role.strip())); con.commit(); con.close()
    return RedirectResponse("/school/teachers",303)

@app.get("/school/teachers/delete/{tid}")
def del_teacher(tid: int):
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM teachers WHERE id=?", (tid,)); con.commit(); con.close()
    return RedirectResponse("/school/teachers",303)

# ===== FIX FOR DETAIL NOT FOUND — CATCH ALL UNMATCHED ROUTES MUST BE LAST =====
@app.get("/school/{path}", response_class=HTMLResponse)
def school_other(path: str, request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    header = school_header(school, name, path, is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:30px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:40px;text-align:center'><h3>🚧 {path.upper()} — Coming Soon</h3><p style='color:#64748b'>This module is intact — placeholder</p><a href='/school/dashboard' style='padding:10px 16px; background:#0f172a;color:white; border-radius:10px; text-decoration:none; font-weight:700'>⬅️ Back to Overview</a></div></div></div></div></body></html>")

# ===== 404 HANDLER — THIS FIXES {"detail":"Not Found"} ON RENDER =====
@app.exception_handler(StarletteHTTPException)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        # If API call, return JSON, else redirect to login
        if request.url.path.startswith("/api") or "application/json" in request.headers.get("accept",""):
            return JSONResponse(status_code=404, content={"detail": "Not Found - redirecting to /"})
        return RedirectResponse("/", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
