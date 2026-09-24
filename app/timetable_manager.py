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
    is_pg = con.__class__.__module__.startswith("psycopg")
    pk = "BIGSERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_manager_settings(
        school_id INTEGER PRIMARY KEY,
        days_json TEXT NOT NULL DEFAULT '["Monday","Tuesday","Wednesday","Thursday","Friday"]',
        complexity TEXT NOT NULL DEFAULT 'normal',
        relaxation TEXT NOT NULL DEFAULT 'relaxed'
    )""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_days(
        id {pk},
        school_id INTEGER NOT NULL,
        day_no INTEGER NOT NULL,
        name TEXT NOT NULL,
        short_name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        UNIQUE(school_id,day_no)
    )""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_rooms(
        id {pk},
        school_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        code TEXT,
        capacity INTEGER,
        room_type TEXT,
        active INTEGER NOT NULL DEFAULT 1
    )""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_lessons(
        id {pk},
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
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_lesson_teachers(
        id {pk},
        school_id INTEGER NOT NULL,
        lesson_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL
    )""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_constraints(
        id {pk},
        school_id INTEGER NOT NULL,
        scope TEXT NOT NULL,
        constraint_type TEXT NOT NULL,
        target_id INTEGER,
        value TEXT,
        priority TEXT NOT NULL DEFAULT 'preferred',
        enabled INTEGER NOT NULL DEFAULT 1,
        notes TEXT
    )""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_slots(
        id {pk},
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
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_generation_runs(
        id {pk},
        school_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        mode TEXT NOT NULL,
        complexity TEXT NOT NULL,
        status TEXT NOT NULL,
        placed INTEGER NOT NULL DEFAULT 0,
        requested INTEGER NOT NULL DEFAULT 0,
        message TEXT
    )""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_periods(
        id {pk},
        school_id INTEGER NOT NULL,
        period_no INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        UNIQUE(school_id,period_no)
    )""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS timetable_breaks(
        id {pk},
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
        cur.execute("INSERT INTO timetable_manager_settings(school_id,days_json,complexity,relaxation) VALUES(?,?,?,?)",
                    (sid, json.dumps(list(DEFAULT_DAYS)), "normal", "relaxed"))
    existing = cur.execute("SELECT COUNT(*) c FROM timetable_days WHERE school_id=?", (sid,)).fetchone()
    if not int(existing["c"] or 0):
        for i, day in enumerate(DAYS, 1):
            cur.execute("INSERT INTO timetable_days(school_id,day_no,name,short_name,enabled) VALUES(?,?,?,?,?)",
                        (sid, i, day, day[:3].upper(), 1 if day in DEFAULT_DAYS else 0))
    settings = cur.execute("SELECT * FROM timetable_settings WHERE school_id=?", (sid,)).fetchone()
    if not settings:
        cur.execute("INSERT INTO timetable_settings(school_id,periods_per_day,period_minutes,periods_per_week) VALUES(?,?,?,?)",
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
    allowed = {"setup","periods","subjects","teachers","classes","rooms","lessons","constraints","generate","verify","timetable","print"}
    return tab if tab in allowed else "timetable"


def _tabs(active):
    labels = [
        ("setup","⚙️ Setup"),("periods","🕐 Periods & Bells"),("subjects","📚 Subjects"),
        ("teachers","👨‍🏫 Teachers"),("classes","🏫 Classes"),("rooms","🚪 Rooms"),
        ("lessons","📝 Lessons"),("constraints","🧩 Constraints"),("generate","🚀 Generate"),
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
.tt-scroll{overflow:auto}.tt-week{min-width:900px;border-collapse:collapse;width:100%}.tt-week th,.tt-week td{border:1px solid #176B3A;padding:8px;vertical-align:top}.tt-week th{background:#176B3A;color:#fff;white-space:nowrap}.tt-week td{min-width:125px;height:64px;font-size:11px}.tt-break{background:#fff7ed;color:#9a3412;text-align:center;font-weight:900}
@media(max-width:900px){.tt-grid,.tt-form{grid-template-columns:1fr}.tt-form .wide{grid-column:auto}}
@media print{.side,.top,.tt-tabs,.no-print{display:none!important}.page{padding:0!important}.tt-card{box-shadow:none;border:0}.tt-wrap{padding:0}.tt-week{min-width:0;font-size:9px}}
</style>"""


def _layout(request, tab, content):
    return _page(request, "Timetable Manager", f"<div class='tt-wrap'><h1>🗓️ Timetable Manager</h1><div class='tt-muted'>A complete school timetable workspace for setup, lesson cards, constraints, generation, verification, manual adjustment and printing.</div>{_notice(request)}{_tabs(tab)}{content}{_base_css()}</div>")


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
        elif tab == "constraints": body = _constraints(con, sid)
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
<div class='tt-card'><h3>Workflow</h3><div class='tt-muted'>Setup → Periods & Bells → Subjects / Teachers / Classes / Rooms → Lessons → Constraints → Generate → Verify → Timetable → Print</div></div>"""


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
    html = "".join(f"<tr><td>{r['id']}</td><td><b>{escape(str(r['name'] or ''))}</b></td><td>{escape(str(r['code'] or ''))}</td><td>{escape(str(r['initial'] or ''))}</td></tr>" for r in rows)
    return f"""<div class='tt-card'><h2>📚 Subjects</h2><div class='tt-muted'>These are the existing DaviSchool subjects. Edit them in the main Academic/Subjects area; the Timetable Manager consumes them directly.</div><div class='tt-scroll' style='margin-top:12px'><table class='tt-table'><thead><tr><th>ID</th><th>Subject</th><th>Code</th><th>Initial</th></tr></thead><tbody>{html or '<tr><td colspan=4>No subjects found.</td></tr>'}</tbody></table></div></div>"""


def _teachers(con, sid):
    rows = con.execute("SELECT id,name,email,phone,role,department FROM teachers WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    html = "".join(f"<tr><td>{r['id']}</td><td><b>{escape(str(r['name'] or ''))}</b></td><td>{escape(str(r['email'] or ''))}</td><td>{escape(str(r['phone'] or ''))}</td><td>{escape(str(r['department'] or r['role'] or ''))}</td></tr>" for r in rows)
    return f"""<div class='tt-card'><h2>👨‍🏫 Teachers</h2><div class='tt-muted'>Existing staff records are used as timetable resources. Teacher allocations are shown in Lessons.</div><div class='tt-scroll' style='margin-top:12px'><table class='tt-table'><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>Role / Department</th></tr></thead><tbody>{html or '<tr><td colspan=5>No teachers found.</td></tr>'}</tbody></table></div></div>"""


def _classes(con, sid):
    rows = con.execute("SELECT id,name,level,stream FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
    html = "".join(f"<tr><td>{r['id']}</td><td><b>{escape(str(r['name'] or ''))}</b></td><td>{escape(str(r['level'] or ''))}</td><td>{escape(str(r['stream'] or ''))}</td></tr>" for r in rows)
    return f"""<div class='tt-card'><h2>🏫 Classes</h2><div class='tt-muted'>Classes and streams come directly from DaviSchool. Each timetable lesson is linked to a class ID, so stream data is preserved.</div><div class='tt-scroll' style='margin-top:12px'><table class='tt-table'><thead><tr><th>ID</th><th>Class</th><th>Level</th><th>Stream</th></tr></thead><tbody>{html or '<tr><td colspan=4>No classes found.</td></tr>'}</tbody></table></div></div>"""


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
    opts = lambda rows,key,label: "".join(f"<option value='{r[key]}' {'selected' if str(e.get(key,''))==str(r[key]) else ''}>{escape(str(r[label] or ''))}</option>" for r in rows)
    return f"""<div class='tt-card'><h3>{'✏️ Edit Lesson' if existing else '📝 Add Lesson Card'}</h3><div class='tt-muted'>Each lesson card represents a teaching requirement. Weekly count and duration are used by the generator.</div>
<form method='post' action='/app/timetable/lesson/save' class='tt-form' style='margin-top:12px'>
<input type='hidden' name='lesson_id' value='{e.get("id","")}'>
<label><span class='tt-label'>Class</span><select class='tt-field' name='class_id' required><option value=''>Select class</option>{opts(classes,'id','name')}</select></label>
<label><span class='tt-label'>Subject</span><select class='tt-field' name='subject_id' required><option value=''>Select subject</option>{opts(subjects,'id','name')}</select></label>
<label><span class='tt-label'>Teacher</span><select class='tt-field' name='teacher_id'><option value=''>Without teacher</option>{opts(teachers,'id','name')}</select></label>
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
    html = "".join(
        f"<tr><td>{escape(str(r['class_name']))} {escape(str(r['stream'] or ''))}</td><td><b>{escape(str(r['subject']))}</b></td><td>{escape(str(r['teacher'] or ''))}</td><td>{int(r['lessons_per_week'])}</td><td>{int(r['duration'])}</td><td>{escape(str(r['group_name'] or 'Entire class'))}</td><td>{'🔒' if int(r['locked'] or 0) else ''}</td><td><a class='tt-btn alt' href='/app/timetable?tab=lessons&edit={r['id']}'>Edit</a> <form style='display:inline' method='post' action='/app/timetable/lesson/delete/{r['id']}' onsubmit='return confirm(&quot;Delete this lesson card?&quot;)'><button class='tt-btn danger'>🗑️</button></form></td></tr>"
        for r in rows
    )
    edit_id = request.query_params.get("edit", "")
    edit = None
    if str(edit_id).isdigit():
        edit = con.execute("SELECT * FROM timetable_lessons WHERE id=? AND school_id=?", (int(edit_id), sid)).fetchone()
    return _lesson_form(con,sid,edit) + f"""<div class='tt-card'><h3>Lesson Cards ({len(rows)})</h3><div class='tt-muted'>This is the timetable equivalent of aSc lesson cards/contracts. One row is one weekly teaching requirement.</div><div class='tt-scroll' style='margin-top:10px'><table class='tt-table'><thead><tr><th>Class</th><th>Subject</th><th>Teacher</th><th>/Week</th><th>Length</th><th>Group</th><th></th><th></th></tr></thead><tbody>{html or '<tr><td colspan=8>No lesson cards yet.</td></tr>'}</tbody></table></div></div>"""


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
    placed={int(r["lesson_id"]) for r in placements}
    issues=[]
    for l in lessons:
        # Duration is counted as occupied periods, so each weekly card needs its count.
        # Slots store one row per starting card; generator keeps duration metadata on lesson.
        if int(l["id"]) not in placed:
            issues.append(f"Lesson card {l['id']} has no placement.")
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
            if a["class_id"]==b["class_id"]:
                issues.append(f"Class conflict on {a['day_name']} period {a['period_no']}: lesson {a['lesson_id']} / {b['lesson_id']}.")
            if a["teacher_id"] and b["teacher_id"] and a["teacher_id"]==b["teacher_id"]:
                issues.append(f"Teacher conflict on {a['day_name']} period {a['period_no']}: lesson {a['lesson_id']} / {b['lesson_id']}.")
            if a["room_id"] and b["room_id"] and a["room_id"]==b["room_id"]:
                issues.append(f"Room conflict on {a['day_name']} period {a['period_no']}: lesson {a['lesson_id']} / {b['lesson_id']}.")
    return f"""<div class='tt-card'><h2>✅ Timetable Verification</h2><div class='tt-muted'>Checks incomplete cards, class conflicts, teacher conflicts and room conflicts before publication.</div>
<div class='tt-stat' style='margin:12px 0'><b>{len(issues)}</b>{'Issues found' if issues else 'No basic conflicts found'}</div>
<div class='tt-scroll'><table class='tt-table'><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{''.join(f"<tr><td>⚠️</td><td>{escape(x)}</td></tr>" for x in issues) if issues else '<tr><td>✅</td><td>Verification passed for the current basic checks.</td></tr>'}</tbody></table></div></div>"""


def _timetable(request, con, sid):
    classes=con.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    teachers=con.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    rooms=con.execute("SELECT id,name FROM timetable_rooms WHERE school_id=? AND active=1 ORDER BY name",(sid,)).fetchall()
    periods=con.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()
    breaks=con.execute("SELECT * FROM timetable_breaks WHERE school_id=? ORDER BY start_time",(sid,)).fetchall()
    days=[r["name"] for r in con.execute("SELECT * FROM timetable_days WHERE school_id=? AND enabled=1 ORDER BY day_no",(sid,)).fetchall()]
    class_filter=request.query_params.get("class_id","")
    teacher_filter=request.query_params.get("teacher_id","")
    room_filter=request.query_params.get("room_id","")
    where=["s.school_id=?"];params=[sid]
    if str(class_filter).isdigit(): where.append("l.class_id=?");params.append(int(class_filter))
    if str(teacher_filter).isdigit(): where.append("l.teacher_id=?");params.append(int(teacher_filter))
    if str(room_filter).isdigit(): where.append("s.room_id=?");params.append(int(room_filter))
    rows=con.execute("""SELECT s.*,l.class_id,l.subject_id,l.teacher_id,l.room_id,l.duration,
        c.name class_name,c.stream,sub.name subject,t.name teacher,r.name room
        FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id
        JOIN classes c ON c.id=l.class_id JOIN subjects sub ON sub.id=l.subject_id
        LEFT JOIN teachers t ON t.id=l.teacher_id LEFT JOIN timetable_rooms r ON r.id=s.room_id
        WHERE """+" AND ".join(where)+""" ORDER BY CASE s.day_name WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 ELSE 6 END,s.period_no""",params).fetchall()
    slot_map={(r["day_name"],int(r["period_no"])):r for r in rows}
    header="<tr><th>DAY</th>"+"".join(f"<th>P{int(p['period_no'])}<br>{escape(str(p['start_time']))}-{escape(str(p['end_time']))}</th>" for p in periods)+"</tr>"
    body=""
    for day in days:
        cells=[]
        for p in periods:
            br=next((b for b in breaks if _time_to_min(str(b["start_time"])) < _time_to_min(str(p["end_time"])) and _time_to_min(str(b["end_time"])) > _time_to_min(str(p["start_time"]))),None)
            if br:
                cells.append(f"<td class='tt-break'>☕ {escape(str(br['name']))}</td>")
                continue
            r=slot_map.get((day,int(p["period_no"])))
            if not r:
                cells.append("<td>—</td>")
            else:
                cells.append(f"<td><b>{escape(str(r['subject']))}</b><br>{escape(str(r['class_name']))} {escape(str(r['stream'] or ''))}<br>{escape(str(r['teacher'] or ''))}{('<br>'+escape(str(r['room']))) if r['room'] else ''}<br><small>{'🔒 Locked' if int(r['locked'] or 0) else ''}</small></td>")
        body+=f"<tr><th>{escape(day)}</th>{''.join(cells)}</tr>"
    class_opts="".join(f"<option value='{c['id']}' {'selected' if str(class_filter)==str(c['id']) else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    teacher_opts="".join(f"<option value='{t['id']}' {'selected' if str(teacher_filter)==str(t['id']) else ''}>{escape(str(t['name']))}</option>" for t in teachers)
    room_opts="".join(f"<option value='{r['id']}' {'selected' if str(room_filter)==str(r['id']) else ''}>{escape(str(r['name']))}</option>" for r in rooms)
    placement_parts=[]
    for r in rows:
        if int(r["locked"] or 0):
            action="🔒"
        else:
            action=(f"<form method='post' action='/app/timetable/placement/lock/{r['id']}' style='display:inline'><button class='tt-btn alt'>🔒</button></form> "
                    f"<form method='post' action='/app/timetable/placement/delete/{r['id']}' style='display:inline' onsubmit=" + '"return confirm(\'Remove this placement?\')" ' + "><button class='tt-btn danger'>🗑️</button></form>")
        placement_parts.append(
            f"<tr><td>{escape(str(r['class_name']))} {escape(str(r['stream'] or ''))}</td><td>{escape(str(r['day_name']))}</td>"
            f"<td>P{int(r['period_no'])}</td><td><b>{escape(str(r['subject']))}</b></td><td>{escape(str(r['teacher'] or ''))}</td>"
            f"<td>{escape(str(r['room'] or ''))}</td><td>{'🔒' if int(r['locked'] or 0) else ''}</td><td>{action}</td></tr>"
        )
    placement_rows="".join(placement_parts)
    move_id=request.query_params.get("move","")
    move_form=""
    if str(move_id).isdigit():
        moving=con.execute("SELECT s.*,l.class_id,l.teacher_id,l.room_id,l.duration,c.name class_name,c.stream,sub.name subject FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id JOIN classes c ON c.id=l.class_id JOIN subjects sub ON sub.id=l.subject_id WHERE s.id=? AND s.school_id=?",(int(move_id),sid)).fetchone()
        if moving:
            day_opts="".join(f"<option {'selected' if d==moving['day_name'] else ''}>{escape(d)}</option>" for d in days)
            period_opts="".join(f"<option value='{p['period_no']}' {'selected' if int(p['period_no'])==int(moving['period_no']) else ''}>P{p['period_no']} — {escape(str(p['start_time']))}-{escape(str(p['end_time']))}</option>" for p in periods)
            move_form=f"""<div class='tt-card'><h3>↔️ Move placement</h3><div class='tt-muted'>{escape(str(moving['subject']))} — {escape(str(moving['class_name']))} {escape(str(moving['stream'] or ''))}</div><form method='post' action='/app/timetable/placement/move/{moving['id']}' class='tt-form' style='margin-top:10px'><label><span class='tt-label'>Day</span><select class='tt-field' name='day_name'>{day_opts}</select></label><label><span class='tt-label'>Start period</span><select class='tt-field' name='period_no'>{period_opts}</select></label><label><span class='tt-label'>Room</span><select class='tt-field' name='room_id'><option value=''>Any / unchanged</option>{room_opts}</select></label><div><button class='tt-btn'>💾 Move</button> <a class='tt-btn alt' href='/app/timetable?tab=timetable'>Cancel</a></div></form></div>"""
    return f"""{move_form}<div class='tt-card'><h2>🗓️ Timetable Grid</h2><div class='tt-muted'>Days run vertically and periods/times horizontally. Use the filters to inspect class, teacher or room views. Locked placements are protected from regeneration.</div>
<form method='get' class='tt-form' style='margin-top:12px'><input type='hidden' name='tab' value='timetable'><label><span class='tt-label'>Class</span><select class='tt-field' name='class_id'><option value=''>All classes</option>{class_opts}</select></label><label><span class='tt-label'>Teacher</span><select class='tt-field' name='teacher_id'><option value=''>All teachers</option>{teacher_opts}</select></label><label><span class='tt-label'>Room</span><select class='tt-field' name='room_id'><option value=''>All rooms</option>{room_opts}</select></label><div><button class='tt-btn'>🔎 View</button></div></form>
<div class='tt-scroll' style='margin-top:12px'><table class='tt-week'>{header}{body or '<tr><td colspan=20>No timetable placements yet.</td></tr>'}</table></div>
<div style='margin-top:12px'><a class='tt-btn' href='/app/timetable?tab=generate'>🚀 Generate / Regenerate</a> <a class='tt-btn alt' href='/app/timetable?tab=verify'>✅ Verify</a> <a class='tt-btn alt' href='/app/timetable?tab=print'>🖨️ Print</a></div></div>
<div class='tt-card'><h3>Placement control</h3><div class='tt-muted'>Lock a lesson to protect it from future generation. Delete an unlocked placement to return that lesson card to the unplaced pool.</div><div class='tt-scroll' style='margin-top:10px'><table class='tt-table'><thead><tr><th>Class</th><th>Day</th><th>Period</th><th>Subject</th><th>Teacher</th><th>Room</th><th></th><th>Action</th></tr></thead><tbody>{placement_rows or '<tr><td colspan=8>No placements.</td></tr>'}</tbody></table></div></div>"""

def _print_view(con, sid):
    rows=con.execute("""SELECT s.*,c.name class_name,c.stream,sub.name subject,t.name teacher,r.name room,l.duration
        FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id JOIN classes c ON c.id=l.class_id
        JOIN subjects sub ON sub.id=l.subject_id LEFT JOIN teachers t ON t.id=l.teacher_id LEFT JOIN timetable_rooms r ON r.id=s.room_id
        WHERE s.school_id=? ORDER BY c.name,c.stream,s.day_name,s.period_no""",(sid,)).fetchall()
    return f"""<div class='tt-card'><h2>🖨️ Print & Publish</h2><div class='tt-muted'>Use the browser print preview to print the timetable grid or the individual class/teacher listings. This is isolated from the other DaviSchool printable documents.</div>
<div class='no-print' style='margin:12px 0'><button class='tt-btn' onclick='window.print()'>🖨️ Open Print Preview</button></div>
<div class='tt-scroll'><table class='tt-table'><thead><tr><th>Class</th><th>Day</th><th>Period</th><th>Subject</th><th>Teacher</th><th>Room</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r['class_name']))} {escape(str(r['stream'] or ''))}</td><td>{escape(str(r['day_name']))}</td><td>{int(r['period_no'])}</td><td>{escape(str(r['subject']))}</td><td>{escape(str(r['teacher'] or ''))}</td><td>{escape(str(r['room'] or ''))}</td></tr>" for r in rows) or '<tr><td colspan=6>No placements yet.</td></tr>'}</tbody></table></div></div>"""


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
        cur.execute("INSERT INTO timetable_settings(school_id,periods_per_day,period_minutes,periods_per_week) VALUES(?,?,?,?) ON CONFLICT(school_id) DO UPDATE SET periods_per_day=excluded.periods_per_day,period_minutes=excluded.period_minutes,periods_per_week=excluded.periods_per_week",(sid,periods_per_day,period_minutes,periods_per_week))
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
        for p in periods:
            st=str(form.get(f"start_{p['period_no']}") or "");et=str(form.get(f"end_{p['period_no']}") or "")
            if not st or not et or et<=st:return RedirectResponse(f"/app/timetable?tab=periods&error=Invalid+time+for+period+{p['period_no']}",303)
            overlap=cur.execute("SELECT id FROM timetable_periods WHERE school_id=? AND period_no<>? AND start_time<? AND end_time>? LIMIT 1",(sid,p["period_no"],et,st)).fetchone()
            if overlap:return RedirectResponse(f"/app/timetable?tab=periods&error=Period+{p['period_no']}+overlaps+another+period",303)
            cur.execute("UPDATE timetable_periods SET start_time=?,end_time=? WHERE id=?",(st,et,p["id"]))
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
def timetable_lesson_save(request:Request,lesson_id:int=Form(0),class_id:int=Form(...),subject_id:int=Form(...),teacher_id:str=Form(""),room_id:str=Form(""),lessons_per_week:int=Form(...),duration:int=Form(...),cycle:str=Form("Every week"),group_name:str=Form(""),locked:str=Form(""),notes:str=Form("")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        cur=con.cursor()
        valid_class=cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
        valid_subject=cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
        if not valid_class or not valid_subject or not 1<=lessons_per_week<=30 or not 1<=duration<=3:return RedirectResponse("/app/timetable?tab=lessons&error=Invalid+lesson+card",303)
        teacher=int(teacher_id) if str(teacher_id).isdigit() else None
        room=int(room_id) if str(room_id).isdigit() else None
        if teacher and not cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(teacher,sid)).fetchone(): teacher=None
        if room and not cur.execute("SELECT id FROM timetable_rooms WHERE id=? AND school_id=?",(room,sid)).fetchone(): room=None
        vals=(class_id,subject_id,teacher,room,group_name.strip(),lessons_per_week,duration,cycle if cycle in ("Every week","Alternate weeks") else "Every week",1 if locked else 0,room,notes.strip())
        if lesson_id:
            cur.execute("""UPDATE timetable_lessons SET class_id=?,subject_id=?,teacher_id=?,room_id=?,group_name=?,lessons_per_week=?,duration=?,cycle=?,locked=?,preferred_room=?,notes=? WHERE id=? AND school_id=?""",vals+(lesson_id,sid))
            action="TIMETABLE_LESSON_UPDATE"
        else:
            cur.execute("""INSERT INTO timetable_lessons(school_id,class_id,subject_id,teacher_id,room_id,group_name,lessons_per_week,duration,cycle,locked,preferred_room,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(sid,)+vals)
            action="TIMETABLE_LESSON_CREATE"
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
            if lesson["class_id"]==other["class_id"]:return False,None
            if lesson["teacher_id"] and other["teacher_id"] and lesson["teacher_id"]==other["teacher_id"]:return False,None
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
    days=[r["name"] for r in cur.execute("SELECT * FROM timetable_days WHERE school_id=? AND enabled=1 ORDER BY day_no",(sid,)).fetchall()]
    periods=cur.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()
    rooms=cur.execute("SELECT * FROM timetable_rooms WHERE school_id=? AND active=1 ORDER BY id",(sid,)).fetchall()
    lessons=cur.execute("""SELECT * FROM timetable_lessons WHERE school_id=?""" + (" AND class_id=?" if class_filter else "") + " ORDER BY duration DESC,lessons_per_week DESC,id",
                        (sid,class_filter) if class_filter else (sid,)).fetchall()
    constraints=_constraint_maps(cur,sid)
    if replace_existing:
        if class_filter:
            cur.execute("DELETE FROM timetable_slots WHERE school_id=? AND locked=0 AND lesson_id IN (SELECT id FROM timetable_lessons WHERE school_id=? AND class_id=?)",(sid,sid,class_filter))
        else:
            cur.execute("DELETE FROM timetable_slots WHERE school_id=? AND locked=0",(sid,))
    occupied=cur.execute("SELECT s.*,l.class_id,l.teacher_id,l.room_id,l.duration,l.subject_id FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id WHERE s.school_id=?",(sid,)).fetchall()
    occupied=[dict(r) for r in occupied]
    requested=0;placed=0;unplaced=[]
    run=datetime.now().strftime("%Y%m%d%H%M%S%f")
    for lesson in lessons:
        requested += int(lesson["lessons_per_week"] or 0)
        already=sum(1 for o in occupied if int(o["lesson_id"])==int(lesson["id"]))
        need=max(0,int(lesson["lessons_per_week"] or 0)-already)
        if int(lesson["locked"] or 0) and already: need=0
        for _ in range(need):
            found=None
            for day in days:
                for p in periods:
                    pno=int(p["period_no"])
                    ok,room_id=_is_available_slot(cur,sid,lesson,day,pno,int(lesson["duration"] or 1),occupied,rooms,mode=="strict")
                    if not ok:continue
                    # Strict mode respects simple constraints; relaxed mode may ignore preferred constraints.
                    bad=False
                    for c in constraints.get("Teacher max lessons/day",[]):
                        if c["target_id"] and lesson["teacher_id"] and int(c["target_id"])==int(lesson["teacher_id"]):
                            limit=int(c["value"] or 0)
                            count=sum(1 for o in occupied if o["day_name"]==day and o["teacher_id"]==lesson["teacher_id"])
                            if limit and count>=limit:bad=True
                    for c in constraints.get("Class max lessons/day",[]):
                        if c["target_id"] and int(c["target_id"])==int(lesson["class_id"]):
                            limit=int(c["value"] or 0)
                            count=sum(1 for o in occupied if o["day_name"]==day and o["class_id"]==lesson["class_id"])
                            if limit and count>=limit:bad=True
                    if mode=="strict" and bad:continue
                    if bad and mode!="strict":continue
                    # Avoid placing the same subject twice on a day unless explicitly relaxed.
                    same_day_subject=sum(1 for o in occupied if o["day_name"]==day and o["class_id"]==lesson["class_id"] and o["subject_id"]==lesson["subject_id"])
                    if same_day_subject and mode=="strict":continue
                    found=(day,p,room_id);break
                if found:break
            if not found:
                unplaced.append(int(lesson["id"]));continue
            day,p,room_id=found
            row={"lesson_id":int(lesson["id"]),"class_id":int(lesson["class_id"]),"teacher_id":lesson["teacher_id"],"room_id":room_id,"day_name":day,"period_no":int(p["period_no"]),"duration":int(lesson["duration"] or 1)}
            cur.execute("INSERT INTO timetable_slots(school_id,lesson_id,day_name,period_no,start_time,end_time,room_id,locked,generated_run) VALUES(?,?,?,?,?,?,?,?,?)",
                        (sid,lesson["id"],day,p["period_no"],p["start_time"],p["end_time"],room_id,0,run))
            occupied.append(row);placed+=1
    status="complete" if not unplaced else ("relaxed" if mode!="strict" else "incomplete")
    return run,requested,placed,unplaced,status


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
            (sid,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),mode,complexity,status,placed,requested,("Unplaced lesson cards: "+",".join(map(str,unplaced))) if unplaced else "All requested cards placed"))
        con.commit()
        message=f"Generation {status}: {placed} of {requested} lesson cards placed"
        if unplaced:message+="; unplaced cards "+",".join(map(str,unplaced))
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
