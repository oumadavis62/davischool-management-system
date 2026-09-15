from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-final-select-blue-v10")
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
<input name='email' placeholder='Email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'>
<input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'>
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
    total = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5")
    recent = cur.fetchall()
    con.close()
    school = get_school(request)
    is_super = school is None
    name = request.session.get("name","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    role_disp = "Super Admin" if is_super else "School Admin"
    if is_super:
        rows = ""
        for s in recent:
            rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
        if not rows:
            rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
        content = f"""
        <div style='padding:24px'>
        <div style='display:flex; justify-content:space-between; margin-bottom:20px'><div><h2 style='margin:0'>📊 School Overview</h2><p style='color:#64748b; font-size:13px'>Welcome {name}</p></div><a href='/schools/manage' style='background:#0f172a; color:white; padding:10px 18px; border-radius:10px; text-decoration:none'>➕ Add School</a></div>
        <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>💰 REVENUE</div><div style='font-size:28px; font-weight:800; margin-top:8px'>KES {total*15000:,}</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 STUDENTS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total*350:,}</div></div>
        </div>
        <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>🏫 Recently Added Schools</b><a href='/schools/manage' style='font-size:12px; color:#2563eb; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Location</th><th style='padding:10px; text-align:left'>Status</th><th style='padding:10px; text-align:left'>Date</th></tr>{rows}</table></div>
            <div style='display:flex; flex-direction:column; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><b>⚡ Quick Actions</b><div style='margin-top:12px; display:flex; flex-direction:column; gap:8px'><a href='/schools/manage' style='display:block; background:#0f172a; color:white; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600'>🏫 Manage Schools</a><a href='/schools/manage?show=add' style='display:block; background:white; border:1px solid #0f172a; color:#0f172a; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600'>➕ Register New School</a></div></div><div style='background:#0f172a; border-radius:14px; padding:18px; color:white'><div style='font-size:13px; font-weight:700'>📊 Davischool Analytics</div><div style='font-size:11px; color:#94a3b8; margin-top:4px'>🚀 All {total} schools active.</div><div style='margin-top:12px; background:#1e293b; border-radius:8px; padding:10px'><div style='font-size:10px; color:#94a3b8'>PLATFORM HEALTH</div><div style='font-size:18px; font-weight:700; color:#4ade80'>✅ 99.9% Uptime</div></div></div></div>
        </div>
        </div>
        """
    else:
        content = f"<div style='padding:24px'><h2>School Overview</h2><p>{school['name']}</p></div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; margin:0; background:#f8fafc'><div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between'><b>🏫 Davischool Platform (Super Admin)</b><div style='display:flex; gap:12px; align-items:center'><div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700'>{initials}</div><a href='/profile?tab=personal'>👤 Profile</a><a href='/logout' style='color:#dc2626'>🚪 Logout</a></div></div>{content}</body></html>")

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("email","")
    name = request.session.get("name","Davis Ouma")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    if tab=="security":
        right = f"<b>🔒 Security</b><form method='post' action='/update-password'><input name='current_password' type='password' placeholder='Current' required style='width:100%; padding:10px; margin-top:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='new_password' type='password' placeholder='New' required style='width:100%; padding:10px; margin-top:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='confirm_password' type='password' placeholder='Confirm' required style='width:100%; padding:10px; margin-top:10px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px; margin-top:12px'>🔐 Update Password</button></form>"
    else:
        right = f"<b>👤 Personal Info</b><form method='post' action='/update-profile'><input name='full_name' value='{name}' required style='width:100%; padding:10px; margin-top:10px; border:1px solid #e2e8f0; border-radius:8px'><input name='email_new' value='{email}' required style='width:100%; padding:10px; margin-top:10px; border:1px solid #e2e8f0; border-radius:8px'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px; margin-top:12px'>💾 Save Changes</button></form>"
    return HTMLResponse(f"<html><body style='margin:0; font-family:Arial; background:#f8fafc'><div style='padding:20px'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px; max-width:700px'>{right}<div style='margin-top:20px'><a href='/dashboard'>Back</a></div></div></div></body></html>")

