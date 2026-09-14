from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-final-key-2026")
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
    try:
        cur.execute("ALTER TABLE students ADD COLUMN gender TEXT")
    except:
        pass
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit()
    con.close()

init_db()

def login_page(error_msg=""):
    err = f"<div class='error'>{error_msg}</div>" if error_msg else ""
    return f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
    body{{font-family:Arial; margin:0; background:white; display:flex; justify-content:center; align-items:center; min-height:100vh}}
    .login-box{{width:100%; max-width:440px; padding:40px 20px}} h1{{font-size:34px; font-weight:800; margin:0 0 6px; color:#0f172a}} .subtitle{{color:#475569; margin-bottom:32px}}
    label{{font-weight:600; color:#334155; font-size:14px; display:block; margin:20px 0 8px}} input{{width:100%; padding:14px 16px; border:1px solid #e2e8f0; border-radius:10px; font-size:15px; box-sizing:border-box}}
    .btn-sign{{width:100%; background:#2563eb; color:white; border:none; padding:14px; border-radius:10px; font-size:16px; font-weight:600; cursor:pointer}}
    .error{{background:#fef2f2; color:#b91c1c; padding:10px; border-radius:8px; margin-bottom:16px; border:1px solid #fecaca}} .bottom-link{{text-align:center; margin-top:20px; color:#64748b; font-size:14px}} .bottom-link a{{color:#2563eb; text-decoration:none; font-weight:600}}
    </style></head><body><div class='login-box'><h1>Welcome Back</h1><div class='subtitle'>Sign in to your DaviSchool account</div>
    {err}
    <form method='post' action='/login'><label>Username or Email</label><input type='text' name='email' required>
    <label>Password</label><input type='password' name='password' required>
    <div style='display:flex; justify-content:space-between; margin:16px 0 24px; font-size:14px'><label><input type='checkbox'> Remember me</label><a href='#' style='color:#0f7a5a; font-weight:600; text-decoration:none'>Forgot Password?</a></div>
    <button class='btn-sign' type='submit'>Sign In</button></form><div class='bottom-link'>Don't have account? <a href='/register'>Register your School</a></div></div></body></html>"""

def wrap(school_name, body_html, user_email, user_role_display, active_tab="overview"):
    ov_style = "background:#0f172a; color:white" if active_tab=="overview" else "background:#f1f5f9; border:1px solid #e2e8f0; font-weight:700; color:#0f172a"
    ac_style = "background:#0f172a; color:white" if active_tab=="academics" else ""
    return f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
    *{{box-sizing:border-box}} body{{margin:0; font-family:Arial; background:#fcfcfc; display:flex}}
    .sidebar{{width:270px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}}
    .logo{{padding:18px 20px; border-bottom:1px solid #f1f5f9; display:flex; align-items:center; gap:10px}} .logo-icon{{width:38px; height:38px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800}}
    .logo b{{color:#0f5b9e; font-size:16px}} .logo small{{display:block; color:#64748b; font-size:9px; letter-spacing:1px}}
    .nav-section{{padding:12px 14px}} .nav-label{{font-size:12px; color:#94a3b8; font-weight:600; margin:10px 8px 8px; text-transform:uppercase}}
    .nav-item{{display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:8px; color:#334155; text-decoration:none; font-size:14px; margin-bottom:2px}}
    .nav-item.active{{background:#0f172a; color:white}} .sub{{margin-left:28px; border-left:1px dashed #e2e8f0; padding-left:12px}}
    .main{{margin-left:270px; flex:1; min-height:100vh}} .topbar{{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:10}}
    .content{{padding:24px}} .grid4{{display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:16px}} .card{{background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px; display:flex; justify-content:space-between}}
    .profile-wrap{{position:relative}} .profile-btn{{display:flex; align-items:center; gap:8px; cursor:pointer; border:none; background:transparent}} 
    .avatar{{width:36px; height:36px; background:#f1f5f9; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700}}
    .dropdown{{position:absolute; top:45px; right:0; width:250px; background:white; border:1px solid #e2e8f0; border-radius:12px; box-shadow:0 10px 25px rgba(0,0,0,0.1); display:none; z-index:100; overflow:hidden}}
    .dropdown.show{{display:block}} .drop-header{{padding:14px 16px; border-bottom:1px solid #f1f5f9}} .drop-item{{display:flex; align-items:center; gap:12px; padding:12px 16px; text-decoration:none; color:#334155; font-size:14px}} .drop-item:hover{{background:#f8fafc}} .drop-item.logout{{color:#dc2626; border-top:1px solid #f1f5f9}}
    </style></head><body>
    <div class='sidebar'><div class='logo'><div class='logo-icon'>D</div><div><b>DaviSchool</b><small>SCHOOL MANAGEMENT SYSTEM</small></div></div>
    <div class='nav-section'><div class='nav-label'>Main Navigation</div><a class='nav-item active'>Dashboard</a>
    <div class='sub'><a class='nav-item' href='/dashboard' style='{ov_style}'>System Overview</a><a class='nav-item' href='/academics' style='{ac_style}'>Academic Analytics</a><a class='nav-item'>Financial Analytics</a><a class='nav-item'>Attendance Analytics</a></div>
    <a class='nav-item' href='/students'>Students Manager</a><a class='nav-item' href='/teachers'>Staff Manager</a></div>
    <div style='padding:14px; border-top:1px solid #f1f5f9; margin-top:20px; display:flex; gap:10px; align-items:center'><div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700'>DO</div><div><div style='font-size:13px; font-weight:600'>Davis Ouma</div><div style='font-size:11px; color:#64748b'>{user_email}</div></div></div></div>
    <div class='main'><div class='topbar'><div><b>{school_name.upper()}</b> <small>(Code: DS-2026)</small></div>
    <div style='display:flex; gap:16px; align-items:center'><span>?</span>
        <div class='profile-wrap'><button class='profile-btn' onclick='document.getElementById("profileDrop").classList.toggle("show")'><div class='avatar'>DO</div><div style='text-align:left'><div style='font-size:14px; font-weight:600'>Davis Ouma</div><div style='font-size:12px; color:#64748b'>{user_role_display}</div></div><span>^</span></button>
            <div id='profileDrop' class='dropdown'><div class='drop-header'><b>Davis Ouma</b><small>{user_email}</small></div><a class='drop-item' href='/profile'>Profile</a><a class='drop-item' href='/settings'>Settings</a><a class='drop-item logout' href='/logout'>Log out</a></div>
        </div>
    </div></div>{body_html}</div>
    <script>window.onclick=function(e){{if(!e.target.closest('.profile-wrap')){{document.getElementById('profileDrop').classList.remove('show')}}}}</script>
    </body></html>"""

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(login_page())

@app.get("/register", response_class=HTMLResponse)
def register_page():
    return HTMLResponse("<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc'><div style='background:white; padding:30px; border-radius:16px; box-shadow:0 4px 20px rgba(0,0,0,0.08); width:400px'><h2>Register School - DaviSchool</h2><form method='post' action='/register'><input name='school_name' placeholder='School Name' required style='width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:8px'><input name='email' placeholder='Admin Email' required style='width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:8px'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:8px'><button style='width:100%; background:#2563eb; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>Register</button></form><p><a href='/'>Back to Login</a></p></div></body></html>")

@app.post("/register")
def register(school_name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("INSERT INTO schools (name, email, approved) VALUES (?,?,0)", (school_name, email))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email, password, school_id, role) VALUES (?,?,?,?)", (email, password, sid, "admin"))
    con.commit()
    con.close()
    return HTMLResponse(login_page(f"School {school_name} registered! Wait for approval."))

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    user = cur.fetchone()
    if not user:
        con.close()
        return HTMLResponse(login_page("Invalid username or password."))
    if user["role"] == "super_admin":
        request.session["user_email"] = email
        request.session["role"] = "super_admin"
        con.close()
        return RedirectResponse("/super-admin", status_code=303)
    cur.execute("SELECT * FROM schools WHERE id=?", (user["school_id"],))
    school = cur.fetchone()
    con.close()
    if school and school["approved"] == 0:
        return HTMLResponse(login_page(f"School {school['name']} not yet approved."))
    request.session["user_email"] = email
    request.session["school_id"] = user["school_id"]
    request.session["school_name"] = school["name"] if school else ""
    request.session["role"] = "admin"
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "school_id" not in request.session and request.session.get("role") != "super_admin":
        return RedirectResponse("/")
    is_super = request.session.get("role") == "super_admin" or request.session.get("user_email") == SUPER_ADMIN_EMAIL
    user_email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role_display = "Super Admin" if is_super else "School Admin"
    school_name = request.session.get("school_name", "DaviSchool")
    con = get_db()
    cur = con.cursor()
    sid = request.session.get("school_id", 0)
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=?", (sid,))
    sc = cur.fetchone()["c"] if sid else 0
    cur.execute("SELECT COUNT(*) as c FROM teachers WHERE school_id=?", (sid,))
    tc = cur.fetchone()["c"] if sid else 0
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND gender='Boy'", (sid,))
    boys = cur.fetchone()["c"] if sid else 0
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND gender='Girl'", (sid,))
    girls = cur.fetchone()["c"] if sid else 0
    con.close()
    total = boys + girls
    ratio = "0:1"
    if boys > 0 and girls > 0:
        ratio = f"{girls/boys:.2f}:1"
    body = f"""<div class='content'><h1>School Overview</h1><p>Welcome back, Davis! {school_name}</p>
    <div class='grid4'><div class='card'><div><h4>Total Students</h4><h2>{sc}</h2></div></div><div class='card'><div><h4>Total Staff</h4><h2>{tc}</h2></div></div><div class='card'><div><h4>Fee Collection</h4><h2>0%</h2></div></div><div class='card'><div><h4>Attendance</h4><h2>--</h2></div></div></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-top:20px; max-width:700px; margin-left:auto; margin-right:auto'>
        <div><b>Students by Gender</b><div style='color:#64748b; font-size:13px'>Boys vs Girls</div></div>
        <div style='display:flex; gap:10px; margin-top:16px; text-align:center'><div style='background:#eff6ff; padding:10px; border-radius:10px; flex:1'><div>Total Boys</div><b>{boys}</b></div><div style='background:#fdf2f8; padding:10px; border-radius:10px; flex:1'><div>Total Girls</div><b>{girls}</b></div><div style='background:#f8fafc; padding:10px; border-radius:10px; flex:1'><div>Total Students</div><b>{total}</b></div><div style='background:#f8fafc; padding:10px; border-radius:10px; flex:1'><div>Ratio</div><b>{ratio}</b></div></div>
    </div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-top:20px'><b>Cumulative Balances by Class</b><div>Total: KES 0</div><div style='margin-top:10px'><div>GRADE 7 - {sc} students - KES 0</div><div>GRADE 8 - 0 students - KES 0</div><div>GRADE 9 - 0 students - KES 0</div></div></div>
    <div style='display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><b>Recent Activity</b><div>Viewed: dashboard</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><b>Top Fee Defaulters</b><div>No defaulters</div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><b>Recent Payments</b><div>No payments yet</div></div></div>
    </div>"""
    return HTMLResponse(wrap(school_name, body, user_email, role_display, "overview"))

@app.get("/academics", response_class=HTMLResponse)
def academics(request: Request, term: str = "Term 1", year: str = "2026", grade: str = "GRADE 7", tab: str = "performance"):
    if "school_id" not in request.session and request.session.get("role") != "super_admin":
        return RedirectResponse("/")
    is_super = request.session.get("role") == "super_admin" or request.session.get("user_email") == SUPER_ADMIN_EMAIL
    user_email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role_display = "Super Admin" if is_super else "School Admin"
    school_name = request.session.get("school_name", "DaviSchool")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT class FROM students WHERE school_id=?", (request.session.get("school_id",0),))
    classes_from_db = [r["class"] for r in cur.fetchall() if r["class"]]
    cur.execute("SELECT name FROM students WHERE school_id=? LIMIT 3", (request.session.get("school_id",0),))
    student_names = [r["name"] for r in cur.fetchall()]
    con.close()
    if not classes_from_db:
        classes_from_db = ["GRADE 7", "GRADE 8", "GRADE 9"]
    if not student_names:
        student_names = ["FLORENCE"]
    grades_options = ""
    for g in classes_from_db:
        sel = "selected" if g == grade else ""
        grades_options += f"<option value='{g}' {sel}>{g}</option>"
    students_badges = ""
    for n in student_names:
        students_badges += f"<span style='background:#f1f5f9; border:1px solid #e2e8f0; padding:4px 10px; border-radius:20px; font-size:12px; margin-right:6px'>{n.upper()} -></span>"

    t1_sel = "selected" if term == "Term 1" else ""
    t2_sel = "selected" if term == "Term 2" else ""
    t3_sel = "selected" if term == "Term 3" else ""
    y24_sel = "selected" if year == "2024" else ""
    y25_sel = "selected" if year == "2025" else ""
    y26_sel = "selected" if year == "2026" else ""

    perf_active = "border-bottom:2px solid #0f172a; font-weight:600; color:#0f172a" if tab == "performance" else "color:#64748b"
    subj_active = "border-bottom:2px solid #0f172a; font-weight:600; color:#0f172a" if tab == "subject" else "color:#64748b"
    teach_active = "border-bottom:2px solid #0f172a; font-weight:600; color:#0f172a" if tab == "teacher" else "color:#64748b"
    stud_active = "border-bottom:2px solid #0f172a; font-weight:600; color:#0f172a" if tab == "student" else "color:#64748b"

    if tab == "subject":
        cards = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><b>Subject Performance Matrix</b><div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No subject performance data available</div><div>Term: {term} | Year: {year} | Grade: {grade}</div></div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><b>Gender Gap Analysis</b><div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No gender gap data available</div></div></div>"""
    elif tab == "teacher":
        cards = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><b>Top 10 Teachers by Value Added</b><div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No teacher performance data available</div><div>Term: {term} | Year: {year} | Grade: {grade}</div></div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><b>Teacher Value-Added Details</b><div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No teacher value-added data available</div></div></div>"""
    elif tab == "student":
        cards = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><div style='display:flex; justify-content:space-between'><b>Student Trajectories</b><span style='border:1px solid #e2e8f0; padding:6px 12px; border-radius:20px; font-size:12px'>Show At-Risk Only</span></div><div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No student trajectory data available</div></div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><b>Cohort Tracking</b><div>Select students to track their progression:</div><div style='margin-top:10px'>{students_badges}</div><div style='height:200px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>Select students above to view their progression chart</div></div></div>"""
    else:
        cards = f"""<div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><b>Class Performance Over Time</b><div style='height:240px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'><div>No exam data available for the selected filters</div><div>Term: {term} | Year: {year} | Grade: {grade}</div></div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><b>Yearly Progression - {year}</b><div style='height:220px; border-left:1px solid #cbd5e1; border-bottom:1px solid #cbd5e1; display:flex; align-items:center; justify-content:center; color:#94a3b8'>Chart - Fresh System</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'><b>Subject Trends Across Terms</b><div style='height:220px; border-left:1px solid #cbd5e1; border-bottom:1px solid #cbd5e1; display:flex; align-items:center; justify-content:center; color:#94a3b8'>T3 2026 - Fresh - No data</div><div style='text-align:center; font-size:11px; margin-top:10px'>AGRICULTURE, CRE, ENGLISH, MATHEMATICS, etc</div></div>"""

    body = f"""<div class='content'><h1>Academic Analytics</h1><div style='color:#64748b; margin:6px 0 18px'>Performance insights across subjects, teachers, and students</div>
    <div style='display:flex; gap:12px; margin-bottom:20px'>
        <select id='termSel' style='padding:10px; border:1px solid #e2e8f0; border-radius:10px' onchange="updateFilters()"><option {t1_sel}>Term 1</option><option {t2_sel}>Term 2</option><option {t3_sel}>Term 3</option></select>
        <select id='yearSel' style='padding:10px; border:1px solid #e2e8f0; border-radius:10px' onchange="updateFilters()"><option {y24_sel}>2024</option><option {y25_sel}>2025</option><option {y26_sel}>2026</option></select>
        <select id='gradeSel' style='padding:10px; border:1px solid #e2e8f0; border-radius:10px' onchange="updateFilters()">{grades_options}</select>
    </div>
    <div style='display:flex; gap:24px; border-bottom:1px solid #e2e8f0; margin-bottom:20px; font-size:14px'>
        <a href='/academics?term={term}&year={year}&grade={grade}&tab=performance' style='padding:10px 0; text-decoration:none; {perf_active}'>Performance Trends</a>
        <a href='/academics?term={term}&year={year}&grade={grade}&tab=subject' style='padding:10px 0; text-decoration:none; {subj_active}'>Subject Analysis</a>
        <a href='/academics?term={term}&year={year}&grade={grade}&tab=teacher' style='padding:10px 0; text-decoration:none; {teach_active}'>Teacher Performance</a>
        <a href='/academics?term={term}&year={year}&grade={grade}&tab=student' style='padding:10px 0; text-decoration:none; {stud_active}'>Student Tracking</a>
    </div>
    {cards}
    </div>
    <script>
    function updateFilters(){{
        var t=document.getElementById('termSel').value;
        var y=document.getElementById('yearSel').value;
        var g=document.getElementById('gradeSel').value;
        var currentTab='{tab}';
        window.location='/academics?term='+encodeURIComponent(t)+'&year='+encodeURIComponent(y)+'&grade='+encodeURIComponent(g)+'&tab='+currentTab;
    }}
    </script>
    """
    return HTMLResponse(wrap(school_name, body, user_email, role_display, "academics"))

@app.get("/students", response_class=HTMLResponse)
def students_list(request: Request):
    if "school_id" not in request.session and request.session.get("role") != "super_admin":
        return RedirectResponse("/")
    is_super = request.session.get("role") == "super_admin" or request.session.get("user_email") == SUPER_ADMIN_EMAIL
    user_email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role_display = "Super Admin" if is_super else "School Admin"
    school_name = request.session.get("school_name", "DaviSchool")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM students WHERE school_id=?", (request.session.get("school_id",0),))
    rows = cur.fetchall()
    con.close()
    rows_html = ""
    for r in rows:
        rows_html += f"<tr><td>{r['adm']}</td><td>{r['name']}</td><td>{r['class']}</td><td>{r['gender'] or '-'}</td></tr>"
    if not rows_html:
        rows_html = "<tr><td colspan=4 style='text-align:center; padding:20px; color:#94a3b8'>No students yet - Fresh</td></tr>"
    body = f"""<div class='content'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><h3>Students - {school_name}</h3>
    <form method='post' action='/students/add' style='margin-top:12px; display:flex; gap:6px; flex-wrap:wrap'><input name='adm' placeholder='ADM No' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='name' placeholder='Full Name' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='class' placeholder='Class' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'>
    <select name='gender' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><option value='Boy'>Boy</option><option value='Girl'>Girl</option></select>
    <button style='background:#2563eb; color:white; padding:10px 16px; border:none; border-radius:8px; font-weight:600'>+ Add Student</button></form></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px; margin-top:16px'><table style='width:100%; border-collapse:collapse'><tr><th style='text-align:left; padding:10px; color:#64748b; font-size:12px'>ADM</th><th style='text-align:left; padding:10px; color:#64748b; font-size:12px'>Name</th><th style='text-align:left; padding:10px; color:#64748b; font-size:12px'>Class</th><th style='text-align:left; padding:10px; color:#64748b; font-size:12px'>Gender</th></tr>{rows_html}</table></div></div>"""
    return HTMLResponse(wrap(school_name, body, user_email, role_display))

@app.post("/students/add")
def add_student(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class"), gender: str = Form("Boy")):
    sid = request.session.get("school_id", 1)
    con = get_db()
    cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, adm, name, class, gender) VALUES (?,?,?,?,?)", (sid, adm, name, class_, gender))
    con.commit()
    con.close()
    return RedirectResponse("/students", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    if not request.session.get("user_email"):
        return RedirectResponse("/")
    is_super = request.session.get("role") == "super_admin" or request.session.get("user_email") == SUPER_ADMIN_EMAIL
    role_display = "Super Admin" if is_super else "School Admin"
    user_email = request.session.get("user_email")
    body = f"""<div class='content'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; max-width:500px'><h2>Profile</h2><p><b>Name:</b> Davis Ouma</p><p><b>Email:</b> {user_email}</p><p><b>Role:</b> {role_display}</p></div></div>"""
    return HTMLResponse(wrap("DaviSchool", body, user_email, role_display))

@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    if not request.session.get("user_email"):
        return RedirectResponse("/")
    is_super = request.session.get("role") == "super_admin" or request.session.get("user_email") == SUPER_ADMIN_EMAIL
    role_display = "Super Admin" if is_super else "School Admin"
    user_email = request.session.get("user_email")
    body = """<div class='content'><h1>Settings</h1><div style='color:#64748b; margin:6px 0 24px'>School configuration</div>
    <div style='display:grid; grid-template-columns:repeat(3,1fr); gap:18px'>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px'><b>User Management</b><div>Create, edit, manage users</div></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px'><b>Roles & Permissions</b><div>Manage roles</div></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px'><b>School Profile</b><div>Update info</div></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px'><b>Classes & Streams</b><div>Manage classes</div></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px'><b>Database Backup</b><div>Create backups</div></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px'><b>Audit Trail</b><div>Track activities</div></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px'><b>Integrations</b><div>Bulk SMS and M-Pesa</div></div>
    </div></div>"""
    return HTMLResponse(wrap("DaviSchool", body, user_email, role_display))

@app.get("/super-admin", response_class=HTMLResponse)
def super_admin(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools")
    schools = cur.fetchall()
    con.close()
    schools_html = ""
    for s in schools:
        status = "Approved" if s["approved"] else "Pending"
        schools_html += f"<tr><td>{s['name']}</td><td>{s['email']}</td><td>{status}</td><td><a href='/super-admin/approve/{s['id']}' style='background:#16a34a; color:white; padding:6px 12px; border-radius:6px; text-decoration:none'>Approve</a></td></tr>"
    if not schools_html:
        schools_html = "<tr><td colspan=4>No schools</td></tr>"
    body = f"""<div class='content'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><h3>Super Admin - {SUPER_ADMIN_EMAIL}</h3><a href='/super-admin/reset-all-mabale-data' style='background:#dc2626; color:white; padding:10px 16px; border-radius:8px; text-decoration:none'>RESET ALL DATA</a> <a href='/logout' style='background:#2563eb; color:white; padding:10px 16px; border-radius:8px; text-decoration:none; margin-left:8px'>Logout</a></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px; margin-top:16px'><table style='width:100%'><tr><th>School</th><th>Email</th><th>Status</th><th>Action</th></tr>{schools_html}</table></div></div>"""
    return HTMLResponse(wrap("Super Admin - DaviSchool", body, SUPER_ADMIN_EMAIL, "Super Admin"))

@app.get("/super-admin/approve/{school_id}")
def approve(request: Request, school_id: int):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE schools SET approved=1 WHERE id=?", (school_id,))
    con.commit()
    con.close()
    return RedirectResponse("/super-admin", status_code=303)

@app.get("/super-admin/reset-all-mabale-data")
def reset_all(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL:
        return HTMLResponse("Denied", status_code=403)
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM students")
    cur.execute("DELETE FROM teachers")
    cur.execute("DELETE FROM school_classes")
    cur.execute("DELETE FROM schools WHERE email != ?", (SUPER_ADMIN_EMAIL,))
    cur.execute("DELETE FROM users WHERE email != ?", (SUPER_ADMIN_EMAIL,))
    con.commit()
    con.close()
    return HTMLResponse(wrap("Wiped", "<div class='content'><h1>Wiped! Fresh system.</h1><a href='/super-admin'>Go to Super Admin</a></div>", SUPER_ADMIN_EMAIL, "Super Admin"))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)

@app.get("/teachers")
def teachers_page(request: Request):
    return RedirectResponse("/dashboard")

@app.get("/classes")
def classes_page(request: Request):
    return RedirectResponse("/dashboard")
