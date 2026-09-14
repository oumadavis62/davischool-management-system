# DaviSchool Management System v2 - Multi-School SaaS - FastAPI Version
# Owner & Super Admin: oumadavis62@gmail.com
# Fresh System - No Mabale Data - You Control Everything
import sqlite3
import random
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

DB="school.db"
SUPER_ADMIN_EMAIL = "oumadavis62@gmail.com"
SUPER_ADMIN_PASS = "DaviSchool@2026!" # Change after first login
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "oumadavis62@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

app=FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davi-secret-2026-v2-super-secure")

def send_email(to, subject, body):
    if not SMTP_PASSWORD:
        print(f"[MOCK EMAIL] To:{to} | {subject} | {body}")
        return True
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_EMAIL
        msg['To'] = to
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(SMTP_EMAIL, SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"Email fail: {e}")
        return False

def init_db():
    c=sqlite3.connect(DB); cur=c.cursor()
    # Fresh multi-tenant tables
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, admin_name TEXT, email TEXT UNIQUE, phone TEXT, county TEXT, status TEXT DEFAULT 'PENDING', is_active INTEGER DEFAULT 0, trial_ends_at TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, email TEXT UNIQUE, username TEXT UNIQUE, password TEXT, role TEXT, is_super_admin INTEGER DEFAULT 0, is_school_admin INTEGER DEFAULT 0, FOREIGN KEY(school_id) REFERENCES schools(id))")
    cur.execute("CREATE TABLE IF NOT EXISTS email_verifications (id INTEGER PRIMARY KEY, school_id INTEGER, code TEXT, expires_at TEXT, verified_at TEXT, FOREIGN KEY(school_id) REFERENCES schools(id))")
    # Core school data - isolated by school_id
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT UNIQUE, name TEXT, class TEXT, stream TEXT, FOREIGN KEY(school_id) REFERENCES schools(id))")
    cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, tsc TEXT UNIQUE, name TEXT, subject TEXT, phone TEXT, FOREIGN KEY(school_id) REFERENCES schools(id))")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, term TEXT, year TEXT, subject TEXT, score INTEGER, FOREIGN KEY(school_id) REFERENCES schools(id))")
    cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, amount INTEGER, balance INTEGER, term TEXT, FOREIGN KEY(school_id) REFERENCES schools(id))")
    cur.execute("CREATE TABLE IF NOT EXISTS school_classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, FOREIGN KEY(school_id) REFERENCES schools(id))")

    # Create Super Admin - YOU
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (school_id, name, email, username, password, role, is_super_admin, is_school_admin) VALUES (NULL, 'Davis Ouma - Owner',?,?,?, 'Super Admin', 1, 1)", (SUPER_ADMIN_EMAIL, SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASS))
        print(f"Super Admin created: {SUPER_ADMIN_EMAIL}")

    c.commit(); c.close()

init_db()

def get_db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; return con

def gen_code(): return str(random.randint(100000,999999))
def gen_school_code():
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT COUNT(*) FROM schools")
    count=cur.fetchone()[0]
    con.close()
    return f"SCH-{10001+count}"

def is_super_admin(request: Request):
    return request.session.get("user_email") == SUPER_ADMIN_EMAIL

