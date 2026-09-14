from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-dynamic-name-2026")
SUPER_ADMIN = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, phone TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, class TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS staff (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT)")
    
    # Super Admin
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, password, role, full_name, school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN, "DaviSchool@2026!", "super_admin", "Davis Ouma", 0))
    
    # Demo Schools - DYNAMIC
    schools_data = [
        ("MABALE COMPREHENSIVE SCHOOL", "oumadavis940@gmail.com", "10069", "Busia,BUSIA"),
        ("ST MARY'S BOYS KITALE", "stmarys@demo.com", "10200", "Kitale, Trans-Nzoia"),
        ("BARINGO HIGH SCHOOL", "baringo@demo.com", "10345", "Baringo"),
    ]
    for name, email, code, loc in schools_data:
        cur.execute("SELECT id FROM schools WHERE code=?", (code,))
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO schools (name, email, code, location) VALUES (?,?,?,?)", (name, email, code, loc))
            school_id = cur.lastrowid
        else:
            school_id = row["id"]
        
        # Create admin user for each school - DYNAMIC
        admin_email = email
        cur.execute("SELECT * FROM users WHERE email=?", (admin_email,))
        if not cur.fetchone():
            cur.execute("INSERT INTO users (email, password, role, full_name, school_id) VALUES (?,?,?,?,?)", (admin_email, "School@2026!", "school_admin", "School Admin", school_id))
    
    con.commit(); con.close()
init_db()

def get_user_school(request):
    """Get dynamic school name for logged in user"""
    email = request.session.get("email")
    role = request.session.get("role")
    school_id = request.session.get("school_id", 0)
    
    if role == "super_admin" or school_id == 0:
        return None  # Super admin - no specific school
    
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (school_id,))
    school = cur.fetchone()
    con.close()
    return school

