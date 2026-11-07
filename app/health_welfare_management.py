from datetime import datetime, date
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.new_ui import _audit, _db, _school_page, _school_session

router = APIRouter()


def _health_guard(request):
    sid = _school_session(request)
    if not sid:
        return None, RedirectResponse("/", 303)
    if str(request.session.get("role", "")) not in ("school_admin", "registrar"):
        return None, HTMLResponse("Health and welfare records are restricted to school administrators and registrars.", 403)
    return sid, None


def _health_schema(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS student_health_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        blood_group TEXT DEFAULT '',
        allergies TEXT DEFAULT '',
        medical_conditions TEXT DEFAULT '',
        medication TEXT DEFAULT '',
        emergency_contact_name TEXT DEFAULT '',
        emergency_contact_phone TEXT DEFAULT '',
        doctor_or_facility TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        updated_at TEXT NOT NULL,
        updated_by TEXT DEFAULT '',
        UNIQUE(school_id,student_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS student_clinic_visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        visit_date TEXT NOT NULL,
        complaint TEXT NOT NULL,
        assessment TEXT DEFAULT '',
        treatment TEXT DEFAULT '',
        outcome TEXT DEFAULT '',
        guardian_notified TEXT NOT NULL DEFAULT 'No',
        follow_up_date TEXT DEFAULT '',
        attended_by TEXT DEFAULT '',
        recorded_by TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS student_welfare_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'Normal',
        concern TEXT NOT NULL,
        action_plan TEXT DEFAULT '',
        assigned_to TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Open',
        follow_up_date TEXT DEFAULT '',
        opened_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT DEFAULT ''
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_health_profiles_school_student ON student_health_profiles(school_id,student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_visits_school_date ON student_clinic_visits(school_id,visit_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_welfare_cases_school_status ON student_welfare_cases(school_id,status,priority)")


def _students(cur, sid):
    return cur.execute("""SELECT s.id,s.name,s.admission_no,s.class_id,c.name class_name,c.stream
        FROM students s LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id
        WHERE s.school_id=? AND lower(coalesce(s.status,'active')) NOT IN ('inactive','transferred','graduated','left')
        ORDER BY s.name""", (sid,)).fetchall()


def _student_options(rows, selected=0):
    return "<option value=''>Select learner</option>" + "".join(
        "<option value='%s' %s>%s — %s%s</option>" % (
            int(r["id"]), "selected" if int(r["id"]) == int(selected or 0) else "",
            escape(str(r["admission_no"] or "No admission number")),
            escape(str(r["name"] or "")),
            (" · " + escape(str(r["class_name"] or "")) + (" " + escape(str(r["stream"])) if r["stream"] else "")) if r["class_name"] else ""
        ) for r in rows
    )


def _health_styles():
    return """<style>
.health-page{max-width:none;width:100%;display:grid;gap:16px;color:#26372d}
.health-page .health-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.health-page h1{margin:0;color:#174b2b}.health-page p{margin:5px 0 0;color:#687c6d;font-size:13px;line-height:1.55}
.health-page .health-card{background:#fff;border:1px solid #dce9de;border-radius:14px;padding:16px;min-width:0}
.health-page .health-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.health-page .health-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.health-page .health-kpis>div{background:#fff;border:1px solid #dce9de;border-radius:13px;padding:14px}
.health-page .health-kpis small{display:block;color:#718078;font-size:12px}.health-page .health-kpis strong{display:block;color:#174b35;font-size:24px;margin-top:5px}
.health-page label{display:grid;gap:6px;font-size:12px;font-weight:700;color:#52645a;min-width:0}
.health-page input,.health-page select,.health-page textarea{width:100%;min-height:40px;padding:9px;border:1px solid #dce6df;border-radius:9px;background:#fff;color:#26372d;font:inherit}
.health-page textarea{min-height:76px;resize:vertical}.health-page .wide{grid-column:1/-1}
.health-page .health-actions{display:flex;gap:9px;justify-content:flex-end;flex-wrap:wrap;margin-top:12px}
.health-page .health-btn{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:9px;background:#176b3a;color:#fff;padding:10px 14px;font-weight:800;font-size:12px;text-decoration:none;cursor:pointer}
.health-page .health-btn.secondary{background:#edf5ef;color:#245638}
.health-page .health-table-wrap{width:100%;overflow:auto}.health-page table{width:100%;min-width:760px;border-collapse:collapse}
.health-page th,.health-page td{padding:10px;border-bottom:1px solid #edf1ee;text-align:left;vertical-align:top;font-size:12px}
.health-page th{background:#f5f9f6;color:#607267;white-space:nowrap}.health-page td small{display:block;color:#718078;margin-top:3px}
.health-page .pill{display:inline-block;padding:4px 8px;border-radius:20px;background:#edf5ef;color:#245638;font-size:11px;font-weight:800}
.health-page .muted{color:#718078}.health-page .filter-row{display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:12px}
.health-page .filter-row label{flex:1;min-width:160px}
@media(max-width:760px){.health-page .health-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.health-page .health-grid{grid-template-columns:1fr}.health-page .wide{grid-column:auto}.health-page .health-card{padding:12px}}
</style>"""


@router.get("/app/health/profiles", response_class=HTMLResponse)
def health_profiles_page(request: Request, q: str = ""):
    sid, denied = _health_guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _health_schema(cur)
        students = _students(cur, sid)
        where = ["p.school_id=?"]
        params = [sid]
        if q.strip():
            term = "%" + q.strip() + "%"
            where.append("(s.name LIKE ? OR s.admission_no LIKE ? OR p.allergies LIKE ? OR p.medical_conditions LIKE ?)")
            params.extend([term, term, term, term])
        rows = cur.execute("""SELECT p.*,s.name student_name,s.admission_no,c.name class_name
            FROM student_health_profiles p JOIN students s ON s.id=p.student_id AND s.school_id=p.school_id
            LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id
            WHERE """ + " AND ".join(where) + " ORDER BY s.name", tuple(params)).fetchall()
        total = cur.execute("SELECT COUNT(*) n FROM student_health_profiles WHERE school_id=?", (sid,)).fetchone()
        con.commit()
    finally:
        con.close()
    options = _student_options(students)
    rows_html = "".join(
        "<tr><td><b>%s</b><small>%s</small></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            escape(str(r["student_name"] or "")), escape(str(r["admission_no"] or "")),
            escape(str(r["class_name"] or "—")), escape(str(r["blood_group"] or "—")),
            escape(str(r["allergies"] or "—")), escape(str(r["medical_conditions"] or "—")),
            escape(str(r["emergency_contact_phone"] or "—"))
        ) for r in rows
    ) or "<tr><td colspan='6'>No health profiles match this search.</td></tr>"
    body = """<div class='page health-page'><div class='health-head'><div><h1>Student Health Profiles</h1><p>Maintain essential medical alerts and emergency contact details for learners. Access is restricted to school administrators and registrars.</p></div></div>
    <div class='health-kpis'><div><small>Profiles recorded</small><strong>%s</strong></div><div><small>Active learners</small><strong>%s</strong></div><div><small>Clinic visits</small><strong>%s</strong></div><div><small>Open welfare cases</small><strong>%s</strong></div></div>
    <section class='health-card'><h2>Save / update health profile</h2><form method='post' action='/app/health/profiles/save' class='health-grid'>
    <label class='wide'>Learner *<select name='student_id' required>%s</select></label>
    <label>Blood group<input name='blood_group' maxlength='12' placeholder='e.g. O+'></label>
    <label>Known allergies<input name='allergies' maxlength='1000' placeholder='List known allergies or write None known'></label>
    <label class='wide'>Medical conditions<textarea name='medical_conditions' maxlength='2000'></textarea></label>
    <label class='wide'>Medication / care instructions<textarea name='medication' maxlength='2000'></textarea></label>
    <label>Emergency contact name<input name='emergency_contact_name' maxlength='160'></label>
    <label>Emergency contact phone<input name='emergency_contact_phone' maxlength='40'></label>
    <label>Doctor / health facility<input name='doctor_or_facility' maxlength='200'></label>
    <label class='wide'>Additional notes<textarea name='notes' maxlength='2000'></textarea></label>
    <div class='wide health-actions'><button class='health-btn'>Save health profile</button></div></form></section>
    <section class='health-card'><form method='get' class='filter-row'><label>Search learner / medical alert<input name='q' value='%s' placeholder='Name, admission number, allergy or condition'></label><button class='health-btn'>Search</button><a class='health-btn secondary' href='/app/health/profiles'>Clear</a></form>
    <div class='health-table-wrap'><table><thead><tr><th>Learner</th><th>Class</th><th>Blood group</th><th>Allergies</th><th>Medical conditions</th><th>Emergency phone</th></tr></thead><tbody>%s</tbody></table></div></section></div>%s""" % (
        int(total["n"] or 0), len(students),
        int(cur_count_placeholder) if False else 0,
        int(welfare_count_placeholder) if False else 0,
        options, escape(q, quote=True), rows_html, _health_styles()
    )
    return _school_page(request, "Student Health Profiles", body)


@router.post("/app/health/profiles/save")
def health_profile_save(request: Request, student_id: int = Form(...), blood_group: str = Form(""),
    allergies: str = Form(""), medical_conditions: str = Form(""), medication: str = Form(""),
    emergency_contact_name: str = Form(""), emergency_contact_phone: str = Form(""),
    doctor_or_facility: str = Form(""), notes: str = Form("")):
    sid, denied = _health_guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _health_schema(cur)
        if not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?", (student_id, sid)).fetchone():
            return HTMLResponse("Learner not found in this school.", 404)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old = cur.execute("SELECT id FROM student_health_profiles WHERE school_id=? AND student_id=?", (sid, student_id)).fetchone()
        values = (blood_group.strip()[:12], allergies.strip()[:1000], medical_conditions.strip()[:2000],
            medication.strip()[:2000], emergency_contact_name.strip()[:160], emergency_contact_phone.strip()[:40],
            doctor_or_facility.strip()[:200], notes.strip()[:2000], now, request.session.get("email", ""))
        if old:
            cur.execute("""UPDATE student_health_profiles SET blood_group=?,allergies=?,medical_conditions=?,
                medication=?,emergency_contact_name=?,emergency_contact_phone=?,doctor_or_facility=?,notes=?,
                updated_at=?,updated_by=? WHERE id=? AND school_id=?""", values + (int(old["id"]), sid))
        else:
            cur.execute("""INSERT INTO student_health_profiles
                (school_id,student_id,blood_group,allergies,medical_conditions,medication,
                 emergency_contact_name,emergency_contact_phone,doctor_or_facility,notes,updated_at,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (sid, student_id) + values)
        _audit(cur, sid, request, "STUDENT_HEALTH_PROFILE_SAVE", "Updated health profile for learner ID %s" % student_id)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/health/profiles", 303)


@router.get("/app/health/visits", response_class=HTMLResponse)
def clinic_visits_page(request: Request, q: str = ""):
    sid, denied = _health_guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _health_schema(cur)
        students = _students(cur, sid)
        term = "%" + q.strip() + "%"
        rows = cur.execute("""SELECT v.*,s.name student_name,s.admission_no
            FROM student_clinic_visits v JOIN students s ON s.id=v.student_id AND s.school_id=v.school_id
            WHERE v.school_id=? AND (?='' OR s.name LIKE ? OR s.admission_no LIKE ? OR v.complaint LIKE ?)
            ORDER BY v.visit_date DESC,v.id DESC LIMIT 300""",
            (sid, q.strip(), term, term, term)).fetchall()
        total = cur.execute("SELECT COUNT(*) n FROM student_clinic_visits WHERE school_id=?", (sid,)).fetchone()
        con.commit()
    finally:
        con.close()
    opts = _student_options(students)
    visit_rows = "".join(
        "<tr><td>%s</td><td><b>%s</b><small>%s</small></td><td>%s</td><td>%s</td><td>%s</td><td><span class='pill'>%s</span></td></tr>" % (
            escape(str(r["visit_date"] or "")), escape(str(r["student_name"] or "")),
            escape(str(r["admission_no"] or "")), escape(str(r["complaint"] or "")),
            escape(str(r["treatment"] or "—")), escape(str(r["attended_by"] or "—")),
            escape(str(r["guardian_notified"] or "No"))
        ) for r in rows
    ) or "<tr><td colspan='6'>No clinic visits recorded.</td></tr>"
    body = """<div class='page health-page'><div class='health-head'><div><h1>Clinic Visits</h1><p>Record learner illness, first aid, treatment, parent notification and follow-up.</p></div></div>
    <div class='health-kpis'><div><small>All clinic visits</small><strong>%s</strong></div><div><small>Displayed records</small><strong>%s</strong></div></div>
    <section class='health-card'><h2>Record clinic visit</h2><form method='post' action='/app/health/visits/save' class='health-grid'>
    <label class='wide'>Learner *<select name='student_id' required>%s</select></label>
    <label>Visit date *<input type='date' name='visit_date' value='%s' required></label>
    <label>Attended by<input name='attended_by' maxlength='160'></label>
    <label class='wide'>Complaint / reason for visit *<textarea name='complaint' required maxlength='2000'></textarea></label>
    <label class='wide'>Assessment / observations<textarea name='assessment' maxlength='2000'></textarea></label>
    <label class='wide'>Treatment / first aid<textarea name='treatment' maxlength='2000'></textarea></label>
    <label>Guardian notified<select name='guardian_notified'><option>No</option><option>Yes</option><option>Not applicable</option></select></label>
    <label>Follow-up date<input type='date' name='follow_up_date'></label>
    <label class='wide'>Outcome / referral notes<textarea name='outcome' maxlength='1500'></textarea></label>
    <div class='wide health-actions'><button class='health-btn'>Save clinic visit</button></div></form></section>
    <section class='health-card'><form method='get' class='filter-row'><label>Search<input name='q' value='%s' placeholder='Learner, admission number or complaint'></label><button class='health-btn'>Search</button><a class='health-btn secondary' href='/app/health/visits'>Clear</a></form>
    <div class='health-table-wrap'><table><thead><tr><th>Date</th><th>Learner</th><th>Complaint</th><th>Treatment</th><th>Attended by</th><th>Guardian notified</th></tr></thead><tbody>%s</tbody></table></div></section></div>%s""" % (
        int(total["n"] or 0), len(rows), opts, date.today().isoformat(), escape(q, quote=True), visit_rows, _health_styles()
    )
    return _school_page(request, "Clinic Visits", body)


@router.post("/app/health/visits/save")
def clinic_visit_save(request: Request, student_id: int = Form(...), visit_date: str = Form(...),
    complaint: str = Form(...), assessment: str = Form(""), treatment: str = Form(""),
    outcome: str = Form(""), guardian_notified: str = Form("No"), follow_up_date: str = Form(""),
    attended_by: str = Form("")):
    sid, denied = _health_guard(request)
    if denied:
        return denied
    try:
        date.fromisoformat(visit_date)
        if follow_up_date:
            date.fromisoformat(follow_up_date)
    except ValueError:
        return HTMLResponse("Enter valid visit and follow-up dates.", 400)
    if guardian_notified not in ("Yes", "No", "Not applicable"):
        guardian_notified = "No"
    con = _db()
    try:
        cur = con.cursor()
        _health_schema(cur)
        if not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?", (student_id, sid)).fetchone():
            return HTMLResponse("Learner not found in this school.", 404)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""INSERT INTO student_clinic_visits
            (school_id,student_id,visit_date,complaint,assessment,treatment,outcome,guardian_notified,
             follow_up_date,attended_by,recorded_by,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, student_id, visit_date, complaint.strip()[:2000], assessment.strip()[:2000],
             treatment.strip()[:2000], outcome.strip()[:1500], guardian_notified, follow_up_date,
             attended_by.strip()[:160], request.session.get("email", ""), now))
        _audit(cur, sid, request, "STUDENT_CLINIC_VISIT_CREATE", "Recorded clinic visit for learner ID %s" % student_id)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/health/visits", 303)


@router.get("/app/welfare/cases", response_class=HTMLResponse)
def welfare_cases_page(request: Request, status: str = "Open"):
    sid, denied = _health_guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _health_schema(cur)
        students = _students(cur, sid)
        where = ["w.school_id=?"]
        params = [sid]
        if status in ("Open", "In Progress", "Closed"):
            where.append("w.status=?")
            params.append(status)
        rows = cur.execute("""SELECT w.*,s.name student_name,s.admission_no
            FROM student_welfare_cases w JOIN students s ON s.id=w.student_id AND s.school_id=w.school_id
            WHERE """ + " AND ".join(where) + " ORDER BY CASE w.priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 ELSE 2 END,w.id DESC",
            tuple(params)).fetchall()
        counts = cur.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN status='Open' THEN 1 ELSE 0 END) opened,
            SUM(CASE WHEN status='In Progress' THEN 1 ELSE 0 END) progress,
            SUM(CASE WHEN status='Closed' THEN 1 ELSE 0 END) closed
            FROM student_welfare_cases WHERE school_id=?""", (sid,)).fetchone()
        con.commit()
    finally:
        con.close()
    opts = _student_options(students)
    case_rows = "".join(
        "<tr><td><b>%s</b><small>%s</small></td><td>%s</td><td><span class='pill'>%s</span></td><td>%s</td><td>%s</td><td>%s</td><td><form method='post' action='/app/welfare/cases/%s/status' class='filter-row'><select name='status'><option %s>Open</option><option %s>In Progress</option><option %s>Closed</option></select><button class='health-btn'>Update</button></form></td></tr>" % (
            escape(str(r["student_name"] or "")), escape(str(r["admission_no"] or "")),
            escape(str(r["category"] or "")), escape(str(r["priority"] or "")),
            escape(str(r["concern"] or "")), escape(str(r["follow_up_date"] or "—")),
            escape(str(r["status"] or "")), int(r["id"]),
            "selected" if r["status"] == "Open" else "",
            "selected" if r["status"] == "In Progress" else "",
            "selected" if r["status"] == "Closed" else ""
        ) for r in rows
    ) or "<tr><td colspan='7'>No welfare cases in this view.</td></tr>"
    body = """<div class='page health-page'><div class='health-head'><div><h1>Student Welfare Cases</h1><p>Record learner welfare concerns, assign follow-up responsibility and track case progress.</p></div></div>
    <div class='health-kpis'><div><small>Total cases</small><strong>%s</strong></div><div><small>Open</small><strong>%s</strong></div><div><small>In progress</small><strong>%s</strong></div><div><small>Closed</small><strong>%s</strong></div></div>
    <section class='health-card'><h2>Open a welfare case</h2><form method='post' action='/app/welfare/cases/add' class='health-grid'>
    <label class='wide'>Learner *<select name='student_id' required>%s</select></label>
    <label>Concern category<select name='category'><option>Attendance</option><option>Safeguarding</option><option>Financial support</option><option>Learning support</option><option>Behaviour</option><option>Family circumstances</option><option>Nutrition</option><option>Other</option></select></label>
    <label>Priority<select name='priority'><option>Normal</option><option>High</option><option>Urgent</option></select></label>
    <label class='wide'>Concern summary *<textarea name='concern' required maxlength='2500'></textarea></label>
    <label class='wide'>Action / support plan<textarea name='action_plan' maxlength='2500'></textarea></label>
    <label>Assigned to<input name='assigned_to' maxlength='160'></label>
    <label>Follow-up date<input type='date' name='follow_up_date'></label>
    <div class='wide health-actions'><button class='health-btn'>Save welfare case</button></div></form></section>
    <section class='health-card'><form method='get' class='filter-row'><label>Case status<select name='status'><option %s>Open</option><option %s>In Progress</option><option %s>Closed</option><option value='All' %s>All cases</option></select></label><button class='health-btn'>Filter</button><a class='health-btn secondary' href='/app/welfare/cases'>Open cases</a></form>
    <div class='health-table-wrap'><table><thead><tr><th>Learner</th><th>Category</th><th>Priority</th><th>Concern</th><th>Follow-up</th><th>Status</th><th>Update status</th></tr></thead><tbody>%s</tbody></table></div></section></div>%s""" % (
        int(counts["total"] or 0), int(counts["opened"] or 0), int(counts["progress"] or 0), int(counts["closed"] or 0),
        opts,
        "selected" if status == "Open" else "", "selected" if status == "In Progress" else "",
        "selected" if status == "Closed" else "", "selected" if status == "All" else "",
        case_rows, _health_styles()
    )
    return _school_page(request, "Student Welfare Cases", body)


@router.post("/app/welfare/cases/add")
def welfare_case_add(request: Request, student_id: int = Form(...), category: str = Form(...),
    priority: str = Form("Normal"), concern: str = Form(...), action_plan: str = Form(""),
    assigned_to: str = Form(""), follow_up_date: str = Form("")):
    sid, denied = _health_guard(request)
    if denied:
        return denied
    if category not in ("Attendance", "Safeguarding", "Financial support", "Learning support",
        "Behaviour", "Family circumstances", "Nutrition", "Other"):
        category = "Other"
    if priority not in ("Normal", "High", "Urgent"):
        priority = "Normal"
    if follow_up_date:
        try:
            date.fromisoformat(follow_up_date)
        except ValueError:
            return HTMLResponse("Enter a valid follow-up date.", 400)
    con = _db()
    try:
        cur = con.cursor()
        _health_schema(cur)
        if not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?", (student_id, sid)).fetchone():
            return HTMLResponse("Learner not found in this school.", 404)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""INSERT INTO student_welfare_cases
            (school_id,student_id,category,priority,concern,action_plan,assigned_to,status,
             follow_up_date,opened_at,updated_at,updated_by)
            VALUES(?,?,?,?,?,?,?,'Open',?,?,?,?)""",
            (sid, student_id, category, priority, concern.strip()[:2500], action_plan.strip()[:2500],
             assigned_to.strip()[:160], follow_up_date, now, now, request.session.get("email", "")))
        _audit(cur, sid, request, "STUDENT_WELFARE_CASE_CREATE", "Opened welfare case for learner ID %s" % student_id)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/welfare/cases", 303)


@router.post("/app/welfare/cases/{case_id}/status")
def welfare_case_status(request: Request, case_id: int, status: str = Form(...)):
    sid, denied = _health_guard(request)
    if denied:
        return denied
    if status not in ("Open", "In Progress", "Closed"):
        return HTMLResponse("Invalid welfare case status.", 400)
    con = _db()
    try:
        cur = con.cursor()
        _health_schema(cur)
        cur.execute("""UPDATE student_welfare_cases SET status=?,updated_at=?,updated_by=?
            WHERE id=? AND school_id=?""",
            (status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             request.session.get("email", ""), case_id, sid))
        if not cur.rowcount:
            return HTMLResponse("Welfare case not found.", 404)
        _audit(cur, sid, request, "STUDENT_WELFARE_CASE_STATUS", "Updated welfare case %s to %s" % (case_id, status))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/welfare/cases", 303)


@router.get("/app/health/reports", response_class=HTMLResponse)
def health_reports_page(request: Request):
    sid, denied = _health_guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _health_schema(cur)
        profiles = cur.execute("SELECT COUNT(*) n FROM student_health_profiles WHERE school_id=?", (sid,)).fetchone()
        visits = cur.execute("SELECT COUNT(*) n FROM student_clinic_visits WHERE school_id=?", (sid,)).fetchone()
        welfare = cur.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN status='Open' THEN 1 ELSE 0 END) opened,
            SUM(CASE WHEN priority IN ('High','Urgent') AND status<>'Closed' THEN 1 ELSE 0 END) priority_open
            FROM student_welfare_cases WHERE school_id=?""", (sid,)).fetchone()
        con.commit()
    finally:
        con.close()
    body = """<div class='page health-page'><div class='health-head'><div><h1>Health & Welfare Reports</h1><p>School-level service indicators. Individual medical and welfare details remain in their restricted registers.</p></div><button class='health-btn' onclick='window.print()'>Print report</button></div>
    <div class='health-kpis'><div><small>Health profiles</small><strong>%s</strong></div><div><small>Clinic visits</small><strong>%s</strong></div><div><small>Welfare cases</small><strong>%s</strong></div><div><small>Priority open cases</small><strong>%s</strong></div></div>
    <section class='health-card'><h2>Management overview</h2><p>Use the Health Profiles, Clinic Visits and Welfare Cases registers to review learner-level records. This report intentionally displays aggregate counts only.</p></section></div>%s""" % (
        int(profiles["n"] or 0), int(visits["n"] or 0), int(welfare["total"] or 0),
        int(welfare["priority_open"] or 0), _health_styles()
    )
    return _school_page(request, "Health & Welfare Reports", body)