# === HOME ===
@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <style>body{font-family:Arial;max-width:800px;margin:30px auto;padding:20px}.card{background:#fff;padding:20px;border-radius:10px;box-shadow:0 2px 10px #0001} button{background:#0d6efd;color:#fff;padding:12px 20px;border:none;border-radius:6px}</style>
    <div class="card"><h1>DaviSchool Management System</h1><p>Multi-School SaaS - Owner: oumadavis62@gmail.com</p><p><b>Fresh System - No Mabale Data</b></p>
    <a href="/register"><button>Register Your School</button></a> <a href="/login"><button style="background:gray">Login</button></a></div>
    """

# === REGISTER ===
@app.get("/register", response_class=HTMLResponse)
def reg_page():
    return """
    <style>input{width:100%;padding:10px;margin:5px 0} button{background:#0d6efd;color:#fff;padding:10px 20px;border:none}</style>
    <h2>DaviSchool - Register School</h2>
    <form method="post" action="/register">
    <input name="school_name" placeholder="School Name" required><br>
    <input name="admin_name" placeholder="Your Full Name" required><br>
    <input name="email" type="email" placeholder="School Email" required><br>
    <input name="phone" placeholder="Phone" required><br>
    <input name="county" placeholder="County e.g. Busia"><br>
    <input name="password" type="password" placeholder="Password min 8" required><br>
    <button>Register & Get Activation Code</button>
    </form><p><a href="/login">Login</a></p>
    """

@app.post("/register")
def register(request: Request, school_name: str = Form(...), admin_name: str = Form(...), email: str = Form(...), phone: str = Form(...), county: str = Form(""), password: str = Form(...)):
    email=email.lower().strip()
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM schools WHERE email=?", (email,))
    if cur.fetchone():
        con.close(); return HTMLResponse(f"Email {email} already registered. <a href='/login'>Login</a>")

    code = gen_school_code()
    trial = (datetime.now() + timedelta(days=14)).isoformat()
    cur.execute("INSERT INTO schools (code, name, admin_name, email, phone, county, status, is_active, trial_ends_at, created_at) VALUES (?,?,?,?,?,?, 'PENDING', 0,?,?)", (code, school_name, admin_name, email, phone, county, trial, datetime.now().isoformat()))
    school_id = cur.lastrowid
    cur.execute("INSERT INTO users (school_id, name, email, username, password, role, is_school_admin) VALUES (?,?,?,?,?,?,1)", (school_id, admin_name, email, email, password, "School Admin"))

    vcode = gen_code()
    expires = (datetime.now() + timedelta(minutes=30)).isoformat()
    cur.execute("INSERT INTO email_verifications (school_id, code, expires_at) VALUES (?,?,?)", (school_id, vcode, expires))
    con.commit(); con.close()

    send_email(email, f"DaviSchool Activation Code {vcode}", f"Hello {school_name},\nYour code is: {vcode}\nExpires in 30 mins\nVerify: https://davischool-management-system.onrender.com/verify?email={email}")
    send_email(SUPER_ADMIN_EMAIL, f"NEW SCHOOL PENDING - {school_name}", f"New school: {school_name} ({code})\nAdmin: {admin_name}\nEmail: {email}\nPhone: {phone}\nCounty: {county}\nApprove at /super-admin")

    return RedirectResponse(f"/verify?email={email}", status_code=303)

@app.get("/verify", response_class=HTMLResponse)
def verify_page(email: str = ""):
    return f"""
    <h2>Enter Code sent to {email}</h2><p>Check inbox & spam</p>
    <form method="post" action="/verify">
    <input type="hidden" name="email" value="{email}">
    <input name="code" placeholder="6-digit code" maxlength="6" required>
    <button>Verify</button></form>
    <form method="post" action="/resend-code"><input type="hidden" name="email" value="{email}"><button>Resend Code</button></form>
    """

@app.post("/verify", response_class=HTMLResponse)
def verify_email(email: str = Form(...), code: str = Form(...)):
    email=email.lower()
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM schools WHERE email=?", (email,))
    school=cur.fetchone()
    if not school: return HTMLResponse("School not found")
    cur.execute("SELECT * FROM email_verifications WHERE school_id=? AND code=? ORDER BY id DESC", (school['id'], code))
    ev=cur.fetchone()
    if not ev or datetime.fromisoformat(ev['expires_at']) < datetime.now():
        con.close(); return HTMLResponse("Invalid or expired code. <a href='/register'>Try again</a>")
    cur.execute("UPDATE email_verifications SET verified_at=? WHERE id=?", (datetime.now().isoformat(), ev['id']))
    cur.execute("UPDATE schools SET status='VERIFIED' WHERE id=?", (school['id'],))
    con.commit(); con.close()
    send_email(SUPER_ADMIN_EMAIL, f"SCHOOL VERIFIED - {school['name']}", f"{school['name']} verified. Approve at /super-admin")
    return HTMLResponse(f"<h2>Email Verified!</h2><p>{school['name']} awaiting approval from {SUPER_ADMIN_EMAIL}. You will get email when approved.</p><a href='/login'>Login</a>")

@app.post("/resend-code")
def resend(email: str = Form(...)):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM schools WHERE email=?", (email,))
    school=cur.fetchone()
    if not school: con.close(); return HTMLResponse("Not found")
    code=gen_code(); exp=(datetime.now()+timedelta(minutes=30)).isoformat()
    cur.execute("INSERT INTO email_verifications (school_id, code, expires_at) VALUES (?,?,?)", (school['id'], code, exp))
    con.commit(); con.close()
    send_email(email, f"DaviSchool New Code {code}", f"New code: {code}")
    return RedirectResponse(f"/verify?email={email}", status_code=303)

# === LOGIN ===
@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """<h2>Login - DaviSchool</h2><form method="post" action="/login"><input name="email" type="email" placeholder="Email" required><br><input name="password" type="password" placeholder="Password" required><br><button>Login</button></form><p><a href="/register">Register School</a></p>"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    email=email.lower()
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    user=cur.fetchone()
    if not user:
        con.close(); return HTMLResponse("Invalid login <a href='/login'>Try again</a>")

    if email == SUPER_ADMIN_EMAIL:
        request.session["user_id"]=user["id"]; request.session["user_email"]=user["email"]; request.session["is_super_admin"]=True
        con.close(); return RedirectResponse("/super-admin", status_code=303)

    cur.execute("SELECT * FROM schools WHERE id=?", (user["school_id"],))
    school=cur.fetchone()
    con.close()
    if not school: return HTMLResponse("School not found")
    if school["status"]=="PENDING": return RedirectResponse(f"/verify?email={school['email']}", status_code=303)
    if school["status"]=="VERIFIED" and school["is_active"]==0: return HTMLResponse(f"Awaiting approval from {SUPER_ADMIN_EMAIL}. You will get email.")
    if school["is_active"]==0: return HTMLResponse(f"Blocked. Contact {SUPER_ADMIN_EMAIL}")

    request.session["user_id"]=user["id"]; request.session["user_email"]=user["email"]; request.session["user_name"]=user["name"]; request.session["role"]=user["role"]; request.session["school_id"]=user["school_id"]; request.session["school_name"]=school["name"]; request.session["is_super_admin"]=False
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/login", status_code=303)

# === SUPER ADMIN - YOU ===
@app.get("/super-admin", response_class=HTMLResponse)
def super_admin(request: Request):
    if not is_super_admin(request): return HTMLResponse("Access Denied: Only oumadavis62@gmail.com", status_code=403)
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools=cur.fetchall(); con.close()
    total=len(schools); active=len([s for s in schools if s["is_active"]==1]); pending=len([s for s in schools if s["status"] in ("PENDING","VERIFIED")])
    html=f"<h1>Super Admin - {SUPER_ADMIN_EMAIL}</h1><p>Total: {total} | Active: {active} | Pending: {pending} | <a href='/logout'>Logout</a></p><table border=1 cellpadding=8><tr><th>Code</th><th>Name</th><th>Email</th><th>Phone</th><th>Status</th><th>Trial</th><th>Action</th></tr>"
    for s in schools:
        html+=f"<tr><td>{s['code']}</td><td>{s['name']}</td><td>{s['email']}</td><td>{s['phone']}</td><td>{s['status']}</td><td>{s['trial_ends_at'][:10] if s['trial_ends_at'] else ''}</td><td><a href='/super-admin/approve/{s['id']}'>Approve</a> | <a href='/super-admin/block/{s['id']}'>Block</a></td></tr>"
    html+="</table><p>Fresh System - No Mabale Data</p>"
    return HTMLResponse(html)

@app.get("/super-admin/approve/{sid}")
def approve(sid: int, request: Request):
    if not is_super_admin(request): return HTMLResponse("Denied", status_code=403)
    con=get_db(); cur=con.cursor()
    cur.execute("UPDATE schools SET is_active=1, status='ACTIVE' WHERE id=?", (sid,))
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s=cur.fetchone()
    con.commit(); con.close()
    if s: send_email(s["email"], "DaviSchool Approved!", f"Your school {s['name']} ({s['code']}) is ACTIVE. Login at /login\nTrial ends: {s['trial_ends_at']}")
    return RedirectResponse("/super-admin", status_code=303)

@app.get("/super-admin/block/{sid}")
def block(sid: int, request: Request):
    if not is_super_admin(request): return HTMLResponse("Denied", status_code=403)
    con=get_db(); cur=con.cursor(); cur.execute("UPDATE schools SET is_active=0, status='BLOCKED' WHERE id=?", (sid,)); con.commit(); con.close()
    return RedirectResponse("/super-admin", status_code=303)

# === SCHOOL DASHBOARD ===
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "user_id" not in request.session: return RedirectResponse("/login", status_code=303)
    if is_super_admin(request): return RedirectResponse("/super-admin", status_code=303)
    school_id=request.session.get("school_id")
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE school_id=?", (school_id,)); sc=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM teachers WHERE school_id=?", (school_id,)); tc=cur.fetchone()[0]
    cur.execute("SELECT * FROM schools WHERE id=?", (school_id,)); school=cur.fetchone()
    con.close()
    return f"""
    <h2>{request.session.get('school_name')} - Dashboard (Fresh)</h2>
    <p>{request.session.get('user_name')} - Role: {request.session.get('role')} | Header shows Teacher exactly like School Admin as requested</p>
    <p>School Code: {school['code']} | Trial ends: {school['trial_ends_at']} | Students: {sc} | Teachers: {tc}</p>
    <p><a href="/students">Students</a> | <a href="/teachers">Teachers</a> | <a href="/my-profile">My Profile (shows role)</a> | <a href="/logout">Logout</a></p>
    <p><b>Fresh System - 0 students initially, no Mabale data</b></p>
    """

@app.get("/my-profile", response_class=HTMLResponse)
def my_profile(request: Request):
    if "user_id" not in request.session: return RedirectResponse("/login", status_code=303)
    return f"<h3>My Profile</h3><p>Name: {request.session.get('user_name')}</p><p>Email: {request.session.get('user_email')}</p><p>Role: {request.session.get('role')} - This shows in header exactly as requested (Teacher or School Admin)</p><a href='/dashboard'>Back</a>"

@app.get("/students", response_class=HTMLResponse)
def list_students(request: Request):
    if "user_id" not in request.session: return RedirectResponse("/login", status_code=303)
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM students WHERE school_id=?", (request.session["school_id"],)); rows=cur.fetchall(); con.close()
    html=f"<h3>Students - {request.session.get('school_name')} - Fresh (0 initially)</h3><table border=1><tr><th>ADM</th><th>Name</th><th>Class</th></tr>"
    for r in rows: html+=f"<tr><td>{r['adm']}</td><td>{r['name']}</td><td>{r['class']}</td></tr>"
    @app.get("/super-admin/reset-all-mabale-data")
def reset_all(request: Request):
    if request.session.get("user_email") != "oumadavis62@gmail.com": 
        return HTMLResponse("Denied - Only oumadavis62@gmail.com", status_code=403)
    con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM students")
    cur.execute("DELETE FROM teachers")
    cur.execute("DELETE FROM marks")
    cur.execute("DELETE FROM fees")
    cur.execute("DELETE FROM school_classes")
    cur.execute("DELETE FROM schools WHERE email != ?", (SUPER_ADMIN_EMAIL,))
    cur.execute("DELETE FROM users WHERE email != ?", (SUPER_ADMIN_EMAIL,))
    cur.execute("DELETE FROM email_verifications")
    con.commit(); con.close()
    return HTMLResponse(f"<h1>All Mabale data wiped!</h1><p>Fresh system ready. Only {SUPER_ADMIN_EMAIL} remains.</p><a href='/super-admin'>Go to Super Admin</a>")

@app.post("/students/add")
def add_student(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class")):
    con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO students (school_id, adm, name, class) VALUES (?,?,?,?)", (request.session["school_id"], adm, name, class_)); con.commit(); con.close()
    return RedirectResponse("/students", status_code=303)
