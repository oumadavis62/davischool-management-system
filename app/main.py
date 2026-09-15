from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random
import json

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-remove-add-school-hover-v11")
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
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px; font-size:22px'>Davischool</h2><p style='font-size:11px; color:#64748b; margin:0; letter-spacing:1px'>SCHOOL MANAGEMENT SYSTEM</p></div><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; font-weight:600'>Sign In</button></form></div></body></html>"""

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
    is_super = get_school(request) is None
    name = request.session.get("name","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"

    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'><span style='background:#dcfce7; color:#166534; padding:3px 8px; border-radius:12px; font-size:10px'>✅ Active</span></td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
    if not rows:
        rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"

    # REMOVED Add School button here!
    content = f"""
    <style>
   .quick-btn {{
        display:block; background:white; border:1px solid #e2e8f0; color:#0f172a; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600; transition:0.2s; cursor:pointer;
    }}
   .quick-btn:hover {{
        background:#0f172a; color:white; border-color:#0f172a;
    }}
   .quick-btn-light {{
        display:block; background:white; border:1px solid #e2e8f0; color:#64748b; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600; transition:0.2s; cursor:pointer;
    }}
   .quick-btn-light:hover {{
        background:#0f172a; color:white; border-color:#0f172a;
    }}
    </style>
    <div style='padding:24px'>
    <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:20px'>
        <div><h2 style='margin:0; font-size:22px; font-weight:800'>📊 School Overview</h2><p style='margin:4px 0 0; color:#64748b; font-size:13px'>Welcome {name} - Monitor all schools</p></div>
        <!-- Add School REMOVED - repetition of Register New School -->
    </div>
    <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div><div style='font-size:11px; color:#16a34a'>📈 Up 12%</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div><div style='font-size:11px; color:#16a34a'>🟢 All active</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>💰 REVENUE</div><div style='font-size:28px; font-weight:800; margin-top:8px'>KES {total*15000:,}</div><div style='font-size:11px; color:#64748b'>💵 15k per school</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 STUDENTS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total*350:,}</div><div style='font-size:11px; color:#64748b'>👨‍🎓 Across all schools</div></div>
    </div>
    <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>🏫 Recently Added Schools</b><a href='/schools/manage' style='font-size:12px; color:#2563eb; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Location</th><th style='padding:10px; text-align:left'>Status</th><th style='padding:10px; text-align:left'>Date</th></tr>{rows}</table></div>
        <div style='display:flex; flex-direction:column; gap:16px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>
                <b style='font-size:14px'>⚡ Quick Actions</b>
                <div style='margin-top:12px; display:flex; flex-direction:column; gap:8px'>
                    <a href='/schools/manage' class='quick-btn'>🏫 Manage Schools</a>
                    <a href='/schools/manage?show=add' class='quick-btn-light'>➕ Register New School</a>
                </div>
                <div style='margin-top:10px; font-size:10px; color:#94a3b8; text-align:center'>Hover to darken</div>
            </div>
            <div style='background:#0f172a; border-radius:14px; padding:18px; color:white'><div style='font-size:13px; font-weight:700'>📊 Davischool Analytics</div><div style='font-size:11px; color:#94a3b8; margin-top:4px'>🚀 All {total} schools active.</div><div style='margin-top:12px; background:#1e293b; border-radius:8px; padding:10px'><div style='font-size:10px; color:#94a3b8'>💚 PLATFORM HEALTH</div><div style='font-size:18px; font-weight:700; color:#4ade80'>✅ 99.9% Uptime</div></div></div>
        </div>
    </div>
    </div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; margin:0; background:#f8fafc'><div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between'><b>🏫 Davischool Platform (Super Admin)</b><div style='display:flex; gap:12px; align-items:center'><div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700'>{initials}</div><a href='/profile?tab=personal'>👤 Profile</a><a href='/logout' style='color:#dc2626'>🚪 Logout</a></div></div>{content}</body></html>")

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session:
        return RedirectResponse("/")
    return HTMLResponse(f"<html><body style='font-family:Arial; padding:20px; background:#f8fafc'><div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px; max-width:600px'><h3>Profile</h3><p>{request.session.get('email')}</p><a href='/dashboard'>Back</a></div></body></html>")

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
        success_banner = "<div id='successBanner' style='background:#dcfce7; border:1px solid #86efac; color:#166534; padding:12px 16px; border-radius:10px; margin-bottom:16px; display:flex; justify-content:space-between'><div>✅ <b>Success!</b> School registered successfully.</div><span onclick=\"this.parentElement.style.display='none'\" style='cursor:pointer'>✖</span></div>"
    elif success == "updated":
        success_banner = "<div style='background:#e0f2fe; border:1px solid #7dd3fc; color:#0c4a6e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>✅ <b>Updated!</b> School updated.</div>"
    elif success == "deleted":
        success_banner = "<div style='background:#fee2e2; border:1px solid #fca5a5; color:#991b1b; padding:12px 16px; border-radius:10px; margin-bottom:16px'>🗑️ <b>Deleted!</b> School removed.</div>"

    rows_html = ""
    schools_json = {}
    for s in schools:
        sid = s["id"]
        schools_json[sid] = {"id": sid, "name": s["name"], "email": s["email"], "code": s["code"], "location": s["location"], "phone": s["phone"] or "", "principal": s["principal"] or "", "school_type": s["school_type"] or ""}
        phone = s["phone"] or "-"
        principal = s["principal"] or "-"
        stype = s["school_type"] or "-"
        rows_html += f"<tr id='row-{sid}' onclick='selectSchool({sid})' style='cursor:pointer'><td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#64748b'>{s['code']} | {stype}</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📧 {s['email']}<div>📱 {phone}</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📍 {s['location']}<div>👨‍💼 {principal}</div></td></tr>"
    if not rows_html:
        rows_html = "<tr><td colspan=3 style='padding:24px; text-align:center; color:#999'>No schools yet</td></tr>"

    schools_data = json.dumps(schools_json)
    hl = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"

    return HTMLResponse(f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head>
<body style='font-family:Arial; background:#f8fafc; margin:0'>
<div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between'><b>🏫 Schools Management</b><a href='/dashboard' style='border:1px solid #e2e8f0; padding:6px 12px; border-radius:6px; text-decoration:none; font-size:12px'>⬅️ Dashboard</a></div>
<div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>
{success_banner}
<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px'>
<div><b>📚 Registered Schools ({len(schools)})</b><div style='font-size:11px; color:#64748b'>Click row to select — highlights blue</div></div>
<div style='display:flex; gap:8px'>
<button id='editBtn' disabled onclick='openEditModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px; font-weight:600; cursor:not-allowed'>✏️ Edit</button>
<button id='deleteBtn' disabled onclick='openDeleteModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px; font-weight:600; cursor:not-allowed'>🗑️ Delete</button>
</div>
</div>
<table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>School</th><th style='padding:10px; text-align:left'>Contact</th><th style='padding:10px; text-align:left'>Location</th></tr>{rows_html}</table>
<div id='selectionInfo' style='margin-top:12px; padding:10px; background:#f8fafc; border-radius:8px; font-size:11px; color:#64748b; text-align:center'>👆 Select a school row to enable Edit / Delete</div>
</div>
<div style='background:white; {hl}; border-radius:12px; padding:20px; position:sticky; top:20px'>
<b>➕ Register New School</b>
<form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'>
<input name='school_name' placeholder='🏫 School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='school_email' placeholder='📧 Admin Email *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='location' placeholder='📍 Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='phone' placeholder='📱 Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='principal' placeholder='👨‍💼 Principal *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select>
<button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>✅ Create School</button>
<a href='/schools/manage' style='background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:13px; display:block'>❌ Cancel</a>
</form>
</div>
</div>

<div id='editModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'>
<div style='background:white; border-radius:16px; width:100%; max-width:480px; padding:24px'>
<div style='display:flex; justify-content:space-between; margin-bottom:16px'><b>✏️ Edit School</b><span onclick='closeEditModal()' style='cursor:pointer'>✖</span></div>
<p id='editCodeInfo' style='font-size:11px; color:#64748b; margin-bottom:12px'></p>
<form method='post' id='editForm' style='display:flex; flex-direction:column; gap:10px'>
<input name='school_name' id='edit_name' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='school_email' id='edit_email' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='location' id='edit_location' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='phone' id='edit_phone' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<input name='principal' id='edit_principal' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'>
<select name='school_type' id='edit_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select>
<button type='submit' style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>💾 Save Changes</button>
<div onclick='closeEditModal()' style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer'>❌ Cancel</div>
</form>
</div>
</div>

<div id='deleteModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'>
<div style='background:white; border-radius:16px; width:100%; max-width:380px; padding:24px; text-align:center'>
<div style='width:56px; height:56px; background:#fee2e2; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px; margin:0 auto 12px'>⚠️</div>
<h3 style='margin:0'>Delete School?</h3>
<p id='deleteInfo' style='font-size:13px; color:#64748b; margin:8px 0 16px'></p>
<div style='display:grid; grid-template-columns:1fr 1fr; gap:10px'>
<div onclick='closeDeleteModal()' style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer; font-weight:600'>❌ Cancel</div>
<a id='confirmDeleteBtn' href='#' style='background:#dc2626; color:white; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-weight:600'>🗑️ Yes, Delete</a>
</div>
</div>
</div>

<script>
let selectedId = null;
let schools = {schools_data};
function selectSchool(id) {{
    document.querySelectorAll('tr[id^="row-"]').forEach(r => {{ r.style.background='white'; r.style.borderLeft='none'; }});
    let row = document.getElementById('row-'+id);
    row.style.background='#dbeafe'; row.style.borderLeft='4px solid #2563eb';
    selectedId=id;
    let editBtn=document.getElementById('editBtn'); let deleteBtn=document.getElementById('deleteBtn');
    editBtn.disabled=false; deleteBtn.disabled=false;
    editBtn.style.background='#0f172a'; editBtn.style.color='white'; editBtn.style.cursor='pointer';
    deleteBtn.style.background='#dc2626'; deleteBtn.style.color='white'; deleteBtn.style.cursor='pointer';
    document.getElementById('selectionInfo').innerHTML='✅ Selected: <b>'+schools[id].name+'</b> ('+schools[id].code+')';
    document.getElementById('selectionInfo').style.background='#dbeafe'; document.getElementById('selectionInfo').style.color='#1e40af';
}}
function openEditModal() {{
    if(!selectedId) return;
    let s=schools[selectedId];
    document.getElementById('edit_name').value=s.name; document.getElementById('edit_email').value=s.email;
    document.getElementById('edit_location').value=s.location; document.getElementById('edit_phone').value=s.phone;
    document.getElementById('edit_principal').value=s.principal; document.getElementById('edit_type').value=s.school_type;
    document.getElementById('editCodeInfo').innerText='Code: '+s.code+' (cannot change)';
    document.getElementById('editForm').action='/schools/update/'+selectedId;
    document.getElementById('editModal').style.display='flex';
}}
function closeEditModal() {{ document.getElementById('editModal').style.display='none'; }}
function openDeleteModal() {{
    if(!selectedId) return;
    let s=schools[selectedId];
    document.getElementById('deleteInfo').innerHTML='Delete <b>'+s.name+'</b> ('+s.code+')?<br>This cannot be undone.';
    document.getElementById('confirmDeleteBtn').href='/schools/delete/'+selectedId;
    document.getElementById('deleteModal').style.display='flex';
}}
function closeDeleteModal() {{ document.getElementById('deleteModal').style.display='none'; }}
setTimeout(()=>{{ let b=document.getElementById('successBanner'); if(b) b.style.display='none'; }},5000);
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
