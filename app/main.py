from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random
from datetime import datetime
from zoneinfo import ZoneInfo

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v61-record-marks-exact-3parts")
SUPER_ADMIN = "oumadavis62@gmail.com"

def get_db():
    con = sqlite3.connect("davischool.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, email TEXT, code TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT, full_name TEXT, school_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pending_schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, location TEXT, phone TEXT, principal TEXT, school_type TEXT, auth_code TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, level TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, admission_no TEXT, assessment_no TEXT, name TEXT, class_id INTEGER, gender TEXT, parent_phone TEXT, stream TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, code TEXT, initial TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year TEXT, exam_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY, school_id INTEGER, term_name TEXT, year TEXT, start_date TEXT, end_date TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, email TEXT, phone TEXT, tsc_no TEXT, gender TEXT, id_no TEXT, role TEXT, employment_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS teacher_allocations (id INTEGER PRIMARY KEY, school_id INTEGER, teacher_id INTEGER, subject_id INTEGER, class_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS global_notices (id INTEGER PRIMARY KEY, message TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS system_audit (id INTEGER PRIMARY KEY, school_id INTEGER, user_email TEXT, action TEXT, details TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS billing (id INTEGER PRIMARY KEY, school_id INTEGER, amount TEXT, status TEXT, due_date TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, subject_id INTEGER, exam_id INTEGER, class_id INTEGER, marks REAL, year TEXT, term TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS set_marks_config (id INTEGER PRIMARY KEY, school_id INTEGER, subject_id INTEGER, class_name TEXT, stream TEXT, year TEXT, term TEXT, exam_id INTEGER, out_of INTEGER, created_at TEXT)")
    try: cur.execute("ALTER TABLE teachers ADD COLUMN employment_type TEXT")
    except: pass
    try: cur.execute("ALTER TABLE students ADD COLUMN category TEXT")
    except: pass
    try: cur.execute("ALTER TABLE students ADD COLUMN guardian_name TEXT")
    except: pass
    cur.execute("SELECT * FROM users WHERE email=?", (SUPER_ADMIN,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (SUPER_ADMIN,"DaviSchool@2026!","super_admin","Davis Ouma",0))
    con.commit(); con.close()
init_db()

def get_school_obj(req):
    sid = req.session.get("school_id",0)
    if sid==0: return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (sid,))
    s = cur.fetchone(); con.close(); return s

def generate_unique_password(name):
    p = "".join([c for c in name.upper() if c.isalpha()])[:4]
    if len(p)<3: p="SCH"
    return f"{p}@{random.randint(1000,9999)}!"

def header_html(initials, name, email):
    return f"""<style>.do-avatar{{width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #e2e8f0}}.dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#0f172a;color:white}}</style><div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px;color:#64748b'>{name} • Super Admin</div></div><div style='position:relative'><div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div><div id='profileDropdown' style='display:none;position:absolute;right:0;top:44px;background:white;border:1px solid #e2e8f0;border-radius:12px;width:220px;box-shadow:0 10px 25px rgba(0,0,0,0.12);z-index:1000;overflow:hidden'><div style='padding:14px;border-bottom:1px solid #f1f5f9;background:#f8fafc'><div style='font-weight:700;font-size:13px'>{name}</div><div style='font-size:11px;color:#64748b'>{email}</div></div><a href='/super/global-control/dashboard' class='dropdown-item' style='color:#0f172a'>🌍 Global Control</a><a href='/logout' class='dropdown-item' style='color:#dc2626'>🚪 Logout</a></div></div></div><script>function toggleProfileMenu(){{let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none';}}</script>"""

def school_header(school, name, active="dashboard", is_impersonating=False):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    academic_pages = ["dean-settings","exams","marks","set-marks","subject-allocation","record-marks","edit-marks","marksheets","marks-status","analysis","spreadsheet","sba"]
    comm_pages = ["sms","communication","announcements","bulk-sms"]
    system_pages = ["system-settings","school-profile","system-classes","user-management","roles-permissions","database-backup","system-audit","integrations","billing-payments","my-profile","user-manual"]
    is_academic_active = active in academic_pages or active.startswith("marks") or active.startswith("set-marks")
    is_comm_active = active in comm_pages
    is_system_active = active in system_pages or str(active).startswith("system-settings")
    acad_display = "block" if is_academic_active else "none"
    comm_display = "block" if is_comm_active else "none"
    sys_display = "block" if is_system_active else "none"
    acad_arrow = "⌃" if is_academic_active else "⌄"
    comm_arrow = "⌃" if is_comm_active else "⌄"
    sys_arrow = "⌃" if is_system_active else "⌄"
    acad_bg = "background:#0f172a;color:white" if is_academic_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    comm_bg = "background:#0f172a;color:white" if is_comm_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    sys_bg = "background:#0f172a;color:white" if is_system_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    def nav(link, icon, label):
        is_active = "background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569;background:transparent"
        return f"<a href='/school/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active}'>{icon} {label}</a>"
    def sub_nav(link, icon, label):
        is_sel = "background:#e2e8f0;color:#0f172a;font-weight:800;border-radius:8px" if active==link else "color:#475569"
        return f"<a href='/school/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:2px;{is_sel}'>{icon} {label}</a>"
    banner = f"""<div style='background:#f59e0b;color:#0f172a;padding:8px 20px;text-align:center;font-weight:800;font-size:12px'>⚠️ Viewing as {school['name']} — <a href='/super/back-to-admin' style='background:#0f172a;color:white;padding:6px 12px;border-radius:8px;text-decoration:none;font-size:11px'>🔙 Back to Super Admin</a></div>""" if is_impersonating else ""
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 1"); notice = cur.fetchone(); con.close()
    notice_banner = f"""<div style='background:#0f172a;color:white;padding:8px 20px;text-align:center;font-size:12px'>📢 {notice['message']}</div>""" if notice else ""
    return f"""<style>.nav-item:hover{{background:#f1f5f9!important;color:#0f172a!important}}.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.section-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:800;margin-bottom:4px}}.academic-header{{ {acad_bg} }}.comm-header{{ {comm_bg} }}.system-header{{ {sys_bg} }}.section-header:hover{{background:#f1f5f9!important}}</style><div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20].upper()}</b><div style='font-size:10px;color:#64748b'>🔑 {school['code']} | {school['location']}</div></div></div></div>{nav('dashboard','📊','School Overview')}{nav('students','🎓','Students Manager')}{nav('classes','🏫','Classes & Streams')}<div style='margin-bottom:4px'><div class='section-header academic-header' onclick='toggleAcademic()'><span>📖 Academic Manager</span><span id='academicArrow'>{acad_arrow}</span></div><div id='academicDropdown' style='display:{acad_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('dean-settings','⚙️','Dean Settings')}{sub_nav('exams','🔧','Exam Settings')}{sub_nav('set-marks','📄','Set Marks')}{sub_nav('subject-allocation','📋','Subject Allocation')}{sub_nav('record-marks','✏️','Record Marks')}{sub_nav('edit-marks','📄','Edit Marks')}{sub_nav('marksheets','☰','Marks Status')}{sub_nav('analysis','📊','Exam Analysis')}{sub_nav('spreadsheet','📄','Spreadsheet')}{sub_nav('sba','📋','SBA (KNEC CBA)')}</div></div>{nav('teachers','👨‍🏫','Staff Manager')}{nav('timetable','🗓️','Smart Timetable')}{nav('fees','💰','Fees & Finance')}<div style='margin-bottom:4px'><div class='section-header comm-header' onclick='toggleComm()'><span>💬 Communication</span><span id='commArrow'>{comm_arrow}</span></div><div id='commDropdown' style='display:{comm_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('sms','💬','Bulk SMS Parents')}{sub_nav('communication','📢','Announcements')}</div></div><div style='margin-bottom:4px;margin-top:6px'><div class='section-header system-header' onclick='toggleSystem()'><span>⚙️ System Settings</span><span id='systemArrow'>{sys_arrow}</span></div><div id='systemDropdown' style='display:{sys_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('system-settings/school-profile','🏢','School Profile')}{sub_nav('system-settings/classes','🏫','Classes')}{sub_nav('system-settings/user-management','👤+','User Management')}{sub_nav('system-settings/roles-permissions','🛡️','Roles & Permissi...')}{sub_nav('system-settings/database-backup','💾','Database Backup')}{sub_nav('system-settings/system-audit','📈','System Audit')}{sub_nav('system-settings/integrations','🔌','Integrations')}{sub_nav('system-settings/billing-payments','💳','Billing & Payments')}</div></div>{nav('my-profile','👤','My Profile')}<div style='margin-top:12px;padding-top:12px;border-top:1px solid #f1f5f9'><div style='font-size:11px;color:#94a3b8;font-weight:700;margin-bottom:8px'>Help</div>{nav('user-manual','❓','User Manual')}<div style='margin-top:12px;padding:10px;background:#f8fafc;border-radius:10px;border:1px solid #f1f5f9'><div style='font-size:12px;font-weight:700'>{name}</div><div style='font-size:10px;color:#64748b'>{school['email']}</div><div style='margin-top:8px;font-size:11px'>🌤️ 24°C<br><span style='color:#64748b'>Mostly cloudy</span></div></div></div><div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/logout' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'>{banner}{notice_banner}<div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>{school['name']} (Code: {school['code']})</b></div><div style='display:flex;align-items:center;gap:12px'><div style='width:28px;height:28px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px'>{initials}</div><div style='font-size:11px'><b>{name}</b></div></div></div><script>function toggleAcademic(){{let d=document.getElementById('academicDropdown'); let a=document.getElementById('academicArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}function toggleComm(){{let d=document.getElementById('commDropdown'); let a=document.getElementById('commArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}function toggleSystem(){{let d=document.getElementById('systemDropdown'); let a=document.getElementById('systemArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}</script>"""

def global_header(name, active="dashboard"):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    academic_pages = ["dean-settings","exams","marks","set-marks","subject-allocation","record-marks","edit-marks","marksheets","marks-status","analysis","spreadsheet","sba"]
    comm_pages = ["sms","communication","announcements"]
    system_pages = ["system-settings","school-profile","system-classes","user-management","roles-permissions","database-backup","system-audit","integrations","billing-payments","my-profile","user-manual"]
    is_academic_active = active in academic_pages or active.startswith("marks") or active.startswith("set-marks")
    is_comm_active = active in comm_pages
    is_system_active = active in system_pages or str(active).startswith("system-settings")
    acad_display = "block" if is_academic_active else "none"
    comm_display = "block" if is_comm_active else "none"
    sys_display = "block" if is_system_active else "none"
    acad_arrow = "⌃" if is_academic_active else "⌄"
    comm_arrow = "⌃" if is_comm_active else "⌄"
    sys_arrow = "⌃" if is_system_active else "⌄"
    acad_bg = "background:#0f172a;color:white" if is_academic_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    comm_bg = "background:#0f172a;color:white" if is_comm_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    sys_bg = "background:#0f172a;color:white" if is_system_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    def nav(link, icon, label):
        is_active = "background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569;background:transparent"
        return f"<a href='/super/global-control/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active}'>{icon} {label}</a>"
    def sub_nav(link, icon, label):
        is_sel = "background:#e2e8f0;color:#0f172a;font-weight:800;border-radius:8px" if active==link else "color:#475569"
        return f"<a href='/super/global-control/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:2px;{is_sel}'>{icon} {label}</a>"
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 1"); notice = cur.fetchone(); con.close()
    notice_banner = f"""<div style='background:#0f172a;color:white;padding:8px 20px;text-align:center;font-size:12px'>📢 {notice['message']}</div>""" if notice else ""
    return f"""<style>.nav-item:hover{{background:#f1f5f9!important;color:#0f172a!important}}.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.section-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:800;margin-bottom:4px}}.academic-header{{ {acad_bg} }}.comm-header{{ {comm_bg} }}.system-header{{ {sys_bg} }}.section-header:hover{{background:#f1f5f9!important}}</style><div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🌍</div><div><b style='font-size:13px'>GLOBAL CONTROL</b><div style='font-size:10px;color:#64748b'>ALL SCHOOLS • Automatic</div></div></div></div>{nav('dashboard','📊','School Overview')}{nav('students','🎓','Students Manager')}{nav('classes','🏫','Classes & Streams')}<div style='margin-bottom:4px'><div class='section-header academic-header' onclick='toggleAcademic()'><span>📖 Academic Manager</span><span id='academicArrow'>{acad_arrow}</span></div><div id='academicDropdown' style='display:{acad_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('dean-settings','⚙️','Dean Settings')}{sub_nav('exams','🔧','Exam Settings')}{sub_nav('set-marks','📄','Set Marks')}{sub_nav('subject-allocation','📋','Subject Allocation')}{sub_nav('record-marks','✏️','Record Marks')}{sub_nav('edit-marks','📄','Edit Marks')}{sub_nav('marksheets','☰','Marks Status')}{sub_nav('analysis','📊','Exam Analysis')}{sub_nav('spreadsheet','📄','Spreadsheet')}{sub_nav('sba','📋','SBA (KNEC CBA)')}</div></div>{nav('teachers','👨‍🏫','Staff Manager')}{nav('timetable','🗓️','Smart Timetable')}{nav('fees','💰','Fees & Finance')}<div style='margin-bottom:4px'><div class='section-header comm-header' onclick='toggleComm()'><span>💬 Communication</span><span id='commArrow'>{comm_arrow}</span></div><div id='commDropdown' style='display:{comm_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('sms','💬','Bulk SMS Parents')}{sub_nav('communication','📢','Announcements')}</div></div><div style='margin-bottom:4px;margin-top:6px'><div class='section-header system-header' onclick='toggleSystem()'><span>⚙️ System Settings</span><span id='systemArrow'>{sys_arrow}</span></div><div id='systemDropdown' style='display:{sys_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('system-settings/school-profile','🏢','School Profile')}{sub_nav('system-settings/classes','🏫','Classes')}{sub_nav('system-settings/user-management','👤+','User Management')}{sub_nav('system-settings/roles-permissions','🛡️','Roles & Permissi...')}{sub_nav('system-settings/database-backup','💾','Database Backup')}{sub_nav('system-settings/system-audit','📈','System Audit')}{sub_nav('system-settings/integrations','🔌','Integrations')}{sub_nav('system-settings/billing-payments','💳','Billing & Payments')}</div></div>{nav('my-profile','👤','My Profile')}<div style='margin-top:12px;padding-top:12px;border-top:1px solid #f1f5f9'><div style='font-size:11px;color:#94a3b8;font-weight:700;margin-bottom:8px'>Help</div>{nav('user-manual','❓','User Manual')}<div style='margin-top:14px;padding:10px;background:#f8fafc;border-radius:10px;border:1px solid #f1f5f9'><div style='display:flex;gap:8px;align-items:center'><div style='width:28px;height:28px;background:#0f172a;color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800'>DO</div><div><div style='font-size:12px;font-weight:800'>{name}</div><div style='font-size:10px;color:#64748b'>Super Admin</div></div></div><div style='margin-top:10px;font-size:12px'>🌤️ 24°C<br><span style='color:#64748b'>Mostly cloudy</span></div></div></div><div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/dashboard' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#0f172a;background:#f8fafc;font-weight:700'>⬅️ Back to Super Admin</a><a href='/logout' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'>{notice_banner}<div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>GLOBAL CONTROL (ALL SCHOOLS)</b><div style='font-size:10px;color:#64748b'>Any change here updates all schools instantly</div></div><div style='display:flex;align-items:center;gap:12px'><div style='width:28px;height:28px;background:#0f172a;color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px'>{initials}</div><div style='font-size:11px'><b>{name}</b> <span style="background:#0f172a;color:white;padding:2px 6px;border-radius:6px;font-size:9px">SUPER</span></div></div></div><script>function toggleAcademic(){{let d=document.getElementById('academicDropdown'); let a=document.getElementById('academicArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}function toggleComm(){{let d=document.getElementById('commDropdown'); let a=document.getElementById('commArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}function toggleSystem(){{let d=document.getElementById('systemDropdown'); let a=document.getElementById('systemArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}</script>"""

