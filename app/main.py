from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-final-emoji-cancel-v9")
SUPER_ADMIN = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
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

def get_school(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin":
        return None
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    s = cur.fetchone()
    con.close()
    return s

@app.get("/", response_class=HTMLResponse)
def home():
    return """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head>
<body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'>
<div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'>
<div style='text-align:center; margin-bottom:24px'>
<div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div>
<h2 style='margin:12px 0 4px; font-size:22px'>Davischool</h2>
<p style='font-size:11px; color:#64748b; margin:0; letter-spacing:1px'>SCHOOL MANAGEMENT SYSTEM</p>
</div>
<form method='post' action='/login'>
<label style='font-size:12px; font-weight:600'>Email</label>
<input name='email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'>
<label style='font-size:12px; font-weight:600'>Password</label>
<input name='password' type='password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'>
<button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; font-weight:600'>Sign In</button>
</form>
</div>
</body></html>
"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    con.close()
    if not u:
        return HTMLResponse("Invalid login <a href='/'>Back</a>")
    request.session["email"]=u["email"]
    request.session["role"]=u["role"]
    request.session["name"]=u["full_name"]
    request.session["school_id"]=u["school_id"] or 0
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools")
    total_schools = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5")
    recent_schools = cur.fetchall()
    con.close()
    school = get_school(request)
    is_super = school is None
    name = request.session.get("name","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    role_disp = "Super Admin" if is_super else "School Admin"
    if is_super:
        schools_rows = ""
        for s in recent_schools:
            schools_rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'><div style='font-weight:600; font-size:13px'>🏫 {s['name']}</div><div style='font-size:11px; color:#64748b'>{s['code']}</div></td><td style='padding:12px; border-bottom:1px solid #f1f5f9; font-size:12px'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'><span style='background:#dcfce7; color:#166534; padding:3px 8px; border-radius:12px; font-size:10px'>✅ Active</span></td><td style='padding:12px; border-bottom:1px solid #f1f5f9; font-size:11px; color:#64748b'>Today</td></tr>"
        if not schools_rows:
            schools_rows = "<tr><td colspan=4 style='padding:24px; text-align:center; color:#94a3b8; font-size:12px'>No schools yet. Click + Add School.</td></tr>"
        content = f"""
        <div style='padding:24px'>
        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:20px'>
        <div><h2 style='margin:0; font-size:22px; font-weight:800; color:#0f172a'>📊 School Overview</h2><p style='margin:4px 0 0; color:#64748b; font-size:13px'>Welcome {name} - Monitor all schools</p></div>
        <a href='/schools/manage' style='background:#0f172a; color:white; padding:10px 18px; border-radius:10px; text-decoration:none; font-size:13px; font-weight:600'>➕ Add School</a>
        </div>
        <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='display:flex; justify-content:space-between; align-items:center'><div style='font-size:11px; color:#64748b; font-weight:600'>🏫 TOTAL SCHOOLS</div><div style='font-size:22px'>🏫</div></div><div style='font-size:28px; font-weight:800; margin:8px 0 2px'>{total_schools}</div><div style='font-size:11px; color:#16a34a'>📈 Up 12%</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='display:flex; justify-content:space-between; align-items:center'><div style='font-size:11px; color:#64748b; font-weight:600'>✅ ACTIVE</div><div style='font-size:22px'>✅</div></div><div style='font-size:28px; font-weight:800; margin:8px 0 2px'>{total_schools}</div><div style='font-size:11px; color:#16a34a'>🟢 All active</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='display:flex; justify-content:space-between; align-items:center'><div style='font-size:11px; color:#64748b; font-weight:600'>💰 REVENUE</div><div style='font-size:22px'>💰</div></div><div style='font-size:28px; font-weight:800; margin:8px 0 2px'>KES {total_schools*15000:,}</div><div style='font-size:11px; color:#64748b'>💵 15k per school</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='display:flex; justify-content:space-between; align-items:center'><div style='font-size:11px; color:#64748b; font-weight:600'>🎓 STUDENTS</div><div style='font-size:22px'>🎓</div></div><div style='font-size:28px; font-weight:800; margin:8px 0 2px'>{total_schools*350:,}</div><div style='font-size:11px; color:#64748b'>👨‍🎓 Across all schools</div></div>
        </div>
        <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:16px 18px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b style='font-size:14px'>🏫 Recently Added Schools</b><a href='/schools/manage' style='font-size:12px; color:#2563eb; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px 12px; text-align:left'>School Name</th><th style='padding:10px 12px; text-align:left'>Location</th><th style='padding:10px 12px; text-align:left'>Status</th><th style='padding:10px 12px; text-align:left'>Date</th></tr>{schools_rows}</table></div>
            <div style='display:flex; flex-direction:column; gap:16px'>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>
                <b style='font-size:14px'>⚡ Quick Actions</b>
                <div style='margin-top:12px; display:flex; flex-direction:column; gap:8px'>
                <a href='/schools/manage' style='display:block; background:#0f172a; color:white; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600'>🏫 Manage Schools</a>
                <a href='/schools/manage?show=add' style='display:block; background:white; border:1px solid #0f172a; color:#0f172a; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600'>➕ Register New School</a>
                </div>
                </div>
                <div style='background:#0f172a; border-radius:14px; padding:18px; color:white'><div style='font-size:13px; font-weight:700'>📊 Davischool Analytics</div><div style='font-size:11px; color:#94a3b8; margin-top:4px'>🚀 Platform performing well. All {total_schools} schools active.</div><div style='margin-top:12px; background:#1e293b; border-radius:8px; padding:10px'><div style='font-size:10px; color:#94a3b8'>💚 PLATFORM HEALTH</div><div style='font-size:18px; font-weight:700; color:#4ade80; margin-top:2px'>✅ 99.9% Uptime</div></div></div>
            </div>
        </div>
        </div>
        """
    else:
        top = school["name"] + " (Code: " + school["code"] + ")"
        content = f"<div style='padding:24px'><h2>📊 School Overview</h2><p>Welcome {name} - {top}</p></div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; margin:0; background:#f8fafc'><div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'><div style='font-weight:700; font-size:14px'>{'🏫 Davischool Platform (Super Admin)' if is_super else top}</div><div style='display:flex; gap:12px; align-items:center; font-size:12px'><div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700'>{initials}</div><div><div style='font-weight:600'>{name}</div><div style='color:#64748b; font-size:11px'>{role_disp}</div></div><a href='/profile?tab=personal' style='border:1px solid #e2e8f0; padding:6px 10px; border-radius:6px; text-decoration:none'>👤 Profile</a><a href='/logout' style='color:#dc2626; text-decoration:none'>🚪 Logout</a></div></div>{content}</body></html>")

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("email","")
    name = request.session.get("name","Davis Ouma")
    school = get_school(request)
    is_super = school is None
    top = "🏫 Davischool Platform (Super Admin)" if is_super else school["name"] + " (Code: " + school["code"] + ")"
    badge = "Super Admin" if is_super else "School Admin"
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    if tab=="security":
        right = f"<b>🔒 Security Settings</b><form method='post' action='/update-password'><label style='font-size:12px; display:block; margin-top:14px'>🔑 Current</label><input name='current_password' type='password' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; display:block; margin-top:12px'>🆕 New</label><input name='new_password' type='password' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; display:block; margin-top:12px'>✅ Confirm</label><input name='confirm_password' type='password' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><div style='text-align:right; margin-top:16px'><button type='submit' style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px'>🔐 Update Password</button></div></form>"
    elif tab=="activity":
        right = f"<b>📜 Activity Log</b><div style='border:1px solid #e2e8f0; border-radius:8px; margin-top:12px'><div style='padding:10px; font-size:12px'>🔓 Logged in - {email}</div></div>"
    else:
        right = f"<b>👤 Personal Info</b><form method='post' action='/update-profile'><label style='font-size:12px; display:block; margin-top:14px'>👨‍💼 Full Name</label><input name='full_name' value='{name}' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; display:block; margin-top:12px'>📧 Email</label><input name='email_new' value='{email}' required style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><label style='font-size:12px; display:block; margin-top:12px'>📱 Phone</label><input name='phone' value='+254748588874' style='width:100%; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'><div style='text-align:right; margin-top:18px'><button type='submit' style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px'>💾 Save Changes</button></div></form>"
    ap = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="personal" else "color:#64748b"
    ase = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="security" else "color:#64748b"
    aa = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="activity" else "color:#64748b"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'><div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between'><div style='font-weight:700'>{top}</div><div><a href='/dashboard'>📊 Dashboard</a> | <a href='/logout'>🚪 Logout</a></div></div><div style='padding:20px'><div style='display:flex; border-bottom:1px solid #e2e8f0; margin-bottom:16px'><a href='/profile?tab=personal' style='padding:8px 4px; margin-right:16px; text-decoration:none; font-size:13px; {ap}'>👤 Personal Info</a><a href='/profile?tab=security' style='padding:8px 4px; margin-right:16px; text-decoration:none; font-size:13px; {ase}'>🔒 Security</a><a href='/profile?tab=activity' style='padding:8px 4px; text-decoration:none; font-size:13px; {aa}'>📜 Activity Log</a></div><div style='display:grid; grid-template-columns:340px 1fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px; text-align:center'><div style='width:80px; height:80px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:26px; font-weight:800; margin:0 auto'>{initials}</div><div style='font-weight:700; margin-top:12px'>{name}</div><div style='font-size:12px'>{email}</div><div style='margin-top:6px'><span style='background:#e0f2fe; color:#0369a1; padding:4px 10px; border-radius:20px; font-size:11px'>{badge}</span></div></div><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px'>{right}</div></div></div></body></html>")

@app.post("/update-password")
def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if "email" not in request.session:
        return RedirectResponse("/")
    if new_password!= confirm_password:
        return HTMLResponse("<h3>❌ Error: Passwords do not match</h3><a href='/profile?tab=security'>Back</a>")
    email = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_password))
    u = cur.fetchone()
    if not u:
        con.close()
        return HTMLResponse("<h3>❌ Current password incorrect</h3><a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_password, email))
    con.commit()
    con.close()
    return HTMLResponse("<h3>✅ Password Updated!</h3><a href='/profile?tab=security'>Back</a>")

@app.post("/update-profile")
def update_profile(request: Request, full_name: str = Form(...), email_new: str = Form(...), phone: str = Form(...)):
    if "email" not in request.session:
        return RedirectResponse("/")
    old_email = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE users SET full_name=?, email=? WHERE email=?", (full_name.strip(), email_new.strip(), old_email))
    con.commit()
    con.close()
    request.session["email"] = email_new.strip()
    request.session["name"] = full_name.strip()
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = ""):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC")
    schools = cur.fetchall()
    con.close()
    rows = ""
    for s in schools:
        phone = s["phone"] if "phone" in s.keys() and s["phone"] else "-"
        principal = s["principal"] if "principal" in s.keys() and s["principal"] else "-"
        stype = s["school_type"] if "school_type" in s.keys() and s["school_type"] else "-"
        rows += f"<tr><td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#64748b'>{s['code']} | {stype}</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📧 {s['email']}<div style='color:#64748b'>📱 {phone}</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📍 {s['location']}<div style='color:#64748b'>👨‍💼 {principal}</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'><a href='/schools/edit/{s['id']}' style='background:#e0f2fe; color:#0369a1; padding:5px 10px; border-radius:6px; text-decoration:none; margin-right:4px'>✏️ Edit</a><a href='/schools/delete/{s['id']}' onclick=\"return confirm('Delete {s['name']}?')\" style='background:#fee2e2; color:#dc2626; padding:5px 10px; border-radius:6px; text-decoration:none'>🗑️ Delete</a></td></tr>"
    if not rows:
        rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999; font-size:12px'>No schools yet</td></tr>"
    hl = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"
    return HTMLResponse(f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; background:#f8fafc; margin:0'>
<div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'><b>🏫 Davischool - Schools Management</b><a href='/dashboard' style='text-decoration:none; border:1px solid #e2e8f0; padding:6px 12px; border-radius:6px; font-size:12px'>⬅️ Back to Dashboard</a></div>
<div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; overflow:auto'>
<div style='display:flex; justify-content:space-between'><b>📚 Registered Schools ({len(schools)})</b><span style='font-size:11px; color:#64748b'>✏️ Edit / 🗑️ Delete enabled</span></div>
<table style='width:100%; margin-top:12px; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; text-align:left'><th style='padding:10px'>School</th><th style='padding:10px'>Contact</th><th style='padding:10px'>Location</th><th style='padding:10px'>Actions</th></tr>{rows}</table>
</div>
<div style='background:white; {hl}; border-radius:12px; padding:20px; position:sticky; top:20px'>
<b style='font-size:15px'>➕ Register New School</b><p style='font-size:11px; color:#64748b; margin:4px 0 12px'>Fill all basic registration features</p>
<form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px'>
<input name='school_name' placeholder='🏫 School Name * e.g. Busia Academy' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='school_email' placeholder='📧 School Admin Email *' required type='email' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='location' placeholder='📍 Location / County *' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='phone' placeholder='📱 Phone * e.g. 0748588874' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='principal' placeholder='👨‍💼 Principal Name *' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<select name='school_type' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<option value=''>🎓 Select School Type *</option>
<option value='Primary'>📚 Primary School</option>
<option value='Secondary'>🏫 Secondary School</option>
<option value='Junior Secondary'>🎒 Junior Secondary</option>
<option value='Mixed'>🏫 Mixed</option>
<option value='Private Academy'>🎓 Private Academy</option>
</select>
<button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; margin-top:6px; font-weight:600; cursor:pointer'>✅ Create School + Auto Code</button>
<a href='/schools/manage' style='width:100%; background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:13px; font-weight:600; display:block; box-sizing:border-box'>❌ Cancel</a>
<a href='/dashboard' style='width:100%; background:#f8fafc; border:1px dashed #cbd5e1; color:#0f172a; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; display:block; box-sizing:border-box'>⬅️ Back to Dashboard</a>
<div style='font-size:10px; color:#64748b; margin-top:2px'>System will auto-generate School Code + Admin Login: School@2026!</div>
</form>
</div>
</div>
</body></html>
""")

