from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from html import escape
from urllib.parse import quote
from datetime import datetime, timedelta
import json

router = APIRouter()

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
DEFAULT_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


def _ctx(request):
    # Import lazily to avoid circular imports while new_ui registers routers.
    from app.new_ui import _db, _school_session, _require_permission, _school_page, _audit
    return _db, _school_session, _require_permission, _school_page, _audit


def _ensure_tables(con):
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_manager_settings(
        school_id INTEGER PRIMARY KEY,
        days_json TEXT NOT NULL DEFAULT '["Monday","Tuesday","Wednesday","Thursday","Friday"]',
        complexity TEXT NOT NULL DEFAULT 'normal',
        relaxation TEXT NOT NULL DEFAULT 'relaxed'
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_days(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        day_no INTEGER NOT NULL,
        name TEXT NOT NULL,
        short_name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        UNIQUE(school_id,day_no)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_rooms(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        code TEXT,
        capacity INTEGER,
        room_type TEXT,
        active INTEGER NOT NULL DEFAULT 1
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_lessons(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        teacher_id INTEGER,
        room_id INTEGER,
        group_name TEXT,
        lessons_per_week INTEGER NOT NULL DEFAULT 1,
        duration INTEGER NOT NULL DEFAULT 1,
        cycle TEXT NOT NULL DEFAULT 'Every week',
        locked INTEGER NOT NULL DEFAULT 0,
        preferred_room INTEGER,
        notes TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_lesson_classes(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        lesson_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        UNIQUE(school_id,lesson_id,class_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_lesson_teachers(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        lesson_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_availability(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        resource_type TEXT NOT NULL,
        resource_id INTEGER NOT NULL,
        day_name TEXT NOT NULL,
        period_no INTEGER NOT NULL,
        allowed INTEGER NOT NULL DEFAULT 1,
        UNIQUE(school_id,resource_type,resource_id,day_name,period_no)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_constraints(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        scope TEXT NOT NULL,
        constraint_type TEXT NOT NULL,
        target_id INTEGER,
        value TEXT,
        priority TEXT NOT NULL DEFAULT 'preferred',
        enabled INTEGER NOT NULL DEFAULT 1,
        notes TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_slots(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        lesson_id INTEGER NOT NULL,
        day_name TEXT NOT NULL,
        period_no INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        room_id INTEGER,
        locked INTEGER NOT NULL DEFAULT 0,
        generated_run TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_generation_runs(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        mode TEXT NOT NULL,
        complexity TEXT NOT NULL,
        status TEXT NOT NULL,
        placed INTEGER NOT NULL DEFAULT 0,
        requested INTEGER NOT NULL DEFAULT 0,
        message TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_periods(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        period_no INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        UNIQUE(school_id,period_no)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_breaks(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_settings(
        school_id INTEGER PRIMARY KEY,
        periods_per_day INTEGER NOT NULL DEFAULT 7,
        period_minutes INTEGER NOT NULL DEFAULT 40,
        periods_per_week INTEGER NOT NULL DEFAULT 35
    )""")
    return cur


def _migrate_legacy(con, sid):
    """Import old timetable rows once without deleting the legacy table."""
    cur=con.cursor()
    existing=cur.execute("SELECT COUNT(*) c FROM timetable_slots WHERE school_id=?",(sid,)).fetchone()
    legacy=cur.execute("SELECT COUNT(*) c FROM timetable WHERE school_id=?",(sid,)).fetchone()
    if int(existing["c"] or 0) or not legacy or not int(legacy["c"] or 0):
        return
    rows=cur.execute("SELECT * FROM timetable WHERE school_id=? ORDER BY id",(sid,)).fetchall()
    periods=cur.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()
    for row in rows:
        cls=cur.execute("SELECT id FROM classes WHERE school_id=? AND name=? AND COALESCE(stream,'')=? LIMIT 1",(sid,row["class_name"],row["stream"] or "")).fetchone()
        sub=cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=? LIMIT 1",(sid,row["subject"])).fetchone()
        teacher=cur.execute("SELECT id FROM teachers WHERE school_id=? AND name=? LIMIT 1",(sid,row["teacher"])).fetchone() if row["teacher"] else None
        if not cls or not sub:
            continue
        cur.execute("INSERT INTO timetable_lessons(school_id,class_id,subject_id,teacher_id,room_id,group_name,lessons_per_week,duration,cycle,locked,preferred_room,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid,cls["id"],sub["id"],teacher["id"] if teacher else None,None,"Entire class",1,1,"Every week",0,None,"Imported from previous timetable workspace"))
        lesson_id=cur.lastrowid
        p=next((x for x in periods if str(x["start_time"])==str(row["start_time"]) and str(x["end_time"])==str(row["end_time"])),None)
        if p:
            cur.execute("INSERT INTO timetable_slots(school_id,lesson_id,day_name,period_no,start_time,end_time,room_id,locked,generated_run) VALUES(?,?,?,?,?,?,?,?,?)",
                        (sid,lesson_id,row["day"],p["period_no"],p["start_time"],p["end_time"],None,0,"legacy-import"))
    con.commit()


def _seed(con, sid):
    cur = con.cursor()
    row = cur.execute("SELECT school_id FROM timetable_manager_settings WHERE school_id=?", (sid,)).fetchone()
    if not row:
        cur.execute("INSERT INTO timetable_manager_settings(school_id,days_json,complexity,relaxation) VALUES(?,?,?,?) RETURNING school_id",
                    (sid, json.dumps(list(DEFAULT_DAYS)), "normal", "relaxed"))
    existing = cur.execute("SELECT COUNT(*) c FROM timetable_days WHERE school_id=?", (sid,)).fetchone()
    if not int(existing["c"] or 0):
        for i, day in enumerate(DAYS, 1):
            cur.execute("INSERT INTO timetable_days(school_id,day_no,name,short_name,enabled) VALUES(?,?,?,?,?)",
                        (sid, i, day, day[:3].upper(), 1 if day in DEFAULT_DAYS else 0))
    settings = cur.execute("SELECT * FROM timetable_settings WHERE school_id=?", (sid,)).fetchone()
    if not settings:
        cur.execute("INSERT INTO timetable_settings(school_id,periods_per_day,period_minutes,periods_per_week) VALUES(?,?,?,?) RETURNING school_id",
                    (sid, 7, 40, 35))
        settings = cur.execute("SELECT * FROM timetable_settings WHERE school_id=?", (sid,)).fetchone()
    count = int(settings["periods_per_day"] or 7)
    base = datetime.strptime("08:00", "%H:%M")
    for n in range(1, count + 1):
        if not cur.execute("SELECT id FROM timetable_periods WHERE school_id=? AND period_no=?", (sid, n)).fetchone():
            st = (base + timedelta(minutes=(n-1)*int(settings["period_minutes"] or 40))).strftime("%H:%M")
            et = (base + timedelta(minutes=n*int(settings["period_minutes"] or 40))).strftime("%H:%M")
            cur.execute("INSERT INTO timetable_periods(school_id,period_no,start_time,end_time) VALUES(?,?,?,?)",
                        (sid,n,st,et))
    con.commit()


def _page(request, title, body):
    _, _school_session, _require_permission, _school_page, _audit = _ctx(request)
    return _school_page(request, title, body)


def _guard(request, permission="timetable.view"):
    db, school_session, require_permission, _, _ = _ctx(request)
    sid = school_session(request)
    if not sid:
        return None, None, RedirectResponse("/", 303)
    if not require_permission(request, sid, permission):
        return sid, None, HTMLResponse("You do not have permission to use the Timetable Manager.", 403)
    con = db()
    _ensure_tables(con)
    _seed(con, sid)
    return sid, con, None


def _selected_tab(request):
    tab = str(request.query_params.get("tab", "timetable") or "timetable").lower()
    allowed = {"setup","periods","subjects","teachers","classes","rooms","lessons","availability","generate","verify","timetable","print"}
    return tab if tab in allowed else "timetable"


def _tabs(active):
    labels = [
        ("setup","⚙️ Setup"),("periods","🕐 Periods & Bells"),("subjects","📚 Subjects"),
        ("teachers","👨‍🏫 Teachers"),("classes","🏫 Classes"),("rooms","🚪 Rooms"),
        ("lessons","📝 Lessons"),("availability","🎯 Availability"),("generate","🚀 Generate"),
        ("verify","✅ Verify"),("timetable","🗓️ Timetable"),("print","🖨️ Print")
    ]
    return "<div class='tt-tabs'>" + "".join(
        f"<a class='tt-tab {'active' if k==active else ''}' href='/app/timetable?tab={k}'>{label}</a>" for k,label in labels
    ) + "</div>"


def _notice(request):
    msg = request.query_params.get("msg","")
    err = request.query_params.get("error","")
    if msg:
        return "<div class='tt-notice ok'>✅ " + escape(msg) + "</div>"
    if err:
        return "<div class='tt-notice bad'>⚠️ " + escape(err) + "</div>"
    return ""


def _base_css():
    return """<style>
.tt-wrap{padding-bottom:30px}.tt-tabs{display:flex;gap:6px;overflow:auto;padding:8px 0 14px;margin-bottom:10px;border-bottom:1px solid #dbe4ee}
.tt-tab{white-space:nowrap;text-decoration:none;padding:9px 12px;border:1px solid #d7e0ea;border-radius:9px;background:#f8fafc;color:#334155;font-size:12px;font-weight:800}
.tt-tab.active{background:#176B3A;color:#fff;border-color:#176B3A}.tt-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.tt-card{background:#fff;border:1px solid #dbe4ee;border-radius:14px;padding:16px;margin-bottom:14px;box-shadow:0 5px 18px rgba(15,23,42,.04)}
.tt-card h2{margin:0 0 5px;color:#176B3A;font-size:18px}.tt-card h3{margin:0 0 8px;font-size:14px}.tt-muted{color:#64748b;font-size:12px;line-height:1.5}
.tt-field{width:100%;box-sizing:border-box;padding:10px;border:1px solid #cbd5e1;border-radius:9px;background:#fff}.tt-label{font-size:11px;font-weight:800;color:#475569;display:block;margin-bottom:5px}
.tt-btn{display:inline-block;border:0;border-radius:9px;background:#176B3A;color:#fff;padding:10px 14px;font-weight:900;cursor:pointer;text-decoration:none}.tt-btn.alt{background:#334155}.tt-btn.danger{background:#b91c1c}
.tt-form{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-items:end}.tt-form .wide{grid-column:span 2}.tt-form .full{grid-column:1/-1}
.tt-table{width:100%;border-collapse:collapse;font-size:12px}.tt-table th,.tt-table td{border:1px solid #dbe4ee;padding:8px;text-align:left;vertical-align:top}.tt-table th{background:#176B3A;color:#fff}.tt-table tr:nth-child(even){background:#f8fafc}
.tt-notice{padding:11px 13px;border-radius:10px;margin:10px 0;font-weight:800;font-size:12px}.tt-notice.ok{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46}.tt-notice.bad{background:#fff1f2;border:1px solid #fecdd3;color:#9f1239}
.tt-stat{padding:14px;border:1px solid #dbe4ee;border-radius:12px;background:#f8fafc}.tt-stat b{font-size:23px;display:block;color:#176B3A}.tt-check{display:flex;gap:7px;align-items:center;font-size:12px;font-weight:700}
.tt-day{display:inline-flex;gap:8px;align-items:center;margin-right:14px;padding:8px 10px;border:1px solid #dbe4ee;border-radius:9px;background:#f8fafc}
.tt-scroll{overflow:auto}.tt-week{min-width:900px;border-collapse:collapse;width:100%}.tt-week th,.tt-week td{border:1px solid #176B3A;padding:8px;vertical-align:top}.tt-week th{background:#176B3A;color:#fff;white-space:nowrap}.tt-week td{min-width:125px;height:64px;font-size:11px}.tt-break{background:#fff7ed;color:#9a3412;text-align:center;font-weight:900}.tt-class-sheet{margin:0 0 22px;break-inside:avoid}.tt-class-sheet h3{margin:0 0 8px;color:#176B3A}.tt-class-grid{min-width:760px}.tt-class-grid th:first-child{min-width:105px}.tt-class-grid .tt-day-col,.tt-class-grid .tt-day{background:#176B3A!important;color:#fff!important}.tt-class-grid .tt-lesson{background:#fff;min-width:130px;text-align:center;font-weight:600}.tt-class-grid .tt-empty{text-align:center;color:#94a3b8}.tt-class-grid .tt-break{min-width:90px;background:#fff7ed;color:#9a3412;text-align:center;font-weight:900}.tt-class-grid .tt-break-col{background:#fff7ed!important;color:#9a3412!important;min-width:90px}.tt-print-sheets .tt-class-sheet{margin-bottom:30px}@media print{.tt-print-sheets .tt-class-sheet{page-break-after:always}.tt-print-sheets .tt-class-sheet:last-child{page-break-after:auto}.tt-class-grid{min-width:0;width:100%}.tt-class-grid th,.tt-class-grid td{padding:6px;font-size:9px}.tt-class-grid .tt-lesson{min-width:0}}
@media(max-width:900px){.tt-grid,.tt-form{grid-template-columns:1fr}.tt-form .wide{grid-column:auto}}
@media print{.side,.top,.tt-tabs,.no-print{display:none!important}.page{padding:0!important}.tt-card{box-shadow:none;border:0}.tt-wrap{padding:0}.tt-week{min-width:0;font-size:9px}}
</style>"""


def _layout(request, tab, content):
    return _page(request, "Timetable Manager", f"<div class='tt-wrap'><h1>🗓️ Timetable Manager</h1><div class='tt-muted'>A complete school timetable workspace for setup, lesson cards, availability, generation, verification, manual adjustment and printing.</div>{_notice(request)}{_tabs(tab)}{content}{_base_css()}</div>")


@router.get("/app/timetable", response_class=HTMLResponse)
def timetable_manager(request: Request):
    sid, con, response = _guard(request, "timetable.view")
    if response:
        return response
    tab = _selected_tab(request)
    try:
        if tab == "setup": body = _setup(request, con, sid)
        elif tab == "periods": body = _periods(request, con, sid)
        elif tab == "subjects": body = _subjects(con, sid)
        elif tab == "teachers": body = _teachers(con, sid)
        elif tab == "classes": body = _classes(con, sid)
        elif tab == "rooms": body = _rooms(con, sid)
        elif tab == "lessons": body = _lessons(request, con, sid)
        elif tab == "availability": body = _availability(request, con, sid)
        elif tab == "generate": body = _generate(con, sid)
        elif tab == "verify": body = _verify(con, sid)
        elif tab == "print": body = _print_view(con, sid)
        else: body = _timetable(request, con, sid)
        return _layout(request, tab, body)
    finally:
        con.close()


def _setup(request, con, sid):
    settings = con.execute("SELECT * FROM timetable_manager_settings WHERE school_id=?", (sid,)).fetchone()
    enabled = con.execute("SELECT * FROM timetable_days WHERE school_id=? ORDER BY day_no", (sid,)).fetchall()
    complexity = str(settings["complexity"] if settings else "normal")
    relaxation = str(settings["relaxation"] if settings else "relaxed")
    days = "".join(
        f"<label class='tt-day'><input type='checkbox' name='days' value='{escape(str(d['name']))}' {'checked' if int(d['enabled'] or 0) else ''}>{escape(str(d['name']))}</label>"
        for d in enabled
    )
    return f"""<div class='tt-card'><h2>⚙️ School Timetable Setup</h2><div class='tt-muted'>Configure the timetable cycle and generation behaviour. The existing school Classes, Subjects and Teachers remain the source of truth.</div>
<form method='post' action='/app/timetable/setup/save' class='tt-form' style='margin-top:14px'>
<div class='full'><span class='tt-label'>Teaching days</span>{days}</div>
<label><span class='tt-label'>Generation complexity</span><select name='complexity' class='tt-field'><option value='normal' {'selected' if complexity=='normal' else ''}>Normal</option><option value='large' {'selected' if complexity=='large' else ''}>Large</option><option value='huge' {'selected' if complexity=='huge' else ''}>Huge</option></select></label>
<label><span class='tt-label'>Constraint mode</span><select name='relaxation' class='tt-field'><option value='draft' {'selected' if relaxation=='draft' else ''}>Draft</option><option value='relaxed' {'selected' if relaxation=='relaxed' else ''}>Allow relaxation</option><option value='strict' {'selected' if relaxation=='strict' else ''}>Strict</option></select></label>
<div><button class='tt-btn'>💾 Save Setup</button></div></form></div>
<div class='tt-grid'><div class='tt-stat'><b>1</b>School timetable</div><div class='tt-stat'><b>4</b>Core resource types</div><div class='tt-stat'><b>3</b>Generation modes</div></div>
<div class='tt-card'><h3>Workflow</h3><div class='tt-muted'>Setup → Periods & Bells → Subjects / Teachers / Classes / Rooms → Lessons → Availability → Generate → Verify → Timetable → Print</div></div>"""


def _periods(request, con, sid):
    settings = con.execute("SELECT * FROM timetable_settings WHERE school_id=?", (sid,)).fetchone()
    periods = con.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no", (sid,)).fetchall()
    breaks = con.execute("SELECT * FROM timetable_breaks WHERE school_id=? ORDER BY start_time,id", (sid,)).fetchall()
    ppd = int(settings["periods_per_day"] or 7)
    pm = int(settings["period_minutes"] or 40)
    rows = "".join(
        f"<tr><td><b>Period {int(p['period_no'])}</b></td><td><input class='tt-field' type='time' name='start_{int(p['period_no'])}' value='{escape(str(p['start_time']))}'></td><td><input class='tt-field' type='time' name='end_{int(p['period_no'])}' value='{escape(str(p['end_time']))}'></td></tr>"
        for p in periods
    )
    br = "".join(
        f"<tr><td>{escape(str(b['name']))}</td><td>{escape(str(b['start_time']))}</td><td>{escape(str(b['end_time']))}</td><td><form method='post' action='/app/timetable/break/delete/{b['id']}' onsubmit='return confirm(&quot;Delete this break?&quot;)'><button class='tt-btn danger'>🗑️</button></form></td></tr>"
        for b in breaks
    ) or "<tr><td colspan='4'>No breaks saved.</td></tr>"
    return f"""<div class='tt-card'><h2>🕐 Periods & Bells</h2><div class='tt-muted'>Set the number of periods and exact bell times. Saved breaks are treated as unavailable timetable time.</div>
<form method='post' action='/app/timetable/periods/settings' class='tt-form' style='margin-top:12px'><label><span class='tt-label'>Periods per day</span><input class='tt-field' name='periods_per_day' type='number' min='1' max='12' value='{ppd}' required></label><label><span class='tt-label'>Default period minutes</span><input class='tt-field' name='period_minutes' type='number' min='20' max='180' value='{pm}' required></label><label><span class='tt-label'>Maximum lessons per week</span><input class='tt-field' name='periods_per_week' type='number' min='1' max='84' value='{int(settings['periods_per_week'] or 35)}' required></label><div><button class='tt-btn'>💾 Save</button></div></form></div>
<div class='tt-card'><h3>Bell / Period Times</h3><form method='post' action='/app/timetable/periods/save'><div class='tt-scroll'><table class='tt-table'><thead><tr><th>Period</th><th>Start</th><th>End</th></tr></thead><tbody>{rows}</tbody></table></div><button class='tt-btn' style='margin-top:10px'>💾 Save Period Times</button></form></div>
<div class='tt-card'><h3>☕ Break Periods</h3><form method='post' action='/app/timetable/break/save' class='tt-form'><label><span class='tt-label'>Break name</span><input class='tt-field' name='name' required placeholder='Tea Break / Lunch'></label><label><span class='tt-label'>Start</span><input class='tt-field' name='start_time' type='time' required></label><label><span class='tt-label'>End</span><input class='tt-field' name='end_time' type='time' required></label><div><button class='tt-btn'>💾 Save Break</button></div></form><div class='tt-scroll' style='margin-top:10px'><table class='tt-table'><thead><tr><th>Name</th><th>Start</th><th>End</th><th></th></tr></thead><tbody>{br}</tbody></table></div></div>"""


def _subjects(con, sid):
    rows = con.execute("SELECT id,name,code,initial FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    html_parts=[]
    for r in rows:
        total = con.execute("""SELECT COALESCE(SUM(
                l.lessons_per_week * l.duration *
                CASE
                    WHEN (SELECT COUNT(*) FROM timetable_lesson_classes lc
                          WHERE lc.school_id=l.school_id AND lc.lesson_id=l.id) > 0
                    THEN (SELECT COUNT(*) FROM timetable_lesson_classes lc
                          WHERE lc.school_id=l.school_id AND lc.lesson_id=l.id)
                    ELSE 1
                END
            ),0) total
            FROM timetable_lessons l
            WHERE l.school_id=? AND l.subject_id=?""", (sid,r["id"])).fetchone()
        html_parts.append(f"<tr><td>{r['id']}</td><td><b>{escape(str(r['name'] or ''))}</b></td><td>{escape(str(r['code'] or ''))}</td><td>{escape(str(r['initial'] or ''))}</td><td><b>{int(total['total'] or 0)}</b></td></tr>")
    html="".join(html_parts)
    return f"""<div class='tt-card'><h2>📚 Subjects</h2><div class='tt-muted'>The weekly subject load is calculated directly from every saved Lesson Card allocation: Lessons per week × duration, with a multiplier for every participating class/stream in a combined lesson. Each allocation is therefore reflected in the subject total.</div><div class='tt-scroll' style='margin-top:12px'><table class='tt-table'><thead><tr><th>ID</th><th>Subject</th><th>Code</th><th>Initial</th><th>No. of Lessons / Week</th></tr></thead><tbody>{html or '<tr><td colspan=5>No subjects found.</td></tr>'}</tbody></table></div></div>"""


def _teachers(con, sid):
    rows = con.execute("SELECT id,name,email,phone,role,department FROM teachers WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    html_parts=[]
    for r in rows:
        # Count weekly teaching requirements from lesson-card inputs. Co-teachers each receive
        # the full lesson count because each teacher is occupied for every co-taught lesson.
        total = con.execute("""SELECT COALESCE(SUM(
                l.lessons_per_week * l.duration *
                CASE
                    WHEN (SELECT COUNT(*) FROM timetable_lesson_classes lc
                          WHERE lc.school_id=l.school_id AND lc.lesson_id=l.id) > 0
                    THEN (SELECT COUNT(*) FROM timetable_lesson_classes lc
                          WHERE lc.school_id=l.school_id AND lc.lesson_id=l.id)
                    ELSE 1
                END
            ),0) total
            FROM timetable_lessons l
            WHERE l.school_id=? AND (l.teacher_id=? OR l.id IN
                (SELECT lesson_id FROM timetable_lesson_teachers WHERE school_id=? AND teacher_id=?))""",
            (sid,r["id"],sid,r["id"])).fetchone()
        html_parts.append(f"<tr><td>{r['id']}</td><td><b>{escape(str(r['name'] or ''))}</b></td><td>{escape(str(r['email'] or ''))}</td><td>{escape(str(r['phone'] or ''))}</td><td>{escape(str(r['department'] or r['role'] or ''))}</td><td><b>{int(total['total'] or 0)}</b></td></tr>")
    html="".join(html_parts)
    return f"""<div class='tt-card'><h2>👨‍🏫 Teachers</h2><div class='tt-muted'>The weekly teacher load is calculated directly from every saved Lesson Card allocation: Lessons per week × duration, multiplied by the number of participating classes/streams. Co-teachers receive the same full allocation because they are teaching the combined lesson.</div><div class='tt-scroll' style='margin-top:12px'><table class='tt-table'><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>Role / Department</th><th>No. of Lessons / Week</th></tr></thead><tbody>{html or '<tr><td colspan=6>No teachers found.</td></tr>'}</tbody></table></div></div>"""


def _classes(con, sid):
    rows = con.execute("SELECT id,name,level,stream FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
    html_parts=[]
    for r in rows:
        total = con.execute("""SELECT COALESCE(SUM(l.lessons_per_week * l.duration),0) total
            FROM timetable_lessons l
            WHERE l.school_id=? AND (l.class_id=? OR l.id IN
                (SELECT lesson_id FROM timetable_lesson_classes WHERE school_id=? AND class_id=?))""",
            (sid,r["id"],sid,r["id"])).fetchone()
        html_parts.append(f"<tr><td>{r['id']}</td><td><b>{escape(str(r['name'] or ''))}</b></td><td>{escape(str(r['level'] or ''))}</td><td>{escape(str(r['stream'] or ''))}</td><td><b>{int(total['total'] or 0)}</b></td></tr>")
    html="".join(html_parts)
    return f"""<div class='tt-card'><h2>🏫 Classes</h2><div class='tt-muted'>The weekly class load counts each period of a lesson. A double lesson counts as 2, and a combined lesson is counted for each participating class/stream.</div><div class='tt-scroll' style='margin-top:12px'><table class='tt-table'><thead><tr><th>ID</th><th>Class</th><th>Level</th><th>Stream</th><th>No. of Lessons / Week</th></tr></thead><tbody>{html or '<tr><td colspan=5>No classes found.</td></tr>'}</tbody></table></div></div>"""


def _rooms(con, sid):
    rows = con.execute("SELECT * FROM timetable_rooms WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    html = "".join(f"<tr><td>{escape(str(r['name']))}</td><td>{escape(str(r['code'] or ''))}</td><td>{escape(str(r['capacity'] or ''))}</td><td>{escape(str(r['room_type'] or ''))}</td><td><form method='post' action='/app/timetable/room/delete/{r['id']}' onsubmit='return confirm(&quot;Delete this room?&quot;)'><button class='tt-btn danger'>🗑️</button></form></td></tr>" for r in rows)
    return f"""<div class='tt-card'><h2>🚪 Classrooms / Rooms</h2><div class='tt-muted'>Rooms are separate timetable resources. A room cannot host two lessons at the same time unless you deliberately create no room requirement for those lessons.</div>
<form method='post' action='/app/timetable/room/save' class='tt-form' style='margin-top:12px'><label><span class='tt-label'>Room name</span><input class='tt-field' name='name' required placeholder='Science Lab 1'></label><label><span class='tt-label'>Code</span><input class='tt-field' name='code' placeholder='SCI1'></label><label><span class='tt-label'>Capacity</span><input class='tt-field' name='capacity' type='number' min='0'></label><label><span class='tt-label'>Type</span><input class='tt-field' name='room_type' placeholder='Laboratory / Classroom'></label><div><button class='tt-btn'>💾 Add Room</button></div></form>
<div class='tt-scroll' style='margin-top:12px'><table class='tt-table'><thead><tr><th>Name</th><th>Code</th><th>Capacity</th><th>Type</th><th></th></tr></thead><tbody>{html or '<tr><td colspan=5>No rooms configured.</td></tr>'}</tbody></table></div></div>"""


def _lesson_form(con, sid, existing=None):
    classes = con.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
    subjects = con.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    teachers = con.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    rooms = con.execute("SELECT id,name FROM timetable_rooms WHERE school_id=? AND active=1 ORDER BY name", (sid,)).fetchall()
    e = existing or {}
    selected_class_ids = {int(e["class_id"])} if existing else set()
    selected_teacher_ids = {int(e["teacher_id"])} if existing and e.get("teacher_id") else set()
    if existing:
        selected_class_ids.update(int(x["class_id"]) for x in con.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?", (sid, int(e["id"]))).fetchall())
        selected_teacher_ids.update(int(x["teacher_id"]) for x in con.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?", (sid, int(e["id"]))).fetchall())
    opts = lambda rows,key,label: "".join(f"<option value='{r[key]}' {'selected' if str(e.get(key,''))==str(r[key]) else ''}>{escape(str(r[label] or ''))}</option>" for r in rows)
    return f"""<div class='tt-card'><h3>{'✏️ Edit Lesson' if existing else '📝 Add Lesson Card'}</h3><div class='tt-muted'>Each lesson card represents a teaching requirement. Weekly count and duration are used by the generator.</div>
<form method='post' action='/app/timetable/lesson/save' class='tt-form' style='margin-top:12px'>
<input type='hidden' name='lesson_id' value='{e.get("id","")}'>
<label class='wide'><span class='tt-label'>Classes / Streams — select multiple to combine</span><select class='tt-field' name='class_ids' multiple size='6' required>{"".join(f"<option value='{r['id']}' {'selected' if int(r['id']) in selected_class_ids else ''}>{escape(str(r['name'] or ''))}{(' — '+escape(str(r['stream']))) if r['stream'] else ''}</option>" for r in classes)}</select><small class='tt-muted'>Select 2, 3, 4, 5… streams/classes when one teacher teaches them together.</small></label>
<label><span class='tt-label'>Subject</span><select class='tt-field' name='subject_id' required><option value=''>Select subject</option>{opts(subjects,'id','name')}</select></label>
<label class='wide'><span class='tt-label'>Teachers — select multiple for co-teaching</span><select class='tt-field' name='teacher_ids' multiple size='5'>{"".join(f"<option value='{r['id']}' {'selected' if int(r['id']) in selected_teacher_ids else ''}>{escape(str(r['name'] or ''))}</option>" for r in teachers)}</select><small class='tt-muted'>Select 2 or more teachers when they co-teach the same lesson.</small></label>
<label><span class='tt-label'>Lessons per week</span><input class='tt-field' name='lessons_per_week' type='number' min='1' max='30' value='{e.get("lessons_per_week",1)}' required></label>
<label><span class='tt-label'>Duration (periods)</span><select class='tt-field' name='duration'><option value='1' {'selected' if str(e.get('duration',1))=='1' else ''}>Single</option><option value='2' {'selected' if str(e.get('duration',1))=='2' else ''}>Double</option><option value='3' {'selected' if str(e.get('duration',1))=='3' else ''}>Triple</option></select></label>
<label><span class='tt-label'>Room</span><select class='tt-field' name='room_id'><option value=''>Any available room</option>{opts(rooms,'id','name')}</select></label>
<label><span class='tt-label'>Group / Division</span><input class='tt-field' name='group_name' value='{escape(str(e.get("group_name") or ""))}' placeholder='Entire class / Boys / Group A'></label>
<label><span class='tt-label'>Cycle / Term</span><select class='tt-field' name='cycle'><option>Every week</option><option {'selected' if e.get('cycle')=='Alternate weeks' else ''}>Alternate weeks</option></select></label>
<label class='tt-check'><input type='checkbox' name='locked' value='1' {'checked' if int(e.get('locked',0) or 0) else ''}> Locked card</label>
<label class='full'><span class='tt-label'>Notes</span><input class='tt-field' name='notes' value='{escape(str(e.get("notes") or ""))}' placeholder='Special instructions'></label>
<div><button class='tt-btn'>💾 Save Lesson</button></div></form></div>"""


def _lessons(request, con, sid):
    rows = con.execute("""SELECT l.*,c.name class_name,c.stream,sub.name subject,t.name teacher,r.name room
        FROM timetable_lessons l JOIN classes c ON c.id=l.class_id JOIN subjects sub ON sub.id=l.subject_id
        LEFT JOIN teachers t ON t.id=l.teacher_id LEFT JOIN timetable_rooms r ON r.id=l.room_id
        WHERE l.school_id=? ORDER BY c.name,c.stream,sub.name,l.id""", (sid,)).fetchall()
    html_parts=[]
    for r in rows:
        cr=con.execute("SELECT c.name,c.stream FROM timetable_lesson_classes lc JOIN classes c ON c.id=lc.class_id WHERE lc.school_id=? AND lc.lesson_id=? ORDER BY c.name,c.stream",(sid,r["id"])).fetchall()
        tr=con.execute("SELECT t.name FROM timetable_lesson_teachers lt JOIN teachers t ON t.id=lt.teacher_id WHERE lt.school_id=? AND lt.lesson_id=? ORDER BY lt.id",(sid,r["id"])).fetchall()
        classes_label=", ".join(f"{x['name']}{(' — '+x['stream']) if x['stream'] else ''}" for x in cr) or f"{r['class_name']}{(' — '+r['stream']) if r['stream'] else ''}"
        teachers_label=", ".join(str(x["name"]) for x in tr) or str(r["teacher"] or "")
        html_parts.append(f"<tr><td>{escape(classes_label)}</td><td><b>{escape(str(r['subject']))}</b></td><td>{escape(teachers_label)}</td><td>{int(r['lessons_per_week'])}</td><td>{int(r['duration'])}</td><td>{escape(str(r['group_name'] or 'Entire class'))}</td><td>{'🔒' if int(r['locked'] or 0) else ''}</td><td><a class='tt-btn alt' href='/app/timetable?tab=lessons&edit={r['id']}'>Edit</a> <form style='display:inline' method='post' action='/app/timetable/lesson/delete/{r['id']}' onsubmit='return confirm(&quot;Delete this lesson card?&quot;)'><button class='tt-btn danger'>🗑️</button></form></td></tr>")
    html="".join(html_parts)
    edit_id = request.query_params.get("edit", "")
    edit = None
    if str(edit_id).isdigit():
        edit = con.execute("SELECT * FROM timetable_lessons WHERE id=? AND school_id=?", (int(edit_id), sid)).fetchone()
    return _lesson_form(con,sid,edit) + f"""<div class='tt-card'><h3>Lesson Cards ({len(rows)})</h3><div class='tt-muted'>This is the timetable equivalent of aSc lesson cards/contracts. One row is one weekly teaching requirement.</div><div class='tt-scroll' style='margin-top:10px'><table class='tt-table'><thead><tr><th>Classes / Streams</th><th>Subject</th><th>Teachers</th><th>/Week</th><th>Length</th><th>Group</th><th></th><th></th></tr></thead><tbody>{html or '<tr><td colspan=8>No lesson cards yet.</td></tr>'}</tbody></table></div></div>"""


def _availability(request, con, sid):
    kind = str(request.query_params.get("kind","teacher") or "teacher").lower()
    if kind not in ("teacher","subject"): kind="teacher"
    selected = int(request.query_params.get("resource_id") or 0) if str(request.query_params.get("resource_id") or "").isdigit() else 0
    teachers = con.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    subjects = con.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    resources = teachers if kind=="teacher" else subjects
    if not selected and resources: selected=int(resources[0]["id"])
    days=[r["name"] for r in con.execute("SELECT * FROM timetable_days WHERE school_id=? AND enabled=1 ORDER BY day_no",(sid,)).fetchall()]
    periods=con.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()
    saved={}
    if selected:
        for r in con.execute("SELECT day_name,period_no,allowed FROM timetable_availability WHERE school_id=? AND resource_type=? AND resource_id=?",(sid,kind,selected)).fetchall():
            saved[(str(r["day_name"]),int(r["period_no"]))]=bool(int(r["allowed"] or 0))
    resource_options="".join(f"<option value='{r['id']}' {'selected' if int(r['id'])==selected else ''}>{escape(str(r['name'] or ''))}</option>" for r in resources)
    head="".join(f"<th>{escape(d)}</th>" for d in days)
    cells=[]
    for p in periods:
        row=[f"<tr><td><b>Period {int(p['period_no'])}</b><br><small>{escape(str(p['start_time']))}–{escape(str(p['end_time']))}</small></td>"]
        for d in days:
            allowed=saved.get((d,int(p["period_no"])),True)
            val=f"{d}|{int(p['period_no'])}"
            row.append(f"<td style='text-align:center'><input type='checkbox' name='slot' value='{escape(val)}' {'checked' if allowed else ''} aria-label='{escape(d)} period {int(p['period_no'])}'></td>")
        row.append("</tr>");cells.append("".join(row))
    table="".join(cells) or "<tr><td>No periods configured.</td></tr>"
    return f"""<div class='tt-card'><h2>🎯 Teacher & Subject Availability</h2><div class='tt-muted'>This replaces the old generic Constraints page with a period-by-period availability grid. Tick a period when the teacher or subject is allowed to be scheduled; untick it to block that period during automatic generation. Unconfigured cells remain available.</div>
<div class='tt-grid' style='margin-top:12px'>
<form method='get' action='/app/timetable' class='tt-form'>
<input type='hidden' name='tab' value='availability'>
<label><span class='tt-label'>Resource type</span><select class='tt-field' name='kind' onchange='this.form.submit()'><option value='teacher' {'selected' if kind=='teacher' else ''}>👨‍🏫 Teacher</option><option value='subject' {'selected' if kind=='subject' else ''}>📚 Subject</option></select></label>
<label><span class='tt-label'>{'Teacher' if kind=='teacher' else 'Subject'}</span><select class='tt-field' name='resource_id' onchange='this.form.submit()'>{resource_options or '<option value="">No resources found</option>'}</select></label>
</form>
<div class='tt-card' style='margin:0'><h3>How it works</h3><div class='tt-muted'>✅ Tick = available for generation<br>⬜ Untick = unavailable for generation<br>Only the selected teacher/subject is affected.</div></div></div>
<form method='post' action='/app/timetable/availability/save' style='margin-top:12px'>
<input type='hidden' name='kind' value='{escape(kind)}'><input type='hidden' name='resource_id' value='{selected}'>
<div class='tt-scroll'><table class='tt-table'><thead><tr><th>Period</th>{head}</tr></thead><tbody>{table}</tbody></table></div>
<div style='margin-top:12px'><button class='tt-btn'>💾 Save Availability</button></div></form></div>
<div class='tt-card'><h3>🧩 aSc-style scheduling controls</h3><div class='tt-muted'>Use this grid before generation to define teacher working availability and subject time restrictions. The generator will not place a lesson in an unticked cell for its teacher or subject. You can still use Lesson Cards, locked placements, rooms, breaks and normal collision checking.</div></div>"""

def _constraints(con, sid):
    rows = con.execute("SELECT * FROM timetable_constraints WHERE school_id=? ORDER BY id DESC", (sid,)).fetchall()
    html = "".join(
        f"<tr><td>{escape(str(r['scope']))}</td><td>{escape(str(r['constraint_type']))}</td><td>{escape(str(r['value'] or ''))}</td><td>{escape(str(r['priority']))}</td><td>{'On' if int(r['enabled'] or 0) else 'Off'}</td><td><form method='post' action='/app/timetable/constraint/delete/{r['id']}' onsubmit='return confirm(&quot;Delete this constraint?&quot;)'><button class='tt-btn danger'>🗑️</button></form></td></tr>"
        for r in rows
    )
    types = [
        "Teacher max lessons/day","Teacher max consecutive","Teacher unavailable",
        "Class max lessons/day","Class max gaps/day","Class unavailable",
        "Subject max/day","Subject not consecutive","Room unavailable",
        "No first period","No last period","Fixed lesson"
    ]
    options = "".join(f"<option>{escape(t)}</option>" for t in types)
    return f"""<div class='tt-card'><h2>🧩 Constraints</h2><div class='tt-muted'>Constraints are stored separately from lesson cards so generation can be tested progressively. Draft, relaxed and strict generation modes are supported.</div>
<form method='post' action='/app/timetable/constraint/save' class='tt-form' style='margin-top:12px'>
<label><span class='tt-label'>Scope</span><select class='tt-field' name='scope'><option>Teacher</option><option>Class</option><option>Subject</option><option>Room</option><option>Other</option></select></label>
<label><span class='tt-label'>Constraint</span><select class='tt-field' name='constraint_type'>{options}</select></label>
<label><span class='tt-label'>Target ID (optional)</span><input class='tt-field' name='target_id' type='number' min='1'></label>
<label class='wide'><span class='tt-label'>Value</span><input class='tt-field' name='value' placeholder='e.g. 5, Mon:1,2,3 or JSON list'></label>
<label><span class='tt-label'>Priority</span><select class='tt-field' name='priority'><option>preferred</option><option>important</option><option>strict</option></select></label>
<div><button class='tt-btn'>💾 Add Constraint</button></div></form>
<div class='tt-scroll' style='margin-top:12px'><table class='tt-table'><thead><tr><th>Scope</th><th>Type</th><th>Value</th><th>Priority</th><th>Status</th><th></th></tr></thead><tbody>{html or '<tr><td colspan=6>No constraints configured.</td></tr>'}</tbody></table></div></div>"""


def _generate(con, sid):
    settings=con.execute("SELECT * FROM timetable_manager_settings WHERE school_id=?", (sid,)).fetchone()
    classes=con.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
    lesson_count=con.execute("SELECT COUNT(*) c FROM timetable_lessons WHERE school_id=?", (sid,)).fetchone()["c"]
    slot_count=con.execute("SELECT COUNT(*) c FROM timetable_slots WHERE school_id=?", (sid,)).fetchone()["c"]
    opts="".join(f"<option value='{c['id']}'>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    complexity=str(settings["complexity"] if settings else "normal")
    relaxation=str(settings["relaxation"] if settings else "relaxed")
    return f"""<div class='tt-card'><h2>🚀 Generate Timetable</h2><div class='tt-muted'>Generate from lesson cards, periods, breaks, rooms and constraints. The generator first creates a draft and then applies constraints according to the selected mode.</div>
<form method='post' action='/app/timetable/generate/new' class='tt-form' style='margin-top:12px'>
<label><span class='tt-label'>Class filter (optional)</span><select class='tt-field' name='class_id'><option value=''>All classes</option>{opts}</select></label>
<label><span class='tt-label'>Mode</span><select class='tt-field' name='mode'><option value='draft'>Draft</option><option value='relaxed' {'selected' if relaxation=='relaxed' else ''}>Allow relaxation</option><option value='strict' {'selected' if relaxation=='strict' else ''}>Strict</option></select></label>
<label><span class='tt-label'>Complexity</span><select class='tt-field' name='complexity'><option value='normal' {'selected' if complexity=='normal' else ''}>Normal</option><option value='large' {'selected' if complexity=='large' else ''}>Large</option><option value='huge' {'selected' if complexity=='huge' else ''}>Huge</option></select></label>
<label class='tt-check'><input type='checkbox' name='replace_existing' value='1' checked> Replace unlocked generated placements</label>
<div><button class='tt-btn'>🚀 Generate</button></div></form></div>
<div class='tt-grid'><div class='tt-stat'><b>{int(lesson_count)}</b>Lesson cards</div><div class='tt-stat'><b>{int(slot_count)}</b>Placed lesson cards</div><div class='tt-stat'><b>{escape(relaxation.title())}</b>Default mode</div></div>"""


def _verify(con, sid):
    lessons=con.execute("SELECT id,lessons_per_week,duration FROM timetable_lessons WHERE school_id=?", (sid,)).fetchall()
    placements=con.execute("SELECT lesson_id FROM timetable_slots WHERE school_id=?", (sid,)).fetchall()
    placed_counts={}
    for r in placements:
        lid=int(r["lesson_id"])
        placed_counts[lid]=placed_counts.get(lid,0)+1
    issues=[]
    for l in lessons:
        lid=int(l["id"])
        required=int(l["lessons_per_week"] or 0)
        actual=int(placed_counts.get(lid,0))
        missing=max(0,required-actual)
        if missing:
            issues.append(f"Lesson card {lid}: {actual} of {required} weekly placements made; {missing} missing.")
    # Hard collision checks.
    rows=con.execute("""SELECT s.*,l.class_id,l.teacher_id,l.room_id,l.duration,l.subject_id
        FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id
        WHERE s.school_id=? ORDER BY s.day_name,s.period_no""",(sid,)).fetchall()
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            if a["day_name"]!=b["day_name"]: continue
            a_end=int(a["period_no"])+int(a["duration"])-1
            b_end=int(b["period_no"])+int(b["duration"])-1
            if a_end < int(b["period_no"]) or b_end < int(a["period_no"]): continue
            a_classes={int(x["class_id"]) for x in con.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,a["lesson_id"])).fetchall()} or {int(a["class_id"])}
            b_classes={int(x["class_id"]) for x in con.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,b["lesson_id"])).fetchall()} or {int(b["class_id"])}
            a_teachers={int(x["teacher_id"]) for x in con.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,a["lesson_id"])).fetchall()} or ({int(a["teacher_id"])} if a["teacher_id"] else set())
            b_teachers={int(x["teacher_id"]) for x in con.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,b["lesson_id"])).fetchall()} or ({int(b["teacher_id"])} if b["teacher_id"] else set())
            if a_classes.intersection(b_classes):
                issues.append(f"Class/stream conflict on {a['day_name']} period {a['period_no']}: lesson {a['lesson_id']} / {b['lesson_id']}.")
            if a_teachers.intersection(b_teachers):
                issues.append(f"Teacher conflict on {a['day_name']} period {a['period_no']}: lesson {a['lesson_id']} / {b['lesson_id']}.")
            if a["room_id"] and b["room_id"] and a["room_id"]==b["room_id"]:
                issues.append(f"Room conflict on {a['day_name']} period {a['period_no']}: lesson {a['lesson_id']} / {b['lesson_id']}.")
    return f"""<div class='tt-card'><h2>✅ Timetable Verification</h2><div class='tt-muted'>Checks incomplete cards, class conflicts, teacher conflicts and room conflicts before publication.</div>
<div class='tt-stat' style='margin:12px 0'><b>{len(issues)}</b>{'Issues found' if issues else 'No basic conflicts found'}</div>
<div class='tt-scroll'><table class='tt-table'><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{''.join(f"<tr><td>⚠️</td><td>{escape(x)}</td></tr>" for x in issues) if issues else '<tr><td>✅</td><td>Verification passed for the current basic checks.</td></tr>'}</tbody></table></div></div>"""


def _class_grid_data(con, sid, class_id=None):
    """Return timetable placements keyed by class, day and period for aSc-style grids."""
    classes = con.execute(
        "SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",
        (sid,)
    ).fetchall()
    periods = con.execute(
        "SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",
        (sid,)
    ).fetchall()
    days = [r["name"] for r in con.execute(
        "SELECT * FROM timetable_days WHERE school_id=? AND enabled=1 ORDER BY day_no",
        (sid,)
    ).fetchall()]
    breaks = con.execute(
        "SELECT * FROM timetable_breaks WHERE school_id=? ORDER BY start_time,id",
        (sid,)
    ).fetchall()

    rows = con.execute("""SELECT s.*,l.class_id,l.subject_id,l.teacher_id,l.room_id,l.duration,
        c.name class_name,c.stream,sub.name subject,t.name teacher,r.name room
        FROM timetable_slots s
        JOIN timetable_lessons l ON l.id=s.lesson_id
        JOIN classes c ON c.id=l.class_id
        JOIN subjects sub ON sub.id=l.subject_id
        LEFT JOIN teachers t ON t.id=l.teacher_id
        LEFT JOIN timetable_rooms r ON r.id=s.room_id
        WHERE s.school_id=?
        ORDER BY s.day_name,s.period_no""", (sid,)).fetchall()

    lesson_classes = {}
    for row in rows:
        lid = int(row["lesson_id"])
        lesson_classes[lid] = {
            int(x["class_id"]) for x in con.execute(
                "SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",
                (sid, lid)
            ).fetchall()
        } or {int(row["class_id"])}

    grids = {}
    selected_ids = {int(class_id)} if class_id else {int(c["id"]) for c in classes}
    for row in rows:
        lid = int(row["lesson_id"])
        for cid in lesson_classes.get(lid, {int(row["class_id"])}):
            if cid not in selected_ids:
                continue
            grids.setdefault(cid, {})[(str(row["day_name"]), int(row["period_no"]))] = row

    return classes, periods, days, breaks, grids


def _class_grid_html(class_row, periods, days, breaks, grid, show_title=True):
    """Render the saved bell schedule exactly: days vertical, periods/breaks horizontal."""
    class_label = f"{class_row['name']}{(' — '+str(class_row['stream'])) if class_row['stream'] else ''}"

    # Build the horizontal school-day timeline from the ACTUAL saved period and
    # break times. Never derive breaks from the default period length.
    period_items = [
        ("period", _time_to_min(str(p["start_time"])), _time_to_min(str(p["end_time"])), p)
        for p in periods
    ]
    break_items = [
        ("break", _time_to_min(str(b["start_time"])), _time_to_min(str(b["end_time"])), b)
        for b in breaks
    ]
    break_ranges = [(x[1], x[2]) for x in break_items]

    # A saved break is a first-class timeline item. If a school accidentally
    # configured a break overlapping a period, the break wins visually so the
    # output never hides the school's saved break.
    visible_periods = [
        x for x in period_items
        if not any(x[1] < be and x[2] > bs for bs, be in break_ranges)
    ]
    visible_timeline = sorted(
        visible_periods + break_items,
        key=lambda x: (x[1], 0 if x[0] == "period" else 1, x[2])
    )

    head = "<tr><th class='tt-day-col'>DAY</th>" + "".join(
        (
            f"<th class='tt-break-col'>☕<br><b>{escape(str(x[3]['name']))}</b>"
            f"<br><small>{escape(str(x[3]['start_time']))}-{escape(str(x[3]['end_time']))}</small></th>"
            if x[0] == "break" else
            f"<th>P{int(x[3]['period_no'])}<br><small>{escape(str(x[3]['start_time']))}-{escape(str(x[3]['end_time']))}</small></th>"
        )
        for x in visible_timeline
    ) + "</tr>"

    body = []
    for day in days:
        row_cells = [f"<th class='tt-day'>{escape(str(day)).upper()}</th>"]
        for kind, st, et, item in visible_timeline:
            if kind == "break":
                row_cells.append(
                    f"<td class='tt-break'>☕<br><b>{escape(str(item['name']))}</b><br>"
                    f"<small>{escape(str(item['start_time']))}-{escape(str(item['end_time']))}</small></td>"
                )
                continue

            pno = int(item["period_no"])
            lesson = grid.get((day, pno))
            if not lesson:
                row_cells.append("<td class='tt-empty'>—</td>")
                continue

            duration = max(1, int(lesson["duration"] or 1))
            # A lesson placement stores its START period plus its duration;
            # there is intentionally no duplicate slot row for the second
            # period of a double/triple lesson. Render the saved duration as
            # one horizontal block across the following actual period columns.
            span = 1
            current_idx = next(
                (idx for idx, x in enumerate(visible_timeline)
                 if x[0] == "period" and int(x[3]["period_no"]) == pno),
                -1
            )
            if current_idx >= 0:
                for next_idx in range(current_idx + 1, min(current_idx + duration, len(visible_timeline))):
                    next_item = visible_timeline[next_idx]
                    # A configured break is a hard boundary; a double lesson
                    # may not visually or logically pass through it.
                    if next_item[0] != "period":
                        break
                    span += 1

            teachers = str(lesson["teacher"] or "")
            room = str(lesson["room"] or "")
            duration_note = f"<br><small>×{span} periods</small>" if span > 1 else ""
            row_cells.append(
                f"<td class='tt-lesson' colspan='{span}'>"
                f"<b>{escape(str(lesson['subject']))}</b>"
                f"<br><span>{escape(teachers)}</span>"
                f"{('<br><small>'+escape(room)+'</small>') if room else ''}"
                f"{duration_note}</td>"
            )
        body.append("<tr>" + "".join(row_cells) + "</tr>")

    title = f"<h3>🏫 {escape(class_label)}</h3>" if show_title else ""
    return (
        f"<div class='tt-class-sheet'>{title}"
        f"<div class='tt-scroll'><table class='tt-week tt-class-grid'>{head}{''.join(body)}</table></div></div>"
    )


def _timetable(request, con, sid):
    class_filter = request.query_params.get("class_id", "")
    teacher_filter = request.query_params.get("teacher_id", "")
    room_filter = request.query_params.get("room_id", "")

    classes, periods, days, breaks, grids = _class_grid_data(
        con, sid, int(class_filter) if str(class_filter).isdigit() else None
    )

    if str(teacher_filter).isdigit() or str(room_filter).isdigit():
        where = ["s.school_id=?"]
        params = [sid]
        if str(teacher_filter).isdigit():
            where.append("(l.teacher_id=? OR l.id IN (SELECT lesson_id FROM timetable_lesson_teachers WHERE school_id=? AND teacher_id=?))")
            params.extend([int(teacher_filter), sid, int(teacher_filter)])
        if str(room_filter).isdigit():
            where.append("s.room_id=?")
            params.append(int(room_filter))
        filtered = con.execute(
            """SELECT DISTINCT s.lesson_id FROM timetable_slots s
               JOIN timetable_lessons l ON l.id=s.lesson_id
               WHERE """ + " AND ".join(where),
            params
        ).fetchall()
        allowed_lesson_ids = {int(x["lesson_id"]) for x in filtered}
        for cid, grid in grids.items():
            grids[cid] = {
                key: row for key, row in grid.items()
                if int(row["lesson_id"]) in allowed_lesson_ids
            }

    teacher_opts = "".join(
        f"<option value='{t['id']}' {'selected' if str(teacher_filter)==str(t['id']) else ''}>{escape(str(t['name']))}</option>"
        for t in con.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    )
    room_opts = "".join(
        f"<option value='{r['id']}' {'selected' if str(room_filter)==str(r['id']) else ''}>{escape(str(r['name']))}</option>"
        for r in con.execute("SELECT id,name FROM timetable_rooms WHERE school_id=? AND active=1 ORDER BY name",(sid,)).fetchall()
    )
    class_opts = "".join(
        f"<option value='{c['id']}' {'selected' if str(class_filter)==str(c['id']) else ''}>"
        f"{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>"
        for c in classes
    )

    sheets = [
        _class_grid_html(c, periods, days, breaks, grids[int(c["id"])])
        for c in classes if int(c["id"]) in grids
    ]

    return f"""<div class='tt-card'><h2>🗓️ Class Timetable</h2>
<div class='tt-muted'>aSc-style class view: days run vertically and the school's saved periods and breaks run horizontally using their exact configured bell times. Combined classes appear in every participating class timetable.</div>
<form method='get' class='tt-form' style='margin-top:12px'>
<input type='hidden' name='tab' value='timetable'>
<label><span class='tt-label'>Class / Stream</span><select class='tt-field' name='class_id'><option value=''>All classes</option>{class_opts}</select></label>
<label><span class='tt-label'>Teacher filter</span><select class='tt-field' name='teacher_id'><option value=''>All teachers</option>{teacher_opts}</select></label>
<label><span class='tt-label'>Room filter</span><select class='tt-field' name='room_id'><option value=''>All rooms</option>{room_opts}</select></label>
<div><button class='tt-btn'>🔎 View</button></div>
</form>
<div style='margin-top:14px'>{''.join(sheets) or "<div class='tt-notice bad'>No timetable placements yet. Generate the timetable first.</div>"}</div>
<div style='margin-top:12px'><a class='tt-btn' href='/app/timetable?tab=generate'>🚀 Generate / Regenerate</a> <a class='tt-btn alt' href='/app/timetable?tab=verify'>✅ Verify</a> <a class='tt-btn alt' href='/app/timetable?tab=print'>🖨️ Print</a></div>
</div>"""


def _print_view(con, sid):
    classes, periods, days, breaks, grids = _class_grid_data(con, sid)
    sheets = [
        _class_grid_html(c, periods, days, breaks, grids[int(c["id"])])
        for c in classes if int(c["id"]) in grids
    ]

    return f"""<div class='tt-card'><h2>🖨️ Print Class Timetables</h2>
<div class='tt-muted'>Every class/stream is printed as a separate timetable using the school's exact saved period and break times, with days vertically and periods horizontally.</div>
<div class='no-print' style='margin:12px 0'><button class='tt-btn' onclick='window.print()'>🖨️ Open Print Preview</button></div>
<div class='tt-print-sheets'>{''.join(sheets) or '<div class="tt-notice bad">No timetable placements yet.</div>'}</div></div>"""


@router.post("/app/timetable/setup/save")
def timetable_setup_save(request: Request, complexity: str=Form(...), relaxation: str=Form(...), days: list[str]=Form([])):
    sid, con, response = _guard(request, "timetable.edit")
    if response: return response
    try:
        if complexity not in ("normal","large","huge"): complexity="normal"
        if relaxation not in ("draft","relaxed","strict"): relaxation="relaxed"
        cur=con.cursor()
        cur.execute("UPDATE timetable_manager_settings SET days_json=?,complexity=?,relaxation=? WHERE school_id=?",
                    (json.dumps(days or list(DEFAULT_DAYS)),complexity,relaxation,sid))
        cur.execute("UPDATE timetable_days SET enabled=0 WHERE school_id=?",(sid,))
        for d in days:
            if d in DAYS:
                cur.execute("UPDATE timetable_days SET enabled=1 WHERE school_id=? AND name=?",(sid,d))
        con.commit()
        return RedirectResponse("/app/timetable?tab=setup&msg=Timetable+setup+saved",303)
    finally: con.close()


@router.post("/app/timetable/periods/settings")
def timetable_period_settings(request: Request, periods_per_day:int=Form(...), period_minutes:int=Form(...), periods_per_week:int=Form(...)):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        if not (1<=periods_per_day<=12 and 20<=period_minutes<=180 and 1<=periods_per_week<=84):
            return RedirectResponse("/app/timetable?tab=periods&error=Invalid+period+settings",303)
        cur=con.cursor()
        cur.execute("INSERT INTO timetable_settings(school_id,periods_per_day,period_minutes,periods_per_week) VALUES(?,?,?,?) ON CONFLICT(school_id) DO UPDATE SET periods_per_day=excluded.periods_per_day,period_minutes=excluded.period_minutes,periods_per_week=excluded.periods_per_week RETURNING school_id",(sid,periods_per_day,period_minutes,periods_per_week))
        cur.execute("DELETE FROM timetable_periods WHERE school_id=? AND period_no>?",(sid,periods_per_day))
        base=datetime.strptime("08:00","%H:%M")
        for n in range(1,periods_per_day+1):
            p=cur.execute("SELECT id FROM timetable_periods WHERE school_id=? AND period_no=?",(sid,n)).fetchone()
            if not p:
                st=(base+timedelta(minutes=(n-1)*period_minutes)).strftime("%H:%M");et=(base+timedelta(minutes=n*period_minutes)).strftime("%H:%M")
                cur.execute("INSERT INTO timetable_periods(school_id,period_no,start_time,end_time) VALUES(?,?,?,?)",(sid,n,st,et))
        con.commit()
        return RedirectResponse("/app/timetable?tab=periods&msg=Period+settings+saved",303)
    finally: con.close()


@router.post("/app/timetable/periods/save")
async def timetable_periods_save(request: Request):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        form=await request.form();cur=con.cursor()
        periods=cur.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()

        # Validate the complete submitted timetable first, then update it.
        # Updating one period before validating the next used to make a
        # legitimate shift (for example 08:20-09:00, 09:00-09:40) look like
        # an overlap because the database contained a mixture of old and new
        # times during the loop.
        submitted=[]
        for p in periods:
            st=str(form.get(f"start_{p['period_no']}") or "").strip()
            et=str(form.get(f"end_{p['period_no']}") or "").strip()
            if not st or not et or et<=st:
                return RedirectResponse(f"/app/timetable?tab=periods&error=Invalid+time+for+period+{p['period_no']}",303)
            submitted.append((int(p["period_no"]),st,et,p["id"]))

        for i,(pno,st,et,pid) in enumerate(submitted):
            for other_no,other_st,other_et,other_id in submitted:
                if pno == other_no:
                    continue
                # Touching at the exact boundary is allowed; actual overlap
                # exists only when one period starts before the other ends and
                # ends after the other starts.
                if st < other_et and et > other_st:
                    return RedirectResponse(f"/app/timetable?tab=periods&error=Period+{pno}+overlaps+period+{other_no}",303)

        for pno,st,et,pid in submitted:
            cur.execute("UPDATE timetable_periods SET start_time=?,end_time=? WHERE id=? AND school_id=?",(st,et,pid,sid))

        con.commit();return RedirectResponse("/app/timetable?tab=periods&msg=Period+times+saved",303)
    finally:con.close()


@router.post("/app/timetable/break/save")
def timetable_break_save(request: Request,name:str=Form(...),start_time:str=Form(...),end_time:str=Form(...)):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        if not name.strip() or not start_time or not end_time or end_time<=start_time:return RedirectResponse("/app/timetable?tab=periods&error=Invalid+break",303)
        cur=con.cursor(); overlap=cur.execute("SELECT id FROM timetable_breaks WHERE school_id=? AND start_time<? AND end_time>? LIMIT 1",(sid,end_time,start_time)).fetchone()
        if overlap:return RedirectResponse("/app/timetable?tab=periods&error=Break+overlaps+another+break",303)
        cur.execute("INSERT INTO timetable_breaks(school_id,name,start_time,end_time) VALUES(?,?,?,?)",(sid,name.strip(),start_time,end_time));con.commit()
        return RedirectResponse("/app/timetable?tab=periods&msg=Break+saved",303)
    finally:con.close()


@router.post("/app/timetable/break/delete/{rid}")
def timetable_break_delete(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        con.execute("DELETE FROM timetable_breaks WHERE id=? AND school_id=?",(rid,sid));con.commit()
        return RedirectResponse("/app/timetable?tab=periods&msg=Break+deleted",303)
    finally:con.close()


@router.post("/app/timetable/room/save")
def timetable_room_save(request:Request,name:str=Form(...),code:str=Form(""),capacity:int=Form(0),room_type:str=Form("")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        con.execute("INSERT INTO timetable_rooms(school_id,name,code,capacity,room_type) VALUES(?,?,?,?,?)",(sid,name.strip(),code.strip(),capacity or None,room_type.strip()));con.commit()
        return RedirectResponse("/app/timetable?tab=rooms&msg=Room+saved",303)
    finally:con.close()


@router.post("/app/timetable/room/delete/{rid}")
def timetable_room_delete(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        con.execute("DELETE FROM timetable_rooms WHERE id=? AND school_id=?",(rid,sid));con.commit()
        return RedirectResponse("/app/timetable?tab=rooms&msg=Room+deleted",303)
    finally:con.close()


@router.post("/app/timetable/lesson/save")
async def timetable_lesson_save(request:Request):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        form=await request.form();cur=con.cursor()
        lesson_id=int(str(form.get("lesson_id") or 0)) if str(form.get("lesson_id") or "").isdigit() else 0
        class_ids=[]
        for v in form.getlist("class_ids"):
            if str(v).isdigit() and int(v) not in class_ids: class_ids.append(int(v))
        teacher_ids=[]
        for v in form.getlist("teacher_ids"):
            if str(v).isdigit() and int(v) not in teacher_ids: teacher_ids.append(int(v))
        subject_id=int(str(form.get("subject_id") or 0)) if str(form.get("subject_id") or "").isdigit() else 0
        lessons_per_week=int(str(form.get("lessons_per_week") or 0) or 0)
        duration=int(str(form.get("duration") or 1) or 1)
        cycle=str(form.get("cycle") or "Every week")
        group_name=str(form.get("group_name") or "").strip()
        notes=str(form.get("notes") or "").strip()
        locked=1 if form.get("locked") else 0
        room_value=str(form.get("room_id") or "")
        room=int(room_value) if room_value.isdigit() else None
        if not class_ids or not subject_id or not 1<=lessons_per_week<=30 or not 1<=duration<=3:
            return RedirectResponse("/app/timetable?tab=lessons&error=Select+at+least+one+class+and+valid+lesson+details",303)
        valid_classes=cur.execute("SELECT id FROM classes WHERE school_id=? AND id IN ("+(",".join(["?"]*len(class_ids)))+")",(sid,*class_ids)).fetchall()
        valid_class_ids=[int(x["id"]) for x in valid_classes]
        valid_subject=cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
        valid_teachers=cur.execute("SELECT id FROM teachers WHERE school_id=? AND id IN ("+(",".join(["?"]*len(teacher_ids)))+")",(sid,*teacher_ids)).fetchall() if teacher_ids else []
        valid_teacher_ids=[int(x["id"]) for x in valid_teachers]
        if len(valid_class_ids)!=len(class_ids) or not valid_subject or len(valid_teacher_ids)!=len(teacher_ids):
            return RedirectResponse("/app/timetable?tab=lessons&error=Invalid+class%2C+subject+or+teacher+selection",303)
        if room and not cur.execute("SELECT id FROM timetable_rooms WHERE id=? AND school_id=?",(room,sid)).fetchone(): room=None
        primary_class=valid_class_ids[0]
        primary_teacher=valid_teacher_ids[0] if valid_teacher_ids else None
        vals=(primary_class,subject_id,primary_teacher,room,group_name,lessons_per_week,duration,cycle if cycle in ("Every week","Alternate weeks") else "Every week",locked,room,notes)
        if lesson_id:
            cur.execute("""UPDATE timetable_lessons SET class_id=?,subject_id=?,teacher_id=?,room_id=?,group_name=?,lessons_per_week=?,duration=?,cycle=?,locked=?,preferred_room=?,notes=? WHERE id=? AND school_id=?""",vals+(lesson_id,sid))
            cur.execute("DELETE FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,lesson_id))
            cur.execute("DELETE FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,lesson_id))
        else:
            cur.execute("""INSERT INTO timetable_lessons(school_id,class_id,subject_id,teacher_id,room_id,group_name,lessons_per_week,duration,cycle,locked,preferred_room,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(sid,)+vals)
            lesson_id=cur.lastrowid
        for cid in valid_class_ids: cur.execute("INSERT INTO timetable_lesson_classes(school_id,lesson_id,class_id) VALUES(?,?,?)",(sid,lesson_id,cid))
        for tid in valid_teacher_ids: cur.execute("INSERT INTO timetable_lesson_teachers(school_id,lesson_id,teacher_id) VALUES(?,?,?)",(sid,lesson_id,tid))
        con.commit();return RedirectResponse("/app/timetable?tab=lessons&msg=Lesson+card+saved",303)
    finally:con.close()
@router.post("/app/timetable/lesson/delete/{rid}")
def timetable_lesson_delete(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        cur=con.cursor();cur.execute("DELETE FROM timetable_slots WHERE lesson_id=? AND school_id=? AND locked=0",(rid,sid));cur.execute("DELETE FROM timetable_lessons WHERE id=? AND school_id=?",(rid,sid));con.commit()
        return RedirectResponse("/app/timetable?tab=lessons&msg=Lesson+card+deleted",303)
    finally:con.close()


@router.post("/app/timetable/availability/save")
async def timetable_availability_save(request:Request,kind:str=Form(...),resource_id:int=Form(...)):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        if kind not in ("teacher","subject"):
            return RedirectResponse("/app/timetable?tab=availability&error=Invalid+resource+type",303)
        valid_table="teachers" if kind=="teacher" else "subjects"
        if not con.execute(f"SELECT id FROM {valid_table} WHERE school_id=? AND id=?",(sid,resource_id)).fetchone():
            return RedirectResponse("/app/timetable?tab=availability&error=Invalid+resource",303)
        days=[str(r["name"]) for r in con.execute("SELECT name FROM timetable_days WHERE school_id=? AND enabled=1 ORDER BY day_no",(sid,)).fetchall()]
        periods=[int(r["period_no"]) for r in con.execute("SELECT period_no FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()]
        allowed={(d,p) for d in days for p in periods}
        selected=set()
        form=await request.form()
        for raw in form.getlist("slot"):
            parts=str(raw).split("|",1)
            if len(parts)==2 and parts[0] in days and parts[1].isdigit() and (parts[0],int(parts[1])) in allowed:
                selected.add((parts[0],int(parts[1])))
        cur=con.cursor()
        cur.execute("DELETE FROM timetable_availability WHERE school_id=? AND resource_type=? AND resource_id=?",(sid,kind,resource_id))
        for d,p in allowed:
            if (d,p) not in selected:
                cur.execute("INSERT INTO timetable_availability(school_id,resource_type,resource_id,day_name,period_no,allowed) VALUES(?,?,?,?,?,0)",(sid,kind,resource_id,d,p))
        con.commit()
        return RedirectResponse(f"/app/timetable?tab=availability&kind={kind}&resource_id={resource_id}&msg=Availability+saved",303)
    finally: con.close()

@router.post("/app/timetable/constraint/save")
def timetable_constraint_save(request:Request,scope:str=Form(...),constraint_type:str=Form(...),target_id:str=Form(""),value:str=Form(""),priority:str=Form("preferred")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        target=int(target_id) if str(target_id).isdigit() else None
        if priority not in ("preferred","important","strict"):priority="preferred"
        con.execute("INSERT INTO timetable_constraints(school_id,scope,constraint_type,target_id,value,priority,enabled) VALUES(?,?,?,?,?,?,1)",(sid,scope.strip(),constraint_type.strip(),target,value.strip(),priority));con.commit()
        return RedirectResponse("/app/timetable?tab=constraints&msg=Constraint+saved",303)
    finally:con.close()


@router.post("/app/timetable/constraint/delete/{rid}")
def timetable_constraint_delete(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        con.execute("DELETE FROM timetable_constraints WHERE id=? AND school_id=?",(rid,sid));con.commit();return RedirectResponse("/app/timetable?tab=constraints&msg=Constraint+deleted",303)
    finally:con.close()


def _time_to_min(value):
    try:
        h,m=map(int,str(value).split(":")[:2]);return h*60+m
    except Exception:return 0


def _overlaps(a,b):
    return int(a["period_no"]) <= int(b["period_no"])+int(b.get("duration",1))-1 and int(b["period_no"]) <= int(a["period_no"])+int(a.get("duration",1))-1


def _constraint_maps(cur,sid):
    out={}
    for r in cur.execute("SELECT * FROM timetable_constraints WHERE school_id=? AND enabled=1",(sid,)).fetchall():
        out.setdefault(str(r["constraint_type"]),[]).append(r)
    return out


def _is_available_slot(cur,sid,lesson,day,pno,duration,occupied,rooms,strict):
    periods=cur.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()
    pmap={int(p["period_no"]):p for p in periods}
    breaks=cur.execute("SELECT * FROM timetable_breaks WHERE school_id=?",(sid,)).fetchall()
    for x in range(pno,pno+duration):
        if x not in pmap:return False,None
        st=str(pmap[x]["start_time"]);et=str(pmap[x]["end_time"])
        if any(_time_to_min(st)<_time_to_min(str(b["end_time"])) and _time_to_min(et)>_time_to_min(str(b["start_time"])) for b in breaks):return False,None
    for other in occupied:
        if other["day_name"]!=day:continue
        if _overlaps({"period_no":pno,"duration":duration},other):
            lesson_classes={int(x["class_id"]) for x in cur.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,lesson["id"])).fetchall()} or {int(lesson["class_id"])}
            lesson_teachers={int(x["teacher_id"]) for x in cur.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,lesson["id"])).fetchall()} or ({int(lesson["teacher_id"])} if lesson["teacher_id"] else set())
            other_classes={int(x["class_id"]) for x in cur.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,other["lesson_id"])).fetchall()} or {int(other["class_id"])}
            other_teachers={int(x["teacher_id"]) for x in cur.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,other["lesson_id"])).fetchall()} or ({int(other["teacher_id"])} if other["teacher_id"] else set())
            if lesson_classes.intersection(other_classes):return False,None
            if lesson_teachers.intersection(other_teachers):return False,None
    room_id=lesson["room_id"]
    if room_id:
        for other in occupied:
            if other["day_name"]==day and other["room_id"]==room_id and _overlaps({"period_no":pno,"duration":duration},other):return False,None
    elif rooms:
        for room in rooms:
            rid=int(room["id"])
            if all(not (o["day_name"]==day and o["room_id"]==rid and _overlaps({"period_no":pno,"duration":duration},o)) for o in occupied):
                room_id=rid;break
    return True,room_id


def _generate_algorithm(cur,sid,class_filter,mode,complexity,replace_existing):
    """Generate a complete timetable automatically, using retries/backtracking-like restarts.

    The generator keeps hard collisions impossible, but in relaxed/draft mode it can
    progressively relax availability/preferred constraints when those rules would
    otherwise leave requirements unplaced. This makes generation self-solving while
    preserving explicit hard class/teacher conflicts.
    """
    days=[str(r["name"]) for r in cur.execute("SELECT name FROM timetable_days WHERE school_id=? AND enabled=1 ORDER BY day_no",(sid,)).fetchall()]
    if not days: days=list(DEFAULT_DAYS)
    periods=[dict(r) for r in cur.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()]
    rooms=[dict(r) for r in cur.execute("SELECT * FROM timetable_rooms WHERE school_id=? AND active=1 ORDER BY id",(sid,)).fetchall()]
    lesson_sql="SELECT * FROM timetable_lessons WHERE school_id=?"
    params=(sid,)
    if class_filter:
        lesson_sql+=" AND (class_id=? OR id IN (SELECT lesson_id FROM timetable_lesson_classes WHERE school_id=? AND class_id=?))"
        params=(sid,class_filter,sid,class_filter)
    lessons=[dict(r) for r in cur.execute(lesson_sql+" ORDER BY duration DESC,lessons_per_week DESC,id",params).fetchall()]
    constraints=_constraint_maps(cur,sid)
    blocked_teacher={(str(r["day_name"]),int(r["period_no"]),int(r["resource_id"])) for r in cur.execute("SELECT day_name,period_no,resource_id FROM timetable_availability WHERE school_id=? AND resource_type='teacher' AND allowed=0",(sid,)).fetchall()}
    blocked_subject={(str(r["day_name"]),int(r["period_no"]),int(r["resource_id"])) for r in cur.execute("SELECT day_name,period_no,resource_id FROM timetable_availability WHERE school_id=? AND resource_type='subject' AND allowed=0",(sid,)).fetchall()}

    if replace_existing:
        if class_filter:
            cur.execute("DELETE FROM timetable_slots WHERE school_id=? AND locked=0 AND lesson_id IN (SELECT id FROM timetable_lessons WHERE school_id=? AND class_id=?)",(sid,sid,class_filter))
        else:
            cur.execute("DELETE FROM timetable_slots WHERE school_id=? AND locked=0",(sid,))

    base=[dict(r) for r in cur.execute("""SELECT s.*,l.class_id,l.teacher_id,l.room_id,l.duration,l.subject_id
        FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id WHERE s.school_id=?""",(sid,)).fetchall()]
    lesson_classes={}
    lesson_teachers={}
    for l in lessons:
        lid=int(l["id"])
        lesson_classes[lid]={int(x["class_id"]) for x in cur.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,lid)).fetchall()} or {int(l["class_id"])}
        lesson_teachers[lid]={int(x["teacher_id"]) for x in cur.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,lid)).fetchall()} or ({int(l["teacher_id"])} if l["teacher_id"] else set())

    breaks=[dict(r) for r in cur.execute("SELECT * FROM timetable_breaks WHERE school_id=?",(sid,)).fetchall()]
    pmap={int(p["period_no"]):p for p in periods}

    def fits_break(pno,duration):
        for x in range(pno,pno+duration):
            if x not in pmap:return False
            st=_time_to_min(pmap[x]["start_time"]); et=_time_to_min(pmap[x]["end_time"])
            for b in breaks:
                if st<_time_to_min(str(b["end_time"])) and et>_time_to_min(str(b["start_time"])):
                    return False
        return True

    def room_for(lesson,day,pno,duration,occ):
        fixed=lesson.get("room_id")
        if fixed:
            if any(o["day_name"]==day and o.get("room_id") and int(o["room_id"])==int(fixed) and _overlaps({"period_no":pno,"duration":duration},o) for o in occ):
                return None
            return int(fixed)
        for room in rooms:
            rid=int(room["id"])
            if not any(o["day_name"]==day and o.get("room_id") and int(o["room_id"])==rid and _overlaps({"period_no":pno,"duration":duration},o) for o in occ):
                return rid
        # A room is optional in DaviSchool; allow placement without one when none are configured.
        return None if rooms else None

    def candidate(lesson,day,pno,occ,enforce_availability=True,enforce_preferred=True):
        lid=int(lesson["id"]); duration=max(1,int(lesson.get("duration") or 1))
        if not fits_break(pno,duration): return None
        classes=lesson_classes[lid]; teachers=lesson_teachers[lid]
        for o in occ:
            if o["day_name"]!=day or not _overlaps({"period_no":pno,"duration":duration},o): continue
            if classes.intersection(lesson_classes.get(int(o["lesson_id"]),{int(o["class_id"])})): return None
            if teachers.intersection(lesson_teachers.get(int(o["lesson_id"]),({int(o["teacher_id"])} if o.get("teacher_id") else set()))): return None
        if enforce_availability:
            for xp in range(pno,pno+duration):
                if any((day,xp,t) in blocked_teacher for t in teachers): return None
                if (day,xp,int(lesson["subject_id"])) in blocked_subject: return None
        if enforce_preferred:
            for cdef in constraints.get("Teacher max lessons/day",[]):
                if cdef["target_id"] and teachers and int(cdef["target_id"]) in teachers:
                    lim=int(cdef["value"] or 0)
                    if lim and sum(1 for o in occ if o["day_name"]==day and lesson_teachers.get(int(o["lesson_id"]),set()) & teachers)>=lim: return None
            for cdef in constraints.get("Class max lessons/day",[]):
                if cdef["target_id"] and any(int(cdef["target_id"])==x for x in classes):
                    lim=int(cdef["value"] or 0)
                    if lim and sum(1 for o in occ if o["day_name"]==day and lesson_classes.get(int(o["lesson_id"]),set()) & classes)>=lim: return None
        room=room_for(lesson,day,pno,duration,occ)
        # A room is optional unless the Lesson Card explicitly requires one.
        # If every configured room is occupied, still allow an "Any available room"
        # lesson to be scheduled without assigning a room. This prevents room
        # configuration from blocking the entire timetable.
        if lesson.get("room_id") and room is None:return None
        return room

    # Several deterministic restarts prevent a greedy early choice from blocking
    # the rest of the school. More constrained/longer cards are placed first.
    orders=[]
    orders.append(sorted(lessons,key=lambda l:(-int(l.get("duration") or 1),-int(l.get("lessons_per_week") or 0),int(l["id"]))))
    orders.append(sorted(lessons,key=lambda l:(-len(lesson_classes[int(l["id"])]),-len(lesson_teachers[int(l["id"])]),-int(l.get("duration") or 1),int(l["id"]))))
    orders.append(sorted(lessons,key=lambda l:(-int(l.get("lessons_per_week") or 0),-int(l.get("duration") or 1),int(l["id"]))))
    orders.append(list(reversed(orders[0])))
    orders.append(sorted(lessons,key=lambda l:(int(l["id"])%5,-int(l.get("duration") or 1),-int(l.get("lessons_per_week") or 0))))
    best=None
    for order_index,order in enumerate(orders):
        occ=[dict(x) for x in base]
        placements=[]
        unplaced=[]
        # In relaxed/draft generation, start strict and automatically fall back
        # to availability/constraint relaxation only for cards that cannot fit.
        for lesson in order:
            lid=int(lesson["id"]); need=max(0,int(lesson.get("lessons_per_week") or 0)-sum(1 for o in occ if int(o["lesson_id"])==lid))
            if int(lesson.get("locked") or 0) and need<=0: continue
            for _ in range(need):
                found=None
                candidate_modes=[(True,True)]
                if mode!="strict":
                    candidate_modes += [(True,False),(False,True),(False,False)]
                for av_ok,pref_ok in candidate_modes:
                    candidates=[]
                    for day in days:
                        for p in periods:
                            pno=int(p["period_no"])
                            room=candidate(lesson,day,pno,occ,av_ok,pref_ok)
                            if room is not None or not lesson.get("room_id"):
                                # Score spreads lessons across the week and avoids
                                # repeatedly using the first available period.
                                same_day=sum(1 for o in occ if o["day_name"]==day and lesson_classes[lid] & lesson_classes.get(int(o["lesson_id"]),set()))
                                same_subject=sum(1 for o in occ if o["day_name"]==day and int(o.get("subject_id") or 0)==int(lesson["subject_id"]) and lesson_classes[lid] & lesson_classes.get(int(o["lesson_id"]),set()))
                                same_period=sum(1 for o in occ if int(o.get("period_no") or 0)==int(p["period_no"]) and lesson_classes[lid] & lesson_classes.get(int(o["lesson_id"]),set()))
                                # Spread a class across the week and across periods
                                # instead of repeatedly selecting Period 1.
                                score=(same_day*100+same_period*20+same_subject*15+days.index(day),int(p["period_no"]))
                                candidates.append((score,day,p,room))
                    if candidates:
                        candidates.sort(key=lambda x:x[0])
                        _,day,p,room=candidates[0]
                        row={"lesson_id":lid,"class_id":lesson["class_id"],"teacher_id":lesson["teacher_id"],"room_id":room,"day_name":day,"period_no":int(p["period_no"]),"duration":max(1,int(lesson.get("duration") or 1))}
                        occ.append(row); placements.append(row); found=True; break
                if not found:
                    unplaced.append((lid,"no collision-free period after automatic relaxation")); break
        score=len(placements)
        if best is None or score>best[0]:
            best=(score,placements,unplaced)
        if not unplaced: break

    placements=best[1] if best else []
    # Remove unlocked generated placements for this run and persist the best solution.
    if class_filter:
        cur.execute("DELETE FROM timetable_slots WHERE school_id=? AND locked=0 AND lesson_id IN (SELECT id FROM timetable_lessons WHERE school_id=? AND class_id=?)",(sid,sid,class_filter))
    else:
        cur.execute("DELETE FROM timetable_slots WHERE school_id=? AND locked=0",(sid,))
    run=datetime.now().strftime("%Y%m%d%H%M%S%f")
    for row in placements:
        p=pmap[int(row["period_no"])]
        cur.execute("INSERT INTO timetable_slots(school_id,lesson_id,day_name,period_no,start_time,end_time,room_id,locked,generated_run) VALUES(?,?,?,?,?,?,?,?,?)",
            (sid,row["lesson_id"],row["day_name"],row["period_no"],p["start_time"],p["end_time"],row["room_id"],0,run))
    # "lessons_per_week" is the number of teaching occurrences. The timetable
    # capacity and generation result, however, are measured in PERIODS. A
    # double lesson therefore consumes 2 periods, not 1; a triple consumes 3.
    requested=sum(
        int(l.get("lessons_per_week") or 0) * max(1, int(l.get("duration") or 1))
        for l in lessons
    )
    placed=sum(max(1, int(row.get("duration") or 1)) for row in placements)
    status="complete" if not best or not best[2] else ("relaxed" if mode!="strict" else "incomplete")
    return run,requested,placed,best[2] if best else [],status


@router.post("/app/timetable/generate/new")
def timetable_generate_new(request:Request,class_id:str=Form(""),mode:str=Form("relaxed"),complexity:str=Form("normal"),replace_existing:str=Form("")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        if mode not in ("draft","relaxed","strict"):mode="relaxed"
        if complexity not in ("normal","large","huge"):complexity="normal"
        cf=int(class_id) if str(class_id).isdigit() else None
        run,requested,placed,unplaced,status=_generate_algorithm(con.cursor(),sid,cf,mode,complexity,bool(replace_existing))
        cur=con.cursor();cur.execute("INSERT INTO timetable_generation_runs(school_id,created_at,mode,complexity,status,placed,requested,message) VALUES(?,?,?,?,?,?,?,?)",
            (sid,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),mode,complexity,status,placed,requested,("Unplaced lesson cards: "+",".join(f"{lid} ({reason})" for lid,reason in unplaced)) if unplaced else "All requested cards placed"))
        con.commit()
        message=f"Generation {status}: {placed} of {requested} lesson placements made"
        if unplaced:message+="; unplaced cards "+",".join(f"{lid} ({reason})" for lid,reason in unplaced)
        return RedirectResponse("/app/timetable?tab=generate&msg="+quote(message),303)
    finally:con.close()





@router.post("/app/timetable/placement/move/{rid}")
def timetable_placement_move(request:Request,rid:int,day_name:str=Form(...),period_no:int=Form(...),room_id:str=Form("")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        cur=con.cursor()
        moving=cur.execute("""SELECT s.*,l.class_id,l.teacher_id,l.duration FROM timetable_slots s
            JOIN timetable_lessons l ON l.id=s.lesson_id WHERE s.id=? AND s.school_id=?""",(rid,sid)).fetchone()
        if not moving or int(moving["locked"] or 0):
            return RedirectResponse("/app/timetable?tab=timetable&error=Locked+or+missing+placement",303)
        if day_name not in DAYS:
            return RedirectResponse("/app/timetable?tab=timetable&error=Invalid+day",303)
        period=cur.execute("SELECT * FROM timetable_periods WHERE school_id=? AND period_no=?",(sid,period_no)).fetchone()
        if not period:
            return RedirectResponse("/app/timetable?tab=timetable&error=Invalid+period",303)
        room=int(room_id) if str(room_id).isdigit() else moving["room_id"]
        pmap={int(p["period_no"]):p for p in cur.execute("SELECT * FROM timetable_periods WHERE school_id=?",(sid,)).fetchall()}
        for pno in range(period_no,period_no+int(moving["duration"] or 1)):
            if pno not in pmap:
                return RedirectResponse("/app/timetable?tab=timetable&error=Lesson+duration+does+not+fit",303)
            if cur.execute("SELECT id FROM timetable_breaks WHERE school_id=? AND start_time<? AND end_time>? LIMIT 1",(sid,pmap[pno]["end_time"],pmap[pno]["start_time"])).fetchone():
                return RedirectResponse("/app/timetable?tab=timetable&error=Placement+crosses+a+break",303)
        others=cur.execute("""SELECT s.*,l.class_id,l.teacher_id,l.duration,l.room_id FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id
            WHERE s.school_id=? AND s.id<>? AND s.day_name=?""",(sid,rid,day_name)).fetchall()
        probe={"period_no":period_no,"duration":int(moving["duration"] or 1)}
        for o in others:
            if not _overlaps(probe,o): continue
            if int(o["class_id"])==int(moving["class_id"]) or (moving["teacher_id"] and o["teacher_id"] and int(o["teacher_id"])==int(moving["teacher_id"])):
                return RedirectResponse("/app/timetable?tab=timetable&error=Class+or+teacher+conflict",303)
            if room and o["room_id"] and int(o["room_id"])==int(room):
                return RedirectResponse("/app/timetable?tab=timetable&error=Room+conflict",303)
        cur.execute("UPDATE timetable_slots SET day_name=?,period_no=?,start_time=?,end_time=?,room_id=? WHERE id=? AND school_id=?",
                    (day_name,period_no,period["start_time"],period["end_time"],room,rid,sid))
        con.commit()
        return RedirectResponse("/app/timetable?tab=timetable&msg=Placement+moved",303)
    finally:
        con.close()
@router.post("/app/timetable/placement/delete/{rid}")
def timetable_placement_delete(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        con.execute("DELETE FROM timetable_slots WHERE id=? AND school_id=? AND locked=0",(rid,sid));con.commit()
        return RedirectResponse("/app/timetable?tab=timetable&msg=Placement+deleted",303)
    finally:con.close()


@router.post("/app/timetable/placement/lock/{rid}")
def timetable_placement_lock(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        con.execute("UPDATE timetable_slots SET locked=1 WHERE id=? AND school_id=?",(rid,sid));con.commit()
        return RedirectResponse("/app/timetable?tab=timetable&msg=Placement+locked",303)
    finally:con.close()