def staff_manager_html(teachers, school_name, is_global=False):
    total = len(teachers)
    male = len([t for t in teachers if (t['gender'] or '').lower().startswith('m')])
    female = total - male
    teaching_roles = ['teacher','classteacher','principal','deputy principal']
    teaching = len([t for t in teachers if (t['role'] or '').lower() in teaching_roles])
    non_teaching = total - teaching
    from collections import Counter
    role_counter = Counter([(t['role'] or 'Unknown') for t in teachers])
    role_pills = "".join([f"<span style='border:1px solid #e2e8f0;background:white;padding:4px 10px;border-radius:16px;font-size:12px;font-weight:600;margin-right:6px;display:inline-block;margin-bottom:6px'>{r}: {c}</span>" for r,c in role_counter.items()]) or "<span style='font-size:12px;color:#94a3b8'>No roles yet</span>"
    rows_html = ""
    for i, t in enumerate(teachers, 1):
        delete_url = f"/super/global-control/teachers/delete/{t['id']}" if is_global else f"/school/teachers/delete/{t['id']}"
        rows_html += f"""<tr class='staff-row' data-role="{(t['role'] or '').lower()}" data-gender="{(t['gender'] or '').lower()}" data-employment="{(t['employment_type'] or ('teaching' if (t['role'] or '').lower() in teaching_roles else 'non-teaching')).lower()}" data-search="{(t['name'] or '').lower()} {(t['id_no'] or '').lower()} {(t['email'] or '').lower()} {(t['tsc_no'] or '').lower()}"><td style='padding:14px 12px;font-size:13px'>{i}</td><td style='padding:14px 12px;font-size:13px;font-weight:600'>{t['id_no'] or t['tsc_no'] or '—'}</td><td style='padding:14px 12px;font-size:13px;font-weight:700'>{t['name']}</td><td style='padding:14px 12px;font-size:13px'>{t['gender'] or '—'}</td><td style='padding:14px 12px;font-size:13px'><span style='background:#f1f5f9;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700'>{t['role'] or 'Teacher'}</span></td><td style='padding:14px 12px;font-size:13px'>{t['phone'] or '—'}</td><td style='padding:14px 12px;font-size:13px;color:#475569'>{t['email'] or '—'}</td><td style='padding:14px 12px'><a href='{delete_url}' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:8px;text-decoration:none;font-size:12px'>🗑️</a></td></tr>"""
    if not rows_html:
        rows_html = "<tr><td colspan='8' style='padding:40px;text-align:center;color:#94a3b8'>No staff yet</td></tr>"
    add_action = "/super/global-control/teachers/add" if is_global else "/school/teachers/add"
    return f"""<style>.staff-card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px;display:flex;justify-content:space-between;align-items:center}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;min-width:140px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-staff-btn{{background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:20px}}.modal.active{{display:flex}}</style><div style='padding:22px;max-width:1500px;margin:auto'><div style='margin-bottom:18px'><h1 style='margin:0;font-size:28px;font-weight:900'>Staff</h1><p style='margin:6px 0 0;color:#64748b;font-size:14px'>Manage staff records — {school_name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px'><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Total Staff</div><div style='font-size:28px;font-weight:900;margin-top:8px'>{total}</div></div></div><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Male / Female</div><div style='font-size:24px;font-weight:900;margin-top:8px'><span style='color:#2563eb'>{male}</span> / <span style='color:#db2777'>{female}</span></div></div></div><div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Teaching / Non-Teaching</div><div style='font-size:24px;font-weight:900;margin-top:8px'><span style='color:#059669'>{teaching}</span> / <span style='color:#ea580c'>{non_teaching}</span></div></div></div><div class='staff-card' style='flex-direction:column;align-items:flex-start'><div style='font-size:13px;color:#64748b;font-weight:600;margin-bottom:10px'>By Role</div><div>{role_pills}</div></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center'><input id='searchInput' onkeyup='filterStaff()' placeholder='Search name, ID, email.' style='padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;min-width:200px'><select id='roleFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Roles</option><option value='administrator'>Administrator</option><option value='principal'>Principal</option><option value='deputy principal'>Deputy Principal</option><option value='classteacher'>Classteacher</option><option value='teacher'>Teacher</option></select><select id='genderFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Gender</option><option value='male'>Male</option><option value='female'>Female</option></select><select id='employmentFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Employment</option><option value='teaching'>Teaching</option><option value='non-teaching'>Non-Teaching</option></select><button class='action-btn' onclick='exportCSV()'>📄 CSV</button><button class='action-btn' onclick='window.print()'>⬇️ PDF</button><button class='add-staff-btn' onclick='openModal()'>+ Add Staff</button></div><div style='overflow:auto;max-height:65vh'><table id='staffTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:12px;color:#64748b;border-top:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9'><th style='padding:12px'>#</th><th style='padding:12px'>NATIONAL ID</th><th style='padding:12px'>NAME</th><th style='padding:12px'>GENDER</th><th style='padding:12px'>ROLE</th><th style='padding:12px'>PHONE</th><th style='padding:12px'>EMAIL</th><th style='padding:12px'>ACTIONS</th></tr></thead><tbody>{rows_html}</tbody></table></div></div></div><div id='addStaffModal' class='modal'><div style='background:white;border-radius:16px;width:520px;max-width:95%;max-height:90vh;overflow:auto'><div style='padding:20px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>➕ Add Staff</b><span onclick='closeModal()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_action}' style='padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:12px'><div style='grid-column:span 2'><input name='name' required placeholder='Full Name *' class='input-field'></div><div><input name='id_no' required placeholder='National ID *' class='input-field'></div><div><input name='tsc_no' placeholder='TSC No' class='input-field'></div><div><select name='gender' required class='input-field'><option value='Male'>Male</option><option value='Female'>Female</option></select></div><div><select name='role' required class='input-field'><option value='Teacher'>Teacher</option><option value='Classteacher'>Classteacher</option><option value='Principal'>Principal</option><option value='Deputy Principal'>Deputy Principal</option><option value='Administrator'>Administrator</option></select></div><div><select name='employment_type' required class='input-field'><option value='Teaching'>Teaching</option><option value='Non-Teaching'>Non-Teaching</option></select></div><div><input name='phone' required placeholder='Phone *' class='input-field'></div><div style='grid-column:span 2'><input name='email' placeholder='Email' class='input-field'></div><div style='grid-column:span 2'><button class='add-btn'>➕ Add Staff</button></div></form></div></div><script>function openModal(){{document.getElementById('addStaffModal').classList.add('active');}}function closeModal(){{document.getElementById('addStaffModal').classList.remove('active');}}function filterStaff(){{let s=document.getElementById('searchInput').value.toLowerCase();let r=document.getElementById('roleFilter').value.toLowerCase();let g=document.getElementById('genderFilter').value.toLowerCase();let e=document.getElementById('employmentFilter').value.toLowerCase();document.querySelectorAll('.staff-row').forEach(row=>{{let ok=row.getAttribute('data-search').includes(s);if(r!=='all'&&!row.getAttribute('data-role').includes(r))ok=false;if(g!=='all'&&!row.getAttribute('data-gender').includes(g))ok=false;if(e!=='all'&&!row.getAttribute('data-employment').includes(e))ok=false;row.style.display=ok?'':'none';}});}}function exportCSV(){{let rows=document.querySelectorAll('#staffTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i<7)d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}});csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='staff_{school_name}.csv';a.click();}}</script>"""

