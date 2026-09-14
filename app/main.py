from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-key-2026")
SUPER_ADMIN_EMAIL = "oumadavis62@gmail.com"
DB_PATH = "davischool.db"

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, approved INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, school_id INTEGER, role TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, name TEXT, class TEXT, gender TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, subject TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS school_classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT)")
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit()
    con.close()

init_db()

def wrap(school_name, body_html, user_email, role_display, active="overview"):
    ov = "background:#0f172a; color:white" if active=="overview" else ""
    ac = "background:#0f172a; color:white" if active=="academics" else ""
    return f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0; font-family:Arial; background:#fcfcfc; display:flex}}.sidebar{{width:270px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed}}.main{{margin-left:270px; flex:1}}.topbar{{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between}}.content{{padding:20px}}.nav-item{{display:block; padding:10px; color:#334155; text-decoration:none; border-radius:8px; margin:2px 10px}}.card{{background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:16px}}.profile-wrap{{position:relative}}.avatar{{width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center}}</style></head><body><div class='sidebar'><div style='padding:16px; border-bottom:1px solid #e2e8f0'><b>DaviSchool</b></div><a class='nav-item' href='/dashboard' style='{ov}'>System Overview</a><a class='nav-item' href='/academics' style='{ac}'>Academic Analytics</a><a class='nav-item' href='/students'>Students Manager</a><div style='padding:14px; margin-top:20px; border-top:1px solid #e2e8f0'>Davis Ouma<br><small>{user_email}</small></div></div><div class='main'><div class='topbar'><div><b>{school_name}</b> (DS-2026)</div><div><b>Davis Ouma</b> - {role_display} - {user_email} | <a href='/logout'>Logout</a></div></div>{body_html}</div></body></html>"

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:400px'><h1>Welcome Back</h1><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%; padding:12px; margin:8px 0'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:8px 0'><button style='width:100%; background:#2563eb; color:white; padding:12px; border:none; border-radius:8px'>Sign In</button></form><p><a href='/register'>Register School</a></p></div></body></html>")

@app.get("/register", response_class=HTMLResponse)
def reg_page():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh'><div style='width:400px'><h2>Register - DaviSchool</h2><form method='post' action='/register'><input name='school_name' placeholder='School Name' required style='width:100%; padding:12px; margin:6px 0'><input name='email' placeholder='Email' required style='width:100%; padding:12px; margin:6px 0'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:6px 0'><button style='width:100%; background:#2563eb; color:white; padding:12px'>Register</button></form></div></body></html>")

@app.post("/register")
def register(school_name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO schools (name, email, approved) VALUES (?,?,0)", (school_name, email))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email, password, school_id, role) VALUES (?,?,?,?)", (email, password, sid, "admin"))
    con.commit(); con.close()
    return RedirectResponse("/", status_code=303)

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    user = cur.fetchone()
    if not user:
        con.close()
        return HTMLResponse("Invalid login - <a href='/'>Try again</a>")
    if user["role"] == "super_admin":
        request.session["user_email"] = email
        request.session["role"] = "super_admin"
        con.close()
        return RedirectResponse("/super-admin", status_code=303)
    cur.execute("SELECT * FROM schools WHERE id=?", (user["school_id"],))
    school = cur.fetchone()
    con.close()
    if school and school["approved"] == 0:
        return HTMLResponse(f"School {school['name']} not approved yet - <a href='/'>Back</a>")
    request.session["user_email"] = email
    request.session["school_id"] = user["school_id"]
    request.session["school_name"] = school["name"] if school else "DaviSchool"
    request.session["role"] = "admin"
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name", "DaviSchool")
    con = get_db(); cur = con.cursor()
    sid = request.session.get("school_id",0)
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=?", (sid,))
    sc = cur.fetchone()["c"]
    con.close()
    body = f"<div class='content'><h1>School Overview - {sname}</h1><p>Top right: Davis Ouma - {role} - {email}</p><div class='card'>Total Students: {sc}</div><div class='card'><a href='/academics'>Go to Academic Analytics - Test Teacher Performance tab</a></div><div class='card'>Settings: 7 cards - User Management, Roles, School Profile, Classes, Backup, Audit, Integrations (Bulk SMS + M-Pesa) - at bottom left</div></div>"
    return HTMLResponse(wrap(sname, body, email, role, "overview"))

