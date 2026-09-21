from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from html import escape
import base64
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
    if not sid: return RedirectResponse("/")
    con = _db(); cur = con.cursor()
    terms = cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    stat = cur.execute("SELECT COUNT(*) entries,COALESCE(AVG(marks),0) avg_mark FROM marks WHERE school_id=?",(sid,)).fetchone()
    eid = int(exam_id) if exam_id.isdigit() else 0
    cid = int(class_id) if class_id.isdigit() else 0
    subid = int(subject_id) if subject_id.isdigit() else 0
    params=[sid]; query="SELECT COUNT(*) entries,COALESCE(AVG(marks),0) avg_mark,COALESCE(MAX(marks),0) high,COALESCE(MIN(marks),0) low FROM marks WHERE school_id=?"
    if eid: query+=" AND exam_id=?"; params.append(eid)
    if cid: query+=" AND class_id=?"; params.append(cid)
    if subid: query+=" AND subject_id=?"; params.append(subid)
    if term: query+=" AND term=?"; params.append(term.strip())
    if year: query+=" AND year=?"; params.append(year.strip())
    selected=cur.execute(query,params).fetchone(); con.close()
    eopts="".join("<option value='%s' %s>%s</option>"%(e["id"],"selected" if int(e["id"])==eid else "",escape(str(e["name"]))) for e in exams)
    copts="".join("<option value='%s' %s>%s %s</option>"%(c["id"],"selected" if int(c["id"])==cid else "",escape(str(c["name"])),escape(str(c["stream"] or ""))) for c in classes)
    sopts="".join("<option value='%s' %s>%s</option>"%(s["id"],"selected" if int(s["id"])==subid else "",escape(str(s["name"]))) for s in subjects)
    topts="".join("<option %s>%s</option>"%("selected" if x==term else "",x) for x in TERM_OPTIONS)
    yopts="".join("<option value='%s' %s>%s</option>"%(y,"selected" if y==year else "",y) for y in YEAR_OPTIONS)
    actions=[("/app/academics/marks","📝","Marks Entry","Enter and update learner marks"),("/app/academics/marksheets","📋","Class Marksheets","View class marks"),("/app/academics/analysis","📊","Subject Analysis","Analyse subjects"),("/app/academics/student-analysis","👤","Student Analysis","Analyse a learner"),("/app/academics/class-analysis","🏫","Class Analysis","Analyse a class"),("/app/academics/assessments","🧪","SBA / CBA","Continuous assessment"),("/app/academics/grading","🎯","Grade & Points","Set subject grading rules"),("/app/academics/allocations","👩‍🏫","Teacher Allocation","Assign teachers"),("/app/report-cards","📄","Report Cards","Generate reports"),("/app/exams","⚙","Examinations","Manage examinations"),("/app/subjects","📚","Subjects","Manage subjects"),("/app/classes","🏷","Classes & Streams","Manage classes")]
    action_html="".join("<a class='action' href='%s'><span>%s</span>%s<small>%s</small></a>"%x for x in actions)
    body="<div class='page'><h1>Academic Management</h1><div class='muted'>Select options below to work with marks, assessments, analysis and reports.</div><div class='grid'><div class='card'><div class='label'>Subjects</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Exams</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Classes</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Marks Average</div><div class='kpi'>%.1f%%</div></div></div>"%(len(subjects),len(exams),len(classes),float(stat["avg_mark"] or 0))
    body+="<div class='card section'><h2>Academic Selection</h2><form method='get' action='/app/academics' class='academic-select'><select name='year' class='field' onchange='this.form.submit()'><option value=''>All Years</option>"+yopts+"</select><select name='term' class='field' onchange='this.form.submit()'><option value=''>All Terms</option>"+topts+"</select><select name='exam_id' class='field' onchange='this.form.submit()'><option value=''>All Exams</option>"+eopts+"</select><select name='class_id' class='field' onchange='this.form.submit()'><option value=''>All Classes</option>"+copts+"</select><select name='subject_id' class='field' onchange='this.form.submit()'><option value=''>All Subjects</option>"+sopts+"</select></form></div><div class='section'><div class='actions'>"+action_html+"</div></div>"
    body+="<div class='card section'><h2>Selected Academic Results</h2><div class='grid' style='margin:0'><div class='card'><div class='label'>Entries</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Average</div><div class='kpi'>%.1f%%</div></div><div class='card'><div class='label'>Highest</div><div class='kpi'>%.1f</div></div><div class='card'><div class='label'>Lowest</div><div class='kpi'>%.1f</div></div></div></div></div><style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff;cursor:pointer}.academic-select{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.action small{display:block;color:#64748b;margin-top:5px}@media(max-width:900px){.academic-select{grid-template-columns:1fr 1fr}}</style>"%(int(selected["entries"] or 0),float(selected["avg_mark"] or 0),float(selected["high"] or 0),float(selected["low"] or 0))
    return _school_page(request,"Academic Management",body)


