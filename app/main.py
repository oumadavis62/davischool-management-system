from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
import random
from datetime import datetime
from zoneinfo import ZoneInfo

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davischool-v50-welcome-restored-no-ranking-reports")
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
    try:
        cur.execute("ALTER TABLE teachers ADD COLUMN employment_type TEXT")
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
    return f"""<style>.do-avatar{{width:36px;height:36px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;cursor:pointer;border:2px solid #e2e8f0}}.dropdown-item{{display:flex;align-items:center;gap:10px;padding:11px 14px;text-decoration:none;font-size:13px}}.dropdown-item:hover{{background:#0f172a;color:white}}</style><div style='background:white;border-bottom:1px solid #e2e8f0;padding:10px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:14px'>🏫 Davischool Platform (Super Admin)</b><div style='font-size:11px;color:#64748b'>{name} • Super Admin</div></div><div style='position:relative'><div onclick='toggleProfileMenu()' class='do-avatar'>{initials}</div><div id='profileDropdown' style='display:none;position:absolute;right:0;top:44px;background:white;border:1px solid #e2e8f0;border-radius:12px;width:220px;box-shadow:0 10px 25px rgba(0,0,0,0.12);z-index:1000;overflow:hidden'><div style='padding:14px;border-bottom:1px solid #f1f5f9;background:#f8fafc'><div style='font-weight:700;font-size:13px'>{name}</div><div style='font-size:11px;color:#64748b'>{email}</div></div><a href='/profile?tab=personal' class='dropdown-item' style='color:#0f172a'>👤 Profile</a><a href='/super/global-control/dashboard' class='dropdown-item' style='color:#0f172a'>🌍 Global Control</a><a href='/logout' class='dropdown-item' style='color:#dc2626'>🚪 Logout</a></div></div></div><script>function toggleProfileMenu(){{let m=document.getElementById('profileDropdown'); m.style.display=m.style.display==='none'||m.style.display===''? 'block':'none';}}</script>"""

def school_header(school, name, active="dashboard", is_impersonating=False):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "S"
    academic_pages = ["dean-settings","exams","marks","subject-allocation","marksheets","analysis","spreadsheet","sba"]
    is_academic_active = active in academic_pages
    dropdown_display = "block" if is_academic_active else "none"
    arrow = "⌃" if is_academic_active else "⌄"
    academic_bg = "background:#0f172a;color:white" if is_academic_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    def nav(link, icon, label):
        is_active = "background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569;background:transparent"
        return f"<a href='/school/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active}'>{icon} {label}</a>"
    def sub_nav(link, icon, label):
        is_sel = "background:#e2e8f0;color:#0f172a;font-weight:800;border-radius:8px" if active==link else "color:#475569"
        return f"<a href='/school/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:2px;{is_sel}'>{icon} {label}</a>"
    banner = f"""<div style='background:#f59e0b;color:#0f172a;padding:8px 20px;text-align:center;font-weight:800;font-size:12px'>⚠️ Viewing as {school['name']} — <a href='/super/back-to-admin' style='background:#0f172a;color:white;padding:6px 12px;border-radius:8px;text-decoration:none;font-size:11px'>🔙 Back to Super Admin</a></div>""" if is_impersonating else ""
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 1"); notice = cur.fetchone(); con.close()
    notice_banner = f"""<div style='background:#0f172a;color:white;padding:8px 20px;text-align:center;font-size:12px'>📢 {notice['message']}</div>""" if notice else ""
    return f"""<style>.nav-item:hover{{background:#f1f5f9!important;color:#0f172a!important}}.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.academic-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:800;margin-bottom:4px;{academic_bg}}}.academic-header:hover{{background:#f1f5f9!important}}</style><div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🏫</div><div><b style='font-size:13px'>{school['name'][:20].upper()}</b><div style='font-size:10px;color:#64748b'>🔑 {school['code']} | {school['location']}</div></div></div></div>{nav('dashboard','📊','Dashboard')}{nav('students','🎓','Students Manager')}{nav('classes','🏫','Classes & Streams')}{nav('subjects','📚','Subjects')}<div style='margin-bottom:4px'><div class='academic-header' onclick='toggleAcademic()'><span>📖 Academic Manager</span><span id='academicArrow'>{arrow}</span></div><div id='academicDropdown' style='display:{dropdown_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('dean-settings','⚙️','Dean Settings')}{sub_nav('exams','🔧','Exam Settings')}{sub_nav('marks','📄','Set Marks')}{sub_nav('subject-allocation','📋','Subject Allocation')}{sub_nav('marks','✏️','Record Marks')}{sub_nav('marks','📄','Edit Marks')}{sub_nav('marksheets','☰','Marks Status')}{sub_nav('analysis','📊','Exam Analysis')}{sub_nav('spreadsheet','📄','Spreadsheet')}{sub_nav('sba','📋','SBA (KNEC CBA)')}</div></div>{nav('teachers','👨‍🏫','Staff Manager')}{nav('timetable','🗓️','Smart Timetable')}{nav('fees','💰','Fees & Finance')}{nav('sms','💬','Bulk SMS Parents')}<div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/logout' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'>{banner}{notice_banner}<div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>{school['name']} (Code: {school['code']})</b></div><div style='display:flex;align-items:center;gap:12px'><div style='width:28px;height:28px;background:#dbeafe;color:#1e40af;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px'>{initials}</div><div style='font-size:11px'><b>{name}</b></div></div></div><script>function toggleAcademic(){{let d=document.getElementById('academicDropdown'); let a=document.getElementById('academicArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}</script>"""

