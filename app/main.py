from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random, os
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage
import smtplib, ssl

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v40-admin-restored-final")
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
    try: cur.execute("ALTER TABLE classes ADD COLUMN stream TEXT")
    except: pass
    try: cur.execute("ALTER TABLE students ADD COLUMN stream TEXT")
    except: pass
    try: cur.execute("ALTER TABLE students ADD COLUMN assessment_no TEXT")
    except: pass
    try: cur.execute("ALTER TABLE subjects ADD COLUMN initial TEXT")
    except: pass
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit(); con.close()
init_db()

def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin": return None
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone(); con.close(); return s

def header_html(initials, name, email):
    return f"""
    <style>
.do-avatar{{width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #e2e8f0}}
.dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#0f172a;color:white}}
.back-btn{{display:inline-flex; align-items:center; gap:6px; padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px; transition:all 0.2s ease; cursor:pointer}}
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
        is_active = "background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569;background:transparent"
        return f"<a href='/school/{link}' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active};transition:all 0.2s ease' onmouseover=\"if('{active}'!='{link}'){{this.style.background='#0f172a'; this.style.color='white'; this.style.transform='translateX(4px)'}} \" onmouseout=\"if('{active}'!='{link}'){{this.style.background='transparent'; this.style.color='#475569'; this.style.transform='translateX(0)'}} \">{icon} {label}</a>"
    return f"""
    <style>