def students_manager_html(students, classes_list, school_name, is_global=False):
    total = len(students)
    male = len([s for s in students if (s['gender'] or '').lower().startswith('m')])
    female = total - male
    boarding = len([s for s in students if (s['category'] or 'Day').lower().startswith('b')])
    day = total - boarding
    from collections import Counter
    class_counter = Counter([(s['class_name'] or 'UNASSIGNED') for s in students])
    class_pills = "".join([f"<span style='border:1px solid #e2e8f0;background:white;padding:4px 10px;border-radius:16px;font-size:11px;font-weight:600;margin-right:6px;display:inline-block;margin-bottom:6px'>{k}: {v}</span>" for k,v in class_counter.items()]) or "<span style='font-size:11px;color:#94a3b8'>No classes yet</span>"
    class_filter_opts = "<option value='all'>All Classes</option>"
    for c in classes_list:
        label = f"{c['name']} {c['stream'] or ''}".strip()
        class_filter_opts += f"<option value='{label.lower()}'>{label}</option>"
    rows_html = ""
    for i, st in enumerate(students, 1):
        del_url = f"/super/global-control/students/delete/{st['id']}" if is_global else f"/school/students/delete/{st['id']}"
        cname = st['class_name'] or '—'
        cat = st['category'] or 'Day'
        guardian = st['guardian_name'] or '—'
        phone = st['parent_phone'] or '—'
        adm = st['admission_no'] or st['assessment_no'] or '—'
        rows_html += f"""<tr class='stu-row' data-class="{cname.lower()}" data-gender="{(st['gender'] or '').lower()}" data-category="{cat.lower()}" data-search="{(st['name'] or '').lower()} {adm.lower()} {guardian.lower()} {cname.lower()}"><td style='padding:12px 10px;font-size:12px'>{i}</td><td style='padding:12px 10px;font-size:12px;font-weight:600'>{adm}</td><td style='padding:12px 10px;font-size:12px;font-weight:700'>{st['name']}</td><td style='padding:12px 10px;font-size:12px'>{st['gender'] or '—'}</td><td style='padding:12px 10px;font-size:12px'><span style='background:#f1f5f9;padding:3px 8px;border-radius:10px;font-size:11px'>{cname}</span></td><td style='padding:12px 10px;font-size:12px'>{cat}</td><td style='padding:12px 10px;font-size:12px'>{guardian}</td><td style='padding:12px 10px;font-size:12px'>{phone}</td><td style='padding:12px 10px'><a href='{del_url}' style='background:#fee2e2;color:#991b1b;padding:5px 8px;border-radius:7px;text-decoration:none;font-size:11px'>🗑️</a></td></tr>"""
    if not rows_html:
        rows_html = "<tr><td colspan='9' style='padding:40px;text-align:center;color:#94a3b8'>No pupils yet</td></tr>"
    add_action = "/super/global-control/students/add" if is_global else "/school/students/add"
    class_opts_form = "".join([f"<option value='{c['id']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes_list])
    return f"""<style>.stu-card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px;display:flex;justify-content:space-between;align-items:center}}.filter-select{{padding:9px 11px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:12px;min-width:130px}}.action-btn{{padding:9px 12px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:12px;font-weight:600;cursor:pointer}}.add-pupil-btn{{background:#0f172a;color:white;padding:11px 16px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div style='margin-bottom:16px'><h1 style='margin:0;font-size:26px;font-weight:900'>Students Manager</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage pupils — {school_name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px'><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Total Students</div><div style='font-size:26px;font-weight:900;margin-top:6px'>{total}</div></div></div><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Male / Female</div><div style='font-size:22px;font-weight:900;margin-top:6px'><span style='color:#2563eb'>{male}</span> / <span style='color:#db2777'>{female}</span></div></div></div><div class='stu-card'><div><div style='font-size:12px;color:#64748b;font-weight:600'>Boarding / Day</div><div style='font-size:22px;font-weight:900;margin-top:6px'><span style='color:#059669'>{boarding}</span> / <span style='color:#ea580c'>{day}</span></div></div></div><div class='stu-card' style='flex-direction:column;align-items:flex-start'><div style='font-size:12px;color:#64748b;font-weight:600;margin-bottom:8px'>By Class</div><div style='display:flex;flex-wrap:wrap'>{class_pills}</div></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;border-bottom:1px solid #f1f5f9'><div style='display:flex;align-items:center;gap:8px'><span style='font-size:12px;color:#64748b'>Show</span><select id='perPage' class='filter-select' style='min-width:70px' onchange='filterStu()'><option value='10'>10</option><option value='25'>25</option><option value='50'>50</option><option value='100'>100</option><option value='1000'>All</option></select><span style='font-size:12px;color:#64748b'>items</span></div><div style='display:flex;gap:8px;flex-wrap:wrap'><button class='add-pupil-btn' onclick='openStuModal()'>+ Admit Pupil</button></div></div><div style='padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:9px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='stuSearch' onkeyup='filterStu()' placeholder='Search name, ADM, guardian' style='padding:9px 12px 9px 30px;border:1px solid #e2e8f0;border-radius:10px;font-size:12px;min-width:200px'></div><select id='classFilter' class='filter-select' onchange='filterStu()'>{class_filter_opts}</select><select id='genderFilter' class='filter-select' onchange='filterStu()'><option value='all'>All Gender</option><option value='male'>Male</option><option value='female'>Female</option></select><select id='categoryFilter' class='filter-select' onchange='filterStu()'><option value='all'>All Category</option><option value='day'>Day</option><option value='boarding'>Boarding</option></select><button class='action-btn' onclick='exportStuCSV()'>📄 CSV</button><button class='action-btn' onclick='exportPDF()'>⬇️ PDF</button><button class='action-btn' onclick='exportKemis()'>📤 KEMIS Export</button></div><div style='overflow:auto;max-height:68vh'><table id='stuTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-top:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9'><th style='padding:11px 10px'>#</th><th style='padding:11px 10px'>ADM NO</th><th style='padding:11px 10px'>NAME</th><th style='padding:11px 10px'>GENDER</th><th style='padding:11px 10px'>CLASS</th><th style='padding:11px 10px'>CATEGORY</th><th style='padding:11px 10px'>GUARDIAN</th><th style='padding:11px 10px'>PHONE</th><th style='padding:11px 10px'>ACTIONS</th></tr></thead><tbody>{rows_html}</tbody></table></div></div></div><div id='stuModal' class='modal'><div style='background:white;border-radius:16px;width:560px;max-width:96%;max-height:92vh;overflow:auto'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center'><b>➕ Admit Pupil — {school_name}</b><span onclick='closeStuModal()' style='cursor:pointer;font-size:20px'>✕</span></div><form method='post' action='{add_action}' style='padding:18px;display:grid;grid-template-columns:1fr 1fr;gap:12px'><div><label style='font-size:11px;font-weight:700'>🆔 Admission No *</label><input name='admission_no' required placeholder='e.g. 1001' class='input-field'></div><div><label style='font-size:11px;font-weight:700'>📝 Assessment No</label><input name='assessment_no' placeholder='KEMIS' class='input-field'></div><div style='grid-column:span 2'><label style='font-size:11px;font-weight:700'>👤 Full Name *</label><input name='student_name' required placeholder='Full Name *' class='input-field'></div><div><label style='font-size:11px;font-weight:700'>🏫 Class *</label><select name='class_id' required class='input-field'><option value=''>Select Class *</option>{class_opts_form}</select></div><div><label style='font-size:11px;font-weight:700'>⚧️ Gender *</label><select name='gender' required class='input-field'><option value='Male'>Male</option><option value='Female'>Female</option></select></div><div><label style='font-size:11px;font-weight:700'>🏠 Category *</label><select name='category' required class='input-field'><option value='Day'>Day</option><option value='Boarding'>Boarding</option></select></div><div><label style='font-size:11px;font-weight:700'>👨‍👩‍👧 Guardian Name</label><input name='guardian_name' placeholder='Guardian Name' class='input-field'></div><div style='grid-column:span 2'><label style='font-size:11px;font-weight:700'>📞 Guardian Phone</label><input name='parent_phone' placeholder='Phone' class='input-field'></div><div style='grid-column:span 2;margin-top:6px'><button class='add-btn'>✅ Admit Pupil</button></div></form></div></div><script>function openStuModal(){{document.getElementById('stuModal').classList.add('active');}}function closeStuModal(){{document.getElementById('stuModal').classList.remove('active');}}function filterStu(){{let q=document.getElementById('stuSearch').value.toLowerCase();let cf=document.getElementById('classFilter').value.toLowerCase();let gf=document.getElementById('genderFilter').value.toLowerCase();let catf=document.getElementById('categoryFilter').value.toLowerCase();let per=parseInt(document.getElementById('perPage').value);let rows=document.querySelectorAll('.stu-row');let vis=0;rows.forEach(r=>{{let ok=true;if(q&&!r.getAttribute('data-search').includes(q))ok=false;if(cf!=='all'&&!r.getAttribute('data-class').includes(cf))ok=false;if(gf!=='all'&&!r.getAttribute('data-gender').includes(gf))ok=false;if(catf!=='all'&&!r.getAttribute('data-category').includes(catf))ok=false;if(ok){{vis++;r.style.display=(per>=1000||vis<=per)?'':'none';}} else {{r.style.display='none';}}}});}}function exportStuCSV(){{let rows=document.querySelectorAll('#stuTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i<8)d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}});if(d.length)csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='students_{school_name}.csv';a.click();}}function exportKemis(){{let rows=document.querySelectorAll('.stu-row');let out=[['ADM_NO','NAME','GENDER','CLASS','CATEGORY','GUARDIAN','PHONE'].join(',')];rows.forEach(r=>{{if(r.style.display==='none')return;let tds=r.querySelectorAll('td');let vals=[tds[1].innerText,tds[2].innerText,tds[3].innerText,tds[4].innerText,tds[5].innerText,tds[6].innerText,tds[7].innerText].map(v=>'\"'+v.replace(/\"/g,'\"\"')+'\"');out.push(vals.join(','));}});let b=new Blob([out.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='KEMIS_{school_name}.csv';a.click();}}function exportPDF(){{window.print();}}</script>"""

def dean_manager_html(terms, subjects, teachers, classes, allocations, students, school_name, is_global=False, active_tab="terms"):
    years = sorted(list(set([t['year'] for t in terms if t['year']])), reverse=True)
    year_opts = "<option value='all'>All Years</option>" + "".join([f"<option value='{y}'>{y}</option>" for y in years])
    term_rows = ""
    for idx, t in enumerate(terms,1):
        edit_btn = f"""<a href='#' onclick='openEditTerm({t['id']},\"{t['term_name']}\",\"{t['year']}\",\"{t['start_date']}\",\"{t['end_date']}\");return false;' style='padding:6px 8px;background:#f1f5f9;border-radius:8px;text-decoration:none'>✏️</a>"""
        del_url = f"/super/global-control/dean-settings/delete-term/{t['id']}" if is_global else f"/school/dean-settings/delete-term/{t['id']}"
        term_rows += f"""<tr class='term-row' data-search="{t['term_name'].lower()} {t['year']}" data-year="{t['year']}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:13px'>{idx}</td><td style='padding:12px;font-size:13px;font-weight:700'>{t['term_name']}</td><td style='padding:12px;font-size:13px'>{t['year']}</td><td style='padding:12px;font-size:13px'>{t['start_date']}</td><td style='padding:12px;font-size:13px'>{t['end_date']}</td><td style='padding:12px;display:flex;gap:6px'>{edit_btn}<a href='{del_url}' style='padding:6px 8px;background:#fee2e2;border-radius:8px;text-decoration:none'>🗑️</a></td></tr>"""
    if not term_rows:
        term_rows = "<tr><td colspan='7' style='padding:40px;text-align:center;color:#94a3b8'>No terms</td></tr>"
    subj_rows = ""
    for idx, s in enumerate(subjects,1):
        del_url = f"/super/global-control/dean-settings/delete-subject/{s['id']}" if is_global else f"/school/dean-settings/delete-subject/{s['id']}"
        subj_rows += f"""<tr class='subj-row' data-search="{s['name'].lower()}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:13px'>{idx}</td><td style='padding:12px;font-size:13px;font-weight:700'>{s['name']}</td><td style='padding:12px;font-size:13px'>{s['code'] or '—'}</td><td style='padding:12px;font-size:13px'>{s['initial'] or '—'}</td><td style='padding:12px'><a href='{del_url}' style='padding:6px 8px;background:#fee2e2;border-radius:8px;text-decoration:none'>🗑️</a></td></tr>"""
    if not subj_rows:
        subj_rows = "<tr><td colspan='6' style='padding:40px;text-align:center;color:#94a3b8'>No subjects</td></tr>"
    t_opts = "".join([f"<option value='{t['id']}'>{t['name']} ({t['role'] or 'Teacher'})</option>" for t in teachers])
    s_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    c_opts = "".join([f"<option value='{c['id']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    alloc_rows = ""
    for a in allocations:
        del_url = f"/super/global-control/dean-settings/delete-alloc/{a['id']}" if is_global else f"/school/dean-settings/delete-alloc/{a['id']}"
        alloc_rows += f"""<tr><td style='padding:10px 12px;font-size:13px'>{a['tname'] or '—'}</td><td style='padding:10px 12px;font-size:13px'>{a['sname'] or '—'}</td><td style='padding:10px 12px;font-size:13px'>{a['cname'] or '—'}</td><td style='padding:10px 12px'><a href='{del_url}' style='background:#fee2e2;color:#991b1b;padding:5px 8px;border-radius:7px;text-decoration:none'>🗑️</a></td></tr>"""
    if not alloc_rows:
        alloc_rows = "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No allocations</td></tr>"
    class_options_promote = "".join([f"<option value='{c['id']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    add_term_action = "/super/global-control/dean-settings/add-term" if is_global else "/school/dean-settings/add-term"
    add_subject_action = "/super/global-control/dean-settings/add-subject" if is_global else "/school/dean-settings/add-subject"
    alloc_action = "/super/global-control/dean-settings/allocate" if is_global else "/school/dean-settings/allocate"
    promote_action = "/super/global-control/dean-settings/promote" if is_global else "/school/dean-settings/promote"
    return f"""<style>.dean-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden}}.dean-tab{{padding:10px 16px;border-radius:10px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid transparent;display:inline-flex;align-items:center;gap:6px}}.dean-tab.active{{background:#0f172a;color:white}}.dean-tab:not(.active){{background:#f8fafc;color:#475569;border:1px solid #e2e8f0}}.filter-input{{padding:10px 12px 10px 34px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;width:220px}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-term-btn{{background:#0f172a;color:white;padding:10px 16px;border:none;border-radius:12px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1450px;margin:auto'><div style='margin-bottom:14px'><h1 style='margin:0;font-size:26px;font-weight:900'>Dean Settings</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage terms, subjects, allocation</p></div><div class='dean-card'><div style='padding:14px 16px;display:flex;gap:8px;border-bottom:1px solid #f1f5f9;flex-wrap:wrap'><div onclick="switchTab('terms')" id='tab-terms' class='dean-tab {"active" if active_tab=="terms" else ""}'>📅 Terms</div><div onclick="switchTab('subjects')" id='tab-subjects' class='dean-tab {"active" if active_tab=="subjects" else ""}'>📖 Subjects</div><div onclick="switchTab('allocation')" id='tab-allocation' class='dean-tab {"active" if active_tab=="allocation" else ""}'>👥 Teacher Allocation</div><div onclick="switchTab('promote')" id='tab-promote' class='dean-tab {"active" if active_tab=="promote" else ""}'>↗️ Promote</div></div><div id='panel-terms' style='display:{"block" if active_tab=="terms" else "none"}'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='termSearch' onkeyup='filterTerms()' placeholder='Search terms...' class='filter-input'></div><select id='yearFilter' class='filter-select' onchange='filterTerms()'>{year_opts}</select></div><div style='display:flex;gap:8px'><button class='add-term-btn' onclick='openAddTerm()'>+ Add Term</button></div></div><div style='overflow:auto;max-height:60vh'><table id='termsTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px'><input type='checkbox'></th><th style='padding:12px'>#</th><th style='padding:12px'>TERM</th><th style='padding:12px'>YEAR</th><th style='padding:12px'>START</th><th style='padding:12px'>END</th><th style='padding:12px'>ACTIONS</th></tr></thead><tbody>{term_rows}</tbody></table></div></div><div id='panel-subjects' style='display:{"block" if active_tab=="subjects" else "none"}'><div style='padding:14px 16px;display:flex;justify-content:space-between'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='subjSearch' onkeyup='filterSubjects()' placeholder='Search...' class='filter-input'></div><button class='add-term-btn' onclick='openAddSubject()'>+ Add Subject</button></div><div style='overflow:auto;max-height:60vh'><table style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:11px;color:#64748b'><th style='padding:12px'><input type='checkbox'></th><th>#</th><th>NAME</th><th>CODE</th><th>INITIAL</th><th>ACTIONS</th></tr></thead><tbody>{subj_rows}</tbody></table></div></div><div id='panel-allocation' style='display:{"block" if active_tab=="allocation" else "none"}'><div style='padding:16px;display:grid;grid-template-columns:320px 1fr;gap:16px'><div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px'><b>📌 Allocate Teacher</b><form method='post' action='{alloc_action}' style='margin-top:10px'><select name='teacher_id' required class='input-field'><option value=''>Select Teacher *</option>{t_opts}</select><select name='subject_id' required class='input-field'><option value=''>Select Subject *</option>{s_opts}</select><select name='class_id' required class='input-field'><option value=''>Select Class *</option>{c_opts}</select><button class='add-btn' style='margin-top:10px'>Allocate</button></form></div><div style='background:white;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden'><div style='padding:12px 14px;border-bottom:1px solid #f1f5f9'><b>Allocations ({len(allocations)})</b></div><table style='width:100%'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>TEACHER</th><th>SUBJECT</th><th>CLASS</th><th>ACTION</th></tr></thead><tbody>{alloc_rows}</tbody></table></div></div></div><div id='panel-promote' style='display:{"block" if active_tab=="promote" else "none"}'><div style='padding:20px;max-width:600px'><form method='post' action='{promote_action}' style='display:grid;gap:12px'><select name='from_class' required class='input-field'><option value=''>From Class *</option>{class_options_promote}</select><select name='to_class' required class='input-field'><option value=''>To Class *</option>{class_options_promote}</select><button class='add-btn'>↗️ Promote</button></form></div></div></div></div><div id='addTermModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Term</b><span onclick='closeAddTerm()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_term_action}' style='padding:18px;display:grid;gap:10px'><select name='term_name' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='Year' class='input-field'><input name='start_date' type='date' required class='input-field'><input name='end_date' type='date' required class='input-field'><button class='add-btn'>Add Term</button></form></div></div><div id='editTermModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>✏️ Edit Term</b><span onclick='closeEditTerm()' style='cursor:pointer'>✕</span></div><form id='editTermForm' method='post' style='padding:18px;display:grid;gap:10px'><select name='term_name' id='e_term_name' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' id='e_year' required class='input-field'><input name='start_date' id='e_start' type='date' required class='input-field'><input name='end_date' id='e_end' type='date' required class='input-field'><button class='add-btn'>Update Term</button></form></div></div><div id='addSubjectModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Subject</b><span onclick='closeAddSubject()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_subject_action}' style='padding:18px;display:grid;gap:10px'><input name='subject_name' required placeholder='Subject Name *' class='input-field'><input name='code' placeholder='Code' class='input-field'><input name='initial' placeholder='Initial' class='input-field'><button class='add-btn'>Add Subject</button></form></div></div><script>function switchTab(t){{document.querySelectorAll('[id^=panel-]').forEach(p=>p.style.display='none');document.querySelectorAll('.dean-tab').forEach(b=>b.classList.remove('active'));document.getElementById('panel-'+t).style.display='block';document.getElementById('tab-'+t).classList.add('active');}}function openAddTerm(){{document.getElementById('addTermModal').classList.add('active');}}function closeAddTerm(){{document.getElementById('addTermModal').classList.remove('active');}}function openEditTerm(id,name,year,s,e){{document.getElementById('editTermModal').classList.add('active');document.getElementById('editTermForm').action = (window.location.pathname.includes('global-control')? '/super/global-control/dean-settings/edit-term/' : '/school/dean-settings/edit-term/') + id;document.getElementById('e_term_name').value=name;document.getElementById('e_year').value=year;document.getElementById('e_start').value=s;document.getElementById('e_end').value=e;}}function closeEditTerm(){{document.getElementById('editTermModal').classList.remove('active');}}function openAddSubject(){{document.getElementById('addSubjectModal').classList.add('active');}}function closeAddSubject(){{document.getElementById('addSubjectModal').classList.remove('active');}}function filterTerms(){{let q=document.getElementById('termSearch').value.toLowerCase();let y=document.getElementById('yearFilter').value.toLowerCase();document.querySelectorAll('.term-row').forEach(r=>{{let ok=true;if(q &&!r.getAttribute('data-search').includes(q)) ok=false;if(y!=='all' && r.getAttribute('data-year').toLowerCase()!==y) ok=false;r.style.display=ok?'':'none';}});}}function filterSubjects(){{let q=document.getElementById('subjSearch').value.toLowerCase();document.querySelectorAll('.subj-row').forEach(r=>{{r.style.display=r.getAttribute('data-search').includes(q)?'':'none';}});}}</script>"""

def exam_manager_html(exams, school_name, is_global=False):
    from collections import Counter
    year_counter = Counter([e['year'] for e in exams if e['year']])
    term_counter = Counter([e['term'] for e in exams if e['term']])
    year_opts_filter = "<option value='all'>All Years</option>" + "".join([f"<option value='{y}'>{y} ({c})</option>" for y,c in sorted(year_counter.items(), reverse=True)])
    term_opts_filter = "<option value='all'>All Terms</option>" + "".join([f"<option value='{t}'>{t} ({c})</option>" for t,c in term_counter.items()])
    rows = ""
    for idx, e in enumerate(exams, 1):
        del_url = f"/super/global-control/exams/delete/{e['id']}" if is_global else f"/school/exams/delete/{e['id']}"
        edit_btn = f"""<a href='#' onclick='openEditExam({e['id']},"{e['name']}","{e['term']}","{e['year']}","{e['exam_type'] or 'Main Exam'}");return false;' style='padding:6px 8px;background:#f1f5f9;border-radius:8px;text-decoration:none'>✏️</a>"""
        rows += f"""<tr class='exam-row' data-search="{e['name'].lower()} {e['year']} {e['term'].lower()}" data-year="{e['year']}" data-term="{e['term']}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:13px'>{idx}</td><td style='padding:12px;font-size:13px;font-weight:700'>{e['name']}</td><td style='padding:12px;font-size:13px'>{e['term']}</td><td style='padding:12px;font-size:13px'>{e['year']}</td><td style='padding:12px'><span style='background:#0f172a;color:white;padding:4px 10px;border-radius:12px;font-size:11px'>{e['exam_type'] or 'Main Exam'}</span></td><td style='padding:12px;display:flex;gap:6px'>{edit_btn}<a href='{del_url}' style='padding:6px 8px;background:#fee2e2;border-radius:8px;text-decoration:none'>🗑️</a></td></tr>"""
    if not rows:
        rows = "<tr><td colspan='7' style='padding:40px;text-align:center;color:#94a3b8'>No exams</td></tr>"
    add_action = "/super/global-control/exams/add" if is_global else "/school/exams/add"
    edit_base = "/super/global-control/exams/edit/" if is_global else "/school/exams/edit/"
    return f"""<style>.exam-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden}}.filter-input{{padding:10px 12px 10px 34px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;width:220px}}.filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px}}.action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:12px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.add-exam-btn{{background:#0f172a;color:white;padding:10px 16px;border:none;border-radius:12px;font-weight:700;cursor:pointer}}.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:16px}}.modal.active{{display:flex}}</style><div style='padding:20px;max-width:1450px;margin:auto'><div style='margin-bottom:14px'><h1 style='margin:0;font-size:26px;font-weight:900'>Exam Settings</h1><p style='margin:6px 0 0;color:#64748b;font-size:13px'>Manage exams — {school_name}</p></div><div class='exam-card'><div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='examSearch' onkeyup='filterExams()' placeholder='Search exams...' class='filter-input'></div><select id='yearFilter' class='filter-select' onchange='filterExams()'>{year_opts_filter}</select><select id='termFilter' class='filter-select' onchange='filterExams()'>{term_opts_filter}</select></div><div style='display:flex;gap:8px'><button class='action-btn' onclick='downloadExams()'>⬇️ Download CSV</button><button class='add-exam-btn' onclick='openAddExam()'>+ Add Exam</button></div></div><div style='overflow:auto;max-height:65vh'><table id='examTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:11px;color:#64748b'><th style='padding:12px'><input type='checkbox'></th><th>#</th><th>EXAM NAME</th><th>TERM</th><th>YEAR</th><th>TYPE</th><th>ACTIONS</th></tr></thead><tbody>{rows}</tbody></table></div></div></div><div id='addExamModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>+ Add Exam</b><span onclick='closeAddExam()' style='cursor:pointer'>✕</span></div><form method='post' action='{add_action}' style='padding:18px;display:grid;gap:10px'><input name='exam_name' required placeholder='Exam Name *' class='input-field'><select name='term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='Year e.g. 2026' class='input-field'><select name='exam_type' required class='input-field'><option>Main Exam</option><option>End Term Exam</option><option>Mid Term</option><option>CAT</option></select><button class='add-btn'>Add Exam</button></form></div></div><div id='editExamModal' class='modal'><div style='background:white;border-radius:16px;width:460px;max-width:95%'><div style='padding:18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><b>✏️ Edit Exam</b><span onclick='closeEditExam()' style='cursor:pointer'>✕</span></div><form id='editExamForm' method='post' style='padding:18px;display:grid;gap:10px'><input name='exam_name' id='e_name' required class='input-field'><select name='term' id='e_term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' id='e_year' required class='input-field'><select name='exam_type' id='e_type' required class='input-field'><option>Main Exam</option><option>End Term Exam</option><option>Mid Term</option><option>CAT</option></select><button class='add-btn'>Update Exam</button></form></div></div><script>function openAddExam(){{document.getElementById('addExamModal').classList.add('active');}}function closeAddExam(){{document.getElementById('addExamModal').classList.remove('active');}}function openEditExam(id,name,term,year,type){{document.getElementById('editExamModal').classList.add('active');document.getElementById('editExamForm').action = "{edit_base}" + id; document.getElementById('e_name').value=name; document.getElementById('e_term').value=term; document.getElementById('e_year').value=year; document.getElementById('e_type').value=type;}}function closeEditExam(){{document.getElementById('editExamModal').classList.remove('active');}}function filterExams(){{let q=document.getElementById('examSearch').value.toLowerCase();let y=document.getElementById('yearFilter').value.toLowerCase();let t=document.getElementById('termFilter').value.toLowerCase();document.querySelectorAll('.exam-row').forEach(r=>{{let ok=true;if(q &&!r.getAttribute('data-search').includes(q)) ok=false;if(y!=='all' && r.getAttribute('data-year').toLowerCase()!==y) ok=false;if(t!=='all' && r.getAttribute('data-term').toLowerCase()!==t) ok=false;r.style.display=ok?'':'none';}});}}function downloadExams(){{let rows=document.querySelectorAll('#examTable tr');let csv=[];rows.forEach(row=>{{let cols=row.querySelectorAll('th,td');let d=[];cols.forEach((c,i)=>{{if(i>0 && i<6) d.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}}); if(d.length) csv.push(d.join(','));}});let b=new Blob([csv.join('\\n')],{{type:'text/csv'}});let u=URL.createObjectURL(b);let a=document.createElement('a');a.href=u;a.download='exams_{school_name}.csv';a.click();}}</script>"""

def set_marks_exact_html(subjects, classes, streams, years, terms_list, exams, configs, school_name, is_global=False, filters=None):
    filters = filters or {}
    subj_opts = "<option value=''>-- Select Subject --</option>" + "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    class_opts = "<option value=''>-- Select Class --</option>" + "".join([f"<option value='{c['name']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    stream_opts = "<option value=''>-- Select Stream --</option>" + "".join([f"<option value='{st}'>{st}</option>" for st in streams])
    year_opts = "<option value=''>-- Select Year --</option>" + "".join([f"<option value='{y}'>{y}</option>" for y in years])
    term_opts = "<option value=''>-- Select Term --</option>" + "".join([f"<option value='{t}'>{t}</option>" for t in terms_list])
    exam_opts = "<option value=''>-- Select Exam --</option>" + "".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams])
    all_years_filter = "<option value='all'>All Years</option>" + "".join([f"<option value='{y}' {'selected' if filters.get('year')==y else ''}>{y}</option>" for y in years])
    all_terms_filter = "<option value='all'>All Terms</option>" + "".join([f"<option value='{t}' {'selected' if filters.get('term')==t else ''}>{t}</option>" for t in terms_list])
    all_classes_filter = "<option value='all'>All Classes</option>" + "".join([f"<option value='{c['name']}' {'selected' if filters.get('class')==c['name'] else ''}>{c['name']}</option>" for c in classes])
    rows = ""
    for idx, cfg in enumerate(configs, 1):
        del_url = f"/super/global-control/set-marks/delete/{cfg['id']}" if is_global else f"/school/set-marks/delete/{cfg['id']}"
        rows += f"""<tr class='cfg-row' data-search="{(cfg['subject_name'] or '').lower()} {(cfg['class_name'] or '').lower()}"><td style='padding:12px'><input type='checkbox'></td><td style='padding:12px;font-size:12px'>{idx}</td><td style='padding:12px;font-size:12px'>{cfg['year']}</td><td style='padding:12px;font-size:12px'>{cfg['term']}</td><td style='padding:12px;font-size:12px;font-weight:700'>{cfg['class_name']} {cfg['stream'] or ''}</td><td style='padding:12px;font-size:12px;font-weight:600'>{cfg['subject_name']}</td><td style='padding:12px;font-size:12px'>{cfg['out_of']}</td><td style='padding:12px'><a href='{del_url}' style='background:#fee2e2;color:#991b1b;padding:5px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️</a></td></tr>"""
    if not rows:
        rows = "<tr><td colspan='8' style='padding:40px;text-align:center;color:#94a3b8'>No set marks yet — configure on left</td></tr>"
    save_action = "/super/global-control/set-marks/save" if is_global else "/school/set-marks/save"
    return f"""<style>.page-title{{font-size:24px;font-weight:900;margin:0}}.page-sub{{font-size:13px;color:#64748b;margin-top:4px}}.two-col{{display:grid;grid-template-columns:380px 1fr;gap:16px;margin-top:16px}}.card-white{{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px}}.info-blue{{background:#e6f0ff;border:1px solid #bfdbfe;border-radius:12px;padding:12px;font-size:12px;color:#1e40af;display:flex;gap:8px;line-height:1.5}}.label-red{{font-size:11px;font-weight:700;color:#dc2626;display:block;margin-top:10px;margin-bottom:4px}}.select-field{{width:100%;padding:11px 12px;border:1px solid #e5e7eb;border-radius:10px;background:white;font-size:13px}}.save-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer;margin-top:14px}}.filter-bar{{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}}.filter-select{{padding:8px 10px;border:1px solid #e5e7eb;border-radius:10px;background:white;font-size:12px;min-width:110px}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div><h1 class='page-title'>Set Marks</h1><p class='page-sub'>Configure the maximum marks (out of) for each subject per exam</p></div><div class='two-col'><div class='card-white'><h3 style='margin:0 0 12px;font-size:16px;font-weight:800'>Set Marks Options</h3><div class='info-blue'>ℹ️ <span><b>Out Of:</b> This is what the teacher will mark this paper out of e.g. 50 or 100. Marks are not converted. e.g. if the paper is out of 60 set that.</span></div><form method='post' action='{save_action}' style='margin-top:14px'><label class='label-red'>Subject *</label><select name='subject_id' required class='select-field'>{subj_opts}</select><label class='label-red'>Class *</label><select name='class_name' required class='select-field'>{class_opts}</select><label class='label-red'>Stream *</label><select name='stream' required class='select-field'>{stream_opts}</select><label class='label-red'>Year *</label><select name='year' required class='select-field'>{year_opts}</select><label class='label-red'>Term *</label><select name='term' required class='select-field'>{term_opts}</select><label class='label-red'>Exam *</label><select name='exam_id' required class='select-field'>{exam_opts}</select><label class='label-red'>Out Of *</label><input name='out_of' required type='number' min='1' max='500' placeholder='Out Of' class='select-field'><button class='save-btn'>💾 Save Settings</button></form></div><div class='card-white'><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'><h3 style='margin:0;font-size:16px;font-weight:800'>Already Set Marks</h3><span style='font-size:11px;color:#64748b'>{len(configs)} records</span></div><div class='filter-bar'><select id='filterYear' class='filter-select' onchange='filterConfigs()'>{all_years_filter}</select><select id='filterTerm' class='filter-select' onchange='filterConfigs()'>{all_terms_filter}</select><select id='filterClass' class='filter-select' onchange='filterConfigs()'>{all_classes_filter}</select><input id='searchConfig' onkeyup='filterConfigs()' placeholder='🔍 Search...' style='padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;font-size:12px;min-width:130px'></div><div style='overflow:auto;max-height:70vh'><table id='configTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#fcfcfc'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:10px 12px'><input type='checkbox'></th><th style='padding:10px 12px'>#</th><th>YEAR ↓</th><th>TERM</th><th>CLASS</th><th>SUBJECT</th><th>OUT OF</th><th>ACTION</th></tr></thead><tbody>{rows}</tbody></table></div><div style='display:flex;justify-content:space-between;margin-top:12px;font-size:12px;color:#64748b'><span>Show <select id='perPage' onchange='filterConfigs()' style='padding:4px;border:1px solid #e5e7eb;border-radius:6px'><option>10</option><option>25</option><option>50</option><option>100</option></select> items per page</span><span id='showing'>Showing 1-{len(configs)} of {len(configs)}</span></div></div></div></div><script>function filterConfigs(){{let q=document.getElementById('searchConfig').value.toLowerCase();let yf=document.getElementById('filterYear').value.toLowerCase();let tf=document.getElementById('filterTerm').value.toLowerCase();let cf=document.getElementById('filterClass').value.toLowerCase();let rows=document.querySelectorAll('.cfg-row');let visible=0;rows.forEach(r=>{{let ok=true;let txt=r.getAttribute('data-search');if(q &&!txt.includes(q)) ok=false;let tds=r.querySelectorAll('td');let year=tds[2].innerText.toLowerCase();let term=tds[3].innerText.toLowerCase();let cls=tds[4].innerText.toLowerCase();if(yf!=='all' && yf!=='' &&!year.includes(yf)) ok=false;if(tf!=='all' && tf!=='' &&!term.includes(tf)) ok=false;if(cf!=='all' && cf!=='' &&!cls.includes(cf)) ok=false;r.style.display=ok?'':'none';if(ok) visible++;}});document.getElementById('showing').innerText='Showing 1-'+visible+' of '+visible;}}</script>"""

def record_marks_exact_html(students, subject_name, exam_name, class_name, stream_name, out_of, total_count, filled_count, school_name, exam_id, subject_id, year, term):
    full_class = f"{class_name} {stream_name}".strip()
    rows = ""
    for idx, st in enumerate(students, 1):
        marks_val = st.get('marks', '')
        display_val = f"{marks_val}" if marks_val!= "" and marks_val is not None else ""
        placeholder = f"/ {out_of}"
        rows += f"""<tr class='stu-row' data-search="{(st['name'] or '').lower()} {str(st['admission_no'] or '').lower()}">
<td style='padding:14px 12px;font-size:13px;color:#64748b'>{idx}</td>
<td style='padding:14px 12px;font-size:13px;font-weight:700'>{st['admission_no'] or ''}</td>
<td style='padding:14px 12px;font-size:13px;font-weight:600'>{st['name']}</td>
<td style='padding:14px 12px'><input type='number' min='0' max='{out_of}' step='0.01' id='mark_{st['id']}' value='{display_val}' placeholder='{placeholder}' onblur='autoSave({st['id']})' onkeydown='if(event.key==="Enter"){{autoSave({st['id']}); let next=document.getElementById("mark_{students[idx]["id"] if idx < len(students) else st["id"]}"); if(next) next.focus();}}' style='width:110px;padding:9px 12px;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;background:#fcfcfc;text-align:center'></td>
</tr>"""
    return f"""<style>.record-card{{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:0;overflow:hidden}}.record-header{{padding:14px 18px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;border-bottom:1px solid #f1f5f9;background:#fcfcfc}}.badge{{padding:4px 10px;border-radius:12px;font-size:11px;font-weight:800;display:inline-block}}.badge-total{{background:#e0f2fe;color:#0369a1;border:1px solid #bae6fd}}.badge-filled{{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}}.badge-open{{background:#f1f5f9;color:#475569;border:1px solid #e2e8f0}}.filter-input{{padding:9px 12px 9px 32px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;min-width:200px}}.action-btn{{padding:9px 14px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;font-weight:600;cursor:pointer}}.save-finish{{background:#0f172a;color:white;padding:10px 18px;border:none;border-radius:10px;font-weight:800;cursor:pointer;display:inline-flex;align-items:center;gap:6px}}</style><div style='padding:20px;max-width:1500px;margin:auto'><div class='record-card'><div style='padding:14px 18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px'><div style='display:flex;gap:16px;flex-wrap:wrap;font-size:13px'><span><span style='color:#64748b'>Subject:</span> <b>{subject_name}</b></span><span><span style='color:#64748b'>Exam:</span> <b>{exam_name}</b></span><span><span style='color:#64748b'>Class:</span> <b>{full_class}</b></span><span><span style='color:#64748b'>Out of:</span> <b>{out_of}</b></span></div><div style='display:flex;gap:8px'><span class='badge badge-total'>Total: {total_count}</span><span class='badge badge-filled' id='filledBadge'>Filled: {filled_count}</span><span class='badge badge-open'>open</span></div></div><div style='padding:12px 18px;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='display:flex;align-items:center;gap:8px;font-size:13px'><span style='color:#64748b'>Show</span><select id='perPage' onchange='changePerPage()' style='padding:6px 8px;border:1px solid #e2e8f0;border-radius:8px'><option value='10' selected>10</option><option value='25'>25</option><option value='50'>50</option><option value='100'>100</option><option value='1000'>All</option></select><span style='color:#64748b'>items per page</span></div><div style='display:flex;gap:10px;align-items:center'><div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='searchInput' onkeyup='filterStudents()' placeholder='Search by name or admno...' class='filter-input'></div><button class='action-btn' onclick='exportCSV()'>⬇️ Export CSV</button></div></div><div style='overflow:auto;max-height:62vh'><table id='marksTable' style='width:100%;border-collapse:collapse'><thead style='position:sticky;top:0;background:#f8fafc;z-index:2'><tr style='text-align:left;font-size:11px;color:#64748b;border-bottom:1px solid #f1f5f9'><th style='padding:12px'>#</th><th style='padding:12px'>ADMNO ↑</th><th style='padding:12px'>STUDENT NAME ↕️</th><th style='padding:12px'>MARKS ↕️</th></tr></thead><tbody id='tableBody'>{rows}</tbody></table></div><div style='padding:14px 18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;border-top:1px solid #f1f5f9'><div style='font-size:12px;color:#64748b'><span id='showingText'>Showing 1-10 of {total_count}</span><br><span id='enteredText'>{filled_count} of {total_count} marks entered</span><br><span style='font-size:11px'>Marks auto-save when you move to the next field. Click 'Save & Finish' when done to mark as recorded.</span></div><div style='display:flex;gap:10px;align-items:center'><div style='display:flex;gap:6px;align-items:center;font-size:12px'><button onclick='prevPage()' class='action-btn'>‹ Previous</button><span id='pageInfo'>Page 1 of 7</span><button onclick='nextPage()' class='action-btn'>Next ›</button></div><button onclick='saveFinish()' class='save-finish'>💾 Save & Finish</button></div></div></div></div><script>let currentPage=1; let perPage=10; let allRows=[]; window.onload=function(){{ allRows=Array.from(document.querySelectorAll('.stu-row')); updatePagination(); }}; function filterStudents(){{ let q=document.getElementById('searchInput').value.toLowerCase(); allRows.forEach(r=>{{ let s=r.getAttribute('data-search'); r.style.display = s.includes(q)? '' : 'none'; }}); currentPage=1; updatePagination(); }} function changePerPage(){{ perPage=parseInt(document.getElementById('perPage').value); currentPage=1; updatePagination(); }} function updatePagination(){{ let searchQ=document.getElementById('searchInput').value.toLowerCase(); let toShow=allRows.filter(r=>r.getAttribute('data-search').includes(searchQ)); let total=toShow.length; let start=(currentPage-1)*perPage; let end=start+perPage; allRows.forEach(r=>r.style.display='none'); toShow.slice(start,end).forEach(r=>r.style.display=''); document.getElementById('showingText').innerText=`Showing ${{total==0?0:start+1}}-${{Math.min(end,total)}} of {total_count}`; let totalPages=Math.ceil(total/perPage)||1; document.getElementById('pageInfo').innerText=`Page ${{currentPage}} of ${{totalPages}}`; }} function prevPage(){{ if(currentPage>1){{currentPage--; updatePagination();}} }} function nextPage(){{ let searchQ=document.getElementById('searchInput').value.toLowerCase(); let toShow=allRows.filter(r=>r.getAttribute('data-search').includes(searchQ)); let totalPages=Math.ceil(toShow.length/perPage)||1; if(currentPage<totalPages){{currentPage++; updatePagination();}} }} function autoSave(studentId){{ let input=document.getElementById('mark_'+studentId); let val=input.value; if(val==='' ) return; let num=parseFloat(val); if(num>{out_of}){{ input.value={out_of}; num={out_of}; input.style.border='2px solid #f59e0b'; }} else{{ input.style.border='1px solid #22c55e'; }} fetch('/school/record-marks/auto-save',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:`student_id=${{studentId}}&exam_id={exam_id}&subject_id={subject_id}&class_name={class_name}&stream={stream_name}&year={year}&term={term}&out_of={out_of}&marks=${{num}}`}}).then(r=>r.json()).then(data=>{{ if(data.ok){{ let filledCount=0; document.querySelectorAll('input[id^=mark_]').forEach(i=>{{if(i.value!=='') filledCount++;}}); document.getElementById('filledBadge').innerText='Filled: '+filledCount; document.getElementById('enteredText').innerText=filledCount+' of {total_count} marks entered'; }} }}); }} function saveFinish(){{ let inputs=document.querySelectorAll('input[id^=mark_]'); let promises=[]; inputs.forEach(inp=>{{ if(inp.value!==''){{ let sid=inp.id.replace('mark_',''); promises.push(fetch('/school/record-marks/auto-save',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:`student_id=${{sid}}&exam_id={exam_id}&subject_id={subject_id}&class_name={class_name}&stream={stream_name}&year={year}&term={term}&out_of={out_of}&marks=${{inp.value}}`}})); }} }}); Promise.all(promises).then(()=>{{ window.location.href='/school/dashboard'; }}); }} function exportCSV(){{ let rows=document.querySelectorAll('.stu-row'); let csv=['#,ADMNO,STUDENT NAME,MARKS']; rows.forEach((r,i)=>{{ let tds=r.querySelectorAll('td'); let adm=tds[1].innerText; let name=tds[2].innerText; let inp=r.querySelector('input'); let mark=inp?inp.value:''; csv.push([i+1,adm,'"'+name+'"',mark].join(',')); }}); let b=new Blob([csv.join('\\n')],{{type:'text/csv'}}); let u=URL.createObjectURL(b); let a=document.createElement('a'); a.href=u; a.download='marks_{class_name}_{subject_name}_{exam_name}.csv'; a.click(); }}</script>"""
   @app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{margin:0;font-family:Arial;background:#f0f2f5;display:flex;height:100vh}.blue-bar{width:32px;background:#0d8bf2;flex-shrink:0}.main{flex:1;display:flex;justify-content:center;align-items:center;padding:20px}.card{background:white;width:540px;max-width:100%;padding:48px 48px 40px;border-radius:6px;box-shadow:0 0 0 1px #e2e8f0;text-align:center}.logo-box{width:72px;height:72px;background:#0f172a;color:white;border-radius:18px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:32px;margin:0 auto}.input{width:100%;padding:14px 16px;border:1px solid #e2e8f0;border-radius:10px;background:#fcfcfc;font-size:14px;outline:none;box-sizing:border-box}.sign{background:#0d8bf2;color:white;width:100%;padding:15px;border:none;border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;margin-top:10px}</style></head><body><div class="blue-bar"></div><div class="main"><div class="card"><div class="logo-box">D</div><h1 style="margin:16px 0 0;font-size:40px;font-weight:900;color:#0f172a">DaviSchool</h1><div style="margin-top:12px;color:#334155;font-size:15px">Sign in to your Davischool account</div><form method="post" action="/login" style="margin-top:30px;text-align:left"><label style="font-size:13px;font-weight:700;display:block;margin-bottom:8px">Username or Email</label><input name="email" class="input" required style="margin-bottom:20px"><label style="font-size:13px;font-weight:700;display:block;margin-bottom:8px">Password</label><input name="password" type="password" class="input" required style="margin-bottom:18px"><button class="sign">Sign In</button></form></div></div></body></html>"""
@app.head("/")
def home_head(): return PlainTextResponse("OK")
@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password)); u = cur.fetchone()
    if not u: con.close(); return HTMLResponse("❌ Invalid <a href='/'>Back</a>")
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id, user_email, action, details, timestamp) VALUES (?,?,?,?,?)", (u["school_id"] or 0, u["email"], "LOGIN", f"Login as {u['role']}", ts))
    con.commit(); con.close()
    request.session["email"]=u["email"]; request.session["role"]=u["role"]; request.session["name"]=u["full_name"]; request.session["school_id"]=u["school_id"] or 0; request.session["is_impersonating"]=False
    if u["role"]!= "super_admin": return RedirectResponse("/school/dashboard", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)
@app.get("/logout")
def logout(request: Request): request.session.clear(); return RedirectResponse("/")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") == "school_admin": return RedirectResponse("/school/dashboard")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT COUNT(*) as c FROM schools"); total = cur.fetchone()["c"]; cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 10"); recent = cur.fetchall(); con.close()
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com"); initials = "".join([p[0] for p in name.split()][:2]).upper()
    rows = "".join([f"<tr><td style='padding:10px 14px;font-size:12px;font-weight:600'>{s['name']}</td><td style='padding:10px 14px;font-size:12px'>{s['location']}</td><td><span style='background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:10px'>Active</span></td><td style='padding:10px 14px;font-size:11px;color:#64748b'>Today</td></tr>" for s in recent]) or "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No schools yet</td></tr>"
    content = f"""<div style='padding:20px;max-width:1400px;margin:auto'><div style='margin-bottom:18px'><h2 style='margin:0;font-size:22px;font-weight:800'>📊 School Overview</h2><p style='margin:4px 0 0;color:#64748b;font-size:13px'>Welcome {name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:32px;font-weight:900;margin:12px 0 8px'>{total}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:32px;font-weight:900;margin:12px 0 8px'>{total}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🔥 TOTAL REVENUE</div><div style='font-size:26px;font-weight:900;margin:12px 0 8px'>KES {total*15000}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:32px;font-weight:900;margin:10px 0 8px'>0</div></div></div><div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px 16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='font-weight:800;font-size:14px'>🏫 Recently Added Schools</div><a href='/schools/manage' style='font-size:12px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 14px'>Name</th><th>Location</th><th>Status</th><th>Date</th></tr></thead><tbody>{rows}</tbody></table></div><div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='font-weight:800;font-size:14px;margin-bottom:12px'>⚡ Quick Actions</div><a href='/schools/manage' style='display:block;text-align:center;background:white;border:1px solid #e2e8f0;padding:10px;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:600;font-size:13px;margin-bottom:10px'>🏫 Manage Schools</a><a href='/super/global-control/dashboard' style='display:block;text-align:center;background:#0f172a;color:white;padding:10px;border-radius:10px;text-decoration:none;font-weight:700;font-size:13px'>🌍 Global Control</a></div></div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header_html(initials, name, email)}{content}</body></html>")

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com"); initials = "".join([p[0] for p in name.split()][:2]).upper()
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools ORDER BY id DESC"); schools = cur.fetchall(); cur.execute("SELECT * FROM users WHERE role='school_admin'"); users = cur.fetchall(); pending=None
    if pending_id: cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    con.close(); users_by_school = {u["school_id"]: u for u in users}
    popup=""
    if success=="code_sent" and pending: popup=f"""<div style='margin-bottom:16px;background:white;border:1.5px solid #fb923c;border-radius:12px;padding:16px'><div style='font-weight:800'>🔓 Code for {pending["name"]}</div><div style='border:1.5px dashed #fb923c;border-radius:10px;padding:18px;text-align:center;background:#fffbeb;margin:12px 0'><div style='font-size:28px;font-weight:900;letter-spacing:10px'>{" ".join(list(pending["auth_code"]))}</div></div><form method='post' action='/verify-school-code' style='display:flex;gap:10px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' value='{pending["auth_code"]}' required style='flex:1;padding:12px;border:1px solid #e2e8f0;border-radius:10px;text-align:center;font-weight:700'><button style='background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px'>✅ Verify</button></form></div>"""
    elif success=="added" and new_pass: popup=f"""<div style='position:fixed;inset:0;background:rgba(0,0,0,0.45);display:flex;align-items:center;justify-content:center;z-index:9999'><div style='background:white;padding:24px;border-radius:16px;width:420px'><div style='font-size:18px;font-weight:800'>✅ {school_name} Added!</div><div style='background:#f8fafc;padding:12px;border-radius:10px;margin:12px 0;font-size:13px'><div>🏫 {school_name}</div><div>👤 {school_email}</div><div>🔑 {new_pass}</div></div><button onclick="this.closest('div').parentElement.style.display='none'" style='width:100%;background:#0f172a;color:white;padding:10px;border:none;border-radius:10px'>OK</button></div></div>"""
    rows="".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:12px 10px'><div style='font-weight:700'>🏫 {s['name']}</div><div style='font-size:10px;color:#64748b'>🔑 {s['code']}</div></td><td style='padding:12px 10px;font-size:12px'>{s['phone'] or ''}</td><td style='padding:12px 10px;font-size:11px'>{s['email']}</td><td style='padding:12px 10px;font-size:12px'>{s['location']}</td><td style='padding:12px 10px;font-size:11px'>{users_by_school.get(s['id'],{}).get('email','') if users_by_school.get(s['id']) else ''}</td><td style='padding:12px 10px;font-size:12px'>{users_by_school.get(s['id'],{}).get('password','') if users_by_school.get(s['id']) else ''}</td><td style='padding:12px 10px;display:flex;gap:6px'><a href='/super/switch-to-school/{s['id']}' style='background:#0f172a;color:white;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px;font-weight:700'>👁️ View</a><a href='/schools/delete/{s['id']}' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️</a></td></tr>" for s in schools]) or "<tr><td colspan='7' style='padding:40px;text-align:center'>No schools</td></tr>"
    return HTMLResponse(f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px}}input,select{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px}}</style></head><body>{header_html(initials, name, email)}<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px;padding:16px;max-width:1500px;margin:auto'><div><div class='card'>{popup}<div style='font-weight:800'>📚 Registered Schools ({len(schools)})</div><div style='overflow:auto;max-height:65vh;border:1px solid #f1f5f9;border-radius:10px;margin-top:10px'><table style='width:100%;border-collapse:collapse;font-size:13px'><thead style='position:sticky;top:0;background:#f8fafc'><tr style='text-align:left;font-size:11px'><th style='padding:10px'>School</th><th>Contact</th><th>Email</th><th>Location</th><th>Username</th><th>Password</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div><a href='/dashboard' style='margin-top:14px;display:inline-block;padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div class='card' style='height:fit-content'><div style='font-weight:800'>➕ Register New School</div><form method='post' action='/register-school'><input name='school_name' required placeholder='🏫 School Name *'><input name='school_email' required type='email' placeholder='📧 Admin Email *'><input name='location' required placeholder='📍 Location *'><input name='phone' required placeholder='📱 Phone *'><input name='principal' required placeholder='👤 Principal *'><select name='school_type' required><option>Primary</option><option>Secondary</option><option>Primary & Junior Secondary</option></select><button style='width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;margin-top:10px'>📧 Send Code</button></form></div></div></body></html>""")