def global_header(name, active="dashboard"):
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    academic_pages = ["dean-settings","exams","marks","subject-allocation","marksheets","analysis","spreadsheet","sba"]
    is_academic_active = active in academic_pages
    dropdown_display = "block" if is_academic_active else "none"
    arrow = "⌃" if is_academic_active else "⌄"
    academic_bg = "background:#0f172a;color:white" if is_academic_active else "background:white;color:#0f172a;border:1px solid #e2e8f0"
    def nav(link, icon, label):
        is_active = "background:#0f172a;color:white;font-weight:800" if active==link else "color:#475569;background:transparent"
        return f"<a href='/super/global-control/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;margin-bottom:4px;{is_active}'>{icon} {label}</a>"
    def sub_nav(link, icon, label):
        is_sel = "background:#e2e8f0;color:#0f172a;font-weight:800;border-radius:8px" if active==link else "color:#475569"
        return f"<a href='/super/global-control/{link}' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:13px;margin-bottom:2px;{is_sel}'>{icon} {label}</a>"
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM global_notices ORDER BY id DESC LIMIT 1"); notice = cur.fetchone(); con.close()
    notice_banner = f"""<div style='background:#0f172a;color:white;padding:8px 20px;text-align:center;font-size:12px'>📢 {notice['message']}</div>""" if notice else ""
    return f"""<style>.nav-item:hover{{background:#f1f5f9!important;color:#0f172a!important}}.ds-card{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;text-decoration:none;color:#0f172a;display:block}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}.academic-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:800;margin-bottom:4px;{academic_bg}}}.academic-header:hover{{background:#f1f5f9!important}}</style><div style='display:flex;min-height:100vh'><div style='width:260px;background:white;border-right:1px solid #e2e8f0;padding:16px;position:sticky;top:0;height:100vh;overflow-y:auto'><div style='padding:10px 6px 16px;border-bottom:1px solid #f1f5f9;margin-bottom:12px'><div style='display:flex;align-items:center;gap:10px'><div style='width:40px;height:40px;background:#0f172a;color:white;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800'>🌍</div><div><b style='font-size:13px'>GLOBAL CONTROL</b><div style='font-size:10px;color:#64748b'>ALL SCHOOLS • Automatic</div></div></div></div>{nav('dashboard','📊','Dashboard')}{nav('students','🎓','Students Manager')}{nav('classes','🏫','Classes & Streams')}{nav('subjects','📚','Subjects')}<div style='margin-bottom:4px'><div class='academic-header' onclick='toggleAcademic()'><span>📖 Academic Manager</span><span id='academicArrow'>{arrow}</span></div><div id='academicDropdown' style='display:{dropdown_display};margin-left:8px;border-left:1px solid #e2e8f0;padding-left:10px;margin-bottom:6px'>{sub_nav('dean-settings','⚙️','Dean Settings')}{sub_nav('exams','🔧','Exam Settings')}{sub_nav('marks','📄','Set Marks')}{sub_nav('subject-allocation','📋','Subject Allocation')}{sub_nav('marks','✏️','Record Marks')}{sub_nav('marks','📄','Edit Marks')}{sub_nav('marksheets','☰','Marks Status')}{sub_nav('analysis','📊','Exam Analysis')}{sub_nav('spreadsheet','📄','Spreadsheet')}{sub_nav('sba','📋','SBA (KNEC CBA)')}</div></div>{nav('teachers','👨‍🏫','Staff Manager')}{nav('timetable','🗓️','Smart Timetable')}{nav('fees','💰','Fees & Finance')}{nav('sms','💬','Bulk SMS Parents')}<div style='margin-top:16px;border-top:1px solid #f1f5f9;padding-top:12px'><a href='/dashboard' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#0f172a;background:#f8fafc;font-weight:700'>⬅️ Back to Super Admin</a><a href='/logout' class='nav-item' style='display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;text-decoration:none;font-size:13px;color:#dc2626'>🚪 Logout</a></div></div><div style='flex:1;background:#f8fafc'>{notice_banner}<div style='background:white;border-bottom:1px solid #e2e8f0;padding:12px 20px;display:flex;justify-content:space-between;align-items:center'><div><b style='font-size:13px'>GLOBAL CONTROL (ALL SCHOOLS) — Same as School Side — Automatic</b><div style='font-size:10px;color:#64748b'>Any change here updates all schools instantly</div></div><div style='display:flex;align-items:center;gap:12px'><div style='width:28px;height:28px;background:#0f172a;color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px'>{initials}</div><div style='font-size:11px'><b>{name}</b> <span style="background:#0f172a;color:white;padding:2px 6px;border-radius:6px;font-size:9px">SUPER</span></div></div></div><script>function toggleAcademic(){{let d=document.getElementById('academicDropdown'); let a=document.getElementById('academicArrow'); if(d.style.display==='none'||d.style.display===''){{d.style.display='block'; a.innerText='⌃';}} else {{d.style.display='none'; a.innerText='⌄';}}}}</script>"""

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
        rows_html += f"""<tr class='staff-row' data-role="{(t['role'] or '').lower()}" data-gender="{(t['gender'] or '').lower()}" data-employment="{(t['employment_type'] or ('teaching' if (t['role'] or '').lower() in teaching_roles else 'non-teaching')).lower()}" data-search="{(t['name'] or '').lower()} {(t['id_no'] or '').lower()} {(t['email'] or '').lower()} {(t['tsc_no'] or '').lower()}"><td style='padding:14px 12px;font-size:13px'>{i}</td><td style='padding:14px 12px;font-size:13px;font-weight:600'>{t['id_no'] or t['tsc_no'] or '—'}</td><td style='padding:14px 12px;font-size:13px;font-weight:700'>{t['name']}</td><td style='padding:14px 12px;font-size:13px'>{t['gender'] or '—'}</td><td style='padding:14px 12px;font-size:13px'><span style='background:#f1f5f9;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700'>{t['role'] or 'Teacher'}</span></td><td style='padding:14px 12px;font-size:13px'>{t['phone'] or '—'}</td><td style='padding:14px 12px;font-size:13px;color:#475569'>{t['email'] or '—'}</td><td style='padding:14px 12px'><div style='display:flex;gap:6px'><a href='{" /super/global-control/teachers/delete/" if is_global else "/school/teachers/delete/"}{t['id']}' style='background:#fee2e2;color:#991b1b;padding:6px 10px;border-radius:8px;text-decoration:none;font-size:12px'>🗑️</a></div></td></tr>"""
    if not rows_html:
        rows_html = "<tr><td colspan='8' style='padding:40px;text-align:center;color:#94a3b8'>No staff yet — click + Add Staff</td></tr>"
    return f"""
    <style>
  .staff-card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:20px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 1px 2px rgba(0,0,0,0.04)}}
  .staff-icon{{width:44px;height:44px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px}}
  .filter-select{{padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;min-width:140px}}
  .action-btn{{padding:10px 14px;border:1px solid #e2e8f0;border-radius:10px;background:white;font-size:13px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px}}
  .add-staff-btn{{background:#0f172a;color:white;padding:12px 18px;border:none;border-radius:10px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:8px}}
  .modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;align-items:center;justify-content:center;padding:20px}}
  .modal.active{{display:flex}}
    </style>
    <div style='padding:22px;max-width:1500px;margin:auto'>
      <div style='margin-bottom:18px'><h1 style='margin:0;font-size:28px;font-weight:900'>Staff</h1><p style='margin:6px 0 0;color:#64748b;font-size:14px'>Manage staff records and assignments — {school_name}</p></div>
      <div style='display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px'>
        <div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Total Staff</div><div style='font-size:28px;font-weight:900;margin-top:8px'>{total}</div></div><div class='staff-icon' style='background:#eff6ff;color:#2563eb'>👥</div></div>
        <div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Male / Female</div><div style='font-size:24px;font-weight:900;margin-top:8px'><span style='color:#2563eb'>{male}</span><span style='color:#64748b'> / </span><span style='color:#db2777'>{female}</span></div></div><div class='staff-icon' style='background:#faf5ff;color:#9333ea'>👤+</div></div>
        <div class='staff-card'><div><div style='font-size:13px;color:#64748b;font-weight:600'>Teaching / Non-Teaching</div><div style='font-size:24px;font-weight:900;margin-top:8px'><span style='color:#059669'>{teaching}</span><span style='color:#64748b'> / </span><span style='color:#ea580c'>{non_teaching}</span></div></div><div class='staff-icon' style='background:#ecfdf5;color:#059669'>💼</div></div>
        <div class='staff-card' style='flex-direction:column;align-items:flex-start'><div style='font-size:13px;color:#64748b;font-weight:600;margin-bottom:10px'>By Role</div><div style='display:flex;flex-wrap:wrap'>{role_pills}</div></div>
      </div>
      <div style='background:white;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'>
        <div style='padding:16px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;border-bottom:1px solid #f1f5f9'>
          <div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap'>
            <span style='font-size:13px;color:#64748b'>Show</span>
            <select id='perPage' class='filter-select' style='min-width:80px' onchange='filterStaff()'><option value='10'>10</option><option value='25'>25</option><option value='50'>50</option><option value='100'>100</option></select>
            <span style='font-size:13px;color:#64748b'>items per page</span>
          </div>
        </div>
        <div style='padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center'>
          <div style='position:relative'><span style='position:absolute;left:10px;top:50%;transform:translateY(-50%);color:#94a3b8'>🔍</span><input id='searchInput' onkeyup='filterStaff()' placeholder='Search name, ID, email.' style='padding:10px 12px 10px 32px;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;min-width:200px'></div>
          <select id='roleFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Roles</option><option value='administrator'>Administrator</option><option value='principal'>Principal</option><option value='deputy principal'>Deputy Principal</option><option value='classteacher'>Classteacher</option><option value='teacher'>Teacher</option></select>
          <select id='genderFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Gender</option><option value='male'>Male</option><option value='female'>Female</option></select>
          <select id='employmentFilter' class='filter-select' onchange='filterStaff()'><option value='all'>All Employment</option><option value='teaching'>Teaching</option><option value='non-teaching'>Non-Teaching</option></select>
          <button class='action-btn' onclick='exportCSV()'>📄 CSV</button>
          <button class='action-btn' onclick='window.print()'>⬇️ PDF</button>
        </div>
        <div style='padding:0 16px 14px'><button class='add-staff-btn' onclick='openModal()'><span style='font-size:18px'>+</span> Add Staff</button></div>
        <div style='overflow:auto;max-height:65vh'>
          <table id='staffTable' style='width:100%;border-collapse:collapse'>
            <thead style='position:sticky;top:0;background:#fcfcfc;z-index:2'><tr style='text-align:left;font-size:12px;color:#64748b;border-top:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9'><th style='padding:12px'>#</th><th style='padding:12px'>NATIONAL ID / PASSPORT ↕</th><th style='padding:12px'>NAME ↑</th><th style='padding:12px'>GENDER</th><th style='padding:12px'>SYSTEM ROLE ↕</th><th style='padding:12px'>PHONE</th><th style='padding:12px'>EMAIL</th><th style='padding:12px'>ACTIONS</th></tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
      </div>
    </div>
    <div id='addStaffModal' class='modal'>
      <div style='background:white;border-radius:16px;width:520px;max-width:95%;max-height:90vh;overflow:auto'>
        <div style='padding:20px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center'><b style='font-size:16px'>➕ Add Staff — {school_name}</b><span onclick='closeModal()' style='cursor:pointer;font-size:20px'>✕</span></div>
        <form method='post' action='{" /super/global-control/teachers/add" if is_global else "/school/teachers/add"}' style='padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:12px'>
          <div style='grid-column:span 2'><label style='font-size:11px;font-weight:700'>👤 Full Name *</label><input name='name' required placeholder='Full Name *' class='input-field'></div>
          <div><label style='font-size:11px;font-weight:700'>🆔 National ID / Passport *</label><input name='id_no' required placeholder='National ID *' class='input-field'></div>
          <div><label style='font-size:11px;font-weight:700'>🔢 TSC No</label><input name='tsc_no' placeholder='TSC No (optional)' class='input-field'></div>
          <div><label style='font-size:11px;font-weight:700'>⚧️ Gender *</label><select name='gender' required class='input-field'><option value='Male'>Male</option><option value='Female'>Female</option></select></div>
          <div><label style='font-size:11px;font-weight:700'>🛡️ System Role *</label><select name='role' required class='input-field'><option value=''>Select Role *</option><option value='Administrator'>Administrator</option><option value='Principal'>Principal</option><option value='Deputy Principal'>Deputy Principal</option><option value='Classteacher'>Classteacher</option><option value='Teacher'>Teacher</option></select></div>
          <div><label style='font-size:11px;font-weight:700'>💼 Employment Type *</label><select name='employment_type' required class='input-field'><option value='Teaching'>Teaching</option><option value='Non-Teaching'>Non-Teaching</option></select></div>
          <div><label style='font-size:11px;font-weight:700'>📞 Phone *</label><input name='phone' required placeholder='Phone *' class='input-field'></div>
          <div style='grid-column:span 2'><label style='font-size:11px;font-weight:700'>📧 Email</label><input name='email' placeholder='Email (optional)' class='input-field'></div>
          <div style='grid-column:span 2;margin-top:8px'><button class='add-btn'>➕ Add Staff</button><div style='font-size:10px;color:#64748b;margin-top:6px;text-align:center'>{'Will be added to ALL schools automatically — Global Control' if is_global else 'Will be added to your school only — private'}</div></div>
        </form>
      </div>
    </div>
    <script>
    function openModal(){{document.getElementById('addStaffModal').classList.add('active');}}
    function closeModal(){{document.getElementById('addStaffModal').classList.remove('active');}}
    function filterStaff(){{
      let search=document.getElementById('searchInput').value.toLowerCase();
      let role=document.getElementById('roleFilter').value.toLowerCase();
      let gender=document.getElementById('genderFilter').value.toLowerCase();
      let emp=document.getElementById('employmentFilter').value.toLowerCase();
      let perPage=parseInt(document.getElementById('perPage').value);
      let rows=document.querySelectorAll('.staff-row');
      let visible=0;
      rows.forEach(r=>{{
        let matchSearch=r.getAttribute('data-search').includes(search);
        let matchRole=role==='all'||r.getAttribute('data-role').includes(role);
        let matchGender=gender==='all'||r.getAttribute('data-gender').includes(gender);
        let matchEmp=emp==='all'||r.getAttribute('data-employment').includes(emp);
        let show=matchSearch&&matchRole&&matchGender&&matchEmp;
        r.style.display=show?'':'none';
        if(show) visible++;
        if(visible>perPage && show) r.style.display='none';
      }});
    }}
    function exportCSV(){{
      let rows=document.querySelectorAll('#staffTable tr');
      let csv=[];
      rows.forEach(row=>{{let cols=row.querySelectorAll('th,td'); let data=[]; cols.forEach((c,i)=>{{if(i<7) data.push('\"'+c.innerText.replace(/\"/g,'\"\"')+'\"');}}); csv.push(data.join(','));}});
      let blob=new Blob([csv.join('\\n')],{{type:'text/csv'}}); let url=URL.createObjectURL(blob); let a=document.createElement('a'); a.href=url; a.download='staff_{school_name}.csv'; a.click();
    }}
    </script>
    """

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{margin:0;font-family:Arial;background:#f0f2f5;display:flex;height:100vh}.blue-bar{width:32px;background:#0d8bf2;flex-shrink:0}.main{flex:1;display:flex;justify-content:center;align-items:center;padding:20px}.card{background:white;width:540px;max-width:100%;padding:48px 48px 40px;border-radius:6px;box-shadow:0 0 0 1px #e2e8f0;text-align:center}.logo-box{width:72px;height:72px;background:#0f172a;color:white;border-radius:18px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:32px;margin:0 auto}.input{width:100%;padding:14px 16px;border:1px solid #e2e8f0;border-radius:10px;background:#fcfcfc;font-size:14px;outline:none;box-sizing:border-box}.sign{background:#0d8bf2;color:white;width:100%;padding:15px;border:none;border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;margin-top:10px}</style></head><body><div class="blue-bar"></div><div class="main"><div class="card"><div class="logo-box">D</div><h1 style="margin:16px 0 0;font-size:40px;font-weight:900;color:#0f172a">DaviSchool</h1><div style="margin-top:12px;color:#334155;font-size:15px">Sign in to your Davischool account</div><form method="post" action="/login" style="margin-top:30px;text-align:left"><label style="font-size:13px;font-weight:700;display:block;margin-bottom:8px">Username or Email</label><input name="email" class="input" required style="margin-bottom:20px"><label style="font-size:13px;font-weight:700;display:block;margin-bottom:8px">Password</label><input name="password" type="password" class="input" required style="margin-bottom:18px"><button class="sign">Sign In</button></form></div></div></body></html>"""
@app.head("/")
def home_head(): return PlainTextResponse("OK")
@app.get("/health")
def health(): return PlainTextResponse("OK")
@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password)); u = cur.fetchone(); con.close()
    if not u: return HTMLResponse("❌ Invalid <a href='/'>Back</a>")
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
    content = f"""<div style='padding:20px;max-width:1400px;margin:auto'><div style='margin-bottom:18px'><h2 style='margin:0;font-size:22px;font-weight:800'>📊 School Overview</h2><p style='margin:4px 0 0;color:#64748b;font-size:13px'>Welcome {name}</p></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🏫 TOTAL SCHOOLS</div><div style='font-size:32px;font-weight:900;margin:12px 0 8px'>{total}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>✅ ACTIVE SCHOOLS</div><div style='font-size:32px;font-weight:900;margin:12px 0 8px'>{total}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🔥 TOTAL REVENUE</div><div style='font-size:26px;font-weight:900;margin:12px 0 8px'>KES {total*15000}</div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px'><div style='font-size:11px;color:#64748b'>🎓 TOTAL STUDENTS</div><div style='font-size:32px;font-weight:900;margin:12px 0 8px'>0</div></div></div><div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px 16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9'><div style='font-weight:800;font-size:14px'>🏫 Recently Added Schools</div><a href='/schools/manage' style='font-size:12px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 14px'>Name</th><th>Location</th><th>Status</th><th>Date</th></tr></thead><tbody>{rows}</tbody></table></div><div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='font-weight:800;font-size:14px;margin-bottom:12px'>⚡ Quick Actions</div><a href='/schools/manage' style='display:block;text-align:center;background:white;border:1px solid #e2e8f0;padding:10px;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:600;font-size:13px;margin-bottom:10px'>🏫 Manage Schools</a><a href='/super/global-control/dashboard' style='display:block;text-align:center;background:#0f172a;color:white;padding:10px;border-radius:10px;text-decoration:none;font-weight:700;font-size:13px'>🌍 Global Control — Automatic</a></div></div></div></div>"""
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

