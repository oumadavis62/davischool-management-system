from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-secret-2026-pro")
SUPER_ADMIN_EMAIL = "oumadavis62@gmail.com"
DB_PATH = "davischool.db"

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con=get_db(); cur=con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, approved INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, school_id INTEGER, role TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, name TEXT, class TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, subject TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, subject TEXT, score INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, amount INTEGER, status TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS school_classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS email_verifications (email TEXT, code TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit(); con.close()
init_db()

def page_wrap(title, body):
    return f"""
    <html><head><meta name='viewport' content='width=device-width, initial-scale=1'>
    <style>
    body{{font-family:Arial,sans-serif; margin:0; background:#f4f6f9}}
    .nav{{background:#1a237e; color:white; padding:15px 25px; display:flex; justify-content:space-between; align-items:center}}
    .nav a{{color:white; text-decoration:none; margin-left:15px}}
    .container{{padding:20px; max-width:1100px; margin:auto}}
    .card{{background:white; border-radius:12px; padding:20px; box-shadow:0 2px 10px rgba(0,0,0,0.1); margin-bottom:20px}}
    .stats{{display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:15px}}
    .stat{{background:white; border-radius:12px; padding:20px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.08); border-left:5px solid #1a237e}}
    .stat h2{{margin:0; font-size:32px; color:#1a237e}}
    table{{width:100%; border-collapse:collapse; background:white; border-radius:10px; overflow:hidden}}
    th{{background:#1a237e; color:white; padding:12px; text-align:left}} td{{padding:10px; border-bottom:1px solid #eee}}
    .btn{{background:#1a237e; color:white; padding:10px 18px; border:none; border-radius:6px; cursor:pointer; text-decoration:none; display:inline-block}}
    .btn-green{{background:#2e7d32}} .btn-red{{background:#c62828}}
    input{{padding:10px; border:1px solid #ccc; border-radius:6px; margin:5px}}
    </style></head><body>
    <div class='nav'><div><b>📚 DaviSchool Management</b></div><div><a href='/dashboard'>Dashboard</a><a href='/students'>Students</a><a href='/super-admin'>Super Admin</a><a href='/logout'>Logout</a></div></div>
    <div class='container'><h2>{title}</h2>{body}</div></body></html>
    """

@app.get("/", response_class=HTMLResponse)
def home():
    body="<div class='card'><h1>Welcome to DaviSchool</h1><p>Complete School Management System for Kenya Schools</p><a class='btn' href='/register'>Register Your School</a> <a class='btn' href='/login'>Login</a></div>"
    return HTMLResponse(page_wrap("Home", body))

@app.get("/register", response_class=HTMLResponse)
def register_page():
    body="<div class='card'><h3>Register School</h3><form method='post' action='/register'><input name='school_name' placeholder='School Name' required><br><input name='email' placeholder='Admin Email' required><br><input name='password' type='password' placeholder='Password' required><br><button class='btn'>Register</button></form></div>"
    return HTMLResponse(page_wrap("Register", body))

@app.post("/register")
def register(school_name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO schools (name, email, approved) VALUES (?,?,0)", (school_name, email))
    school_id=cur.lastrowid
    cur.execute("INSERT INTO users (email, password, school_id, role) VALUES (?,?,?,?)", (email, password, school_id, "admin"))
    con.commit(); con.close()
    return RedirectResponse("/login", status_code=303)

@app.get("/login", response_class=HTMLResponse)
def login_page():
    body="<div class='card'><h3>Login to DaviSchool</h3><form method='post' action='/login'><input name='email' placeholder='Email' required><br><input name='password' type='password' placeholder='Password' required><br><button class='btn'>Login</button></form><p>Super Admin: oumadavis62@gmail.com</p></div>"
    return HTMLResponse(page_wrap("Login", body))

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    user=cur.fetchone()
    if not user:
        con.close()
        return HTMLResponse(page_wrap("Error", "<div class='card'>Invalid login <a href='/login'>Try again</a></div>"))
    if user["role"] == "super_admin":
        request.session["user_email"]=email; request.session["role"]="super_admin"
        con.close()
        return RedirectResponse("/super-admin", status_code=303)
    cur.execute("SELECT * FROM schools WHERE id=?", (user["school_id"],))
    school=cur.fetchone(); con.close()
    if school and school["approved"]==0:
        return HTMLResponse(page_wrap("Pending", "<div class='card'>School not yet approved by Super Admin. Please wait for approval.</div>"))
    request.session["user_email"]=email; request.session["school_id"]=user["school_id"]; request.session["school_name"]=school["name"] if school else ""; request.session["role"]="admin"
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "school_id" not in request.session:
        return RedirectResponse("/login")
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=?", (request.session["school_id"],))
    sc=cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) as c FROM teachers WHERE school_id=?", (request.session["school_id"],))
    tc=cur.fetchone()["c"]; con.close()
    body=f"""
    <div class='stats'>
        <div class='stat'><h2>{sc}</h2><p>Students - Fresh (0 initially)</p></div>
        <div class='stat' style='border-left-color:#2e7d32'><h2>{tc}</h2><p>Teachers</p></div>
        <div class='stat' style='border-left-color:#ff6f00'><h2>{request.session.get('school_name')}</h2><p>Your School</p></div>
    </div>
    <div class='card'><h3>Quick Actions</h3><a class='btn' href='/students'>View Students List</a> <a class='btn btn-green' href='/students'>Add Student</a></div>
    """
    return HTMLResponse(page_wrap(f"Dashboard - {request.session.get('school_name')}", body))

@app.get("/students", response_class=HTMLResponse)
def students_list(request: Request):
    if "school_id" not in request.session:
        return RedirectResponse("/login")
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM students WHERE school_id=?", (request.session["school_id"],))
    rows=cur.fetchall(); con.close()
    rows_html="".join([f"<tr><td>{r['adm']}</td><td>{r['name']}</td><td>{r['class']}</td></tr>" for r in rows]) or "<tr><td colspan=3 style='text-align:center; padding:20px'>No students yet - Fresh (0 initially) - Add your first student below</td></tr>"
    body=f"""
    <div class='card'><h3>Students - {request.session.get('school_name')} - Fresh (0 initially)</h3>
    <form method='post' action='/students/add'><input name='adm' placeholder='ADM No' required><input name='name' placeholder='Full Name' required><input name='class' placeholder='Class (e.g. Class 8)'><button class='btn btn-green'>+ Add Student</button></form></div>
    <div class='card'><table><tr><th>ADM</th><th>Name</th><th>Class</th></tr>{rows_html}</table></div>
    """
    return HTMLResponse(page_wrap("Students List", body))

@app.post("/students/add")
def add_student(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class")):
    if "school_id" not in request.session:
        return RedirectResponse("/login")
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO students (school_id, adm, name, class) VALUES (?,?,?,?)", (request.session["school_id"], adm, name, class_))
    con.commit(); con.close()
    return RedirectResponse("/students", status_code=303)

@app.get("/super-admin", response_class=HTMLResponse)
def super_admin(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse(page_wrap("Denied", "<div class='card'>Denied - Only Super Admin</div>"), status_code=403)
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM schools"); schools=cur.fetchall()
    cur.execute("SELECT COUNT(*) as c FROM students"); sc=cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM teachers"); tc=cur.fetchone()["c"]
    con.close()
    schools_html="".join([f"<tr><td>{s['name']}</td><td>{s['email']}</td><td>{'✅ Approved' if s['approved'] else '⏳ Pending'}</td><td><a class='btn btn-green' href='/super-admin/approve/{s['id']}'>Approve</a></td></tr>" for s in schools]) or "<tr><td colspan=4 style='text-align:center'>No schools registered yet - Fresh System</td></tr>"
    body=f"""
    <div class='stats'><div class='stat'><h2>{sc}</h2><p>Total Students</p></div><div class='stat'><h2>{tc}</h2><p>Total Teachers</p></div><div class='stat'><h2>{len(schools)}</h2><p>Total Schools</p></div></div>
    <div class='card'><h3>Super Admin - {SUPER_ADMIN_EMAIL}</h3><p>Students: {sc} | Teachers: {tc} - FRESH SYSTEM</p>
    <a class='btn btn-red' href='/super-admin/reset-all-mabale-data' onclick="return confirm('Are you sure you want to DELETE ALL DATA?')">RESET ALL MABALE DATA (Make Fresh)</a> <a class='btn' href='/logout'>Logout</a></div>
    <div class='card'><h3>Schools Management</h3><table><tr><th>School Name</th><th>Email</th><th>Status</th><th>Action</th></tr>{schools_html}</table></div>
    """
    return HTMLResponse(page_wrap("Super Admin", body))

@app.get("/super-admin/approve/{school_id}")
def approve(request: Request, school_id: int):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    con=get_db(); cur=con.cursor()
    cur.execute("UPDATE schools SET approved=1 WHERE id=?", (school_id,))
    con.commit(); con.close()
    return RedirectResponse("/super-admin", status_code=303)

@app.get("/super-admin/reset-all-mabale-data")
def reset_all(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM students"); cur.execute("DELETE FROM teachers"); cur.execute("DELETE FROM marks"); cur.execute("DELETE FROM fees"); cur.execute("DELETE FROM school_classes")
    cur.execute("DELETE FROM schools WHERE email != ?", (SUPER_ADMIN_EMAIL,)); cur.execute("DELETE FROM users WHERE email != ?", (SUPER_ADMIN_EMAIL,)); cur.execute("DELETE FROM email_verifications")
    con.commit(); con.close()
    return HTMLResponse(page_wrap("Wiped", f"<div class='card'><h1>✅ All Mabale data wiped!</h1><p>Fresh system ready. Only {SUPER_ADMIN_EMAIL} remains.</p><a class='btn' href='/super-admin'>Go to Super Admin</a></div>"))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
