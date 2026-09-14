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
    con=get_db(); cur=con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, approved INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, school_id INTEGER, role TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm TEXT, name TEXT, class TEXT, gender TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, subject TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS school_classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, term TEXT, year TEXT, grade TEXT, subject TEXT, class_mean REAL, highest REAL, lowest REAL)")
    try: cur.execute("ALTER TABLE students ADD COLUMN gender TEXT")
    except: pass
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role) VALUES (?,?,?)", (SUPER_ADMIN_EMAIL, "DaviSchool@2026!", "super_admin"))
    con.commit(); con.close()
init_db()

def login_page(error_msg=""):
    return f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial; margin:0; background:white; display:flex; justify-content:center; align-items:center; min-height:100vh}}
    .login-box{{width:100%; max-width:440px; padding:40px 20px}} h1{{font-size:34px; font-weight:800; margin:0 0 6px; color:#0f172a}} .subtitle{{color:#475569; margin-bottom:32px}}
    label{{font-weight:600; color:#334155; font-size:14px; display:block; margin:20px 0 8px}} input,select{{width:100%; padding:14px 16px; border:1px solid #e2e8f0; border-radius:10px; font-size:15px; box-sizing:border-box}}
    .btn-sign{{width:100%; background:#2563eb; color:white; border:none; padding:14px; border-radius:10px; font-size:16px; font-weight:600; cursor:pointer}}
    .error{{background:#fef2f2; color:#b91c1c; padding:10px; border-radius:8px; margin-bottom:16px; border:1px solid #fecaca}} .bottom-link{{text-align:center; margin-top:20px; color:#64748b; font-size:14px}} .bottom-link a{{color:#2563eb; text-decoration:none; font-weight:600}}
    </style></head><body><div class='login-box'><h1>Welcome Back</h1><div class='subtitle'>Sign in to your DaviSchool account</div>
    {f"<div class='error'>{error_msg}</div>" if error_msg else ""}
    <form method='post' action='/login'><label>Username or Email</label><input type='text' name='email' placeholder='Enter your username or email' required>
    <label>Password</label><input type='password' name='password' placeholder='Enter your password' required>
    <div style='display:flex; justify-content:space-between; margin:16px 0 24px; font-size:14px'><label><input type='checkbox'> Remember me</label><a href='#' style='color:#0f7a5a; font-weight:600; text-decoration:none'>Forgot Password?</a></div>
    <button class='btn-sign' type='submit'>Sign In</button></form><div class='bottom-link'>Don't have account? <a href='/register'>Register your School</a></div></div></body></html>"""

def wrap(school_name, body_html, user_email, user_role_display, active_tab="overview"):
    return f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
    *{{box-sizing:border-box}} body{{margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial; background:#fcfcfc; display:flex}}
    .sidebar{{width:270px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}}
    .logo{{padding:18px 20px; border-bottom:1px solid #f1f5f9; display:flex; align-items:center; gap:10px}} .logo-icon{{width:38px; height:38px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800}}
    .logo b{{color:#0f5b9e; font-size:16px}} .logo small{{display:block; color:#64748b; font-size:9px; letter-spacing:1px}}
    .nav-section{{padding:12px 14px}} .nav-label{{font-size:12px; color:#94a3b8; font-weight:600; margin:10px 8px 8px; text-transform:uppercase}}
    .nav-item{{display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:8px; color:#334155; text-decoration:none; font-size:14px; margin-bottom:2px}}
    .nav-item.active{{background:#0f172a; color:white}} .sub{{margin-left:28px; border-left:1px dashed #e2e8f0; padding-left:12px}}
    .main{{margin-left:270px; flex:1; min-height:100vh}} .topbar{{background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:10}}
    .content{{padding:24px}} h1{{font-size:26px; margin:0}} .welcome{{color:#64748b; margin:8px 0 20px}}
    .grid4{{display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:16px}} .card{{background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px; display:flex; justify-content:space-between}}
    .card h4{{margin:0; color:#64748b; font-size:13px; font-weight:500}} .card h2{{margin:6px 0 4px; font-size:26px; font-weight:700}} .card small{{color:#94a3b8; font-size:12px}}
    .icon-box{{width:44px; height:44px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:20px}}
    .profile-wrap{{position:relative}} .profile-btn{{display:flex; align-items:center; gap:8px; cursor:pointer; border:none; background:transparent}} 
    .avatar{{width:36px; height:36px; background:#f1f5f9; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700}}
    .dropdown{{position:absolute; top:45px; right:0; width:250px; background:white; border:1px solid #e2e8f0; border-radius:12px; box-shadow:0 10px 25px rgba(0,0,0,0.1); display:none; z-index:100; overflow:hidden}}
    .dropdown.show{{display:block}} .drop-header{{padding:14px 16px; border-bottom:1px solid #f1f5f9}} .drop-header b{{display:block; font-size:14px}} .drop-header small{{color:#64748b; font-size:12px}}
    .drop-item{{display:flex; align-items:center; gap:12px; padding:12px 16px; text-decoration:none; color:#334155; font-size:14px}} .drop-item:hover{{background:#f8fafc}} .drop-item.logout{{color:#dc2626; border-top:1px solid #f1f5f9}}
    @media(max-width:900px){{.sidebar{{display:none}} .main{{margin-left:0}} .grid4{{grid-template-columns:1fr 1fr}}}}
    </style></head><body>
    <div class='sidebar'><div class='logo'><div class='logo-icon'>D</div><div><b>DaviSchool</b><small>SCHOOL MANAGEMENT SYSTEM</small></div></div>
    <div class='nav-section'><div class='nav-label'>Main Navigation</div><a class='nav-item active'>📊 Dashboard</a>
    <div class='sub'>
        <a class='nav-item' href='/dashboard' style='{"background:#0f172a; color:white" if active_tab=="overview" else "background:#f1f5f9; border:1px solid #e2e8f0; font-weight:700; color:#0f172a"}'>🏠 System Overview</a>
        <a class='nav-item' href='/academics' style='{"background:#0f172a; color:white" if active_tab=="academics" else ""}'>📊 Academic Analyt...</a>
        <a class='nav-item'>📈 Financial Analytics</a><a class='nav-item'>📅 Attendance Analy...</a><a class='nav-item'>💡 Automated Insig...</a><a class='nav-item'>🤝 Benchmarking</a>
    </div>
    <a class='nav-item' href='/students'>🎓 Students Manager</a><a class='nav-item' href='/teachers'>👥 Staff Manager</a><a class='nav-item'>📖 Academic Manager</a><a class='nav-item' href='/classes'>🗓️ Timetable</a><a class='nav-item'>🎥 Online Classes</a></div>
    <div style='padding:14px; border-top:1px solid #f1f5f9; margin-top:20px; display:flex; gap:10px; align-items:center'><div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700'>DO</div><div><div style='font-size:13px; font-weight:600'>Davis Ouma</div><div style='font-size:11px; color:#64748b'>{user_email}</div></div></div></div>
    <div class='main'><div class='topbar'><div><b style='font-size:16px'>{school_name.upper()}</b> <small style='color:#64748b'>(Code: DS-2026)</small></div>
    <div style='display:flex; gap:16px; align-items:center'><span>☀️</span><span>🔔</span><span>❓</span>
        <div class='profile-wrap'>
            <button class='profile-btn' onclick='document.getElementById("profileDrop").classList.toggle("show")'>
                <div class='avatar'>DO</div>
                <div style='text-align:left; line-height:1.1'><div style='font-size:14px; font-weight:600'>Davis Ouma</div><div style='font-size:12px; color:#64748b'>{user_role_display}</div></div>
                <span style='font-size:12px; margin-left:4px'>⌄</span>
            </button>
            <div id='profileDrop' class='dropdown'>
                <div class='drop-header'><b>Davis Ouma</b><small>{user_email}</small></div>
                <a class='drop-item' href='/profile'><span>👤</span> Profile</a>
                <a class='drop-item' href='/settings'><span>⚙️</span> Settings</a>
                <a class='drop-item logout' href='/logout'><span>↪</span> Log out</a>
            </div>
        </div>
    </div></div>
    {body_html}</div>
    <script>window.onclick=function(e){{if(!e.target.closest('.profile-wrap')){{document.getElementById('profileDrop').classList.remove('show')}}}}</script>
    </body></html>"""

@app.get("/", response_class=HTMLResponse)
def home(): return HTMLResponse(login_page())
@app.get("/register", response_class=HTMLResponse)
def register_page():
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0}} .box{{background:white; padding:30px; border-radius:16px; box-shadow:0 4px 20px rgba(0,0,0,0.08); width:100%; max-width:400px}} input{{width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:8px; box-sizing:border-box}} .btn{{width:100%; background:#2563eb; color:white; padding:12px; border:none; border-radius:8px; font-weight:600; cursor:pointer; margin-top:10px}}</style></head><body><div class='box'><h2 style='text-align:center'>Register School - DaviSchool</h2><form method='post' action='/register'><input name='school_name' placeholder='School Name' required><input name='email' placeholder='Admin Email' required><input name='password' type='password' placeholder='Password' required><button class='btn'>Register</button></form><p style='text-align:center; margin-top:15px'><a href='/'>Back to Login</a></p></div></body></html>")

@app.post("/register")
def register(school_name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO schools (name, email, approved) VALUES (?,?,0)", (school_name, email)); sid=cur.lastrowid; cur.execute("INSERT INTO users (email, password, school_id, role) VALUES (?,?,?,?)", (email, password, sid, "admin")); con.commit(); con.close()
    return HTMLResponse(login_page(f"School {school_name} registered! Wait for approval."))

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password)); user=cur.fetchone()
    if not user: con.close(); return HTMLResponse(login_page("Invalid username or password."))
    if user["role"]=="super_admin": request.session["user_email"]=email; request.session["role"]="super_admin"; con.close(); return RedirectResponse("/super-admin", status_code=303)
    cur.execute("SELECT * FROM schools WHERE id=?", (user["school_id"],)); school=cur.fetchone(); con.close()
    if school and school["approved"]==0: return HTMLResponse(login_page(f"School {school['name']} not yet approved."))
    request.session["user_email"]=email; request.session["school_id"]=user["school_id"]; request.session["school_name"]=school["name"] if school else ""; request.session["role"]="admin"
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "school_id" not in request.session and request.session.get("role")!="super_admin": return RedirectResponse("/")
    is_super = request.session.get("role")=="super_admin" or request.session.get("user_email")==SUPER_ADMIN_EMAIL
    user_email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role_display = "Super Admin" if is_super else "School Admin"
    school_name = request.session.get("school_name", "DaviSchool")
    con=get_db(); cur=con.cursor(); sid = request.session.get("school_id", 0)
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=?", (sid,)); sc=cur.fetchone()["c"] if sid else 0
    cur.execute("SELECT COUNT(*) as c FROM teachers WHERE school_id=?", (sid,)); tc=cur.fetchone()["c"] if sid else 0
    cur.execute("SELECT COUNT(*) as c FROM school_classes WHERE school_id=?", (sid,)); cc=cur.fetchone()["c"] if sid else 0
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND gender='Boy'", (sid,)); boys=cur.fetchone()["c"] if sid else 0
    cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=? AND gender='Girl'", (sid,)); girls=cur.fetchone()["c"] if sid else 0
    con.close()
    total = boys + girls
    ratio = f"{(girls/boys):.2f}:1" if boys>0 and girls>0 else "0:1"
    max_val = max(boys, girls, 1)
    boy_h = int((boys/max_val)*140) if boys>0 else 8
    girl_h = int((girls/max_val)*140) if girls>0 else 8
    body=f"""<div class='content'>
        <div style='display:flex; justify-content:space-between; align-items:center'><div><h1>School Overview</h1><div class='welcome'>Welcome back, Davis! Here's what's happening at {school_name}.</div></div><button style='border:1px solid #e2e8f0; background:white; padding:8px 14px; border-radius:10px; font-size:13px; font-weight:600'>✨ Getting Started</button></div>
        <div class='grid4'><div class='card'><div><h4>Total Students</h4><h2>{sc}</h2><small>{cc} classes</small></div><div class='icon-box' style='background:#e0f2fe'>🎓</div></div><div class='card'><div><h4>Total Staff</h4><h2>{tc}</h2><small>{tc} system users</small></div><div class='icon-box' style='background:#f3e8ff'>👥</div></div><div class='card'><div><h4>Fee Collection</h4><h2>0%</h2><small>KES 0 of 0</small></div><div class='icon-box' style='background:#dcfce7'>💰</div></div><div class='card'><div><h4>Attendance Today</h4><h2>--</h2><small>Not marked yet</small></div><div class='icon-box' style='background:#fef9c3'>📅</div></div></div>
        <div class='grid4'><div class='card'><div style='display:flex; gap:12px'><div class='icon-box' style='background:#e0f2fe; width:40px; height:40px'>📖</div><div><h4 style='color:#0f172a; font-weight:600'>Library</h4><small>0 books<br>0 issued, 0 overdue</small></div></div></div><div class='card'><div style='display:flex; gap:12px'><div class='icon-box' style='background:#fef9c3; width:40px; height:40px'>🚚</div><div><h4 style='color:#0f172a; font-weight:600'>Transport</h4><small>0 vehicles<br>0 routes</small></div></div></div><div class='card'><div style='display:flex; gap:12px'><div class='icon-box' style='background:#f3e8ff; width:40px; height:40px'>📦</div><div><h4 style='color:#0f172a; font-weight:600'>Inventory</h4><small>0 items<br>0 low stock, 0 out</small></div></div></div><div class='card'><div style='display:flex; gap:12px'><div class='icon-box' style='background:#dcfce7; width:40px; height:40px'>💵</div><div><h4 style='color:#0f172a; font-weight:600'>Payroll</h4><small>0 runs<br>No runs yet</small></div></div></div></div>
        <div style='margin-top:28px; background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; max-width:700px; margin-left:auto; margin-right:auto'>
            <div style='display:flex; align-items:center; gap:8px; font-weight:700; font-size:16px'><span style='color:#7c3aed'>👥</span> Students by Gender</div>
            <div style='color:#64748b; font-size:13px; margin:4px 0 16px'>Boys vs Girls enrollment per form</div>
            <div style='display:flex; justify-content:center; align-items:flex-end; gap:60px; height:200px; padding:10px; border-bottom:1px solid #f1f5f9; position:relative'>
                <div style='display:flex; flex-direction:column; align-items:center; gap:6px'><div style='width:60px; background:#3b82f6; border-radius:6px 6px 0 0; height:{boy_h}px; min-height:8px'></div><small style='color:#64748b'>GRADE 7</small></div>
                <div style='display:flex; flex-direction:column; align-items:center; gap:6px'><div style='width:60px; background:#ec4899; border-radius:6px 6px 0 0; height:{girl_h}px; min-height:8px'></div><small style='color:#64748b'>&nbsp;</small></div>
                <div style='position:absolute; left:20px; height:180px; display:flex; flex-direction:column; justify-content:space-between; font-size:12px; color:#94a3b8; padding-bottom:20px'><span>36</span><span>27</span><span>18</span><span>9</span><span>0</span></div>
            </div>
            <div style='display:flex; justify-content:center; gap:16px; margin-top:10px; font-size:12px'><span><span style='display:inline-block; width:12px; height:8px; background:#3b82f6; margin-right:4px'></span>Boys</span><span><span style='display:inline-block; width:12px; height:8px; background:#ec4899; margin-right:4px'></span>Girls</span></div>
            <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-top:20px'>
                <div style='background:#eff6ff; border-radius:10px; padding:10px; text-align:center'><div style='font-size:11px; color:#64748b'>Total Boys</div><div style='font-weight:700; color:#2563eb; font-size:18px'>{boys}</div></div>
                <div style='background:#fdf2f8; border-radius:10px; padding:10px; text-align:center'><div style='font-size:11px; color:#64748b'>Total Girls</div><div style='font-weight:700; color:#db2777; font-size:18px'>{girls}</div></div>
                <div style='background:#f8fafc; border-radius:10px; padding:10px; text-align:center'><div style='font-size:11px; color:#64748b'>Total Students</div><div style='font-weight:700; color:#0f172a; font-size:18px'>{total}</div></div>
                <div style='background:#f8fafc; border-radius:10px; padding:10px; text-align:center'><div style='font-size:11px; color:#64748b'>Girl:Boy Ratio</div><div style='font-weight:700; color:#0f172a; font-size:16px'>{ratio}</div></div>
            </div>
        </div>
        <div style='margin-top:24px; background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'>
            <div style='display:flex; align-items:center; gap:8px; font-weight:700; font-size:15px'>📊 Cumulative Balances by Class</div>
            <div style='color:#64748b; font-size:13px; margin:4px 0 18px'>Current outstanding fee balances — Total: KES 0</div>
            <div style='display:flex; flex-direction:column; gap:10px'>
                <div style='display:flex; align-items:center; justify-content:space-between; background:#f8fafc; border-radius:8px; padding:10px 14px'><div style='display:flex; gap:20px; align-items:center'><b style='width:70px'>GRADE 7</b><span style='background:white; border:1px solid #e2e8f0; padding:4px 10px; border-radius:20px; font-size:12px; color:#64748b'>{sc} students</span></div><b style='color:#dc2626; font-size:13px'>KES 0</b></div>
                <div style='display:flex; align-items:center; justify-content:space-between; background:#f8fafc; border-radius:8px; padding:10px 14px'><div style='display:flex; gap:20px; align-items:center'><b style='width:70px'>GRADE 8</b><span style='background:white; border:1px solid #e2e8f0; padding:4px 10px; border-radius:20px; font-size:12px; color:#64748b'>0 students</span></div><b style='color:#dc2626; font-size:13px'>KES 0</b></div>
                <div style='display:flex; align-items:center; justify-content:space-between; background:#f8fafc; border-radius:8px; padding:10px 14px'><div style='display:flex; gap:20px; align-items:center'><b style='width:70px'>GRADE 9</b><span style='background:white; border:1px solid #e2e8f0; padding:4px 10px; border-radius:20px; font-size:12px; color:#64748b'>0 students</span></div><b style='color:#dc2626; font-size:13px'>KES 0</b></div>
            </div>
        </div>
        <div style='display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:24px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><div style='display:flex; align-items:center; gap:8px; font-weight:700'>🕒 Recent Activity</div><div style='color:#64748b; font-size:12px; margin:4px 0 14px'>Latest system activity</div><div style='height:150px; display:flex; flex-direction:column; gap:10px; font-size:13px'><div><div style='display:flex; justify-content:space-between'><span>Viewed: dashboard > overvi...</span><span style='background:#f1f5f9; padding:2px 8px; border-radius:10px; font-size:10px'>data_view</span></div><small style='color:#94a3b8'>Davis Ouma -- now</small></div></div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><div style='display:flex; align-items:center; gap:8px; font-weight:700'>🔴 Top Fee Defaulters</div><div style='color:#64748b; font-size:12px; margin:4px 0 14px'>Highest outstanding balances</div><div style='height:150px; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:14px'>No defaulters</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><div style='display:flex; align-items:center; gap:8px; font-weight:700'>💳 Recent Payments</div><div style='color:#64748b; font-size:12px; margin:4px 0 14px'>Latest fee payments received</div><div style='height:150px; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:14px'>No payments yet</div></div>
        </div>
    </div>
    """
    return HTMLResponse(wrap(school_name, body, user_email, role_display, "overview"))

@app.get("/academics", response_class=HTMLResponse)
def academics(request: Request, term: str = "Term 1", year: str = "2026", grade: str = "GRADE 7"):
    if "school_id" not in request.session and request.session.get("role")!="super_admin": return RedirectResponse("/")
    is_super = request.session.get("role")=="super_admin" or request.session.get("user_email")==SUPER_ADMIN_EMAIL
    user_email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role_display = "Super Admin" if is_super else "School Admin"
    school_name = request.session.get("school_name", "DaviSchool")
    if is_super: school_name = request.session.get("school_name", "DaviSchool")

    # Get actual grades from students table for dropdown
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT DISTINCT class FROM students WHERE school_id=?", (request.session.get("school_id",0),))
    classes_from_db = [r["class"] for r in cur.fetchall() if r["class"]]
    con.close()
    if not classes_from_db: classes_from_db = ["GRADE 7", "GRADE 8", "GRADE 9"]

    grades_options = "".join([f"<option value='{g}' {'selected' if g==grade else ''}>{g}</option>" for g in classes_from_db])

    body=f"""
    <div class='content'>
        <h1 style='font-size:26px; font-weight:700'>Academic Analytics</h1>
        <div style='color:#64748b; font-size:14px; margin:6px 0 18px'>Performance insights across subjects, teachers, and students</div>

        <div style='display:flex; gap:12px; margin-bottom:20px'>
            <select id='termSel' style='padding:10px 14px; border:1px solid #e2e8f0; border-radius:10px; background:white; min-width:120px' onchange="updateFilters()">
                <option {'selected' if term=='Term 1' else ''}>Term 1</option><option {'selected' if term=='Term 2' else ''}>Term 2</option><option {'selected' if term=='Term 3' else ''}>Term 3</option>
            </select>
            <select id='yearSel' style='padding:10px 14px; border:1px solid #e2e8f0; border-radius:10px; background:white; min-width:120px' onchange="updateFilters()">
                <option {'selected' if year=='2024' else ''}>2024</option><option {'selected' if year=='2025' else ''}>2025</option><option {'selected' if year=='2026' else ''}>2026</option>
            </select>
            <select id='gradeSel' style='padding:10px 14px; border:1px solid #e2e8f0; border-radius:10px; background:white; min-width:140px' onchange="updateFilters()">
                {grades_options}
            </select>
        </div>

        <div style='display:flex; gap:24px; border-bottom:1px solid #e2e8f0; margin-bottom:20px; font-size:14px'>
            <div style='padding:10px 0; border-bottom:2px solid #0f172a; font-weight:600'>📈 Performance Trends</div>
            <a href='#' style='padding:10px 0; color:#64748b; text-decoration:none'>📖 Subject Analysis</a>
            <a href='#' style='padding:10px 0; color:#64748b; text-decoration:none'>🎓 Teacher Performance</a>
            <a href='#' style='padding:10px 0; color:#64748b; text-decoration:none'>👥 Student Tracking</a>
        </div>

        <!-- SCROLL PART 1 - Class Performance Over Time -->
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:20px; display:flex; gap:8px; align-items:center'>📊 Class Performance Over Time</div>
            <div style='height:240px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'>
                <div style='font-size:36px; margin-bottom:12px'>📊</div>
                <div style='font-size:14px'>No exam data available for the selected filters</div>
                <div style='font-size:12px; margin-top:4px'>Term: {term} | Year: {year} | Grade: {grade}</div>
            </div>
        </div>

        <!-- SCROLL PART 2 - Yearly Progression - YOUR 2ND PICTURE -->
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:16px; display:flex; gap:8px; align-items:center'>📈 Yearly Progression</div>
            <div style='position:relative; height:280px; padding-left:40px'>
                <div style='position:absolute; left:0; top:0; height:220px; display:flex; flex-direction:column; justify-content:space-between; font-size:12px; color:#94a3b8'>
                    <span>100</span><span>75</span><span>50</span><span>25</span><span>0</span>
                </div>
                <div style='height:220px; border-left:1px solid #cbd5e1; border-bottom:1px solid #cbd5e1; position:relative; display:flex; align-items:flex-end; justify-content:center'>
                    <div style='position:absolute; bottom:0; left:50%; transform:translateX(-50%); display:flex; flex-direction:column; align-items:center; gap:30px; height:220px; justify-content:flex-end; padding-bottom:20px'>
                        <div style='width:8px; height:8px; background:#22c55e; border-radius:50%'></div>
                        <div style='width:8px; height:8px; background:#3b82f6; border-radius:50%; margin-top:20px'></div>
                        <div style='width:8px; height:8px; background:#ef4444; border-radius:50%; margin-top:40px'></div>
                    </div>
                </div>
                <div style='text-align:center; font-size:12px; color:#64748b; margin-top:8px'>{year}</div>
                <div style='display:flex; justify-content:center; gap:20px; margin-top:12px; font-size:12px'>
                    <span style='display:flex; align-items:center; gap:6px'><span style='width:8px; height:8px; background:#3b82f6; border-radius:50%; display:inline-block'></span>Class Mean</span>
                    <span style='display:flex; align-items:center; gap:6px'><span style='width:8px; height:8px; background:#22c55e; border-radius:50%; display:inline-block'></span>Highest</span>
                    <span style='display:flex; align-items:center; gap:6px'><span style='width:8px; height:8px; background:#ef4444; border-radius:50%; display:inline-block'></span>Lowest</span>
                </div>
            </div>
        </div>

        <!-- SCROLL PART 3 - Subject Trends Across Terms - YOUR 3RD PICTURE -->
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:16px; display:flex; gap:8px; align-items:center'>📖 Subject Trends Across Terms</div>
            <div style='position:relative; height:340px; padding-left:40px'>
                <div style='position:absolute; left:0; top:0; height:220px; display:flex; flex-direction:column; justify-content:space-between; font-size:12px; color:#94a3b8'>
                    <span>100</span><span>75</span><span>50</span><span>25</span><span>0</span>
                </div>
                <div style='height:220px; border-left:1px solid #cbd5e1; border-bottom:1px solid #cbd5e1; position:relative;'>
                    <div style='position:absolute; bottom:20px; left:50%; transform:translateX(-50%); display:flex; flex-direction:column; gap:8px; align-items:center'>
                        <div style='width:6px; height:6px; background:#ef4444; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#22c55e; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#3b82f6; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#f59e0b; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#ef4444; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#8b5cf6; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#06b6d4; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#22c55e; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#3b82f6; border-radius:50%'></div>
                        <div style='width:6px; height:6px; background:#3b82f6; border-radius:50%'></div>
                    </div>
                </div>
                <div style='text-align:center; font-size:11px; color:#64748b; margin-top:8px'>T3 2026</div>
                <div style='display:flex; flex-wrap:wrap; gap:12px; justify-content:center; margin-top:14px; font-size:11px; line-height:1.6'>
                    <span style='color:#0ea5e9'>◉ AGRICULTURE</span><span style='color:#22c55e'>◉ CHRISTIAN_RELIGIOUS_EDUCATION</span><span style='color:#ef4444'>◉ CREATIVE_ARTS</span><span style='color:#f59e0b'>◉ ENGLISH</span>
                    <span style='color:#06b6d4'>◉ INTERGRATED_SCIENCE</span><span style='color:#8b5cf6'>◉ KISWAHILI</span><span style='color:#ec4899'>◉ MATHEMATICS</span><span style='color:#84cc16'>◉ PRE-TECHNICAL_STUDIES</span><span style='color:#f97316'>◉ SOCIAL_STUDIES</span>
                </div>
                <div style='display:flex; flex-wrap:wrap; gap:10px; justify-content:center; margin-top:10px; font-size:10px; color:#64748b'>
                    <span>AGRICULTURE: 0.0 →</span><span>CHRISTIAN_RELIGIOUS_EDUCATION: 0.0 →</span><span>CREATIVE ARTS: 0.0 →</span><span>ENGLISH: 0.0 →</span><span>INTERGRATED_SCIENCE: 0.0 →</span>
                    <span>KISWAHILI: 0.0 →</span><span>MATHEMATICS: 0.0 →</span><span>PRE-TECHNICAL_STUDIES: 0.0 →</span><span>SOCIAL_STUDIES: 0.0 →</span>
                </div>
            </div>
        </div>
    </div>
    <script>
    function updateFilters(){{
        var t=document.getElementById('termSel').value;
        var y=document.getElementById('yearSel').value;
        var g=document.getElementById('gradeSel').value;
        window.location='/academics?term='+encodeURIComponent(t)+'&year='+encodeURIComponent(y)+'&grade='+encodeURIComponent(g);
    }}
    </script>
    """
    return HTMLResponse(wrap(school_name, body, user_email, role_display, "academics"))

@app.get("/students", response_class=HTMLResponse)
def students_list(request: Request):
    if "school_id" not in request.session and request.session.get("role")!="super_admin": return RedirectResponse("/")
    is_super = request.session.get("role")=="super_admin" or request.session.get("user_email")==SUPER_ADMIN_EMAIL
    user_email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role_display = "Super Admin" if is_super else "School Admin"
    school_name = request.session.get("school_name", "DaviSchool")
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM students WHERE school_id=?", (request.session.get("school_id",0),)); rows=cur.fetchall(); con.close()
    rows_html="".join([f"<tr><td>{r['adm']}</td><td>{r['name']}</td><td>{r['class']}</td><td>{r['gender'] or '-'}</td></tr>" for r in rows]) or "<tr><td colspan=4 style='text-align:center; padding:20px; color:#94a3b8'>No students yet - Fresh</td></tr>"
    body=f"""<div class='content'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><h3>Students - {school_name}</h3>
    <form method='post' action='/students/add' style='margin-top:12px; display:flex; gap:6px; flex-wrap:wrap'><input name='adm' placeholder='ADM No' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='name' placeholder='Full Name' required style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='class' placeholder='Class' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'>
    <select name='gender' style='padding:10px; border:1px solid #e2e8f0; border-radius:8px'><option value='Boy'>Boy</option><option value='Girl'>Girl</option></select>
    <button style='background:#2563eb; color:white; padding:10px 16px; border:none; border-radius:8px; font-weight:600'>+ Add Student</button></form></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px; margin-top:16px'><table style='width:100%; border-collapse:collapse'><tr><th style='text-align:left; padding:10px; color:#64748b; font-size:12px'>ADM</th><th style='text-align:left; padding:10px; color:#64748b; font-size:12px'>Name</th><th style='text-align:left; padding:10px; color:#64748b; font-size:12px'>Class</th><th style='text-align:left; padding:10px; color:#64748b; font-size:12px'>Gender</th></tr>{rows_html}</table></div></div>"""
    return HTMLResponse(wrap(school_name, body, user_email, role_display))

@app.post("/students/add")
def add_student(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class"), gender: str = Form("Boy")):
    if "school_id" not in request.session and request.session.get("role")!="super_admin": return RedirectResponse("/")
    sid = request.session.get("school_id", 1)
    con=get_db(); cur=con.cursor(); cur.execute("INSERT INTO students (school_id, adm, name, class, gender) VALUES (?,?,?,?,?)", (sid, adm, name, class_, gender)); con.commit(); con.close()
    return RedirectResponse("/students", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    if not request.session.get("user_email"): return RedirectResponse("/")
    is_super = request.session.get("role")=="super_admin" or request.session.get("user_email")==SUPER_ADMIN_EMAIL
    role_display = "Super Admin" if is_super else "School Admin"
    user_email = request.session.get("user_email")
    body=f"""<div class='content'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; max-width:500px'>
    <h2>Profile</h2><div style='margin-top:20px'><p><b>Name:</b> Davis Ouma</p><p><b>Email:</b> {user_email}</p><p><b>Role:</b> {role_display}</p><p><b>System:</b> DaviSchool Management System</p></div>
    <div style='margin-top:20px'><a href='/dashboard' style='background:#2563eb; color:white; padding:10px 16px; border-radius:8px; text-decoration:none'>Back to Dashboard</a></div>
    </div></div>"""
    return HTMLResponse(wrap("DaviSchool", body, user_email, role_display))

@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    if not request.session.get("user_email"): return RedirectResponse("/")
    is_super = request.session.get("role")=="super_admin" or request.session.get("user_email")==SUPER_ADMIN_EMAIL
    role_display = "Super Admin" if is_super else "School Admin"
    user_email = request.session.get("user_email")
    body=f"""
    <div class='content'>
        <h1 style='font-size:28px; font-weight:700; margin:0'>Settings</h1>
        <div style='color:#64748b; font-size:15px; margin:6px 0 24px'>School configuration and system settings</div>
        <div style='display:grid; grid-template-columns:repeat(3,1fr); gap:18px'>
            <a href='/settings/users' style='text-decoration:none; color:inherit'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px; display:flex; flex-direction:column; justify-content:center; cursor:pointer'><div style='font-size:20px; color:#64748b; margin-bottom:12px'>👥</div><div style='font-weight:700; font-size:16px; margin-bottom:6px'>User Management</div><div style='color:#64748b; font-size:13px; line-height:1.4'>Create, edit, and manage user accounts</div></div></a>
            <a href='/settings/roles' style='text-decoration:none; color:inherit'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px; display:flex; flex-direction:column; justify-content:center; cursor:pointer'><div style='font-size:20px; color:#64748b; margin-bottom:12px'>🛡️</div><div style='font-weight:700; font-size:16px; margin-bottom:6px'>Roles & Permissions</div><div style='color:#64748b; font-size:13px; line-height:1.4'>Manage user roles and access control</div></div></a>
            <a href='/settings/school-profile' style='text-decoration:none; color:inherit'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px; display:flex; flex-direction:column; justify-content:center; cursor:pointer'><div style='font-size:20px; color:#64748b; margin-bottom:12px'>🏫</div><div style='font-weight:700; font-size:16px; margin-bottom:6px'>School Profile</div><div style='color:#64748b; font-size:13px; line-height:1.4'>Update school information and branding</div></div></a>
            <a href='/settings/classes' style='text-decoration:none; color:inherit'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px; display:flex; flex-direction:column; justify-content:center; cursor:pointer'><div style='font-size:20px; color:#64748b; margin-bottom:12px'>🎓</div><div style='font-weight:700; font-size:16px; margin-bottom:6px'>Classes & Streams</div><div style='color:#64748b; font-size:13px; line-height:1.4'>Manage class levels, streams, and teachers</div></div></a>
            <a href='/settings/backup' style='text-decoration:none; color:inherit'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px; display:flex; flex-direction:column; justify-content:center; cursor:pointer'><div style='font-size:20px; color:#64748b; margin-bottom:12px'>💾</div><div style='font-weight:700; font-size:16px; margin-bottom:6px'>Database Backup</div><div style='color:#64748b; font-size:13px; line-height:1.4'>Create and manage database backups</div></div></a>
            <a href='/settings/audit' style='text-decoration:none; color:inherit'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px; display:flex; flex-direction:column; justify-content:center; cursor:pointer'><div style='font-size:20px; color:#64748b; margin-bottom:12px'>📄</div><div style='font-weight:700; font-size:16px; margin-bottom:6px'>Audit Trail</div><div style='color:#64748b; font-size:13px; line-height:1.4'>Track system activities and user actions</div></div></a>
            <a href='/settings/integrations' style='text-decoration:none; color:inherit'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:24px; height:180px; display:flex; flex-direction:column; justify-content:center; cursor:pointer'><div style='font-size:20px; color:#64748b; margin-bottom:12px'>🔌</div><div style='font-weight:700; font-size:16px; margin-bottom:6px'>Integrations</div><div style='color:#64748b; font-size:13px; line-height:1.4'>Bulk SMS gateway and M-Pesa payments</div></div></a>
        </div>
    </div>
    """
    return HTMLResponse(wrap("DaviSchool", body, user_email, role_display))

@app.get("/super-admin", response_class=HTMLResponse)
def super_admin(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL: return HTMLResponse("Denied", status_code=403)
    con=get_db(); cur=con.cursor(); cur.execute("SELECT * FROM schools"); schools=cur.fetchall(); con.close()
    schools_html="".join([f"<tr><td>{s['name']}</td><td>{s['email']}</td><td>{'✅ Approved' if s['approved'] else '⏳ Pending'}</td><td><a href='/super-admin/approve/{s['id']}' style='background:#16a34a; color:white; padding:6px 12px; border-radius:6px; text-decoration:none'>Approve</a></td></tr>" for s in schools]) or "<tr><td colspan=4 style='text-align:center'>No schools</td></tr>"
    body=f"""<div class='content'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><h3>Super Admin - {SUPER_ADMIN_EMAIL} - Role: Super Admin</h3><a href='/super-admin/reset-all-mabale-data' style='background:#dc2626; color:white; padding:10px 16px; border-radius:8px; text-decoration:none'>RESET ALL DATA</a> <a href='/logout' style='background:#2563eb; color:white; padding:10px 16px; border-radius:8px; text-decoration:none; margin-left:8px'>Logout</a></div>
    <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px; margin-top:16px'><h3>Schools Management</h3><table style='width:100%; margin-top:10px'><tr><th>School Name</th><th>Email</th><th>Status</th><th>Action</th></tr>{schools_html}</table></div></div>"""
    return HTMLResponse(wrap("Super Admin - DaviSchool", body, SUPER_ADMIN_EMAIL, "Super Admin"))

@app.get("/super-admin/approve/{school_id}")
def approve(request: Request, school_id: int):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL: return HTMLResponse("Denied", status_code=403)
    con=get_db(); cur=con.cursor(); cur.execute("UPDATE schools SET approved=1 WHERE id=?", (school_id,)); con.commit(); con.close()
    return RedirectResponse("/super-admin", status_code=303)

@app.get("/super-admin/reset-all-mabale-data")
def reset_all(request: Request):
    if request.session.get("user_email") != SUPER_ADMIN_EMAIL: return HTMLResponse("Denied", status_code=403)
    con=get_db(); cur=con.cursor(); cur.execute("DELETE FROM students"); cur.execute("DELETE FROM teachers"); cur.execute("DELETE FROM school_classes"); cur.execute("DELETE FROM schools WHERE email != ?", (SUPER_ADMIN_EMAIL,)); cur.execute("DELETE FROM users WHERE email != ?", (SUPER_ADMIN_EMAIL,)); con.commit(); con.close()
    return HTMLResponse(wrap("Wiped", f"<div class='content'><div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:18px'><h1>✅ Wiped!</h1><p>Fresh system. Only {SUPER_ADMIN_EMAIL} remains.</p><a href='/super-admin' style='background:#2563eb; color:white; padding:10px 16px; border-radius:8px; text-decoration:none'>Go to Super Admin</a></div></div>", SUPER_ADMIN_EMAIL, "Super Admin"))

@app.get("/logout")
def logout(request: Request): request.session.clear(); return RedirectResponse("/", status_code=303)
@app.get("/teachers")
def teachers_page(request: Request): return RedirectResponse("/dashboard")
@app.get("/classes")
def classes_page(request: Request): return RedirectResponse("/dashboard")
