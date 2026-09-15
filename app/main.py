from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random, json
from datetime import datetime

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-activity-auto-v14")
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
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
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

def log_activity(email, action, details=""):
    try:
        con = get_db()
        cur = con.cursor()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO activity_log (email, action, details, timestamp) VALUES (?,?,?,?)", (email, action, details, ts))
        con.commit()
        con.close()
    except:
        pass

def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0 or req.session.get("role")=="super_admin":
        return None
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    s = cur.fetchone()
    con.close()
    return s

def header_html(initials, name, email):
    return f"""
    <div style='background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; position:relative'>
        <div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px; color:#64748b'>{name} • Super Admin</div></div>
        <div style='position:relative'>
            <div onclick='toggleProfileMenu()' style='width:36px; height:36px; background:#dbeafe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; cursor:pointer; border:2px solid #e2e8f0'>{initials}</div>
            <div id='profileDropdown' style='display:none; position:absolute; right:0; top:44px; background:white; border:1px solid #e2e8f0; border-radius:12px; width:220px; box-shadow:0 10px 25px rgba(0,0,0,0.12); z-index:1000; overflow:hidden'>
                <div style='padding:14px; border-bottom:1px solid #f1f5f9; background:#f8fafc'><div style='font-weight:700; font-size:13px'>{name}</div><div style='font-size:11px; color:#64748b'>{email}</div><div style='margin-top:6px'><span style='background:#e0f2fe; color:#0369a1; padding:3px 8px; border-radius:20px; font-size:10px'>Super Admin</span></div></div>
                <a href='/profile?tab=personal' style='display:flex; align-items:center; gap:10px; padding:11px 14px; text-decoration:none; color:#0f172a; font-size:13px; border-bottom:1px solid #f8fafc'>👤 Profile</a>
                <a href='/logout' style='display:flex; align-items:center; gap:10px; padding:11px 14px; text-decoration:none; color:#dc2626; font-size:13px'>🚪 Logout</a>
            </div>
        </div>
    </div>
    <script>
    function toggleProfileMenu(){{ let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none'; }}
    document.addEventListener('click', function(e){{ let b=e.target.closest('[onclick="toggleProfileMenu()"]'); let menu=document.getElementById('profileDropdown'); if(!b && menu &&!menu.contains(e.target)){{ menu.style.display='none'; }} }});
    </script>
    """

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'><div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px'><div style='text-align:center; margin-bottom:24px'><div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div><h2 style='margin:12px 0 4px'>Davischool</h2><p style='font-size:11px; color:#64748b'>SCHOOL MANAGEMENT SYSTEM</p></div><form method='post' action='/login'><input name='email' placeholder='Email' required style='width:100%; padding:12px; margin:6px 0 12px; border:1px solid #e2e8f0; border-radius:10px'><input name='password' type='password' placeholder='Password' required style='width:100%; padding:12px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px'><button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px'>Sign In</button></form></div></body></html>"""

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password))
    u = cur.fetchone()
    con.close()
    if not u:
        return HTMLResponse("Invalid <a href='/'>Back</a>")
    request.session["email"]=u["email"]
    request.session["role"]=u["role"]
    request.session["name"]=u["full_name"]
    request.session["school_id"]=u["school_id"] or 0
    log_activity(u["email"], "🔓 Logged in", f"Login from {u['email']}")
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
    name = request.session.get("name","Davis Ouma")
    email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    log_activity(email, "📊 Viewed dashboard", "School Overview")
    rows = ""
    for s in recent:
        rows += f"<tr><td style='padding:12px; border-bottom:1px solid #f1f5f9'>🏫 {s['name']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>📍 {s['location']}</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>✅ Active</td><td style='padding:12px; border-bottom:1px solid #f1f5f9'>Today</td></tr>"
    if not rows:
        rows = "<tr><td colspan=4 style='padding:20px; text-align:center; color:#999'>No schools yet</td></tr>"
    content = f"""
    <style>.quick-btn{{display:block; background:white; border:1px solid #e2e8f0; color:#0f172a; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600; transition:0.2s;}}.quick-btn:hover{{background:#0f172a; color:white;}}.quick-btn-light{{display:block; background:white; border:1px solid #e2e8f0; color:#64748b; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600; transition:0.2s;}}.quick-btn-light:hover{{background:#0f172a; color:white; border-color:#0f172a;}}</style>
    <div style='padding:24px'><div style='margin-bottom:20px'><h2 style='margin:0; font-size:22px; font-weight:800'>📊 School Overview</h2><p style='color:#64748b; font-size:13px'>Welcome {name}</p></div>
    <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div><div style='font-size:11px; color:#16a34a'>📈 Up 12%</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>✅ ACTIVE</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total}</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>💰 REVENUE</div><div style='font-size:28px; font-weight:800; margin-top:8px'>KES {total*15000:,}</div></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>🎓 STUDENTS</div><div style='font-size:28px; font-weight:800; margin-top:8px'>{total*350:,}</div></div>
    </div>
    <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden'><div style='padding:16px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><b>🏫 Recently Added Schools</b><a href='/schools/manage' style='font-size:12px; color:#2563eb; text-decoration:none'>View All →</a></div><table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>Name</th><th style='padding:10px; text-align:left'>Location</th><th style='padding:10px; text-align:left'>Status</th><th style='padding:10px; text-align:left'>Date</th></tr>{rows}</table></div>
    <div style='display:flex; flex-direction:column; gap:16px'><div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><b>⚡ Quick Actions</b><div style='margin-top:12px; display:flex; flex-direction:column; gap:8px'><a href='/schools/manage' class='quick-btn'>🏫 Manage Schools</a><a href='/schools/manage?show=add' class='quick-btn-light'>➕ Register New School</a></div></div><div style='background:#0f172a; border-radius:14px; padding:18px; color:white'><div style='font-size:13px; font-weight:700'>📊 Davischool Analytics</div><div style='font-size:11px; color:#94a3b8; margin-top:4px'>All {total} active</div><div style='margin-top:12px; background:#1e293b; border-radius:8px; padding:10px'><div style='font-size:10px; color:#94a3b8'>PLATFORM HEALTH</div><div style='font-size:18px; font-weight:700; color:#4ade80'>✅ 99.9% Uptime</div></div></div></div></div></div>
    """
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; margin:0; background:#f8fafc'>{header_html(initials, name, email)}{content}</body></html>")

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("email","")
    name = request.session.get("name","Davis Ouma")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    school_obj = get_school_obj(request)
    is_super = school_obj is None
    sname = "Davischool Platform" if is_super else school_obj["name"]
    scode = "SUPER-ADMIN" if is_super else school_obj["code"]
    sloc = "Platform Owner - Full System Control" if is_super else school_obj["location"]
    badge = "Super Admin" if is_super else "School Admin"

    log_activity(email, f"👀 Viewed profile tab: {tab}", f"{tab} tab")

    if tab=="security":
        right = f"""
        <div><b style='font-size:15px'>🔒 Security Settings</b><p style='font-size:11px; color:#64748b; margin-top:4px'>Manage your password</p>
        <form method='post' action='/update-password' style='margin-top:18px'>
            <label style='font-size:12px; font-weight:600; display:block; margin-top:14px'>🔑 Current Password</label>
            <input name='current_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
            <label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>🆕 New Password</label>
            <input name='new_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
            <label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>✅ Confirm New Password</label>
            <input name='confirm_password' type='password' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; margin-top:4px'>
            <div style='text-align:right; margin-top:16px'><button type='submit' style='background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:8px; font-weight:600'>🔐 Update Password</button></div>
        </form>
        </div>
        """
    elif tab=="activity":
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 50", (email,))
        logs = cur.fetchall()
        con.close()
        log_rows = ""
        icon_map = {
            "Logged in": "🔓", "dashboard": "📊", "profile": "👀", "Registered": "🏫",
            "Edited": "✏️", "Deleted": "🗑️", "Password": "🔑", "Updated profile": "👤"
        }
        for log in logs:
            action = log["action"]
            icon = "📌"
            for k,v in icon_map.items():
                if k.lower() in action.lower():
                    icon = v
                    break
            time_str = log["timestamp"]
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                time_display = dt.strftime("%b %d, %I:%M %p")
            except:
                time_display = time_str
            bg = "#f8fafc"
            if "Logged" in action: bg = "#e0f2fe"
            elif "Registered" in action: bg = "#dcfce7"
            elif "Edited" in action: bg = "#fef3c7"
            elif "Deleted" in action: bg = "#fee2e2"
            elif "Password" in action: bg = "#f3e8ff"
            log_rows += f"""
            <div style='padding:12px 14px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; align-items:center'>
                <div style='display:flex; align-items:center; gap:10px'>
                    <span style='width:32px; height:32px; background:{bg}; border-radius:8px; display:flex; align-items:center; justify-content:center; font-size:14px'>{icon}</span>
                    <div>
                        <div style='font-size:12px; font-weight:600'>{action}</div>
                        <div style='font-size:11px; color:#64748b'>{log["details"]}</div>
                    </div>
                </div>
                <span style='font-size:10px; color:#94a3b8; white-space:nowrap'>{time_display}</span>
            </div>
            """
        if not log_rows:
            log_rows = "<div style='padding:24px; text-align:center; color:#999; font-size:12px'>No activity yet — actions will appear here automatically</div>"

        right = f"""
        <div>
            <div style='display:flex; justify-content:space-between; align-items:center'><div><b style='font-size:15px'>📜 Activity Log</b><p style='font-size:11px; color:#64748b; margin-top:4px'>Live auto-updating — {len(logs)} events for {email}</p></div><a href='/clear-activity' onclick="return confirm('Clear all activity log?')" style='font-size:11px; color:#dc2626; border:1px solid #fecaca; padding:6px 10px; border-radius:6px; text-decoration:none'>Clear Log</a></div>
            <div style='border:1px solid #e2e8f0; border-radius:10px; margin-top:16px; overflow:hidden; max-height:500px; overflow-y:auto'>
                {log_rows}
            </div>
            <div style='margin-top:10px; font-size:10px; color:#94a3b8; text-align:center'>🔄 Automatically records every login, school add/edit/delete, profile view, password change</div>
        </div>
        """
    else:
        right = f"""
        <div><b style='font-size:15px'>👤 Personal Information</b><p style='font-size:11px; color:#64748b; margin-top:4px'>Update your personal details</p>
        <form method='post' action='/update-profile' style='margin-top:18px'>
            <label style='font-size:12px; font-weight:600; display:block; margin-top:14px'>👨‍💼 Full Name</label>
            <input name='full_name' value='{name}' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
            <label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>📧 Email Address</label>
            <input name='email_new' value='{email}' required style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
            <label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>📱 Phone Number</label>
            <input name='phone' value='+254748588874' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:4px'>
            <label style='font-size:12px; font-weight:600; display:block; margin-top:12px'>🏫 Organization</label>
            <input value='{sname}' disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f1f5f9; color:#64748b; margin-top:4px'>
            <div style='text-align:right; margin-top:20px'><button type='submit' style='background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:8px; font-weight:600'>💾 Save Changes</button></div>
        </form>
        </div>
        """

    ap = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="personal" else "color:#64748b; border-bottom:2px solid transparent"
    ase = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="security" else "color:#64748b; border-bottom:2px solid transparent"
    aa = "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700" if tab=="activity" else "color:#64748b; border-bottom:2px solid transparent"

    html = f"""
    <html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='margin:0; font-family:Arial; background:#f8fafc'>
    {header_html(initials, name, email)}
    <div style='padding:20px; max-width:1100px; margin:0 auto'>
        <div style='margin-bottom:16px'><h2 style='margin:0; font-size:20px; font-weight:800'>👤 My Profile</h2><p style='font-size:12px; color:#64748b; margin:4px 0 0'>Manage your personal information and security settings</p></div>
        <div style='display:flex; border-bottom:1px solid #e2e8f0; margin-bottom:20px; background:white; border-radius:10px 10px 0 0; padding:0 16px'>
            <a href='/profile?tab=personal' style='padding:14px 4px; margin-right:24px; text-decoration:none; font-size:13px; {ap}'>👤 Personal Info</a>
            <a href='/profile?tab=security' style='padding:14px 4px; margin-right:24px; text-decoration:none; font-size:13px; {ase}'>🔒 Security</a>
            <a href='/profile?tab=activity' style='padding:14px 4px; text-decoration:none; font-size:13px; {aa}'>📜 Activity Log</a>
        </div>
        <div style='display:grid; grid-template-columns:340px 1fr; gap:20px; align-items:start'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; text-align:center; position:sticky; top:20px'>
                <div style='width:88px; height:88px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px; font-weight:800; margin:0 auto'>{initials}</div>
                <div style='font-weight:700; margin-top:14px; font-size:16px'>{name}</div>
                <div style='margin-top:8px'><span style='background:#e0f2fe; color:#0369a1; padding:5px 12px; border-radius:20px; font-size:11px; font-weight:600'>{badge}</span></div>
                <div style='margin-top:12px; font-size:12px; color:#0f172a'>{email}</div>
                <div style='margin-top:16px; border-top:1px solid #f1f5f9; padding-top:16px; text-align:left'>
                    <div style='font-size:12px; font-weight:700'>{sname}</div>
                    <div style='font-size:11px; color:#64748b; margin-top:2px'>{sloc}</div>
                    <div style='font-size:10px; color:#94a3b8; margin-top:6px; background:#f8fafc; padding:6px 8px; border-radius:6px'>Code: {scode}</div>
                </div>
            </div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; min-height:400px'>
                {right}
            </div>
        </div>
    </div>
    </body></html>
    """
    return HTMLResponse(html)