# RESTORED WELCOME WINDOW - EXACTLY AS BEFORE
@app.get("/school/dashboard", response_class=HTMLResponse)
def school_dashboard(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    if request.session.get("role")=="super_admin" and request.session.get("school_id",0)==0: return RedirectResponse("/dashboard")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?", (school["id"],)); sc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?", (school["id"],)); cc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM exams WHERE school_id=?", (school["id"],)); ec = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM teachers WHERE school_id=?", (school["id"],)); tc = cur.fetchone()["c"]; cur.execute("SELECT c.name as class_name, s.gender, COUNT(*) as cnt FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? GROUP BY c.name, s.gender ORDER BY c.name", (school["id"],)); gender_rows = cur.fetchall(); cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY id DESC LIMIT 5", (school["id"],)); recent_students = cur.fetchall(); con.close()
    stats = {}; tb=0; tg=0
    for r in gender_rows:
        cn = (r['class_name'] or 'UNASSIGNED').upper()
        if cn not in stats: stats[cn] = {'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys']=r['cnt']; tb+=r['cnt']
        else: stats[cn]['girls']=r['cnt']; tg+=r['cnt']
    max_v = max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    chart_html = "".join([f"<div style='text-align:center;min-width:90px'><div style='display:flex;gap:10px;align-items:end;justify-content:center;height:170px'><div><div style='width:42px;height:{bh}px;background:#0a84ff;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px;height:{gh}px;background:#ff2d92;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px;font-weight:800;margin-top:8px'>{cn}</div></div>" for cn,v in stats.items() for bh in [int((v['boys']/max_v)*150) if v['boys']>0 else 6] for gh in [int((v['girls']/max_v)*150) if v['girls']>0 else 6]]) or "<div style='padding:30px;color:#94a3b8;text-align:center;width:100%'>No students yet</div>"
    stu_rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{st['name']}</td><td style='padding:10px 12px;font-size:11px'>{st['assessment_no'] or ''}</td><td style='padding:10px 12px;font-size:11px'>{st['gender']}</td><td>Class {st['class_id'] or ''}</td></tr>" for st in recent_students]) or "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No students yet</td></tr>"
    header = school_header(school, name, "dashboard", is_impersonating=is_imp)
    html = f"""<div style='padding:18px;max-width:1400px;margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%);border-radius:18px;padding:22px 24px;color:white;display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'><div><div style='font-size:22px;font-weight:900'>DaviSchool Management System 🚀</div><div style='font-size:12px;color:#bfdbfe;margin-top:4px'>REVOLUTIONIZE YOUR SCHOOL'S MANAGEMENT!</div></div><div style='text-align:right'><div style='font-size:34px;font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students</div></div></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px'><a href='/school/students' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🎓 TOTAL STUDENTS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{sc}</div></a><a href='/school/classes' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🏫 CLASSES</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{cc}</div></a><a href='/school/exams' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>📝 EXAMS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{ec}</div></a><a href='/school/teachers' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>👨‍🏫 STAFF</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{tc}</div></a></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='display:flex;justify-content:space-between'><div><div style='font-weight:800;font-size:14px'>👥 Students by Gender</div></div><div style='display:flex;gap:12px;font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex;gap:24px;overflow-x:auto;margin-top:18px'>{chart_html}</div></div><div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:14px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px 16px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><div style='font-weight:800'>🎓 Recent Students</div><a href='/school/students' style='font-size:11px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:10px;color:#64748b'><th style='padding:10px 12px'>Name</th><th>Adm No</th><th>Gender</th><th>Class</th></tr></thead><tbody>{stu_rows}</tbody></table></div><div style='background:#0f172a;border-radius:14px;padding:16px;color:white;height:fit-content'><div style='font-weight:800;font-size:14px'>📊 LIVE</div><div style='background:#1e293b;border-radius:10px;padding:12px;margin-top:10px'><div style='font-size:11px'>👦 {tb} | 👧 {tg}</div><div style='font-size:11px;margin-top:6px;color:#22c55e'>Auto ✅</div></div></div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

@app.get("/school/students", response_class=HTMLResponse)
def school_students(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name, stream", (school["id"],)); classes = cur.fetchall(); cur.execute("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=? ORDER BY s.id DESC", (school["id"],)); students = cur.fetchall(); con.close()
    class_opts = "".join([f"<option value='{c['id']}'>{c['name']} {c['stream'] or ''}</option>" for c in classes])
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{st['assessment_no'] or ''}</td><td style='padding:10px 12px;font-size:12px'>{st['name']}</td><td style='padding:10px 12px;font-size:12px'>{st['gender'] or ''}</td><td style='padding:10px 12px;font-size:12px'>{st['class_name'] or ''}</td><td style='padding:10px 12px'><a href='/school/students/delete/{st['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️ Delete</a></td></tr>" for st in students]) or "<tr><td colspan='5' style='padding:30px;text-align:center;color:#94a3b8'>No students yet</td></tr>"
    header = school_header(school, name, "students", is_impersonating=is_imp)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px;max-width:1400px;margin:auto'><h2 style='margin:0;font-size:20px;font-weight:800'>🎓 Students Manager ({len(students)})</h2><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px;margin-top:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px'><b>📚 Students List</b></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>ADM NO</th><th>NAME</th><th>GENDER</th><th>CLASS</th><th>ACTION</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;height:fit-content'><div style='font-weight:800;margin-bottom:10px'>➕ Add Student</div><form method='post' action='/school/students/add'><input name='assessment_no' required placeholder='🆔 Assessment No *' class='input-field'><input name='student_name' required placeholder='👤 Student Name *' class='input-field'><select name='class_id' required class='input-field'><option value=''>🏫 Select Class *</option>{class_opts}</select><select name='gender' required class='input-field'><option>Male</option><option>Female</option></select><input name='parent_phone' placeholder='📞 Parent Phone' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Student</button></form></div></div></div></div></div></body></html>")

@app.post("/school/students/add")
def add_student(request: Request, assessment_no: str = Form(...), student_name: str = Form(...), class_id: int = Form(...), gender: str = Form(...), parent_phone: str = Form("")):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO students (school_id, admission_no, assessment_no, name, class_id, gender, parent_phone) VALUES (?,?,?,?,?,?,?)", (school["id"], assessment_no.strip().upper(), assessment_no.strip().upper(), student_name.strip().upper(), class_id, gender, parent_phone.strip())); con.commit(); con.close(); return RedirectResponse("/school/students",303)
@app.get("/school/students/delete/{sid}")
def del_stud(sid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=?", (sid,)); con.commit(); con.close(); return RedirectResponse("/school/students",303)

@app.get("/school/classes", response_class=HTMLResponse)
def school_classes(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
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

@app.get("/school/subjects", response_class=HTMLResponse)
def school_subjects(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY id DESC", (school["id"],)); subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{s['name']}</td><td style='padding:10px 12px;font-size:12px'>{s['code'] or ''}</td><td style='padding:10px 12px;font-size:12px'>{s['initial'] or ''}</td><td style='padding:10px 12px'><a href='/school/subjects/delete/{s['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️ Delete</a></td></tr>" for s in subs]) or "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No subjects yet</td></tr>"
    header = school_header(school, name, "subjects", is_impersonating=is_imp)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px;max-width:1200px;margin:auto'><h2 style='margin:0;font-size:20px;font-weight:800'>📚 Subjects ({len(subs)})</h2><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px;margin-top:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px'><b>📚 Subjects List</b></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>NAME</th><th>CODE</th><th>INITIAL</th><th>ACTION</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;height:fit-content'><div style='font-weight:800;margin-bottom:10px'>➕ Add Subject</div><form method='post' action='/school/subjects/add'><input name='subject_name' required placeholder='📚 Subject Name *' class='input-field'><input name='code' placeholder='🔢 Code' class='input-field'><input name='initial' placeholder='🔤 Initial' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Subject</button></form></div></div></div></div></div></body></html>")
@app.post("/school/subjects/add")
def add_subject(request: Request, subject_name: str = Form(...), code: str = Form(""), initial: str = Form("")):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO subjects (school_id, name, code, initial) VALUES (?,?,?,?)", (school["id"], subject_name.strip().upper(), code.strip().upper(), initial.strip().upper())); con.commit(); con.close(); return RedirectResponse("/school/subjects",303)
@app.get("/school/subjects/delete/{sid}")
def del_sub(sid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE id=?", (sid,)); con.commit(); con.close(); return RedirectResponse("/school/subjects",303)

@app.get("/school/dean-settings", response_class=HTMLResponse)
def dean_settings(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY id DESC", (school["id"],)); terms = cur.fetchall(); con.close()
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{t['term_name']}</td><td style='padding:10px 12px;font-size:12px'>{t['year']}</td><td style='padding:10px 12px;font-size:12px'>{t['start_date']}</td><td style='padding:10px 12px;font-size:12px'>{t['end_date']}</td><td style='padding:10px 12px'><a href='/school/dean-settings/delete-term/{t['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️ Delete</a></td></tr>" for t in terms]) or "<tr><td colspan='5' style='padding:30px;text-align:center;color:#94a3b8'>No terms yet</td></tr>"
    header = school_header(school, name, "dean-settings", is_impersonating=is_imp)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px;max-width:1200px;margin:auto'><h2 style='margin:0;font-size:20px;font-weight:800'>⚙️ Dean Settings</h2><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px;margin-top:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px'><b>📅 Terms List</b></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>TERM</th><th>YEAR</th><th>START</th><th>END</th><th>ACTION</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;height:fit-content'><div style='font-weight:800;margin-bottom:10px'>➕ Add Term</div><form method='post' action='/school/dean-settings/add-term'><select name='term_name' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='📅 Year e.g. 2026' class='input-field'><input name='start_date' type='date' required class='input-field'><input name='end_date' type='date' required class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Term</button></form></div></div></div></div></div></body></html>")
@app.post("/school/dean-settings/add-term")
def add_term(request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO terms (school_id, term_name, year, start_date, end_date) VALUES (?,?,?,?,?)", (school["id"], term_name, year, start_date, end_date)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings",303)
@app.get("/school/dean-settings/delete-term/{tid}")
def del_term(tid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM terms WHERE id=?", (tid,)); con.commit(); con.close(); return RedirectResponse("/school/dean-settings",303)

@app.get("/school/exams", response_class=HTMLResponse)
def school_exams(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (school["id"],)); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px 12px'>{e['name']}</td><td>{e['term']}</td><td>{e['year']}</td><td><span style='background:#0f172a;color:white;padding:3px 8px;border-radius:12px;font-size:10px'>{e['exam_type'] or ''}</span></td><td><a href='/school/exams/delete/{e['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for e in exams]) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No exams</td></tr>"
    header = school_header(school, name, "exams", is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>📝 Exams ({len(exams)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/school/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Exam</b><form method='post' action='/school/exams/add'><input name='exam_name' required placeholder='Exam Name *' class='input-field'><select name='term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='2026' class='input-field'><select name='exam_type' required class='input-field'><option>Main Exam</option><option>End Term Exam</option></select><button class='add-btn' style='margin-top:8px'>➕ Add Exam</button></form></div></div></div></div></div></body></html>")
@app.post("/school/exams/add")
def add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (school["id"], exam_name.strip().upper(), term.strip(), year.strip(), exam_type.strip())); con.commit(); con.close(); return RedirectResponse("/school/exams",303)
@app.get("/school/exams/delete/{eid}")
def del_exam(eid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM exams WHERE id=?", (eid,)); con.commit(); con.close(); return RedirectResponse("/school/exams",303)

@app.get("/school/teachers", response_class=HTMLResponse)
def teachers_page(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY id DESC", (school["id"],)); teachers = cur.fetchall(); con.close()
    header = school_header(school, name, "teachers", is_impersonating=is_imp)
    body = staff_manager_html(teachers, school["name"], is_global=False)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/school/teachers/add")
def add_teacher(request: Request, name: str = Form(...), tsc_no: str = Form(""), id_no: str = Form(...), gender: str = Form(...), role: str = Form(...), phone: str = Form(...), email: str = Form(""), employment_type: str = Form("Teaching")):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO teachers (school_id, name, email, phone, tsc_no, gender, id_no, role, employment_type) VALUES (?,?,?,?,?,?,?,?,?)", (school["id"], name.strip().upper(), email.strip(), phone.strip(), tsc_no.strip(), gender, id_no.strip(), role.strip(), employment_type.strip())); con.commit(); con.close(); return RedirectResponse("/school/teachers",303)
@app.get("/school/teachers/delete/{tid}")
def del_teacher(tid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM teachers WHERE id=?", (tid,)); con.commit(); con.close(); return RedirectResponse("/school/teachers",303)

@app.get("/school/subject-allocation", response_class=HTMLResponse)
def school_alloc(request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request); name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM teachers WHERE school_id=?", (school["id"],)); teachers = cur.fetchall(); cur.execute("SELECT * FROM subjects WHERE school_id=?", (school["id"],)); subjects = cur.fetchall(); cur.execute("SELECT * FROM classes WHERE school_id=?", (school["id"],)); classes = cur.fetchall(); cur.execute("SELECT ta.*, t.name as tname, s.name as sname, c.name as cname FROM teacher_allocations ta LEFT JOIN teachers t ON ta.teacher_id=t.id LEFT JOIN subjects s ON ta.subject_id=s.id LEFT JOIN classes c ON ta.class_id=c.id WHERE ta.school_id=?", (school["id"],)); allocs = cur.fetchall(); con.close()
    t_opts = "".join([f"<option value='{t['id']}'>{t['name']}</option>" for t in teachers]); s_opts = "".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subjects]); c_opts = "".join([f"<option value='{c['id']}'>{c['name']}</option>" for c in classes])
    rows = "".join([f"<tr><td style='padding:10px'>{a['tname'] or ''}</td><td>{a['sname'] or ''}</td><td>{a['cname'] or ''}</td><td><a href='/school/subject-allocation/delete/{a['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for a in allocs]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No allocations</td></tr>"
    header = school_header(school, name, "subject-allocation", is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid;grid-template-columns:360px 1fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>📌 Allocation</b><form method='post' action='/school/subject-allocation/add'><select name='teacher_id' required class='input-field'><option value=''>Teacher ▼</option>{t_opts}</select><select name='subject_id' required class='input-field'><option value=''>Subject ▼</option>{s_opts}</select><select name='class_id' required class='input-field'><option value=''>Class ▼</option>{c_opts}</select><button class='add-btn' style='margin-top:10px'>Allocate</button></form></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:12px'><b>Allocations ({len(allocs)})</b></div><table style='width:100%'><tbody>{rows}</tbody></table></div></div></div></div></div></body></html>")
@app.post("/school/subject-allocation/add")
def add_alloc(request: Request, teacher_id: int = Form(...), subject_id: int = Form(...), class_id: int = Form(...)):
    school = get_school_obj(request); con = get_db(); cur = con.cursor(); cur.execute("INSERT INTO teacher_allocations (school_id, teacher_id, subject_id, class_id) VALUES (?,?,?,?)", (school["id"], teacher_id, subject_id, class_id)); con.commit(); con.close(); return RedirectResponse("/school/subject-allocation",303)
@app.get("/school/subject-allocation/delete/{aid}")
def del_alloc(aid: int): con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM teacher_allocations WHERE id=?", (aid,)); con.commit(); con.close(); return RedirectResponse("/school/subject-allocation",303)

@app.get("/super/global-control", response_class=HTMLResponse)
@app.get("/super/global-control/dashboard", response_class=HTMLResponse)
def global_dashboard(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM students"); sc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM classes"); cc = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM exams"); ec = cur.fetchone()["c"]; cur.execute("SELECT COUNT(*) c FROM teachers"); tc = cur.fetchone()["c"]
    cur.execute("SELECT c.name as class_name, s.gender, COUNT(*) as cnt FROM students s LEFT JOIN classes c ON s.class_id=c.id GROUP BY c.name, s.gender ORDER BY c.name"); gender_rows = cur.fetchall()
    cur.execute("SELECT s.*, sc.name as school_name FROM students s LEFT JOIN schools sc ON s.school_id=sc.id ORDER BY s.id DESC LIMIT 5"); recent = cur.fetchall()
    con.close()
    stats = {}; tb=0; tg=0
    for r in gender_rows:
        cn = (r['class_name'] or 'UNASSIGNED').upper()
        if cn not in stats: stats[cn] = {'boys':0,'girls':0}
        if (r['gender'] or '').lower().startswith('m'): stats[cn]['boys']=r['cnt']; tb+=r['cnt']
        else: stats[cn]['girls']=r['cnt']; tg+=r['cnt']
    max_v = max([max(v['boys'],v['girls']) for v in stats.values()], default=1) or 1
    chart_html = "".join([f"<div style='text-align:center;min-width:90px'><div style='display:flex;gap:10px;align-items:end;justify-content:center;height:170px'><div><div style='width:42px;height:{bh}px;background:#0a84ff;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#0a84ff'>{v['boys']}</div></div><div><div style='width:42px;height:{gh}px;background:#ff2d92;border-radius:6px 6px 0 0'></div><div style='font-size:10px;font-weight:700;color:#ff2d92'>{v['girls']}</div></div></div><div style='font-size:11px;font-weight:800;margin-top:8px'>{cn}</div></div>" for cn,v in stats.items() for bh in [int((v['boys']/max_v)*150) if v['boys']>0 else 6] for gh in [int((v['girls']/max_v)*150) if v['girls']>0 else 6]]) or "<div style='padding:30px;color:#94a3b8;text-align:center;width:100%'>No students yet</div>"
    stu_rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{st['name']} <span style='font-size:10px;color:#64748b'>({st['school_name'] or ''})</span></td><td style='padding:10px 12px;font-size:11px'>{st['assessment_no'] or ''}</td><td style='padding:10px 12px;font-size:11px'>{st['gender']}</td><td>Class {st['class_id'] or ''}</td></tr>" for st in recent]) or "<tr><td colspan='4' style='padding:30px;text-align:center;color:#94a3b8'>No students yet</td></tr>"
    header = global_header(name, "dashboard")
    html = f"""<div style='padding:18px;max-width:1400px;margin:auto'><div style='background:linear-gradient(135deg,#0f172a 0%, #1e3a8a 60%, #1e40af 100%);border-radius:18px;padding:22px 24px;color:white;display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'><div><div style='font-size:22px;font-weight:900'>DaviSchool Management System 🚀</div><div style='font-size:12px;color:#bfdbfe;margin-top:4px'>GLOBAL CONTROL — Same as School Overview — Automatic Sync</div></div><div style='text-align:right'><div style='font-size:34px;font-weight:900'>{sc}</div><div style='font-size:11px'>Total Students (ALL)</div></div></div><div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px'><a href='/super/global-control/students' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🎓 TOTAL STUDENTS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{sc}</div></a><a href='/super/global-control/classes' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>🏫 CLASSES</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{cc}</div></a><a href='/super/global-control/exams' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>📝 EXAMS</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{ec}</div></a><a href='/super/global-control/teachers' class='ds-card'><div style='font-size:11px;color:#64748b;font-weight:700'>👨‍🏫 STAFF</div><div style='font-size:30px;font-weight:900;margin:10px 0'>{tc}</div></a></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:16px'><div style='display:flex;justify-content:space-between'><div><div style='font-weight:800;font-size:14px'>👥 Students by Gender — ALL Schools</div></div><div style='display:flex;gap:12px;font-size:11px'><span><span style='width:10px;height:10px;background:#0a84ff;display:inline-block'></span> Boys</span><span><span style='width:10px;height:10px;background:#ff2d92;display:inline-block'></span> Girls</span></div></div><div style='display:flex;gap:24px;overflow-x:auto;margin-top:18px'>{chart_html}</div></div><div style='display:grid;grid-template-columns:1.9fr 0.8fr;gap:14px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px 16px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between'><div style='font-weight:800'>🎓 Recent Students — ALL Schools</div><a href='/super/global-control/students' style='font-size:11px;color:#3b82f6;text-decoration:none'>View All →</a></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:10px;color:#64748b'><th style='padding:10px 12px'>Name (School)</th><th>Adm No</th><th>Gender</th><th>Class</th></tr></thead><tbody>{stu_rows}</tbody></table></div><div style='background:#0f172a;border-radius:14px;padding:16px;color:white;height:fit-content'><div style='font-weight:800;font-size:14px'>📊 GLOBAL LIVE — Automatic</div><div style='background:#1e293b;border-radius:10px;padding:12px;margin-top:10px'><div style='font-size:11px'>👦 {tb} | 👧 {tg}</div><div style='font-size:11px;margin-top:6px;color:#22c55e'>Sync ✅</div></div></div></div></div>"""
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}{html}</div></div></body></html>")

