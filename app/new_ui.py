from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo

router = APIRouter()

def _db():
    from app.main import get_db
    return get_db()

def _shell(title, name, role, body):
    nav = [
        ("/app","⌂","Overview"),
        ("/app/students","🎓","Students"),
        ("/app/staff","👩‍🏫","Staff & Teachers"),
        ("/school/classes","🏫","Classes"),
        ("/app/academics","📝","Academics"),
        ("/school/analysis","📊","Academic Analysis"),
        ("/school/report-cards","📄","Report Cards"),
        ("/school/attendance/bulk","✓","Attendance"),
        ("/school/timetable","🗓","Timetable"),
        ("/app/finance","💰","Fees & Finance"),
        ("/school/accounting","📚","Accounting"),
        ("/school/announcements","📢","Announcements"),
        ("/school/system-settings/user-management","👤","Users"),
        ("/school/system-settings/roles-permissions","🔐","Roles & Permissions"),
        ("/school/system-audit","🛡","Audit Trail"),
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
</style></head><body><div class='app'><aside class='side'><div class='brand'>DaviSchool<small>MANAGEMENT PLATFORM</small></div>{links}<a href='/logout' class='nav' style='margin-top:18px'>↪ Logout</a></aside>
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
<input name='name' required placeholder='Full name' class='field'><input name='email' placeholder='Email' class='field'><input name='phone' placeholder='Phone' class='field'><input name='tsc_no' placeholder='TSC number' class='field'><input name='id_no' placeholder='ID number' class='field'><input name='role' placeholder='Role / subject area' class='field'><select name='gender' class='field'><option>Male</option><option>Female</option><option>Other</option></select><select name='employment_type' class='field'><option>Permanent</option><option>Contract</option><option>Part-time</option></select><button class='btn'>Save Staff</button></form></div>
<div class='card section'><h2>Staff register ({len(staff)})</h2><table><thead><tr><th>Name</th><th>Role</th><th>Email</th><th>Phone</th><th>Employment</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No staff yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Staff & Teachers",body)

@router.post("/app/staff/add")
def staff_add(request: Request,name:str=Form(...),email:str=Form(""),phone:str=Form(""),tsc_no:str=Form(""),id_no:str=Form(""),role:str=Form("Teacher"),gender:str=Form(""),employment_type:str=Form("Permanent")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    con=_db();cur=con.cursor();cur.execute("INSERT INTO teachers(school_id,name,email,phone,tsc_no,gender,id_no,role,employment_type) VALUES(?,?,?,?,?,?,?,?,?)",(sid,name.strip(),email.strip(),phone.strip(),tsc_no.strip(),gender.strip(),id_no.strip(),role.strip(),employment_type.strip()));_audit(cur,sid,request,"STAFF_CREATE",f"Created staff member {name.strip()}");con.commit();con.close();return RedirectResponse("/app/staff",303)

@router.get("/app/academics", response_class=HTMLResponse)
def academics_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    terms=cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    marks=cur.execute("SELECT COUNT(*) c,COALESCE(AVG(mark),0) a FROM marks WHERE school_id=?",(sid,)).fetchone();con.close()
    term_rows="".join(f"<tr><td>{escape(str(t['term_name']))}</td><td>{escape(str(t['year'] or ''))}</td><td>{escape(str(t['start_date'] or ''))}</td><td>{escape(str(t['end_date'] or ''))}</td></tr>" for t in terms)
    exam_rows="".join(f"<tr><td>{escape(str(e['name']))}</td><td>{escape(str(e['term'] or ''))}</td><td>{escape(str(e['year'] or ''))}</td><td>{escape(str(e['exam_type'] or ''))}</td></tr>" for e in exams)
    body=f"""<div class='page'><h1>Academic Management</h1><div class='muted'>Terms, examinations, subjects, marks and academic intelligence.</div>
<div class='grid'><div class='card'><div class='label'>Subjects</div><div class='kpi'>{len(subjects)}</div></div><div class='card'><div class='label'>Exams</div><div class='kpi'>{len(exams)}</div></div><div class='card'><div class='label'>Terms</div><div class='kpi'>{len(terms)}</div></div><div class='card'><div class='label'>Average mark</div><div class='kpi'>{float(marks['a'] or 0):.1f}</div></div></div>
<div class='section'><div class='actions'><a class='action' href='/school/record-marks'><span>📝</span>Record Marks</a><a class='action' href='/school/set-marks'><span>⚙</span>Set Marks</a><a class='action' href='/school/analysis'><span>📊</span>Analysis</a><a class='action' href='/school/report-cards'><span>📄</span>Report Cards</a></div></div>
<div class='card section'><h2>Examinations</h2><table><thead><tr><th>Name</th><th>Term</th><th>Year</th><th>Type</th></tr></thead><tbody>{exam_rows or '<tr><td colspan=4>No examinations.</td></tr>'}</tbody></table></div>
<div class='card section'><h2>Terms</h2><table><thead><tr><th>Term</th><th>Year</th><th>Start</th><th>End</th></tr></thead><tbody>{term_rows or '<tr><td colspan=4>No terms.</td></tr>'}</tbody></table></div></div>"""
    return _school_page(request,"Academic Management",body)

@router.get("/app/finance", response_class=HTMLResponse)
def finance_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    con=_db();cur=con.cursor()
    fee=cur.execute("SELECT COALESCE(SUM(amount),0) expected,COALESCE(SUM(paid),0) paid FROM fees WHERE school_id=?",(sid,)).fetchone()
    exp=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM expenses WHERE school_id=?",(sid,)).fetchone()["v"]
    payments=cur.execute("SELECT fp.*,s.name student_name FROM fee_payments fp LEFT JOIN students s ON s.id=fp.student_id WHERE fp.school_id=? ORDER BY fp.id DESC LIMIT 50",(sid,)).fetchall();con.close()
    rows="".join(f"<tr><td>{escape(str(p['student_name'] or ''))}</td><td>KES {float(p['amount'] or 0):,.2f}</td><td>{escape(str(p['payment_date'] or ''))}</td><td>{escape(str(p['receipt_no'] or ''))}</td></tr>" for p in payments)
    body=f"""<div class='page'><h1>Finance & Fees</h1><div class='muted'>Fee register, collections, expenses and financial control.</div><div class='grid'><div class='card'><div class='label'>Fees charged</div><div class='kpi'>KES {float(fee['expected'] or 0):,.0f}</div></div><div class='card'><div class='label'>Collected</div><div class='kpi'>KES {float(fee['paid'] or 0):,.0f}</div></div><div class='card'><div class='label'>Outstanding</div><div class='kpi'>KES {float(fee['expected'] or 0)-float(fee['paid'] or 0):,.0f}</div></div><div class='card'><div class='label'>Expenses</div><div class='kpi'>KES {float(exp or 0):,.0f}</div></div></div><div class='section'><div class='actions'><a class='action' href='/school/finance'><span>💳</span>Finance Workspace</a><a class='action' href='/school/accounting'><span>📚</span>Accounting</a><a class='action' href='/school/accounting/trial-balance'><span>⚖</span>Trial Balance</a><a class='action' href='/school/fees'><span>📒</span>Fee Register</a></div></div><div class='card section'><h2>Recent fee payments</h2><table><thead><tr><th>Student</th><th>Amount</th><th>Date</th><th>Receipt</th></tr></thead><tbody>{rows or '<tr><td colspan=4>No payments yet.</td></tr>'}</tbody></table></div></div>"""
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
<div class='section'><h2>Daily operations</h2><div class='actions'><a class='action' href='/school/students'><span>🎓</span>Students</a><a class='action' href='/school/record-marks'><span>📝</span>Record Marks</a><a class='action' href='/school/attendance/bulk'><span>✓</span>Attendance</a><a class='action' href='/school/finance'><span>💰</span>Finance</a><a class='action' href='/school/report-cards'><span>📄</span>Report Cards</a><a class='action' href='/school/analysis'><span>📊</span>Analysis</a><a class='action' href='/school/accounting'><span>📚</span>Accounting</a><a class='action' href='/school/system-settings/user-management'><span>👤</span>Users</a></div></div>
<div class='section'><h2>Administration</h2><div class='actions'><a class='action' href='/school/system-settings/school-profile'><span>⚙</span>School Settings</a><a class='action' href='/school/system-settings/roles-permissions'><span>🔐</span>Roles</a><a class='action' href='/school/system-audit'><span>🛡</span>Audit Trail</a><a class='action' href='/portal'><span>🌐</span>Portals</a></div></div></div>"""
    return HTMLResponse(_shell("DaviSchool",name,role,body))
