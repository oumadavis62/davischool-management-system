from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random, smtplib, ssl
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage
import os

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v24-zeraki-true-copy")
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
    cur.execute("CREATE TABLE IF NOT EXISTS timetable (id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER, day TEXT, period TEXT, subject TEXT, teacher TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS sms_logs (id INTEGER PRIMARY KEY, school_id INTEGER, recipient TEXT, message TEXT, timestamp TEXT)")
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
        msg.add_alternative(f"<div style='font-family:Arial; padding:20px'><h3>{subject}</h3><pre style='background:#f8fafc; padding:16px; border-radius:8px'>{body}</pre></div>", subtype="html")
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
    <style>.do-avatar{{width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #e2e8f0}}.dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#0f172a;color:white}}</style>
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
        return f"<a href='/school/{link}' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{a}'>{icon} {label}</a>"
    return f"""<div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20]}</b><div style='font-size:10px;color:#64748b'>🔑 {school['code']} | {school['location']}</div></div></div></div>{nav('dashboard','📊','Dashboard')}{nav('students','🎓','Students')}{nav('classes','🏫','Classes & Streams')}{nav('subjects','📚','Subjects')}{nav('exams','📝','Exams')}{nav('marks','✍️','Enter Marks')}{nav('marksheets','📄','MarkSheets')}{nav('ranking','🏆','Ranking')}{nav('analysis','📈','Exam Analysis')}{nav('reports','📑','Student Reports')}{nav('timetable','🗓️','Smart Timetable')}{nav('fees','💰','Fees & Finance')}{nav('sms','💬','Bulk SMS Parents')}<div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/logout' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'><div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:14px'>MATOKEO ANALYTICS 🚀</b><div style='font-size:11px;color:#64748b'>{name} • {school['name']}</div></div><div style='display:flex;align-items:center;gap:10px'><span style='font-size:11px;background:#dbeafe;color:#1e40af;padding:6px 10px;border-radius:20px'>{school['name']}</span><div style='width:36px;height:36px;background:#dcfce7;color:#166534;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800'>{initials}</div></div></div>"""

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
    log_activity(u["email"], "🔓 Super Admin Logged in", ""); return RedirectResponse("/dashboard", status_code=303)

# ===== RESTORED DASHBOARD - EXACT SCREENSHOT WINDOW =====
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") == "school_admin": return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools"); total = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5"); recent = cur.fetchall()
    cur.execute("SELECT COUNT(*) as c FROM students"); total_students = cur.fetchone()["c"] if total>0 else 0
    con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:12px;border-bottom:1px solid #f1f5f9;font-size:13px;font-weight:600'>🏫 {s['name']}</td><td style='padding:12px;border-bottom:1px solid #f1f5f9;font-size:13px'>📍 {s['location']}</td><td style='padding:12px;border-bottom:1px solid #f1f5f9'><span style='background:#dcfce7;color:#166534;padding:4px 10px;border-radius:20px;font-size:11px'>✅ Active</span></td><td style='padding:12px;border-bottom:1px solid #f1f5f9;font-size:12px;color:#64748b'>Today</td></tr>"
    if not rows: rows = "<tr><td colspan='4' style='padding:40px;text-align:center;color:#94a3b8;font-size:14px'>No schools yet</td></tr>"
    content = f"""
    <div style='padding:24px;max-width:1400px;margin:auto'>
        <div style='margin-bottom:20px'><div style='display:flex;align-items:center;gap:10px;margin-bottom:6px'><div style='width:32px;height:32px;background:linear-gradient(135deg,#3b82f6,#6366f1);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px'>📊</div><h2 style='margin:0;font-size:22px;font-weight:800'>School Overview</h2></div><p style='margin:0;color:#64748b;font-size:13px'>Welcome {name}</p></div>
        <div style='display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px'>
            <div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><div style='font-size:11px;color:#64748b;font-weight:600'>🏫 TOTAL SCHOOLS</div><div style='font-size:28px;font-weight:900;margin:8px 0'>{total}</div><div style='font-size:11px;color:#16a34a;background:#f0fdf4;padding:4px 8px;border-radius:6px;display:inline-flex'>📈 Up 12% from last month</div></div>
            <div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><div style='font-size:11px;color:#64748b;font-weight:600'>✅ ACTIVE SCHOOLS</div><div style='font-size:28px;font-weight:900;margin:8px 0'>{total}</div><div style='font-size:11px;color:#16a34a;background:#f0fdf4;padding:4px 8px;border-radius:6px;display:inline-flex'>🟢 100% operational</div></div>
            <div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><div style='font-size:11px;color:#64748b;font-weight:600'>🔥 TOTAL REVENUE</div><div style='font-size:28px;font-weight:900;margin:8px 0'>KES {total*15000 if total>0 else 0:,}</div><div style='font-size:11px;color:#16a34a;background:#f0fdf4;padding:4px 8px;border-radius:6px;display:inline-flex'>💹 +8% monthly growth</div></div>
            <div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><div style='font-size:11px;color:#64748b;font-weight:600'>🎓 TOTAL STUDENTS</div><div style='font-size:28px;font-weight:900;margin:8px 0'>{total_students}</div><div style='font-size:11px;color:#64748b;background:#f8fafc;padding:4px 8px;border-radius:6px;display:inline-flex'>👥 Avg 350 per school</div></div>
        </div>
        <div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:16px'>
            <div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:16px 18px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='font-weight:800;display:flex;align-items:center;gap:8px'>🏫 Recently Added Schools</div><a href='/schools/manage' style='font-size:12px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 18px'>Name</th><th style='padding:10px'>Location</th><th style='padding:10px'>Status</th><th style='padding:10px'>Date</th></tr></thead><tbody>{rows}</tbody></table></div>
            <div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px;margin-bottom:16px'><div style='font-weight:800;margin-bottom:12px;display:flex;align-items:center;gap:8px'>⚡ Quick Actions</div><a href='/schools/manage' style='display:block;text-align:center;background:white;border:1px solid #e2e8f0;padding:12px;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:600;font-size:13px;margin-bottom:10px'>🏫 Manage Schools</a><a href='/schools/manage' style='display:block;text-align:center;background:white;border:1px solid #e2e8f0;padding:12px;border-radius:10px;text-decoration:none;color:#6366f1;font-weight:600;font-size:13px'>➕ Register New School</a></div><div style='background:#0f172a;border-radius:16px;padding:16px;color:white'><div style='font-weight:800;display:flex;align-items:center;gap:8px;margin-bottom:4px'>📊 Davischool Analytics</div><div style='font-size:11px;color:#94a3b8;margin-bottom:14px'>🛠️ All {total} schools are active</div><div style='background:#1e293b;border-radius:10px;padding:12px'><div style='font-size:10px;color:#94a3b8;letter-spacing:0.5px;margin-bottom:6px'>🔧 PLATFORM HEALTH</div><div style='color:#22c55e;font-weight:800'>✅ 99.9% Uptime</div><div style='height:4px;background:#334155;border-radius:10px;margin-top:8px'><div style='width:99%;height:100%;background:#22c55e;border-radius:10px'></div></div></div></div></div>
        </div>
    </div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Inter,Arial;background:#f8fafc}}</style></head><body>{header_html(initials, name, email)}{content}</body></html>")

# ===== RESTORED MANAGE SCHOOLS - EXACT SCREENSHOT + 6-DIGIT + EYE + OK/CANCEL =====
@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools = cur.fetchall()
    cur.execute("SELECT * FROM users WHERE role='school_admin'"); users = cur.fetchall(); con.close()
    users_by_school = {u["school_id"]: u for u in users}
    banner = ""
    if success == "added" and new_pass:
        banner = f"""<div id='successModal' style='position:fixed;inset:0;background:rgba(0,0,0,0.45);display:flex;align-items:center;justify-content:center;z-index:9999'><div style='background:white;padding:24px;border-radius:16px;width:420px'><div style='font-size:18px;font-weight:800;margin-bottom:8px'>✅ {school_name} Added!</div><div style='background:#f8fafc;padding:12px;border-radius:10px;font-size:13px;border:1px solid #e2e8f0'><div>🏫 <b>{school_name}</b></div><div>👤 Username: <b>{school_email}</b></div><div>🔑 Password: <b>{new_pass}</b></div></div><div style='display:flex;gap:10px;margin-top:16px'><button onclick="document.getElementById('successModal').style.display='none'" style='flex:1;background:#0f172a;color:white;padding:10px;border:none;border-radius:10px'>OK ✅</button><button onclick="document.getElementById('successModal').style.display='none'" style='flex:1;background:#f1f5f9;color:#475569;padding:10px;border:none;border-radius:10px'>Cancel ❌</button></div></div></div>"""
    elif success == "code_sent":
        banner = f"""<div style='position:fixed;inset:0;background:rgba(0,0,0,0.45);display:flex;align-items:center;justify-content:center;z-index:9999'><div style='background:white;padding:24px;border-radius:16px;width:400px'><div style='background:#fef3c7;padding:12px;border-radius:10px;margin-bottom:12px'>📧 6-digit code sent to {SUPER_ADMIN}!</div><form method='post' action='/verify-school-code'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='Enter 6-digit code 🔐' required maxlength='6' style='width:100%;padding:12px;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:12px;text-align:center;font-size:18px;letter-spacing:6px'><div style='display:flex;gap:10px'><button style='flex:1;background:#0f172a;color:white;padding:11px;border:none;border-radius:10px'>Verify ✅</button><a href='/resend-code/{pending_id}' style='flex:1;background:#f59e0b;color:white;padding:11px;border-radius:10px;text-align:center;text-decoration:none'>Resend 📤</a></div><a href='/schools/manage' style='display:block;text-align:center;margin-top:10px;color:#64748b;text-decoration:none'>Cancel ❌</a></form></div></div>"""
    rows_html = ""
    for s in schools:
        sid = s["id"]; u = users_by_school.get(sid); upass = u["password"] if u else "—"; uemail = u["email"] if u else s["email"]
        rows_html += f"""<tr onclick="highlightRow(this, {sid})" style='cursor:pointer;border-bottom:1px solid #f1f5f9'><td style='padding:12px 10px'><div style='font-weight:700'>🏫 {s['name']}</div><div style='font-size:10px;color:#64748b'>🔑 Code: <b>{s['code']}</b></div></td><td style='padding:12px 10px;font-size:12px'>📧 {s['phone'] or ''}</td><td style='padding:12px 10px;font-size:12px'>📍 {s['location']}</td><td style='padding:12px 10px;font-size:12px'>👤 {uemail}</td><td style='padding:12px 10px;font-size:12px'><span id='pwd-dot-{sid}'>••••••••</span><span id='pwd-real-{sid}' style='display:none;font-weight:700'>{upass}</span> <span onclick="event.stopPropagation(); togglePwd({sid})" style='cursor:pointer'>👁️</span></td><td style='padding:12px 10px'><span id='actions-{sid}' style='display:none;gap:6px'><a href='/schools/delete/{sid}' style='background:#fee2e2;border:none;padding:6px 8px;border-radius:6px;text-decoration:none;font-size:12px'>🗑️ Delete</a></span><span id='hint-{sid}' style='font-size:10px;color:#94a3b8'>Click to activate</span></td></tr>"""
    if not rows_html: rows_html = "<tr><td colspan='6' style='padding:40px;text-align:center;color:#94a3b8'>No schools yet 🏫</td></tr>"
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px}}.highlight{{background:#eff6ff!important;border-left:3px solid #3b82f6}} input,select{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px}}</style></head><body>{header_html(initials, name, email)}{banner}<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px;padding:16px'><div class='card'><div style='font-weight:800;font-size:15px'>🗂️ Registered Schools ({len(schools)})</div><div style='font-size:11px;color:#64748b'>👉 Click row to highlight 💙 → then ✏️ Edit / 🗑️ Delete becomes active</div><div style='overflow:auto;max-height:70vh;border:1px solid #f1f5f9;border-radius:10px;margin-top:10px'><table style='width:100%;border-collapse:collapse;font-size:13px'><thead style='position:sticky;top:0;background:#f8fafc'><tr style='text-align:left;color:#475569;font-size:11px'><th style='padding:10px'>🏫 School</th><th style='padding:10px'>📧 Contact</th><th style='padding:10px'>📍 Location</th><th style='padding:10px'>👤 Username</th><th style='padding:10px'>🔑 Password</th><th style='padding:10px'>⚙️ Action</th></tr></thead><tbody>{rows_html}</tbody></table></div></div><div class='card' style='height:fit-content'><div style='font-weight:800'>➕ Register New School 🏫</div><div style='font-size:11px;color:#64748b;margin-bottom:10px'>Unique password auto-created 🔑</div><form method='post' action='/register-school'><input name='school_name' required placeholder='🏫 School Name *'><input name='school_email' required type='email' placeholder='📧 Admin Email *'><input name='location' required placeholder='📍 Location *'><input name='phone' required placeholder='📱 Phone *'><input name='principal' required placeholder='👤 Principal *'><select name='school_type' required><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Primary & Secondary</option></select><button style='width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;margin-top:10px'>📧 Send Code & Create Login</button><a href='/dashboard' style='display:block;text-align:center;padding:10px;border:1px solid #e2e8f0;border-radius:10px;margin-top:8px;text-decoration:none;color:#64748b'>❌ Cancel</a></form></div></div><script>let lastRow=null; function highlightRow(row,id){{if(lastRow) lastRow.classList.remove('highlight'); row.classList.add('highlight'); lastRow=row; document.querySelectorAll('[id^=actions-]').forEach(el=>el.style.display='none'); document.querySelectorAll('[id^=hint-]').forEach(el=>el.style.display='inline'); document.getElementById('actions-'+id).style.display='flex'; document.getElementById('hint-'+id).style.display='none';}} function togglePwd(id){{let d=document.getElementById('pwd-dot-'+id); let r=document.getElementById('pwd-real-'+id); if(d.style.display=='none'){{d.style.display='inline'; r.style.display='none';}} else {{d.style.display='none'; r.style.display='inline';}} }}</script></body></html>""")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code = str(random.randint(100000, 999999))
    con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid; con.commit(); con.close()
    send_email(SUPER_ADMIN, f"🔐 Code: {auth_code} - {school_name}", f"🏫 {school_name.upper()}\n🔑 CODE: {auth_code}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    if not pending: con.close(); return HTMLResponse("Invalid <a href='/schools/manage'>Back</a>")
    if pending["auth_code"]!= auth_code.strip(): con.close(); return HTMLResponse(f"<h3>❌ Wrong Code</h3><a href='/schools/manage?pending_id={pending_id}'>Try Again</a>")
    code = str(random.randint(100000,999999)); unique_pass = generate_unique_password(pending["name"])
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid = cur.lastrowid; cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], unique_pass, "school_admin", pending["principal"], sid))
    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,)); con.commit(); con.close()
    send_email(pending["email"], f"Welcome {pending['name']}", f"Username: {pending['email']}\nPassword: {unique_pass}\nCode: {code}")
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}&school_name={pending['name']}", status_code=303)