def _ensure_overall_grading_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS overall_grading_rules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        min_total REAL,
        max_total REAL,
        grade TEXT
    )""")

def _overall_grade(cur, school_id, total):
    _ensure_overall_grading_table(cur)
    rule=cur.execute("""SELECT grade FROM overall_grading_rules
        WHERE school_id=? AND ? BETWEEN min_total AND max_total
        ORDER BY min_total DESC,id DESC LIMIT 1""",(school_id,total)).fetchone()
    return str(rule["grade"]) if rule else _default_grade_points(total)[0]

@router.get("/app/academics/overall-grading", response_class=HTMLResponse)
def overall_grading(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();_ensure_overall_grading_table(cur)
    rules=cur.execute("SELECT * FROM overall_grading_rules WHERE school_id=? ORDER BY min_total DESC,max_total DESC",(sid,)).fetchall()
    con.close()
    rows="".join("<tr><td>%.1f</td><td>%.1f</td><td><b>%s</b></td><td><a class='btnlink' href='/app/academics/overall-grading/delete/%s'>Delete</a></td></tr>"%(float(r["min_total"]),float(r["max_total"]),escape(str(r["grade"])),r["id"]) for r in rules)
    body=("<div class='page'><h1>Overall Grade & Position Settings</h1>"
      "<div class='muted'>Set the total-mark bands your school uses for the final overall grade. Position is then calculated automatically from total marks within the selected class and stream.</div>"
      "<div class='card section'><h2>Add overall grade band</h2><form method='post' action='/app/academics/overall-grading/add' style='display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px'>"
      "<input name='min_total' type='number' min='0' step='0.01' required placeholder='Minimum total marks' class='field'>"
      "<input name='max_total' type='number' min='0' step='0.01' required placeholder='Maximum total marks' class='field'>"
      "<input name='grade' required placeholder='Overall grade e.g. A' class='field'><button class='btn'>Save</button></form></div>"
      "<div class='card section'><table><thead><tr><th>Minimum Total</th><th>Maximum Total</th><th>Overall Grade</th><th>Action</th></tr></thead><tbody>"+(rows or "<tr><td colspan='4'>No overall grading bands configured.</td></tr>")+"</tbody></table></div>"
      "<div class='card section'><b>Position:</b> DaviSchool ranks learners automatically by total marks, highest total first. Equal totals receive the same position.</div>"
      "<style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}.btn,.btnlink{padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}.btnlink{background:#fff;color:#172033}</style></div>")
    return _school_page(request,"Overall Grade & Position Settings",body)

@router.post("/app/academics/overall-grading/add")
def overall_grading_add(request: Request,min_total:float=Form(...),max_total:float=Form(...),grade:str=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if min_total<0 or max_total<min_total:
        return HTMLResponse("Invalid total-mark range. <a href='/app/academics/overall-grading'>Back</a>",400)
    con=_db();cur=con.cursor();_ensure_overall_grading_table(cur)
    cur.execute("INSERT INTO overall_grading_rules(school_id,min_total,max_total,grade) VALUES(?,?,?,?)",(sid,min_total,max_total,grade.strip()))
    _audit(cur,sid,request,"OVERALL_GRADING_RULE_CREATE","Configured overall grade %s for %.1f-%.1f total marks"%(grade.strip(),min_total,max_total))
    con.commit();con.close()
    return RedirectResponse("/app/academics/overall-grading",303)

@router.get("/app/academics/overall-grading/delete/{rule_id}")
def overall_grading_delete(request: Request,rule_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();_ensure_overall_grading_table(cur)
    cur.execute("DELETE FROM overall_grading_rules WHERE id=? AND school_id=?",(rule_id,sid))
    con.commit();con.close()
    return RedirectResponse("/app/academics/overall-grading",303)

@router.get("/app/academics/marksheets", response_class=HTMLResponse)
def class_marksheets(request: Request, exam_id: str = "", class_id: str = "", term: str = "", year: str = "", stream: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/")
    con = _db()
    cur = con.cursor()
    _ensure_grading_table(cur)
    exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (sid,)).fetchall()
    classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
    subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    eid = int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    cid = int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
    class_row = cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?", (cid, sid)).fetchone() if cid else None
    er = cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?", (eid, sid)).fetchone() if eid else None
    if er:
        if not term:
            term = str(er["term"] or "")
        if not year:
            year = str(er["year"] or "")
    student_query = "SELECT * FROM students WHERE school_id=? AND class_id=?"
    student_params = [sid, cid]
    if stream:
        student_query += " AND stream=?"
        student_params.append(stream)
    student_query += " ORDER BY name"
    students = cur.execute(student_query, student_params).fetchall() if cid else []
    mark_query = "SELECT student_id,subject_id,marks FROM marks WHERE school_id=? AND exam_id=? AND class_id=?"
    mark_params = [sid, eid, cid]
    if term:
        mark_query += " AND term=?"
        mark_params.append(term)
    if year:
        mark_query += " AND year=?"
        mark_params.append(year)
    mark_rows = cur.execute(mark_query, mark_params).fetchall() if eid and cid else []
    marks = {(int(r["student_id"]), int(r["subject_id"])): r["marks"] for r in mark_rows}
    streams = sorted(set(str(c["stream"] or "") for c in classes if str(c["stream"] or "")))

    eopts = "".join("<option value='%s' %s>%s</option>" % (
        e["id"], "selected" if int(e["id"]) == eid else "", escape(str(e["name"]))
    ) for e in exams)
    copts = "".join("<option value='%s' %s>%s %s</option>" % (
        c["id"], "selected" if int(c["id"]) == cid else "",
        escape(str(c["name"])), escape(str(c["stream"] or ""))
    ) for c in classes)
    stropts = "".join("<option value='%s' %s>%s</option>" % (
        escape(x), "selected" if x == stream else "", escape(x)
    ) for x in streams)
    topts = "".join("<option %s>%s</option>" % (
        "selected" if x == term else "", x
    ) for x in TERM_OPTIONS)
    yopts = "".join("<option value='%s' %s>%s</option>" % (
        y, "selected" if y == year else "", y
    ) for y in YEAR_OPTIONS)

    header_cells = ""
    sub_header_cells = ""
    for subject in subjects:
        header_cells += "<th colspan='3' class='subjecthead'>%s</th>" % escape(str(subject["name"]))
        sub_header_cells += "<th>MKS</th><th>GRD</th><th>PTS</th>"

    computed=[]
    for student in students:
        total=0.0
        total_points=0.0
        count=0
        cells=""
        for subject in subjects:
            value=marks.get((int(student["id"]),int(subject["id"])))
            if value is None:
                cells+="<td>—</td><td>—</td><td>—</td>"
            else:
                grade,points=_subject_grade_points(cur,sid,int(subject["id"]),value)
                total+=float(value or 0)
                total_points+=float(points or 0)
                count+=1
                cells+="<td>%.1f</td><td><b>%s</b></td><td>%.1f</td>"%(float(value),escape(str(grade)),float(points))
        computed.append((student,total,total_points,count,cells))
    computed.sort(key=lambda x:x[1],reverse=True)
    rows=""
    last_total=None
    last_position=0
    for index,item in enumerate(computed,1):
        student,total,total_points,count,cells=item
        if last_total is None or total != last_total:
            last_position=index
            last_total=total
        overall_grade=_overall_grade(cur,sid,total) if count else "—"
        average=(total/count) if count else 0
        rows+=("<tr><td>%d</td><td>%s</td><td><b>%s</b></td>%s"
          "<td><b>%.1f</b></td><td><b>%.1f</b></td><td><b>%.1f%%</b></td><td><b>%s</b></td><td><b>%d</b></td></tr>"
          %(index,escape(str(student["admission_no"] or "")),escape(str(student["name"] or "")),cells,total,total_points,average,escape(str(overall_grade)),last_position))

    school_row = cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    school_name = escape(str(school_row["name"])) if school_row else "DaviSchool"
    school_email = escape(str(school_row["email"] or "")) if school_row else ""
    school_phone = escape(str(school_row["phone"] or "")) if school_row else ""
    school_postal = escape("P.O. Box %s" % str(school_row["postal_address"] or "")) if school_row and "postal_address" in school_row.keys() and school_row["postal_address"] else ""
    school_postal_code = escape(str(school_row["postal_code"] or "")) if school_row and "postal_code" in school_row.keys() else ""
    school_logo = str(school_row["logo_data"] or "") if school_row and "logo_data" in school_row.keys() else ""
    doc_brand = "<div class='doc-header'><div class='doc-logo'>%s</div><div><div class='doc-school'>%s</div><div class='doc-contact'>%s%s%s%s</div></div></div>" % (("<img src='%s' alt='School logo'>" % escape(school_logo)) if school_logo else "🏫",school_name,school_email,(" · "+school_phone) if school_phone else "",(" · "+school_postal) if school_postal else "",(" · "+school_postal_code) if school_postal_code else "")
    class_title = escape(str(class_row["name"])) if class_row else "Select a class"
    exam_name = escape(str(er["name"])) if er else "Select an examination"
    colspan = 3 + len(subjects) * 3 + 5

    print_script = '''<script>function printDocument(){var doc=document.querySelector('.marksheet-card');if(!doc){window.print();return;}var w=window.open('', '_blank', 'width=1200,height=800');if(!w){window.print();return;}var css='*{box-sizing:border-box}body{margin:0;background:#fff;color:#111;font-family:Arial,sans-serif}.marksheet-card{display:block!important;width:100%!important;margin:0!important;padding:0!important;border:0!important;box-shadow:none!important}.no-print{display:none!important}.doc-header{display:flex;align-items:center;gap:14px;border-bottom:2px solid #111827;padding-bottom:10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school{font-size:18px;font-weight:900;text-transform:uppercase}.doc-contact{font-size:10px;color:#475569;margin-top:3px}.marksheet-school{text-align:center;font-size:20px;font-weight:900;text-transform:uppercase;padding:6px}.marksheet-meta{font-size:14px;font-weight:800;padding:8px 4px;border-top:1px solid #111;border-bottom:1px solid #111}.marksheet{border-collapse:collapse;width:100%;font-family:Arial,sans-serif}.marksheet th,.marksheet td{border:1px solid #111;padding:4px 5px;text-align:center;font-size:10px;white-space:nowrap}.marksheet th{background:#fff;color:#111}.marksheet .subjecthead{font-size:11px;color:#d00;text-transform:uppercase}.marksheet th:nth-child(2),.marksheet td:nth-child(2){text-align:left;min-width:190px}.marksheet td b{font-weight:800}@page{size:auto;margin:10mm}';w.document.open();w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>Class Marksheet</title><style>'+css+'</style></head><body>'+doc.outerHTML+'</body></html>');w.document.close();w.focus();setTimeout(function(){w.print();},300);}</script>'''
    body = (
        "<div class='page'><h1>Class Marksheets</h1>"
        "<div class='muted'>A print-ready marksheet with automatic subject grades and points.</div>"
        "<div class='card section no-print'><form method='get' action='/app/academics/marksheets' class='marksheet-select'>"
        "<select name='class_id' class='field' onchange='this.form.submit()'><option value=''>Select Class</option>" + copts + "</select>"
        "<select name='stream' class='field' onchange='this.form.submit()'><option value=''>All Streams</option>" + stropts + "</select>"
        "<select name='term' class='field' onchange='this.form.submit()'><option value=''>All Terms</option>" + topts + "</select>"
        "<select name='year' class='field' onchange='this.form.submit()'><option value=''>All Years</option>" + yopts + "</select>"
        "<select name='exam_id' class='field' onchange='this.form.submit()'><option value=''>Select Exam</option>" + eopts + "</select>"
        "<button type='button' class='btn' onclick='printDocument()' >Print Marksheet</button>"
        "</form><div style='margin-top:10px'><a class='btnlink' href='/app/academics/marks'>Enter / Edit Marks</a> "
        "<a class='btnlink' href='/app/academics/grading'>Set Subject Grade & Points</a> <a class='btnlink' href='/app/academics/overall-grading'>Set Overall Grade</a></div></div>"
        "<div class='card section marksheet-card'>{doc_brand}"
        "<div class='marksheet-school'>%s</div><div class='marksheet-meta'>CLASS: %s &nbsp;&nbsp; EXAM: %s &nbsp;&nbsp; TERM: %s &nbsp;&nbsp; YEAR: %s</div>"
        "<div style='overflow:auto'><table class='marksheet'><thead><tr><th rowspan='2'>NO.</th><th rowspan='2'>NAME</th>%s<th colspan='5'>OVERALL</th></tr>"
        "<tr>%s<th>MKS</th><th>PTS</th><th>AVG %%</th><th>GRD</th><th>POS</th></tr></thead><tbody>%s</tbody></table></div></div></div>"
        + print_script +
        "<style>"
        ".field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}"
        ".marksheet-select{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}.btn,.btnlink{padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}.btnlink{background:#fff;color:#172033;margin-right:6px}"
        ".marksheet-card{background:#fff}.doc-header{display:flex;align-items:center;gap:14px;border-bottom:2px solid #111827;padding-bottom:10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school{font-size:18px;font-weight:900;text-transform:uppercase}.doc-contact{font-size:10px;color:#475569;margin-top:3px}.marksheet-title{text-align:center;font-size:24px;font-weight:900;color:#111827;padding:4px}.marksheet-school{text-align:center;font-size:22px;font-weight:900;text-transform:uppercase;padding:6px}.marksheet-meta{font-size:14px;font-weight:800;padding:8px 4px;border-top:1px solid #111;border-bottom:1px solid #111}.marksheet{border-collapse:collapse;width:max-content;min-width:100%%;font-family:Arial,sans-serif}.marksheet th,.marksheet td{border:1px solid #111;padding:6px 8px;text-align:center;font-size:12px;white-space:nowrap}.marksheet th{background:#fff;color:#111;text-transform:none}.marksheet .subjecthead{font-size:13px;color:#d00;text-transform:uppercase}.marksheet th:nth-child(2),.marksheet td:nth-child(2){text-align:left;min-width:190px}.marksheet td b{font-weight:800}"
        "@media(max-width:900px){.marksheet-select{grid-template-columns:1fr 1fr}}"
        "@media print{body{background:#fff}.side,.top,.no-print,.page>h1,.page>.muted{display:none!important}.main{margin-left:0!important;padding:0!important}.page{padding:0!important;margin:0!important;max-width:none!important}.marksheet-card{display:block!important;border:0!important;box-shadow:none!important;margin:0!important;padding:0!important;width:100%!important}.marksheet-card .doc-header{margin-top:0}.marksheet-title{font-size:20px}.marksheet-school{font-size:20px}.marksheet th,.marksheet td{padding:4px 5px;font-size:10px}}"
        "</style></div>"
    ) % (
        doc_brand, school_name, class_title, exam_name, escape(term or "All"), escape(year or "All"),
        header_cells, sub_header_cells, rows or "<tr><td colspan='%s'>No students or marks found.</td></tr>" % colspan
    )
    con.close()
    return _school_page(request, "Class Marksheets", body)


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


@router.get("/app/school-settings", response_class=HTMLResponse)
def school_settings_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    school=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
    con.close()
    if not school:return RedirectResponse("/app")
    def val(key):
        return escape(str(school[key] or ""))
    logo=str(school["logo_data"] or "") if "logo_data" in school.keys() else ""
    logo_preview=f"<img src='{escape(logo)}' alt='School logo' style='max-width:140px;max-height:100px;object-fit:contain;border:1px solid #dbe2ea;border-radius:10px;padding:6px;background:white'>" if logo else "<div style='width:140px;height:100px;border:1px dashed #cbd5e1;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:12px'>No logo uploaded</div>"
    body=f"""<div class='page'><h1>School Settings</h1><div class='muted'>Manage the registered profile, contact details and document identity for this school.</div>