@app.get("/super/global-control/classes", response_class=HTMLResponse)
def global_classes(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "classes")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT name, stream, COUNT(*) cnt FROM classes GROUP BY name, stream ORDER BY name"); classes = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px 12px'>{c['name']}</td><td>{c['stream'] or ''}</td><td><span style='background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:10px'>In {c['cnt']} schools</span></td><td><a href='/super/global-control/classes/delete/{c['name']}/{c['stream'] or ''}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for c in classes]) or "<tr><td colspan='4' style='padding:30px;text-align:center'>No classes</td></tr>"
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>🏫 Classes & Streams ({len(classes)}) — Automatic</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/super/global-control/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Class</b><div style='font-size:10px;color:#64748b;margin-bottom:8px'>Automatically added to ALL schools</div><form method='post' action='/super/global-control/classes/add'><input name='class_name' required placeholder='Class Name *' class='input-field'><input name='stream' required placeholder='Stream *' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Class</button></form></div></div></div></div></div></body></html>")
@app.post("/super/global-control/classes/add")
def global_add_class(request: Request, class_name: str = Form(...), stream: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND stream=?", (sch["id"], class_name.strip().upper(), stream.strip().upper()))
        if not cur.fetchone(): cur.execute("INSERT INTO classes (school_id, name, stream) VALUES (?,?,?)", (sch["id"], class_name.strip().upper(), stream.strip().upper()))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/classes",303)
@app.get("/super/global-control/classes/delete/{cname}/{stream}")
def global_del_class(cname: str, stream: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM classes WHERE name=? AND stream=?", (cname, stream)); con.commit(); con.close(); return RedirectResponse("/super/global-control/classes",303)

@app.get("/super/global-control/subjects", response_class=HTMLResponse)
def global_subjects(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "subjects")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT name, code, initial, COUNT(*) cnt FROM subjects GROUP BY name ORDER BY name"); subs = cur.fetchall(); con.close()
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{s['name']}</td><td style='padding:10px 12px;font-size:12px'>{s['code'] or ''}</td><td style='padding:10px 12px;font-size:12px'>{s['initial'] or ''}</td><td style='padding:10px 12px'><span style='background:#dbeafe;color:#1e40af;padding:3px 8px;border-radius:12px;font-size:10px'>{s['cnt']} schools</span></td><td><a href='/super/global-control/subjects/delete/{s['name']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none'>🗑️</a></td></tr>" for s in subs]) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No subjects</td></tr>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px;max-width:1200px;margin:auto'><h2 style='margin:0;font-size:20px;font-weight:800'>📚 Subjects ({len(subs)}) — Automatic</h2><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px;margin-top:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px'><b>📚 Subjects List</b></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>NAME</th><th>CODE</th><th>INITIAL</th><th>SCHOOLS</th><th>ACTION</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/super/global-control/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;height:fit-content'><div style='font-weight:800;margin-bottom:10px'>➕ Add Subject</div><div style='font-size:10px;color:#64748b;margin-bottom:8px'>Automatically added to ALL schools</div><form method='post' action='/super/global-control/subjects/add'><input name='subject_name' required placeholder='📚 Subject Name *' class='input-field'><input name='code' placeholder='🔢 Code' class='input-field'><input name='initial' placeholder='🔤 Initial' class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Subject</button></form></div></div></div></div></div></body></html>")
@app.post("/super/global-control/subjects/add")
def global_add_subject(request: Request, subject_name: str = Form(...), code: str = Form(""), initial: str = Form("")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=?", (sch["id"], subject_name.strip().upper()))
        if not cur.fetchone(): cur.execute("INSERT INTO subjects (school_id, name, code, initial) VALUES (?,?,?,?)", (sch["id"], subject_name.strip().upper(), code.strip().upper(), initial.strip().upper()))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/subjects",303)
@app.get("/super/global-control/subjects/delete/{sname}")
def global_del_sub(sname: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM subjects WHERE name=?", (sname,)); con.commit(); con.close(); return RedirectResponse("/super/global-control/subjects",303)

@app.get("/super/global-control/dean-settings", response_class=HTMLResponse)
def global_dean(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "dean-settings")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT term_name, year, start_date, end_date, COUNT(*) cnt FROM terms GROUP BY term_name, year ORDER BY year DESC"); terms = cur.fetchall(); con.close()
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{t['term_name']}</td><td style='padding:10px 12px;font-size:12px'>{t['year']}</td><td style='padding:10px 12px;font-size:12px'>{t['start_date']}</td><td style='padding:10px 12px;font-size:12px'>{t['end_date']}</td><td style='padding:10px 12px'><span style='background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:10px'>{t['cnt']} schools</span></td></tr>" for t in terms]) or "<tr><td colspan='5' style='padding:30px;text-align:center;color:#94a3b8'>No terms yet</td></tr>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px;max-width:1200px;margin:auto'><h2 style='margin:0;font-size:20px;font-weight:800'>⚙️ Dean Settings — Automatic</h2><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px;margin-top:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'><div style='padding:14px'><b>📅 Terms List</b></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>TERM</th><th>YEAR</th><th>START</th><th>END</th><th>SCHOOLS</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/super/global-control/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px;height:fit-content'><div style='font-weight:800;margin-bottom:10px'>➕ Add Term</div><div style='font-size:10px;color:#64748b;margin-bottom:8px'>Automatically added to ALL schools</div><form method='post' action='/super/global-control/dean-settings/add'><select name='term_name' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='📅 Year e.g. 2026' class='input-field'><input name='start_date' type='date' required class='input-field'><input name='end_date' type='date' required class='input-field'><button class='add-btn' style='margin-top:8px'>➕ Add Term</button></form></div></div></div></div></div></body></html>")
@app.post("/super/global-control/dean-settings/add")
def global_add_term(request: Request, term_name: str = Form(...), year: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM terms WHERE school_id=? AND term_name=? AND year=?", (sch["id"], term_name, year))
        if not cur.fetchone(): cur.execute("INSERT INTO terms (school_id, term_name, year, start_date, end_date) VALUES (?,?,?,?,?)", (sch["id"], term_name, year, start_date, end_date))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/dean-settings",303)

@app.get("/super/global-control/exams", response_class=HTMLResponse)
def global_exams(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "exams")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT name, term, year, exam_type, COUNT(*) cnt FROM exams GROUP BY name, year ORDER BY year DESC"); exams = cur.fetchall(); con.close()
    rows = "".join([f"<tr><td style='padding:10px 12px'>{e['name']}</td><td>{e['term']}</td><td>{e['year']}</td><td><span style='background:#0f172a;color:white;padding:3px 8px;border-radius:12px;font-size:10px'>{e['exam_type'] or ''}</span></td><td><span style='background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:10px'>{e['cnt']} schools</span></td></tr>" for e in exams]) or "<tr><td colspan='5' style='padding:30px;text-align:center'>No exams</td></tr>"
    return HTMLResponse(f"<html><body>{header}<div style='padding:18px'><div style='display:grid;grid-template-columns:1.7fr 0.7fr;gap:16px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px'><div style='padding:14px'><b>📝 Exams — Automatic</b></div><table style='width:100%'><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/super/global-control/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:16px'><b>➕ Add Exam</b><div style='font-size:10px;color:#64748b;margin-bottom:8px'>Automatically added to ALL schools</div><form method='post' action='/super/global-control/exams/add'><input name='exam_name' required placeholder='Exam Name *' class='input-field'><select name='term' required class='input-field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required placeholder='2026' class='input-field'><select name='exam_type' required class='input-field'><option>Main Exam</option><option>End Term Exam</option></select><button class='add-btn' style='margin-top:8px'>➕ Add Exam</button></form></div></div></div></div></div></body></html>")
@app.post("/super/global-control/exams/add")
def global_add_exam(request: Request, exam_name: str = Form(...), term: str = Form(...), year: str = Form(...), exam_type: str = Form(...)):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM exams WHERE school_id=? AND name=? AND year=?", (sch["id"], exam_name.strip().upper(), year))
        if not cur.fetchone(): cur.execute("INSERT INTO exams (school_id, name, term, year, exam_type) VALUES (?,?,?,?,?)", (sch["id"], exam_name.strip().upper(), term, year, exam_type))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/exams",303)

@app.get("/super/global-control/teachers", response_class=HTMLResponse)
def global_teachers(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "teachers")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT * FROM teachers ORDER BY id DESC"); teachers = cur.fetchall(); con.close()
    body = staff_manager_html(teachers, "ALL SCHOOLS — Global Control", is_global=True)
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}.input-field{{width:100%;padding:11px 12px;border:1px solid #e2e8f0;border-radius:10px;margin:6px 0;font-size:13px;background:white}}.add-btn{{width:100%;background:#0f172a;color:white;padding:12px;border:none;border-radius:10px;font-weight:700;cursor:pointer}}</style></head><body>{header}{body}</div></div></body></html>")
@app.post("/super/global-control/teachers/add")
def global_add_teacher(request: Request, name: str = Form(...), tsc_no: str = Form(""), id_no: str = Form(...), gender: str = Form(...), role: str = Form(...), phone: str = Form(...), email: str = Form(""), employment_type: str = Form("Teaching")):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id FROM schools"); schools = cur.fetchall()
    for sch in schools:
        cur.execute("SELECT id FROM teachers WHERE school_id=? AND id_no=?", (sch["id"], id_no.strip()))
        if not cur.fetchone():
            cur.execute("INSERT INTO teachers (school_id, name, email, phone, tsc_no, gender, id_no, role, employment_type) VALUES (?,?,?,?,?,?,?,?,?)", (sch["id"], name.strip().upper(), email.strip(), phone.strip(), tsc_no.strip(), gender, id_no.strip(), role.strip(), employment_type.strip()))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/teachers",303)
@app.get("/super/global-control/teachers/delete/{tid}")
def global_del_teacher(tid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT id_no FROM teachers WHERE id=?", (tid,)); t = cur.fetchone()
    if t and t["id_no"]: cur.execute("DELETE FROM teachers WHERE id_no=?", (t["id_no"],))
    else: cur.execute("DELETE FROM teachers WHERE id=?", (tid,))
    con.commit(); con.close(); return RedirectResponse("/super/global-control/teachers",303)

@app.get("/super/global-control/students", response_class=HTMLResponse)
def global_students(request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name",""); header = global_header(name, "students")
    con = get_db(); cur = con.cursor(); cur.execute("SELECT s.*, sc.name as school_name, c.name as class_name FROM students s LEFT JOIN schools sc ON s.school_id=sc.id LEFT JOIN classes c ON s.class_id=c.id ORDER BY s.id DESC LIMIT 100"); students = cur.fetchall(); con.close()
    rows = "".join([f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:10px 12px;font-size:12px'>{st['name']} <span style='font-size:10px;color:#64748b'>({st['school_name'] or ''})</span></td><td style='padding:10px 12px;font-size:12px'>{st['assessment_no'] or ''}</td><td style='padding:10px 12px;font-size:12px'>{st['gender'] or ''}</td><td style='padding:10px 12px;font-size:12px'>{st['class_name'] or ''}</td><td style='padding:10px 12px'><a href='/super/global-control/students/delete/{st['id']}' style='background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:11px'>🗑️ Delete</a></td></tr>" for st in students]) or "<tr><td colspan='5' style='padding:30px;text-align:center;color:#94a3b8'>No students yet</td></tr>"
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head><body>{header}<div style='padding:18px;max-width:1400px;margin:auto'><h2 style='margin:0;font-size:20px;font-weight:800'>🎓 Students Manager — ALL Schools ({len(students)})</h2><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;margin-top:16px'><div style='padding:14px'><b>📚 Students List — ALL Schools</b></div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#f8fafc;text-align:left;font-size:11px;color:#64748b'><th style='padding:10px 12px'>NAME (School)</th><th>ADM NO</th><th>GENDER</th><th>CLASS</th><th>ACTION</th></tr></thead><tbody>{rows}</tbody></table><div style='padding:12px'><a href='/super/global-control/dashboard' style='padding:10px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;color:#0f172a;font-weight:700;font-size:12px'>⬅️ Back</a></div></div></div></div></div></body></html>")
@app.get("/super/global-control/students/delete/{sid}")
def global_del_stud(sid: int, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    con = get_db(); cur = con.cursor(); cur.execute("DELETE FROM students WHERE id=?", (sid,)); con.commit(); con.close(); return RedirectResponse("/super/global-control/students",303)

@app.get("/super/global-control/{path}", response_class=HTMLResponse)
def global_other(path: str, request: Request):
    if request.session.get("role")!="super_admin": return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma"); header = global_header(name, path)
    return HTMLResponse(f"<html><body>{header}<div style='padding:30px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:40px;text-align:center'><h3 style='margin:0'>🚧 {path.upper()} — Coming Soon</h3><p style='color:#64748b;font-size:13px'>Academic Manager auto-hides — click to open</p><a href='/super/global-control/dashboard' style='margin-top:16px;display:inline-block;padding:10px 16px;background:#0f172a;color:white;border-radius:10px;text-decoration:none;font-weight:700'>⬅️ Back</a></div></div></div></div></body></html>")

@app.get("/school/{path}", response_class=HTMLResponse)
def school_other(path: str, request: Request):
    if "email" not in request.session: return RedirectResponse("/")
    if request.session.get("role") not in ["school_admin","super_admin"]: return RedirectResponse("/")
    school = get_school_obj(request)
    if not school: return RedirectResponse("/dashboard")
    name = request.session.get("name",""); is_imp = request.session.get("is_impersonating", False)
    header = school_header(school, name, path, is_impersonating=is_imp)
    return HTMLResponse(f"<html><body>{header}<div style='padding:30px'><div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:40px;text-align:center'><h3>🚧 {path.upper()} — Coming Soon</h3><a href='/school/dashboard' style='padding:10px 16px;background:#0f172a;color:white;border-radius:10px;text-decoration:none;font-weight:700'>⬅️ Back</a></div></div></div></div></body></html>")

@app.exception_handler(StarletteHTTPException)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        if request.url.path.startswith("/api") or "application/json" in request.headers.get("accept",""):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return RedirectResponse("/", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