@app.get("/schools/edit/{school_id}", response_class=HTMLResponse)
def edit_school_form(school_id: int, request: Request):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (school_id,))
    s = cur.fetchone()
    con.close()
    if not s:
        return HTMLResponse("School not found <a href='/schools/manage'>Back</a>")
    return HTMLResponse(f"""
<html><body style='font-family:Arial; background:#f8fafc; margin:0; padding:20px; display:flex; justify-content:center'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:24px; width:480px'>
<h3>✏️ Edit School - {s['name']}</h3><p style='font-size:11px; color:#64748b'>Code: {s['code']}</p>
<form method='post' action='/schools/update/{s['id']}' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'>
<label style='font-size:12px'>🏫 School Name</label><input name='school_name' value="{s['name']}" required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<label style='font-size:12px'>📧 Admin Email</label><input name='school_email' value="{s['email']}" required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<label style='font-size:12px'>📍 Location</label><input name='location' value="{s['location']}" required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<label style='font-size:12px'>📱 Phone</label><input name='phone' value="{s['phone'] if s['phone'] else ''}" style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<label style='font-size:12px'>👨‍💼 Principal</label><input name='principal' value="{s['principal'] if s['principal'] else ''}" style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<label style='font-size:12px'>🎓 Type</label>
<select name='school_type' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<option {'selected' if s['school_type']=='Primary' else ''}>Primary</option>
<option {'selected' if s['school_type']=='Secondary' else ''}>Secondary</option>
<option {'selected' if s['school_type']=='Junior Secondary' else ''}>Junior Secondary</option>
<option {'selected' if s['school_type']=='Mixed' else ''}>Mixed</option>
<option {'selected' if s['school_type']=='Private Academy' else ''}>Private Academy</option>
</select>
<button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; margin-top:8px'>💾 Save Changes</button>
<a href='/schools/manage' style='text-align:center; padding:10px; border:1px solid #e2e8f0; border-radius:8px; text-decoration:none; color:#64748b; font-size:12px'>❌ Cancel</a>
</form>
</div>
</body></html>
""")

@app.post("/schools/update/{school_id}")
def update_school(school_id: int, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, school_id))
    cur.execute("UPDATE users SET email=? WHERE school_id=?", (school_email.strip(), school_id))
    con.commit()
    con.close()
    return RedirectResponse("/schools/manage", status_code=303)

@app.get("/schools/delete/{school_id}")
def delete_school(school_id: int, request: Request):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/")
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM schools WHERE id=?", (school_id,))
    cur.execute("DELETE FROM users WHERE school_id=?", (school_id,))
    con.commit()
    con.close()
    return RedirectResponse("/schools/manage", status_code=303)

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    code = str(random.randint(10000,99999))
    con = get_db()
    cur = con.cursor()
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), code, location.strip(), phone.strip(), principal.strip(), school_type))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (school_email.strip(), "School@2026!", "school_admin", f"{principal.strip() or 'School Admin'}", sid))
    con.commit()
    con.close()
    return HTMLResponse(f"<h3>✅ School {school_name} Created - Code {code}</h3><p>Login: {school_email} / School@2026!</p><a href='/schools/manage'>Back</a>")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