@app.get("/academics", response_class=HTMLResponse)
def academics(request: Request, term: str = "Term 1", year: str = "2026", grade: str = "GRADE 7", tab: str = "performance"):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name", "DaviSchool")

    # Build dropdowns safe
    t_opts = ""
    for t in ["Term 1","Term 2","Term 3"]:
        sel = "selected" if t==term else ""
        t_opts += f"<option {sel}>{t}</option>"
    y_opts = ""
    for y in ["2024","2025","2026"]:
        sel = "selected" if y==year else ""
        y_opts += f"<option {sel}>{y}</option>"

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT DISTINCT class FROM students WHERE school_id=?", (request.session.get("school_id",0),))
    classes = [r["class"] for r in cur.fetchall() if r["class"]]
    cur.execute("SELECT name FROM students WHERE school_id=? LIMIT 2", (request.session.get("school_id",0),))
    snames = [r["name"] for r in cur.fetchall()]
    con.close()
    if not classes:
        classes = ["GRADE 7","GRADE 8","GRADE 9"]
    if not snames:
        snames = ["FLORENCE"]
    g_opts = ""
    for g in classes:
        sel = "selected" if g==grade else ""
        g_opts += f"<option {sel}>{g}</option>"

    if tab == "teacher":
        cards = """
        <div class='card'><b>Top 10 Teachers by Value Added</b><div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No teacher performance data available</div></div>
        <div class='card'><b>Teacher Value-Added Details</b><div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No teacher value-added data available</div></div>
        """
    elif tab == "student":
        badge = snames[0].upper() + " ->"
        cards = f"""
        <div class='card'><div style='display:flex; justify-content:space-between'><b>Student Trajectories</b><span style='border:1px solid #e2e8f0; padding:4px 10px; border-radius:20px; font-size:12px'>Show At-Risk Only</span></div><div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No student trajectory data available</div></div>
        <div class='card'><b>Cohort Tracking</b><div>Select students to track their progression:</div><div style='margin-top:8px'><span style='background:#f1f5f9; padding:4px 10px; border-radius:20px; font-size:12px'>{badge}</span></div><div style='height:150px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>Select students above to view their progression chart</div></div>
        """
    elif tab == "subject":
        cards = """
        <div class='card'><b>Subject Performance Matrix</b><div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No subject performance data available</div></div>
        <div class='card'><b>Gender Gap Analysis</b><div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No gender gap data available</div></div>
        """
    else:
        cards = f"""
        <div class='card'><b>Class Performance Over Time</b><div style='height:200px; display:flex; align-items:center; justify-content:center; color:#94a3b8'>No exam data available for the selected filters - Term: {term} | Year: {year} | Grade: {grade}</div></div>
        <div class='card'><b>Yearly Progression - {year}</b><div style='height:200px; border-left:1px solid #ccc; border-bottom:1px solid #ccc; display:flex; align-items:center; justify-content:center'>Chart placeholder - Fresh system</div></div>
        <div class='card'><b>Subject Trends Across Terms - T3 2026</b><div>AGRICULTURE, CRE, ENGLISH, MATHEMATICS, etc - Fresh</div></div>
        """

    body = f"""
    <div class='content'>
        <h1>Academic Analytics</h1>
        <div style='color:#64748b; margin-bottom:12px'>Performance insights</div>
        <div style='display:flex; gap:8px; margin-bottom:16px'>
            <select id='t' onchange='go()'>{t_opts}</select>
            <select id='y' onchange='go()'>{y_opts}</select>
            <select id='g' onchange='go()'>{g_opts}</select>
        </div>
        <div style='display:flex; gap:16px; border-bottom:1px solid #e2e8f0; margin-bottom:16px; padding-bottom:8px'>
            <a href='/academics?term={term}&year={year}&grade={grade}&tab=performance'>Performance Trends</a>
            <a href='/academics?term={term}&year={year}&grade={grade}&tab=subject'>Subject Analysis</a>
            <a href='/academics?term={term}&year={year}&grade={grade}&tab=teacher' style='font-weight:bold; border-bottom:2px solid black'>Teacher Performance</a>
            <a href='/academics?term={term}&year={year}&grade={grade}&tab=student'>Student Tracking</a>
        </div>
        {cards}
    </div>
    <script>
    function go(){{
        var t=document.getElementById('t').value;
        var y=document.getElementById('y').value;
        var g=document.getElementById('g').value;
        window.location='/academics?term='+encodeURIComponent(t)+'&year='+encodeURIComponent(y)+'&grade='+encodeURIComponent(g)+'&tab={tab}';
    }}
    </script>
    """
    return HTMLResponse(wrap(sname, body, email, role, "academics"))

@app.get("/students", response_class=HTMLResponse)
def students(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    role = "Super Admin" if request.session.get("role")=="super_admin" else "School Admin"
    sname = request.session.get("school_name","DaviSchool")
    body = "<div class='content'><div class='card'><h3>Students - Fresh</h3><form method='post' action='/students/add'><input name='adm' placeholder='ADM' required><input name='name' placeholder='Name' required><input name='class' placeholder='Class'><select name='gender'><option>Boy</option><option>Girl</option></select><button>Add</button></form></div></div>"
    return HTMLResponse(wrap(sname, body, email, role))

@app.post("/students/add")
def add_student(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class"), gender: str = Form("Boy")):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, adm, name, class, gender) VALUES (?,?,?,?,?)", (request.session.get("school_id",0), adm, name, class_, gender))
    con.commit(); con.close()
    return RedirectResponse("/students", status_code=303)

@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("user_email")
    body = "<div class='content'><h1>Settings - 7 cards</h1><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:12px'><div class='card'>User Management</div><div class='card'>Roles & Permissions</div><div class='card'>School Profile</div><div class='card'>Classes & Streams</div><div class='card'>Database Backup</div><div class='card'>Audit Trail</div><div class='card'>Integrations - Bulk SMS and M-Pesa - BOTTOM LEFT</div></div></div>"
    return HTMLResponse(wrap("DaviSchool", body, email, "Super Admin"))

@app.get("/super-admin", response_class=HTMLResponse)
def super_admin(request: Request):
    if request.session.get("user_email")!= SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    body = f"<div class='content'><div class='card'><h3>Super Admin {SUPER_ADMIN_EMAIL}</h3><a href='/super-admin/reset' style='background:red; color:white; padding:8px; border-radius:6px; text-decoration:none'>RESET ALL</a> <a href='/logout'>Logout</a></div></div>"
    return HTMLResponse(wrap("Super Admin", body, SUPER_ADMIN_EMAIL, "Super Admin"))

@app.get("/super-admin/reset")
def reset(request: Request):
    if request.session.get("user_email")!= SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM students"); cur.execute("DELETE FROM teachers"); cur.execute("DELETE FROM schools WHERE email!=?", (SUPER_ADMIN_EMAIL,)); cur.execute("DELETE FROM users WHERE email!=?", (SUPER_ADMIN_EMAIL,))
    con.commit(); con.close()
    return HTMLResponse("Wiped - <a href='/super-admin'>Back</a>")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
@app.get("/teachers")
def t(request: Request):
    return RedirectResponse("/dashboard")
