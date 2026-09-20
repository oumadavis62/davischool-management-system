from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo

router = APIRouter()

# Standard selection lists used across school data-entry screens. These keep
# entry consistent while still allowing the database to store plain text.
TERM_OPTIONS = ("Term 1", "Term 2", "Term 3")
YEAR_OPTIONS = tuple(str(y) for y in range(datetime.now(ZoneInfo("Africa/Nairobi")).year, datetime.now(ZoneInfo("Africa/Nairobi")).year + 5))

@router.get("/", response_class=HTMLResponse)
def davischool_login_page(request: Request):
    if request.session.get("email"):
        return RedirectResponse("/app", status_code=303)
    error = "<div class='err'>Invalid username or password.</div>" if request.query_params.get("error") else ""
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>DaviSchool Login</title><style>body{{margin:0;background:#f4f7fb;font-family:Arial,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}}.box{{width:min(430px,92vw);background:white;border:1px solid #e2e8f0;border-radius:18px;padding:32px;box-shadow:0 18px 50px #0f172a14}}.logo{{font-size:25px;font-weight:900;color:#111827;margin-bottom:5px}}.sub{{color:#64748b;margin-bottom:25px}}label{{display:block;font-size:13px;font-weight:800;color:#334155;margin:14px 0 7px}}input{{width:100%;box-sizing:border-box;padding:13px;border:1px solid #dbe2ea;border-radius:10px;font-size:15px}}button{{width:100%;margin-top:20px;padding:14px;border:0;border-radius:10px;background:#111827;color:white;font-weight:900;font-size:15px;cursor:pointer}}.err{{background:#fff1f2;border:1px solid #fda4af;color:#9f1239;padding:11px;border-radius:10px;margin-bottom:14px}}</style></head><body><div class='box'><div class='logo'>🏫 DaviSchool Management System</div><div class='sub'>Secure school management platform</div>{error}<form method='post' action='/login'><label>Email / Username</label><input name='email' type='email' autocomplete='username' required placeholder='Enter your email'><label>Password</label><input name='password' type='password' autocomplete='current-password' required placeholder='Enter password'><button type='submit'>Sign In</button></form></div></body></html>""")

@router.post("/login")
def davischool_login(request: Request, email: str = Form(...), password: str = Form(...)):
    from app.main import verify_password
    con = _db()
    try:
        user = con.execute("SELECT * FROM users WHERE lower(email)=lower(?) LIMIT 1", (email.strip(),)).fetchone()
    finally:
        con.close()
    if not user:
        return RedirectResponse("/?error=1", status_code=303)
    ok, legacy = verify_password(password, user["password"] or "")
    if not ok:
        return RedirectResponse("/?error=1", status_code=303)
    request.session["email"] = user["email"]
    request.session["role"] = user["role"]
    request.session["school_id"] = user["school_id"]
    request.session["name"] = user["full_name"] or user["email"]
    if legacy:
        from app.main import hash_password
        con = _db()
        con.execute("UPDATE users SET password=? WHERE id=?", (hash_password(password), user["id"]))
        con.commit(); con.close()
    return RedirectResponse("/app", status_code=303)

@router.get("/logout")
def davischool_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)

def _db():
    from app.main import get_db
    return get_db()

def _shell(title, name, role, body):
    # Keep the sidebar aligned with the authenticated workspace.
    # Super Admin users must not be offered school-scoped pages because those
    # pages intentionally require a school_id and would otherwise redirect
    # back to the login page.
    if role == "super_admin":
        nav = [
            ("/app","⌂","Platform Overview"),
            ("/schools/manage","🏫","Manage Schools"),
            ("/super/global-control/dashboard","🌍","Global Control"),
            ("/account/change-password","🔑","My Account"),
            ("/school/system-audit","🛡","Audit & Security"),
        ]
    else:
        nav = [
            ("/app","⌂","Overview"),
            ("/app/students","🎓","Students"),
            ("/app/staff","👩‍🏫","Staff & Teachers"),
            ("/app/classes","🏫","Classes"),
            ("/app/subjects","📚","Subjects"),
            ("/app/exams","🧪","Examinations"),
            ("/app/academics","📝","Academics"),
            ("/app/academics/analysis","📊","Academic Analysis"),
            ("/app/report-cards","📄","Report Cards"),
            ("/app/attendance","✓","Attendance"),
            ("/app/timetable","🗓","Timetable"),
            ("/app/finance","💰","Fees & Finance"),
            ("/app/accounting","📚","Accounting"),
            ("/app/announcements","📢","Announcements"),
            ("/app/users","👤","Users"),
            ("/app/roles","🔐","Roles & Permissions"),
            ("/app/audit","🛡","Audit Trail"),
        ]
    links="".join(f"<a href='{u}' class='nav'><span>{i}</span>{escape(l)}</a>" for u,i,l in nav)
    initials="".join(x[0] for x in (name or "DaviSchool").split()[:2]).upper()
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{escape(title)} · DaviSchool</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,Arial,sans-serif;background:#f5f7fb;color:#172033}}
.app{{display:flex;min-height:100vh}}.side{{width:250px;background:#111827;color:#cbd5e1;padding:18px 12px;position:fixed;inset:0 auto 0 0;overflow:auto}}
.brand{{font-size:20px;font-weight:900;color:white;padding:8px 12px 24px}}.brand small{{display:block;font-size:10px;color:#94a3b8;margin-top:4px;letter-spacing:1px}}
.nav{{display:flex;gap:11px;align-items:center;color:#cbd5e1;text-decoration:none;padding:10px 12px;border-radius:10px;font-size:13px;margin:3px 0}}.nav:hover{{background:#1f2937;color:white}}
.main{{margin-left:250px;flex:1}}.top{{height:68px;background:white;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;justify-content:space-between;padding:0 28px;position:sticky;top:0;z-index:5}}
.avatar{{width:36px;height:36px;border-radius:50%;background:#111827;color:white;display:flex;align-items:center;justify-content:center;font-weight:800}}
.page{{padding:28px;max-width:1500px;margin:auto}}h1{{font-size:25px;margin:0 0 6px}}.muted{{color:#64748b;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin:22px 0}}.card{{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px;box-shadow:0 2px 8px #00000005}}.kpi{{font-size:28px;font-weight:900;margin-top:10px}}.label{{font-size:11px;color:#64748b;text-transform:uppercase;font-weight:800}}
.section{{margin-top:18px}}.section h2{{font-size:16px;margin:0 0 12px}}.actions{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.action{{background:white;border:1px solid #e5e7eb;border-radius:14px;padding:15px;text-decoration:none;color:#172033;font-weight:800;font-size:13px}}.action span{{font-size:21px;display:block;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden}}th,td{{padding:12px;border-bottom:1px solid #eef2f7;text-align:left;font-size:12px}}th{{background:#f8fafc;color:#64748b;font-size:10px;text-transform:uppercase}}
@media(max-width:900px){{.side{{width:72px}}.brand{{font-size:0}}.brand:before{{content:'DS';font-size:18px}}.nav{{justify-content:center;font-size:0}}.nav span{{font-size:17px}}.main{{margin-left:72px}}.grid,.actions{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:600px){{.page{{padding:16px}}.grid,.actions{{grid-template-columns:1fr 1fr}}.top{{padding:0 16px}}}}
</style></head><body><div class='app'><aside class='side'><div class='brand'>DaviSchool<small>MANAGEMENT PLATFORM</small></div>{links}<div style='padding:14px 12px;color:#94a3b8;font-size:10px;line-height:1.4'>Selection-based data entry is enabled throughout the school workspace.</div><a href='/logout' class='nav' style='margin-top:18px'>↪ Logout</a></aside>
<main class='main'><header class='top'><div><strong>{escape(title)}</strong><div class='muted'>{escape(role.replace("_"," ").title())}</div></div><div style='display:flex;gap:10px;align-items:center'><span class='muted'>{escape(name)}</span><div class='avatar'>{escape(initials)}</div></div></header>{body}</main></div></body></html>"""

def _school_session(request):
    if "email" not in request.session or request.session.get("role") == "super_admin":
        return None
    return int(request.session.get("school_id") or 0)

def _audit(cur, school_id, request, action, details):
    ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit(school_id,user_email,action,details,timestamp) VALUES(?,?,?,?,?)",
                (school_id,request.session.get("email",""),action,details,ts))

def _school_page(request, title, body):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    return HTMLResponse(_shell(title,request.session.get("name","DaviSchool"),request.session.get("role",""),body))

@router.get("/app/students", response_class=HTMLResponse)
def students_page(request: Request):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    con=_db(); cur=con.cursor()
    students=cur.execute("SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.id DESC",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall(); con.close()
    rows="".join(f"<tr><td>{escape(str(s['admission_no'] or ''))}</td><td><b>{escape(str(s['name'] or ''))}</b></td><td>{escape(str(s['class_name'] or 'Unassigned'))}</td><td>{escape(str(s['gender'] or ''))}</td><td>{escape(str(s['parent_phone'] or ''))}</td></tr>" for s in students)
    opts="".join(f"<option value='{c['id']}'>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    body=f"""<div class='page'><h1>Students</h1><div class='muted'>Complete student register and admissions workspace.</div>
<div class='card section'><h2>Add student</h2><form method='post' action='/app/students/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<input name='admission_no' required placeholder='Admission number' class='field'><input name='name' required placeholder='Full name' class='field'><select name='class_id' class='field'><option value=''>Class</option>{opts}</select>
<select name='gender' class='field'><option value=''>Gender</option><option>Male</option><option>Female</option><option>Other</option></select><input name='parent_phone' placeholder='Parent phone' class='field'><input name='assessment_no' placeholder='Assessment number' class='field'>
<button class='btn'>Save Student</button></form></div>
<div class='card section'><div style='display:flex;justify-content:space-between'><h2>Student register ({len(students)})</h2><a class='action' href='/app/students'>Refresh</a></div><table><thead><tr><th>Admission</th><th>Name</th><th>Class</th><th>Gender</th><th>Parent phone</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No students yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}</style>"""
    return _school_page(request,"Students",body)

@router.post("/app/students/add")
def students_add(request: Request, admission_no:str=Form(...), name:str=Form(...), class_id:str=Form(""), gender:str=Form(""), parent_phone:str=Form(""), assessment_no:str=Form("")):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/",303)
    con=_db(); cur=con.cursor()
    exists=cur.execute("SELECT id FROM students WHERE school_id=? AND admission_no=?",(sid,admission_no.strip())).fetchone()
    if exists: con.close(); return HTMLResponse("Admission number already exists. <a href='/app/students'>Back</a>",400)
    cid=int(class_id) if class_id.isdigit() else None
    if cid and not cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(cid,sid)).fetchone(): cid=None
    cur.execute("INSERT INTO students(school_id,admission_no,assessment_no,name,class_id,gender,parent_phone,stream) VALUES(?,?,?,?,?,?,?,?)",(sid,admission_no.strip(),assessment_no.strip(),name.strip(),cid,gender.strip(),parent_phone.strip(),""))
    _audit(cur,sid,request,"STUDENT_CREATE",f"Created student {name.strip()} ({admission_no.strip()})")
    con.commit(); con.close(); return RedirectResponse("/app/students",303)

@router.get("/app/staff", response_class=HTMLResponse)
def staff_page(request: Request):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    con=_db(); cur=con.cursor(); staff=cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall(); con.close()
    rows="".join(f"<tr><td>{escape(str(t['name'] or ''))}</td><td>{escape(str(t['role'] or ''))}</td><td>{escape(str(t['email'] or ''))}</td><td>{escape(str(t['phone'] or ''))}</td><td>{escape(str(t['employment_type'] or ''))}</td></tr>" for t in staff)
    body=f"""<div class='page'><h1>Staff & Teachers</h1><div class='muted'>Staff directory and teaching workforce.</div>
<div class='card section'><h2>Add staff member</h2><form method='post' action='/app/staff/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<input name='name' required placeholder='Full name' class='field'><input name='email' placeholder='Email' class='field'><input name='phone' placeholder='Phone' class='field'><input name='tsc_no' placeholder='TSC number' class='field'><input name='id_no' placeholder='ID number' class='field'><select name='role' class='field'><option>Teacher</option><option>Deputy Teacher</option><option>Head of Department</option><option>Head Teacher</option><option>Principal</option><option>Bursar</option><option>Secretary</option><option>Support Staff</option></select><select name='gender' class='field'><option>Male</option><option>Female</option><option>Other</option></select><select name='employment_type' class='field'><option>Permanent</option><option>Contract</option><option>Part-time</option></select><button class='btn'>Save Staff</button></form></div>
<div class='card section'><h2>Staff register ({len(staff)})</h2><table><thead><tr><th>Name</th><th>Role</th><th>Email</th><th>Phone</th><th>Employment</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No staff yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Staff & Teachers",body)

@router.post("/app/staff/add")
def staff_add(request: Request,name:str=Form(...),email:str=Form(""),phone:str=Form(""),tsc_no:str=Form(""),id_no:str=Form(""),role:str=Form("Teacher"),gender:str=Form(""),employment_type:str=Form("Permanent")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();cur.execute("INSERT INTO teachers(school_id,name,email,phone,tsc_no,gender,id_no,role,employment_type) VALUES(?,?,?,?,?,?,?,?,?)",(sid,name.strip(),email.strip(),phone.strip(),tsc_no.strip(),gender.strip(),id_no.strip(),role.strip(),employment_type.strip()));_audit(cur,sid,request,"STAFF_CREATE",f"Created staff member {name.strip()}");con.commit();con.close();return RedirectResponse("/app/staff",303)

@router.get("/app/academics", response_class=HTMLResponse)
def academics_page(request: Request, exam_id: str = "", class_id: str = "", subject_id: str = "", term: str = "", year: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/")
    con = _db()
    cur = con.cursor()
    terms = cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY id DESC", (sid,)).fetchall()
    exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (sid,)).fetchall()
    subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
    teachers = cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    marks_stats = cur.execute(
        "SELECT COUNT(*) c,COALESCE(AVG(marks),0) a FROM marks WHERE school_id=?", (sid,)
    ).fetchone()

    eid = int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    cid = int(class_id) if class_id.isdigit() else 0
    subid = int(subject_id) if subject_id.isdigit() else 0
    selected_term = term.strip()
    selected_year = year.strip()

    # Load the selected academic slice so every control on this page actually
    # changes the data displayed below it.
    params = [sid]
    q = """SELECT COUNT(m.id) entries, COALESCE(AVG(m.marks),0) avg_mark,
                  COALESCE(MAX(m.marks),0) high, COALESCE(MIN(m.marks),0) low
           FROM marks m WHERE m.school_id=?"""
    if eid:
        q += " AND m.exam_id=?"; params.append(eid)
    if cid:
        q += " AND m.class_id=?"; params.append(cid)
    if subid:
        q += " AND m.subject_id=?"; params.append(subid)
    if selected_term:
        q += " AND m.term=?"; params.append(selected_term)
    if selected_year:
        q += " AND m.year=?"; params.append(selected_year)
    stats = cur.execute(q, params).fetchone()

    con.close()

    eopts = "".join(
        f"<option value='{e['id']}' {'selected' if e['id']==eid else ''}>{escape(str(e['name']))} ({escape(str(e['year'] or ''))})</option>"
        for e in exams
    )
    copts = "".join(
        f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>"
        for c in classes
    )
    sopts = "".join(
        f"<option value='{s['id']}' {'selected' if s['id']==subid else ''}>{escape(str(s['name']))}</option>"
        for s in subjects
    )
    topts = "".join(
        f"<option value='{escape(str(t['term_name'] or t['term'] or ''))}' {'selected' if str(t['term_name'] or t['term'] or '')==selected_term else ''}>{escape(str(t['term_name'] or t['term'] or ''))}</option>"
        for t in terms
    ) or "".join(
        f"<option {'selected' if x==selected_term else ''}>{x}</option>" for x in TERM_OPTIONS
    )
    yopts = "".join(
        f"<option value='{y}' {'selected' if y==selected_year else ''}>{y}</option>" for y in YEAR_OPTIONS
    )

    body = f"""<div class='page'>
<h1>Academic Management</h1>
<div class='muted'>Complete academic workspace. Use the selectors below to load the exact term, year, exam, class and subject you want to work with.</div>

<div class='grid'>
  <div class='card'><div class='label'>Subjects</div><div class='kpi'>{len(subjects)}</div></div>
  <div class='card'><div class='label'>Exams</div><div class='kpi'>{len(exams)}</div></div>
  <div class='card'><div class='label'>Classes</div><div class='kpi'>{len(classes)}</div></div>
  <div class='card'><div class='label'>Marks Average</div><div class='kpi'>{float(marks_stats['a'] or 0):.1f}%</div></div>
</div>

<div class='card section'>
  <h2>Academic Selection</h2>
  <div class='muted' style='margin-bottom:12px'>Select an option and click Load Selection. The buttons below open the corresponding functional workspace with your selections.</div>
  <form method='get' action='/app/academics' style='display:grid;grid-template-columns:repeat(5,1fr);gap:10px'>
    <select name='year' class='field' onchange='this.form.submit()'><option value=''>All Years</option>{yopts}</select>
    <select name='term' class='field' onchange='this.form.submit()'><option value=''>All Terms</option>{topts}</select>
    <select name='exam_id' class='field' onchange='this.form.submit()'><option value=''>All Exams</option>{eopts}</select>
    <select name='class_id' class='field' onchange='this.form.submit()'><option value=''>All Classes</option>{copts}</select>
    <select name='subject_id' class='field' onchange='this.form.submit()'><option value=''>All Subjects</option>{sopts}</select>
  </form>
</div>

<div class='section'>
  <div class='actions'>
    <a class='action' href='/app/academics/marks'><span>📝</span>Marks Entry<small>Enter and update learner marks</small></a>
    <a class='action' href='/app/academics/marksheets'><span>📋</span>Class Marksheets<small>View class subject marks</small></a>
    <a class='action' href='/app/academics/analysis'><span>📊</span>Subject Analysis<small>Compare subject performance</small></a>
    <a class='action' href='/app/academics/student-analysis'><span>👤</span>Student Analysis<small>Analyse an individual learner</small></a>
    <a class='action' href='/app/academics/class-analysis'><span>🏫</span>Class Analysis<small>Analyse class performance</small></a>
    <a class='action' href='/app/academics/assessments'><span>🧪</span>SBA / CBA<small>Record continuous assessment</small></a>
    <a class='action' href='/app/academics/allocations'><span>👩‍🏫</span>Teacher Allocation<small>Assign teachers to subjects</small></a>
    <a class='action' href='/app/report-cards'><span>📄</span>Report Cards<small>Generate learner reports</small></a>
    <a class='action' href='/app/exams'><span>⚙</span>Examinations<small>Create and manage exams</small></a>
    <a class='action' href='/app/subjects'><span>📚</span>Subjects<small>Create and manage subjects</small></a>
    <a class='action' href='/app/classes'><span>🏷</span>Classes & Streams<small>Create classes and streams</small></a>
    <a class='action' href='/app/academics/marksheets?view=summary'><span>📈</span>Marks Summary<small>Class totals and averages</small></a>
  </div>
</div>

<div class='card section'>
  <h2>Selected Academic Snapshot</h2>
  <div class='grid' style='margin:0'>
    <div class='card'><div class='label'>Entries</div><div class='kpi'>{int(stats['entries'] or 0)}</div></div>
    <div class='card'><div class='label'>Average</div><div class='kpi'>{float(stats['avg_mark'] or 0):.1f}%</div></div>
    <div class='card'><div class='label'>Highest</div><div class='kpi'>{float(stats['high'] or 0):.1f}</div></div>
    <div class='card'><div class='label'>Lowest</div><div class='kpi'>{float(stats['low'] or 0):.1f}</div></div>
  </div>
</div>

<div class='card section'>
  <h2>Quick Academic Lists</h2>
  <table><thead><tr><th>Examination</th><th>Term</th><th>Year</th><th>Type</th><th>Action</th></tr></thead>
  <tbody>{''.join(f"<tr><td>{escape(str(e['name']))}</td><td>{escape(str(e['term'] or ''))}</td><td>{escape(str(e['year'] or ''))}</td><td>{escape(str(e['exam_type'] or ''))}</td><td><a class='action' href='/app/academics/marks?exam_id={e['id']}'>Open Marks</a></td></tr>" for e in exams) or '<tr><td colspan=5>No examinations yet. Create one from Examinations.</td></tr>'}</tbody></table>
</div>
</div>
<style>
.field{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:white;cursor:pointer}
.action small{display:block;color:#64748b;font-weight:500;margin-top:5px}
.action:hover{border-color:#94a3b8;box-shadow:0 4px 12px #0000000b}
</style>"""
    return _school_page(request, "Academic Management", body)


@router.get("/app/academics/marksheets", response_class=HTMLResponse)
def class_marksheets(request: Request, exam_id: str = "", class_id: str = "", subject_id: str = "", term: str = "", year: str = "", stream: str = "", view: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/")
    con = _db()
    cur = con.cursor()
    exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (sid,)).fetchall()
    classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
    subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    students = cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY name", (sid,)).fetchall()

    eid = int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    cid = int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
    subid = int(subject_id) if subject_id.isdigit() else 0
    selected_term = term.strip()
    selected_year = year.strip()
    selected_stream = stream.strip()

    class_row = cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?", (cid, sid)).fetchone() if cid else None
    if not selected_stream and class_row:
        selected_stream = str(class_row["stream"] or "")

    class_students = [s for s in students if int(s["class_id"] or 0) == cid]
    if selected_stream:
        class_students = [s for s in class_students if str(s["stream"] or class_row["stream"] if class_row else "") == selected_stream]

    # Restrict the displayed marks to the chosen academic filters.
    marks = {}
    if eid and cid:
        q = "SELECT student_id,subject_id,marks FROM marks WHERE school_id=? AND exam_id=? AND class_id=?"
        params = [sid, eid, cid]
        if selected_term:
            q += " AND term=?"; params.append(selected_term)
        if selected_year:
            q += " AND year=?"; params.append(selected_year)
        if subid:
            q += " AND subject_id=?"; params.append(subid)
        for row in cur.execute(q, params).fetchall():
            marks[(int(row["student_id"]), int(row["subject_id"]))] = row["marks"]

    # If no term/year was explicitly chosen, the exam selection supplies them.
    if eid:
        exam_row = cur.execute("SELECT term,year FROM exams WHERE id=? AND school_id=?", (eid, sid)).fetchone()
        if exam_row:
            if not selected_term: selected_term = str(exam_row["term"] or "")
            if not selected_year: selected_year = str(exam_row["year"] or "")

    con.close()

    eopts = "".join(f"<option value='{e['id']}' {'selected' if e['id']==eid else ''}>{escape(str(e['name']))} ({escape(str(e['year'] or ''))})</option>" for e in exams)
    copts = "".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    subjopts = "".join(f"<option value='{s['id']}' {'selected' if s['id']==subid else ''}>{escape(str(s['name']))}</option>" for s in subjects)
    stream_values = sorted({str(c["stream"] or "") for c in classes if str(c["stream"] or "")} | {str(s["stream"] or "") for s in class_students if str(s["stream"] or "")})
    streamopts = "".join(f"<option value='{escape(v)}' {'selected' if v==selected_stream else ''}>{escape(v)}</option>" for v in stream_values)
    termopts = "".join(f"<option value='{x}' {'selected' if x==selected_term else ''}>{x}</option>" for x in TERM_OPTIONS)
    yearopts = "".join(f"<option value='{y}' {'selected' if y==selected_year else ''}>{y}</option>" for y in YEAR_OPTIONS)

    # Subject columns for a complete class marksheet. If a subject is selected,
    # show only that subject; otherwise show all school subjects.
    display_subjects = [s for s in subjects if not subid or int(s["id"]) == subid]
    header = "".join(f"<th>{escape(str(s['name']))}</th>" for s in display_subjects)
    body_rows = []
    for idx, student in enumerate(class_students, 1):
        cells = []
        total = 0.0
        count = 0
        for subj in display_subjects:
            val = marks.get((int(student["id"]), int(subj["id"])))
            if val is not None:
                total += float(val or 0); count += 1
                cells.append(f"<td>{float(val):.1f}</td>")
            else:
                cells.append("<td>—</td>")
        avg = total / count if count else 0
        body_rows.append(f"<tr><td>{idx}</td><td>{escape(str(student['admission_no'] or ''))}</td><td><b>{escape(str(student['name'] or ''))}</b></td>{''.join(cells)}<td>{total:.1f}</td><td>{avg:.1f}%</td><td>{_grade(avg) if count else '—'}</td></tr>")
    rows_html = "".join(body_rows)

    title = "Class Marks Summary" if view == "summary" else "Class Marksheets"
    body = f"""<div class='page'><h1>{title}</h1>
<div class='muted'>Select class, stream, term, year, examination and subject. Changing a selection reloads the marksheet immediately.</div>
<div class='card section'>
<form method='get' action='/app/academics/marksheets' style='display:grid;grid-template-columns:repeat(6,1fr);gap:10px'>
<select name='class_id' class='field' onchange='this.form.submit()'><option value=''>Select class</option>{copts}</select>
<select name='stream' class='field' onchange='this.form.submit()'><option value=''>All streams</option>{streamopts}</select>
<select name='term' class='field' onchange='this.form.submit()'><option value=''>All terms</option>{termopts}</select>
<select name='year' class='field' onchange='this.form.submit()'><option value=''>All years</option>{yearopts}</select>
<select name='exam_id' class='field' onchange='this.form.submit()'><option value=''>Select examination</option>{eopts}</select>
<select name='subject_id' class='field' onchange='this.form.submit()'><option value=''>All subjects</option>{subjopts}</select>
</form>
<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:12px'>
<a class='btnlink' href='/app/academics/marksheets?class_id={cid}&exam_id={eid}&term={escape(selected_term)}&year={escape(selected_year)}'>All Subjects</a>
<a class='btnlink' href='/app/academics/marks?class_id={cid}&exam_id={eid}'>Enter / Edit Marks</a>
<button class='btnlink' onclick='window.print()'>Print Marksheet</button>
<button class='btnlink' onclick='downloadMarksheet()'>Download CSV</button>
</div>
</div>
<div class='card section'>
<div style='display:flex;justify-content:space-between;align-items:center'><div><h2>{escape(str(class_row['name'] if class_row else 'Select a class'))} {escape(str(selected_stream))}</h2><div class='muted'>{escape(selected_term or 'All terms')} · {escape(selected_year or 'All years')} · {escape(str(next((e['name'] for e in exams if e['id']==eid), 'All exams')))}</div></div><strong>{len(class_students)} students</strong></div>
<div style='overflow:auto;margin-top:12px'><table id='marksheetTable'><thead><tr><th>Pos</th><th>Admission</th><th>Student</th>{header}<th>Total</th><th>Average</th><th>Grade</th></tr></thead><tbody>{rows_html or '<tr><td colspan=10>No students or marks found for the selected class.</td></tr>'}</tbody></table></div>
</div></div>
<style>
.field{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:white;cursor:pointer}
.btnlink{display:inline-block;padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:white;color:#172033;text-decoration:none;font-weight:800;cursor:pointer}
@media print{.side,.top,.card:first-child{display:none!important}.page{padding:0}.card{border:0;box-shadow:none}}
</style>
<script>
function downloadMarksheet(){
 const table=document.getElementById('marksheetTable');
 if(!table)return;
 const rows=[...table.querySelectorAll('tr')].map(r=>[...r.querySelectorAll('th,td')].map(c=>'"'+c.innerText.replace(/"/g,'""')+'"').join(','));
 const blob=new Blob([rows.join('\\n')],{type:'text/csv'});
 const url=URL.createObjectURL(blob); const a=document.createElement('a');
 a.href=url; a.download='class-marksheet.csv'; a.click(); URL.revokeObjectURL(url);
}
</script>"""
    return _school_page(request, title, body)


@router.get("/app/finance", response_class=HTMLResponse)
def finance_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    fee=cur.execute("SELECT COALESCE(SUM(amount),0) expected,COALESCE(SUM(paid),0) paid FROM fees WHERE school_id=?",(sid,)).fetchone()
    exp=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM expenses WHERE school_id=?",(sid,)).fetchone()["v"]
    payments=cur.execute("SELECT fp.*,s.name student_name FROM fee_payments fp LEFT JOIN students s ON s.id=fp.student_id WHERE fp.school_id=? ORDER BY fp.id DESC LIMIT 50",(sid,)).fetchall();con.close()
    rows="".join(f"<tr><td>{escape(str(p['student_name'] or ''))}</td><td>KES {float(p['amount'] or 0):,.2f}</td><td>{escape(str(p['date'] or ''))}</td><td>{escape(str(p['reference'] or ''))}</td></tr>" for p in payments)
    body=f"""<div class='page'><h1>Finance & Fees</h1><div class='muted'>Fee register, collections, expenses and financial control.</div><div class='grid'><div class='card'><div class='label'>Fees charged</div><div class='kpi'>KES {float(fee['expected'] or 0):,.0f}</div></div><div class='card'><div class='label'>Collected</div><div class='kpi'>KES {float(fee['paid'] or 0):,.0f}</div></div><div class='card'><div class='label'>Outstanding</div><div class='kpi'>KES {float(fee['expected'] or 0)-float(fee['paid'] or 0):,.0f}</div></div><div class='card'><div class='label'>Expenses</div><div class='kpi'>KES {float(exp or 0):,.0f}</div></div></div><div class='section'><div class='actions'><a class='action' href='/app/finance'><span>💳</span>Finance Workspace</a><a class='action' href='/app/finance'><span>📚</span>Accounting</a><a class='action' href='/app/finance'><span>⚖</span>Trial Balance</a><a class='action' href='/app/finance/fees'><span>📒</span>Fee Register</a></div></div><div class='card section'><h2>Recent fee payments</h2><table><thead><tr><th>Student</th><th>Amount</th><th>Date</th><th>Receipt</th></tr></thead><tbody>{rows or '<tr><td colspan=4>No payments yet.</td></tr>'}</tbody></table></div></div>"""
    return _school_page(request,"Finance & Fees",body)


@router.get("/app", response_class=HTMLResponse)
def app_home(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    role=request.session.get("role","")
    name=request.session.get("name","DaviSchool")
    con=_db(); cur=con.cursor()
    if role=="super_admin":
        schools=cur.execute("SELECT COUNT(*) c FROM schools").fetchone()["c"]
        users=cur.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        students=cur.execute("SELECT COUNT(*) c FROM students").fetchone()["c"]
        revenue=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM fee_payments").fetchone()["v"]
        recent=cur.execute("SELECT name,location FROM schools ORDER BY id DESC LIMIT 8").fetchall()
        con.close()
        rows="".join(f"<tr><td>{escape(r['name'])}</td><td>{escape(r['location'] or '')}</td><td>Active</td></tr>" for r in recent)
        body=f"""<div class='page'><h1>Platform Overview</h1><div class='muted'>One control centre for every DaviSchool institution.</div>
<div class='grid'><div class='card'><div class='label'>Schools</div><div class='kpi'>{schools}</div></div><div class='card'><div class='label'>Users</div><div class='kpi'>{users}</div></div><div class='card'><div class='label'>Students</div><div class='kpi'>{students}</div></div><div class='card'><div class='label'>Fees received</div><div class='kpi'>KES {revenue:,.0f}</div></div></div>
<div class='section'><h2>Platform controls</h2><div class='actions'><a class='action' href='/schools/manage'><span>🏫</span>Manage Schools</a><a class='action' href='/super/global-control/dashboard'><span>🌍</span>Global Control</a><a class='action' href='/school/system-audit'><span>🛡</span>Audit & Security</a><a class='action' href='/account/change-password'><span>🔑</span>My Account</a></div></div>
<div class='section'><h2>Institutions</h2><table><thead><tr><th>School</th><th>Location</th><th>Status</th></tr></thead><tbody>{rows or '<tr><td colspan=3>No schools yet</td></tr>'}</tbody></table></div></div>"""
    else:
        school_id=request.session.get("school_id",0)
        school=cur.execute("SELECT * FROM schools WHERE id=?",(school_id,)).fetchone()
        s=cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?",(school_id,)).fetchone()["c"]
        t=cur.execute("SELECT COUNT(*) c FROM teachers WHERE school_id=?",(school_id,)).fetchone()["c"]
        c=cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?",(school_id,)).fetchone()["c"]
        fees=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM fee_payments WHERE school_id=?",(school_id,)).fetchone()["v"]
        con.close()
        school_name=school["name"] if school else "School"
        body=f"""<div class='page'><h1>{escape(school_name)}</h1><div class='muted'>Your complete school operating centre.</div>
<div class='grid'><div class='card'><div class='label'>Students</div><div class='kpi'>{s}</div></div><div class='card'><div class='label'>Staff</div><div class='kpi'>{t}</div></div><div class='card'><div class='label'>Classes</div><div class='kpi'>{c}</div></div><div class='card'><div class='label'>Fees received</div><div class='kpi'>KES {fees:,.0f}</div></div></div>
<div class='section'><h2>Daily operations</h2><div class='actions'><a class='action' href='/school/students'><span>🎓</span>Students</a><a class='action' href='/app/academics/marks'><span>📝</span>Record Marks</a><a class='action' href='/app/attendance/bulk'><span>✓</span>Attendance</a><a class='action' href='/app/finance'><span>💰</span>Finance</a><a class='action' href='/app/report-cards'><span>📄</span>Report Cards</a><a class='action' href='/app/academics/analysis'><span>📊</span>Analysis</a><a class='action' href='/app/finance'><span>📚</span>Accounting</a><a class='action' href='/school/system-settings/user-management'><span>👤</span>Users</a></div></div>
<div class='section'><h2>Administration</h2><div class='actions'><a class='action' href='/school/system-settings/school-profile'><span>⚙</span>School Settings</a><a class='action' href='/school/system-settings/roles-permissions'><span>🔐</span>Roles</a><a class='action' href='/school/system-audit'><span>🛡</span>Audit Trail</a><a class='action' href='/portal'><span>🌐</span>Portals</a></div></div></div>"""
    return HTMLResponse(_shell("DaviSchool",name,role,body))


def _grade(mark, out_of=100):
    try:
        p=(float(mark)/float(out_of))*100
    except Exception:
        p=0
    if p>=80: return "A"
    if p>=75: return "A-"
    if p>=70: return "B+"
    if p>=65: return "B"
    if p>=60: return "B-"
    if p>=55: return "C+"
    if p>=50: return "C"
    if p>=45: return "C-"
    if p>=40: return "D+"
    if p>=30: return "D"
    return "E"

@router.get("/app/academics/marks", response_class=HTMLResponse)
def marks_page(request: Request, exam_id: str="", class_id: str="", subject_id: str=""):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    con=_db(); cur=con.cursor()
    exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    cid=int(class_id) if class_id.isdigit() else 0
    subid=int(subject_id) if subject_id.isdigit() else 0
    students=[]
    if eid and cid and subid:
        students=cur.execute("""SELECT s.id,s.admission_no,s.name,COALESCE(m.marks,'') marks
          FROM students s LEFT JOIN marks m ON m.student_id=s.id AND m.exam_id=? AND m.subject_id=? AND m.school_id=?
          WHERE s.school_id=? AND s.class_id=? ORDER BY s.name""",(eid,subid,sid,sid,cid)).fetchall()
    con.close()
    eopts="".join(f"<option value='{e['id']}' {'selected' if e['id']==eid else ''}>{escape(str(e['name']))} ({escape(str(e['year'] or ''))})</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    sopts="".join(f"<option value='{s['id']}' {'selected' if s['id']==subid else ''}>{escape(str(s['name']))}</option>" for s in subjects)
    rows="".join(f"<tr><td>{escape(str(x['admission_no'] or ''))}</td><td><b>{escape(str(x['name'] or ''))}</b></td><td><input name='mark_{x['id']}' value='{escape(str(x['marks']))}' type='number' min='0' max='100' step='0.01' style='width:100px;padding:8px;border:1px solid #dbe2ea;border-radius:8px'></td><td>{_grade(x['marks']) if x['marks']!='' else '—'}</td></tr>" for x in students)
    body=f"""<div class='page'><h1>Marks Entry</h1><div class='muted'>Enter, update and review marks by examination, class and subject.</div>
<div class='card section'><form method='get' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'><select name='exam_id' class='field'>{eopts}</select><select name='class_id' class='field'><option value=''>Select class</option>{copts}</select><select name='subject_id' class='field'><option value=''>Select subject</option>{sopts}</select><button class='btn'>Load Students</button></form></div>
<div class='card section'><form method='post' action='/app/academics/marks/save'><input type='hidden' name='exam_id' value='{eid}'><input type='hidden' name='class_id' value='{cid}'><input type='hidden' name='subject_id' value='{subid}'><table><thead><tr><th>Admission</th><th>Student</th><th>Mark / 100</th><th>Grade</th></tr></thead><tbody>{rows or '<tr><td colspan=4>Select an exam, class and subject, then load students.</td></tr>'}</tbody></table>{'<button class="btn" style="margin-top:12px">Save Marks</button>' if students else ''}</form></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Marks Entry",body)

@router.post("/app/academics/marks/save")
async def marks_save(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    form=await request.form()
    con=_db();cur=con.cursor()
    valid=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not valid: con.close(); return HTMLResponse("Invalid academic selection. <a href='/app/academics/marks'>Back</a>",400)
    exam=cur.execute("SELECT year,term FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
    students=cur.execute("SELECT id FROM students WHERE school_id=? AND class_id=?",(sid,class_id)).fetchall()
    for st in students:
        raw=form.get(f"mark_{st['id']}")
        if raw is None or str(raw).strip()=="":
            continue
        try: mark=float(raw); mark_int=int(mark) if mark.is_integer() else mark
        except Exception: continue
        if mark<0 or mark>100: continue
        old=cur.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=?",(sid,st["id"],subject_id,exam_id)).fetchone()
        if old:
            cur.execute("UPDATE marks SET marks=?,class_id=?,year=?,term=? WHERE id=?",(mark_int,class_id,exam["year"],exam["term"],old["id"]))
        else:
            cur.execute("INSERT INTO marks(school_id,student_id,subject_id,exam_id,class_id,marks,year,term) VALUES(?,?,?,?,?,?,?,?)",(sid,st["id"],subject_id,exam_id,class_id,mark_int,exam["year"],exam["term"]))
    _audit(cur,sid,request,"MARKS_SAVE",f"Saved marks for exam {exam_id}, class {class_id}, subject {subject_id}")
    con.commit();con.close()
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

@router.get("/app/academics/analysis", response_class=HTMLResponse)
def new_analysis(request: Request, exam_id:str="", class_id:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    cid=int(class_id) if class_id.isdigit() else 0
    stats=[]
    if eid:
        q="""SELECT sub.name subject,COUNT(m.id) entries,COALESCE(AVG(m.marks),0) avg_mark,
          COALESCE(MAX(m.marks),0) high,COALESCE(MIN(m.marks),0) low
          FROM subjects sub LEFT JOIN marks m ON m.subject_id=sub.id AND m.exam_id=? AND m.school_id=?"""
        params=[eid,sid]
        if cid:
            q+=" AND m.class_id=?";params.append(cid)
        q+=" WHERE sub.school_id=? GROUP BY sub.id,sub.name ORDER BY sub.name"
        params.append(sid);stats=cur.execute(q,params).fetchall()
    con.close()
    eopts="".join(f"<option value='{e['id']}' {'selected' if e['id']==eid else ''}>{escape(str(e['name']))}</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    rows="".join(f"<tr><td>{escape(str(x['subject']))}</td><td>{x['entries']}</td><td>{float(x['avg_mark'] or 0):.2f}</td><td>{x['high']}</td><td>{x['low']}</td></tr>" for x in stats)
    body=f"""<div class='page'><h1>Academic Analysis</h1><div class='muted'>Subject performance for a selected examination and class.</div><div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_id' class='field'>{eopts}</select><select name='class_id' class='field'><option value=''>All classes</option>{copts}</select><button class='btn'>Analyse</button></form></div><div class='card section'><table><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No marks found.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Academic Analysis",body)

@router.get("/app/report-cards", response_class=HTMLResponse)
def report_cards(request: Request, exam_id:str="", student_id:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    students=cur.execute("SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(sid,)).fetchall()
    eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    stid=int(student_id) if student_id.isdigit() else (int(students[0]["id"]) if students else 0)
    st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(stid,sid)).fetchone()
    rows=[];comment=""
    if st and eid:
        rows=cur.execute("""SELECT sub.name,m.marks FROM marks m JOIN subjects sub ON sub.id=m.subject_id
          WHERE m.school_id=? AND m.student_id=? AND m.exam_id=? ORDER BY sub.name""",(sid,stid,eid)).fetchall()
        cm=cur.execute("SELECT comment FROM report_comments WHERE school_id=? AND student_id=? AND exam_id=? ORDER BY id DESC LIMIT 1",(sid,stid,eid)).fetchone()
        comment=cm["comment"] if cm else ""
    eopts="".join(f"<option value='{e['id']}' {'selected' if e['id']==eid else ''}>{escape(str(e['name']))} {escape(str(e['year'] or ''))}</option>" for e in exams)
    sopts="".join(f"<option value='{s['id']}' {'selected' if s['id']==stid else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    total=sum(float(r["marks"] or 0) for r in rows);avg=total/len(rows) if rows else 0
    markrows="".join(f"<tr><td>{escape(str(r['name']))}</td><td>{r['marks']}</td><td>{_grade(r['marks'])}</td></tr>" for r in rows)
    report_html=f"""<div class='card section' id='report'><h2>{escape(str(st['name']))}</h2><div class='muted'>Admission: {escape(str(st['admission_no'] or ''))} · Class: {escape(str(st['class_name'] or ''))} {escape(str(st['stream'] or ''))}</div><table style='margin-top:14px'><thead><tr><th>Subject</th><th>Mark</th><th>Grade</th></tr></thead><tbody>{markrows}</tbody></table><div class='grid'><div class='card'><div class='label'>Subjects</div><div class='kpi'>{len(rows)}</div></div><div class='card'><div class='label'>Total</div><div class='kpi'>{total:.1f}</div></div><div class='card'><div class='label'>Average</div><div class='kpi'>{avg:.1f}%</div></div></div><form method='post' action='/app/report-cards/comment'><input type='hidden' name='exam_id' value='{eid}'><input type='hidden' name='student_id' value='{stid}'><textarea name='comment' class='field' rows='3' placeholder='Teacher / principal comment'>{escape(str(comment or ''))}</textarea><button class='btn' style='margin-top:8px'>Save Comment</button></form><button class='btn' style='margin-top:8px' onclick='window.print()'>Print Report</button></div>""" if st else "<div class='card section'>Select a student and examination.</div>"
    body=f"""<div class='page'><h1>Report Cards</h1><div class='muted'>Generate a print-ready student academic report.</div><div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_id' class='field'>{eopts}</select><select name='student_id' class='field'>{sopts}</select><button class='btn'>Generate</button></form></div>{report_html}</div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Report Cards",body)

@router.post("/app/report-cards/comment")
def report_comment(request: Request, exam_id:int=Form(...), student_id:int=Form(...), comment:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor()
    if cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone():
        cur.execute("INSERT INTO report_comments(school_id,student_id,exam_id,comment,created_at) VALUES(?,?,?,?,?)",(sid,student_id,exam_id,comment.strip(),datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")))
        _audit(cur,sid,request,"REPORT_COMMENT","Updated report comment")
    con.commit();con.close();return RedirectResponse(f"/app/report-cards?exam_id={exam_id}&student_id={student_id}",303)

@router.get("/app/attendance", response_class=HTMLResponse)
def attendance_page(request: Request, class_id:str="", date:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    today=date or datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d")
    cid=int(class_id) if class_id.isdigit() else 0
    con=_db();cur=con.cursor()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    students=cur.execute("SELECT s.id,s.name,s.admission_no,COALESCE(a.status,'Present') status FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.school_id=? AND a.date=? WHERE s.school_id=? AND s.class_id=? ORDER BY s.name",(sid,today,sid,cid)).fetchall() if cid else []
    con.close()
    opts="".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    rows="".join(f"<tr><td>{escape(str(s['admission_no'] or ''))}</td><td>{escape(str(s['name']))}</td><td><select name='status_{s['id']}' class='field'><option {'selected' if s['status']=='Present' else ''}>Present</option><option {'selected' if s['status']=='Absent' else ''}>Absent</option><option {'selected' if s['status']=='Late' else ''}>Late</option><option {'selected' if s['status']=='Excused' else ''}>Excused</option></select></td></tr>" for s in students)
    body=f"""<div class='page'><h1>Attendance</h1><div class='muted'>Daily class register with bulk status saving.</div><div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='class_id' class='field'><option value=''>Select class</option>{opts}</select><input type='date' name='date' value='{today}' class='field'><button class='btn'>Load Register</button></form></div><div class='card section'><form method='post' action='/app/attendance/save'><input type='hidden' name='class_id' value='{cid}'><input type='hidden' name='date' value='{today}'><table><thead><tr><th>Admission</th><th>Student</th><th>Status</th></tr></thead><tbody>{rows or '<tr><td colspan=3>Select a class and date.</td></tr>'}</tbody></table>{'<button class="btn" style="margin-top:12px">Save Attendance</button>' if students else ''}</form></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Attendance",body)

@router.post("/app/attendance/save")
async def attendance_save(request: Request, class_id:int=Form(...), date:str=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    form=await request.form();con=_db();cur=con.cursor()
    students=cur.execute("SELECT id FROM students WHERE school_id=? AND class_id=?",(sid,class_id)).fetchall()
    for s in students:
        status=str(form.get(f"status_{s['id']}","Present"))
        old=cur.execute("SELECT id FROM attendance WHERE school_id=? AND student_id=? AND date=?",(sid,s["id"],date)).fetchone()
        if old: cur.execute("UPDATE attendance SET status=? WHERE id=?",(status,old["id"]))
        else: cur.execute("INSERT INTO attendance(school_id,student_id,date,status) VALUES(?,?,?,?)",(sid,s["id"],date,status))
    _audit(cur,sid,request,"ATTENDANCE_SAVE",f"Saved attendance for class {class_id} on {date}")
    con.commit();con.close();return RedirectResponse(f"/app/attendance?class_id={class_id}&date={date}",303)


@router.get("/app/users", response_class=HTMLResponse)
def users_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    users=cur.execute("""SELECT u.*,t.name teacher_name,s.name student_name
        FROM users u LEFT JOIN teachers t ON t.id=u.teacher_id LEFT JOIN students s ON s.id=u.student_id
        WHERE u.school_id=? ORDER BY u.id DESC""",(sid,)).fetchall()
    teachers=cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    con.close()
    rows="".join(f"<tr><td>{escape(str(u['full_name'] or ''))}</td><td>{escape(str(u['email'] or ''))}</td><td>{escape(str(u['role'] or ''))}</td><td>{escape(str(u['teacher_name'] or u['student_name'] or '—'))}</td></tr>" for u in users)
    topts="".join(f"<option value='{t['id']}'>{escape(str(t['name']))}</option>" for t in teachers)
    sopts="".join(f"<option value='{s['id']}'>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    body=f"""<div class='page'><h1>User Management</h1><div class='muted'>Create school accounts and link them to staff or students.</div>
<div class='card section'><h2>Create user</h2><form method='post' action='/app/users/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<input name='full_name' required placeholder='Full name' class='field'><input name='email' type='email' required placeholder='Email' class='field'><input name='password' type='password' required minlength='8' placeholder='Temporary password' class='field'>
<select name='role' class='field'><option value='school_admin'>School Admin</option><option value='teacher'>Teacher</option><option value='parent'>Parent</option><option value='student'>Student</option><option value='accountant'>Accountant</option><option value='registrar'>Registrar</option></select>
<select name='teacher_id' class='field'><option value=''>Link teacher (optional)</option>{topts}</select><select name='student_id' class='field'><option value=''>Link student (optional)</option>{sopts}</select>
<button class='btn'>Create Account</button></form></div>
<div class='card section'><h2>Accounts ({len(users)})</h2><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Linked profile</th></tr></thead><tbody>{rows or '<tr><td colspan=4>No users yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"User Management",body)

@router.post("/app/users/add")
def users_add(request: Request, full_name:str=Form(...), email:str=Form(...), password:str=Form(...), role:str=Form("teacher"), teacher_id:str=Form(""), student_id:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if len(password)<8:return HTMLResponse("Password must be at least 8 characters. <a href='/app/users'>Back</a>",400)
    allowed={"school_admin","teacher","parent","student","accountant","registrar"}
    if role not in allowed:return HTMLResponse("Invalid role. <a href='/app/users'>Back</a>",400)
    con=_db();cur=con.cursor()
    if cur.execute("SELECT id FROM users WHERE email=?",(email.strip(),)).fetchone():
        con.close();return HTMLResponse("Email already exists. <a href='/app/users'>Back</a>",400)
    tid=int(teacher_id) if teacher_id.isdigit() else None
    stid=int(student_id) if student_id.isdigit() else None
    if tid and not cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(tid,sid)).fetchone(): tid=None
    if stid and not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(stid,sid)).fetchone(): stid=None
    from app.main import hash_password
    cur.execute("INSERT INTO users(email,password,role,full_name,school_id,teacher_id,student_id) VALUES(?,?,?,?,?,?,?)",(email.strip(),hash_password(password),role,full_name.strip(),sid,tid,stid))
    _audit(cur,sid,request,"USER_CREATE",f"Created {role} account {email.strip()}")
    con.commit();con.close();return RedirectResponse("/app/users",303)


@router.get("/app/classes", response_class=HTMLResponse)
def classes_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor(); rows=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall();con.close()
    trs="".join(f"<tr><td>{escape(str(x['name']))}</td><td>{escape(str(x['level'] or ''))}</td><td>{escape(str(x['stream'] or ''))}</td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Classes & Streams</h1><div class='card section'><form method='post' action='/app/classes/add' class='formgrid'><input name='name' required placeholder='Class name e.g. Grade 6' class='field'><select name='level' class='field'><option value=''>Select level</option><option>Pre-Primary</option><option>Lower Primary</option><option>Upper Primary</option><option>Junior Secondary</option><option>Senior Secondary</option><option>College</option><option>Other</option></select><input name='stream' placeholder='Stream' class='field'><button class='btn'>Add Class</button></form></div><div class='card section'><table><thead><tr><th>Name</th><th>Level</th><th>Stream</th></tr></thead><tbody>{trs or '<tr><td colspan=3>No classes.</td></tr>'}</tbody></table></div></div><style>.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Classes",body)

@router.post("/app/classes/add")
def classes_add(request: Request,name:str=Form(...),level:str=Form(""),stream:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();cur.execute("INSERT INTO classes(school_id,name,level,stream) VALUES(?,?,?,?)",(sid,name.strip(),level.strip(),stream.strip()));_audit(cur,sid,request,"CLASS_CREATE",name.strip());con.commit();con.close();return RedirectResponse("/app/classes",303)

@router.get("/app/subjects", response_class=HTMLResponse)
def subjects_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor(); rows=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall();con.close()
    trs="".join(f"<tr><td>{escape(str(x['name']))}</td><td>{escape(str(x['code'] or ''))}</td><td>{escape(str(x['initial'] or ''))}</td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Subjects</h1><div class='card section'><form method='post' action='/app/subjects/add' class='formgrid'><input name='name' required placeholder='Subject name' class='field'><input name='code' placeholder='Code' class='field'><input name='initial' placeholder='Initial' class='field'><button class='btn'>Add Subject</button></form></div><div class='card section'><table><thead><tr><th>Subject</th><th>Code</th><th>Initial</th></tr></thead><tbody>{trs or '<tr><td colspan=3>No subjects.</td></tr>'}</tbody></table></div></div><style>.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Subjects",body)

@router.post("/app/subjects/add")
def subjects_add(request: Request,name:str=Form(...),code:str=Form(""),initial:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();cur.execute("INSERT INTO subjects(school_id,name,code,initial) VALUES(?,?,?,?)",(sid,name.strip(),code.strip(),initial.strip()));_audit(cur,sid,request,"SUBJECT_CREATE",name.strip());con.commit();con.close();return RedirectResponse("/app/subjects",303)

@router.get("/app/exams", response_class=HTMLResponse)
def exams_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall();con.close()
    trs="".join(f"<tr><td>{escape(str(x['name']))}</td><td>{escape(str(x['exam_type'] or ''))}</td><td>{escape(str(x['term'] or ''))}</td><td>{escape(str(x['year'] or ''))}</td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Examinations</h1><div class='card section'><form method='post' action='/app/exams/add' class='formgrid'><input name='name' required placeholder='Exam name' class='field'><select name='exam_type' class='field'><option value=''>Select exam type</option><option>CAT</option><option>Mid-Term</option><option>End-Term</option><option>Mock</option><option>Final</option><option>SBA/CBA</option></select><select name='term' class='field'><option value=''>Select term</option><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><select name='year' class='field'>{''.join('<option>'+y+'</option>' for y in YEAR_OPTIONS)}</select><button class='btn'>Create Exam</button></form></div><div class='card section'><table><thead><tr><th>Name</th><th>Type</th><th>Term</th><th>Year</th></tr></thead><tbody>{trs or '<tr><td colspan=4>No examinations.</td></tr>'}</tbody></table></div></div><style>.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Examinations",body)

@router.post("/app/exams/add")
def exams_add(request: Request,name:str=Form(...),exam_type:str=Form(""),term:str=Form(""),year:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();cur.execute("INSERT INTO exams(school_id,name,term,year,exam_type) VALUES(?,?,?,?,?)",(sid,name.strip(),term.strip(),year.strip(),exam_type.strip()));_audit(cur,sid,request,"EXAM_CREATE",name.strip());con.commit();con.close();return RedirectResponse("/app/exams",303)

@router.get("/app/finance/fees", response_class=HTMLResponse)
def fees_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    fees=cur.execute("""SELECT f.*,s.name student_name,s.admission_no FROM fees f JOIN students s ON s.id=f.student_id
        WHERE f.school_id=? ORDER BY f.id DESC LIMIT 100""",(sid,)).fetchall()
    con.close()
    sopts="".join(f"<option value='{s['id']}'>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    trs="".join(f"<tr><td>{escape(str(x['student_name']))}</td><td>{x['amount']}</td><td>{x['paid'] or 0}</td><td>{x['status'] or 'Pending'}</td><td>{escape(str(x['description'] or ''))}</td></tr>" for x in fees)
    body=f"""<div class='page'><h1>Fees & Student Charges</h1><div class='card section'><h2>Charge a student</h2><form method='post' action='/app/finance/fees/add' class='formgrid'><select name='student_id' class='field' required>{sopts}</select><input name='amount' type='number' step='0.01' min='0' required placeholder='Amount' class='field'><select name='description' required class='field'><option value=''>Select charge type</option><option>Tuition Fees</option><option>Activity Fees</option><option>Examination Fees</option><option>Transport</option><option>Boarding</option><option>Lunch / Meals</option><option>Uniform</option><option>Books</option><option>Other</option></select><input name='due_date' type='date' class='field'><button class='btn'>Post Charge</button></form></div><div class='card section'><h2>Receive fee payment</h2><form method='post' action='/app/finance/payments' class='formgrid'><select name='student_id' class='field' required>{sopts}</select><input name='amount' type='number' step='0.01' min='0.01' required placeholder='Amount' class='field'><select name='method' class='field'><option>Cash</option><option>Bank</option><option>Mobile Money</option><option>Cheque</option><option>Card</option><option>Other</option></select><input name='reference' placeholder='Receipt / reference' class='field'><button class='btn'>Record Payment</button></form></div><div class='card section'><table><thead><tr><th>Student</th><th>Charged</th><th>Paid</th><th>Status</th><th>Description</th></tr></thead><tbody>{trs or '<tr><td colspan=5>No fee charges.</td></tr>'}</tbody></table></div></div><style>.formgrid{{display:grid;grid-template-columns:1.5fr 1fr 1.5fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Fees",body)

@router.post("/app/finance/fees/add")
def fees_add(request: Request,student_id:int=Form(...),amount:float=Form(...),description:str=Form(...),due_date:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor()
    if cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone():
        cur.execute("INSERT INTO fees(school_id,student_id,amount,paid,description,due_date,status) VALUES(?,?,?,?,?,?,?)",(sid,student_id,amount,0,description.strip(),due_date or None,"Pending"));_audit(cur,sid,request,"FEE_CHARGE",f"Charged {amount} to student {student_id}")
    con.commit();con.close();return RedirectResponse("/app/finance/fees",303)

@router.post("/app/finance/payments")
def fee_payment(request: Request,student_id:int=Form(...),amount:float=Form(...),reference:str=Form(""),method:str=Form("Cash")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor()
    if cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone():
        now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d")
        cur.execute("INSERT INTO fee_payments(school_id,student_id,amount,reference,method,date,received_by) VALUES(?,?,?,?,?,?,?)",(sid,student_id,amount,reference.strip(),method,now,str(request.session.get("user_email",""))))
        remaining=amount
        charges=cur.execute("SELECT id,amount,paid FROM fees WHERE school_id=? AND student_id=? AND COALESCE(amount,0)>COALESCE(paid,0) ORDER BY id",(sid,student_id)).fetchall()
        for f in charges:
            if remaining<=0:break
            applied=min(remaining,float(f["amount"])-float(f["paid"] or 0)); newpaid=float(f["paid"] or 0)+applied; remaining-=applied
            cur.execute("UPDATE fees SET paid=?,status=? WHERE id=?",(newpaid,"Paid" if newpaid>=float(f["amount"]) else "Partial",f["id"]))
        cur.execute("INSERT INTO cashbook(school_id,date,reference,description,debit,credit,account) VALUES(?,?,?,?,?,?,?)",(sid,now,reference,"School fee receipt",0,amount,"Fees"))
        _audit(cur,sid,request,"FEE_PAYMENT",f"Received {amount} from student {student_id}")
    con.commit();con.close();return RedirectResponse("/app/finance/fees",303)

# Additional native DaviSchool workspaces
def _simple_rows(rows, cols):
    return "".join("<tr>"+"".join(f"<td>{escape(str(row[c] if row[c] is not None else ''))}</td>" for c in cols)+"</tr>" for row in rows)

@router.get("/app/timetable", response_class=HTMLResponse)
def timetable_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    rows=cur.execute("SELECT * FROM timetable WHERE school_id=? ORDER BY day,start_time",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    teachers=cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    con.close()
    co="".join(f"<option>{escape(str(x['name']))} {escape(str(x['stream'] or ''))}</option>" for x in classes)
    streams=sorted({str(x['stream'] or '').strip() for x in classes if str(x['stream'] or '').strip()})
    to="".join(f"<option>{escape(str(x['name']))}</option>" for x in teachers)
    so="".join(f"<option>{escape(str(x['name']))}</option>" for x in subjects)
    stro="".join(f"<option>{escape(x)}</option>" for x in streams)
    tr=_simple_rows(rows,["day","start_time","end_time","class_name","stream","subject","teacher","room"])
    body=f"""<div class='page'><h1>Timetable</h1><div class='muted'>Build and maintain the school timetable.</div>
<div class='card section'><h2>Add lesson</h2><form method='post' action='/app/timetable/add' style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>
<select name='day' class='field'><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option><option>Saturday</option></select><input name='start_time' required type='time' class='field'><input name='end_time' required type='time' class='field'><select name='class_name' class='field'>{co}</select><select name='stream' class='field'><option value=''>Select stream</option>{stro}</select><select name='subject' class='field'>{so}</select><select name='teacher' class='field'>{to}</select><input name='room' placeholder='Room' class='field'><button class='btn'>Save Lesson</button></form></div>
<div class='card section'><h2>Weekly timetable ({len(rows)})</h2><table><thead><tr><th>Day</th><th>Start</th><th>End</th><th>Class</th><th>Stream</th><th>Subject</th><th>Teacher</th><th>Room</th></tr></thead><tbody>{tr or '<tr><td colspan=8>No timetable entries yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Timetable",body)

@router.post("/app/timetable/add")
def timetable_add(request: Request,day:str=Form(...),start_time:str=Form(...),end_time:str=Form(...),class_name:str=Form(""),stream:str=Form(""),subject:str=Form(""),teacher:str=Form(""),room:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor()
    cur.execute("INSERT INTO timetable(school_id,day,start_time,end_time,class_name,stream,subject,teacher,room) VALUES(?,?,?,?,?,?,?,?,?)",(sid,day,start_time,end_time,class_name,stream,subject,teacher,room))
    _audit(cur,sid,request,"TIMETABLE_CREATE",f"{day} {start_time}-{end_time} {class_name} {subject}")
    con.commit();con.close();return RedirectResponse("/app/timetable",303)

@router.get("/app/announcements", response_class=HTMLResponse)
def announcements_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM announcements WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall();con.close()
    tr=_simple_rows(rows,["title","message","audience","created_at"])
    body=f"""<div class='page'><h1>Announcements</h1><div class='muted'>Publish school notices and internal communications.</div>
<div class='card section'><h2>New announcement</h2><form method='post' action='/app/announcements/add' style='display:grid;gap:10px'><input name='title' required placeholder='Title' class='field'><select name='audience' class='field'><option>All</option><option>Students</option><option>Parents</option><option>Teachers</option><option>Staff</option></select><textarea name='message' required placeholder='Message' class='field' rows='5'></textarea><button class='btn'>Publish Announcement</button></form></div>
<div class='card section'><h2>Published announcements ({len(rows)})</h2><table><thead><tr><th>Title</th><th>Message</th><th>Audience</th><th>Created</th></tr></thead><tbody>{tr or '<tr><td colspan=4>No announcements yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Announcements",body)

@router.post("/app/announcements/add")
def announcements_add(request: Request,title:str=Form(...),message:str=Form(...),audience:str=Form("All")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO announcements(school_id,title,message,audience,created_at) VALUES(?,?,?,?,?)",(sid,title.strip(),message.strip(),audience,now))
    _audit(cur,sid,request,"ANNOUNCEMENT_CREATE",title.strip());con.commit();con.close();return RedirectResponse("/app/announcements",303)

@router.get("/app/roles", response_class=HTMLResponse)
def roles_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM roles_permissions WHERE school_id=? ORDER BY role,permission",(sid,)).fetchall();con.close()
    tr=_simple_rows(rows,["role","permission","enabled"])
    body=f"""<div class='page'><h1>Roles & Permissions</h1><div class='muted'>Control permissions for school roles.</div>
<div class='card section'><h2>Grant permission</h2><form method='post' action='/app/roles/add' style='display:grid;grid-template-columns:1fr 2fr 1fr;gap:10px'><select name='role' class='field'><option>school_admin</option><option>teacher</option><option>parent</option><option>student</option><option>accountant</option><option>registrar</option></select><select name='permission' required class='field'><option value=''>Select permission</option><option>students.view</option><option>students.create</option><option>students.edit</option><option>marks.view</option><option>marks.edit</option><option>attendance.edit</option><option>fees.view</option><option>fees.edit</option><option>finance.view</option><option>finance.edit</option><option>reports.view</option><option>users.manage</option><option>settings.manage</option></select><select name='enabled' class='field'><option value='1'>Enabled</option><option value='0'>Disabled</option></select><button class='btn'>Save Permission</button></form></div>
<div class='card section'><h2>Configured permissions ({len(rows)})</h2><table><thead><tr><th>Role</th><th>Permission</th><th>Enabled</th></tr></thead><tbody>{tr or '<tr><td colspan=3>No custom permissions yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Roles & Permissions",body)

@router.post("/app/roles/add")
def roles_add(request: Request,role:str=Form(...),permission:str=Form(...),enabled:int=Form(1)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();cur.execute("INSERT INTO roles_permissions(school_id,role,permission,enabled) VALUES(?,?,?,?)",(sid,role,permission.strip(),enabled))
    _audit(cur,sid,request,"PERMISSION_CHANGE",f"{role}: {permission.strip()}={enabled}");con.commit();con.close();return RedirectResponse("/app/roles",303)

@router.get("/app/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM system_audit WHERE school_id=? ORDER BY id DESC LIMIT 500",(sid,)).fetchall();con.close()
    tr=_simple_rows(rows,["timestamp","user_email","action","details"])
    body=f"""<div class='page'><h1>Audit Trail</h1><div class='muted'>Security and activity history for this school.</div><div class='card section'><h2>Recent activity ({len(rows)})</h2><table><thead><tr><th>Timestamp</th><th>User</th><th>Action</th><th>Details</th></tr></thead><tbody>{tr or '<tr><td colspan=4>No activity recorded yet.</td></tr>'}</tbody></table></div></div>"""
    return _school_page(request,"Audit Trail",body)

@router.get("/app/accounting", response_class=HTMLResponse)
def accounting_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    expenses=cur.execute("SELECT * FROM expenses WHERE school_id=? ORDER BY id DESC LIMIT 100",(sid,)).fetchall()
    vouchers=cur.execute("SELECT * FROM payment_vouchers WHERE school_id=? ORDER BY id DESC LIMIT 100",(sid,)).fetchall()
    lpos=cur.execute("SELECT * FROM lpos WHERE school_id=? ORDER BY id DESC LIMIT 100",(sid,)).fetchall()
    cash=cur.execute("SELECT COALESCE(SUM(credit),0) credit,COALESCE(SUM(debit),0) debit FROM cashbook WHERE school_id=?",(sid,)).fetchone()
    con.close()
    exp_total=sum(float(x["amount"] or 0) for x in expenses)
    body=f"""<div class='page'><h1>Accounting</h1><div class='muted'>School accounting workspace: expenses, vouchers, LPOs and cashbook.</div>
<div class='grid'><div class='card'><div class='label'>Expenses listed</div><div class='kpi'>{exp_total:,.2f}</div></div><div class='card'><div class='label'>Cash credits</div><div class='kpi'>{float(cash['credit'] or 0):,.2f}</div></div><div class='card'><div class='label'>Cash debits</div><div class='kpi'>{float(cash['debit'] or 0):,.2f}</div></div><div class='card'><div class='label'>Open LPOs</div><div class='kpi'>{len(lpos)}</div></div></div>
<div class='card section'><h2>Record expense</h2><form method='post' action='/app/accounting/expense' style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'><select name='category' required class='field'><option value=''>Select expense category</option><option>Salaries</option><option>Utilities</option><option>Stationery</option><option>Repairs & Maintenance</option><option>Transport</option><option>Food & Catering</option><option>Learning Materials</option><option>Rent</option><option>Other</option></select><input name='description' required placeholder='Description' class='field'><input name='amount' required type='number' step='0.01' placeholder='Amount' class='field'><input name='paid_to' placeholder='Paid to' class='field'><input name='voucher_no' placeholder='Voucher no.' class='field'><input name='date' type='date' class='field'><button class='btn'>Save Expense</button></form></div>
<div class='card section'><h2>Expenses</h2><table><thead><tr><th>Category</th><th>Description</th><th>Amount</th><th>Paid To</th><th>Voucher</th><th>Date</th></tr></thead><tbody>{_simple_rows(expenses,['category','description','amount','paid_to','voucher_no','date']) or '<tr><td colspan=6>No expenses yet.</td></tr>'}</tbody></table></div>
<div class='card section'><h2>Payment Vouchers ({len(vouchers)})</h2><table><thead><tr><th>Voucher</th><th>Payee</th><th>Description</th><th>Amount</th><th>Date</th><th>Status</th></tr></thead><tbody>{_simple_rows(vouchers,['voucher_no','payee','description','amount','date','status']) or '<tr><td colspan=6>No vouchers yet.</td></tr>'}</tbody></table></div>
<div class='card section'><h2>LPOs ({len(lpos)})</h2><table><thead><tr><th>LPO</th><th>Supplier</th><th>Description</th><th>Amount</th><th>Date</th><th>Status</th></tr></thead><tbody>{_simple_rows(lpos,['lpo_no','supplier','description','amount','date','status']) or '<tr><td colspan=6>No LPOs yet.</td></tr>'}</tbody></table></div>
</div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Accounting",body)

@router.post("/app/accounting/expense")
def accounting_expense(request: Request,category:str=Form(...),description:str=Form(...),amount:float=Form(...),paid_to:str=Form(""),voucher_no:str=Form(""),date:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();cur.execute("INSERT INTO expenses(school_id,category,description,amount,paid_to,voucher_no,date) VALUES(?,?,?,?,?,?,?)",(sid,category.strip(),description.strip(),amount,paid_to.strip(),voucher_no.strip(),date or datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d")))
    _audit(cur,sid,request,"EXPENSE_CREATE",f"{category}: {amount}");con.commit();con.close();return RedirectResponse("/app/accounting",303)


def _ensure_assessment_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS assessment_scores(
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, student_id INTEGER,
        subject_id INTEGER, term TEXT, year TEXT, component TEXT,
        score REAL, out_of REAL, created_at TEXT)""")

@router.get("/app/academics/allocations", response_class=HTMLResponse)
def allocations_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    teachers=cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    rows=cur.execute("""SELECT ta.*,t.name teacher_name,s.name subject_name,c.name class_name,c.stream
                        FROM teacher_allocations ta JOIN teachers t ON t.id=ta.teacher_id
                        JOIN subjects s ON s.id=ta.subject_id JOIN classes c ON c.id=ta.class_id
                        WHERE ta.school_id=? ORDER BY t.name,s.name,c.name""",(sid,)).fetchall()
    con.close()
    opts=lambda xs,label: "".join(f"<option value='{x['id']}'>{escape(str(x['name']))}{(' '+escape(str(x['stream'] or ''))) if label=='class' else ''}</option>" for x in xs)
    tr=_simple_rows(rows,["teacher_name","subject_name","class_name","stream"])
    body=f"""<div class='page'><h1>Teacher Allocation</h1><div class='muted'>Assign teachers to subjects and classes.</div>
<div class='card section'><form method='post' action='/app/academics/allocations/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<select name='teacher_id' required class='field'>{opts(teachers,'teacher')}</select><select name='subject_id' required class='field'>{opts(subjects,'subject')}</select><select name='class_id' required class='field'>{opts(classes,'class')}</select><button class='btn'>Save Allocation</button></form></div>
<div class='card section'><h2>Current allocations ({len(rows)})</h2><table><thead><tr><th>Teacher</th><th>Subject</th><th>Class</th><th>Stream</th></tr></thead><tbody>{tr or '<tr><td colspan=4>No allocations yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Teacher Allocation",body)

@router.post("/app/academics/allocations/add")
def allocations_add(request: Request,teacher_id:int=Form(...),subject_id:int=Form(...),class_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor()
    valid=all(cur.execute(q,(x,sid)).fetchone() for q,x in [
        ("SELECT id FROM teachers WHERE id=? AND school_id=?",teacher_id),
        ("SELECT id FROM subjects WHERE id=? AND school_id=?",subject_id),
        ("SELECT id FROM classes WHERE id=? AND school_id=?",class_id)])
    if valid:
        if not cur.execute("SELECT id FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND subject_id=? AND class_id=?",(sid,teacher_id,subject_id,class_id)).fetchone():
            cur.execute("INSERT INTO teacher_allocations(school_id,teacher_id,subject_id,class_id) VALUES(?,?,?,?)",(sid,teacher_id,subject_id,class_id))
            _audit(cur,sid,request,"TEACHER_ALLOCATION","Created teacher allocation")
    con.commit();con.close();return RedirectResponse("/app/academics/allocations",303)

@router.get("/app/academics/assessments", response_class=HTMLResponse)
def assessments_page(request: Request, student_id:str="", subject_id:str="", term:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();_ensure_assessment_table(cur)
    students=cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    stid=int(student_id) if student_id.isdigit() else 0; subid=int(subject_id) if subject_id.isdigit() else 0
    rows=cur.execute("""SELECT a.*,s.name subject_name FROM assessment_scores a JOIN subjects s ON s.id=a.subject_id
                        WHERE a.school_id=? AND (?=0 OR a.student_id=?) AND (?=0 OR a.subject_id=?) AND (?='' OR a.term=?)
                        ORDER BY a.id DESC LIMIT 300""",(sid,stid,stid,subid,subid,term,term)).fetchall()
    con.commit();con.close()
    so="".join(f"<option value='{s['id']}' {'selected' if s['id']==subid else ''}>{escape(str(s['name']))}</option>" for s in subjects)
    sto="".join(f"<option value='{s['id']}' {'selected' if s['id']==stid else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    tr=_simple_rows(rows,["student_id","subject_name","term","year","component","score","out_of","created_at"])
    body=f"""<div class='page'><h1>SBA / CBA</h1><div class='muted'>Record continuous assessment components separately from examination marks.</div>
<div class='card section'><form method='post' action='/app/academics/assessments/add' style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>
<select name='student_id' required class='field'>{sto}</select><select name='subject_id' required class='field'>{so}</select><select name='term' required class='field'><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name='year' required value='{datetime.now(ZoneInfo("Africa/Nairobi")).year}' class='field'><select name='component' required class='field'><option>CAT 1</option><option>CAT 2</option><option>Project</option><option>Practical</option><option>SBA</option><option>CBA</option><option>Assignment</option><option>Other</option></select><input name='score' required type='number' min='0' step='0.01' placeholder='Score' class='field'><input name='out_of' required type='number' min='1' step='0.01' value='100' placeholder='Out of' class='field'><button class='btn'>Save Assessment</button></form></div>
<div class='card section'><h2>Assessment records</h2><table><thead><tr><th>Student ID</th><th>Subject</th><th>Term</th><th>Year</th><th>Component</th><th>Score</th><th>Out Of</th><th>Created</th></tr></thead><tbody>{tr or '<tr><td colspan=8>No assessment records yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"SBA / CBA",body)

@router.post("/app/academics/assessments/add")
def assessments_add(request: Request,student_id:int=Form(...),subject_id:int=Form(...),term:str=Form(...),year:str=Form(...),component:str=Form(...),score:float=Form(...),out_of:float=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if out_of<=0 or score<0 or score>out_of:return HTMLResponse("Invalid assessment score. <a href='/app/academics/assessments'>Back</a>",400)
    con=_db();cur=con.cursor();_ensure_assessment_table(cur)
    valid=cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if valid:
        cur.execute("INSERT INTO assessment_scores(school_id,student_id,subject_id,term,year,component,score,out_of,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(sid,student_id,subject_id,term.strip(),year.strip(),component.strip(),score,out_of,datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")))
        _audit(cur,sid,request,"ASSESSMENT_SAVE",f"Saved {component.strip()} for student {student_id}")
    con.commit();con.close();return RedirectResponse("/app/academics/assessments",303)

@router.get("/app/academics/student-analysis", response_class=HTMLResponse)
def student_analysis(request: Request, student_id:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();students=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(sid,)).fetchall()
    stid=int(student_id) if student_id.isdigit() else (int(students[0]["id"]) if students else 0)
    rows=cur.execute("""SELECT sub.name subject,COUNT(m.id) entries,COALESCE(AVG(m.marks),0) avg_mark,COALESCE(MAX(m.marks),0) high,COALESCE(MIN(m.marks),0) low
                        FROM subjects sub LEFT JOIN marks m ON m.subject_id=sub.id AND m.student_id=? AND m.school_id=?
                        WHERE sub.school_id=? GROUP BY sub.id,sub.name ORDER BY sub.name""",(stid,sid,sid)).fetchall() if stid else []
    st=next((x for x in students if x["id"]==stid),None);con.close()
    vals=[float(x["avg_mark"] or 0) for x in rows if int(x["entries"] or 0)>0];overall=sum(vals)/len(vals) if vals else 0
    so="".join(f"<option value='{s['id']}' {'selected' if s['id']==stid else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    tr="".join(f"<tr><td>{escape(str(x['subject']))}</td><td>{x['entries']}</td><td>{float(x['avg_mark'] or 0):.2f}</td><td>{x['high']}</td><td>{x['low']}</td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Student Analysis</h1><div class='muted'>{escape(str(st['name'] if st else ''))} · {escape(str(st['class_name'] if st else ''))}</div>
<div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr auto;gap:10px'><select name='student_id' class='field'>{so}</select><button class='btn'>Analyse Student</button></form></div>
<div class='grid'><div class='card'><div class='label'>Overall subject average</div><div class='kpi'>{overall:.2f}%</div></div><div class='card'><div class='label'>Subjects with marks</div><div class='kpi'>{len(vals)}</div></div></div>
<div class='card section'><table><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th></tr></thead><tbody>{tr or '<tr><td colspan=5>No marks recorded.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Student Analysis",body)

@router.get("/app/academics/class-analysis", response_class=HTMLResponse)
def class_analysis(request: Request, exam_id:str="", class_id:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall();classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0);cid=int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
    rows=cur.execute("""SELECT s.id,s.name,s.admission_no,COALESCE(AVG(m.marks),0) average,COUNT(m.id) entries
                        FROM students s LEFT JOIN marks m ON m.student_id=s.id AND m.exam_id=? AND m.school_id=?
                        WHERE s.school_id=? AND s.class_id=? GROUP BY s.id,s.name,s.admission_no ORDER BY average DESC""",(eid,sid,sid,cid)).fetchall() if eid and cid else []
    con.close(); avg=(sum(float(x["average"] or 0) for x in rows)/len(rows)) if rows else 0
    eo="".join(f"<option value='{e['id']}' {'selected' if e['id']==eid else ''}>{escape(str(e['name']))}</option>" for e in exams);co="".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    tr="".join(f"<tr><td>{n}</td><td>{escape(str(x['admission_no'] or ''))}</td><td>{escape(str(x['name']))}</td><td>{x['entries']}</td><td>{float(x['average'] or 0):.2f}</td><td>{_grade(x['average'])}</td></tr>" for n,x in enumerate(rows,1))
    body=f"""<div class='page'><h1>Class Analysis</h1><div class='muted'>Student performance distribution for a selected examination and class.</div><div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_id' class='field'>{eo}</select><select name='class_id' class='field'>{co}</select><button class='btn'>Analyse Class</button></form></div><div class='grid'><div class='card'><div class='label'>Class average</div><div class='kpi'>{avg:.2f}%</div></div><div class='card'><div class='label'>Students</div><div class='kpi'>{len(rows)}</div></div></div><div class='card section'><table><thead><tr><th>Pos</th><th>Admission</th><th>Student</th><th>Entries</th><th>Average</th><th>Grade</th></tr></thead><tbody>{tr or '<tr><td colspan=6>No marks recorded.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Class Analysis",body)