@app.get("/resend-code/{pending_id}")
def resend_code(pending_id: str):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); p = cur.fetchone()
    if p: send_email(SUPER_ADMIN, f"🔐 Code: {p['auth_code']} - {p['name']}", f"Code: {p['auth_code']}")
    con.close(); return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.get("/schools/delete/{sid}")
def delete_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM schools WHERE id=?", (sid,)); cur.execute("DELETE FROM users WHERE school_id=?", (sid,)); con.commit(); con.close()
    return RedirectResponse("/schools/manage", status_code=303)

@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]; con.close()
    html = school_header(school, name, "dashboard")
    html += f"<div style='padding:20px'><h2>MATOKEO ANALYTICS 🚀</h2><p>Students {sc} | Classes {cc} | Exams {ec}</p></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td>{s['name']}</td><td>{s['admission_no']}</td><td>{s['cname']}</td><td>{s['parent_phone']}</td><td><a href='/school/student/delete/{s['id']}'>🗑️</a></td></tr>" for s in students]) or "<tr><td colspan=5>No students</td></tr>"
    html = school_header(school, request.session.get("name",""), "students")
    html += f"<div style='padding:20px'><b>🎓 Students ({len(students)})</b><table style='width:100%'><tr><th>Name</th><th>Adm</th><th>Class</th><th>Phone</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/students/add'><input name='admission_no' required placeholder='Adm'><input name='student_name' required placeholder='Name'><select name='class_id'>{opts}</select><select name='gender'><option>Male</option><option>Female</option></select><input name='parent_name' placeholder='Parent'><input name='parent_phone' required placeholder='Phone'><button>Add</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_name: str = Form(...), parent_phone: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO students (school_id, admission_no, name, class_id, gender, parent_name, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], admission_no, student_name, class_id, gender, parent_name, parent_phone)); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td>{c['name']}</td><td>{c['level']}</td><td><a href='/school/class/delete/{c['id']}'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan=3>No classes</td></tr>"
    html = school_header(school, request.session.get("name",""), "classes")
    html += f"<div style='padding:20px'><table><tr><th>Class</th><th>Level</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/classes/add'><input name='class_name' required placeholder='Class'><select name='level'><option>Primary</option><option>Junior School</option><option>Senior School</option></select><button>Add</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), level: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, level) VALUES (?,?,?)", (school["id"], class_name, level)); con.commit(); con.close(); return RedirectResponse("/school/classes", status_code=303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td>{s['name']}</td><td>{s['code']}</td><td><a href='/school/subject/delete/{s['id']}'>🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan=3>No subjects</td></tr>"
    html = school_header(school, request.session.get("name",""), "subjects")
    html += f"<div style='padding:20px'><table><tr><th>Subject</th><th>Code</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/subjects/add'><input name='subject_name' required placeholder='Subject'><input name='subject_code' placeholder='Code'><button>Add</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), subject_code: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO subjects (school_id, name, code) VALUES (?,?,?)", (school["id"], subject_name.strip(), subject_code.strip())); con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/subject/delete/{sid}")