@app.post("/register-school")
def register_school(school_name: str = Form(...), school_email: str = Form(...), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    auth_code = str(random.randint(100000, 999999)); con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pending_schools (name,email,location,phone,principal,school_type,auth_code,timestamp) VALUES (?,?,?,?,?,?,?,?)", (school_name.strip().upper(), school_email.strip(), location.strip(), phone.strip(), principal.strip(), school_type, auth_code, ts))
    pending_id = cur.lastrowid; con.commit(); con.close(); return RedirectResponse(f"/schools/manage?success=code_sent&pending_id={pending_id}",303)
@app.post("/verify-school-code")
def verify_school_code(pending_id: str = Form(...), auth_code: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)); pending = cur.fetchone()
    if not pending or pending["auth_code"]!=auth_code.strip(): con.close(); return HTMLResponse(f"❌ Wrong <a href='/schools/manage?success=code_sent&pending_id={pending_id}'>Back</a>")
    code = str(random.randint(100000,999999)); unique_pass = generate_unique_password(pending["name"])
    cur.execute("INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)", (pending["name"], pending["email"], code, pending["location"], pending["phone"], pending["principal"], pending["school_type"]))
    sid = cur.lastrowid; cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (pending["email"], unique_pass, "school_admin", pending["principal"], sid)); cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,)); con.commit(); con.close()
    return RedirectResponse(f"/schools/manage?success=added&new_pass={unique_pass}&school_email={pending['email']}&school_name={pending['name']}",303)