<div class='card section'><h2>School Profile</h2><form method='post' action='/app/school-settings' enctype='multipart/form-data' style='display:grid;grid-template-columns:repeat(2,1fr);gap:12px'>
<label>School Name<input name='school_name' required value='{val("name")}' class='field'></label>
<label>School Email<input name='school_email' type='email' required value='{val("email")}' class='field'></label>
<label>Location<input name='location' required value='{val("location")}' class='field'></label>
<label>Phone<input name='phone' required value='{val("phone")}' class='field'></label>
<label>Postal Address<input name='postal_address' placeholder='P.O. Box 123' value='{val("postal_address")}' class='field'></label>
<label>Postal Code<input name='postal_code' placeholder='00100' value='{val("postal_code")}' class='field'></label>
<label>Principal / Administrator<input name='principal' required value='{val("principal")}' class='field'></label>
<label>School Type<select name='school_type' class='field'><option {'selected' if school["school_type"]=="Primary" else ''}>Primary</option><option {'selected' if school["school_type"]=="Secondary" else ''}>Secondary</option><option {'selected' if school["school_type"]=="Primary & Junior Secondary" else ''}>Primary & Junior Secondary</option></select></label>
<div style='grid-column:1/-1'><div style='font-size:12px;font-weight:800;color:#475569;margin-bottom:7px'>School Logo</div>{logo_preview}<input name='school_logo' type='file' accept='image/png,image/jpeg,image/webp,image/gif' class='field' style='margin-top:8px'><div class='muted' style='margin-top:5px'>Upload PNG, JPG, WEBP or GIF. The logo will appear on school printouts, including report cards and marksheets.</div></div>
<div style='grid-column:1/-1'><button class='btn'>Save School Settings</button></div></form></div></div>
<style>label{{display:block;font-size:12px;font-weight:800;color:#475569}}.field{{width:100%;margin-top:6px;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:white}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}</style>"""
    return _school_page(request,"School Settings",body)

@router.post("/app/school-settings")
async def school_settings_save(request: Request, school_name:str=Form(...), school_email:str=Form(...), location:str=Form(...), phone:str=Form(...), principal:str=Form(...), school_type:str=Form(...), postal_address:str=Form(""), postal_code:str=Form(""), school_logo:UploadFile|None=File(None)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    allowed={"Primary","Secondary","Primary & Junior Secondary"}
    if school_type not in allowed:return HTMLResponse("Invalid school type. <a href='/app/school-settings'>Back</a>",400)
    logo_data=None
    if school_logo and school_logo.filename:
        raw=await school_logo.read()
        if len(raw)>2*1024*1024:return HTMLResponse("School logo is too large. Maximum size is 2 MB. <a href='/app/school-settings'>Back</a>",400)
        content_type=(school_logo.content_type or "").lower()
        allowed_types={"image/png","image/jpeg","image/webp","image/gif"}
        if content_type not in allowed_types:return HTMLResponse("Invalid logo format. Use PNG, JPG, WEBP or GIF. <a href='/app/school-settings'>Back</a>",400)
        logo_data=f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
    con=_db();cur=con.cursor()
    if logo_data:
        cur.execute("UPDATE schools SET name=?,email=?,location=?,phone=?,principal=?,school_type=?,postal_address=?,postal_code=?,logo_data=? WHERE id=?",(school_name.strip(),school_email.strip(),location.strip(),phone.strip(),principal.strip(),school_type,postal_address.strip(),postal_code.strip(),logo_data,sid))
    else:
        cur.execute("UPDATE schools SET name=?,email=?,location=?,phone=?,principal=?,school_type=?,postal_address=?,postal_code=? WHERE id=?",(school_name.strip(),school_email.strip(),location.strip(),phone.strip(),principal.strip(),school_type,postal_address.strip(),postal_code.strip(),sid))
    _audit(cur,sid,request,"SCHOOL_PROFILE_UPDATE",f"Updated school profile and document identity for {school_name.strip()}")
    con.commit();con.close()
    return RedirectResponse("/app/school-settings?saved=1",303)

@router.get("/app/portals", response_class=HTMLResponse)
def portals_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    body="""<div class='page'><h1>School Portals</h1><div class='muted'>Portal access and school-facing services.</div>
<div class='actions section'>
<div class='action'><span>👨‍🎓</span>Student Portal<small style='display:block;color:#64748b;margin-top:5px'>Student-facing access can be connected to this school workspace.</small></div>
<div class='action'><span>👨‍👩‍👧</span>Parent Portal<small style='display:block;color:#64748b;margin-top:5px'>Parent-facing access can be connected to this school workspace.</small></div>
<div class='action'><span>👩‍🏫</span>Teacher Portal<small style='display:block;color:#64748b;margin-top:5px'>Teacher-facing access can be connected to this school workspace.</small></div>
</div>
<div class='card section'><h2>Portal Access</h2><div class='muted'>Use User Management to create and assign school accounts, then use the appropriate role to control portal access.</div><div style='margin-top:12px'><a class='action' href='/app/users'>👤 Open User Management</a> <a class='action' href='/app/roles'>🔐 Open Roles & Permissions</a></div></div></div>"""
    return _school_page(request,"School Portals",body)

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
        platform_users=cur.execute("SELECT full_name,email,role FROM users ORDER BY id").fetchall()
        students=cur.execute("SELECT COUNT(*) c FROM students").fetchone()["c"]
        revenue=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM fee_payments").fetchone()["v"]
        recent=cur.execute("SELECT name,location FROM schools ORDER BY id DESC LIMIT 8").fetchall()
        con.close()
        rows="".join(f"<tr><td>{escape(r['name'])}</td><td>{escape(r['location'] or '')}</td><td>Active</td></tr>" for r in recent)
        body=f"""<div class='page'><h1>Platform Overview</h1><div class='muted'>One control centre for every DaviSchool institution.</div>
<div class='grid'><div class='card'><div class='label'>Schools</div><div class='kpi'>{schools}</div></div><div class='card'><div class='label'>Users</div><div class='kpi'>{users}</div></div><div class='card'><div class='label'>Students</div><div class='kpi'>{students}</div></div><div class='card'><div class='label'>Fees received</div><div class='kpi'>KES {revenue:,.0f}</div></div></div>
<div class='section'><h2>🩺 Platform Health</h2>
<div class='card' style='margin-bottom:12px;background:#f0fdf4;border-color:#bbf7d0'>
  <div style='font-size:16px;font-weight:900;color:#166534'>🟢 Platform operating normally</div>
  <div class='muted' style='margin-top:6px'>DaviSchool is connected to its production data store and the platform overview is responding normally. School, user and student records are available to the platform.</div>
</div>
<div class='actions'>
  <div class='action'><span>🗄️</span>Database Health<small style='display:block;color:#64748b;margin-top:5px'>🟢 Connected</small></div>
  <div class='action'><span>🏫</span>School Services<small style='display:block;color:#64748b;margin-top:5px'>🟢 {schools} schools registered</small></div>
  <div class='action'><span>👥</span>User Access<small style='display:block;color:#64748b;margin-top:5px'>🟢 {users} users registered</small>
    <div style='margin-top:10px;text-align:left;border-top:1px solid #e2e8f0;padding-top:8px'>
      {''.join(f"<div style='padding:6px 0;border-bottom:1px solid #f1f5f9'><b>👤 {escape(str(u['full_name'] or 'User'))}</b><br><span style='font-size:12px;color:#64748b'>📧 {escape(str(u['email'] or ''))} · 🔐 {escape(str(u['role'] or ''))}</span></div>" for u in platform_users)}
    </div>
  </div>
  <div class='action'><span>🎓</span>Student Records<small style='display:block;color:#64748b;margin-top:5px'>🟢 {students} students recorded</small></div>
</div>
</div>
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
<div class='section'><h2>Administration</h2><div class='actions'><a class='action' href='/app/school-settings'><span>⚙</span>School Settings</a><a class='action' href='/app/roles'><span>🔐</span>Roles</a><a class='action' href='/app/audit'><span>🛡</span>Audit Trail</a><a class='action' href='/app/portals'><span>🌐</span>Portals</a></div></div></div>"""
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


def _ensure_grading_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS subject_grading_rules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        subject_id INTEGER,
        min_mark REAL,
        max_mark REAL,
        grade TEXT,
        points REAL
    )""")

def _default_grade_points(mark):
    grade = _grade(mark)
    points = {
        "A": 12, "A-": 11, "B+": 10, "B": 9, "B-": 8,
        "C+": 7, "C": 6, "C-": 5, "D+": 4, "D": 3, "E": 1
    }.get(grade, 0)
    return grade, points

def _subject_grade_points(cur, school_id, subject_id, mark):
    _ensure_grading_table(cur)
    try:
        value = float(mark)
    except Exception:
        return "—", 0
    rule = cur.execute(
        """SELECT grade,points FROM subject_grading_rules
           WHERE school_id=? AND subject_id=? AND ? BETWEEN min_mark AND max_mark
           ORDER BY min_mark DESC, id DESC LIMIT 1""",
        (school_id, subject_id, value)
    ).fetchone()
    if rule:
        return str(rule["grade"]), float(rule["points"] or 0)
    return _default_grade_points(value)

@router.get("/app/academics/grading", response_class=HTMLResponse)
def grading_setup(request: Request, subject_id: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/")
    con = _db()
    cur = con.cursor()
    _ensure_grading_table(cur)
    subjects = cur.execute(
        "SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)
    ).fetchall()
    subid = int(subject_id) if subject_id.isdigit() else 0
    if subid and not cur.execute(
        "SELECT id FROM subjects WHERE id=? AND school_id=?", (subid, sid)
    ).fetchone():
        subid = 0
    rules = cur.execute(
        """SELECT * FROM subject_grading_rules
           WHERE school_id=? AND subject_id=?
           ORDER BY min_mark DESC, max_mark DESC""",
        (sid, subid)
    ).fetchall() if subid else []
    con.commit()
    con.close()

    sopts = "".join(
        "<option value='%s' %s>%s</option>" % (
            s["id"],
            "selected" if int(s["id"]) == subid else "",
            escape(str(s["name"]))
        ) for s in subjects
    )
    rule_rows = "".join(
        "<tr><td>%.1f</td><td>%.1f</td><td><b>%s</b></td><td>%.1f</td>"
        "<td><a class='btnlink' href='/app/academics/grading/delete/%s?subject_id=%s'>Delete</a></td></tr>"
        % (float(r["min_mark"]), float(r["max_mark"]), escape(str(r["grade"])),
           float(r["points"] or 0), r["id"], subid)
        for r in rules
    )
    body = (
        "<div class='page'><h1>Subject Grading & Points</h1>"
        "<div class='muted'>Set the grade band and points for each subject. "
        "These rules are applied automatically when marks are entered and when class marksheets are generated.</div>"
        "<div class='card section'><form method='get' action='/app/academics/grading' "
        "style='display:grid;grid-template-columns:1fr auto;gap:10px'>"
        "<select name='subject_id' class='field' required><option value=''>Select subject</option>"
        + sopts +
        "</select><button class='btn'>Load Subject</button></form></div>"
        "<div class='card section'><h2>Add grading rule</h2>"
        "<form method='post' action='/app/academics/grading/add' "
        "style='display:grid;grid-template-columns:repeat(5,1fr);gap:10px'>"
        "<input type='hidden' name='subject_id' value='%s'>"
        "<input name='min_mark' required type='number' min='0' max='100' step='0.01' placeholder='Minimum mark' class='field'>"
        "<input name='max_mark' required type='number' min='0' max='100' step='0.01' placeholder='Maximum mark' class='field'>"
        "<input name='grade' required placeholder='Grade e.g. A' class='field'>"
        "<input name='points' required type='number' min='0' step='0.01' placeholder='Points' class='field'>"
        "<button class='btn'>Save Grade & Points</button></form></div>"
        "<div class='card section'><h2>Configured rules</h2>"
        "<table><thead><tr><th>Minimum</th><th>Maximum</th><th>Grade</th><th>Points</th><th>Action</th></tr></thead>"
        "<tbody>%s</tbody></table></div>"
        "<div class='card section'><b>Default fallback:</b> if a subject has no custom rule for a mark, DaviSchool uses the standard A–E scale and default points until you configure that subject.</div>"
        "</div><style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}.btn,.btnlink{padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}.btnlink{background:#fff;color:#172033}</style>"
    ) % (subid, rule_rows or "<tr><td colspan='5'>No custom grading rules configured for this subject.</td></tr>")
    return _school_page(request, "Subject Grading & Points", body)

@router.post("/app/academics/grading/add")
def grading_add(request: Request, subject_id: int = Form(...), min_mark: float = Form(...),
                max_mark: float = Form(...), grade: str = Form(...), points: float = Form(...)):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if min_mark < 0 or max_mark > 100 or min_mark > max_mark or points < 0:
        return HTMLResponse("Invalid grading range. <a href='/app/academics/grading'>Back</a>", 400)
    con = _db()
    cur = con.cursor()
    _ensure_grading_table(cur)
    if not cur.execute(
        "SELECT id FROM subjects WHERE id=? AND school_id=?", (subject_id, sid)
    ).fetchone():
        con.close()
        return HTMLResponse("Invalid subject. <a href='/app/academics/grading'>Back</a>", 400)
    cur.execute(
        """INSERT INTO subject_grading_rules
           (school_id,subject_id,min_mark,max_mark,grade,points)
           VALUES(?,?,?,?,?,?)""",
        (sid, subject_id, min_mark, max_mark, grade.strip(), points)
    )
    _audit(cur, sid, request, "GRADING_RULE_CREATE",
           "Configured %s: %.1f-%.1f = %s / %.1f points" %
           (grade.strip(), min_mark, max_mark, grade.strip(), points))
    con.commit()
    con.close()
    return RedirectResponse("/app/academics/grading?subject_id=%s" % subject_id, 303)

@router.get("/app/academics/grading/delete/{rule_id}")
def grading_delete(request: Request, rule_id: int, subject_id: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    con = _db()
    cur = con.cursor()
    _ensure_grading_table(cur)
    row = cur.execute(
        "SELECT * FROM subject_grading_rules WHERE id=? AND school_id=?",
        (rule_id, sid)
    ).fetchone()
    if row:
        cur.execute("DELETE FROM subject_grading_rules WHERE id=?", (rule_id,))
        _audit(cur, sid, request, "GRADING_RULE_DELETE",
               "Deleted grading rule %s" % rule_id)
    con.commit()
    con.close()
    return RedirectResponse("/app/academics/grading?subject_id=%s" % subject_id, 303)

@router.get("/app/academics/marks", response_class=HTMLResponse)
def marks_page(request: Request, exam_id: str="", class_id: str="", subject_id: str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor();_ensure_grading_table(cur)
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
    grading_rules=cur.execute("""SELECT * FROM subject_grading_rules
      WHERE school_id=? AND subject_id=? ORDER BY min_mark DESC,max_mark DESC""",(sid,subid)).fetchall() if subid else []
    js_rules="["+",".join("[%s,%s,%r,%s]"%(float(r["min_mark"]),float(r["max_mark"]),str(r["grade"]),float(r["points"] or 0)) for r in grading_rules)+"]"
    eopts="".join("<option value='%s' %s>%s (%s)</option>"%(e["id"],"selected" if int(e["id"])==eid else "",escape(str(e["name"])),escape(str(e["year"] or ""))) for e in exams)
    copts="".join("<option value='%s' %s>%s %s</option>"%(c["id"],"selected" if int(c["id"])==cid else "",escape(str(c["name"])),escape(str(c["stream"] or ""))) for c in classes)
    sopts="".join("<option value='%s' %s>%s</option>"%(s["id"],"selected" if int(s["id"])==subid else "",escape(str(s["name"]))) for s in subjects)
    rule_note="Custom grading: %s rule(s)"%len(grading_rules) if grading_rules else "Using default A-E grading until you configure this subject."
    rows=""
    for x in students:
        mark=x["marks"]
        if mark=="":
            grade,points="—","—"
        else:
            grade,points=_subject_grade_points(cur,sid,subid,mark)
        rows+="<tr><td>%s</td><td><b>%s</b></td><td><input name='mark_%s' value='%s' type='number' min='0' max='100' step='0.01' class='markinput'></td><td class='gradecell'>%s</td><td class='pointcell'>%s</td></tr>"%(escape(str(x["admission_no"] or "")),escape(str(x["name"] or "")),x["id"],escape(str(mark)),escape(str(grade)),points if points=="—" else "%.1f"%float(points))
    con.close()
    body=(
      "<div class='page'><h1>Marks Entry</h1><div class='muted'>Enter marks and DaviSchool will apply the subject's configured grade and point rules automatically.</div>"
      "<div class='card section'><form method='get' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>"
      "<select name='exam_id' class='field'><option value=''>Select examination</option>"+eopts+"</select>"
      "<select name='class_id' class='field'><option value=''>Select class</option>"+copts+"</select>"
      "<select name='subject_id' class='field'><option value=''>Select subject</option>"+sopts+"</select>"
      "<button class='btn'>Load Students</button></form>"
      "<div style='margin-top:10px;padding:10px;background:#f8fafc;border-radius:9px'>"+escape(rule_note)+" "
      "<a href='/app/academics/grading?subject_id=%s' style='margin-left:10px;font-weight:800'>Set / Edit Grade & Points</a></div></div>"%subid+
      "<div class='card section'><form method='post' action='/app/academics/marks/save'>"
      "<input type='hidden' name='exam_id' value='%s'><input type='hidden' name='class_id' value='%s'><input type='hidden' name='subject_id' value='%s'>"
      "<table><thead><tr><th>Admission</th><th>Student</th><th>Mark / 100</th><th>Grade</th><th>Points</th></tr></thead><tbody>%s</tbody></table>%s"
      "</form></div></div>"%(eid,cid,subid,rows or "<tr><td colspan='5'>Select an examination, class and subject, then load students.</td></tr>","<button class='btn' style='margin-top:12px'>Save Marks</button>" if students else "")+
      "<style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}.markinput{width:100px;padding:8px;border:1px solid #dbe2ea;border-radius:8px}.btn{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}</style>"
      "<script>var gradingRules=%s;document.querySelectorAll('.markinput').forEach(function(el){el.addEventListener('input',function(){var row=el.closest('tr'),mark=parseFloat(el.value);if(isNaN(mark)){row.querySelector('.gradecell').textContent='—';row.querySelector('.pointcell').textContent='—';return;}var grade='E',points=1;for(var i=0;i<gradingRules.length;i++){if(mark>=gradingRules[i][0]&&mark<=gradingRules[i][1]){grade=gradingRules[i][2];points=gradingRules[i][3];break;}}if(gradingRules.length===0){if(mark>=80){grade='A';points=12}else if(mark>=75){grade='A-';points=11}else if(mark>=70){grade='B+';points=10}else if(mark>=65){grade='B';points=9}else if(mark>=60){grade='B-';points=8}else if(mark>=55){grade='C+';points=7}else if(mark>=50){grade='C';points=6}else if(mark>=45){grade='C-';points=5}else if(mark>=40){grade='D+';points=4}else if(mark>=30){grade='D';points=3}}row.querySelector('.gradecell').textContent=grade;row.querySelector('.pointcell').textContent=points;});});</script>"%js_rules
    )
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
    school_row=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
    school_name=escape(str(school_row["name"] or "DaviSchool")) if school_row else "DaviSchool"
    school_email=escape(str(school_row["email"] or "")) if school_row else ""
    school_phone=escape(str(school_row["phone"] or "")) if school_row else ""
    school_postal=escape("P.O. Box %s" % str(school_row["postal_address"] or "")) if school_row and "postal_address" in school_row.keys() and school_row["postal_address"] else ""
    school_postal_code=escape(str(school_row["postal_code"] or "")) if school_row and "postal_code" in school_row.keys() else ""
    school_logo=str(school_row["logo_data"] or "") if school_row and "logo_data" in school_row.keys() else ""
    doc_brand="<div class='doc-header'><div class='doc-logo'>%s</div><div><div class='doc-school'>%s</div><div class='doc-contact'>%s%s%s%s</div></div></div>" % (("<img src='%s' alt='School logo'>" % escape(school_logo)) if school_logo else "🏫",school_name,school_email,(" · "+school_phone) if school_phone else "",(" · "+school_postal) if school_postal else "",(" · "+school_postal_code) if school_postal_code else "")
    report_html=f"""<div class='card section' id='report'>{doc_brand}<h2>{escape(str(st['name']))}</h2><div class='muted'>Admission: {escape(str(st['admission_no'] or ''))} · Class: {escape(str(st['class_name'] or ''))} {escape(str(st['stream'] or ''))}</div><table style='margin-top:14px'><thead><tr><th>Subject</th><th>Mark</th><th>Grade</th></tr></thead><tbody>{markrows}</tbody></table><div class='grid'><div class='card'><div class='label'>Subjects</div><div class='kpi'>{len(rows)}</div></div><div class='card'><div class='label'>Total</div><div class='kpi'>{total:.1f}</div></div><div class='card'><div class='label'>Average</div><div class='kpi'>{avg:.1f}%</div></div></div><form method='post' action='/app/report-cards/comment'><input type='hidden' name='exam_id' value='{eid}'><input type='hidden' name='student_id' value='{stid}'><textarea name='comment' class='field' rows='3' placeholder='Teacher / principal comment'>{escape(str(comment or ''))}</textarea><button class='btn' style='margin-top:8px'>Save Comment</button></form><button class='btn' style='margin-top:8px' onclick='window.print()'>Print Report</button></div>""" if st else "<div class='card section'>Select a student and examination.</div>"
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