def del_sub(sid: int, request: Request): school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/subjects", status_code=303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td>{e['name']}</td><td>{e['term']}</td><td>{e['year']}</td><td><a href='/school/exam/delete/{e['id']}'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan=4>No exams</td></tr>"
    html = school_header(school, request.session.get("name",""), "exams")
    html += f"<div style='padding:20px'><table><tr><th>Exam</th><th>Term</th><th>Year</th><th>Action</th></tr>{rows}</table><form method='post' action='/school/exams/add'><input name='exam_name' required placeholder='Exam'><select name='term'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' value='2026'><select name='exam_type'><option>Main Exam</option><option>CAT</option></select><button>Add</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip(), term, year, exam_type)); con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/exam/delete/{eid}")
def del_exam(eid: int, request: Request): school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM exams WHERE id=? AND school_id=?", (eid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/exams", status_code=303)

@app.get("/school/marks", response_class=HTMLResponse)
def school_marks(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall()
    cur.execute("SELECT s.id, s.name FROM students s WHERE s.school_id=? LIMIT 50", (school["id"],)); students = cur.fetchall()
    cur.execute("SELECT m.*, s.name as sname, sub.name as subname FROM marks m JOIN students s ON m.student_id=s.id JOIN subjects sub ON m.subject_id=sub.id WHERE m.school_id=? ORDER BY m.id DESC LIMIT 15", (school["id"],)); recent = cur.fetchall(); con.close()
    e_opts = "".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams])
    sub_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    st_opts = "".join([f"<option value='{st['id']}'>{st['name']}</option>" for st in students])
    rows = "".join([f"<tr><td>{r['sname']}</td><td>{r['subname']}</td><td><b>{r['score']}</b></td></tr>" for r in recent]) or "<tr><td colspan=3>No marks</td></tr>"
    html = school_header(school, request.session.get("name",""), "marks")
    html += f"<div style='padding:20px'><table><tr><th>Student</th><th>Subject</th><th>Score</th></tr>{rows}</table><form method='post' action='/school/marks/add'><select name='exam_id'>{e_opts}</select><select name='subject_id'>{sub_opts}</select><select name='student_id'>{st_opts}</select><input name='score' type='number' min='0' max='100' required placeholder='Score'><button>Save</button></form></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.post("/school/marks/add")