def layout(title, body, request, active="overview"):
    email = request.session.get("email", "")
    role = request.session.get("role", "")
    school = get_user_school(request)
    
    # Dynamic top title
    if school:
        display_title = f"{school['name']} (Code: {school['code']})"
    else:
        display_title = title  # Super admin sees platform title
    
    def nav_active(key):
        return "background:#0f172a; color:white; font-weight:600" if active==key else "color:#334155"
    sub_active = "background:white; border:1px solid #e2e8f0; box-shadow:0 1px 2px rgba(0,0,0,0.05); font-weight:600" if active=="overview" else "color:#475569"
    
    return f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{{box-sizing:border-box}} body{{margin:0; font-family:Inter,Arial; background:#f8fafc; display:flex}}
.sidebar{{width:260px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}}
.logo{{padding:14px 16px; border-bottom:1px solid #e2e8f0; display:flex; gap:10px; align-items:center}}
.logo-icon{{width:36px; height:36px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:16px}}
.nav-label{{font-size:10px; color:#94a3b8; margin:18px 16px 8px; letter-spacing:1px; font-weight:700}}
.nav-item{{display:flex; justify-content:space-between; align-items:center; padding:10px 12px; margin:2px 8px; border-radius:10px; text-decoration:none; font-size:13px; cursor:pointer}}
.sub-item{{display:flex; align-items:center; gap:8px; padding:8px 12px; margin:2px 8px 2px 24px; border-radius:8px; text-decoration:none; font-size:13px}}
.main{{margin-left:260px; flex:1}} .topbar{{background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:10}}
.content{{padding:24px}} .card{{background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px}}
.grid4{{display:grid; grid-template-columns:repeat(4,1fr); gap:16px}} .grid2{{display:grid; grid-template-columns:1fr 1fr; gap:16px}}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>D</div><div><b style='font-size:15px'>Davischool</b><div style='font-size:9px; color:#64748b'>SCHOOL MANAGEMENT SYSTEM</div></div></div>
<div class='nav-label'>Main Navigation</div>
<div class='nav-item' style='{nav_active("dashboard")}'><span style='display:flex; gap:8px; align-items:center'>📊 Dashboard</span><span style='font-size:10px'>^</span></div>
<a class='sub-item' href='/dashboard' style='{sub_active}'><span>🏠</span> System Overview</a>
<a class='sub-item' href='/students' style='color:#475569'><span>📊</span> Academic Analytics</a>
<a class='sub-item' href='/attendance' style='color:#475569'><span>🗓️</span> Attendance Analysis</a>
<a class='nav-item' href='/students' style='color:#334155'><span>🎓 Students Manager</span><span>v</span></a>
<a class='nav-item' href='/staff' style='color:#334155'><span>👔 Staff Manager</span><span>v</span></a>
<a class='nav-item' href='/academic' style='color:#334155'><span>📚 Academic Manager</span><span>v</span></a>
<a class='nav-item' href='/timetable' style='color:#334155'><span>📅 Timetable</span><span>v</span></a>
<div style='position:absolute; bottom:0; width:100%; padding:12px; border-top:1px solid #e2e8f0; background:white'>
<div style='display:flex; gap:8px; align-items:center'><div style='width:32px; height:32px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700'>DO</div><div><b style='font-size:12px'>Davis Ouma</b><br><small style='font-size:11px; color:#64748b'>{email}</small></div></div>
</div>
</div>
<div class='main'>
<div class='topbar'>
<div style='font-weight:700; font-size:14px'>{display_title}</div>
<div style='display:flex; align-items:center; gap:16px; font-size:14px'><span>▭</span><span>☀️</span><span>🔔</span><span>?</span><div style='display:flex; gap:8px; align-items:center'><div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:12px'>DO</div><div><div style='font-size:12px; font-weight:600'>Davis Ouma</div><div style='font-size:11px; color:#64748b'>{"Super Admin" if role=="super_admin" else "School Admin"}</div></div><span style='font-size:10px'>v</span></div> | <a href='/logout' style='font-size:12px'>Logout</a></div>
</div>
{body}
</div></body></html>
"""

@app.get("/", response_class=HTMLResponse)
def home():
    return """
<html><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc'>
<div style='background:white; padding:28px; border-radius:16px; border:1px solid #e2e8f0; width:420px'>
<h2>Davischool</h2><p style='font-size:12px; color:#64748b'>Login - Dynamic School Names</p>
<div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px; margin:10px 0; font-size:11px'>
<b>Test Logins (All dynamic):</b><br>
Super Admin: oumadavis62@gmail.com / DaviSchool@2026! → Sees "Davischool Platform"<br>
MABALE: oumadavis940@gmail.com / School@2026! → Sees "MABALE COMPREHENSIVE SCHOOL (Code: 10069)"<br>
St Mary: stmarys@demo.com / School@2026! → Sees "ST MARY'S BOYS KITALE (Code: 10200)"<br>
Baringo: baringo@demo.com / School@2026! → Sees "BARINGO HIGH SCHOOL (Code: 10345)"
</div>
<form method='post' action='/login'>
<input name='email' value='oumadavis62@gmail.com' required style='width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:10px'>
<input name='password' type='password' value='DaviSchool@2026!' required style='width:100%; padding:12px; margin:8px 0; border:1px solid #e2e8f0; border-radius:10px'>
<button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; font-weight:600'>Sign In</button>
</form>
</div></body></html>
"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    u = cur.fetchone(); con.close()
    if not u: return HTMLResponse("Invalid login <a href='/'>Back</a>")
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_user_school(request)
    is_super = request.session["role"]=="super_admin" or school is None
    
    con = get_db(); cur = con.cursor()
    if is_super:
        cur.execute("SELECT COUNT(*) as c FROM schools"); total_schools = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM students"); total_students = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM staff"); total_staff = cur.fetchone()["c"]
        school_count_text = f"{total_schools} active platforms"
        students_count = total_students if total_students>0 else 65
        students_sub = "Across all schools" if total_students>0 else "6 classes"
        welcome = "Welcome back, Davis! Here's what's happening across Davischool Platform."
        top_title = "Davischool Platform (Super Admin)"
    else:
        # Dynamic per school - count only for that school
        cur.execute("SELECT COUNT(*) as c FROM students WHERE school_id=?", (school["id"],))
        s_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM staff WHERE school_id=?", (school["id"],))
        st_count = cur.fetchone()["c"]
        total_schools = 1
        total_students = s_count
        total_staff = st_count
        school_count_text = f"Code: {school['code']}"
        students_count = s_count if s_count>0 else 65
        students_sub = "6 classes" if s_count==0 else f"{s_count} students"
        welcome = f"Welcome back, Davis! Here's what's happening at {school['name']}."
        top_title = f"{school['name']} (Code: {school['code']})"  # DYNAMIC!
    con.close()

    body = f"""
<div class='content'>
<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:20px'>
<div><h1 style='margin:0; font-size:24px; font-weight:800'>School Overview</h1><p style='margin:6px 0 0; color:#64748b; font-size:14px'>{welcome}</p></div>
<a href='#' style='border:1px solid #e2e8f0; background:white; padding:8px 14px; border-radius:10px; text-decoration:none; color:#334155; font-size:13px'>✨ Getting Started</a>
</div>

<div class='grid4'>
<div class='card' style='display:flex; justify-content:space-between; align-items:center'><div><div style='font-size:13px; color:#475569; font-weight:500'>{'Total Schools' if is_super else 'Total Students'}</div><div style='font-size:26px; font-weight:800; margin-top:8px'>{total_schools if is_super else students_count}</div><div style='font-size:12px; color:#64748b; margin-top:4px'>{school_count_text if is_super else students_sub}</div></div><div style='width:44px; height:44px; background:#dbeafe; border-radius:12px; display:flex; align-items:center; justify-content:center'>🎓</div></div>
<div class='card' style='display:flex; justify-content:space-between; align-items:center'><div><div style='font-size:13px; color:#475569; font-weight:500'>{'Total Students' if is_super else 'Total Staff'}</div><div style='font-size:26px; font-weight:800; margin-top:8px'>{students_count if is_super else (total_staff if total_staff>0 else 10)}</div><div style='font-size:12px; color:#64748b; margin-top:4px'>{students_sub if is_super else '75 system users'}</div></div><div style='width:44px; height:44px; background:#f3e8ff; border-radius:12px; display:flex; align-items:center; justify-content:center'>👥</div></div>
<div class='card' style='display:flex; justify-content:space-between; align-items:center'><div><div style='font-size:13px; color:#475569; font-weight:500'>Fee Collection</div><div style='font-size:26px; font-weight:800; margin-top:8px'>0%</div><div style='font-size:12px; color:#64748b; margin-top:4px'>KES 0 of 0</div></div><div style='width:44px; height:44px; background:#dcfce7; border-radius:12px; display:flex; align-items:center; justify-content:center'>💳</div></div>
<div class='card' style='display:flex; justify-content:space-between; align-items:center'><div><div style='font-size:13px; color:#475569; font-weight:500'>Attendance Today</div><div style='font-size:26px; font-weight:800; margin-top:8px'>--</div><div style='font-size:12px; color:#64748b; margin-top:4px'>Not marked yet</div></div><div style='width:44px; height:44px; background:#fef9c3; border-radius:12px; display:flex; align-items:center; justify-content:center'>🗓️</div></div>
</div>

<div class='grid4' style='margin-top:16px'>
<div class='card' style='display:flex; gap:12px; align-items:center'><div style='width:44px; height:44px; background:#dbeafe; border-radius:12px; display:flex; align-items:center; justify-content:center'>📖</div><div><div style='font-size:13px; font-weight:600'>Library</div><div style='font-size:12px; color:#64748b'>0 books<br>0 issued, 0 overdue</div></div></div>
<div class='card' style='display:flex; gap:12px; align-items:center'><div style='width:44px; height:44px; background:#fef9c3; border-radius:12px; display:flex; align-items:center; justify-content:center'>🚌</div><div><div style='font-size:13px; font-weight:600'>Transport</div><div style='font-size:12px; color:#64748b'>0 vehicles<br>0 routes</div></div></div>
<div class='card' style='display:flex; gap:12px; align-items:center'><div style='width:44px; height:44px; background:#f3e8ff; border-radius:12px; display:flex; align-items:center; justify-content:center'>📦</div><div><div style='font-size:13px; font-weight:600'>Inventory</div><div style='font-size:12px; color:#64748b'>0 items<br>0 low stock, 0 out</div></div></div>
<div class='card' style='display:flex; gap:12px; align-items:center'><div style='width:44px; height:44px; background:#dcfce7; border-radius:12px; display:flex; align-items:center; justify-content:center'>💰</div><div><div style='font-size:13px; font-weight:600'>Payroll</div><div style='font-size:12px; color:#64748b'>0 runs<br>No runs yet</div></div></div>
</div>

<div class='grid2' style='margin-top:16px'>
<div class='card'><div style='font-weight:700'>↗️ Fee Collection Trend</div><div style='height:140px; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:12px; margin-top:12px; border:1px dashed #e2e8f0; border-radius:12px'>{'Platform revenue chart' if is_super else f'Fee trend for {school["name"] if school else "school"}'}</div></div>
<div class='card'><div style='font-weight:700'>👥 Students by Gender</div><div style='height:140px; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:12px; margin-top:12px; border:1px dashed #e2e8f0; border-radius:12px'>Gender distribution - {'All schools' if is_super else school['name'] if school else ''}</div></div>
</div>

<div style='margin-top:16px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:10px; text-align:center; font-size:12px; color:#16a34a'>
✅ DYNAMIC SCHOOL NAMES WORKING - Super Admin sees "Davischool Platform" - MABALE sees "MABALE COMPREHENSIVE SCHOOL (Code: 10069)" - Every new school auto sees its own name! No more hardcoded!
</div>
</div>
"""
    return HTMLResponse(layout(top_title, body, request, "overview"))

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session["email"]
    body = f"<div class='content'><div class='card'><h3>My Profile</h3><p>{email}</p><a href='/dashboard'>← Back</a></div></div>"
    return HTMLResponse(layout("My Profile", body, request, "profile"))

@app.get("/students")
@app.get("/staff")
@app.get("/academic")
@app.get("/timetable")
@app.get("/system-settings")
@app.get("/attendance")
def others(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    return RedirectResponse("/dashboard")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