@app.post("/update-password")
def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if "email" not in request.session:
        return RedirectResponse("/")
    if new_password!= confirm_password:
        return HTMLResponse("<h3>❌ New passwords do not match</h3><a href='/profile?tab=security'>Back</a>")
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
    log_activity(email, "🔑 Changed password", "Password updated successfully")
    return HTMLResponse("<h3>✅ Password Updated!</h3><a href='/profile?tab=security'>Back to Security</a> | <a href='/dashboard'>Dashboard</a>")

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
    log_activity(email_new.strip(), "👤 Updated profile", f"Name: {full_name} | Phone: {phone}")
    request.session["email"] = email_new.strip()
    request.session["name"] = full_name.strip()
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = "", success: str = ""):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/")
    name = request.session.get("name","")
    email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC")
    schools = cur.fetchall()
    con.close()
    log_activity(email, "🏫 Viewed schools management", f"{len(schools)} schools listed")
    success_banner = ""
    if success=="added":
        success_banner = "<div style='background:#dcfce7; border:1px solid #86efac; color:#166534; padding:12px 16px; border-radius:10px; margin-bottom:16px'>✅ <b>Success!</b> School registered successfully — Activity Log updated.</div>"
    elif success=="updated":
        success_banner = "<div style='background:#e0f2fe; border:1px solid #7dd3fc; color:#0c4a6e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>✅ <b>Updated!</b> School updated — Activity Log updated.</div>"
    elif success=="deleted":
        success_banner = "<div style='background:#fee2e2; border:1px solid #fca5a5; color:#991b1b; padding:12px 16px; border-radius:10px; margin-bottom:16px'>🗑️ <b>Deleted!</b> School removed — Activity Log updated.</div>"
    rows_html = ""
    schools_json = {}
    for s in schools:
        sid = s["id"]
        schools_json[sid] = {"id": sid, "name": s["name"], "email": s["email"], "code": s["code"], "location": s["location"], "phone": s["phone"] or "", "principal": s["principal"] or "", "school_type": s["school_type"] or ""}
        rows_html += f"<tr id='row-{sid}' onclick='selectSchool({sid})' style='cursor:pointer'><td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#64748b'>{s['code']}</div></td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📧 {s['email']}</td><td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📍 {s['location']}</td></tr>"
    if not rows_html:
        rows_html = "<tr><td colspan=3 style='padding:24px; text-align:center; color:#999'>No schools yet</td></tr>"
    schools_data = json.dumps(schools_json)
    hl = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"
    return HTMLResponse(f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Arial; background:#f8fafc; margin:0'>
{header_html(initials, name, email)}
<div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'>
<div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px'>
{success_banner}
<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px'><div><b>📚 Registered Schools ({len(schools)})</b><div style='font-size:11px; color:#64748b'>Click row — highlights blue</div></div><div style='display:flex; gap:8px'><button id='editBtn' disabled onclick='openEditModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px; font-weight:600'>✏️ Edit</button><button id='deleteBtn' disabled onclick='openDeleteModal()' style='background:#e5e7eb; color:#9ca3af; padding:8px 14px; border:none; border-radius:8px; font-size:12px; font-weight:600'>🗑️ Delete</button></div></div>
<table style='width:100%; border-collapse:collapse'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>School</th><th style='padding:10px; text-align:left'>Contact</th><th style='padding:10px; text-align:left'>Location</th></tr>{rows_html}</table>
<div id='selectionInfo' style='margin-top:12px; padding:10px; background:#f8fafc; border-radius:8px; font-size:11px; color:#64748b; text-align:center'>👆 Select a school row to enable Edit / Delete</div>
</div>
<div style='background:white; {hl}; border-radius:12px; padding:20px; position:sticky; top:20px'><b>➕ Register New School</b><form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='school_name' placeholder='🏫 School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' placeholder='📧 Admin Email *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' placeholder='📍 Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' placeholder='📱 Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' placeholder='👨‍💼 Principal *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>✅ Create School</button><a href='/schools/manage' style='background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:13px; display:block'>❌ Cancel</a></form></div>
</div>
<div id='editModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'><div style='background:white; border-radius:16px; width:100%; max-width:480px; padding:24px'><div style='display:flex; justify-content:space-between; margin-bottom:16px'><b>✏️ Edit School</b><span onclick='closeEditModal()' style='cursor:pointer'>✖</span></div><p id='editCodeInfo' style='font-size:11px; color:#64748b; margin-bottom:12px'></p><form method='post' id='editForm' style='display:flex; flex-direction:column; gap:10px'><input name='school_name' id='edit_name' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' id='edit_email' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' id='edit_location' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' id='edit_phone' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' id='edit_principal' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' id='edit_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button type='submit' style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>💾 Save Changes</button><div onclick='closeEditModal()' style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer'>❌ Cancel</div></form></div></div>
<div id='deleteModal' style='display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); z-index:9999; justify-content:center; align-items:center; padding:20px'><div style='background:white; border-radius:16px; width:100%; max-width:380px; padding:24px; text-align:center'><div style='width:56px; height:56px; background:#fee2e2; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px; margin:0 auto 12px'>⚠️</div><h3 style='margin:0'>Delete School?</h3><p id='deleteInfo' style='font-size:13px; color:#64748b; margin:8px 0 16px'></p><div style='display:grid; grid-template-columns:1fr 1fr; gap:10px'><div onclick='closeDeleteModal()' style='background:white; border:1px solid #e2e8f0; padding:11px; border-radius:8px; text-align:center; cursor:pointer; font-weight:600'>❌ Cancel</div><a id='confirmDeleteBtn' href='#' style='background:#dc2626; color:white; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-weight:600'>🗑️ Yes, Delete</a></div></div></div>
<script>
let selectedId=null; let schools={schools_data};
function selectSchool(id){{document.querySelectorAll('tr[id^="row-"]').forEach(r=>{{r.style.background='white';}}); document.getElementById('row-'+id).style.background='#dbeafe'; selectedId=id; let e=document.getElementById('editBtn'); let d=document.getElementById('deleteBtn'); e.disabled=false; d.disabled=false; e.style.background='#0f172a'; e.style.color='white'; e.style.cursor='pointer'; d.style.background='#dc2626'; d.style.color='white'; d.style.cursor='pointer'; document.getElementById('selectionInfo').innerHTML='✅ Selected: <b>'+schools[id].name+'</b>';}}
function openEditModal(){{if(!selectedId)return; let s=schools[selectedId]; document.getElementById('edit_name').value=s.name; document.getElementById('edit_email').value=s.email; document.getElementById('edit_location').value=s.location; document.getElementById('edit_phone').value=s.phone; document.getElementById('edit_principal').value=s.principal; document.getElementById('edit_type').value=s.school_type; document.getElementById('editCodeInfo').innerText='Code: '+s.code; document.getElementById('editForm').action='/schools/update/'+selectedId; document.getElementById('editModal').style.display='flex';}}
function closeEditModal(){{document.getElementById('editModal').style.display='none';}}
function openDeleteModal(){{if(!selectedId)return; let s=schools[selectedId]; document.getElementById('deleteInfo').innerHTML='Delete <b>'+s.name+'</b>? Cannot be undone.'; document.getElementById('confirmDeleteBtn').href='/schools/delete/'+selectedId; document.getElementById('deleteModal').style.display='flex';}}
function closeDeleteModal(){{document.getElementById('deleteModal').style.display='none';}}
</script>
</body></html>
""")

@app.post("/schools/update/{school_id}")
def update_school(school_id: int, school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...), request: Request = None):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT name FROM schools WHERE id=?", (school_id,))
    old = cur.fetchone()
    old_name = old["name"] if old else "Unknown"
    cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, school_id))
    cur.execute("UPDATE users SET email=?, full_name=? WHERE school_id=?", (school_email.strip(), principal.strip(), school_id))
    con.commit()
    con.close()
    email = request.session.get("email","") if request else ""
    log_activity(email, f"✏️ Edited school: {school_name}", f"From {old_name} to {school_name} | {school_type}")
    return RedirectResponse("/schools/manage?success=updated", status_code=303)

@app.get("/schools/delete/{school_id}")
def delete_school(school_id: int, request: Request):
    if request.session.get("role")!= "super_admin":
        return RedirectResponse("/")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT name, code FROM schools WHERE id=?", (school_id,))
    s = cur.fetchone()
    sname = s["name"] if s else "Unknown"
    scode = s["code"] if s else ""
    cur.execute("DELETE FROM schools WHERE id=?", (school_id,))
    cur.execute("DELETE FROM users WHERE school_id=?", (school_id,))
    con.commit()
    con.close()
    email = request.session.get("email","")
    log_activity(email, f"🗑️ Deleted school: {sname}", f"Code: {scode} removed with admin login")
    return RedirectResponse("/schools/manage?success=deleted", status_code=303)

@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...), request: Request = None):
    code = str(random.randint(10000,99999))
    con = get_db()
    cur = con.cursor()
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), code, location.strip(), phone.strip(), principal.strip(), school_type))
    sid = cur.lastrowid
    cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (school_email.strip(), "School@2026!", "school_admin", f"{principal.strip() or 'School Admin'}", sid))
    con.commit()
    con.close()
    email = request.session.get("email","") if request else SUPER_ADMIN
    # need to get from request session manually
    try:
        if request:
            email = request.session.get("email", SUPER_ADMIN)
    except:
        email = SUPER_ADMIN
    log_activity(email, f"🏫 Registered new school: {school_name}", f"Code: {code} | Type: {school_type} | Location: {location} | Principal: {principal}")
    return RedirectResponse("/schools/manage?success=added", status_code=303)

@app.get("/clear-activity")
def clear_activity(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    email = request.session.get("email")
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM activity_log WHERE email=?", (email,))
    con.commit()
    con.close()
    log_activity(email, "🧹 Cleared activity log", "All previous logs deleted")
    return RedirectResponse("/profile?tab=activity", status_code=303)

@app.get("/logout")
def logout(request: Request):
    email = request.session.get("email","")
    if email:
        log_activity(email, "🚪 Logged out", "Session ended")
    request.session.clear()
    return RedirectResponse("/", status_code=303)