def add_marks(request: Request, exam_id: int = Form(...), subject_id: int = Form(...), student_id: int = Form(...), score: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO marks (school_id, exam_id, student_id, subject_id, score) VALUES (?,?,?,?,?)", (school["id"], exam_id, student_id, subject_id, score)); con.commit(); con.close(); return RedirectResponse("/school/marks", status_code=303)

@app.get("/school/marksheets", response_class=HTMLResponse)
def school_marksheets(request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=?", (school["id"],)); exams = cur.fetchall(); con.close()
    html = school_header(school, request.session.get("name",""), "marksheets")
    content = "".join([f"<div style='background:white;padding:14px;border-radius:12px'><b>{e['name']}</b></div>" for e in exams]) or "No exams"
    html += f"<div style='padding:20px'><div style='display:grid;grid-template-columns:repeat(3,1fr);gap:12px'>{content}</div></div></div></div>"
    return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/ranking", response_class=HTMLResponse)
def school_ranking(request: Request):
    school = get_school_obj(request); html = school_header(school, request.session.get("name",""), "ranking"); html += f"<div style='padding:20px'>Ranking</div></div></div>"; return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/analysis", response_class=HTMLResponse)
def school_analysis(request: Request):
    school = get_school_obj(request); html = school_header(school, request.session.get("name",""), "analysis"); html += f"<div style='padding:20px'>Analysis</div></div></div>"; return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/reports", response_class=HTMLResponse)
def school_reports(request: Request):
    school = get_school_obj(request); html = school_header(school, request.session.get("name",""), "reports"); html += f"<div style='padding:20px'>Reports</div></div></div>"; return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/fees", response_class=HTMLResponse)
def school_fees(request: Request):
    school = get_school_obj(request); html = school_header(school, request.session.get("name",""), "fees"); html += f"<div style='padding:20px'>Fees</div></div></div>"; return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/timetable", response_class=HTMLResponse)
def school_timetable(request: Request):
    school = get_school_obj(request); html = school_header(school, request.session.get("name",""), "timetable"); html += f"<div style='padding:20px'>Timetable</div></div></div>"; return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/sms", response_class=HTMLResponse)
def school_sms(request: Request):
    school = get_school_obj(request); html = school_header(school, request.session.get("name",""), "sms"); html += f"<div style='padding:20px'>Bulk SMS</div></div></div>"; return HTMLResponse(f"<html><body>{html}</body></html>")

@app.get("/school/student/delete/{sid}")
def del_student(sid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=? AND school_id=?", (sid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/students", status_code=303)

@app.get("/school/class/delete/{cid}")
def del_class(cid: int, request: Request):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=? AND school_id=?", (cid, school["id"])); con.commit(); con.close(); return RedirectResponse("/school/classes", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/")