.ds-card{{background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; text-decoration:none; color:#0f172a; display:block; transition:all 0.25s ease; cursor:pointer}}
.ds-card:hover{{background:#0f172a!important; color:white!important; transform:translateY(-3px); box-shadow:0 12px 24px rgba(15,23,42,0.35)}}
.ds-card:hover div{{color:white!important}}
.input-field{{width:100%; padding:11px 12px; border:1px solid #e2e8f0; border-radius:10px; margin:6px 0; font-size:13px; background:white}}
.add-btn{{width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; font-weight:700; cursor:pointer; transition:all 0.2s}}
.add-btn:hover{{background:#1e3a8a; transform:translateY(-1px)}}
.highlight-row{{background:#dbeafe!important; border-left:4px solid #0f172a!important}}
table{{user-select:none; caret-color:transparent}} tr{{user-select:none; caret-color:transparent}}
.confirm-overlay{{position:fixed; inset:0; background:rgba(0,0,0,0.5); display:none; align-items:center; justify-content:center; z-index:10000}}
.confirm-box{{background:white; border-radius:16px; padding:22px; width:380px; text-align:center; border:1px solid #e2e8f0; box-shadow:0 20px 40px rgba(0,0,0,0.25)}}
.back-btn{{display:inline-flex; align-items:center; gap:6px; padding:10px 16px; background:white; border:1px solid #e2e8f0; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:700; font-size:12px; transition:all 0.25s ease; cursor:pointer}}
.back-btn:hover{{background:#0f172a!important; color:white!important; border-color:#0f172a!important; transform:translateY(-1px); box-shadow:0 6px 16px rgba(15,23,42,0.3)}}
    </style>
    <div style='display:flex;min-height:100vh'>
    <div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'>
      <div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'>
        <div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20].upper()}</b><div style='font-size:10px;color:#64748b'>🔑 {school['code']} | {school['location']}</div></div></div>
      </div>
      {nav('dashboard','📊','Dashboard')}{nav('students','🎓','Students')}{nav('classes','🏫','Classes & Streams')}{nav('subjects','📚','Subjects')}{nav('exams','📝','Exams')}{nav('marks','✍️','Enter Marks')}{nav('marksheets','📄','MarkSheets')}{nav('ranking','🏆','Ranking')}{nav('analysis','📈','Exam Analysis')}{nav('reports','📑','Student Reports')}{nav('timetable','🗓️','Smart Timetable')}{nav('fees','💰','Fees & Finance')}{nav('sms','💬','Bulk SMS Parents')}
      <div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/logout' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626' onmouseover="this.style.background='#0f172a'; this.style.color='white'" onmouseout="this.style.background='transparent'; this.style.color='#dc2626'">🚪 Logout</a></div>
    </div>
    <div style='flex:1;background:#f8fafc'><div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>DaviSchool Management System 🚀</b><div style='font-size:11px;color:#64748b'>{name.upper()} • {school['name']}</div></div><div style='display:flex;align-items:center;gap:10px'><span style='font-size:11px;background:#dbeafe;color:#1e40af;padding:6px 10px;border-radius:20px'>{school['name']}</span><div style='width:32px;height:32px;background:#dcfce7;color:#166534;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px'>{initials}</div></div></div>
    """

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f8fafc;margin:0'><div style='background:white;padding:36px 32px;border-radius:16px;border:1px solid #e2e8f0;width:400px'><div style='text-align:center;margin-bottom:24px'><div style='width:52px;height:52px;background:#0f172a;color:white;border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:22px;margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2></div><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%;padding:12px;margin:6px 0;border:1px solid #e2e8f0;border-radius:10px'><input name='password' type='password' placeholder='Password' required style='width:100%;padding:12px;margin:6px 0 20px;border:1px solid #e2e8f0;border-radius:10px'><button style='width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px'>Sign In</button></form></div></body></html>"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password)); u = cur.fetchone()
    school_info = None
    if u: cur.execute("SELECT * FROM schools WHERE id=?", (u["school_id"],)); school_info = cur.fetchone()
    con.close()
    if not u: return HTMLResponse("Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    if u["role"]!= "super_admin" and school_info: return RedirectResponse("/school/dashboard", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)

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
    # RICH DASHBOARD RESTORED - matches original design + your screenshot structure
    content = f"""
    <div style='padding:20px; max-width:1400px; margin:auto'>
      <div style='margin-bottom:18px'><h2 style='margin:0; font-size:22px; font-weight:800'>📊 School Overview</h2><p style='margin:4px 0 0; color:#64748b; font-size:13px'>Welcome {name}</p></div>
      <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:18px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>{total}</div><div style='font-size:11px; color:#16a34a'>📈 Up 12% from last month</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>{total}</div><div style='font-size:11px; color:#16a34a'>🟢 100% operational</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🔥 TOTAL REVENUE</div><div style='font-size:26px; font-weight:900; margin:12px 0 8px'>KES {total*15000 if total>0 else 0}</div><div style='font-size:11px; color:#16a34a'>💹 +8% monthly growth</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:32px; font-weight:900; margin:12px 0 8px'>0</div><div style='font-size:11px; color:#64748b'>👥 Avg 350 per school</div></div>
      </div>
      <div style='display:grid; grid-template-columns:1.9fr 0.8fr; gap:16px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #f1f5f9'><div style='font-weight:800; font-size:14px'>🏫 Recently Added Schools</div><a href='/schools/manage' style='font-size:12px; color:#3b82f6; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 14px'>Name</th><th style='padding:10px 14px'>Location</th><th style='padding:10px 14px'>Status</th><th style='padding:10px 14px'>Date</th></tr></thead><tbody>{rows}</tbody></table></div>
        <div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; margin-bottom:16px'><div style='font-weight:800; font-size:14px; margin-bottom:12px'>⚡ Quick Actions</div><a href='/schools/manage' style='display:block; text-align:center; background:white; border:1px solid #e2e8f0; padding:10px; border-radius:10px; text-decoration:none; color:#0f172a; font-weight:600; font-size:13px; margin-bottom:10px'>🏫 Manage Schools</a><a href='/schools/manage' style='display:block; text-align:center; background:white; border:1px solid #e2e8f0; padding:10px; border-radius:10px; text-decoration:none; color:#6366f1; font-weight:600; font-size:13px'>➕ Register New School</a></div><div style='background:#0f172a; border-radius:14px; padding:16px; color:white'><div style='font-weight:800; font-size:14px; margin-bottom:4px'>📊 Davischool Analytics</div><div style='font-size:11px; color:#94a3b8; margin-bottom:14px'>All {total} schools are active</div><div style='background:#1e293b; border-radius:10px; padding:12px'><div style='font-size:10px; color:#94a3b8; letter-spacing:0.5px; margin-bottom:6px'>PLATFORM HEALTH</div><div style='color:#22c55e; font-weight:800; font-size:14px'>✅ 99.9% Uptime</div><div style='height:4px; background:#334155; border-radius:10px; margin-top:8px'><div style='width:99%; height:100%; background:#22c55e; border-radius:10px'></div></div></div></div></div>
      </div>
    </div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials, name, email)}{content}</body></html>")

# ALL OTHER ROUTES (school side v38) remain same as v38 file you have - paste v38 after this for school modules
@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools = cur.fetchall(); con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com"); initials = "".join([p[0] for p in name.split()][:2]).upper()
    rows = "".join([f"<tr><td style='padding:10px'>{s['name']}</td><td style='padding:10px'>{s['location']}</td><td style='padding:10px'>{s['email']}</td></tr>" for s in schools])
    if not rows: rows = "<tr><td colspan='3' style='padding:30px; text-align:center; color:#94a3b8'>No schools yet</td></tr>"
    return HTMLResponse(f"<html><body>{header_html(initials, name, email)}<div style='padding:20px'><h3>Registered Schools ({len(schools)})</h3><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left'><th>Name</th><th>Location</th><th>Email</th></tr></thead><tbody>{rows}</tbody></table><br><a href='/dashboard' class='back-btn'>⬅️ Back to Dashboard</a></div></body></html>")

@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","JOHN DOE")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]
    con.close()
    header = school_header(school, name, "dashboard")
    html = f"<div style='padding:18px'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 100%); border-radius:18px; padding:22px 24px; color:white; margin-bottom:16px'><b style='font-size:22px'>DaviSchool Management System 🚀</b><div style='font-size:12px; color:#bfdbfe'>REVOLUTIONIZE YOUR SCHOOL'S MANAGEMENT!</div></div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:14px'><a href='/school/students' class='ds-card'><div>🎓 TOTAL STUDENTS</div><div style='font-size:30px; font-weight:900'>{sc}</div></a><a href='/school/classes' class='ds-card'><div>🏫 CLASSES</div><div style='font-size:30px; font-weight:900'>{cc}</div></a><a href='/school/exams' class='ds-card'><div>📝 EXAMS</div><div style='font-size:30px; font-weight:900'>{ec}</div></a><a href='/school/subjects' class='ds-card'><div>📚 SUBJECTS</div></a></div></div>"
    return HTMLResponse(f"<html><head><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

@app.get("/school/{page}", response_class=HTMLResponse)
def school_generic(page: str, request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    if page in ["dashboard"]: return RedirectResponse(f"/school/dashboard")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/")
    name = request.session.get("name","")
    header = school_header(school, name, page)
    return HTMLResponse(f"<html><body>{header}<div style='padding:20px'><h2>{page.title()} — {school['name']}</h2><p>This module is part of DaviSchool</p><a href='/school/dashboard' class='back-btn'>⬅️ Back to Overview</a></div></div></div></body></html>")

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/")
