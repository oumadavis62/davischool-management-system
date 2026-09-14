from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3, os, secrets
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-secret-2026")
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
    # create super admin user if not exists
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit(); con.close()

init_db()

@app.get("/", response_class=HTMLResponse)
def home():
    return '<h1>DaviSchool Management System</h1><a href="/register">Register School</a> | <a href="/login">Login</a>'

@app.get("/register", response_class=HTMLResponse)
def register_page():
    return '''<h2>Register School</h2><form method="post" action="/register"><input name="school_name" placeholder="School Name" required><input name="email" placeholder="Email" required><input name="password" type="password" placeholder="Password" required><button>Register</button></form>'''

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
    return '''<h2>Login</h2><form method="post" action="/login"><input name="email" placeholder="Email" required><input name="password" type="password" placeholder="Password" required><button>Login</button></form>'''

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    user=cur.fetchone()
    if not user:
        con.close()
        return HTMLResponse("Invalid login")
    if user["role"] == "super_admin":
        request.session["user_email"]=email
        request.session["role"]="super_admin"
        con.close()
        return RedirectResponse("/super-admin", status_code=303)
    cur.execute("SELECT * FROM schools WHERE id=?", (user["school_id"],))
    school=cur.fetchone()
    con.close()
    if school and school["approved"]==0:
        return HTMLResponse("School not yet approved by Super Admin")
    request.session["user_email"]=email
    request.session["school_id"]=user["school_id"]
    request.session["school_name"]=school["name"] if school else ""
    request.session["role"]="admin"
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "school_id" not in request.session:
        return RedirectResponse("/login")
    name=request.session.get("school_name")
    return f'<h1>Welcome {name}</h1><a href="/students">Students List</a> | <a href="/teachers">Teachers</a> | <a href="/logout">Logout</a>'

@app.get("/students", response_class=HTMLResponse)
def students_list(request: Request):
    if "school_id" not in request.session:
        return RedirectResponse("/login")
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM students WHERE school_id=?", (request.session["school_id"],))
    rows=cur.fetchall(); con.close()
    html=f"<h3>Students - {request.session.get('school_name')} - Fresh (0 initially)</h3>"
    html+='<form method="post" action="/students/add"><input name="adm" placeholder="ADM" required><input name="name" placeholder="Name" required><input name="class" placeholder="Class"><button>Add</button></form>'
    html+="<table border=1><tr><th>ADM</th><th>Name</th><th>Class</th></tr>"
    for r in rows:
        html+=f"<tr><td>{r['adm']}</td><td>{r['name']}</td><td>{r['class']}</td></tr>"
    html+="</table><a href='/dashboard'>Back</a>"
    return HTMLResponse(html)

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
        return HTMLResponse("Denied - Only Super Admin", status_code=403)
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM schools")
    schools=cur.fetchall()
    cur.execute("SELECT COUNT(*) as c FROM students"); sc=cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM teachers"); tc=cur.fetchone()["c"]
    con.close()
    html=f"<h1>Super Admin - {SUPER_ADMIN_EMAIL}</h1><p>Students: {sc} | Teachers: {tc}</p><hr><h3>Schools</h3><ul>"
    for s in schools:
        status="Approved" if s["approved"] else "Pending"
        html+=f"<li>{s['name']} - {s['email']} - {status} - <a href='/super-admin/approve/{s['id']}'>Approve</a></li>"
    html+=f"</ul><hr><a href='/super-admin/reset-all-mabale-data'>RESET ALL MABALE DATA (Make Fresh)</a> | <a href='/logout'>Logout</a>"
    return HTMLResponse(html)

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

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
