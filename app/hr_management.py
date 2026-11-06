from datetime import datetime, date
from html import escape
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.new_ui import _audit, _db, _require_permission, _school_page, _school_session

router = APIRouter()


def _hr_admin(request):
    return str(request.session.get("role", "")) in ("school_admin", "registrar", "super_admin")


def _hr_guard(request, permission="staff.view", admin_only=False):
    sid = _school_session(request)
    if not sid:
        return None, RedirectResponse("/", 303)
    if not _require_permission(request, sid, permission):
        return None, HTMLResponse("You do not have permission to access this HR workspace.", 403)
    if admin_only and not _hr_admin(request):
        return None, HTMLResponse("This HR action is restricted to school administrators and registrars.", 403)
    return sid, None


def _ensure_hr_schema(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS staff_leave_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        staff_id INTEGER NOT NULL,
        leave_type TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        reason TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Pending',
        decision_note TEXT DEFAULT '',
        requested_by TEXT DEFAULT '',
        decided_by TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        decided_at TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS staff_pay_settings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        staff_id INTEGER NOT NULL,
        monthly_salary REAL NOT NULL DEFAULT 0,
        allowances REAL NOT NULL DEFAULT 0,
        deductions REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        UNIQUE(school_id,staff_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS staff_payroll_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        period TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Processed',
        created_by TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE(school_id,period)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS staff_payroll_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        run_id INTEGER NOT NULL,
        staff_id INTEGER NOT NULL,
        base_salary REAL NOT NULL DEFAULT 0,
        allowances REAL NOT NULL DEFAULT 0,
        deductions REAL NOT NULL DEFAULT 0,
        net_pay REAL NOT NULL DEFAULT 0,
        UNIQUE(school_id,run_id,staff_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS staff_appraisals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        staff_id INTEGER NOT NULL,
        review_date TEXT NOT NULL,
        review_period TEXT DEFAULT '',
        score INTEGER NOT NULL,
        strengths TEXT DEFAULT '',
        improvement_plan TEXT DEFAULT '',
        reviewer TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_staff_leave_school_status ON staff_leave_requests(school_id,status,start_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_staff_payroll_school_period ON staff_payroll_runs(school_id,period)")


def _hr_now():
    return datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")


def _staff_options(cur, sid):
    return cur.execute("""SELECT id,name,role,department FROM teachers
        WHERE school_id=? AND lower(coalesce(status,'active')) NOT IN ('left','inactive')
        ORDER BY name""", (sid,)).fetchall()


@router.get("/app/staff/leave", response_class=HTMLResponse)
def staff_leave_page(request: Request):
    sid, denied = _hr_guard(request)
    if denied:
        return denied
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    staff = _staff_options(cur, sid)
    rows = cur.execute("""SELECT l.*,t.name staff_name,t.role designation
        FROM staff_leave_requests l JOIN teachers t ON t.id=l.staff_id AND t.school_id=l.school_id
        WHERE l.school_id=? ORDER BY l.id DESC""", (sid,)).fetchall()
    counts = {str(r["status"] or "").lower(): int(r["n"] or 0) for r in cur.execute(
        "SELECT status,COUNT(*) n FROM staff_leave_requests WHERE school_id=? GROUP BY status", (sid,)).fetchall()}
    con.commit()
    con.close()
    staff_opts = "".join("<option value='%s'>%s</option>" % (int(t["id"]), escape(str(t["name"] or ""))) for t in staff)
    cells = "".join(
        "<tr><td><b>%s</b><small>%s</small></td><td>%s</td><td>%s – %s</td><td>%s</td><td><span class='hr-status'>%s</span></td><td>%s</td></tr>" % (
            escape(str(r["staff_name"] or "")), escape(str(r["designation"] or "")),
            escape(str(r["start_date"] or "")), escape(str(r["end_date"] or "")),
            escape(str(r["leave_type"] or "")), escape(str(r["reason"] or "")),
            escape(str(r["status"] or "")),
            ("<form method='post' action='/app/staff/leave/%s/decision' class='hr-inline'><button name='decision' value='Approved'>Approve</button><button name='decision' value='Rejected'>Decline</button></form>" % int(r["id"])) if str(r["status"]).lower() == "pending" and _hr_admin(request) else "—"
        ) for r in rows)
    body = """<div class='page hr-page'><header><div class='hr-eyebrow'>STAFF MANAGER / PEOPLE OPERATIONS</div><h1>Leave Management</h1><p>Record staff leave requests and track approval decisions.</p></header>
    <div class='hr-kpis'><div><small>Pending requests</small><strong>%s</strong></div><div><small>Approved</small><strong>%s</strong></div><div><small>Declined</small><strong>%s</strong></div></div>
    <section class='card'><h2>Record a leave request</h2><form method='post' action='/app/staff/leave/apply' class='hr-form'>
    <label>Staff member<select name='staff_id' required><option value=''>Choose staff</option>%s</select></label>
    <label>Leave type<select name='leave_type' required><option>Annual</option><option>Sick</option><option>Maternity</option><option>Paternity</option><option>Compassionate</option><option>Study</option><option>Unpaid</option><option>Other</option></select></label>
    <label>Start date<input type='date' name='start_date' required></label><label>End date<input type='date' name='end_date' required></label>
    <label class='wide'>Reason<textarea name='reason' rows='2'></textarea></label><button class='hr-button'>Save request</button></form></section>
    <section class='card'><h2>Leave register</h2><div class='hr-table-wrap'><table><thead><tr><th>Staff member</th><th>Leave dates</th><th>Type</th><th>Reason</th><th>Status</th><th>Action</th></tr></thead><tbody>%s</tbody></table></div></section></div>%s""" % (
        counts.get("pending", 0), counts.get("approved", 0), counts.get("rejected", 0), staff_opts,
        cells or "<tr><td colspan='6'>No leave requests recorded yet.</td></tr>", _HR_STYLE)
    return _school_page(request, "Leave Management", body)


@router.post("/app/staff/leave/apply")
def staff_leave_apply(request: Request, staff_id: int = Form(...), leave_type: str = Form(...),
                      start_date: str = Form(...), end_date: str = Form(...), reason: str = Form("")):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if end < start:
            return HTMLResponse("End date cannot be before start date.", 400)
    except ValueError:
        return HTMLResponse("Choose valid leave dates.", 400)
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    person = cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?", (staff_id, sid)).fetchone()
    if not person:
        con.close()
        return HTMLResponse("Staff member not found.", 404)
    overlap = cur.execute("""SELECT id FROM staff_leave_requests WHERE school_id=? AND staff_id=?
        AND lower(status) IN ('pending','approved') AND start_date<=? AND end_date>=? LIMIT 1""",
        (sid, staff_id, end_date, start_date)).fetchone()
    if overlap:
        con.close()
        return HTMLResponse("This request overlaps an existing pending or approved leave period.", 409)
    cur.execute("""INSERT INTO staff_leave_requests(school_id,staff_id,leave_type,start_date,end_date,reason,status,requested_by,created_at)
        VALUES(?,?,?,?,?,?, 'Pending',?,?)""",
        (sid, staff_id, leave_type.strip()[:40], start_date, end_date, reason.strip()[:1000],
         request.session.get("email", ""), _hr_now()))
    _audit(cur, sid, request, "STAFF_LEAVE_REQUEST", "Recorded %s leave for staff ID %s" % (leave_type, staff_id))
    con.commit()
    con.close()
    return RedirectResponse("/app/staff/leave", 303)


@router.post("/app/staff/leave/{leave_id}/decision")
def staff_leave_decision(request: Request, leave_id: int, decision: str = Form(...)):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    decision = decision.strip().title()
    if decision not in ("Approved", "Rejected"):
        return HTMLResponse("Invalid leave decision.", 400)
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    cur.execute("""UPDATE staff_leave_requests SET status=?,decided_by=?,decided_at=?
        WHERE id=? AND school_id=? AND lower(status)='pending'""",
        (decision, request.session.get("email", ""), _hr_now(), leave_id, sid))
    if cur.rowcount:
        _audit(cur, sid, request, "STAFF_LEAVE_" + decision.upper(), "Leave request %s was %s" % (leave_id, decision.lower()))
    con.commit()
    con.close()
    return RedirectResponse("/app/staff/leave", 303)


@router.get("/app/staff/payroll", response_class=HTMLResponse)
def staff_payroll_page(request: Request):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    staff = _staff_options(cur, sid)
    settings = cur.execute("""SELECT p.*,t.name staff_name,t.role designation FROM staff_pay_settings p
        JOIN teachers t ON t.id=p.staff_id AND t.school_id=p.school_id WHERE p.school_id=? ORDER BY t.name""", (sid,)).fetchall()
    runs = cur.execute("""SELECT r.*,COUNT(i.id) staff_count,COALESCE(SUM(i.net_pay),0) total_pay
        FROM staff_payroll_runs r LEFT JOIN staff_payroll_items i ON i.run_id=r.id AND i.school_id=r.school_id
        WHERE r.school_id=? GROUP BY r.id ORDER BY r.period DESC""", (sid,)).fetchall()
    con.commit()
    con.close()
    setting_rows = "".join("<tr><td><b>%s</b><small>%s</small></td><td>KES %s</td><td>KES %s</td><td>KES %s</td></tr>" % (
        escape(str(r["staff_name"] or "")), escape(str(r["designation"] or "")),
        format(float(r["monthly_salary"] or 0), ",.2f"), format(float(r["allowances"] or 0), ",.2f"),
        format(float(r["deductions"] or 0), ",.2f")) for r in settings)
    opts = "".join("<option value='%s'>%s</option>" % (int(t["id"]), escape(str(t["name"] or ""))) for t in staff)
    run_rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>KES %s</td><td><a href='/app/staff/payslips?period=%s'>View payslips</a></td></tr>" % (
        escape(str(r["period"] or "")), escape(str(r["status"] or "")), int(r["staff_count"] or 0),
        format(float(r["total_pay"] or 0), ",.2f"), escape(str(r["period"] or ""))) for r in runs)
    body = """<div class='page hr-page'><header><div class='hr-eyebrow'>STAFF MANAGER / COMPENSATION</div><h1>Payroll Processing</h1><p>Maintain monthly pay settings and create a school payroll run. Amounts are stored in Kenya shillings.</p></header>
    <section class='card'><h2>Set staff pay details</h2><form method='post' action='/app/staff/payroll/settings' class='hr-form'>
    <label>Staff member<select name='staff_id' required><option value=''>Choose staff</option>%s</select></label>
    <label>Monthly salary (KES)<input name='monthly_salary' type='number' min='0' step='0.01' required></label>
    <label>Monthly allowances (KES)<input name='allowances' type='number' min='0' step='0.01' value='0'></label>
    <label>Monthly deductions (KES)<input name='deductions' type='number' min='0' step='0.01' value='0'></label><button class='hr-button'>Save pay details</button></form></section>
    <section class='card'><h2>Configured pay details</h2><div class='hr-table-wrap'><table><thead><tr><th>Staff member</th><th>Monthly salary</th><th>Allowances</th><th>Deductions</th></tr></thead><tbody>%s</tbody></table></div></section>
    <section class='card'><h2>Process monthly payroll</h2><form method='post' action='/app/staff/payroll/process' class='hr-form'><label>Payroll month<input type='month' name='period' required></label><button class='hr-button'>Create payroll run</button></form><p class='hr-note'>A payroll run snapshots the configured salary, allowances and deductions. Each month can be processed once.</p></section>
    <section class='card'><h2>Payroll history</h2><div class='hr-table-wrap'><table><thead><tr><th>Period</th><th>Status</th><th>Staff paid</th><th>Total net pay</th><th>Records</th></tr></thead><tbody>%s</tbody></table></div></section></div>%s""" % (
        opts, setting_rows or "<tr><td colspan='4'>No pay details configured yet.</td></tr>",
        run_rows or "<tr><td colspan='5'>No payroll runs yet.</td></tr>", _HR_STYLE)
    return _school_page(request, "Payroll Processing", body)


@router.post("/app/staff/payroll/settings")
def staff_payroll_settings(request: Request, staff_id: int = Form(...), monthly_salary: float = Form(...),
                           allowances: float = Form(0), deductions: float = Form(0)):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    if min(monthly_salary, allowances, deductions) < 0:
        return HTMLResponse("Pay amounts cannot be negative.", 400)
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    if not cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?", (staff_id, sid)).fetchone():
        con.close()
        return HTMLResponse("Staff member not found.", 404)
    old = cur.execute("SELECT id FROM staff_pay_settings WHERE school_id=? AND staff_id=?", (sid, staff_id)).fetchone()
    if old:
        cur.execute("""UPDATE staff_pay_settings SET monthly_salary=?,allowances=?,deductions=?,updated_at=?
            WHERE school_id=? AND staff_id=?""", (monthly_salary, allowances, deductions, _hr_now(), sid, staff_id))
    else:
        cur.execute("""INSERT INTO staff_pay_settings(school_id,staff_id,monthly_salary,allowances,deductions,updated_at)
            VALUES(?,?,?,?,?,?)""", (sid, staff_id, monthly_salary, allowances, deductions, _hr_now()))
    _audit(cur, sid, request, "STAFF_PAY_SETTINGS_SAVE", "Updated pay settings for staff ID %s" % staff_id)
    con.commit()
    con.close()
    return RedirectResponse("/app/staff/payroll", 303)


@router.post("/app/staff/payroll/process")
def staff_payroll_process(request: Request, period: str = Form(...)):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    try:
        datetime.strptime(period, "%Y-%m")
    except ValueError:
        return HTMLResponse("Choose a valid payroll month.", 400)
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    if cur.execute("SELECT id FROM staff_payroll_runs WHERE school_id=? AND period=?", (sid, period)).fetchone():
        con.close()
        return HTMLResponse("Payroll for this month has already been processed. Use the existing payslip records.", 409)
    configs = cur.execute("""SELECT p.* FROM staff_pay_settings p JOIN teachers t
        ON t.id=p.staff_id AND t.school_id=p.school_id
        WHERE p.school_id=? AND lower(coalesce(t.status,'active')) NOT IN ('left','inactive')""", (sid,)).fetchall()
    if not configs:
        con.close()
        return HTMLResponse("Configure at least one staff salary before processing payroll.", 409)
    cur.execute("INSERT INTO staff_payroll_runs(school_id,period,status,created_by,created_at) VALUES(?,?,'Processed',?,?)",
        (sid, period, request.session.get("email", ""), _hr_now()))
    run_id = int(cur.lastrowid)
    for row in configs:
        base = float(row["monthly_salary"] or 0)
        allowance = float(row["allowances"] or 0)
        deduction = float(row["deductions"] or 0)
        cur.execute("""INSERT INTO staff_payroll_items(school_id,run_id,staff_id,base_salary,allowances,deductions,net_pay)
            VALUES(?,?,?,?,?,?,?)""", (sid, run_id, int(row["staff_id"]), base, allowance, deduction, base + allowance - deduction))
    _audit(cur, sid, request, "STAFF_PAYROLL_PROCESS", "Processed payroll for %s with %s staff records" % (period, len(configs)))
    con.commit()
    con.close()
    return RedirectResponse("/app/staff/payslips?period=" + period, 303)


@router.get("/app/staff/payslips", response_class=HTMLResponse)
def staff_payslips_page(request: Request, period: str = ""):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    periods = cur.execute("SELECT period FROM staff_payroll_runs WHERE school_id=? ORDER BY period DESC", (sid,)).fetchall()
    selected = period if period else (str(periods[0]["period"]) if periods else "")
    rows = cur.execute("""SELECT i.*,t.name staff_name,t.role designation,r.period FROM staff_payroll_items i
        JOIN teachers t ON t.id=i.staff_id AND t.school_id=i.school_id
        JOIN staff_payroll_runs r ON r.id=i.run_id AND r.school_id=i.school_id
        WHERE i.school_id=? AND r.period=? ORDER BY t.name""", (sid, selected)).fetchall() if selected else []
    con.commit()
    con.close()
    opts = "".join("<option %s>%s</option>" % ("selected" if str(p["period"]) == selected else "", escape(str(p["period"]))) for p in periods)
    cells = "".join("<tr><td>%s</td><td>KES %s</td><td>KES %s</td><td>KES %s</td><td><button type='button' onclick='window.open(\"/app/staff/payslips/%s\",\"_blank\")'>Print</button></td></tr>" % (
        escape(str(r["staff_name"] or "")), format(float(r["base_salary"] or 0), ",.2f"),
        format(float(r["allowances"] or 0), ",.2f"), format(float(r["net_pay"] or 0), ",.2f"), int(r["id"])) for r in rows)
    body = """<div class='page hr-page'><header><div class='hr-eyebrow'>STAFF MANAGER / PAY DOCUMENTS</div><h1>Payslips</h1><p>Review and print payslips generated from processed payroll runs.</p></header>
    <section class='card'><form method='get' class='hr-form'><label>Payroll period<select name='period'>%s</select></label><button class='hr-button'>View period</button></form>
    <div class='hr-table-wrap'><table><thead><tr><th>Staff member</th><th>Basic salary</th><th>Allowances</th><th>Net pay</th><th>Document</th></tr></thead><tbody>%s</tbody></table></div></section></div>%s""" % (
        opts or "<option value=''>No payroll runs</option>", cells or "<tr><td colspan='5'>No payslips for this period.</td></tr>", _HR_STYLE)
    return _school_page(request, "Payslips", body)


@router.get("/app/staff/payslips/{item_id}", response_class=HTMLResponse)
def staff_payslip_print(request: Request, item_id: int):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    row = cur.execute("""SELECT i.*,t.name staff_name,t.role designation,t.department,r.period
        FROM staff_payroll_items i JOIN teachers t ON t.id=i.staff_id AND t.school_id=i.school_id
        JOIN staff_payroll_runs r ON r.id=i.run_id AND r.school_id=i.school_id
        WHERE i.id=? AND i.school_id=?""", (item_id, sid)).fetchone()
    con.close()
    if not row:
        return HTMLResponse("Payslip not found.", 404)
    body = """<div class='page hr-page'><div class='hr-tools'><a href='/app/staff/payslips?period=%s'>Back to payslips</a><button onclick='window.print()'>Print payslip</button></div>
    <article class='hr-slip'><h1>DaviSchool · Staff Payslip</h1><h2>%s</h2><p>%s · %s</p><hr><p>Payroll period: <b>%s</b></p>
    <p>Basic salary: <b>KES %s</b></p><p>Allowances: <b>KES %s</b></p><p>Deductions: <b>KES %s</b></p><h2>Net pay: KES %s</h2>
    <p class='hr-note'>Generated from the school's recorded payroll run.</p></article></div>%s""" % (
        escape(str(row["period"])), escape(str(row["staff_name"] or "")), escape(str(row["designation"] or "")),
        escape(str(row["department"] or "")), escape(str(row["period"])), format(float(row["base_salary"] or 0), ",.2f"),
        format(float(row["allowances"] or 0), ",.2f"), format(float(row["deductions"] or 0), ",.2f"),
        format(float(row["net_pay"] or 0), ",.2f"), _HR_STYLE)
    return _school_page(request, "Staff Payslip", body)


@router.get("/app/staff/appraisals", response_class=HTMLResponse)
def staff_appraisals_page(request: Request):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    staff = _staff_options(cur, sid)
    rows = cur.execute("""SELECT a.*,t.name staff_name,t.role designation FROM staff_appraisals a
        JOIN teachers t ON t.id=a.staff_id AND t.school_id=a.school_id
        WHERE a.school_id=? ORDER BY a.review_date DESC,a.id DESC""", (sid,)).fetchall()
    con.commit()
    con.close()
    opts = "".join("<option value='%s'>%s</option>" % (int(t["id"]), escape(str(t["name"] or ""))) for t in staff)
    cells = "".join("<tr><td><b>%s</b><small>%s</small></td><td>%s</td><td>%s</td><td>%s / 5</td><td>%s</td></tr>" % (
        escape(str(r["staff_name"] or "")), escape(str(r["designation"] or "")), escape(str(r["review_date"] or "")),
        escape(str(r["review_period"] or "")), int(r["score"] or 0), escape(str(r["reviewer"] or ""))) for r in rows)
    body = """<div class='page hr-page'><header><div class='hr-eyebrow'>STAFF MANAGER / DEVELOPMENT</div><h1>Staff Appraisals</h1><p>Record structured performance reviews and improvement plans.</p></header>
    <section class='card'><h2>New appraisal</h2><form method='post' action='/app/staff/appraisals/save' class='hr-form'>
    <label>Staff member<select name='staff_id' required><option value=''>Choose staff</option>%s</select></label>
    <label>Review date<input type='date' name='review_date' required></label><label>Review period<input name='review_period' placeholder='e.g. Term 2, 2026'></label>
    <label>Performance score<select name='score'><option value='1'>1 – Needs support</option><option value='2'>2 – Developing</option><option value='3' selected>3 – Meets expectations</option><option value='4'>4 – Strong</option><option value='5'>5 – Outstanding</option></select></label>
    <label class='wide'>Strengths and achievements<textarea name='strengths' rows='2'></textarea></label>
    <label class='wide'>Improvement plan<textarea name='improvement_plan' rows='2'></textarea></label><button class='hr-button'>Save appraisal</button></form></section>
    <section class='card'><h2>Appraisal history</h2><div class='hr-table-wrap'><table><thead><tr><th>Staff member</th><th>Review date</th><th>Period</th><th>Score</th><th>Reviewer</th></tr></thead><tbody>%s</tbody></table></div></section></div>%s""" % (
        opts, cells or "<tr><td colspan='5'>No appraisals recorded yet.</td></tr>", _HR_STYLE)
    return _school_page(request, "Staff Appraisals", body)


@router.post("/app/staff/appraisals/save")
def staff_appraisal_save(request: Request, staff_id: int = Form(...), review_date: str = Form(...),
                         review_period: str = Form(""), score: int = Form(3),
                         strengths: str = Form(""), improvement_plan: str = Form("")):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    try:
        date.fromisoformat(review_date)
    except ValueError:
        return HTMLResponse("Choose a valid review date.", 400)
    if score < 1 or score > 5:
        return HTMLResponse("Appraisal score must be between 1 and 5.", 400)
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    if not cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?", (staff_id, sid)).fetchone():
        con.close()
        return HTMLResponse("Staff member not found.", 404)
    cur.execute("""INSERT INTO staff_appraisals(school_id,staff_id,review_date,review_period,score,strengths,improvement_plan,reviewer,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)""", (sid, staff_id, review_date, review_period.strip()[:100], score,
        strengths.strip()[:3000], improvement_plan.strip()[:3000], request.session.get("email", ""), _hr_now()))
    _audit(cur, sid, request, "STAFF_APPRAISAL_SAVE", "Recorded appraisal for staff ID %s" % staff_id)
    con.commit()
    con.close()
    return RedirectResponse("/app/staff/appraisals", 303)


@router.get("/app/staff/hr-reports", response_class=HTMLResponse)
def staff_hr_reports_page(request: Request):
    sid, denied = _hr_guard(request, admin_only=True)
    if denied:
        return denied
    con = _db()
    cur = con.cursor()
    _ensure_hr_schema(cur)
    active = cur.execute("""SELECT COUNT(*) n FROM teachers WHERE school_id=?
        AND lower(coalesce(status,'active')) NOT IN ('left','inactive')""", (sid,)).fetchone()
    leave = cur.execute("""SELECT lower(status) status,COUNT(*) n FROM staff_leave_requests
        WHERE school_id=? GROUP BY lower(status)""", (sid,)).fetchall()
    payroll = cur.execute("""SELECT COUNT(*) runs,COALESCE(SUM(i.net_pay),0) total
        FROM staff_payroll_runs r LEFT JOIN staff_payroll_items i ON i.run_id=r.id AND i.school_id=r.school_id
        WHERE r.school_id=?""", (sid,)).fetchone()
    appraisals = cur.execute("SELECT COUNT(*) n,COALESCE(AVG(score),0) average FROM staff_appraisals WHERE school_id=?", (sid,)).fetchone()
    con.commit()
    con.close()
    leave_counts = {str(r["status"] or ""): int(r["n"] or 0) for r in leave}
    body = """<div class='page hr-page'><header><div class='hr-eyebrow'>STAFF MANAGER / MANAGEMENT INSIGHTS</div><h1>HR Reports</h1><p>At-a-glance staffing, leave, payroll and appraisal activity.</p></header>
    <div class='hr-kpis'><div><small>Active staff</small><strong>%s</strong></div><div><small>Pending leave</small><strong>%s</strong></div><div><small>Approved leave</small><strong>%s</strong></div><div><small>Payroll runs</small><strong>%s</strong></div><div><small>Payroll net total</small><strong>KES %s</strong></div><div><small>Appraisals</small><strong>%s</strong></div><div><small>Average appraisal score</small><strong>%s / 5</strong></div></div>
    <section class='card'><h2>HR workspace</h2><p>Use the Leave Management, Payroll Processing, Payslips and Staff Appraisals tabs to inspect detailed registers and supporting records.</p></section></div>%s""" % (
        int(active["n"] or 0), leave_counts.get("pending", 0), leave_counts.get("approved", 0),
        int(payroll["runs"] or 0), format(float(payroll["total"] or 0), ",.2f"),
        int(appraisals["n"] or 0), format(float(appraisals["average"] or 0), ".1f"), _HR_STYLE)
    return _school_page(request, "HR Reports", body)


_HR_STYLE = """<style>
.hr-page{width:100%;max-width:1500px;margin:0 auto;color:#244631}.hr-page header{margin:0 0 18px}.hr-eyebrow{font-size:11px;font-weight:800;letter-spacing:.12em;color:#63836c}.hr-page h1{margin:3px 0;color:#174b2b}.hr-page header p,.hr-note{color:#718477}.hr-page .card{background:#fff;border:1px solid #dce9de;border-radius:14px;padding:18px;margin:14px 0;min-width:0}.hr-page .card h2{font-size:17px;color:#214b30;margin:0 0 14px}.hr-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:16px 0}.hr-kpis>div{background:#fff;border:1px solid #dce9de;border-radius:12px;padding:14px}.hr-kpis small{display:block;color:#718477;font-size:11px;font-weight:700}.hr-kpis strong{display:block;color:#176b3a;font-size:23px;margin-top:5px}.hr-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;align-items:end}.hr-form label{display:grid;gap:6px;color:#48624e;font-size:12px;font-weight:700}.hr-form input,.hr-form select,.hr-form textarea{width:100%;min-width:0;padding:10px;border:1px solid #d8e4da;border-radius:8px;font:inherit;color:#244631;background:#fff}.hr-form .wide{grid-column:1/-1}.hr-button,.hr-inline button,.hr-tools button{border:0;border-radius:8px;background:#176b3a;color:white;padding:10px 15px;font-weight:800;cursor:pointer}.hr-table-wrap{width:100%;overflow-x:auto}.hr-page table{width:100%;border-collapse:collapse;min-width:650px}.hr-page th,.hr-page td{text-align:left;padding:11px;border-bottom:1px solid #e8efe9;font-size:12px;vertical-align:top}.hr-page th{color:#55705b;background:#f5faf6}.hr-page td small{display:block;color:#829187;margin-top:3px}.hr-status{display:inline-block;padding:4px 8px;border-radius:20px;background:#eef6ef;color:#24633a;font-weight:700}.hr-inline{display:flex;gap:5px}.hr-inline button{padding:6px 8px;font-size:11px}.hr-inline button[value='Rejected']{background:#8d4242}.hr-tools{display:flex;justify-content:space-between;margin-bottom:15px}.hr-tools a{color:#176b3a}.hr-slip{background:#fff;border:1px solid #dce9de;border-radius:14px;padding:35px;max-width:760px;margin:20px auto;color:#244631}.hr-slip h1{text-align:center;border-bottom:2px solid #176b3a;padding-bottom:16px}.hr-slip h2{margin-top:24px}@media(max-width:650px){.hr-page .card{padding:13px}.hr-form{grid-template-columns:1fr}.hr-form .wide{grid-column:auto}.hr-slip{padding:18px}}@media print{.hr-tools{display:none}.hr-slip{border:0;margin:0;max-width:none}}
</style>"""