@app.get("/schools/delete/{sid}")
def delete_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM schools WHERE id=?", (sid,)); cur.execute("DELETE FROM users WHERE school_id=?", (sid,)); con.commit(); con.close(); return RedirectResponse("/schools/manage",303)
@app.get("/super/switch-to-school/{sid}")
def switch_to_school(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM schools WHERE id=?", (sid,)); s = cur.fetchone(); con.close()
    if not s: return RedirectResponse("/schools/manage")
    request.session["school_id"]=sid; request.session["is_impersonating"]=True; return RedirectResponse("/school/dashboard",303)
@app.get("/super/back-to-admin")
def back_to_admin(request: Request): request.session["school_id"]=0; request.session["is_impersonating"]=False; return RedirectResponse("/dashboard",303)

def get_set_marks_filter_data(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (school_id,)); subjects = cur.fetchall()
    cur.execute("SELECT name, stream FROM classes WHERE school_id=? GROUP BY name, stream ORDER BY name", (school_id,)); classes_raw = cur.fetchall()
    cur.execute("SELECT DISTINCT stream FROM classes WHERE school_id=? AND stream!='' ORDER BY stream", (school_id,)); streams = [r["stream"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT year FROM terms WHERE school_id=? ORDER BY year DESC", (school_id,)); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years:
        cur.execute("SELECT DISTINCT year FROM exams WHERE school_id=? ORDER BY year DESC", (school_id,)); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years: years = [str(datetime.now().year)]
    cur.execute("SELECT DISTINCT term_name FROM terms WHERE school_id=? ORDER BY term_name", (school_id,)); terms_list = [r["term_name"] for r in cur.fetchall()]
    if not terms_list: terms_list = ["Term 1","Term 2","Term 3"]
    cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school_id,)); exams = cur.fetchall()
    classes_unique = []; seen=set()
    for c in classes_raw:
        if c["name"] not in seen:
            classes_unique.append(c); seen.add(c["name"])
    con.close()
    return subjects, classes_unique, streams, years, terms_list, exams

def get_global_set_marks_filter_data():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM subjects GROUP BY name ORDER BY name"); subjects = cur.fetchall()
    cur.execute("SELECT name, stream FROM classes GROUP BY name, stream ORDER BY name"); classes_raw = cur.fetchall()
    cur.execute("SELECT DISTINCT stream FROM classes WHERE stream!='' ORDER BY stream"); streams = [r["stream"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT year FROM terms ORDER BY year DESC"); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years:
        cur.execute("SELECT DISTINCT year FROM exams ORDER BY year DESC"); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years: years = [str(datetime.now().year)]
    cur.execute("SELECT DISTINCT term_name FROM terms ORDER BY term_name"); terms_list = [r["term_name"] for r in cur.fetchall()]
    if not terms_list: terms_list = ["Term 1","Term 2","Term 3"]
    cur.execute("SELECT * FROM exams GROUP BY name ORDER BY id DESC"); exams = cur.fetchall()
    classes_unique = []; seen=set()
    for c in classes_raw:
        if c["name"] not in seen:
            classes_unique.append(c); seen.add(c["name"])
    con.close()
    return subjects, classes_unique, streams, years, terms_list, exams

@app.get("/school/set-marks", response_class=HTMLResponse)
@app.get("/school/marks", response_class=HTMLResponse)
def school_set_marks(request: Request, year: str = "all", term: str = "all", class_name: str = "all"):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    subjects, classes, streams, years, terms_list, exams = get_set_marks_filter_data(school["id"])
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT cfg.*, s.name as subject_name FROM set_marks_config cfg LEFT JOIN subjects s ON cfg.subject_id=s.id WHERE cfg.school_id=? ORDER BY cfg.year DESC, cfg.term, cfg.class_name""", (school["id"],))
    configs = cur.fetchall(); con.close()
    filters = {"year": year, "term": term, "class": class_name}
    header = school_header(school, name, "set-marks", is_impersonating=is_imp)
    body = set_marks_exact_html(subjects, classes, streams, years, terms_list, exams, configs, school["name"], is_global=False, filters=filters)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/set-marks/save")
def school_set_marks_save(request: Request, subject_id: int = Form(...), class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), exam_id: int = Form(...), out_of: int = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM set_marks_config WHERE school_id=? AND subject_id=? AND class_name=? AND stream=? AND year=? AND term=? AND exam_id=?", (school["id"], subject_id, class_name.strip().upper(), stream.strip().upper(), year.strip(), term.strip(), exam_id))
    existing = cur.fetchone()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        cur.execute("UPDATE set_marks_config SET out_of=?, created_at=? WHERE id=?", (out_of, ts, existing["id"]))
    else:
        cur.execute("INSERT INTO set_marks_config (school_id, subject_id, class_name, stream, year, term, exam_id, out_of, created_at) VALUES (?,?,?,?,?,?,?,?,?)", (school["id"], subject_id, class_name.strip().upper(), stream.strip().upper(), year.strip(), term.strip(), exam_id, out_of, ts))
    con.commit(); con.close()
    return RedirectResponse("/school/set-marks",303)
@app.get("/school/set-marks/delete/{cid}")
def school_set_marks_delete(cid: int, request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM set_marks_config WHERE id=?", (cid,)); con.commit(); con.close()
    return RedirectResponse("/school/set-marks",303)
@app.get("/super/global-control/set-marks", response_class=HTMLResponse)
@app.get("/super/global-control/marks", response_class=HTMLResponse)
def global_set_marks(request: Request, year: str = "all", term: str = "all", class_name: str = "all"):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","")
    subjects, classes, streams, years, terms_list, exams = get_global_set_marks_filter_data()
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT cfg.*, s.name as subject_name FROM set_marks_config cfg LEFT JOIN subjects s ON cfg.subject_id=s.id GROUP BY cfg.subject_id, cfg.class_name, cfg.stream, cfg.year, cfg.term ORDER BY cfg.year DESC""")
    configs = cur.fetchall(); con.close()
    filters = {"year": year, "term": term, "class": class_name}
    header = global_header(name, "set-marks")
    body = set_marks_exact_html(subjects, classes, streams, years, terms_list, exams, configs, "ALL SCHOOLS", is_global=True, filters=filters)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/super/global-control/set-marks/save")
def global_set_marks_save(request: Request, subject_id: int = Form(...), class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), exam_id: int = Form(...), out_of: int = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("SELECT name FROM subjects WHERE id=?", (subject_id,)); srow = cur.fetchone()
    sname = srow["name"] if srow else ""
    for sch in schools:
        cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=?", (sch["id"], sname))
        sub_real = cur.fetchone()
        sub_id_real = sub_real["id"] if sub_real else subject_id
        cur.execute("SELECT id FROM set_marks_config WHERE school_id=? AND subject_id=? AND class_name=? AND stream=? AND year=? AND term=? AND exam_id=?", (sch["id"], sub_id_real, class_name.strip().upper(), stream.strip().upper(), year.strip(), term.strip(), exam_id))
        existing = cur.fetchone()
        if existing:
            cur.execute("UPDATE set_marks_config SET out_of=?, created_at=? WHERE id=?", (out_of, ts, existing["id"]))
        else:
            cur.execute("INSERT INTO set_marks_config (school_id, subject_id, class_name, stream, year, term, exam_id, out_of, created_at) VALUES (?,?,?,?,?,?,?,?,?)", (sch["id"], sub_id_real, class_name.strip().upper(), stream.strip().upper(), year.strip(), term.strip(), exam_id, out_of, ts))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/set-marks",303)
@app.get("/super/global-control/set-marks/delete/{cid}")
def global_set_marks_delete(cid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT subject_id, class_name, stream, year, term, exam_id FROM set_marks_config WHERE id=?", (cid,)); row = cur.fetchone()
    if row:
        cur.execute("DELETE FROM set_marks_config WHERE class_name=? AND stream=? AND year=? AND term=? AND exam_id=? AND subject_id IN (SELECT id FROM subjects WHERE name=(SELECT name FROM subjects WHERE id=?))", (row["class_name"], row["stream"], row["year"], row["term"], row["exam_id"], row["subject_id"]))
        cur.execute("DELETE FROM set_marks_config WHERE id=?", (cid,))
    else:
        cur.execute("DELETE FROM set_marks_config WHERE id=?", (cid,))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/set-marks",303)

# === SCHOOL DASHBOARD + STUDENTS + DEAN + CLASSES + EXAMS RESTORED ===
@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM teachers WHERE school_id=?", (school["id"],)); tc = cur.fetchone()["c"]
    cur.execute("SELECT c.name as class_name, s.gender, COUNT(*) as cnt FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? GROUP BY c.name, s.gender ORDER BY c.name", (school["id"],)); gender_rows = cur.fetchall()
    cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY id DESC LIMIT 5", (school["id"],)); recent = cur.fetchall()
    cur.execute("SELECT COUNT(*) c FROM set_marks_config WHERE school_id=?", (school["id"],)); set_cfg = cur.fetchone()["c"]
    con.close()
    stats={}; tb=0; tg=0
    for r in gender_rows:
        cn=(r['class_name'] or 'UNASSIGNED').upper()
        if cn not in stats: stats[cn]={'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys']=r['cnt']; tb+=r['cnt']
        else: stats[cn]['girls']=r['cnt']; tg+=r['cnt']
    max_v = max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    chart="".join([f"<div style='text-align:center;min-width:90px'><div style='display:flex;gap:10px;align-items:end;justify-content:center;height:170px'><div><div style='width:42px;height:{bh}px;background:#0a84ff;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px;height:{gh}px;background:#ff2d92;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px;font-weight:800;margin-top:8px'>{cn}</div></div>" for cn,v in stats.items() for bh in [int((v['boys']/max_v)*150) if v['boys']>0 else 6] for gh in [int((v['girls']/max_v)*150) if v['girls']>0 else 6]]) or "<div style='padding:30px;color:#94a3b8'>No students</div>"
    stu_rows="".join([f"<tr><td style='padding:10px 12px;font-size:12px'>{st['name']}</td><td>{st['admission_no'] or ''}</td><td>{st['gender']}</td><td>Class {st['class_id'] or ''}</td></tr>" for st in recent]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No students</td></tr>"
    header=school_header(school, name, "dashboard", is_impersonating=is_imp)
    html=f"""<div style='padding:18px;max-width:1400px;margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%);border-radius:18px;padding:22px 24px;color:white;display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'><div><div style='font-size:22px;font-weight:900'>DaviSchool Management System 🚀</div><div style='font-size:12px;color:#bfdbfe;margin-top:4px'>Set Marks: {set_cfg} | Students: {sc}</div></div><div style='text-align:right'><div style='font-size:34px;font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students</div></div></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px'><a href='/school/students' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🎓 TOTAL STUDENTS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{sc}</div></a><a href='/school/classes' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🏫 CLASSES</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{cc}</div></a><a href='/school/exams' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>📝 EXAMS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{ec}</div></a><a href='/school/teachers' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>👨‍🏫 STAFF</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{tc}</div></a></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='display:flex;justify-content:space-between'><div><div style='font-weight:800;font-size:14px'>👥 Students by Gender</div></div><div style='display:flex;gap:12px;font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex;gap:24px;overflow-x:auto;margin-top:18px'>{chart}</div></div><div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:14px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px 16px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><div style='font-weight:800'>🎓 Recent Students</div><a href='/school/students' style='font-size:11px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:10px;color:#64748b'><th style='padding:10px 12px'>Name</th><th>Adm No</th><th>Gender</th><th>Class</th></tr></thead><tbody>{stu_rows}</tbody></table></div><div style='background:#0f172a;border-radius:14px;padding:16px;color:white;height:fit-content'><div style='font-weight:800;font-size:14px'>📊 LIVE</div><div style='background:#1e293b;border-radius:10px;padding:12px;margin-top:10px'><div style='font-size:11px'>👦 {tb} | 👧 {tg}</div><div style='font-size:11px;margin-top:6px;color:#22c55e'>Out Of Config: {set_cfg}</div><a href='/school/set-marks' style='display:block;margin-top:10px;background:white;color:#0f172a;padding:8px;border-radius:8px;text-align:center;text-decoration:none;font-weight:800;font-size:12px'>📄 Set Marks</a></div></div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall()
    con.close()
    header = school_header(school, name, "students", is_impersonating=is_imp)
    body = students_manager_html(students, classes, school["name"], is_global=False)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/students/add")
def add_student(request: Request, admission_no: str = Form(...), assessment_no: str = Form(""), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), category: str = Form("Day"), guardian_name: str = Form(""), parent_phone: str = Form("")):
    school = get_school_obj(request); con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO students (school_id, admission_no, assessment_no, name, class_id, gender, parent_phone, category, guardian_name) VALUES (?,?,?,?,?,?,?,?,?)", (school["id"], admission_no.strip().upper(), assessment_no.strip().upper(), student_name.strip().upper(), class_id, gender.strip(), parent_phone.strip(), category.strip(), guardian_name.strip().upper()))
    con.commit(); con.close(); return RedirectResponse("/school/students",303)
@app.get("/school/students/delete/{sid}")
def del_stud(sid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=?", (sid,)); con.commit(); con.close(); return RedirectResponse("/school/students",303)

@app.get("/school/dean-settings", response_class=HTMLResponse)
def dean_settings(request: Request, tab: str = "terms"):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY year DESC, id DESC", (school["id"],)); terms = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (school["id"],)); subjects = cur.fetchall()
    cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name", (school["id"],)); teachers = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT ta.*, t.name as tname, s.name as sname, c.name as cname FROM teacher_allocations ta LEFT JOIN teachers t ON ta.teacher_id=t.id LEFT JOIN subjects s ON ta.subject_id=s.id LEFT JOIN classes c ON ta.class_id=c.id WHERE ta.school_id=? ORDER BY t.name", (school["id"],)); allocs = cur.fetchall()
    con.close()
    header = school_header(school, name, "dean-settings", is_impersonating=is_imp)
    body = dean_manager_html(terms, subjects, teachers, classes, allocs, 0, school["name"], is_global=False, active_tab=tab)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/dean-settings/add-term")
def school_add_term(request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO terms (school_id, term_name, year, start_date, end_date) VALUES (?,?,?,?,?)", (school["id"], term_name, year.strip(), start_date, end_date)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=terms",303)
@app.post("/school/dean-settings/edit-term/{tid}")
def school_edit_term(tid: int, request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("UPDATE terms SET term_name=?, year=?, start_date=?, end_date=? WHERE id=?", (term_name, year.strip(), start_date, end_date, tid)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=terms",303)
@app.get("/school/dean-settings/delete-term/{tid}")
def school_del_term(tid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM terms WHERE id=?", (tid,)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=terms",303)
@app.post("/school/dean-settings/add-subject")
def school_dean_add_subject(request: Request, subject_name: str = Form(...), code: str = Form(""), initial: str = Form("")):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO subjects (school_id, name, code, initial) VALUES (?,?,?,?)", (school["id"], subject_name.strip().upper(), code.strip().upper(), initial.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=subjects",303)
@app.get("/school/dean-settings/delete-subject/{sid}")
def school_dean_del_subject(sid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE id=?", (sid,)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=subjects",303)
@app.post("/school/dean-settings/allocate")
def school_dean_allocate(request: Request, teacher_id: int = Form(...), subject_id: int = Form(...), class_id: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO teacher_allocations (school_id, teacher_id, subject_id, class_id) VALUES (?,?,?,?)", (school["id"], teacher_id, subject_id, class_id)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=allocation",303)
@app.get("/school/dean-settings/delete-alloc/{aid}")
def school_del_alloc(aid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM teacher_allocations WHERE id=?", (aid,)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=allocation",303)
@app.post("/school/dean-settings/promote")
def school_promote(request: Request, from_class: int = Form(...), to_class: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("UPDATE students SET class_id=? WHERE school_id=? AND class_id=?", (to_class, school["id"], from_class)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings?tab=promote",303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px 12px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><a href='/school/classes/delete/{c['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No classes</td></tr>"
    header = school_header(school, name, "classes", is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>🏫 Classes & Streams ({len(classes)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Class</b><form method='post' action='/school/classes/add'><input name='class_name' required placeholder='Class Name *' class='input-field'><input name='stream' required placeholder='Stream *' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Class</button></form></div></div></div></div></div></body></html>")
@app.post("/school/classes/add")
def add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (school["id"], class_name.strip().upper(), stream.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/classes",303)
@app.get("/school/classes/delete/{cid}")
def del_class(cid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=?", (cid,)); con.commit(); con.close(); return RedirectResponse("/school/classes",303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY year DESC, id DESC", (school["id"],))
    exams = cur.fetchall(); con.close()
    header = school_header(school, name, "exams", is_impersonating=is_imp)
    body = exam_manager_html(exams, school["name"], is_global=False)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip()))
    ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit (school_id, user_email, action, details, timestamp) VALUES (?,?,?,?,?)", (school["id"], request.session.get("email",""), "ADD EXAM", f"{exam_name} {year}", ts))
    con.commit(); con.close()
    return RedirectResponse("/school/exams",303)
@app.post("/school/exams/edit/{eid}")
def edit_exam(eid: int, request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE exams SET name=?, term=?, year=?, exam_type=? WHERE id=?", (exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip(), eid))
    con.commit(); con.close()
    return RedirectResponse("/school/exams",303)
@app.get("/school/exams/delete/{eid}")
def del_exam(eid: int):
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM exams WHERE id=?", (eid,)); con.commit(); con.close()
    return RedirectResponse("/school/exams",303)
    @app.get("/school/teachers", response_class=HTMLResponse)
def teachers_page(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY id DESC", (school["id"],)); teachers = cur.fetchall(); con.close()
    header = school_header(school, name, "teachers", is_impersonating=is_imp)
    body = staff_manager_html(teachers, school["name"], is_global=False)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/teachers/add")
def add_teacher(request: Request, name: str = Form(...), tsc_no: str = Form(""), id_no: str = Form(...), gender: str = Form(...), role: str = Form(...), phone: str = Form(...), email: str = Form(""), employment_type: str = Form("Teaching")):
    school = get_school_obj(request)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO teachers (school_id, name, email, phone, tsc_no, gender, id_no, role, employment_type) VALUES (?,?,?,?,?,?,?,?,?)", (school["id"], name.strip().upper(), email.strip(), phone.strip(), tsc_no.strip(), gender.strip(), id_no.strip(), role.strip(), employment_type.strip()))
    con.commit(); con.close()
    return RedirectResponse("/school/teachers",303)
@app.get("/school/teachers/delete/{tid}")
def del_teacher(tid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM teachers WHERE id=?", (tid,)); con.commit(); con.close(); return RedirectResponse("/school/teachers",303)

# === RECORD MARKS EXACT - ELIMIKASASA STYLE ===
@app.get("/school/record-marks", response_class=HTMLResponse)
def school_record_marks(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name", (school["id"],)); classes = cur.fetchall()
    cur.execute("SELECT DISTINCT stream FROM classes WHERE school_id=? AND stream!='' ORDER BY stream", (school["id"],)); streams = [r["stream"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT year FROM terms WHERE school_id=? ORDER BY year DESC", (school["id"],)); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years:
        cur.execute("SELECT DISTINCT year FROM exams WHERE school_id=? ORDER BY year DESC", (school["id"],)); years = [r["year"] for r in cur.fetchall() if r["year"]]
    if not years: years = [str(datetime.now().year)]
    cur.execute("SELECT DISTINCT term_name FROM terms WHERE school_id=? ORDER BY term_name", (school["id"],)); terms_list = [r["term_name"] for r in cur.fetchall()]
    if not terms_list: terms_list = ["Term 1","Term 2","Term 3"]
    cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school["id"],)); exams = cur.fetchall()
    cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (school["id"],)); subjects = cur.fetchall()
    con.close()
    header = school_header(school, name, "record-marks", is_impersonating=is_imp)
    opts_class = "".join([f"<option value='{c['name']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    opts_stream = "".join([f"<option value='{st}'>{st}</option>" for st in streams]) or "<option value=''>ALL</option>"
    opts_year = "".join([f"<option>{y}</option>" for y in years])
    opts_term = "".join([f"<option>{t}</option>" for t in terms_list])
    opts_exam = "".join([f"<option value='{e['id']}'>{e['name']}</option>" for e in exams])
    opts_subj = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects])
    html = f"""<div style='padding:20px;max-width:1400px;margin:auto'><h1 style='margin:0;font-size:22px;font-weight:900'>✏️ Record Marks</h1><p style='color:#64748b;font-size:13px'>Select filters — exact window as your screenshot</p><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-top:14px;display:grid;grid-template-columns:repeat(3,1fr);gap:12px'><form method='post' action='/school/record-marks/load-exact' style='display:contents'><div><label style='font-size:11px;font-weight:700'>Class *</label><select name='class_name' required class='input-field'>{opts_class}</select></div><div><label style='font-size:11px;font-weight:700'>Stream *</label><select name='stream' required class='input-field'>{opts_stream}</select></div><div><label style='font-size:11px;font-weight:700'>Year *</label><select name='year' required class='input-field'>{opts_year}</select></div><div><label style='font-size:11px;font-weight:700'>Term *</label><select name='term' required class='input-field'>{opts_term}</select></div><div><label style='font-size:11px;font-weight:700'>Exam *</label><select name='exam_id' required class='input-field'>{opts_exam}</select></div><div><label style='font-size:11px;font-weight:700'>Subject *</label><select name='subject_id' required class='input-field'>{opts_subj}</select></div><button style='grid-column:span 3;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:800'>🔍 Load Students (Exact)</button></form></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{html}</div></div></body></html>")

@app.post("/school/record-marks/load-exact", response_class=HTMLResponse)
def school_record_load_exact(request: Request, class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), exam_id: int = Form(...), subject_id: int = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (school["id"], class_name.upper(), stream.upper()))
    cl = cur.fetchone()
    if not cl:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? LIMIT 1", (school["id"], class_name.upper()))
        cl = cur.fetchone()
    class_id = cl["id"] if cl else 0
    cur.execute("SELECT id, admission_no, name FROM students WHERE school_id=? AND class_id=? ORDER BY CAST(admission_no AS INTEGER) ASC, name", (school["id"], class_id))
    students_raw = cur.fetchall()
    cur.execute("SELECT name FROM subjects WHERE id=?", (subject_id,)); subj_row = cur.fetchone(); subject_name = subj_row["name"] if subj_row else "SUBJECT"
    cur.execute("SELECT name FROM exams WHERE id=?", (exam_id,)); exam_row = cur.fetchone(); exam_name = exam_row["name"] if exam_row else "EXAM"
    cur.execute("SELECT out_of FROM set_marks_config WHERE school_id=? AND class_name=? AND stream=? AND year=? AND term=? AND exam_id=? AND subject_id=?", (school["id"], class_name.upper(), stream.upper(), year, term, exam_id, subject_id))
    cfg = cur.fetchone()
    out_of = cfg["out_of"] if cfg else 100
    cur.execute("SELECT student_id, marks FROM marks WHERE school_id=? AND class_id=? AND exam_id=? AND subject_id=?", (school["id"], class_id, exam_id, subject_id))
    existing = {str(r["student_id"]): r["marks"] for r in cur.fetchall()}
    con.close()
    students = []
    filled = 0
    for s in students_raw:
        m = existing.get(str(s["id"]))
        if m is not None and m!= "":
            filled += 1
        students.append({"id": s["id"], "admission_no": s["admission_no"] or s["id"], "name": s["name"], "marks": m if m is not None else ""})
    total = len(students)
    header = school_header(school, name, "record-marks", is_impersonating=is_imp)
    body = record_marks_exact_html(students, subject_name, exam_name, class_name, stream, out_of, total, filled, school["name"], exam_id, subject_id, year, term)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{body}</div></div></body></html>")

@app.post("/school/record-marks/auto-save")
def auto_save_mark(request: Request, student_id: int = Form(...), exam_id: int = Form(...), subject_id: int = Form(...), class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), out_of: int = Form(...), marks: str = Form("")):
    if "email" not in request.session:
        return JSONResponse({"ok": False})
    school = get_school_obj(request)
    if not school:
        return JSONResponse({"ok": False})
    try:
        m_val = float(marks)
        if m_val > out_of: m_val = out_of
        if m_val < 0: m_val = 0
    except:
        return JSONResponse({"ok": False})
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (school["id"], class_name.upper(), stream.upper()))
    cl = cur.fetchone()
    if not cl:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? LIMIT 1", (school["id"], class_name.upper()))
        cl = cur.fetchone()
    class_id = cl["id"] if cl else 0
    cur.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=?", (school["id"], student_id, subject_id, exam_id))
    ex = cur.fetchone()
    if ex:
        cur.execute("UPDATE marks SET marks=?, class_id=?, year=?, term=? WHERE id=?", (m_val, class_id, year, term, ex["id"]))
    else:
        cur.execute("INSERT INTO marks (school_id, student_id, subject_id, exam_id, class_id, marks, year, term) VALUES (?,?,?,?,?,?,?,?)", (school["id"], student_id, subject_id, exam_id, class_id, m_val, year, term))
    con.commit(); con.close()
    return JSONResponse({"ok": True, "saved": m_val})

@app.post("/school/record-marks/load", response_class=HTMLResponse)
def school_record_load_old(request: Request, class_name: str = Form(...), stream: str = Form(...), year: str = Form(...), term: str = Form(...), exam_id: int = Form(...), subject_id: int = Form(...)):
    return RedirectResponse("/school/record-marks",303)

# === SYSTEM SETTINGS ===
@app.get("/school/system-settings/{sub}", response_class=HTMLResponse)
def school_system_settings(sub: str, request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school_obj = get_school_obj(request)
    if not school_obj: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools WHERE id=?", (school_obj["id"],)); school = cur.fetchone()
    cur.execute("SELECT * FROM users WHERE school_id=? ORDER BY id DESC", (school_obj["id"],)); users = cur.fetchall()
    cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school_obj["id"],)); classes = cur.fetchall()
    cur.execute("SELECT * FROM system_audit WHERE school_id=? ORDER BY id DESC LIMIT 200", (school_obj["id"],)); audit = cur.fetchall()
    cur.execute("SELECT * FROM billing WHERE school_id=? ORDER BY id DESC", (school_obj["id"],)); bills = cur.fetchall()
    con.close()
    header = school_header(school_obj, name, f"system-settings/{sub}", is_impersonating=is_imp)
    base_path = "/school/system-settings"
    if sub=="school-profile":
        panel = f"""<div style='display:grid;grid-template-columns:1.2fr 0.8fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><h3 style='margin:0 0 12px'>🏢 School Profile</h3><form method='post' action='{base_path}/update-profile' style='display:grid;gap:10px'><input name='name' value="{school['name']}" class='input-field'><input name='email' value="{school['email']}" class='input-field'><input name='location' value="{school['location']}" class='input-field'><input name='phone' value="{school['phone']}" class='input-field'><input name='principal' value="{school['principal']}" class='input-field'><input name='school_type' value="{school['school_type']}" class='input-field'><button class='add-btn'>💾 Update Profile</button></form></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:18px'><h3>📊 Info</h3><div>🔑 {school['code']}</div><div>👥 Users: {len(users)}</div></div></div>"""
    elif sub=="classes":
        rows = "".join([f"<tr><td style='padding:10px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><a href='{base_path}/delete-class/{c['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No classes</td></tr>"
        panel = f"""<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px'><div style='padding:14px'><b>🏫 Classes ({len(classes)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><b>➕ Add Class</b><form method='post' action='{base_path}/add-class'><input name='class_name' required placeholder='Class' class='input-field'><input name='stream' required placeholder='Stream' class='input-field'><button class='add-btn'>Add</button></form></div></div>"""
    elif sub=="user-management":
        urows = "".join([f"<tr><td style='padding:10px'>{u['full_name']}</td><td>{u['email']}</td><td>{u['role']}</td><td><a href='{base_path}/delete-user/{u['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for u in users]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No users</td></tr>"
        panel = f"""<div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:16px'><div style='padding:14px'><b>👥 Users ({len(users)})</b></div><table style='width:100%'><tbody>{urows}</tbody></table></div><div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px'><b>➕ Add User</b><form method='post' action='{base_path}/add-user'><input name='full_name' required class='input-field' placeholder='Name'><input name='email' required class='input-field' placeholder='Email'><input name='password' required class='input-field' placeholder='Pass'><select name='role' class='input-field'><option>teacher</option><option>school_admin</option></select><button class='add-btn'>Create</button></form></div></div>"""
    elif sub=="system-audit":
        audit_rows = "".join([f"<tr><td style='padding:10px'>{a['timestamp'] or ''}</td><td>{a['user_email'] or ''}</td><td>{a['action'] or ''}</td><td>{a['details'] or ''}</td></tr>" for a in audit[:100]]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No logs</td></tr>"
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px'><div style='padding:14px;display:flex;justify-content:space-between'><b>📈 Audit</b><a href='{base_path}/audit/clear' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:8px;text-decoration:none'>Clear</a></div><table style='width:100%'><tbody>{audit_rows}</tbody></table></div>"""
    elif sub=="billing-payments":
        brows = "".join([f"<tr><td style='padding:10px'>{b['amount']}</td><td>{b['status']}</td><td>{b['due_date'] or ''}</td></tr>" for b in bills]) or "<tr><td colspan='3' style='padding:30px;text-align:center'>No invoices</td></tr>"
        panel = f"""<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px'><h3>💳 Billing</h3><form method='post' action='{base_path}/billing/add'><input name='amount' required placeholder='Amount' class='input-field' style='width:200px'><select name='status' class='input-field' style='width:200px'><option>Paid</option><option>Pending</option></select><input name='due_date' type='date' class='input-field' style='width:200px'><button class='add-btn' style='width:200px'>Add</button></form><table style='width:100%;margin-top:10px'><tbody>{brows}</tbody></table></div>"""
    else:
        panel = "<div style='background:white;border-radius:16px;padding:40px;text-align:center'>🚧 Coming Soon</div>"
    def pill(tab, label, icon):
        active_style = "background:#0f172a;color:white" if sub==tab else "background:#f8fafc;color:#475569;border:1px solid #e2e8f0"
        return f"<a href='/school/system-settings/{tab}' style='padding:8px 12px;border-radius:10px;text-decoration:none;font-size:12px;font-weight:700;{active_style}'>{icon} {label}</a>"
    pills = f"<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:12px;margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap'>{pill('school-profile','School Profile','🏢')}{pill('classes','Classes','🏫')}{pill('user-management','User Management','👥+')}{pill('system-audit','System Audit','📈')}{pill('billing-payments','Billing & Payments','💳')}</div>"
    content = f"<div style='padding:20px;max-width:1450px;margin:auto'><h1 style='margin:0;font-size:26px;font-weight:900'>⚙️ System Settings</h1>{pills}{panel}</div>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{content}</div></div></body></html>")
@app.post("/school/system-settings/update-profile")
def sys_update_profile(request: Request, name: str = Form(...), email: str = Form(""), location: str = Form(...), phone: str = Form(...), principal: str = Form(...), school_type: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("UPDATE schools SET name=?, email=?, location=?, phone=?, principal=?, school_type=? WHERE id=?", (name.strip().upper(), email.strip(), location.strip(), phone.strip(), principal.strip(), school_type.strip(), school_obj["id"])); con.commit(); con.close(); return RedirectResponse("/school/system-settings/school-profile",303)
@app.post("/school/system-settings/add-class")
def sys_add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (school_obj["id"], class_name.strip().upper(), stream.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/system-settings/classes",303)
@app.get("/school/system-settings/delete-class/{cid}")
def sys_del_class(cid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE id=?", (cid,)); con.commit(); con.close(); return RedirectResponse("/school/system-settings/classes",303)
@app.post("/school/system-settings/add-user")
def sys_add_user(request: Request, full_name: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)", (email.strip(), password.strip(), role.strip(), full_name.strip(), school_obj["id"])); con.commit(); con.close(); return RedirectResponse("/school/system-settings/user-management",303)
@app.get("/school/system-settings/delete-user/{uid}")
def sys_del_user(uid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM users WHERE id=?", (uid,)); con.commit(); con.close(); return RedirectResponse("/school/system-settings/user-management",303)
@app.get("/school/system-settings/audit/clear")
def sys_audit_clear(request: Request):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM system_audit WHERE school_id=?", (school_obj["id"],)); con.commit(); con.close(); return RedirectResponse("/school/system-settings/system-audit",303)
@app.post("/school/system-settings/billing/add")
def sys_billing_add(request: Request, amount: str = Form(...), status: str = Form(...), due_date: str = Form(...)):
    school_obj = get_school_obj(request); con = get_db(); cur = con.cursor(); ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO billing (school_id, amount, status, due_date, created_at) VALUES (?,?,?,?,?)", (school_obj["id"], amount.strip(), status.strip(), due_date.strip(), ts)); con.commit(); con.close(); return RedirectResponse("/school/system-settings/billing-payments",303)

@app.get("/super/global-control/dashboard", response_class=HTMLResponse)
def global_dashboard(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students"); sc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM classes"); cc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM exams"); ec = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM teachers"); tc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM set_marks_config"); setc = cur.fetchone()["c"]
    con.close()
    header = global_header(name, "dashboard")
    html = f"""<div style='padding:18px;max-width:1400px;margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%);border-radius:18px;padding:22px 24px;color:white;display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'><div><div style='font-size:22px;font-weight:900'>DaviSchool — GLOBAL CONTROL 🚀</div><div style='font-size:12px;color:#bfdbfe'>Set Marks: {setc} | Exams: {ec}</div></div><div style='text-align:right'><div style='font-size:34px;font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students</div></div></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px'><a href='/super/global-control/students' class='ds-card'><div style='font-size:11px;color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:30px;font-weight:900'>{sc}</div></a><a href='/super/global-control/classes' class='ds-card'><div style='font-size:11px;color:#64748b'>🏫 CLASSES</div><div style='font-size:30px;font-weight:900'>{cc}</div></a><a href='/super/global-control/exams' class='ds-card'><div style='font-size:11px;color:#64748b'>📝 EXAMS</div><div style='font-size:30px;font-weight:900'>{ec}</div></a><a href='/super/global-control/teachers' class='ds-card'><div style='font-size:11px;color:#64748b'>👨‍🏫 STAFF</div><div style='font-size:30px;font-weight:900'>{tc}</div></a></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

@app.get("/super/global-control/exams", response_class=HTMLResponse)
def global_exams(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM exams GROUP BY name, year ORDER BY year DESC, id DESC")
    exams = cur.fetchall(); con.close()
    header = global_header(name, "exams")
    body = exam_manager_html(exams, "ALL SCHOOLS — Global Control", is_global=True)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/super/global-control/exams/add")
def global_add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM exams WHERE school_id=? AND name=? AND year=?", (sch["id"], exam_name.strip().upper(), year.strip()))
        if not cur.fetchone():
            cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (sch["id"], exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip()))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/exams",303)
@app.post("/super/global-control/exams/edit/{eid}")
def global_edit_exam(eid: int, request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name, year FROM exams WHERE id=?", (eid,)); old = cur.fetchone()
    if old:
        cur.execute("UPDATE exams SET name=?, term=?, year=?, exam_type=? WHERE name=? AND year=?", (exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip(), old["name"], old["year"]))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/exams",303)
@app.get("/super/global-control/exams/delete/{eid}")
def global_del_exam(eid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name, year FROM exams WHERE id=?", (eid,)); old = cur.fetchone()
    if old:
        cur.execute("DELETE FROM exams WHERE name=? AND year=?", (old["name"], old["year"]))
    con.commit(); con.close()
    return RedirectResponse("/super/global-control/exams",303)

@app.get("/super/global-control/students", response_class=HTMLResponse)
def global_students(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "students")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes GROUP BY name, stream ORDER BY name"); classes = cur.fetchall()
    cur.execute("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id=c.id ORDER BY s.id DESC LIMIT 500"); students = cur.fetchall()
    con.close()
    body = students_manager_html(students, classes, "ALL SCHOOLS — Global Control", is_global=True)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.get("/super/global-control/teachers", response_class=HTMLResponse)
def global_teachers(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "teachers")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM teachers ORDER BY id DESC"); teachers = cur.fetchall(); con.close()
    body = staff_manager_html(teachers, "ALL SCHOOLS — Global Control", is_global=True)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")

@app.get("/super/global-control/system-settings/{sub}", response_class=HTMLResponse)
def global_system_settings(sub: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM schools LIMIT 1"); school = cur.fetchone()
    if not school:
        con.close()
        header = global_header(name, f"system-settings/{sub}")
        return HTMLResponse(f"<html><body>{header}<div style='padding:40px;text-align:center'>No school yet</div></div></div></body></html>")
    cur.execute("SELECT * FROM users ORDER BY id DESC"); users = cur.fetchall()
    cur.execute("SELECT * FROM system_audit ORDER BY id DESC LIMIT 100"); audit = cur.fetchall()
    con.close()
    header = global_header(name, f"system-settings/{sub}")
    panel = f"<div style='background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px'><h3>⚙️ Global — {sub.upper()}</h3><p style='color:#64748b'>Total Users: {len(users)} | Audit: {len(audit)}</p></div>"
    return HTMLResponse(f"<html><body>{header}<div style='padding:20px'>{panel}</div></div></div></body></html>")

@app.get("/super/global-control/{path}", response_class=HTMLResponse)
def global_other(path: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma"); header = global_header(name, path)
    return HTMLResponse(f"<html><body>{header}<div style='padding:30px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:40px;text-align:center'><h3>🚧 {path.upper()} — Coming Soon</h3><a href='/super/global-control/dashboard' style='padding:10px 16px;background:#0f172a;color:white;border-radius:10px;text-decoration:none'>⬅️ Back</a></div></div></div></div></body></html>")

@app.get("/school/{path}", response_class=HTMLResponse)
def school_other(path: str, request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    header = school_header(school, name, path, is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:30px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:40px;text-align:center'><h3>🚧 {path.upper()} — Coming Soon</h3><a href='/school/dashboard' style='padding:10px 16px;background:#0f172a;color:white;border-radius:10px;text-decoration:none'>⬅️ Back</a></div></div></div></div></body></html>")

@app.exception_handler(StarletteHTTPException)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        if request.url.path.startswith("/api") or "application/json" in request.headers.get("accept",""):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return RedirectResponse("/", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