@app.post("/update-password")
def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    if new_password!= confirm_password: return HTMLResponse("<h3>❌ Passwords do not match</h3><a href='/profile?tab=security'>Back</a>")
    email = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_password))
    if not cur.fetchone():
        con.close()
        return HTMLResponse("<h3>❌ Current incorrect</h3><a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_password, email))
    con.commit()
    con.close()
    return HTMLResponse("<h3>✅ Updated</h3><a href='/profile?tab=security'>Back</a>")

@app.post("/update-profile")
def update_profile(request: Request, full_name: str = Form(...), email_new: str = Form(...), phone: str = Form(default="")):
    if "email" not in request.session: return RedirectResponse("/")
    old = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE users SET full_name=?, email=? WHERE email=?", (full_name.strip(), email_new.strip(), old))
    con.commit()
    con.close()
    request.session["email"]=email_new.strip()
    request.session["name"]=full_name.strip()
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = "", success: str = ""):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC")
    schools = cur.fetchall()
    con.close()

    success_banner = ""
    if success == "added":
        success_banner = "<div id='successBanner' style='background:#dcfce7; border:1px solid #86efac; color:#166534; padding:12px 16px; border-radius:10px; margin-bottom:16px; display:flex; justify-content:space-between; align-items:center'><div>✅ <b>Success!</b> School registered successfully. Code generated & login created.</div><span onclick=\"this.parentElement.style.display='none'\" style='cursor:pointer; font-weight:700'>✖</span></div>"
    elif success == "updated":
        success_banner = "<div id='successBanner' style='background:#e0f2fe; border:1px solid #7dd3fc; color:#0c4a6e; padding:12px 16px; border-radius:10px; margin-bottom:16px; display:flex; justify-content:space-between; align-items:center'><div>✅ <b>Updated!</b> School information updated successfully.</div><span onclick=\"this.parentElement.style.display='none'\" style='cursor:pointer; font-weight:700'>✖</span></div>"
    elif success == "deleted":
        success_banner = "<div id='successBanner' style='background:#fee2e2; border:1px solid #fca5a5; color:#991b1b; padding:12px 16px; border-radius:10px; margin-bottom:16px; display:flex; justify-content:space-between; align-items:center'><div>🗑️ <b>Deleted!</b> School removed successfully.</div><span onclick=\"this.parentElement.style.display='none'\" style='cursor:pointer; font-weight:700'>✖</span></div>"

    rows_html = ""
    schools_json = {}
    for s in schools:
        sid = s["id"]
        schools_json[sid] = {
            "id": sid,
            "name": s["name"],
            "email": s["email"],
            "code": s["code"],
            "location": s["location"],
            "phone": s["phone"] if s["phone"] else "",
            "principal": s["principal"] if s["principal"] else "",
            "school_type": s["school_type"] if s["school_type"] else ""
        }
        phone = s["phone"] or "-"
        principal = s["principal"] or "-"
        stype = s["school_type"] or "-"
        rows_html += f"""
        <tr id='row-{sid}' onclick='selectSchool({sid})' style='cursor:pointer; transition:0.15s'>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#64748b'>{s['code']} | {stype}</div></td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📧 {s['email']}<div style='color:#64748b'>📱 {phone}</div></td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📍 {s['location']}<div style='color:#64748b'>👨‍💼 {principal}</div></td>
        </tr>
        """
    if not rows_html:
        rows_html = "<tr><td colspan=3 style='padding:24px; text-align:center; color:#999'>No schools yet — add first school on the right</td></tr>"

    import json
    schools_data = json.dumps(schools_json)

    highlight = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"

    return HTMLResponse(f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head>
<body style='font-family:Arial; background:#f8fafc; margin:0'>
<div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'>
<b>🏫 Davischool - Schools Management</b>
<a href='/dashboard' style='text-decoration:none; border:1px solid #e2e8f0; padding:6px 12px; border-radius:6px; font-size:12px'>⬅️ Dashboard</a>
</div>

<div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>
{success_banner}
<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px'>
    <div><b>📚 Registered Schools ({len(schools)})</b><div style='font-size:11px; color:#64748b'>Click a row to select — highlighted in blue</div></div>
    <div style='display:flex; gap:8px'>
        <button id='editBtn' disabled onclick='openEditModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px; font-weight:600; cursor:not-allowed'>✏️ Edit</button>
        <button id='deleteBtn' disabled onclick='openDeleteModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px; font-weight:600; cursor:not-allowed'>🗑️ Delete</button>
    </div>
</div>

<table style='width:100%; border-collapse:collapse'>
<tr style='background:#f8fafc; font-size:11px; text-align:left; color:#64748b'><th style='padding:10px'>School</th><th style='padding:10px'>Contact</th><th style='padding:10px'>Location</th></tr>
{rows_html}
</table>
<div id='selectionInfo' style='margin-top:12px; padding:10px; background:#f8fafc; border-radius:8px; font-size:11px; color:#64748b; text-align:center'>👆 Select a school row above to enable Edit / Delete buttons</div>
</div>

<div style='background:white; {highlight}; border-radius:12px; padding:20px; position:sticky; top:20px'>
<b style='font-size:15px'>➕ Register New School</b><p style='font-size:11px; color:#64748b; margin:4px 0 12px'>All basic registration features</p>
<form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px'>
<input name='school_name' placeholder='🏫 School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='school_email' placeholder='📧 Admin Email *' required type='email' style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='location' placeholder='📍 Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='phone' placeholder='📱 Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='principal' placeholder='👨‍💼 Principal Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<option value=''>🎓 Select Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option>
</select>
<button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600; cursor:pointer'>✅ Create School + Auto Code</button>
<a href='/schools/manage' style='background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:13px; display:block'>❌ Cancel</a>
<a href='/dashboard' style='background:#f8fafc; border:1px dashed #cbd5e1; color:#0f172a; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; display:block'>⬅️ Back to Dashboard</a>
</form>
</div>
</div>

<!-- EDIT MODAL - Same as Register Window -->
<div id='editModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'>
<div style='background:white; border-radius:16px; width:100%; max-width:480px; max-height:90vh; overflow:auto; padding:24px'>
<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:16px'><b style='font-size:16px'>✏️ Edit School</b><span onclick='closeEditModal()' style='cursor:pointer; font-size:20px'>✖</span></div>
<p id='editCodeInfo' style='font-size:11px; color:#64748b; margin-bottom:12px'></p>
<form method='post' id='editForm' style='display:flex; flex-direction:column; gap:10px'>
<input name='school_name' id='edit_name' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='school_email' id='edit_email' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='location' id='edit_location' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='phone' id='edit_phone' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='principal' id='edit_principal' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<select name='school_type' id='edit_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select>
<button type='submit' style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600; margin-top:6px'>💾 Save Changes</button>
<div onclick='closeEditModal()' style='background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; cursor:pointer'>❌ Cancel</div>
</form>
</div>
</div>

<!-- DELETE CONFIRMATION MODAL -->
<div id='deleteModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'>
<div style='background:white; border-radius:16px; width:100%; max-width:380px; padding:24px; text-align:center'>
<div style='width:56px; height:56px; background:#fee2e2; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px; margin:0 auto 12px'>⚠️</div>
<h3 style='margin:0'>Delete School?</h3>
<p id='deleteInfo' style='font-size:13px; color:#64748b; margin:8px 0 16px'>Are you sure you want to delete this school? This action cannot be undone and will also delete its admin login.</p>
<div style='display:grid; grid-template-columns:1fr 1fr; gap:10px'>
<div onclick='closeDeleteModal()' style='background:white; border:1px solid #e2e8f0; color:#0f172a; padding:11px; border-radius:8px; text-align:center; cursor:pointer; font-weight:600'>❌ Cancel</div>
<a id='confirmDeleteBtn' href='#' style='background:#dc2626; color:white; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-weight:600'>🗑️ Yes, Delete</a>
</div>
</div>
</div>

<script>
let selectedId = null;
let schools = {schools_data};

function selectSchool(id) {{
    // remove old highlight
    document.querySelectorAll('tr[id^="row-"]').forEach(r => {{
        r.style.background = 'white';
        r.style.borderLeft = 'none';
    }});
    // highlight new - BLUE
    let row = document.getElementById('row-'+id);
    if(row) {{
        row.style.background = '#dbeafe';
        row.style.borderLeft = '4px solid #2563eb';
    }}
    selectedId = id;
    // enable buttons - REAL BUTTONS now
    let editBtn = document.getElementById('editBtn');
    let deleteBtn = document.getElementById('deleteBtn');
    editBtn.disabled = false;
    deleteBtn.disabled = false;
    editBtn.style.background = '#0f172a';
    editBtn.style.color = 'white';
    editBtn.style.cursor = 'pointer';
    deleteBtn.style.background = '#dc2626';
    deleteBtn.style.color = 'white';
    deleteBtn.style.cursor = 'pointer';
    document.getElementById('selectionInfo').innerHTML = '✅ Selected: <b>' + schools[id].name + '</b> (' + schools[id].code + ') — Now click ✏️ Edit or 🗑️ Delete';
    document.getElementById('selectionInfo').style.background = '#dbeafe';
    document.getElementById('selectionInfo').style.color = '#1e40af';
}}

function openEditModal() {{
    if(!selectedId) return;
    let s = schools[selectedId];
    document.getElementById('edit_name').value = s.name;
    document.getElementById('edit_email').value = s.email;
    document.getElementById('edit_location').value = s.location;
    document.getElementById('edit_phone').value = s.phone;
    document.getElementById('edit_principal').value = s.principal;
    document.getElementById('edit_type').value = s.school_type;
    document.getElementById('editCodeInfo').innerText = 'Code: ' + s.code + ' (cannot be changed)';
    document.getElementById('editForm').action = '/schools/update/' + selectedId;
    document.getElementById('editModal').style.display = 'flex';
}}

function closeEditModal() {{
    document.getElementById('editModal').style.display = 'none';
}}

function openDeleteModal() {{
    if(!selectedId) return;
    let s = schools[selectedId];
    document.getElementById('deleteInfo').innerHTML = 'Are you sure you want to delete <b>' + s.name + '</b> (Code: ' + s.code + ')?<br><br>This will also delete its admin login. This cannot be undone.';
    document.getElementById('confirmDeleteBtn').href = '/schools/delete/' + selectedId;
    document.getElementById('deleteModal').style.display = 'flex';
}}

function closeDeleteModal() {{
    document.getElementById('deleteModal').style.display = 'none';
}}

// auto hide success after 5 sec
setTimeout(() => {{
    let b = document.getElementById('successBanner');
    if(b) b.style.display='none';
}}, 5000);
</script>

</body></html>
""")

@app.post("/schools/update/{school_id}")
def update_school(school_id: int, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, school_id))
    cur.execute("UPDATE users SET email=?, full_name=? WHERE school_id=?", (school_email.strip(), principal.strip(), school_id))
    con.commit()
    con.close()
    return RedirectResponse("/schools/manage?success=updated", status_code=303)

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
    return RedirectResponse("/schools/manage?success=deleted", status_code=303)

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
    return RedirectResponse("/schools/manage?success=added", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
