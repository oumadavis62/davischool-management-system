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
app.add_middleware(SessionMiddleware, secret_key="davischool-v21-fixed")
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

def send_email(to_email, subject, body):
    if not EMAIL_PASSWORD:
        return False
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
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
    <style>.do-avatar{{width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; cursor:pointer; border:2px solid #e2e8f0; user-select:none; caret-color:transparent;}}</style>
    <div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center'>
        <div><b>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px; color:#64748b'>{name} • Super Admin</div></div>
        <div style='display:flex; gap:12px; align-items:center'><a href='/dashboard' style='font-size:12px; text-decoration:none'>📊 Dashboard</a><a href='/schools/manage' style='font-size:12px; text-decoration:none'>🏫 Schools</a><div style='width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800'>{initials}</div><a href='/logout' style='font-size:12px; color:#dc2626; text-decoration:none'>🚪</a></div>
    </div>"""

@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.get("/ping")
def ping(): return PlainTextResponse("pong")

@app.get("/", response_class=HTMLResponse)
def home():
    return "<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc'><div style='background:white; padding:30px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><h2 style='text-align:center'>Davischool</h2><p style='text-align:center; font-size:11px; color:#64748b'>ONE LOGIN FOR ALL ROLES</p><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%; padding:12px; margin:6px 0; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:6px 0 16px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In</button></form></div></body></html>"

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    con.close()
    if not u: return HTMLResponse("Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]
    request.session["role"]=u["role"]
    request.session["name"]=u["full_name"]
    request.session["school_id"]=u["school_id"] or 0
    if u["role"]!= "super_admin":
        log_activity(u["email"], f"🏫 School login")
        return RedirectResponse("/school/dashboard", status_code=303)
    log_activity(u["email"], "Super Admin Login")
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role")=="school_admin": return RedirectResponse("/school/dashboard")
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
    rows=""
    for s in recent:
        rows+=f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
    if not rows: rows="<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
    content=f"<div style='padding:24px'><h2>📊 School Overview</h2><p>Welcome {name}</p><div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin:20px 0'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:28px; font-weight:800'>{total}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:28px; font-weight:800'>{total}</div><div style='font-size:11px; color:#16a34a'>🛠️ All {total} schools are active</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>💰 TOTAL REVENUE</div><div style='font-size:28px; font-weight:800'>KES {total*15000:,}</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:28px; font-weight:800'>{total*350:,}</div></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:14px'><div style='padding:16px; border-bottom:1px solid #f1f5f9'><b>🏫 Recently Added</b> <a href='/schools/manage' style='float:right; font-size:12px; color:#2563eb; text-decoration:none'>View All</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Location</th><th style='padding:10px; text-align:left'>Status</th><th style='padding:10px; text-align:left'>Date</th></tr>{rows}</table></div></div>"
    return HTMLResponse(f"<html><body style='font-family:Arial; margin:0; background:#f8fafc'>{header_html(initials, name, email)}{content}</body></html>")

@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session or request.session.get("role")!="school_admin": return RedirectResponse("/")
    school_obj = get_school_obj(request)
    if not school_obj: return RedirectResponse("/")
    name = request.session.get("name","")
    return HTMLResponse(f"<html><body style='font-family:Arial; margin:0; background:#f8fafc'><div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px'><b>🏫 {school_obj['name']}</b> - {name} - Code {school_obj['code']}</div><div style='padding:24px'><h2>🏫 Welcome {school_obj['name']}!</h2><p>🔑 Code: {school_obj['code']}</p><p>📍 {school_obj['location']} | {school_obj['school_type']}</p><p>📧 {school_obj['email']}</p><div style='background:#f0fdf4; border:1px solid #bbf7d0; padding:12px; border-radius:8px; margin-top:16px'>✅ Isolated portal - Super admin untouched!</div><br><a href='/logout'>Logout</a></div></body></html>")

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = "", success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    name = request.session.get("name","")
    email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC")
    schools = cur.fetchall()
    con.close()
    banner=""
    if success=="added" and new_pass:
        banner=f"<div style='background:#dcfce7; border:2px solid #16a34a; padding:16px; border-radius:10px; margin-bottom:16px'><b>✅ School Added!</b><br>📧 {school_email}<br>🔑 Unique Password: <b style='font-size:18px'>{new_pass}</b><br><span style='font-size:10px; color:#dc2626'>Different from super admin! Copy now!</span></div>"
    elif success=="code_sent":
        banner="<div style='background:#fef3c7; border:1px solid #fcd34d; padding:12px; border-radius:10px; margin-bottom:16px'>📧 Code sent to super admin!</div>"
    rows_html=""
    for s in schools:
        rows_html+=f"<tr><td style='padding:10px; border-bottom:1px solid #eee'>🏫 {s['name']} ({s['code']})</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['email']}</td><td style='padding:10px; border-bottom:1px solid #eee'>{s['location']}</td></tr>"
    if not rows_html: rows_html="<tr><td colspan=3 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
    verify_html=""
    if pending_id:
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,))
        pending = cur.fetchone()
        con.close()
        if pending:
            verify_html=f"<div style='background:#fffbeb; border:2px solid #f59e0b; border-radius:12px; padding:20px; margin-bottom:16px'><b>Enter Code for {pending['name']}</b><br>Code: {pending['auth_code']}<form method='post' action='/verify-school-code' style='display:flex; gap:8px; margin-top:10px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='6-digit code' required style='flex:1; padding:12px; border:1px solid #fcd34d; border-radius:8px'><button style='background:#0f172a; color:white; padding:12px 20px; border:none; border-radius:8px'>Verify & Create Pass</button></form></div>"
    return HTMLResponse(f"<html><body style='font-family:Arial; background:#f8fafc; margin:0'>{header_html(initials, name, email)}<div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>{banner}{verify_html}<b>Registered Schools ({len(schools)})</b><table style='width:100%; border-collapse:collapse; margin-top:10px'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>School</th><th style='padding:10px; text-align:left'>Contact</th><th style='padding:10px; text-align:left'>Location</th></tr>{rows_html}</table></div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px'><b>Register New School</b><p style='font-size:11px; color:#64748b'>Unique password auto-created</p><form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='school_name' placeholder='School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' placeholder='Admin Email *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' placeholder='Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' placeholder='Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' placeholder='Principal *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>Type *</option><option>Primary</option><option>Secondary</option><option>Private Academy</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px'>Send Code & Create Pass</button></form></div></div></body></html>")

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code = str(random.randint(100000, 999999))
    con = get_db()
    cur = con.cursor()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid
    con.commit()
    con.close()
    send_email(SUPER_ADMIN, f"Code {auth_code} - {school_name}", f"Code: {auth_code} for {school_name}")
    return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}", status_code=303)

@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,))
    pending = cur.fetchone()
    if not pending or pending["auth_code"]!= auth_code.strip():
        con.close()
        return HTMLResponse("Wrong code <a href='/schools/manage'>Back</a>")
    code = str(random.randint(10000,99999))
    # UNIQUE PASSWORD PER SCHOOL - DIFFERENT FROM SUPER ADMIN
    prefix = "".join([c for c in pending["name"] if c.isalpha()])[:4].upper()
    if len(prefix)<3: prefix="SCH"
    unique_pass = f"{prefix}@{random.randint(1000,9999)}!"
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], unique_pass, "school_admin", pending["principal"], sid))
    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,))
    con.commit()
    con.close()
    send_email(pending["email"], f"Welcome {pending['name']} - Your Login", f"School: {pending['name']}\nEmail: {pending['email']}\nPassword: {unique_pass}\nCode: {code}\nLogin at your site")
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
