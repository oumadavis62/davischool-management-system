from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import sqlite3, os, random, smtplib, ssl
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v38-final-postgres-chart")

SUPER_ADMIN = "oumadavis62@gmail.com"
EMAIL_SENDER = SUPER_ADMIN
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
DATABASE_URL = os.getenv("DATABASE_URL", "")
IS_PG = DATABASE_URL.startswith("postgres")

def q(sql): return sql.replace("?", "%s") if IS_PG else sql
def get_db():
    if IS_PG:
        import psycopg2, psycopg2.extras
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        con = sqlite3.connect("davischool.db")
        con.row_factory = sqlite3.Row
        return con
def get_cur(con):
    if IS_PG:
        import psycopg2.extras
        return con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return con.cursor()

def init_db():
    con = get_db(); cur = get_cur(con)
    if IS_PG:
        cur.execute("CREATE TABLE IF NOT EXISTS schools (id SERIAL PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id SERIAL PRIMARY KEY, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id SERIAL PRIMARY KEY, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS classes (id SERIAL PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, stream TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS students (id SERIAL PRIMARY KEY, school_id INTEGER, admission_no TEXT, assessment_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_name TEXT, parent_phone TEXT, stream TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS subjects (id SERIAL PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT, initial TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS exams (id SERIAL PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS marks (id SERIAL PRIMARY KEY, school_id INTEGER, exam_id INTEGER, student_id INTEGER, subject_id INTEGER, score INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS fees (id SERIAL PRIMARY KEY, school_id INTEGER, student_id INTEGER, term TEXT, total INTEGER, paid INTEGER, balance INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS teachers (id SERIAL PRIMARY KEY, school_id INTEGER, name TEXT, email TEXT, phone TEXT, tsc_no TEXT, gender TEXT, id_no TEXT, role TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS teacher_allocations (id SERIAL PRIMARY KEY, school_id INTEGER, teacher_id INTEGER, subject_id INTEGER, class_id INTEGER)")
    else:
        cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, stream TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, assessment_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_name TEXT, parent_phone TEXT, stream TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT, initial TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, exam_id INTEGER, student_id INTEGER, subject_id INTEGER, score INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, term TEXT, total INTEGER, paid INTEGER, balance INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, email TEXT, phone TEXT, tsc_no TEXT, gender TEXT, id_no TEXT, role TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS teacher_allocations (id INTEGER PRIMARY KEY, school_id INTEGER, teacher_id INTEGER, subject_id INTEGER, class_id INTEGER)")
    cur.execute(q("SELECT * FROM users WHERE email=?"), (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute(q("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)"), (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit(); con.close()
init_db()

def generate_unique_password(n):
    p = "".join([c for c in n.upper() if c.isalpha()])[:4]
    if len(p)<3: p="SCH"
    return f"{p}@{random.randint(1000,9999)}!"
def send_email(to_e, subj, body):
    if not EMAIL_PASSWORD: return False
    try:
        msg = EmailMessage(); msg["From"]=EMAIL_SENDER; msg["To"]=to_e; msg["Subject"]=subj; msg.set_content(body)
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
            s.starttls(context=ctx); s.login(EMAIL_SENDER, EMAIL_PASSWORD); s.send_message(msg)
        return True
    except: return False
def log_activity(email, action, details=""):
    try:
        con=get_db(); cur=get_cur(con); ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(q("INSERT INTO activity_log (email, action, details, timestamp) VALUES (?,?,?,?)"), (email,action,details,ts))
        con.commit(); con.close()
    except: pass
def get_school_obj(req):
    sid=req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin": return None
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM schools WHERE id=?"), (sid,)); s=cur.fetchone(); con.close(); return s

def header_html(initials, name, email):
    return f"<style>.do-avatar{{width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #e2e8f0}}.dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#0f172a;color:white}}.back-btn{{display:inline-flex;align-items:center;gap:6px;padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px;cursor:pointer}}.back-btn:hover{{background:#0f172a!important;color:white!important}}</style><div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 20px;display:flex;justify-content:space-between;align-items:center'><div><b>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px;color:#64748b'>{name} • Super Admin</div></div><div style='position:relative'><div onclick=\"document.getElementById('pd').style.display=document.getElementById('pd').style.display=='block'?'none':'block'\" class='do-avatar'>{initials}</div><div id='pd' style='display:none;position:absolute;right:0;top:44px;background:white;border:1px solid #e2e8f0;border-radius:12px;width:220px;box-shadow:0 10px 25px rgba(0,0,0,0.12);z-index:1000;overflow:hidden'><div style='padding:14px;background:#f8fafc;border-bottom:1px solid #f1f5f9'><div style='font-weight:700;font-size:13px'>{name}</div><div style='font-size:11px;color:#64748b'>{email}</div></div><a href='/profile?tab=personal' class='dropdown-item'>👤 Profile</a><a href='/logout' class='dropdown-item' style='color:#dc2626'>🚪 Logout</a></div></div></div>"

def school_header(school, name, active="dashboard"):
    initials="".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    def nav(link, icon, label):
        a="background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569"
        return f"<a href='/school/{link}' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{a}'>{icon} {label}</a>"
    return f"<style>.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block;transition:all 0.25s ease}}.ds-card:hover{{background:#0f172a!important;color:white!important}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style><div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20].upper()}</b><div style='font-size:10px;color:#64748b'>{school['code']} | {school['location']}</div></div></div></div>{nav('dashboard','📊','Dashboard')}{nav('students','🎓','Students')}{nav('classes','🏫','Classes')}{nav('subjects','📚','Subjects')}{nav('exams','📝','Exams')}{nav('marks','✍️','Enter Marks')}{nav('marksheets','📄','MarkSheets')}{nav('ranking','🏆','Ranking')}{nav('analysis','📈','Analysis')}{nav('reports','📑','Reports')}{nav('teachers','👨‍🏫','Teachers')}{nav('subject-allocation','📌','Allocation')}{nav('timetable','🗓️','Timetable')}{nav('fees','💰','Fees')}{nav('sms','💬','SMS')}<div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/logout' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'><div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>DaviSchool Management System 🚀</b><div style='font-size:11px;color:#64748b'>{name.upper()} • {school['name']}</div></div><div style='display:flex;align-items:center;gap:10px'><span style='font-size:11px;background:#dbeafe;color:#1e40af;padding:6px 10px;border-radius:20px'>{school['name']}</span><div style='width:32px;height:32px;background:#dcfce7;color:#166534;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px'>{initials}</div></div></div>"

# ORIGINAL PROFILE
@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, tab: str = "personal"):
    if "email" not in request.session: return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper()
    con=get_db(); cur=get_cur(con)
    cur.execute(q("SELECT COUNT(*) as c FROM activity_log WHERE email=?"), (email,)); total_events=cur.fetchone()["c"]
    cur.execute(q("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 20"), (email,)); logs=cur.fetchall(); con.close()
    ap = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="personal" else "color:#64748b"
    asec = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="security" else "color:#64748b"
    alog = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="activity" else "color:#64748b"
    left = f"<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; text-align:center; height:fit-content'><div style='width:80px; height:80px; background:#a8d8ff; color:#1e3a8a; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:900; font-size:28px; margin:0 auto 12px'>{initials}</div><div style='font-weight:800'>{name}</div><div style='background:#e0f2fe; color:#0369a1; padding:4px 12px; border-radius:20px; font-size:11px; font-weight:700; display:inline-block; margin:6px 0'>Super Admin</div><div style='font-size:12px; color:#64748b'>{email}</div><a href='/dashboard' class='back-btn' style='margin-top:20px; justify-content:center'>⬅️ Back</a></div>"
    if tab=="personal":
        right=f"<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='font-weight:800; margin-bottom:16px'>👤 Personal Information</div><form method='post' action='/profile/update'><label>Full Name</label><input name='full_name' value='{name}' style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:4px 0 12px'><label>Email</label><input value='{email}' disabled style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:4px 0 12px'><button style='background:#0f172a;color:white;padding:10px 18px;border:none;border-radius:10px'>💾 Save</button></form></div>"
    elif tab=="security":
        right="<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='font-weight:800; margin-bottom:16px'>🔒 Security</div><form method='post' action='/profile/change-password'><input type='password' name='current_pass' placeholder='Current' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input type='password' name='new_pass' placeholder='New' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input type='password' name='confirm_pass' placeholder='Confirm' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><button style='background:#0f172a;color:white;padding:10px 18px;border:none;border-radius:10px;margin-top:10px'>🔒 Update</button></form></div>"
    else:
        rows="".join([f"<div style='padding:10px 0;border-bottom:1px solid #f1f5f9'><b style='font-size:12px'>{l['action']}</b><div style='font-size:11px;color:#64748b'>{l['details']} - {l['timestamp']}</div></div>" for l in logs]) or "No logs"
        right=f"<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'><div style='font-weight:800'>📜 Activity Log - {total_events} events</div><div style='margin-top:12px; max-height:60vh; overflow:auto'>{rows}</div><a href='/profile/clear-logs' style='font-size:11px'>🧹 Clear</a></div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials,name,email)}<div style='padding:20px; max-width:1100px; margin:auto'><h2>👤 My Profile</h2><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:0 16px; display:flex; gap:20px; margin-bottom:16px'><a href='/profile?tab=personal' style='padding:12px 4px; text-decoration:none; font-size:13px; {ap}'>👤 Personal</a><a href='/profile?tab=security' style='padding:12px 4px; text-decoration:none; font-size:13px; {asec}'>🔒 Security</a><a href='/profile?tab=activity' style='padding:12px 4px; text-decoration:none; font-size:13px; {alog}'>📜 Activity</a></div><div style='display:grid; grid-template-columns:300px 1fr; gap:20px'>{left}{right}</div></div></body></html>")

@app.get("/profile/clear-logs")
def clear_logs(request: Request):
    con=get_db(); cur=get_cur(con); cur.execute(q("DELETE FROM activity_log WHERE email=?"), (request.session.get("email"),)); con.commit(); con.close(); return RedirectResponse("/profile?tab=activity",303)
@app.post("/profile/update")
def profile_update(request: Request, full_name: str = Form(...)):
    con=get_db(); cur=get_cur(con); cur.execute(q("UPDATE users SET full_name=? WHERE email=?"), (full_name, request.session.get("email"))); con.commit(); con.close(); request.session["name"]=full_name; return RedirectResponse("/profile?tab=personal",303)
@app.post("/profile/change-password")
def change_password(request: Request, current_pass: str = Form(...), new_pass: str = Form(...), confirm_pass: str = Form(...)):
    if new_pass!=confirm_pass: return HTMLResponse("Passwords mismatch <a href='/profile?tab=security'>Back</a>")
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM users WHERE email=? AND password=?"), (request.session.get("email"), current_pass)); u=cur.fetchone()
    if not u: con.close(); return HTMLResponse("Wrong current <a href='/profile?tab=security'>Back</a>")
    cur.execute(q("UPDATE users SET password=? WHERE email=?"), (new_pass, request.session.get("email"))); con.commit(); con.close(); return RedirectResponse("/profile?tab=security",303)

@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.get("/", response_class=HTMLResponse)
def home(): return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f8fafc;margin:0'><div style='background:white;padding:36px 32px;border-radius:16px;border:1px solid #e2e8f0;width:400px'><div style='text-align:center;margin-bottom:24px'><h2>Davischool</h2><p style='font-size:11px;color:#64748b'>ONE LOGIN FOR ALL ROLES</p></div><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%;padding:12px;margin:6px 0;border:1px solid #e2e8f0;border-radius:10px'><input name='password' type='password' placeholder='Password' required style='width:100%;padding:12px;margin:6px 0 20px;border:1px solid #e2e8f0;border-radius:10px'><button style='width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px'>Sign In</button></form></div></body></html>"""
@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM users WHERE email=? AND password=?"), (email,password)); u=cur.fetchone(); si=None
    if u: cur.execute(q("SELECT * FROM schools WHERE id=?"), (u["school_id"],)); si=cur.fetchone()
    con.close()
    if not u: return HTMLResponse("❌ Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    if u["role"]!="super_admin" and si: return RedirectResponse("/school/dashboard",303)
    return RedirectResponse("/dashboard",303)
@app.get("/logout")
def logout(request: Request): request.session.clear(); return RedirectResponse("/")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role")=="school_admin": return RedirectResponse("/school/dashboard")
    con=get_db(); cur=get_cur(con); cur.execute("SELECT COUNT(*) as c FROM schools"); total=cur.fetchone()["c"]; cur.execute(q("SELECT * FROM schools ORDER BY id DESC LIMIT 10")); recent=cur.fetchall(); con.close()
    name=request.session.get("name","Davis Ouma"); email=request.session.get("email",""); initials="".join([p[0] for p in name.split()][:2]).upper()
    rows="".join([f"<tr><td style='padding:10px 14px'>{s['name']}</td><td style='padding:10px 14px'>{s['location']}</td><td style='padding:10px 14px'><span style='background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:10px'>Active</span></td><td style='padding:10px 14px; font-size:11px'>Today</td></tr>" for s in recent]) or "<tr><td colspan='4' style='padding:30px; text-align:center'>No schools</td></tr>"
    content=f"<div style='padding:20px; max-width:1400px; margin:auto'><h2>📊 School Overview</h2><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:18px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div>🏫 TOTAL SCHOOLS</div><div style='font-size:32px; font-weight:900'>{total}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div>✅ ACTIVE</div><div style='font-size:32px; font-weight:900'>{total}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div>🔥 REVENUE</div><div style='font-size:26px; font-weight:900'>KES {total*15000}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div>🎓 STUDENTS</div><div style='font-size:32px; font-weight:900'>0</div></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; display:flex; justify-content:space-between'><div style='font-weight:800'>🏫 Recently Added Schools</div><a href='/schools/manage'>View All →</a></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px'><th style='padding:10px 14px'>Name</th><th>Location</th><th>Status</th><th>Date</th></tr></thead><tbody>{rows}</tbody></table></div></div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials,name,email)}{content}</body></html>")

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = ""):
    if request.session.get("role")!="super_admin": return RedirectResponse("/school/dashboard")
    name=request.session.get("name",""); email=request.session.get("email",""); initials="".join([p[0] for p in name.split()][:2]).upper()
    con=get_db(); cur=get_cur(con); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools=cur.fetchall(); cur.execute(q("SELECT * FROM users WHERE role='school_admin'")); users=cur.fetchall()
    pending=None
    if pending_id: cur.execute(q("SELECT * FROM pending_schools WHERE id=?"), (pending_id,)); pending=cur.fetchone()
    con.close(); users_by={u["school_id"]:u for u in users}
    popup=""
    if success=="code_sent" and pending:
        popup=f"<div style='background:white;border:1.5px solid #fb923c;border-radius:12px;padding:16px;margin-bottom:16px'><div style='font-weight:800'>🔓 Enter Code for {pending['name']}</div><div style='border:1.5px dashed #fb923c;border-radius:10px;padding:18px;text-align:center;background:#fffbeb;margin:12px 0;font-size:28px;font-weight:900;letter-spacing:10px'>🔑 {pending['auth_code']}</div><form method='post' action='/verify-school-code' style='display:flex;gap:10px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' value='{pending['auth_code']}' required maxlength='6' style='flex:1;padding:12px;border:1px solid #e2e8f0;border-radius:10px;font-size:18px;text-align:center'><button style='background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px'>Verify</button></form></div>"
    elif success=="added" and new_pass:
        popup=f"<div id='m' style='position:fixed;inset:0;background:rgba(0,0,0,0.45);display:flex;align-items:center;justify-content:center;z-index:9999'><div style='background:white;padding:24px;border-radius:16px;width:420px'><div style='font-size:18px;font-weight:800'>✅ {school_name} Added!</div><div style='background:#f8fafc;padding:12px;border-radius:10px;font-size:13px;border:1px solid #e2e8f0;margin-top:10px'><div>🏫 {school_name}</div><div>👤 {school_email}</div><div>🔑 {new_pass}</div></div><button onclick=\"document.getElementById('m').style.display='none'\" style='width:100%;background:#0f172a;color:white;padding:10px;border:none;border-radius:10px;margin-top:16px'>OK</button></div></div>"
    rows_html="".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:12px 10px'><div style='font-weight:700'>{s['name']}</div><div style='font-size:10px'>🔑 {s['code']}</div></td><td style='padding:12px 10px;font-size:12px'>{s['phone'] or ''}</td><td style='padding:12px 10px;font-size:11px'>{s['email']}</td><td style='padding:12px 10px;font-size:12px'>{s['location']}</td><td style='padding:12px 10px'><a href='/schools/edit/{s['id']}' style='background:#dbeafe;color:#1e40af;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px'>✏️ Edit</a> <a href='/schools/delete/{s['id']}' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️</a></td></tr>" for s in schools]) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No schools</td></tr>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials,name,email)}<div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px; padding:16px; max-width:1500px; margin:auto'><div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'>{popup}<div style='font-weight:800'>📚 Registered Schools ({len(schools)})</div><table style='width:100%;border-collapse:collapse;margin-top:10px'><thead style='background:#f8fafc;font-size:11px'><tr><th style='padding:10px'>School</th><th>Contact</th><th>Email</th><th>Location</th><th>Action</th></tr></thead><tbody>{rows_html}</tbody></table><a href='/dashboard' class='back-btn' style='margin-top:14px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px;height:fit-content'><div style='font-weight:800'>➕ Register New School</div><form method='post' action='/register-school'><input name='school_name' required placeholder='School Name *' style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='school_email' required type='email' placeholder='Admin Email *' style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='location' required placeholder='Location *' style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='phone' required placeholder='Phone *' style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='principal' required placeholder='Principal *' style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><select name='school_type' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><option value=''>Type *</option><option>Primary</option><option>Secondary</option><option>Primary & Junior Secondary</option></select><button style='width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;margin-top:10px'>📧 Send Code</button></form></div></div></body></html>")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code=str(random.randint(100000,999999)); con=get_db(); cur=get_cur(con); ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(q("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)"), (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pid=cur.lastrowid; con.commit(); con.close(); log_activity(SUPER_ADMIN, f"Auth code sent for {school_name.upper()}", f"Code {auth_code}"); send_email(SUPER_ADMIN, f"Code: {auth_code} - {school_name}", f"{school_name.upper()}\nCODE: {auth_code}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pid}",303)
@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM pending_schools WHERE id=?"), (pending_id,)); p=cur.fetchone()
    if not p: con.close(); return HTMLResponse("Invalid <a href='/schools/manage'>Back</a>")
    if p["auth_code"]!=auth_code.strip(): con.close(); return HTMLResponse(f"Wrong Code! <a href='/schools/manage?success=code_sent&pending_id={pending_id}'>Try Again</a>")
    code=str(random.randint(100000,999999)); upass=generate_unique_password(p["name"])
    cur.execute(q("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)"), (p["name"], p["email"], code, p["location"], p["phone"], p["principal"], p["school_type"]))
    sid=cur.lastrowid; cur.execute(q("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)"), (p["email"], upass, "school_admin", p["principal"], sid))
    cur.execute(q("DELETE FROM pending_schools WHERE id=?"), (pending_id,)); con.commit(); con.close()
    return RedirectResponse(f"/schools/manage?success=added&new_pass={upass}&school_email={p['email']}&school_name={p['name']}",303)
@app.get("/schools/delete/{sid}")
def delete_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con=get_db(); cur=get_cur(con); cur.execute(q("DELETE FROM schools WHERE id=?"), (sid,)); cur.execute(q("DELETE FROM users WHERE school_id=?"), (sid,)); con.commit(); con.close(); return RedirectResponse("/schools/manage",303)
@app.get("/schools/edit/{sid}", response_class=HTMLResponse)
def edit_school_page(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM schools WHERE id=?"), (sid,)); s=cur.fetchone(); con.close()
    name=request.session.get("name",""); email=request.session.get("email",""); initials="".join([p[0] for p in name.split()][:2]).upper()
    return HTMLResponse(f"<html><body>{header_html(initials,name,email)}<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px;max-width:500px;margin:30px auto'><h3>Edit {s['name']}</h3><form method='post' action='/schools/edit/{sid}'><input name='school_name' value='{s['name']}' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='school_email' value='{s['email']}' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='location' value='{s['location']}' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='phone' value='{s['phone']}' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='principal' value='{s['principal']}' required style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><input name='new_password' placeholder='New Password (blank keep old)' style='width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0'><div style='display:flex;gap:10px;margin-top:12px'><button style='flex:1;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px'>Save</button><a href='/schools/manage' style='flex:1;text-align:center;padding:12px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none'>Cancel</a></div></form></div></body></html>")
@app.post("/schools/edit/{sid}")
def edit_school_save(sid: int, request: Request, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), new_password: str = Form("")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con=get_db(); cur=get_cur(con)
    cur.execute(q("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=? WHERE id=?"), (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), sid))
    if new_password.strip(): cur.execute(q("UPDATE users SET email=?, full_name=?, password=? WHERE school_id=? AND role='school_admin'"), (school_email.strip(), principal.strip(), new_password.strip(), sid))
    else: cur.execute(q("UPDATE users SET email=?, full_name=? WHERE school_id=? AND role='school_admin'"), (school_email.strip(), principal.strip(), sid))
    con.commit(); con.close(); return RedirectResponse("/schools/manage",303)

# ===== SCHOOL DASHBOARD WITH AUTOMATIC GENDER CHART =====
@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school=get_school_obj(request); name=request.session.get("name","")
    con=get_db(); cur=get_cur(con)
    cur.execute(q("SELECT COUNT(*) c FROM students WHERE school_id=?"), (school["id"],)); sc=cur.fetchone()["c"]
    cur.execute(q("SELECT COUNT(*) c FROM classes WHERE school_id=?"), (school["id"],)); cc=cur.fetchone()["c"]
    cur.execute(q("SELECT COUNT(*) c FROM exams WHERE school_id=?"), (school["id"],)); ec=cur.fetchone()["c"]
    cur.execute(q("SELECT COUNT(*) c FROM teachers WHERE school_id=?"), (school["id"],)); tc=cur.fetchone()["c"]
    cur.execute(q("SELECT c.name as class_name, s.gender, COUNT(*) as cnt FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? GROUP BY c.name, s.gender ORDER BY c.name"), (school["id"],))
    gender_rows=cur.fetchall()
    cur.execute(q("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC LIMIT 5"), (school["id"],)); recent=cur.fetchall()
    con.close()
    stats={}; tb=0; tg=0
    for r in gender_rows:
        cn=(r['class_name'] or 'UNASSIGNED').upper()
        if cn not in stats: stats[cn]={'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys']=r['cnt']; tb+=r['cnt']
        else: stats[cn]['girls']=r['cnt']; tg+=r['cnt']
    total=tb+tg; ratio=round(tg/tb,2) if tb>0 else 0; max_v=max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    blocks=""
    for cls_name, v in stats.items():
        bh=int((v['boys']/max_v)*150) if v['boys']>0 else 6
        gh=int((v['girls']/max_v)*150) if v['girls']>0 else 6
        blocks+=f"<div style='text-align:center; min-width:90px'><div style='display:flex; gap:10px; align-items:end; justify-content:center; height:170px'><div><div style='width:42px; height:{bh}px; background:#0a84ff; border-radius:6px 6px 0 0'></div><div style='font-size:10px; font-weight:700; color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px; height:{gh}px; background:#ff2d92; border-radius:6px 6px 0 0'></div><div style='font-size:10px; font-weight:700; color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px; font-weight:800; margin-top:8px'>{cls_name}</div></div>"
    if not blocks: blocks="<div style='padding:30px; color:#94a3b8; text-align:center; width:100%'>No students yet — add students to see chart 📊</div>"
    stu_rows="".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{s['name']}</td><td style='padding:10px 12px;font-size:11px'>{s['assessment_no'] or s['admission_no'] or ''}</td><td style='padding:10px 12px;font-size:11px'>{s['gender']}</td><td style='padding:10px 12px;font-size:11px'>{s['class_name'] or ''}</td></tr>" for s in recent]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No students</td></tr>"
    header=school_header(school,name,"dashboard")
    html=f"<div style='padding:18px; max-width:1400px; margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%); border-radius:18px; padding:22px 24px; color:white; display:flex; justify-content:space-between; align-items:center; margin-bottom:16px'><div><div style='font-size:22px; font-weight:900'>DaviSchool Management System 🚀</div><div style='font-size:12px; color:#bfdbfe'>REVOLUTIONIZE YOUR SCHOOL'S MANAGEMENT!</div></div><div style='text-align:right'><div style='font-size:34px; font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students</div></div></div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:14px'><a href='/school/students' class='ds-card'><div style='font-size:11px;color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:30px;font-weight:900'>{sc}</div></a><a href='/school/classes' class='ds-card'><div style='font-size:11px;color:#64748b'>🏫 CLASSES</div><div style='font-size:30px;font-weight:900'>{cc}</div></a><a href='/school/exams' class='ds-card'><div style='font-size:11px;color:#64748b'>📝 EXAMS</div><div style='font-size:30px;font-weight:900'>{ec}</div></a><a href='/school/teachers' class='ds-card'><div style='font-size:11px;color:#64748b'>👨‍🏫 TEACHERS</div><div style='font-size:30px;font-weight:900'>{tc}</div></a></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; margin-bottom:16px'><div style='display:flex; justify-content:space-between'><div><div style='font-weight:800; font-size:14px'>👥 Students by Gender</div><div style='font-size:11px; color:#64748b'>Boys vs Girls enrollment per form — auto updates</div></div><div style='display:flex; gap:12px; font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex; gap:24px; overflow-x:auto; margin-top:18px'>{blocks}</div><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:18px; border-top:1px solid #f1f5f9; padding-top:14px'><div style='background:#f0f9ff; padding:12px; border-radius:10px; text-align:center'><div style='font-size:11px;color:#64748b'>Total Boys</div><div style='font-size:20px;font-weight:900;color:#0a84ff'>{tb}</div></div><div style='background:#fdf2f8; padding:12px; border-radius:10px; text-align:center'><div style='font-size:11px;color:#64748b'>Total Girls</div><div style='font-size:20px;font-weight:900;color:#ff2d92'>{tg}</div></div><div style='background:#f8fafc; padding:12px; border-radius:10px; text-align:center'><div style='font-size:11px;color:#64748b'>Total Students</div><div style='font-size:20px;font-weight:900'>{total}</div></div><div style='background:#f0fdf4; padding:12px; border-radius:10px; text-align:center'><div style='font-size:11px;color:#64748b'>Girl:Boy Ratio</div><div style='font-size:20px;font-weight:900'>{ratio}:1</div></div></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; border-bottom:1px solid #f1f5f9'><b>🎓 Recently Added Students</b></div><table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; font-size:10px; text-align:left'><th style='padding:10px 12px'>Name</th><th>Adm No</th><th>Gender</th><th>Class</th></tr></thead><tbody>{stu_rows}</tbody></table></div></div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

# --- KEEP ALL OTHER SCHOOL ROUTES (students, classes, subjects, exams, teachers, allocation etc) - simplified working versions ---
@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school=get_school_obj(request); name=request.session.get("name","")
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream"), (school["id"],)); classes=cur.fetchall(); con.close()
    rows="".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px'>{c['name']}</td><td style='padding:10px 12px'>{c['stream'] or ''}</td><td><a href='/school/classes/delete/{c['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️ Delete</a></td></tr>" for c in classes]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No classes</td></tr>"
    header=school_header(school,name,"classes")
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px; max-width:1200px; margin:auto'><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px; border-bottom:1px solid #f1f5f9'><b>🏫 Classes ({len(classes)})</b></div><table style='width:100%; border-collapse:collapse'>{rows}</table><div style='padding:12px'><a href='/school/dashboard' class='back-btn'>⬅️ Back</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><b>➕ Add Class</b><form method='post' action='/school/classes/add'><input name='class_name' required placeholder='Class Name *' class='input-field'><input name='stream' required placeholder='Stream *' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add</button></form></div></div></div></div></div></body></html>")
@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=get_cur(con); cur.execute(q("INSERT INTO classes (school_id, name, level, stream) VALUES (?,?,?,?)"), (school["id"], class_name.strip().upper(), stream.strip().upper(), stream.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/classes",303)
@app.get("/school/classes/delete/{cid}")
def delete_class(cid: int, request: Request): con=get_db(); cur=get_cur(con); cur.execute(q("DELETE FROM classes WHERE id=?"), (cid,)); con.commit(); con.close(); return RedirectResponse("/school/classes",303)

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school=get_school_obj(request); name=request.session.get("name","")
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM classes WHERE school_id=? ORDER BY name"), (school["id"],)); classes=cur.fetchall(); cur.execute(q("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC"), (school["id"],)); students=cur.fetchall(); con.close()
    opts="".join([f"<option value='{c['name']}|{c['id']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    rows="".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px'>{st['name']}</td><td style='padding:10px 12px'>{st['assessment_no'] or ''}</td><td style='padding:10px 12px'>{st['class_name'] or ''}</td><td style='padding:10px 12px'>{st['gender']}</td><td><a href='/school/students/delete/{st['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️</a></td></tr>" for st in students]) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No students</td></tr>"
    header=school_header(school,name,"students")
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px 16px'><b>🎓 Students ({len(students)})</b></div><table style='width:100%; border-collapse:collapse'><thead style='background:#f8fafc;font-size:11px'><tr><th>Name</th><th>Adm No</th><th>Class</th><th>Gender</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' class='back-btn'>⬅️ Back</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><b>➕ Add Student</b><form method='post' action='/school/students/add'><input name='assessment_no' required placeholder='Adm No *' class='input-field'><input name='student_name' required placeholder='Name *' class='input-field'><select name='class_info' required class='input-field'><option value=''>Select Class *</option>{opts}</select><select name='gender' required class='input-field'><option value='Male'>Male</option><option value='Female'>Female</option></select><input name='parent_phone' required placeholder='Parent Phone *' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add</button></form></div></div></div></div></div></body></html>")
@app.post("/school/students/add")
def add_student(request: Request, assessment_no: str = Form(...), student_name: str = Form(...), class_info: str = Form(...), gender: str = Form(...), parent_phone: str = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=get_cur(con); cid=int(class_info.split("|")[1]) if "|" in class_info else 0
    cur.execute(q("INSERT INTO students (school_id, admission_no, assessment_no, name, class_id, gender, parent_phone) VALUES (?,?,?,?,?,?,?)"), (school["id"], assessment_no.strip().upper(), assessment_no.strip().upper(), student_name.strip().upper(), cid, gender, parent_phone.strip())); con.commit(); con.close(); return RedirectResponse("/school/students",303)
@app.get("/school/students/delete/{sid}")
def delete_student(sid: int): con=get_db(); cur=get_cur(con); cur.execute(q("DELETE FROM students WHERE id=?"), (sid,)); con.commit(); con.close(); return RedirectResponse("/school/students",303)

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school=get_school_obj(request); name=request.session.get("name","")
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM subjects WHERE school_id=?"), (school["id"],)); subs=cur.fetchall(); con.close()
    rows="".join([f"<tr><td style='padding:10px 12px'>{s['name']}</td><td>{s['code'] or ''}</td><td><a href='/school/subjects/delete/{s['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No subjects</td></tr>"
    header=school_header(school,name,"subjects")
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px'><b>📚 Subjects ({len(subs)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' class='back-btn'>⬅️ Back</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><b>➕ Add Subject</b><form method='post' action='/school/subjects/add'><input name='subject_name' required placeholder='Subject Name *' class='input-field'><input name='code' placeholder='Code' class='input-field'><input name='initial' placeholder='Initial e.g MAT' class='input-field'><button class='add-btn' style='margin-top:8px'>Add</button></form></div></div></div></div></div></body></html>")
@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), code: str = Form(""), initial: str = Form("")):
    school=get_school_obj(request); con=get_db(); cur=get_cur(con); cur.execute(q("INSERT INTO subjects (school_id, name, code, initial) VALUES (?,?,?,?)"), (school["id"], subject_name.strip().upper(), code.strip().upper(), initial.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/subjects",303)
@app.get("/school/subjects/delete/{sid}")
def delete_subject(sid: int): con=get_db(); cur=get_cur(con); cur.execute(q("DELETE FROM subjects WHERE id=?"), (sid,)); con.commit(); con.close(); return RedirectResponse("/school/subjects",303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school=get_school_obj(request); name=request.session.get("name","")
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC"), (school["id"],)); exams=cur.fetchall(); con.close()
    rows="".join([f"<tr><td style='padding:10px 12px'>{e['name']}</td><td>{e['term']}</td><td>{e['year']}</td><td><span style='background:#0f172a;color:white;padding:3px 8px;border-radius:12px;font-size:10px'>{e['exam_type'] or ''}</span></td><td><a href='/school/exams/delete/{e['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No exams</td></tr>"
    header=school_header(school,name,"exams")
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid; grid-template-columns:1.7fr 0.7fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:14px'><b>📝 Exams ({len(exams)})</b></div><table style='width:100%; border-collapse:collapse'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' class='back-btn'>⬅️ Back</a></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><b>➕ Add Exam</b><form method='post' action='/school/exams/add'><input name='exam_name' required placeholder='Exam Name *' class='input-field'><select name='term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='2026' class='input-field'><select name='exam_type' required class='input-field'><option>Main Exam</option><option>Opening Exam</option><option>Mid Term Exam</option><option>End Term Exam</option><option>CAT</option></select><button class='add-btn' style='margin-top:8px'>Add</button></form></div></div></div></div></div></body></html>")
@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=get_cur(con); cur.execute(q("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)"), (school["id"], exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip())); con.commit(); con.close(); return RedirectResponse("/school/exams",303)
@app.get("/school/exams/delete/{eid}")
def del_exam(eid: int): con=get_db(); cur=get_cur(con); cur.execute(q("DELETE FROM exams WHERE id=?"), (eid,)); con.commit(); con.close(); return RedirectResponse("/school/exams",303)

@app.get("/school/teachers", response_class=HTMLResponse)
def teachers_page(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school=get_school_obj(request); name=request.session.get("name","")
    con=get_db(); cur=get_cur(con); cur.execute(q("SELECT * FROM teachers WHERE school_id=? ORDER BY id DESC"), (school["id"],)); teachers=cur.fetchall(); con.close()
    rows="".join([f"<tr><td style='padding:10px 12px'>{t['name']}<br><span style='background:#0f172a;color:white;padding:2px 6px;border-radius:10px;font-size:10px'>{t['role'] or 'Teacher'}</span></td><td>{t['tsc_no']}</td><td>{t['phone']}</td><td>{t['email'] or ''}</td><td><a href='/school/teachers/delete/{t['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for t in teachers]) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No teachers</td></tr>"
    header=school_header(school,name,"teachers")
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px; max-width:1200px; margin:auto'><a href='/school/dashboard' class='back-btn' style='margin-bottom:14px'>⬅️ Back</a><h2>👨‍🏫 Teachers — {school['name']}</h2><div style='display:grid; grid-template-columns:360px 1fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><div style='font-weight:800'>➕ Add Teacher + Role</div><form method='post' action='/school/teachers/add'><input name='name' placeholder='Full Name *' required class='input-field'><input name='tsc_no' placeholder='TSC No *' required class='input-field'><input name='id_no' placeholder='ID No' class='input-field'><select name='gender' class='input-field'><option>Male</option><option>Female</option></select><select name='role' required class='input-field'><option value=''>Select Role</option><option>Principal</option><option>Deputy Principal</option><option>Class Teacher</option><option>Senior Teacher</option><option>Director of Studies</option><option>Teacher</option></select><input name='phone' placeholder='Phone *' required class='input-field'><input name='email' placeholder='Email' class='input-field'><button class='add-btn' style='margin-top:10px'>Add Teacher</button></form></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:12px 16px; font-weight:800'>Teachers List ({len(teachers)})</div><table style='width:100%; border-collapse:collapse'><tbody>{rows}</tbody></table></div></div></div></div></div></body></html>")
@app.post("/school/teachers/add")
def add_teacher(request: Request, name: str = Form(...), tsc_no: str = Form(...), id_no: str = Form(""), gender: str = Form(...), role: str = Form(...), phone: str = Form(...), email: str = Form("")):
    school=get_school_obj(request); con=get_db(); cur=get_cur(con); cur.execute(q("INSERT INTO teachers (school_id, name, email, phone, tsc_no, gender, id_no, role) VALUES (?,?,?,?,?,?,?,?)"), (school["id"], name.strip().upper(), email.strip(), phone.strip(), tsc_no.strip(), gender, id_no.strip(), role.strip())); con.commit(); con.close(); return RedirectResponse("/school/teachers",303)
@app.get("/school/teachers/delete/{tid}")
def del_teacher(tid: int): con=get_db(); cur=get_cur(con); cur.execute(q("DELETE FROM teachers WHERE id=?"), (tid,)); con.commit(); con.close(); return RedirectResponse("/school/teachers",303)

@app.get("/school/subject-allocation", response_class=HTMLResponse)
def allocation_page(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school=get_school_obj(request); name=request.session.get("name","")
    con=get_db(); cur=get_cur(con)
    cur.execute(q("SELECT * FROM teachers WHERE school_id=?"), (school["id"],)); teachers=cur.fetchall()
    cur.execute(q("SELECT * FROM subjects WHERE school_id=?"), (school["id"],)); subjects=cur.fetchall()
    cur.execute(q("SELECT * FROM classes WHERE school_id=?"), (school["id"],)); classes=cur.fetchall()
    cur.execute(q("SELECT ta.*, t.name as tname, s.name as sname, c.name as cname FROM teacher_allocations ta LEFT JOIN teachers t ON ta.teacher_id=t.id LEFT JOIN subjects s ON ta.subject_id=s.id LEFT JOIN classes c ON ta.class_id=c.id WHERE ta.school_id=?"), (school["id"],)); allocs=cur.fetchall()
    con.close()
    topts="".join([f"<option value='{t['id']}'>{t['name']}</option>" for t in teachers])
    sopts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    copts="".join([f"<option value='{c['id']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    rows="".join([f"<tr><td style='padding:10px'>{a['tname'] or ''}</td><td>{a['sname'] or ''}</td><td>{a['cname'] or ''}</td><td><a href='/school/allocation/delete/{a['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for a in allocs]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No allocations</td></tr>"
    header=school_header(school,name,"subject-allocation")
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid; grid-template-columns:360px 1fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px'><b>📌 Subject Allocation (No Roles)</b><form method='post' action='/school/allocation/add' style='margin-top:10px'><select name='teacher_id' required class='input-field'><option value=''>Teacher ▼</option>{topts}</select><select name='subject_id' required class='input-field'><option value=''>Subject ▼</option>{sopts}</select><select name='class_id' required class='input-field'><option value=''>Class ▼</option>{copts}</select><button class='add-btn' style='margin-top:10px'>Allocate</button></form></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:12px 16px'><b>Allocations ({len(allocs)})</b></div><table style='width:100%; border-collapse:collapse'><thead style='background:#f8fafc;font-size:11px'><tr><th>Teacher</th><th>Subject</th><th>Class</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div></div></div></div></div></body></html>")
@app.post("/school/allocation/add")
def add_alloc(request: Request, teacher_id: int = Form(...), subject_id: int = Form(...), class_id: int = Form(...)):
    school=get_school_obj(request); con=get_db(); cur=get_cur(con); cur.execute(q("INSERT INTO teacher_allocations (school_id, teacher_id, subject_id, class_id) VALUES (?,?,?,?)"), (school["id"], teacher_id, subject_id, class_id)); con.commit(); con.close(); return RedirectResponse("/school/subject-allocation",303)
@app.get("/school/allocation/delete/{aid}")
def del_alloc(aid: int): con=get_db(); cur=get_cur(con); cur.execute(q("DELETE FROM teacher_allocations WHERE id=?"), (aid,)); con.commit(); con.close(); return RedirectResponse("/school/subject-allocation",303)

# Placeholder routes to keep app alive
@app.get("/school/{page}", response_class=HTMLResponse)
def school_generic(page: str, request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    if page in ["dashboard","students","classes","subjects","exams","teachers","subject-allocation"]: return RedirectResponse(f"/school/{page}")
    school=get_school_obj(request); name=request.session.get("name","")
    header=school_header(school,name,page)
    return HTMLResponse(f"<html><body>{header}<div style='padding:30px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:30px;text-align:center'><h3>🚧 {page.upper()} — Coming in v38.8</h3><p style='color:#64748b'>Your data is safe in Postgres. Chart feature working.</p><a href='/school/dashboard' class='back-btn' style='margin-top:14px'>⬅️ Back to Dashboard</a></div></div></div></div></body></html>")
