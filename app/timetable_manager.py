from fastapi import APIRouter, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from html import escape
from urllib.parse import quote
from datetime import datetime, timedelta
import json
import random

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
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable_profiles(
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        active INTEGER NOT NULL DEFAULT 0,
        days_json TEXT NOT NULL DEFAULT '[]',
        periods_json TEXT NOT NULL DEFAULT '[]',
        breaks_json TEXT NOT NULL DEFAULT '[]',
        periods_per_day INTEGER NOT NULL DEFAULT 7,
        period_minutes INTEGER NOT NULL DEFAULT 40,
        periods_per_week INTEGER NOT NULL DEFAULT 35,
        complexity TEXT NOT NULL DEFAULT 'normal',
        relaxation TEXT NOT NULL DEFAULT 'relaxed',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    slot_columns={str(x["name"]) for x in cur.execute("PRAGMA table_info(timetable_slots)").fetchall()}
    if "profile_id" not in slot_columns:
        cur.execute("ALTER TABLE timetable_slots ADD COLUMN profile_id INTEGER DEFAULT 1")
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
            cur.execute("INSERT INTO timetable_slots(school_id,lesson_id,day_name,period_no,start_time,end_time,room_id,locked,generated_run,profile_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (sid,lesson_id,row["day"],p["period_no"],p["start_time"],p["end_time"],None,0,"legacy-import",_active_profile_id(con,sid)))
    con.commit()


def _seed(con, sid):
    """Create/migrate the school's timetable profiles without deleting legacy data."""
    cur=con.cursor()
    profile=cur.execute(
        "SELECT * FROM timetable_profiles WHERE school_id=? ORDER BY active DESC,id LIMIT 1",
        (sid,)
    ).fetchone()

    if not profile:
        manager=cur.execute("SELECT * FROM timetable_manager_settings WHERE school_id=?",(sid,)).fetchone()
        settings=cur.execute("SELECT * FROM timetable_settings WHERE school_id=?",(sid,)).fetchone()
        legacy_days=cur.execute("SELECT * FROM timetable_days WHERE school_id=? ORDER BY day_no",(sid,)).fetchall()
        days=[
            {"day_no":int(x["day_no"]),"name":str(x["name"]),
             "short_name":str(x["short_name"]),"enabled":int(x["enabled"] or 0)}
            for x in legacy_days
        ] if legacy_days else [
            {"day_no":i,"name":day,"short_name":day[:3].upper(),
             "enabled":1 if day in DEFAULT_DAYS else 0}
            for i,day in enumerate(DAYS,1)
        ]
        legacy_periods=cur.execute("SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)).fetchall()
        if legacy_periods:
            periods=[
                {"id":int(x["period_no"]),"period_no":int(x["period_no"]),
                 "start_time":str(x["start_time"]),"end_time":str(x["end_time"])}
                for x in legacy_periods
            ]
        else:
            ppd=int(settings["periods_per_day"] if settings else 7)
            pm=int(settings["period_minutes"] if settings else 40)
            base=datetime.strptime("08:00","%H:%M")
            periods=[
                {"id":n,"period_no":n,
                 "start_time":(base+timedelta(minutes=(n-1)*pm)).strftime("%H:%M"),
                 "end_time":(base+timedelta(minutes=n*pm)).strftime("%H:%M")}
                for n in range(1,ppd+1)
            ]
        legacy_breaks=cur.execute("SELECT * FROM timetable_breaks WHERE school_id=? ORDER BY start_time,id",(sid,)).fetchall()
        breaks=[
            {"id":int(x["id"]),"name":str(x["name"]),
             "start_time":str(x["start_time"]),"end_time":str(x["end_time"])}
            for x in legacy_breaks
        ]
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""INSERT INTO timetable_profiles(
            school_id,name,description,active,days_json,periods_json,breaks_json,
            periods_per_day,period_minutes,periods_per_week,complexity,relaxation,
            created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            sid,"Weekday Timetable",
            "Original timetable migrated safely into the profile system.",1,
            json.dumps(days),json.dumps(periods),json.dumps(breaks),
            int(settings["periods_per_day"] if settings else len(periods) or 7),
            int(settings["period_minutes"] if settings else 40),
            int(settings["periods_per_week"] if settings else max(1,sum(1 for x in days if x["enabled"]))*max(1,len(periods))),
            str(manager["complexity"] if manager else "normal"),
            str(manager["relaxation"] if manager else "relaxed"),
            now,now
        ))
        profile=cur.execute("SELECT * FROM timetable_profiles WHERE school_id=? ORDER BY id DESC LIMIT 1",(sid,)).fetchone()

    pid=int(profile["id"])
    cur.execute("UPDATE timetable_profiles SET active=0 WHERE school_id=? AND id<>?",(sid,pid))
    cur.execute("UPDATE timetable_profiles SET active=1 WHERE school_id=? AND id=?",(sid,pid))
    cur.execute("UPDATE timetable_slots SET profile_id=? WHERE school_id=? AND (profile_id IS NULL OR profile_id=1)",(pid,sid))
    con.commit()


def _active_profile_id(con,sid):
    row=con.execute("SELECT id FROM timetable_profiles WHERE school_id=? AND active=1 ORDER BY id LIMIT 1",(sid,)).fetchone()
    if row:return int(row["id"])
    row=con.execute("SELECT id FROM timetable_profiles WHERE school_id=? ORDER BY id LIMIT 1",(sid,)).fetchone()
    return int(row["id"]) if row else 0


def _active_profile(con,sid):
    pid=_active_profile_id(con,sid)
    return con.execute("SELECT * FROM timetable_profiles WHERE id=? AND school_id=?",(pid,sid)).fetchone()


def _profile_days(db,sid):
    row=_active_profile(db,sid)
    if not row:return []
    try:values=json.loads(str(row["days_json"] or "[]"))
    except Exception:values=[]
    return [
        {"day_no":int(x.get("day_no",i+1)),"name":str(x.get("name") or ""),
         "short_name":str(x.get("short_name") or str(x.get("name") or "")[:3].upper()),
         "enabled":int(x.get("enabled",1))}
        for i,x in enumerate(values) if str(x.get("name") or "").strip()
    ]


def _profile_periods(db,sid):
    row=_active_profile(db,sid)
    if not row:return []
    try:values=json.loads(str(row["periods_json"] or "[]"))
    except Exception:values=[]
    return [
        {"id":int(x.get("id",x.get("period_no",i+1))),
         "period_no":int(x.get("period_no",i+1)),
         "start_time":str(x.get("start_time") or ""),
         "end_time":str(x.get("end_time") or "")}
        for i,x in enumerate(values)
        if str(x.get("start_time") or "").strip() and str(x.get("end_time") or "").strip()
    ]


def _profile_breaks(db,sid):
    row=_active_profile(db,sid)
    if not row:return []
    try:values=json.loads(str(row["breaks_json"] or "[]"))
    except Exception:values=[]
    return [
        {"id":int(x.get("id",i+1)),"name":str(x.get("name") or ""),
         "start_time":str(x.get("start_time") or ""),"end_time":str(x.get("end_time") or "")}
        for i,x in enumerate(values) if str(x.get("name") or "").strip()
    ]


def _profile_settings(db,sid):
    row=_active_profile(db,sid)
    return row or {"periods_per_day":7,"period_minutes":40,"periods_per_week":35,"complexity":"normal","relaxation":"relaxed","name":"Weekday Timetable"}


def _save_profile_json(con,sid,field,value):
    pid=_active_profile_id(con,sid)
    con.execute(
        f"UPDATE timetable_profiles SET {field}=?,updated_at=? WHERE id=? AND school_id=?",
        (json.dumps(value),datetime.now().strftime("%Y-%m-%d %H:%M:%S"),pid,sid)
    )


def _install_profile_sql_function(con,sid):
    pid=_active_profile_id(con,sid)
    con.create_function("timetable_active_profile",1,
        lambda school_id: pid if str(school_id).isdigit() and int(school_id)==int(sid) else -1)


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
    _install_profile_sql_function(con, sid)
    return sid, con, None


def _selected_tab(request):
    tab = str(request.query_params.get("tab", "timetable") or "timetable").lower()
    allowed = {"profiles","setup","periods","subjects","teachers","classes","rooms","lessons","availability","generate","verify","timetable","teacher_sheets","print"}
    return tab if tab in allowed else "timetable"


def _tabs(active):
    labels = [
        ("profiles","🗂️ Timetable Profiles"),("setup","⚙️ Setup"),("periods","🕐 Periods & Bells"),("subjects","📚 Subjects"),
        ("teachers","👨‍🏫 Teachers"),("classes","🏫 Classes"),("rooms","🚪 Rooms"),
        ("lessons","📝 Lessons"),("availability","🎯 Availability"),("generate","🚀 Generate"),
        ("verify","✅ Verify"),("timetable","🗓️ Timetable"),("teacher_sheets","👨‍🏫 Teacher Sheets"),("print","🖨️ Print")
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
.tt-master-scroll{overflow:auto;max-width:100%;border:1px solid #cbd5e1;border-radius:10px;background:#fff}.tt-master-table{border-collapse:separate;border-spacing:0;min-width:max-content;width:100%;font-size:11px}.tt-master-table th,.tt-master-table td{border-right:1px solid #cbd5e1;border-bottom:1px solid #cbd5e1}.tt-master-day{background:#176B3A;color:#fff;font-weight:900;text-align:center;padding:8px;position:sticky;top:0;z-index:12}.tt-master-period{background:#f1f5f9;font-weight:900;text-align:center;padding:5px;min-width:125px;position:sticky;top:34px;z-index:11}.tt-master-class{background:#176B3A;color:#fff;font-weight:900;text-align:left;padding:8px;min-width:120px;width:120px;position:sticky;left:0;z-index:13}.tt-master-corner{z-index:15}.tt-master-cell{height:78px;min-width:125px;padding:3px;vertical-align:top;text-align:center;background:#fff}.tt-master-drop{color:#94a3b8;font-size:20px;cursor:copy}.tt-master-drop:hover{background:#ecfdf5!important;color:#176B3A}.tt-master-continuation{font-size:18px;color:#64748b;background:#f8fafc;vertical-align:middle}.tt-master-placard{height:70px;box-sizing:border-box;border:1px solid rgba(15,23,42,.15);border-radius:6px;padding:5px;cursor:grab;box-shadow:0 1px 2px rgba(15,23,42,.08);overflow:hidden}.tt-master-placard b{display:block;font-size:12px;font-weight:900;line-height:1.15}.tt-master-placard span{display:block;font-size:10px;font-weight:700;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tt-master-placard small{display:block;font-size:8px;margin-top:2px}.tt-master-placard em{display:block;font-size:8px;font-style:normal;font-weight:900;margin-top:2px}.tt-master-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:10px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:10px;margin-bottom:8px}.tt-master-toolbar span{font-size:11px;color:#475569}.tt-master-placard.tt-dragging{opacity:.4}.tt-master-drop.tt-drop-hover{background:#dcfce7!important;outline:2px dashed #176B3A;outline-offset:-3px}.tt-draggable-lesson{cursor:grab;transition:transform .12s,box-shadow .12s}.tt-draggable-lesson:hover{transform:translateY(-1px);box-shadow:0 3px 9px rgba(15,23,42,.18)}.tt-dragging{opacity:.45;cursor:grabbing}.tt-drop-slot{transition:background .12s,outline .12s}.tt-drop-slot.tt-drop-hover{background:#ecfdf5!important;outline:2px dashed #176B3A;outline-offset:-3px}.tt-legend{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.tt-teacher-chip{display:inline-flex;align-items:center;gap:5px;padding:5px 8px;border:1px solid rgba(15,23,42,.12);border-radius:999px;font-size:11px;font-weight:800}.tt-chip-dot{width:7px;height:7px;border-radius:50%;background:#176B3A}.tt-tab.active{background:#176B3A;color:#fff;border-color:#176B3A}.tt-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.tt-card{background:#fff;border:1px solid #dbe4ee;border-radius:14px;padding:16px;margin-bottom:14px;box-shadow:0 5px 18px rgba(15,23,42,.04)}
.tt-card h2{margin:0 0 5px;color:#176B3A;font-size:18px}.tt-card h3{margin:0 0 8px;font-size:14px}.tt-muted{color:#64748b;font-size:12px;line-height:1.5}
.tt-field{width:100%;box-sizing:border-box;padding:10px;border:1px solid #cbd5e1;border-radius:9px;background:#fff}.tt-label{font-size:11px;font-weight:800;color:#475569;display:block;margin-bottom:5px}
.tt-btn{display:inline-block;border:0;border-radius:9px;background:#176B3A;color:#fff;padding:10px 14px;font-weight:900;cursor:pointer;text-decoration:none}.tt-btn.alt{background:#334155}.tt-btn.danger{background:#b91c1c}
.tt-form{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-items:end}.tt-form .wide{grid-column:span 2}.tt-form .full{grid-column:1/-1}
.tt-table{width:100%;border-collapse:collapse;font-size:12px}.tt-table th,.tt-table td{border:1px solid #dbe4ee;padding:8px;text-align:left;vertical-align:top}.tt-table th{background:#176B3A;color:#fff}.tt-table tr:nth-child(even){background:#f8fafc}
.tt-notice{padding:11px 13px;border-radius:10px;margin:10px 0;font-weight:800;font-size:12px}.tt-notice.ok{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46}.tt-notice.bad{background:#fff1f2;border:1px solid #fecdd3;color:#9f1239}
.tt-stat{padding:14px;border:1px solid #dbe4ee;border-radius:12px;background:#f8fafc}.tt-stat b{font-size:23px;display:block;color:#176B3A}.tt-check{display:flex;gap:7px;align-items:center;font-size:12px;font-weight:700}
.tt-day{display:inline-flex;gap:8px;align-items:center;margin-right:14px;padding:8px 10px;border:1px solid #dbe4ee;border-radius:9px;background:#f8fafc}
.tt-scroll{width:100%;max-width:100%;overflow-x:auto;overflow-y:visible;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}.tt-week{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%}.tt-week th,.tt-week td{border:1px solid #176B3A;padding:8px;vertical-align:top}.tt-week th{background:#176B3A;color:#fff;white-space:nowrap}.tt-week td{min-width:125px;height:64px;font-size:11px}.tt-break{background:#fff7ed;color:#9a3412;text-align:center;font-weight:900}.tt-class-sheet{margin:0 0 22px;break-inside:avoid}.tt-class-sheet h3{margin:0 0 8px;color:#176B3A}.tt-class-grid{min-width:max-content}.tt-class-grid th:first-child,.tt-class-grid td:first-child{min-width:105px;width:105px;position:sticky;left:0;z-index:5}.tt-class-grid th:first-child{z-index:8}.tt-class-grid .tt-day-col,.tt-class-grid .tt-day{background:#176B3A!important;color:#fff!important}.tt-class-grid .tt-lesson{background:#fff;min-width:130px;text-align:center;font-weight:700;vertical-align:top;position:relative}.tt-class-grid .tt-lesson b{display:block;font-size:14px;font-weight:900;line-height:1.25}.tt-class-grid .tt-lesson .tt-screen-teacher{display:none}.tt-class-grid .tt-lesson .tt-print-teacher{display:none}.tt-class-grid .tt-lesson span{position:absolute;right:7px;bottom:7px;left:auto;display:block;text-align:right;font-size:10px;font-weight:500;line-height:1.15;white-space:nowrap}.tt-class-grid .tt-merged-lesson{vertical-align:top!important;text-align:center!important;min-width:260px}.tt-class-grid th{font-weight:900;text-align:center!important;vertical-align:middle!important}.tt-class-grid .tt-day-col,.tt-class-grid .tt-day{font-weight:900;text-align:center!important}.tt-class-grid .tt-break-col{font-weight:900;text-align:center!important}.tt-class-grid .tt-empty{text-align:center;color:#94a3b8}.tt-class-grid .tt-break{min-width:90px;background:#fff7ed;color:#9a3412;text-align:center;font-weight:900}.tt-class-grid .tt-duration{font-weight:800;letter-spacing:.2px}.tt-class-grid .tt-merged-lesson{vertical-align:middle!important;text-align:center!important;min-width:260px}.tt-class-grid .tt-lesson{box-sizing:border-box;overflow:hidden}.tt-class-grid .tt-break-col{background:#fff7ed!important;color:#9a3412!important;min-width:90px}.tt-break-label{display:flex;flex-direction:column;align-items:center;justify-content:space-around;height:100%;min-height:320px;font-size:28px;font-weight:900;line-height:1;letter-spacing:2px;padding:10px 0;box-sizing:border-box}.tt-break-label span{display:block}.tt-print-sheets .tt-class-sheet{margin-bottom:30px}.tt-teacher-sheet{margin:0 0 24px;break-inside:avoid;page-break-after:always;background:#fff}.tt-teacher-sheet:last-child{page-break-after:auto}.tt-teacher-title{font-size:18px;font-weight:900;color:#176B3A;margin:0 0 8px;padding:8px 0}.tt-teacher-grid{width:100%!important;min-width:0!important}.tt-teacher-grid th,.tt-teacher-grid td{padding:7px}.tt-teacher-lesson{height:72px!important;position:relative!important;text-align:center!important;vertical-align:top!important}.tt-teacher-lesson b{font-size:14px!important}.tt-teacher-class{position:absolute;right:6px;bottom:5px;left:auto!important;text-align:right!important;font-size:10px!important;font-weight:800!important;white-space:nowrap;max-width:95%;overflow:hidden;text-overflow:ellipsis}.tt-teacher-room{position:absolute;left:6px;bottom:5px;font-size:9px;font-weight:600}@media print{.tt-class-grid .tt-lesson .tt-print-teacher{display:block!important;position:absolute!important;right:7px!important;bottom:7px!important;left:auto!important;text-align:right!important;font-size:10px!important;font-weight:700!important;white-space:nowrap!important;max-width:90%;overflow:hidden;text-overflow:ellipsis}.tt-print-sheets .tt-class-sheet{page-break-after:always}.tt-print-sheets .tt-class-sheet:last-child{page-break-after:auto}.tt-class-grid{min-width:0;width:100%}.tt-class-grid th,.tt-class-grid td{padding:6px;font-size:9px}.tt-class-grid .tt-lesson{min-width:0}.tt-class-grid th:first-child,.tt-class-grid td:first-child{position:static;width:auto;min-width:0}}
@media(max-width:900px){.tt-grid,.tt-form{grid-template-columns:1fr}.tt-form .wide{grid-column:auto}}
.tt-profile-active{display:inline-block;margin-left:6px;padding:3px 6px;border-radius:999px;background:#dcfce7;color:#166534;font-size:9px;font-weight:900}.tt-profile-bar{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;padding:10px 12px;margin:8px 0 10px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px}.tt-profile-inline{display:inline-flex;gap:6px;align-items:center;margin:4px 0}.tt-profile-inline .tt-field{min-width:150px}.tt-profile-bar b{color:#166534}
.tt-profile-active{display:inline-block;margin-left:6px;padding:3px 6px;border-radius:999px;background:#dcfce7;color:#166534;font-size:9px;font-weight:900}.tt-profile-bar{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;padding:10px 12px;margin:8px 0 10px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px}.tt-profile-inline{display:inline-flex;gap:6px;align-items:center;margin:4px 0}.tt-profile-inline .tt-field{min-width:150px}.tt-profile-bar b{color:#166534}
.tt-print-footer{text-align:center;margin-top:8px;padding-top:4px;border-top:1px solid #176B3A;font-size:8px;color:#176B3A;background:#fff}.tt-generated-at{font-weight:600}
@media print{.side,.top,.tt-tabs,.no-print{display:none!important}.page{padding:0!important}.tt-card{box-shadow:none;border:0}.tt-wrap{padding:0}.tt-week{min-width:0;font-size:9px}.tt-teacher-sheet{page-break-after:always;break-after:page;margin:0!important;padding:0!important}.tt-teacher-sheet:last-child{page-break-after:auto;break-after:auto}.tt-teacher-title{font-size:16px!important;padding:4px 0!important;margin:0 0 5px!important}.tt-teacher-grid{width:100%!important;table-layout:fixed!important}.tt-teacher-grid th,.tt-teacher-grid td{padding:4px!important;font-size:8px!important}.tt-teacher-grid th:first-child,.tt-teacher-grid td:first-child{width:70px!important}.tt-teacher-lesson{height:62px!important}.tt-teacher-lesson b{font-size:11px!important}.tt-teacher-class{font-size:8px!important;right:3px!important;bottom:3px!important}.tt-teacher-room{font-size:7px!important;left:3px!important;bottom:3px!important}}
.tt-placard-platform{margin-top:16px;border:2px dashed #8bb9a1;border-radius:16px;background:#f4fbf7;padding:14px}.tt-placard-platform-head{display:flex;gap:10px;justify-content:space-between;align-items:center;flex-wrap:wrap;margin-bottom:10px;color:#176B45}.tt-placard-platform-head span{font-size:.88rem;color:#64748b}.tt-placard-tray{min-height:82px;display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start}.tt-tray-placard{min-width:170px;max-width:235px;border:1px solid rgba(0,0,0,.12);border-radius:12px;padding:10px 12px;box-shadow:0 2px 7px rgba(0,0,0,.08);cursor:grab;user-select:none}.tt-tray-placard:active{cursor:grabbing}.tt-tray-placard b,.tt-tray-placard span,.tt-tray-placard small{display:block}.tt-placed-card{position:relative}.tt-placed-card.tt-card-options{outline:2px solid #176B3A;outline-offset:-2px}.tt-placed-menu{position:absolute;z-index:40;left:50%;top:50%;transform:translate(-50%,-50%);background:#fff;border:1px solid #176B3A;border-radius:9px;padding:6px;box-shadow:0 4px 14px rgba(0,0,0,.22);white-space:nowrap}.tt-placed-menu button{border:0;border-radius:7px;background:#176B3A;color:#fff;padding:7px 9px;font-size:11px;font-weight:900;cursor:pointer}.tt-tray-placard b{font-size:1rem;font-weight:900}.tt-tray-detail{display:none;margin-top:6px;padding-top:6px;border-top:1px dashed rgba(0,0,0,.18)}.tt-tray-open .tt-tray-detail{display:block}.tt-tray-detail span,.tt-tray-detail small{display:block;margin-top:3px}.tt-tray-detail span{font-weight:800}.tt-tray-detail small{opacity:.8}.tt-tray-dragging{opacity:.55}</style><script>
function timetableGeneratedStamp(){
  return new Intl.DateTimeFormat('en-KE',{
    timeZone:'Africa/Nairobi',year:'numeric',month:'2-digit',day:'2-digit',
    hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false
  }).format(new Date())+' EAT';
}
function stampTimetableFooters(root,stamp){
  (root||document).querySelectorAll('.tt-generated-at').forEach(function(el){el.textContent=stamp;});
}
// Keep the Timetable Manager as one browser-history workspace. Repeated
// lesson saves and tab changes must not force a phone user to press Back once
// for every lesson. If Back lands on another timetable page, skip it and keep
// going until the user reaches the page outside the timetable workspace.
(function(){
  function isTimetableUrl(url){
    try{return new URL(url,window.location.href).pathname==='/app/timetable';}
    catch(e){return false;}
  }
  window.addEventListener('popstate',function(){
    if(isTimetableUrl(window.location.href)){
      window.setTimeout(function(){window.history.go(-1);},0);
    }
  });
  document.addEventListener('submit',function(event){
    var form=event.target;
    if(!form)return;
    var action=form.getAttribute('action')||'';
    if(action.indexOf('/app/timetable/lesson/save')===-1 && action.indexOf('/app/timetable/lesson/delete/')===-1)return;
    event.preventDefault();
    var data=new FormData(form);
    var submitter=event.submitter;
    if(submitter && submitter.name && !data.has(submitter.name))data.append(submitter.name,submitter.value||'');
    fetch(new URL(action,window.location.href).toString(),{
      method:'POST',body:data,credentials:'same-origin',redirect:'follow',cache:'no-store'
    }).then(function(response){
      window.location.replace(response.url||'/app/timetable?tab=lessons');
    }).catch(function(){window.location.href='/app/timetable?tab=lessons';});
  },true);
})();
function printClassTimetables(){
  stampTimetableFooters(document,timetableGeneratedStamp());
  window.print();
}
function printTeacherSheet(id){
  const source=document.getElementById(id);
  if(!source){return;}
  const win=window.open('', '_blank', 'width=1200,height=800');
  if(!win){window.print();return;}
  const styles=Array.from(document.querySelectorAll('style')).map(s=>s.outerHTML).join('');
  const clone=source.cloneNode(true);
  clone.querySelectorAll('.no-print').forEach(el=>el.remove());
  stampTimetableFooters(clone,timetableGeneratedStamp());
  win.document.open();
  win.document.write('<!doctype html><html><head><meta charset=\"utf-8\"><title>Teacher Timetable</title>'+styles+'<style>@page{size:A4 landscape;margin:8mm}body{margin:0;background:#fff}.tt-teacher-sheet{page-break-after:auto!important;break-after:auto!important;margin:0!important}.tt-teacher-grid{width:100%!important;table-layout:fixed!important}</style></head><body>'+clone.outerHTML+'</body></html>');
  win.document.close();
  win.focus();
  setTimeout(function(){win.print();},300);
}
</script>"""


def _profile_bar(con,sid,tab):
    rows=con.execute("SELECT id,name,active FROM timetable_profiles WHERE school_id=? ORDER BY active DESC,id",(sid,)).fetchall()
    current=next((r for r in rows if int(r["active"] or 0)),rows[0] if rows else None)
    if not current:return ""
    opts="".join(f"<option value='{int(r['id'])}' {'selected' if int(r['id'])==int(current['id']) else ''}>{escape(str(r['name']))}</option>" for r in rows)
    return f"""<div class='tt-profile-bar'><div><b>🗓️ Current timetable:</b> {escape(str(current['name']))}<div class='tt-muted'>Periods, times, breaks and placements are isolated to this timetable.</div></div>
<form method='post' action='/app/timetable/profile/switch-select'><input type='hidden' name='tab' value='{escape(tab)}'><select class='tt-field' name='profile_id' onchange='this.form.submit()'>{opts}</select></form>
<a class='tt-btn alt' href='/app/timetable?tab=profiles'>Manage Timetables</a></div>"""

def _layout(request, tab, content, con=None, sid=None):
    profile_bar=_profile_bar(con,sid,tab) if con is not None and sid is not None else ""
    return _page(request, "Timetable Manager", f"<div class='tt-wrap'><h1>🗓️ Timetable Manager</h1><div class='tt-muted'>A complete school timetable workspace for setup, lesson cards, availability, generation, verification, manual adjustment and printing.</div>{_notice(request)}{profile_bar}{_tabs(tab)}{content}{_base_css()}</div>")


@router.get("/app/timetable", response_class=HTMLResponse)
def timetable_manager(request: Request):
    sid, con, response = _guard(request, "timetable.view")
    if response:
        return response
    tab = _selected_tab(request)
    try:
        if tab == "profiles": body = _profiles(request, con, sid)
        elif tab == "setup": body = _setup(request, con, sid)
        elif tab == "periods": body = _periods(request, con, sid)
        elif tab == "subjects": body = _subjects(con, sid)
        elif tab == "teachers": body = _teachers(con, sid)
        elif tab == "classes": body = _classes(con, sid)
        elif tab == "rooms": body = _rooms(con, sid)
        elif tab == "lessons": body = _lessons(request, con, sid)
        elif tab == "availability": body = _availability(request, con, sid)
        elif tab == "generate": body = _generate(con, sid)
        elif tab == "verify": body = _verify(con, sid)
        elif tab == "teacher_sheets":
            teacher_id = request.query_params.get("teacher_id", "")
            teacher_rows = con.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (sid,)).fetchall()
            selected_id = int(teacher_id) if str(teacher_id).isdigit() else (int(teacher_rows[0]["id"]) if teacher_rows else None)
            teacher_opts = "".join(
                f"<option value='{int(t['id'])}' {'selected' if selected_id == int(t['id']) else ''}>{escape(str(t['name']))}</option>"
                for t in teacher_rows
            )
            body = f"""<div class='tt-card'><h2>👨‍🏫 Teacher Weekly Timetable</h2>
<div class='tt-muted'>One teacher is shown on one complete Monday–Friday sheet containing ALL lessons assigned to that teacher. The class/stream appears at the far bottom-right of each subject period.</div>
<form method='get' class='tt-form' style='margin-top:12px'>
<input type='hidden' name='tab' value='teacher_sheets'>
<label><span class='tt-label'>Select Teacher</span><select class='tt-field' name='teacher_id' onchange='this.form.submit()'><option value=''>Select teacher</option>{teacher_opts}</select></label>
<div class='no-print'><button class='tt-btn' type='submit'>👨‍🏫 View Teacher Sheet</button></div>
</form>
<div class='no-print' style='margin:12px 0'><button class='tt-btn' onclick='printTeacherSheet("teacher-sheet-{selected_id}")'>🖨️ Print This Teacher Sheet</button></div>
<div class='tt-print-sheets'>{_teacher_sheets(con, sid, selected_id) if selected_id is not None else "<div class='tt-notice bad'>No teachers found.</div>"}</div></div>"""
        elif tab == "print": body = _print_view(con, sid)
        else:
            try:
                body = _timetable(request, con, sid)
            except Exception as exc:
                # Last-resort read-only renderer. A problem with an optional
                # timetable relation must never prevent the school from seeing
                # the saved physical timetable.
                try:
                    rows = con.execute("""SELECT s.day_name,s.period_no,s.start_time,s.end_time,
                        s.lesson_id,l.class_id,l.subject_id,
                        c.name class_name,c.stream,sub.name subject,sub.code subject_code,sub.initial subject_initial
                        FROM timetable_slots s
                        JOIN timetable_lessons l ON l.id=s.lesson_id
                        JOIN classes c ON c.id=l.class_id
                        JOIN subjects sub ON sub.id=l.subject_id
                        WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id) ORDER BY c.name,c.stream,s.day_name,s.period_no""",(sid,)).fetchall()
                    p_rows = _profile_periods(con,sid)
                    d_rows = [r for r in _profile_days(con,sid) if int(r["enabled"] or 0)]
                    day_names=[str(x["name"]) for x in d_rows] or list(DEFAULT_DAYS)
                    grouped={}
                    for r in rows:
                        grouped.setdefault((int(r["class_id"]),str(r["class_name"]),str(r["stream"] or "")),{})[(str(r["day_name"]),int(r["period_no"]))]=r
                    sheets=[]
                    for (cid,cname,cstream),grid in grouped.items():
                        head="<tr><th>DAY</th>"+"".join(
                            f"<th>P{int(p['period_no'])}<br><small>{escape(str(p['start_time']))}-{escape(str(p['end_time']))}</small></th>"
                            for p in p_rows
                        )+"</tr>"
                        body_rows=[]
                        for day in day_names:
                            cells=[f"<th>{escape(day).upper()}</th>"]
                            for p in p_rows:
                                r=grid.get((day,int(p["period_no"])))
                                cells.append(
                                    f"<td class='tt-lesson'><b>{escape(str(r['subject_initial'] or r['subject_code'] or r['subject']))}</b></td>"
                                    if r else "<td class='tt-empty'>—</td>"
                                )
                            body_rows.append("<tr>"+"".join(cells)+"</tr>")
                        label=f"{cname}{(' — '+cstream) if cstream else ''}"
                        sheets.append(
                            f"<div class='tt-class-sheet'><h3>🏫 {escape(label)}</h3>"
                            f"<div class='tt-scroll'><table class='tt-week tt-class-grid'>{head}{''.join(body_rows)}</table></div></div>"
                        )
                    empty_notice = '<div class="tt-notice bad">No saved timetable placements found.</div>'
                    body=f"<div class='tt-card'><h2>🗓️ Class Timetable</h2><div class='tt-notice ok'>Showing the saved timetable in safe view.</div>{''.join(sheets) or empty_notice}</div>"
                except Exception:
                    body = f"<div class='tt-card'><h2>🗓️ Class Timetable</h2><div class='tt-notice bad'>Unable to display the timetable. The saved timetable data is still protected.</div></div>"
        return _layout(request, tab, body, con, sid)
    finally:
        con.close()


def _profiles(request, con, sid):
    rows=con.execute("SELECT * FROM timetable_profiles WHERE school_id=? ORDER BY active DESC,id",(sid,)).fetchall()
    current=_active_profile_id(con,sid)
    table=[]
    for p in rows:
        pid=int(p["id"])
        active=int(p["active"] or 0)
        slots=int(con.execute("SELECT COUNT(*) c FROM timetable_slots WHERE school_id=? AND profile_id=?",(sid,pid)).fetchone()["c"] or 0)
        badge="<span class='tt-profile-active'>ACTIVE</span>" if active else ""
        switch="" if active else f"<form method='post' action='/app/timetable/profile/switch/{pid}' style='display:inline'><input type='hidden' name='tab' value='profiles'><button class='tt-btn alt'>Use</button></form>"
        duplicate=f"<form method='post' action='/app/timetable/profile/duplicate/{pid}' style='display:inline'><button class='tt-btn'>Duplicate</button></form>"
        rename=f"<form method='post' action='/app/timetable/profile/rename/{pid}' class='tt-profile-inline'><input class='tt-field' name='name' value='{escape(str(p['name']))}' required><button class='tt-btn alt'>Rename</button></form>"
        delete="" if pid==current or len(rows)<=1 else f"<form method='post' action='/app/timetable/profile/delete/{pid}' style='display:inline' onsubmit='return confirm(&quot;Delete this saved timetable profile? Lesson cards will remain.&quot;)'><button class='tt-btn danger'>Delete</button></form>"
        table.append(f"<tr><td><b>{escape(str(p['name']))}</b> {badge}<br><small>{escape(str(p['description'] or ''))}</small></td><td>{'Yes' if active else '—'}</td><td>{len(json.loads(str(p['periods_json'] or '[]')))}</td><td>{slots}</td><td>{switch} {duplicate} {delete}</td></tr>")
    return f"""<div class='tt-card'><h2>🗂️ Timetable Profiles</h2>
<div class='tt-muted'>Create completely independent schedules such as Weekday, Saturday, Weekend, Exam or Special Activity. Each profile keeps its own days, period times, breaks and lesson placements. The existing timetable is preserved as the first profile.</div>
<form method='post' action='/app/timetable/profile/create' class='tt-form' style='margin-top:12px'><label><span class='tt-label'>New timetable name</span><input class='tt-field' name='name' required placeholder='Saturday Timetable'></label><label class='wide'><span class='tt-label'>Description</span><input class='tt-field' name='description' placeholder='Different Saturday schedule'></label><div><button class='tt-btn'>➕ Create Timetable</button></div></form></div>
<div class='tt-card'><h3>Saved Timetables</h3><div class='tt-scroll'><table class='tt-table'><thead><tr><th>Name</th><th>Active</th><th>Periods</th><th>Placements</th><th>Actions</th></tr></thead><tbody>{''.join(table)}</tbody></table></div></div>"""


def _setup(request, con, sid):
    profile=_active_profile(con,sid)
    enabled=_profile_days(con,sid)
    complexity=str(profile["complexity"] if profile else "normal")
    relaxation=str(profile["relaxation"] if profile else "relaxed")
    days="".join(f"<label class='tt-day'><input type='checkbox' name='days' value='{escape(str(d['name']))}' {'checked' if int(d['enabled'] or 0) else ''}>{escape(str(d['name']))}</label>" for d in enabled)
    return f"""<div class='tt-card'><h2>⚙️ {escape(str(profile['name']))} Setup</h2><div class='tt-muted'>This setup belongs only to the selected timetable profile. Changing it does not change another saved timetable.</div>
<form method='post' action='/app/timetable/setup/save' class='tt-form' style='margin-top:14px'><div class='full'><span class='tt-label'>Teaching days</span>{days}</div>
<label><span class='tt-label'>Generation complexity</span><select name='complexity' class='tt-field'><option value='normal' {'selected' if complexity=='normal' else ''}>Normal</option><option value='large' {'selected' if complexity=='large' else ''}>Large</option><option value='huge' {'selected' if complexity=='huge' else ''}>Huge</option></select></label>
<label><span class='tt-label'>Constraint mode</span><select name='relaxation' class='tt-field'><option value='draft' {'selected' if relaxation=='draft' else ''}>Draft</option><option value='relaxed' {'selected' if relaxation=='relaxed' else ''}>Allow relaxation</option><option value='strict' {'selected' if relaxation=='strict' else ''}>Strict</option></select></label><div><button class='tt-btn'>💾 Save Setup</button></div></form></div>
<div class='tt-grid'><div class='tt-stat'><b>{sum(1 for d in enabled if int(d['enabled'] or 0))}</b>Teaching days</div><div class='tt-stat'><b>{len(_profile_periods(con,sid))}</b>Periods</div><div class='tt-stat'><b>{len(_profile_breaks(con,sid))}</b>Breaks</div><div class='tt-stat'><b>Independent</b>Profile configuration</div></div>"""


def _periods(request, con, sid):
    settings=_profile_settings(con,sid)
    periods=_profile_periods(con,sid)
    breaks=_profile_breaks(con,sid)
    ppd=int(settings["periods_per_day"] or len(periods) or 7)
    pm=int(settings["period_minutes"] or 40)
    rows="".join(f"<tr><td><b>Period {int(p['period_no'])}</b></td><td><input class='tt-field' type='time' name='start_{int(p['period_no'])}' value='{escape(str(p['start_time']))}'></td><td><input class='tt-field' type='time' name='end_{int(p['period_no'])}' value='{escape(str(p['end_time']))}'></td></tr>" for p in periods)
    br="".join(f"<tr><td>{escape(str(b['name']))}</td><td>{escape(str(b['start_time']))}</td><td>{escape(str(b['end_time']))}</td><td><form method='post' action='/app/timetable/break/delete/{b['id']}' onsubmit='return confirm(&quot;Delete this break?&quot;)'><button class='tt-btn danger'>🗑️</button></form></td></tr>" for b in breaks) or "<tr><td colspan='4'>No breaks saved for this timetable.</td></tr>"
    return f"""<div class='tt-card'><h2>🕐 Periods & Bells — {escape(str(settings['name']))}</h2><div class='tt-muted'>These period times and breaks belong only to the active timetable profile. Weekday and Saturday profiles can have completely different schedules.</div>
<form method='post' action='/app/timetable/periods/settings' class='tt-form' style='margin-top:12px'><label><span class='tt-label'>Periods per day</span><input class='tt-field' name='periods_per_day' type='number' min='1' max='12' value='{ppd}' required></label><label><span class='tt-label'>Default period minutes</span><input class='tt-field' name='period_minutes' type='number' min='20' max='180' value='{pm}' required></label><label><span class='tt-label'>Teaching periods per week</span><input class='tt-field' type='number' value='{int(settings['periods_per_week'] or 0)}' readonly disabled><small class='tt-muted'>Calculated from this profile's enabled days × periods.</small></label><input type='hidden' name='periods_per_week' value='{int(settings['periods_per_week'] or 0)}'><div><button class='tt-btn'>💾 Save</button></div></form></div>
<div class='tt-card'><h3>Bell / Period Times</h3><form method='post' action='/app/timetable/periods/save'><div class='tt-scroll'><table class='tt-table'><thead><tr><th>Period</th><th>Start</th><th>End</th></tr></thead><tbody>{rows}</tbody></table></div><button class='tt-btn' style='margin-top:10px'>💾 Save Period Times</button></form></div>
<div class='tt-card'><h3>☕ Breaks for {escape(str(settings['name']))}</h3><form method='post' action='/app/timetable/break/save' class='tt-form'><label><span class='tt-label'>Break name</span><input class='tt-field' name='name' required placeholder='Tea Break / Lunch'></label><label><span class='tt-label'>Start</span><input class='tt-field' name='start_time' type='time' required></label><label><span class='tt-label'>End</span><input class='tt-field' name='end_time' type='time' required></label><div><button class='tt-btn'>💾 Save Break</button></div></form><div class='tt-scroll' style='margin-top:10px'><table class='tt-table'><thead><tr><th>Name</th><th>Start</th><th>End</th><th></th></tr></thead><tbody>{br}</tbody></table></div></div>"""


def _weekly_period_capacity(con, sid):
    day_count=sum(1 for x in _profile_days(con,sid) if int(x["enabled"] or 0))
    period_count=len(_profile_periods(con,sid))
    return int(day_count or 0)*int(period_count or 0)



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
    rows = con.execute("""SELECT l.*,c.name class_name,c.stream,sub.name subject,sub.code subject_code,sub.initial subject_initial,t.name teacher,r.name room
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
    days=[r["name"] for r in [r for r in _profile_days(con,sid) if int(r["enabled"] or 0)]]
    periods=_profile_periods(con,sid)
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


def _weekly_period_capacity(con, sid):
    """Physical teaching periods in one school week; breaks are not periods."""
    day_count=con.execute("SELECT COUNT(*) c FROM timetable_days WHERE school_id=? AND enabled=1",(sid,)).fetchone()["c"]
    period_count=con.execute("SELECT COUNT(*) c FROM timetable_periods WHERE school_id=?",(sid,)).fetchone()["c"]
    return int(day_count or 0) * int(period_count or 0)


def _generate(con, sid):
    settings=con.execute("SELECT * FROM timetable_manager_settings WHERE school_id=?", (sid,)).fetchone()
    classes=con.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
    lesson_count=con.execute("SELECT COUNT(*) c FROM timetable_lessons WHERE school_id=?", (sid,)).fetchone()["c"]
    slot_count=con.execute("SELECT COUNT(*) c FROM timetable_slots WHERE school_id=? AND profile_id=timetable_active_profile(school_id)", (sid,)).fetchone()["c"]
    weekly_capacity=_weekly_period_capacity(con,sid)
    latest_run=con.execute("""SELECT status,placed,requested,message,created_at
        FROM timetable_generation_runs WHERE school_id=? ORDER BY id DESC LIMIT 1""",(sid,)).fetchone()
    opts="".join(f"<option value='{c['id']}'>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    complexity=str(settings["complexity"] if settings else "normal")
    relaxation=str(settings["relaxation"] if settings else "relaxed")
    run_notice=""
    if latest_run:
        run_notice=f"<div class='tt-notice {'ok' if str(latest_run['status']) in ('complete','relaxed') else ('bad' if str(latest_run['status'])=='failed' else 'ok')}'>📌 Last generation: {escape(str(latest_run['status']).title())} — {int(latest_run['placed'] or 0)} of {int(latest_run['requested'] or 0)} periods. {escape(str(latest_run['message'] or ''))}</div>"
    return f"""<div class='tt-card'><h2>🚀 Generate Timetable</h2><div class='tt-muted'>Generate from lesson cards, periods, breaks, rooms and constraints. Weekly capacity is the physical teaching periods per class; breaks are intervals between periods and never count toward that capacity.</div>{run_notice}
<form method='post' action='/app/timetable/generate/new' class='tt-form' style='margin-top:12px'>
<label><span class='tt-label'>Class filter (optional)</span><select class='tt-field' name='class_id'><option value=''>All classes</option>{opts}</select></label>
<label><span class='tt-label'>Mode</span><select class='tt-field' name='mode'><option value='draft'>Draft</option><option value='relaxed' {'selected' if relaxation=='relaxed' else ''}>Allow relaxation</option><option value='strict' {'selected' if relaxation=='strict' else ''}>Strict</option></select></label>
<label><span class='tt-label'>Complexity</span><select class='tt-field' name='complexity'><option value='normal' {'selected' if complexity=='normal' else ''}>Normal</option><option value='large' {'selected' if complexity=='large' else ''}>Large</option><option value='huge' {'selected' if complexity=='huge' else ''}>Huge</option></select></label>
<label class='tt-check'><input type='checkbox' name='replace_existing' value='1' checked> Replace unlocked generated placements</label>
<div><button class='tt-btn' type='submit' onclick="this.disabled=true;this.innerText='⏳ Starting…';this.form.submit();return false;">🚀 Generate</button><div class='tt-muted' style='margin-top:8px'>Generation runs in the background so this page will not stall while the timetable solver works.</div></div></form></div>
<div class='tt-grid'><div class='tt-stat'><b>{int(lesson_count)}</b>Lesson cards</div><div class='tt-stat'><b>{int(weekly_capacity)}</b>Teaching periods / class / week</div><div class='tt-stat'><b>Breaks excluded</b>Weekly capacity rule</div><div class='tt-stat'><b>{escape(relaxation.title())}</b>Default mode</div></div>"""


def _verify(con, sid):
    lessons=con.execute("SELECT id,lessons_per_week,duration FROM timetable_lessons WHERE school_id=?", (sid,)).fetchall()
    placements=con.execute("""SELECT s.lesson_id,l.lessons_per_week,l.duration
        FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id
        WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id)""",(sid,)).fetchall()
    placed_occurrences={}
    placed_periods={}
    for r in placements:
        lid=int(r["lesson_id"])
        placed_occurrences[lid]=placed_occurrences.get(lid,0)+1
        placed_periods[lid]=placed_periods.get(lid,0)+max(1,int(r["duration"] or 1))
    issues=[]
    for l in lessons:
        lid=int(l["id"])
        required_occurrences=int(l["lessons_per_week"] or 0)
        required_periods=required_occurrences*max(1,int(l["duration"] or 1))
        actual_occurrences=int(placed_occurrences.get(lid,0))
        actual_periods=int(placed_periods.get(lid,0))
        missing_occ=max(0,required_occurrences-actual_occurrences)
        missing_periods=max(0,required_periods-actual_periods)
        if missing_occ or missing_periods:
            issues.append(
                f"Lesson card {lid}: {actual_occurrences} of {required_occurrences} weekly occurrences "
                f"placed ({actual_periods} of {required_periods} periods); "
                f"{missing_occ} occurrence(s) / {missing_periods} period(s) missing."
            )
    # Hard collision checks.
    rows=con.execute("""SELECT s.*,l.class_id,l.teacher_id,l.room_id,l.duration,l.subject_id
        FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id
        WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id) ORDER BY s.day_name,s.period_no""",(sid,)).fetchall()
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
    periods = _profile_periods(con,sid)
    days = [str(r["name"]) for r in _profile_days(con,sid) if int(r["enabled"] or 0)]
    breaks = _profile_breaks(con,sid)

    rows = con.execute("""SELECT s.*,l.class_id,l.subject_id,l.teacher_id,l.room_id,l.duration,
        c.name class_name,c.stream,sub.name subject,sub.code subject_code,sub.initial subject_initial,t.name teacher,r.name room
        FROM timetable_slots s
        JOIN timetable_lessons l ON l.id=s.lesson_id
        JOIN classes c ON c.id=l.class_id
        JOIN subjects sub ON sub.id=l.subject_id
        LEFT JOIN teachers t ON t.id=l.teacher_id
        LEFT JOIN timetable_rooms r ON r.id=s.room_id
        WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id)
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



def _subject_initial(lesson):
    """Return the subject initial configured in the school's Subjects module."""
    initial = str(lesson.get("subject_initial") or "").strip()
    if initial:
        return initial
    code = str(lesson.get("subject_code") or "").strip()
    if code:
        return code
    name = str(lesson.get("subject") or "").strip()
    return name[:4].upper() if name else "SUB"

def _teacher_placard_color(teacher_id):
    """Stable soft color for a teacher's lesson placard."""
    palette=("#DBEAFE","#DCFCE7","#FEF3C7","#FCE7F3","#EDE9FE","#CFFAFE","#FFEDD5","#E0F2FE","#F3E8FF","#ECFCCB","#FDE2E2","#D1FAE5")
    try:
        return palette[(int(teacher_id or 0) * 17) % len(palette)]
    except Exception:
        return palette[0]

def _class_grid_html(class_row, periods, days, breaks, grid, show_title=True):
    """Render an aSc-style class grid with true merged double/triple lessons."""
    class_label = f"{class_row['name']}{(' — '+str(class_row['stream'])) if class_row['stream'] else ''}"

    period_items = [
        ("period", _time_to_min(str(p["start_time"])), _time_to_min(str(p["end_time"])), p)
        for p in periods
    ]
    break_items = [
        ("break", _time_to_min(str(b["start_time"])), _time_to_min(str(b["end_time"])), b)
        for b in breaks
    ]
    break_ranges = [(x[1], x[2]) for x in break_items]

    visible_timeline = sorted(
        [x for x in period_items
         if not any(x[1] < be and x[2] > bs for bs, be in break_ranges)] + break_items,
        key=lambda x: (x[1], 0 if x[0] == "period" else 1, x[2])
    )

    head = "<tr><th class='tt-day-col'>DAY</th>" + "".join(
        (
            f"<th class='tt-break-col'><b>{escape(str(x[3]['name']))}</b><br><small>{escape(str(x[3]['start_time']))}-{escape(str(x[3]['end_time']))}</small></th>"
            if x[0] == "break" else
            f"<th>P{int(x[3]['period_no'])}<br><small>{escape(str(x[3]['start_time']))}-{escape(str(x[3]['end_time']))}</small></th>"
        )
        for x in visible_timeline
    ) + "</tr>"

    # A lesson is stored once at its starting period with duration=2/3.
    # Render it as ONE merged cell across the physical periods it occupies.
    # This prevents a double lesson from appearing as "subject + blank".
    start_cells = {}
    occupied_periods = {}

    for (day_name, start_pno), lesson in grid.items():
        duration = max(1, int(lesson["duration"] or 1))
        start_cells[(str(day_name), int(start_pno))] = (lesson, duration)
        for offset in range(duration):
            occupied_periods[(str(day_name), int(start_pno) + offset)] = (
                lesson, offset + 1, duration
            )

    body = []
    for day_index, day in enumerate(days):
        row_cells = [f"<th class='tt-day'>{escape(str(day)).upper()}</th>"]
        skip_periods = set()

        break_index = 0
        total_breaks = len(breaks)
        for kind, st, et, item in visible_timeline:
            if kind == "break":
                # Merge each break column vertically across Monday-Friday and
                # label the merged cell according to its break position.
                break_index += 1
                label = "BREAK" if break_index in (1, 2) else "LUNCH" if break_index == 3 else "BREAK"
                if break_index == total_breaks and total_breaks >= 4:
                    label = "GAMES"
                label_html = "".join(f"<span>{escape(ch)}</span>" for ch in label)
                if day_index == 0:
                    row_cells.append(
                        f"<td class='tt-break' aria-label='{escape(label)}' rowspan='{len(days)}'>"
                        f"<div class='tt-break-label'>{label_html}</div></td>"
                    )
                continue

            pno = int(item["period_no"])

            # The second/third physical period of a merged lesson has already
            # been emitted as part of the starting cell.
            if pno in skip_periods:
                continue

            entry = start_cells.get((str(day), pno))
            if entry:
                lesson, duration = entry
                # Only merge across periods that are actually consecutive
                # visible teaching-period columns. Breaks cannot be crossed
                # because the generator rejects such placements.
                span_periods = []
                for offset in range(duration):
                    target = pno + offset
                    if any(
                        x[0] == "period" and int(x[3]["period_no"]) == target
                        for x in visible_timeline
                    ):
                        span_periods.append(target)

                span = len(span_periods)
                if span < duration:
                    span = 1

                for target in span_periods[1:]:
                    skip_periods.add(target)

                teachers = str(lesson["teacher"] or "")
                room = str(lesson["room"] or "")
                label = (
                    "<br><small class='tt-duration'>DOUBLE LESSON</small>"
                    if duration == 2 else
                    "<br><small class='tt-duration'>TRIPLE LESSON</small>"
                    if duration >= 3 else ""
                )
                lesson_id = int(lesson["id"])
                lesson_teacher_id = lesson["teacher_id"]
                lesson_subject = escape(_subject_initial(lesson))
                row_cells.append(
                    f"<td class='tt-lesson tt-merged-lesson tt-draggable-lesson tt-placed-card' draggable='true' colspan='{span}' data-slot-id='{lesson_id}' data-day='{escape(str(day))}' data-period='{pno}' style='background:{_teacher_placard_color(lesson_teacher_id)}' title='Click lesson card for options'>"
                    f"<b>{lesson_subject}</b>"
                    f"<span class='tt-screen-teacher'>{escape(teachers)}</span>"
                    f"<span class='tt-print-teacher'>{escape(teachers)}</span>"
                    f"{label}</td>"
                )
                continue

            # A physical period occupied by a lesson that starts earlier should
            # already have been merged into that earlier cell.
            occupied = occupied_periods.get((str(day), pno))
            if occupied:
                continue

            row_cells.append(f"<td class='tt-empty tt-drop-slot' data-day='{escape(str(day))}' data-period='{pno}' title='Drop lesson here'>—</td>")

        body.append("<tr>" + "".join(row_cells) + "</tr>")

    title = f"<h3>🏫 {escape(class_label)}</h3>" if show_title else ""
    return (
        f"<div class='tt-class-sheet'>{title}"
        f"<div class='tt-scroll'><table class='tt-week tt-class-grid'>{head}{''.join(body)}</table></div>"
        f"<div class='tt-print-footer'>D-School Management System · Generated: <span class='tt-generated-at'></span></div></div>"
    )

def _teacher_grid_html(teacher_row, periods, days, breaks, grid):
    """Render one teacher's complete Monday-Friday timetable on one sheet."""
    teacher_label = str(teacher_row["name"] or "Teacher")
    period_items = [("period", _time_to_min(str(p["start_time"])), _time_to_min(str(p["end_time"])), p) for p in periods]
    break_items = [("break", _time_to_min(str(b["start_time"])), _time_to_min(str(b["end_time"])), b) for b in breaks]
    break_ranges = [(x[1], x[2]) for x in break_items]
    visible_timeline = sorted(
        [x for x in period_items if not any(x[1] < be and x[2] > bs for bs, be in break_ranges)] + break_items,
        key=lambda x: (x[1], 0 if x[0] == "period" else 1, x[2])
    )
    head = "<tr><th class='tt-day-col'>DAY</th>" + "".join(
        (f"<th class='tt-break-col'><b>{escape(str(x[3]['name']))}</b><br><small>{escape(str(x[3]['start_time']))}-{escape(str(x[3]['end_time']))}</small></th>"
         if x[0] == "break" else
         f"<th>P{int(x[3]['period_no'])}<br><small>{escape(str(x[3]['start_time']))}-{escape(str(x[3]['end_time']))}</small></th>")
        for x in visible_timeline
    ) + "</tr>"
    start_cells = {}
    occupied_periods = {}
    for key, lesson in grid.items():
        duration = max(1, int(lesson["duration"] or 1))
        start_cells[key] = (lesson, duration)
        for offset in range(duration):
            occupied_periods[(str(lesson["day_name"]), int(lesson["period_no"]) + offset)] = (lesson, offset + 1, duration)
    body = []
    for day_index, day in enumerate(days):
        row_cells = [f"<th class='tt-day'>{escape(str(day)).upper()}</th>"]
        skip_periods = set()
        break_index = 0
        total_breaks = len(breaks)
        for kind, st, et, item in visible_timeline:
            if kind == "break":
                # Merge each break column vertically across Monday-Friday and
                # label the merged cell according to its break position.
                break_index += 1
                label = "BREAK" if break_index in (1, 2) else "LUNCH" if break_index == 3 else "BREAK"
                if break_index == total_breaks and total_breaks >= 4:
                    label = "GAMES"
                label_html = "".join(f"<span>{escape(ch)}</span>" for ch in label)
                if day_index == 0:
                    row_cells.append(
                        f"<td class='tt-break' aria-label='{escape(label)}' rowspan='{len(days)}'>"
                        f"<div class='tt-break-label'>{label_html}</div></td>"
                    )
                continue
            pno = int(item["period_no"])
            if pno in skip_periods:
                continue
            entry = start_cells.get((str(day), pno))
            if entry:
                lesson, duration = entry
                span_periods = [pno + offset for offset in range(duration) if any(x[0] == "period" and int(x[3]["period_no"]) == pno + offset for x in visible_timeline)]
                span = max(1, len(span_periods))
                for target in span_periods[1:]:
                    skip_periods.add(target)
                classes = str(lesson.get("class_label") or "Class")
                room = str(lesson.get("room") or "")
                label = "<br><small class='tt-duration'>DOUBLE LESSON</small>" if duration == 2 else "<br><small class='tt-duration'>TRIPLE LESSON</small>" if duration >= 3 else ""
                room_html = f"<small class='tt-teacher-room'>{escape(room)}</small>" if room else ""
                row_cells.append(
                    f"<td class='tt-lesson tt-teacher-lesson' colspan='{span}'><b>{escape(_subject_initial(lesson))}</b>{label}"
                    f"<span class='tt-teacher-class'>{escape(classes)}</span>{room_html}</td>"
                )
                continue
            if (str(day), pno) in occupied_periods:
                continue
            row_cells.append("<td class='tt-empty'>—</td>")
        body.append("<tr>" + "".join(row_cells) + "</tr>")
    sheet_id = 'teacher-sheet-' + str(teacher_row['id'])
    return f"<div id='{sheet_id}' class='tt-teacher-sheet'><div class='tt-teacher-title'>👨‍🏫 {escape(teacher_label)} <span class='no-print' style='float:right'><button type='button' class='tt-btn alt tt-teacher-print-btn' onclick=\"printTeacherSheet('{sheet_id}')\">🖨️ Print This Sheet</button></span></div><div class='tt-scroll'><table class='tt-week tt-class-grid tt-teacher-grid'>{head}{''.join(body)}</table></div><div class='tt-print-footer'>D-School Management System · Generated: <span class='tt-generated-at'></span></div></div>"


def _teacher_sheets(con, sid, selected_teacher_id=None):
    """Build one complete weekly timetable sheet for the selected teacher."""
    teachers = con.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (sid,)).fetchall()
    if selected_teacher_id is not None:
        teachers = [t for t in teachers if int(t["id"]) == int(selected_teacher_id)]
    periods = _profile_periods(con,sid)
    days = [str(r["name"]) for r in _profile_days(con,sid) if int(r["enabled"] or 0)]
    breaks = _profile_breaks(con,sid)
    rows = con.execute("""SELECT s.*,l.class_id,l.subject_id,l.teacher_id,l.room_id,l.duration,
        c.name class_name,c.stream,sub.name subject,r.name room
        FROM timetable_slots s
        JOIN timetable_lessons l ON l.id=s.lesson_id
        JOIN classes c ON c.id=l.class_id
        JOIN subjects sub ON sub.id=l.subject_id
        LEFT JOIN timetable_rooms r ON r.id=s.room_id
        WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id) ORDER BY s.day_name,s.period_no""", (sid,)).fetchall()
    class_cache = {}
    for row in rows:
        lid = int(row["lesson_id"])
        if lid not in class_cache:
            attached = con.execute("""SELECT c.name,c.stream FROM timetable_lesson_classes lc
                JOIN classes c ON c.id=lc.class_id WHERE lc.school_id=? AND lc.lesson_id=? ORDER BY c.name,c.stream""", (sid, lid)).fetchall()
            class_cache[lid] = ", ".join(f"{str(x['name'])}{(' '+str(x['stream'])) if x['stream'] else ''}" for x in attached) if attached else f"{str(row['class_name'])}{(' '+str(row['stream'])) if row['stream'] else ''}"
    grids = {int(t["id"]): {} for t in teachers}
    for row in rows:
        lid = int(row["lesson_id"])
        tids = {int(x["teacher_id"]) for x in con.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?", (sid, lid)).fetchall()}
        if row["teacher_id"]:
            tids.add(int(row["teacher_id"]))
        lesson = dict(row)
        lesson["class_label"] = class_cache[lid]
        for tid in tids:
            if tid in grids:
                grids[tid][(str(row["day_name"]), int(row["period_no"]))] = lesson
    return "".join(_teacher_grid_html(t, periods, days, breaks, grids[int(t["id"])]) for t in teachers) or "<div class='tt-notice bad'>No teachers found.</div>"



def _master_timetable_html(classes, periods, days, grids):
    """Render one school-wide drag/drop timetable: classes down, days and periods across."""
    day_head = "".join(
        f"<th class='tt-master-day' colspan='{len(periods)}'>{escape(str(day)).upper()}</th>"
        for day in days
    )
    period_head = "".join(
        f"<th class='tt-master-period'>P{int(p['period_no'])}<br><small>{escape(str(p['start_time']))}-{escape(str(p['end_time']))}</small></th>"
        for _day in days for p in periods
    )
    rows = []
    for cls in classes:
        cid = int(cls["id"])
        grid = grids.get(cid, {})
        occupied = {}
        for (key, lesson0) in grid.items():
            start_day, start_pno = key
            dur0 = max(1, int(lesson0["duration"] or 1))
            for off0 in range(dur0):
                occupied[(str(start_day), int(start_pno)+off0)] = lesson0
        cells = [f"<th class='tt-master-class'>{escape(str(cls['name']))}{(' — '+escape(str(cls['stream']))) if cls['stream'] else ''}</th>"]
        for day in days:
            for p in periods:
                pno = int(p["period_no"])
                lesson = occupied.get((str(day), pno))
                if lesson:
                    start_pno = int(lesson["period_no"])
                    duration = max(1, int(lesson["duration"] or 1))
                    if pno != start_pno and pno < start_pno + duration:
                        cells.append(f"<td class='tt-master-cell tt-master-continuation' title='Continuation of {escape(_subject_initial(lesson))}'>↳</td>")
                    else:
                        lid = int(lesson["id"])
                        teacher_id = lesson["teacher_id"]
                        subject = escape(_subject_initial(lesson))
                        duration_label = " · DOUBLE" if duration == 2 else (" · TRIPLE" if duration >= 3 else "")
                        cells.append(
                            f"<td class='tt-master-cell tt-master-occupied'><div class='tt-master-placard tt-draggable-lesson tt-placed-card' draggable='true' data-slot-id='{lid}' data-class-id='{cid}' data-day='{escape(str(day))}' data-period='{pno}' style='background:{_teacher_placard_color(teacher_id)}' title='Click lesson card for options'>"
                            f"<b>{subject}</b><em>{duration_label}</em></div></td>"
                        )
                else:
                    cells.append(
                        f"<td class='tt-master-cell tt-master-drop tt-drop-slot' data-class-id='{cid}' data-day='{escape(str(day))}' data-period='{pno}' title='Drop a lesson here'>+</td>"
                    )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    # Teacher names are intentionally not shown on the working timetable placards.
    # They are revealed on the bottom lesson platform when a placard is clicked,
    # while printed class timetables show the teacher at the bottom-right.
    legend_html = ""
    return f"""<div class='tt-master-wrap'>
<div class='tt-master-toolbar'><b>🏫 Whole-School Master Timetable</b><span>Drag lesson placards into empty cells. The server checks teacher, class, room, break and double-period clashes before saving.</span></div>
<div class='tt-legend'>{legend_html}</div>
<div class='tt-master-scroll'><table class='tt-master-table'>
<thead><tr><th class='tt-master-class tt-master-corner'>CLASS / STREAM</th>{day_head}</tr><tr><th class='tt-master-class tt-master-corner'>PERIOD</th>{period_head}</tr></thead>
<tbody>{''.join(rows) or "<tr><td>No classes found.</td></tr>"}</tbody>
</table></div></div>"""

def _lesson_placard_platform(con, sid):
    rows = con.execute("""SELECT l.id,l.class_id,l.teacher_id,l.duration,l.lessons_per_week,
        c.name class_name,c.stream,sub.name subject,sub.code subject_code,sub.initial subject_initial,t.name teacher
        FROM timetable_lessons l JOIN classes c ON c.id=l.class_id
        JOIN subjects sub ON sub.id=l.subject_id LEFT JOIN teachers t ON t.id=l.teacher_id
        WHERE l.school_id=? ORDER BY c.name,c.stream,sub.name,l.id""",(sid,)).fetchall()
    placed={int(x["lesson_id"]):int(x["c"] or 0) for x in con.execute(
        "SELECT lesson_id,COUNT(*) c FROM timetable_slots WHERE school_id=? AND profile_id=timetable_active_profile(school_id) GROUP BY lesson_id",(sid,)
    ).fetchall()}
    cards=[]
    for row in rows:
        remaining=max(0,int(row["lessons_per_week"] or 0)-placed.get(int(row["id"]),0))
        if remaining<=0: continue
        duration=max(1,int(row["duration"] or 1))
        label=f"{str(row['class_name'])}{(' — '+str(row['stream'])) if row['stream'] else ''}"
        for _ in range(remaining):
            cards.append(
                f"<div class='tt-tray-placard' draggable='true' data-lesson-id='{int(row['id'])}' style='background:{_teacher_placard_color(row['teacher_id'])}'>"
                f"<b>{escape(_subject_initial(row))}</b>"
                f"<div class='tt-tray-detail'><span>Teacher: {escape(str(row['teacher'] or 'Unassigned teacher'))}</span>"
                f"<small>Class: {escape(label)} · {duration} period{'s' if duration != 1 else ''}</small></div></div>"
            )
    return "".join(cards) or "<div class='tt-tray-empty'>All lesson occurrences are placed.</div>"



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

    # A class/teacher filter is a request for an independent timetable sheet,
    # not a filtered copy of the whole-school master sheet.
    selected_sheet = None
    selected_view_title = ""
    if str(class_filter).isdigit():
        selected_cid = int(class_filter)
        selected_class = next((c for c in classes if int(c["id"]) == selected_cid), None)
        if selected_class:
            selected_sheet = _class_grid_html(
                selected_class, periods, days, breaks, grids.get(selected_cid, {}), show_title=True
            )
            selected_view_title = "🏫 Independent Class Timetable"
    elif str(teacher_filter).isdigit():
        selected_tid = int(teacher_filter)
        selected_teacher = con.execute(
            "SELECT id,name FROM teachers WHERE id=? AND school_id=?",
            (selected_tid, sid)
        ).fetchone()
        if selected_teacher:
            selected_sheet = _teacher_sheets(con, sid, selected_tid)
            selected_view_title = "👨‍🏫 Independent Teacher Timetable"

    master_sheet = (
        f"<div class='tt-card'><h3>{selected_view_title}</h3>"
        "<div class='tt-muted'>This is an independent timetable for the selected class or teacher. "
        "It uses the active timetable profile's exact days, period times and saved breaks. "
        "Use Print to print only this selected timetable.</div>"
        "<div class='no-print' style='margin:12px 0'>"
        "<button class='tt-btn' type='button' onclick='printClassTimetables()'>🖨️ Print This Timetable</button>"
        "</div>"
        f"<div class='tt-print-sheets'>{selected_sheet}</div></div>"
        if selected_sheet else _master_timetable_html(classes, periods, days, grids)
    )

    drag_script = """<script>
(function(){
  let dragged=null,draggedType=null;
  document.querySelectorAll('.tt-draggable-lesson').forEach(function(card){
    card.addEventListener('dragstart',function(e){dragged=this.dataset.slotId;draggedType='placed';this.classList.add('tt-dragging');e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',dragged);});
    card.addEventListener('dragend',function(){this.classList.remove('tt-dragging');dragged=null;draggedType=null;});
  });
  document.querySelectorAll('.tt-tray-placard').forEach(function(card){
    card.addEventListener('click',function(){card.classList.toggle('tt-tray-open');});
    card.addEventListener('dragstart',function(e){dragged=this.dataset.lessonId;draggedType='tray';this.classList.add('tt-tray-dragging');e.dataTransfer.effectAllowed='copy';e.dataTransfer.setData('text/plain','tray:'+dragged);});
    card.addEventListener('dragend',function(){this.classList.remove('tt-tray-dragging');dragged=null;draggedType=null;});
  });
  document.querySelectorAll('.tt-placed-card').forEach(function(card){
    card.addEventListener('click',function(e){
      if(e.target.closest('.tt-placed-menu'))return;
      e.preventDefault();
      e.stopPropagation();
      document.querySelectorAll('.tt-placed-menu').forEach(function(m){m.remove();});
      var menu=document.createElement('div');
      menu.className='tt-placed-menu';
      var form=document.createElement('form');
      form.method='POST';
      form.action='/app/timetable/placement/platform/'+encodeURIComponent(card.getAttribute('data-slot-id'));
      var btn=document.createElement('button');
      btn.type='button';
      btn.textContent='📌 Place on platform';
      btn.addEventListener('click',async function(ev){
        ev.preventDefault();
        ev.stopPropagation();
        btn.disabled=true;
        btn.textContent='Moving…';
        try{
          var res=await fetch(form.action,{method:'POST',credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}});
          if(!res.ok)throw new Error('HTTP '+res.status);
          window.location.href=res.url||'/app/timetable?tab=timetable';
        }catch(err){
          btn.disabled=false;
          btn.textContent='📌 Place on platform';
          alert('Unable to return this lesson to the platform. Please try again.');
        }
      });
      form.addEventListener('click',function(ev){ev.stopPropagation();});
      form.appendChild(btn);
      menu.appendChild(form);
      card.appendChild(menu);
    });
  });
  document.addEventListener('click',function(e){
    if(!e.target.closest('.tt-placed-card'))document.querySelectorAll('.tt-placed-menu').forEach(function(m){m.remove();});
  });
  document.querySelectorAll('.tt-drop-slot').forEach(function(slot){
    slot.addEventListener('dragover',function(e){e.preventDefault();e.dataTransfer.dropEffect=draggedType==='tray'?'copy':'move';this.classList.add('tt-drop-hover');});
    slot.addEventListener('dragleave',function(){this.classList.remove('tt-drop-hover');});
    slot.addEventListener('drop',async function(e){
      e.preventDefault();this.classList.remove('tt-drop-hover');
      let id=dragged,type=draggedType;
      if(!id){const raw=e.dataTransfer.getData('text/plain');if(raw.indexOf('tray:')===0){type='tray';id=raw.slice(5);}else{type='placed';id=raw;}}
      if(!id)return;
      const fd=new FormData();fd.append('day_name',this.dataset.day);fd.append('period_no',this.dataset.period);fd.append('class_id',this.dataset.classId);
      const endpoint=type==='tray'?'/app/timetable/placement/place/'+encodeURIComponent(id):'/app/timetable/placement/move/'+encodeURIComponent(id);
      try{const res=await fetch(endpoint,{method:'POST',body:fd,credentials:'same-origin'});window.location.href=res.url||'/app/timetable?tab=timetable';}
      catch(err){alert('Unable to place this lesson.');}
    });
  });
})();
</script>"""
    teacher_rows = con.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    teacher_legend = "".join(
        "<span class='tt-teacher-chip' style='background:{}'>{}</span>".format(
            _teacher_placard_color(t["id"]), escape(str(t["name"]))
        )
        for t in teacher_rows
    ) or "<span class='tt-muted'>No teachers found.</span>"

    return f"""<div class='tt-card'><h2>🗓️ Class Timetable</h2>
<div class='tt-muted'>Choose a class/stream or teacher and press View to open that person's independent timetable. The unfiltered view remains the whole-school master timetable for manual placement.</div>
<form method='get' class='tt-form' style='margin-top:12px'>
<input type='hidden' name='tab' value='timetable'>
<label><span class='tt-label'>Class / Stream</span><select class='tt-field' name='class_id'><option value=''>All classes</option>{class_opts}</select></label>
<label><span class='tt-label'>Teacher filter</span><select class='tt-field' name='teacher_id'><option value=''>All teachers</option>{teacher_opts}</select></label>
<label><span class='tt-label'>Room filter</span><select class='tt-field' name='room_id'><option value=''>All rooms</option>{room_opts}</select></label>
<div><button class='tt-btn'>🔎 View</button></div>
</form>
<div class='tt-card tt-manual-editor'><h3>🖱️ Manual Placement</h3>
<div class='tt-muted'>Drag lessons directly across the whole-school sheet. Classes stay on the left, days run across the top, and every day contains its periods. A move is rejected if it creates a teacher, class, room, break or double-period clash.</div>
</div>
<div style='margin-top:14px'>{master_sheet}</div>
<div class='tt-placard-platform'><div class='tt-placard-platform-head'><b>📌 Lesson Placard Platform</b><span>Drag unplaced lesson cards into empty timetable cells above. Rebalance them manually as needed.</span></div><div class='tt-placard-tray'>{_lesson_placard_platform(con, sid)}</div></div>
{drag_script}
<div style='margin-top:12px'><a class='tt-btn' href='/app/timetable?tab=generate'>🚀 Generate / Regenerate</a> <a class='tt-btn alt' href='/app/timetable?tab=verify'>✅ Verify</a> <a class='tt-btn alt' href='/app/timetable?tab=teacher_sheets'>👨‍🏫 Teacher Sheets</a> <a class='tt-btn alt' href='/app/timetable?tab=print'>🖨️ Print Classes</a></div>
</div>"""


def _print_view(con, sid):
    classes, periods, days, breaks, grids = _class_grid_data(con, sid)
    sheets = [
        _class_grid_html(c, periods, days, breaks, grids[int(c["id"])])
        for c in classes if int(c["id"]) in grids
    ]

    return f"""<div class='tt-card'><h2>🖨️ Print Class Timetables</h2>
<div class='tt-muted'>Every class/stream is printed as a separate timetable using the school's exact saved period and break times, with days vertically and periods horizontally.</div>
<div class='no-print' style='margin:12px 0'><button class='tt-btn' onclick='printClassTimetables()'>🖨️ Open Print Preview</button></div>
<div class='tt-print-sheets'>{''.join(sheets) or '<div class="tt-notice bad">No timetable placements yet.</div>'}</div></div>"""


@router.post("/app/timetable/profile/switch-select")
def timetable_profile_switch_select(request:Request,profile_id:int=Form(...),tab:str=Form("timetable")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        if not con.execute("SELECT id FROM timetable_profiles WHERE id=? AND school_id=?",(profile_id,sid)).fetchone():
            return RedirectResponse("/app/timetable?tab="+quote(tab)+"&error=Invalid+timetable+profile",303)
        con.execute("UPDATE timetable_profiles SET active=0 WHERE school_id=?",(sid,))
        con.execute("UPDATE timetable_profiles SET active=1,updated_at=? WHERE id=? AND school_id=?",(datetime.now().strftime("%Y-%m-%d %H:%M:%S"),profile_id,sid))
        con.commit()
        return RedirectResponse("/app/timetable?tab="+quote(tab),303)
    finally:con.close()

@router.post("/app/timetable/profile/switch/{pid}")
def timetable_profile_switch(request:Request,pid:int,tab:str=Form("profiles")):
    return timetable_profile_switch_select(request,profile_id=pid,tab=tab)

@router.post("/app/timetable/profile/create")
def timetable_profile_create(request:Request,name:str=Form(...),description:str=Form("")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        name=name.strip()
        if not name:return RedirectResponse("/app/timetable?tab=profiles&error=Timetable+name+is+required",303)
        if con.execute("SELECT id FROM timetable_profiles WHERE school_id=? AND lower(name)=lower(?)",(sid,name)).fetchone():
            return RedirectResponse("/app/timetable?tab=profiles&error=A+timetable+with+that+name+already+exists",303)
        current=_active_profile(con,sid);now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.execute("""INSERT INTO timetable_profiles(
            school_id,name,description,active,days_json,periods_json,breaks_json,
            periods_per_day,period_minutes,periods_per_week,complexity,relaxation,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            sid,name,description.strip(),0,str(current["days_json"]),str(current["periods_json"]),str(current["breaks_json"]),
            int(current["periods_per_day"] or 7),int(current["period_minutes"] or 40),int(current["periods_per_week"] or 35),
            str(current["complexity"] or "normal"),str(current["relaxation"] or "relaxed"),now,now))
        con.commit()
        return RedirectResponse("/app/timetable?tab=profiles&msg=New+timetable+created+from+the+current+schedule",303)
    finally:con.close()

@router.post("/app/timetable/profile/duplicate/{pid}")
def timetable_profile_duplicate(request:Request,pid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        source=con.execute("SELECT * FROM timetable_profiles WHERE id=? AND school_id=?",(pid,sid)).fetchone()
        if not source:return RedirectResponse("/app/timetable?tab=profiles&error=Timetable+profile+not+found",303)
        base=str(source["name"] or "Timetable")+" Copy";name=base;n=2
        while con.execute("SELECT id FROM timetable_profiles WHERE school_id=? AND lower(name)=lower(?)",(sid,name)).fetchone():
            name=base+" "+str(n);n+=1
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.execute("""INSERT INTO timetable_profiles(
            school_id,name,description,active,days_json,periods_json,breaks_json,
            periods_per_day,period_minutes,periods_per_week,complexity,relaxation,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            sid,name,"Duplicated from "+str(source["name"]),0,str(source["days_json"]),str(source["periods_json"]),str(source["breaks_json"]),
            int(source["periods_per_day"] or 7),int(source["period_minutes"] or 40),int(source["periods_per_week"] or 35),
            str(source["complexity"] or "normal"),str(source["relaxation"] or "relaxed"),now,now))
        new_id=int(con.execute("SELECT id FROM timetable_profiles WHERE school_id=? AND name=?",(sid,name)).fetchone()["id"])
        con.execute("""INSERT INTO timetable_slots(
            school_id,lesson_id,day_name,period_no,start_time,end_time,room_id,locked,generated_run,profile_id
        ) SELECT school_id,lesson_id,day_name,period_no,start_time,end_time,room_id,locked,generated_run,?
          FROM timetable_slots WHERE school_id=? AND profile_id=?""",(new_id,sid,pid))
        con.commit()
        return RedirectResponse("/app/timetable?tab=profiles&msg=Timetable+duplicated+with+its+saved+placements",303)
    finally:con.close()

@router.post("/app/timetable/profile/rename/{pid}")
def timetable_profile_rename(request:Request,pid:int,name:str=Form(...)):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        name=name.strip()
        if not name:return RedirectResponse("/app/timetable?tab=profiles&error=Timetable+name+is+required",303)
        if con.execute("SELECT id FROM timetable_profiles WHERE school_id=? AND lower(name)=lower(?) AND id<>?",(sid,name,pid)).fetchone():
            return RedirectResponse("/app/timetable?tab=profiles&error=A+timetable+with+that+name+already+exists",303)
        con.execute("UPDATE timetable_profiles SET name=?,updated_at=? WHERE id=? AND school_id=?",(name,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),pid,sid))
        con.commit()
        return RedirectResponse("/app/timetable?tab=profiles&msg=Timetable+renamed",303)
    finally:con.close()

@router.post("/app/timetable/profile/delete/{pid}")
def timetable_profile_delete(request:Request,pid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        current=_active_profile_id(con,sid)
        total=int(con.execute("SELECT COUNT(*) c FROM timetable_profiles WHERE school_id=?",(sid,)).fetchone()["c"] or 0)
        if pid==current:return RedirectResponse("/app/timetable?tab=profiles&error=Switch+to+another+timetable+before+deleting+this+one",303)
        if total<=1:return RedirectResponse("/app/timetable?tab=profiles&error=The+last+timetable+cannot+be+deleted",303)
        con.execute("DELETE FROM timetable_slots WHERE school_id=? AND profile_id=?",(sid,pid))
        con.execute("DELETE FROM timetable_profiles WHERE id=? AND school_id=?",(pid,sid))
        con.commit()
        return RedirectResponse("/app/timetable?tab=profiles&msg=Timetable+deleted+without+deleting+lesson+cards",303)
    finally:con.close()

@router.post("/app/timetable/setup/save")
def timetable_setup_save(request: Request, complexity: str=Form(...), relaxation: str=Form(...), days: list[str]=Form([])):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        complexity=complexity if complexity in ("normal","large","huge") else "normal"
        relaxation=relaxation if relaxation in ("draft","relaxed","strict") else "relaxed"
        wanted=[d for d in days if d in DAYS] or list(DEFAULT_DAYS)
        values=[{"day_no":i,"name":d,"short_name":d[:3].upper(),"enabled":1 if d in wanted else 0} for i,d in enumerate(DAYS,1)]
        _save_profile_json(con,sid,"days_json",values)
        pid=_active_profile_id(con,sid)
        con.execute("UPDATE timetable_profiles SET complexity=?,relaxation=?,periods_per_week=?,updated_at=? WHERE id=? AND school_id=?",
                    (complexity,relaxation,max(1,len(wanted)*len(_profile_periods(con,sid))),datetime.now().strftime("%Y-%m-%d %H:%M:%S"),pid,sid))
        con.commit()
        return RedirectResponse("/app/timetable?tab=setup&msg=Timetable+profile+setup+saved",303)
    finally:con.close()

@router.post("/app/timetable/periods/settings")
def timetable_period_settings(request: Request, periods_per_day:int=Form(...), period_minutes:int=Form(...), periods_per_week:int=Form(...)):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        if not (1<=periods_per_day<=12 and 20<=period_minutes<=180):
            return RedirectResponse("/app/timetable?tab=periods&error=Invalid+period+settings",303)
        old={int(x["period_no"]):x for x in _profile_periods(con,sid)}
        base=datetime.strptime("08:00","%H:%M")
        values=[]
        for n in range(1,periods_per_day+1):
            if n in old:
                st=str(old[n]["start_time"]);et=str(old[n]["end_time"])
            else:
                st=(base+timedelta(minutes=(n-1)*period_minutes)).strftime("%H:%M")
                et=(base+timedelta(minutes=n*period_minutes)).strftime("%H:%M")
            values.append({"id":n,"period_no":n,"start_time":st,"end_time":et})
        _save_profile_json(con,sid,"periods_json",values)
        pid=_active_profile_id(con,sid)
        enabled=sum(1 for x in _profile_days(con,sid) if int(x["enabled"] or 0))
        physical_week=max(1,enabled)*periods_per_day
        con.execute("UPDATE timetable_profiles SET periods_per_day=?,period_minutes=?,periods_per_week=?,updated_at=? WHERE id=? AND school_id=?",
                    (periods_per_day,period_minutes,physical_week,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),pid,sid))
        con.commit()
        return RedirectResponse("/app/timetable?tab=periods&msg=Period+settings+saved+for+this+timetable",303)
    finally:con.close()

@router.post("/app/timetable/periods/save")
async def timetable_periods_save(request: Request):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        form=await request.form()
        periods=_profile_periods(con,sid)
        submitted=[]
        seen=[]
        for p in periods:
            pno=int(p["period_no"]);st=str(form.get(f"start_{pno}") or "").strip();et=str(form.get(f"end_{pno}") or "").strip()
            if not st or not et or et<=st:return RedirectResponse(f"/app/timetable?tab=periods&error=Invalid+time+for+period+{pno}",303)
            submitted.append({"id":pno,"period_no":pno,"start_time":st,"end_time":et});seen.append((pno,st,et))
        for i,(pno,st,et) in enumerate(seen):
            for other_no,ost,oet in seen[i+1:]:
                if st<oet and et>ost:return RedirectResponse(f"/app/timetable?tab=periods&error=Period+{pno}+overlaps+period+{other_no}",303)
        _save_profile_json(con,sid,"periods_json",submitted)
        pid=_active_profile_id(con,sid)
        con.execute("UPDATE timetable_profiles SET periods_per_week=?,updated_at=? WHERE id=? AND school_id=?",
                    (max(1,sum(1 for x in _profile_days(con,sid) if int(x["enabled"] or 0)))*len(submitted),datetime.now().strftime("%Y-%m-%d %H:%M:%S"),pid,sid))
        con.commit()
        return RedirectResponse("/app/timetable?tab=periods&msg=Period+times+saved+for+this+timetable",303)
    finally:con.close()

@router.post("/app/timetable/break/save")
def timetable_break_save(request: Request,name:str=Form(...),start_time:str=Form(...),end_time:str=Form(...)):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        name=name.strip()
        if not name or not start_time or not end_time or end_time<=start_time:return RedirectResponse("/app/timetable?tab=periods&error=Invalid+break",303)
        breaks=_profile_breaks(con,sid)
        if any(start_time<str(b["end_time"]) and end_time>str(b["start_time"]) for b in breaks):return RedirectResponse("/app/timetable?tab=periods&error=Break+overlaps+another+break",303)
        next_id=max([int(b["id"]) for b in breaks] or [0])+1
        breaks.append({"id":next_id,"name":name,"start_time":start_time,"end_time":end_time});breaks.sort(key=lambda x:(str(x["start_time"]),int(x["id"])))
        _save_profile_json(con,sid,"breaks_json",breaks);con.commit()
        return RedirectResponse("/app/timetable?tab=periods&msg=Break+saved+for+this+timetable",303)
    finally:con.close()

@router.post("/app/timetable/break/delete/{rid}")
def timetable_break_delete(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        _save_profile_json(con,sid,"breaks_json",[b for b in _profile_breaks(con,sid) if int(b["id"])!=int(rid)])
        con.commit();return RedirectResponse("/app/timetable?tab=periods&msg=Break+deleted+from+this+timetable",303)
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
        days=[str(r["name"]) for r in [r for r in _profile_days(con,sid) if int(r["enabled"] or 0)]]
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
    periods=_profile_periods(cur,sid)
    pmap={int(p["period_no"]):p for p in periods}
    breaks=_profile_breaks(cur,sid)
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
    """Automatically solve the timetable with deterministic backtracking.

    Hard rules are never relaxed: class/stream collisions, teacher collisions,
    breaks, fixed-room collisions and period boundaries. In relaxed/draft mode
    availability and preferred daily limits may be relaxed only when necessary.
    A lesson occurrence occupies its full duration, so double/triple lessons
    consume 2/3 physical periods while remaining one occurrence.
    """
    days=[str(r["name"]) for r in cur.execute(
        "SELECT name FROM timetable_days WHERE school_id=? AND enabled=1 ORDER BY day_no",(sid,)
    ).fetchall()]
    if not days:
        days=list(DEFAULT_DAYS)

    periods=[dict(r) for r in cur.execute(
        "SELECT * FROM timetable_periods WHERE school_id=? ORDER BY period_no",(sid,)
    ).fetchall()]
    rooms=[dict(r) for r in cur.execute(
        "SELECT * FROM timetable_rooms WHERE school_id=? AND active=1 ORDER BY id",(sid,)
    ).fetchall()]

    lesson_sql="SELECT * FROM timetable_lessons WHERE school_id=?"
    params=(sid,)
    if class_filter:
        lesson_sql += """ AND (class_id=? OR id IN (
            SELECT lesson_id FROM timetable_lesson_classes
            WHERE school_id=? AND class_id=?
        ))"""
        params=(sid,class_filter,sid,class_filter)
    lessons=[dict(r) for r in cur.execute(
        lesson_sql+" ORDER BY duration DESC,lessons_per_week DESC,id",params
    ).fetchall()]

    if not periods or not lessons:
        return datetime.now().strftime("%Y%m%d%H%M%S%f"),0,0,[],"complete"

    pmap={int(p["period_no"]):p for p in periods}
    breaks=[dict(r) for r in cur.execute(
        "SELECT * FROM timetable_breaks WHERE school_id=? ORDER BY start_time,id",(sid,)
    ).fetchall()]

    lesson_classes={}
    lesson_teachers={}
    for l in lessons:
        lid=int(l["id"])
        cls={int(x["class_id"]) for x in cur.execute(
            "SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,lid)
        ).fetchall()} or {int(l["class_id"])}
        tea={int(x["teacher_id"]) for x in cur.execute(
            "SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,lid)
        ).fetchall()} or ({int(l["teacher_id"])} if l["teacher_id"] else set())
        lesson_classes[lid]=cls
        lesson_teachers[lid]=tea

    blocked_teacher={(str(r["day_name"]),int(r["period_no"]),int(r["resource_id"])) for r in cur.execute(
        "SELECT day_name,period_no,resource_id FROM timetable_availability WHERE school_id=? AND resource_type='teacher' AND allowed=0",(sid,)
    ).fetchall()}
    blocked_subject={(str(r["day_name"]),int(r["period_no"]),int(r["resource_id"])) for r in cur.execute(
        "SELECT day_name,period_no,resource_id FROM timetable_availability WHERE school_id=? AND resource_type='subject' AND allowed=0",(sid,)
    ).fetchall()}
    constraints=_constraint_maps(cur,sid)

    if replace_existing:
        if class_filter:
            cur.execute("""DELETE FROM timetable_slots
                WHERE school_id=? AND profile_id=timetable_active_profile(school_id) AND locked=0 AND lesson_id IN (
                    SELECT id FROM timetable_lessons WHERE school_id=? AND class_id=?
                )""",(sid,sid,class_filter))
        else:
            cur.execute("DELETE FROM timetable_slots WHERE school_id=? AND profile_id=timetable_active_profile(school_id) AND locked=0",(sid,))

    base=[dict(r) for r in cur.execute("""SELECT s.*,l.class_id,l.teacher_id,l.room_id,l.duration,l.subject_id
        FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id
        WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id)""",(sid,)).fetchall()]

    def overlap(a_pno,a_duration,b):
        return (
            int(a_pno) <= int(b["period_no"])+max(1,int(b.get("duration",1)))-1
            and int(b["period_no"]) <= int(a_pno)+max(1,int(a_duration))-1
        )

    def crosses_break(pno,duration):
        for x in range(int(pno),int(pno)+int(duration)):
            p=pmap.get(x)
            if not p:
                return True
            st=_time_to_min(p["start_time"])
            et=_time_to_min(p["end_time"])
            for b in breaks:
                if st < _time_to_min(b["end_time"]) and et > _time_to_min(b["start_time"]):
                    return True
        return False

    def valid_duration_start(pno,duration):
        """Keep double lessons inside the school's two-period blocks.

        Teaching periods are grouped as 1-2, 3-4, 5-6, 7-8 because a
        break follows each pair. A double lesson therefore starts only on
        1, 3, 5, 7, etc. and occupies that complete pair.
        """
        pno=int(pno)
        duration=max(1,int(duration))
        return duration != 2 or pno % 2 == 1

    def candidate(lesson,day,pno,occ,enforce_availability,enforce_preferred):
        lid=int(lesson["id"])
        duration=max(1,int(lesson.get("duration") or 1))
        if not valid_duration_start(pno,duration):
            return None
        if crosses_break(pno,duration):
            return None

        classes=lesson_classes[lid]
        teachers=lesson_teachers[lid]

        # A subject may appear only once per class/stream on a day.
        # A double/triple lesson is still one occurrence, so its consecutive
        # physical periods are allowed; a second occurrence of that subject on
        # the same day is not.
        subject_id=int(lesson["subject_id"])
        for o in occ:
            if str(o["day_name"]) != day:
                continue
            oid=int(o["lesson_id"])
            other_classes=lesson_classes.get(oid,{int(o["class_id"])})
            if classes.intersection(other_classes) and int(o.get("subject_id") or 0)==subject_id:
                return None

        for o in occ:
            if str(o["day_name"]) != day or not overlap(pno,duration,o):
                continue
            oid=int(o["lesson_id"])
            if classes.intersection(lesson_classes.get(oid,{int(o["class_id"])})):
                return None
            if teachers.intersection(lesson_teachers.get(
                oid,({int(o["teacher_id"])} if o.get("teacher_id") else set())
            )):
                return None
            fixed=int(lesson["room_id"]) if lesson.get("room_id") else None
            other_room=int(o["room_id"]) if o.get("room_id") else None
            if fixed and other_room==fixed:
                return None

        if enforce_availability:
            for xp in range(int(pno),int(pno)+duration):
                if any((day,xp,t) in blocked_teacher for t in teachers):
                    return None
                if (day,xp,int(lesson["subject_id"])) in blocked_subject:
                    return None

        if enforce_preferred:
            for cdef in constraints.get("Teacher max lessons/day",[]):
                if cdef["target_id"] and teachers and int(cdef["target_id"]) in teachers:
                    lim=int(cdef["value"] or 0)
                    if lim:
                        used=sum(
                            1 for o in occ
                            if str(o["day_name"])==day
                            and lesson_teachers.get(int(o["lesson_id"]),set()).intersection(teachers)
                        )
                        if used>=lim:
                            return None
            for cdef in constraints.get("Class max lessons/day",[]):
                if cdef["target_id"]:
                    target=int(cdef["target_id"])
                    if target in classes:
                        lim=int(cdef["value"] or 0)
                        if lim:
                            used=sum(
                                1 for o in occ
                                if str(o["day_name"])==day
                                and lesson_classes.get(int(o["lesson_id"]),set()).intersection(classes)
                            )
                            if used>=lim:
                                return None

        fixed=int(lesson["room_id"]) if lesson.get("room_id") else None
        if fixed:
            if any(
                str(o["day_name"])==day and int(o.get("room_id") or 0)==fixed
                and overlap(pno,duration,o) for o in occ
            ):
                return None
            room_id=fixed
        else:
            room_id=None
            for room in rooms:
                rid=int(room["id"])
                if all(
                    not (
                        str(o["day_name"])==day
                        and int(o.get("room_id") or 0)==rid
                        and overlap(pno,duration,o)
                    ) for o in occ
                ):
                    room_id=rid
                    break
            # Room is optional when the Lesson Card says "Any available room".
            # Return a distinct sentinel when no room is available. None is
            # reserved for a hard placement conflict, so the generator must
            # never mistake a conflicting slot for a valid optional-room slot.
            if room_id is None:
                return -1
        return room_id

    def spread_score(lesson,day,pno,occ):
        # Spread placements across the physical school week. The old scoring
        # strongly favored the first available period, which could concentrate
        # generated lessons in P1. Prefer the least-used day/period for the
        # participating classes and teachers while still keeping subjects
        # reasonably distributed.
        lid=int(lesson["id"])
        classes=lesson_classes[lid]
        teachers=lesson_teachers[lid]
        subject=int(lesson["subject_id"])

        class_day=sum(
            1 for o in occ
            if str(o["day_name"])==day
            and classes.intersection(lesson_classes.get(int(o["lesson_id"]),set()))
        )
        teacher_day=sum(
            1 for o in occ
            if str(o["day_name"])==day
            and teachers.intersection(lesson_teachers.get(int(o["lesson_id"]),set()))
        )
        class_period=sum(
            1 for o in occ
            if str(o["day_name"])==day
            and overlap(pno,1,o)
            and classes.intersection(lesson_classes.get(int(o["lesson_id"]),set()))
        )
        teacher_period=sum(
            1 for o in occ
            if str(o["day_name"])==day
            and overlap(pno,1,o)
            and teachers.intersection(lesson_teachers.get(int(o["lesson_id"]),set()))
        )
        same_subject=sum(
            1 for o in occ
            if str(o["day_name"])==day
            and int(o.get("subject_id") or 0)==subject
            and classes.intersection(lesson_classes.get(int(o["lesson_id"]),set()))
        )
        # Exact period occupancy is the strongest penalty; then day load.
        return (
            class_period*1000 +
            teacher_period*800 +
            class_day*40 +
            teacher_day*30 +
            same_subject*8 +
            int(pno)*0.01 +
            days.index(day)*0.001
        )

    def solve(enforce_availability,enforce_preferred):
        """Automatic timetable solver.

        Rules enforced here:
        - one subject occurrence per class/stream per day;
        - a double is one occurrence occupying exactly two consecutive periods;
        - doubles may start only at 1,3,5,7,...;
        - breaks, class clashes, teacher clashes and fixed-room clashes are hard;
        - weekly occurrences are deliberately spread across different days.
        """
        import random

        lesson_by_id={int(x["id"]):x for x in lessons}
        occurrences=[]
        for lesson in lessons:
            lid=int(lesson["id"])
            already=sum(1 for o in base if int(o["lesson_id"])==lid)
            need=max(0,int(lesson.get("lessons_per_week") or 0)-already)
            for n in range(need):
                occurrences.append((lid,n))

        # If the requested weekly count exceeds the number of teaching days,
        # the once-per-day rule makes the request mathematically impossible.
        day_count=max(1,len(days))
        impossible=set()
        for lesson in lessons:
            lid=int(lesson["id"])
            need=int(lesson.get("lessons_per_week") or 0)
            if need>day_count:
                impossible.add(lid)

        all_candidates={}
        for lid,_ in occurrences:
            lesson=lesson_by_id[lid]
            duration=max(1,int(lesson.get("duration") or 1))
            cand=[]
            for day in days:
                for p in periods:
                    pno=int(p["period_no"])
                    if pno+duration-1>max(pmap):
                        continue
                    if not valid_duration_start(pno,duration):
                        continue
                    if crosses_break(pno,duration):
                        continue
                    cand.append((day,pno))
            all_candidates[lid]=cand

        def key_for(lid):
            return (tuple(sorted(lesson_classes[lid])),int(lesson_by_id[lid]["subject_id"]))

        # Reserve preferred days for each class/subject before choosing periods.
        # This prevents the greedy scheduler from consuming all five days with
        # unrelated cards and then leaving a subject unplaceable.
        def day_score(lesson,day,occupied):
            lid=int(lesson["id"])
            classes=lesson_classes[lid]
            teachers=lesson_teachers[lid]
            subject=int(lesson["subject_id"])
            class_day=sum(
                1 for o in occupied
                if str(o["day_name"])==day
                and classes.intersection(lesson_classes.get(int(o["lesson_id"]),set()))
            )
            teacher_day=sum(
                1 for o in occupied
                if str(o["day_name"])==day
                and teachers.intersection(lesson_teachers.get(int(o["lesson_id"]),set()))
            )
            subject_day=sum(
                1 for o in occupied
                if str(o["day_name"])==day
                and classes.intersection(lesson_classes.get(int(o["lesson_id"]),set()))
                and int(o.get("subject_id") or 0)==subject
            )
            # Spread the same subject's weekly occurrences across different
            # periods as well as different days. A subject should not simply
            # repeat at the same bell time from Monday to Friday.
            return subject_day*100000+class_day*100+teacher_day*80+days.index(day)

        # Harder requirements first: doubles/triples, high weekly demand,
        # then cards with fewer physical choices.
        occurrences.sort(key=lambda x:(
            len(all_candidates.get(x[0],[])),
            -len(lesson_teachers.get(x[0],set())),
            -len(lesson_classes.get(x[0],set())),
            -max(1,int(lesson_by_id[x[0]].get("duration") or 1)),
            -int(lesson_by_id[x[0]].get("lessons_per_week") or 0),
            x[0],x[1]
        ))

        def run_once(seed):
            """Fast single-pass scheduler using indexed occupancy.

            The HTTP/background job must not spend minutes repeatedly scanning
            every existing placement for every candidate. All hard conflicts
            are represented by sets, making a candidate check O(duration *
            resources) rather than O(number of placements).
            """
            rng=random.Random(seed)
            occupied=[dict(x) for x in base]
            placed=[]

            class_slot=set()
            teacher_slot=set()
            room_slot=set()
            subject_day=set()
            class_day_load={}
            teacher_day_load={}

            def index_row(row):
                lid=int(row["lesson_id"])
                classes=lesson_classes.get(lid,{int(row["class_id"])})
                teachers=lesson_teachers.get(
                    lid,({int(row["teacher_id"])} if row.get("teacher_id") else set())
                )
                duration=max(1,int(row.get("duration") or 1))
                day=str(row["day_name"])
                start=int(row["period_no"])
                subject=int(row.get("subject_id") or lesson_by_id[lid]["subject_id"])
                for pno in range(start,start+duration):
                    for cid in classes:
                        class_slot.add((day,pno,cid))
                    for tid in teachers:
                        teacher_slot.add((day,pno,tid))
                    rid=int(row.get("room_id") or 0)
                    if rid:
                        room_slot.add((day,pno,rid))
                for cid in classes:
                    subject_day.add((day,cid,subject))
                    class_day_load[(day,cid)]=class_day_load.get((day,cid),0)+1
                for tid in teachers:
                    teacher_day_load[(day,tid)]=teacher_day_load.get((day,tid),0)+1

            for row in occupied:
                index_row(row)

            def placeable(lesson,day,pno):
                lid=int(lesson["id"])
                duration=max(1,int(lesson.get("duration") or 1))
                if not valid_duration_start(pno,duration) or crosses_break(pno,duration):
                    return None

                classes=lesson_classes[lid]
                teachers=lesson_teachers[lid]
                subject=int(lesson["subject_id"])

                if any((day,cid,subject) in subject_day for cid in classes):
                    return None

                for xp in range(int(pno),int(pno)+duration):
                    if any((day,xp,cid) in class_slot for cid in classes):
                        return None
                    if any((day,xp,tid) in teacher_slot for tid in teachers):
                        return None
                    # A teacher must not teach two different subjects in
                    # immediately consecutive slots. The same double/triple
                    # lesson may occupy its own consecutive periods.
                    for tid in teachers:
                        if xp == int(pno) and (day,xp-1,tid) in teacher_slot:
                            return None
                        if xp == int(pno)+duration-1 and (day,xp+1,tid) in teacher_slot:
                            return None
                    if enforce_availability:
                        if any((day,xp,tid) in blocked_teacher for tid in teachers):
                            return None
                        if (day,xp,subject) in blocked_subject:
                            return None

                if enforce_preferred:
                    for cdef in constraints.get("Teacher max lessons/day",[]):
                        target=cdef["target_id"]
                        if target and int(target) in teachers:
                            lim=int(cdef["value"] or 0)
                            if lim and teacher_day_load.get((day,int(target)),0)>=lim:
                                return None
                    for cdef in constraints.get("Class max lessons/day",[]):
                        target=cdef["target_id"]
                        if target and int(target) in classes:
                            lim=int(cdef["value"] or 0)
                            if lim and class_day_load.get((day,int(target)),0)>=lim:
                                return None

                fixed=int(lesson["room_id"]) if lesson.get("room_id") else 0
                if fixed:
                    if any((day,xp,fixed) in room_slot for xp in range(int(pno),int(pno)+duration)):
                        return None
                    return fixed

                if rooms:
                    for room in rooms:
                        rid=int(room["id"])
                        if all((day,xp,rid) not in room_slot for xp in range(int(pno),int(pno)+duration)):
                            return rid

                # Room is optional. Zero means "no room assigned".
                return 0

            pending=list(occurrences)
            rng.shuffle(pending)
            pending.sort(key=lambda x:(
                -max(1,int(lesson_by_id[x[0]].get("duration") or 1)),
                -int(lesson_by_id[x[0]].get("lessons_per_week") or 0),
                len(all_candidates.get(x[0],[])),
                x[0],x[1]
            ))

            # Greedy placement with bounded look-ahead. We do not repeatedly
            # rescan the pending list; this keeps generation fast and stable.
            for lid,occ_no in pending:
                lesson=lesson_by_id[lid]
                choices=[]
                for day,pno in all_candidates.get(lid,[]):
                    room=placeable(lesson,day,pno)
                    if room is None:
                        continue
                    classes=lesson_classes[lid]
                    teachers=lesson_teachers[lid]
                    load=sum(class_day_load.get((day,c),0) for c in classes)
                    load+=sum(teacher_day_load.get((day,t),0) for t in teachers)
                    adjacent_class=0
                    for existing in occupied:
                        if str(existing["day_name"]) != day:
                            continue
                        existing_classes=lesson_classes.get(int(existing["lesson_id"]),{int(existing["class_id"])})
                        if not classes.intersection(existing_classes):
                            continue
                        existing_subject=int(existing.get("subject_id") or lesson_by_id[int(existing["lesson_id"])]["subject_id"])
                        if existing_subject == int(lesson["subject_id"]):
                            continue
                        ep=int(existing["period_no"])
                        ed=max(1,int(existing.get("duration") or 1))
                        nd=max(1,int(lesson.get("duration") or 1))
                        if ep+ed == int(pno) or int(pno)+nd == ep:
                            adjacent_class += 1
                    adjacency_bonus=-25*adjacent_class
                    choices.append((load+adjacency_bonus+int(pno)*0.01+rng.random(),day,int(pno),room))

                if not choices:
                    continue
                choices.sort(key=lambda x:x[0])

                committed=False
                for _,day,pno,room in choices[:12]:
                    checked=placeable(lesson,day,pno)
                    if checked is None:
                        continue
                    row={
                        "lesson_id":lid,
                        "class_id":lesson["class_id"],
                        "teacher_id":lesson["teacher_id"],
                        "subject_id":lesson["subject_id"],
                        "room_id":checked or None,
                        "day_name":day,
                        "period_no":pno,
                        "duration":max(1,int(lesson.get("duration") or 1))
                    }
                    occupied.append(row)
                    placed.append(row)
                    index_row(row)
                    committed=True
                    break

                if not committed:
                    continue

            complete=(len(placed)==len(occurrences) and not impossible)
            return complete,placed

        best=(False,[])
        # Use multiple fast randomized passes so the greedy solver can recover\n        # from an early placement that would otherwise leave later lesson cards\n        # stranded. The best complete/most-filled pass is retained.\n        # Keep the retry count in a clearly scoped variable.  Older deployed
        # versions could reach the return path with the retry-count name
        # undefined, which made Generate fail before any timetable was saved.
        # Keep generation inside a normal web-request time budget.
        # The solver retains the best placement found, so bounded randomized
        # passes prevent Render from appearing to ignore the Generate button.
        attempt_count={"normal":8,"large":10,"huge":12}.get(complexity,8)
        for attempt in range(attempt_count):
            complete,trial=run_once(2009+attempt)
            score=sum(max(1,int(x.get("duration") or 1)) for x in trial)
            # Reward completed occurrence counts first, then physical periods.
            trial_key=(1 if complete else 0,len(trial),score)
            best_key=(1 if best[0] else 0,len(best[1]),sum(max(1,int(x.get("duration") or 1)) for x in best[1]))
            if trial_key>best_key:
                best=(complete,trial)
            if complete:
                break

        return best[0],best[1],attempt_count

    # Strict first; relaxed/draft automatically soften only availability and
    # preferred constraints. Hard timetable collisions and breaks remain hard.
    modes=[(True,True)]
    if mode!="strict":
        modes += [(True,False),(False,True),(False,False)]

    best_solution=None
    best_score=-1
    for av_ok,pref_ok in modes:
        complete,chosen,nodes=solve(av_ok,pref_ok)
        score=sum(max(1,int(x.get("duration") or 1)) for x in chosen)
        if score>best_score:
            best_score=score
            best_solution=(complete,chosen,av_ok,pref_ok,nodes)
        if complete:
            break

    complete,placements,av_ok,pref_ok,nodes=best_solution or (True,[],True,True,0)

    # Persist only the best unlocked generated placements.
    if class_filter:
        cur.execute("""DELETE FROM timetable_slots
            WHERE school_id=? AND profile_id=timetable_active_profile(school_id) AND locked=0 AND lesson_id IN (
                SELECT id FROM timetable_lessons WHERE school_id=? AND class_id=?
            )""",(sid,sid,class_filter))
    else:
        cur.execute("DELETE FROM timetable_slots WHERE school_id=? AND profile_id=timetable_active_profile(school_id) AND locked=0",(sid,))

    run=datetime.now().strftime("%Y%m%d%H%M%S%f")
    for row in placements:
        # Store one placement at the start of the lesson, but also reserve
        # every physical period occupied by a double/triple through the
        # duration field. The class-grid renderer expands this into each
        # consecutive period cell.
        p=pmap[int(row["period_no"])]
        duration=max(1,int(row.get("duration") or 1))
        if int(row["period_no"])+duration-1 > max(pmap):
            continue
        cur.execute("""INSERT INTO timetable_slots(
            school_id,lesson_id,day_name,period_no,start_time,end_time,room_id,locked,generated_run,profile_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?)""",(
            sid,row["lesson_id"],row["day_name"],row["period_no"],
            p["start_time"],
            pmap[int(row["period_no"])+duration-1]["end_time"],
            row["room_id"],0,run,_active_profile_id(cur,sid)
        ))

    requested=sum(
        int(l.get("lessons_per_week") or 0)*max(1,int(l.get("duration") or 1))
        for l in lessons
    )
    placed=sum(max(1,int(row.get("duration") or 1)) for row in placements)

    unplaced=[]
    if not complete:
        placed_by={int(x["lesson_id"]) for x in placements}
        for l in lessons:
            need=int(l.get("lessons_per_week") or 0)
            got=sum(1 for x in placements if int(x["lesson_id"])==int(l["id"]))
            if got<need:
                unplaced.append((
                    int(l["id"]),
                    f"{got}/{need} occurrences placed; automatic solver exhausted its search"
                ))

    status="complete" if complete else ("relaxed" if mode!="strict" and placed else "incomplete")
    return run,requested,placed,unplaced,status


def _run_generation_job(sid,class_filter,mode,complexity,replace_existing,run_id):
    """Run generation outside the HTTP request so the Generate tab never waits."""
    from app.new_ui import _db
    con=_db()
    try:
        _ensure_tables(con)
        _seed(con,sid)
        _install_profile_sql_function(con,sid)
        try:
            run,requested,placed,unplaced,status=_generate_algorithm(
                con.cursor(),sid,class_filter,mode,complexity,replace_existing
            )
            message=(("Unplaced lesson cards: "+",".join(
                f"{lid} ({reason})" for lid,reason in unplaced
            )) if unplaced else "All requested cards placed")
            con.execute("""UPDATE timetable_generation_runs
                SET status=?,placed=?,requested=?,message=? WHERE id=? AND school_id=?""",
                (status,placed,requested,message,run_id,sid))
            con.commit()
        except Exception as exc:
            try:
                con.rollback()
            except Exception:
                pass
            con.execute("""UPDATE timetable_generation_runs
                SET status=?,placed=?,requested=?,message=? WHERE id=? AND school_id=?""",
                ("failed",0,0,"Generation error: "+str(exc)[:500],run_id,sid))
            con.commit()
    finally:
        con.close()


@router.post("/app/timetable/generate/new")
def timetable_generate_new(request:Request,background_tasks:BackgroundTasks,class_id:str=Form(""),mode:str=Form("relaxed"),complexity:str=Form("normal"),replace_existing:str=Form("")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:
        return response
    try:
        if mode not in ("draft","relaxed","strict"):
            mode="relaxed"
        if complexity not in ("normal","large","huge"):
            complexity="normal"
        cf=int(class_id) if str(class_id).isdigit() else None

        # Register the job before returning. The actual solver runs as a
        # background task, so the browser receives a response immediately.
        cur=con.cursor()
        cur.execute(
            """INSERT INTO timetable_generation_runs(
                school_id,created_at,mode,complexity,status,placed,requested,message
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (sid,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),mode,complexity,
             "running",0,0,"Generation started in background")
        )
        run_id=cur.lastrowid
        con.commit()
        background_tasks.add_task(
            _run_generation_job,sid,cf,mode,complexity,bool(replace_existing),run_id
        )
        return RedirectResponse(
            "/app/timetable?tab=generate&msg="+quote("Generation started. You can remain on this tab; it will not stall."),
            303
        )
    finally:
        con.close()


@router.post("/app/timetable/placement/place/{lesson_id}")
def timetable_placement_place(request: Request, lesson_id: int, day_name: str=Form(...), period_no: int=Form(...), class_id: str=Form("")):
    sid, con, response = _guard(request, "timetable.edit")
    if response: return response
    try:
        cur=con.cursor()
        lesson=cur.execute("SELECT * FROM timetable_lessons WHERE id=? AND school_id=?",(lesson_id,sid)).fetchone()
        if not lesson:return RedirectResponse("/app/timetable?tab=timetable&error=Lesson+card+not+found",303)
        target=int(class_id) if str(class_id).isdigit() else int(lesson["class_id"])
        linked=cur.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,lesson_id)).fetchall()
        linked_ids={int(x["class_id"]) for x in linked} or {int(lesson["class_id"])}
        if target not in linked_ids:return RedirectResponse("/app/timetable?tab=timetable&error=Lesson+is+not+assigned+to+this+class",303)
        if day_name not in DAYS:return RedirectResponse("/app/timetable?tab=timetable&error=Invalid+day",303)
        duration=max(1,int(lesson["duration"] or 1))
        if duration==2 and int(period_no)%2==0:return RedirectResponse("/app/timetable?tab=timetable&error=Double+lessons+must+start+at+1,+3,+5+or+7",303)
        pmap={int(p["period_no"]):p for p in _profile_periods(cur,sid)}
        if int(period_no) not in pmap:return RedirectResponse("/app/timetable?tab=timetable&error=Invalid+period",303)
        for pno in range(int(period_no),int(period_no)+duration):
            if pno not in pmap:return RedirectResponse("/app/timetable?tab=timetable&error=Lesson+duration+does+not+fit",303)
            if cur.execute("SELECT id FROM timetable_breaks WHERE school_id=? AND start_time<? AND end_time>? LIMIT 1",(sid,pmap[pno]["end_time"],pmap[pno]["start_time"])).fetchone():
                return RedirectResponse("/app/timetable?tab=timetable&error=Placement+crosses+a+break",303)
        count=int(cur.execute("SELECT COUNT(*) c FROM timetable_slots WHERE school_id=? AND profile_id=timetable_active_profile(school_id) AND lesson_id=?",(sid,lesson_id)).fetchone()["c"] or 0)
        if count>=max(0,int(lesson["lessons_per_week"] or 0)):return RedirectResponse("/app/timetable?tab=timetable&error=All+weekly+occurrences+are+already+placed",303)
        teacher_ids={int(x["teacher_id"]) for x in cur.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,lesson_id)).fetchall()}
        if not teacher_ids and lesson["teacher_id"]:teacher_ids={int(lesson["teacher_id"])}
        room_id=int(lesson["room_id"]) if lesson["room_id"] else None
        others=cur.execute("SELECT s.*,l.class_id,l.teacher_id,l.room_id,l.duration FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id) AND s.day_name=?",(sid,day_name)).fetchall()
        for other in others:
            if not _overlaps({"period_no":period_no,"duration":duration},other):continue
            other_classes={int(x["class_id"]) for x in cur.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,other["lesson_id"])).fetchall()} or {int(other["class_id"])}
            other_teachers={int(x["teacher_id"]) for x in cur.execute("SELECT teacher_id FROM timetable_lesson_teachers WHERE school_id=? AND lesson_id=?",(sid,other["lesson_id"])).fetchall()}
            if not other_teachers and other["teacher_id"]:other_teachers={int(other["teacher_id"])}
            if linked_ids.intersection(other_classes):return RedirectResponse("/app/timetable?tab=timetable&error=Class+conflict",303)
            if teacher_ids.intersection(other_teachers):return RedirectResponse("/app/timetable?tab=timetable&error=Teacher+conflict",303)
            if room_id and other["room_id"] and int(other["room_id"])==room_id:return RedirectResponse("/app/timetable?tab=timetable&error=Room+conflict",303)
        subject_id=int(lesson["subject_id"])
        for cid in linked_ids:
            if cur.execute("SELECT s.id FROM timetable_slots s JOIN timetable_lessons l ON l.id=s.lesson_id WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id) AND s.day_name=? AND l.subject_id=? AND (l.class_id=? OR l.id IN (SELECT lesson_id FROM timetable_lesson_classes WHERE school_id=? AND class_id=?)) LIMIT 1",(sid,day_name,subject_id,cid,sid,cid)).fetchone():
                return RedirectResponse("/app/timetable?tab=timetable&error=Subject+already+scheduled+for+this+class+that+day",303)
        start=pmap[int(period_no)]["start_time"];end=pmap[int(period_no)+duration-1]["end_time"]
        cur.execute("INSERT INTO timetable_slots(school_id,lesson_id,day_name,period_no,start_time,end_time,room_id,locked,generated_run,profile_id) VALUES(?,?,?,?,?,?,?,?,?,?)",(sid,lesson_id,day_name,period_no,start,end,room_id,0,None,_active_profile_id(con,sid)))
        con.commit()
        return RedirectResponse("/app/timetable?tab=timetable&msg=Lesson+placard+placed",303)
    finally:
        con.close()

@router.post("/app/timetable/placement/move/{rid}")
def timetable_placement_move(request:Request,rid:int,day_name:str=Form(...),period_no:int=Form(...),room_id:str=Form(""),class_id:str=Form("")):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        cur=con.cursor()
        moving=cur.execute("""SELECT s.*,l.class_id,l.teacher_id,l.duration FROM timetable_slots s
            JOIN timetable_lessons l ON l.id=s.lesson_id WHERE s.id=? AND s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id)""",(rid,sid)).fetchone()
        if not moving or int(moving["locked"] or 0):
            return RedirectResponse("/app/timetable?tab=timetable&error=Locked+or+missing+placement",303)
        if day_name not in DAYS:
            return RedirectResponse("/app/timetable?tab=timetable&error=Invalid+day",303)
        target_class_id = int(class_id) if str(class_id).isdigit() else int(moving["class_id"])
        target_class = cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(target_class_id,sid)).fetchone()
        if not target_class:
            return RedirectResponse("/app/timetable?tab=timetable&error=Invalid+target+class",303)
        linked_classes = cur.execute("SELECT class_id FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,int(moving["lesson_id"]))).fetchall()
        if len(linked_classes) > 1 and target_class_id != int(moving["class_id"]):
            return RedirectResponse("/app/timetable?tab=timetable&error=Combined+lessons+must+be+moved+as+a+group",303)
        if int(moving["duration"] or 1) == 2 and int(period_no) % 2 == 0:
            return RedirectResponse("/app/timetable?tab=timetable&error=Double+lessons+must+occupy+periods+1-2,+3-4,+5-6,+7-8",303)
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
            WHERE s.school_id=? AND s.profile_id=timetable_active_profile(s.school_id) AND s.id<>? AND s.day_name=?""",(sid,rid,day_name)).fetchall()
        probe={"period_no":period_no,"duration":int(moving["duration"] or 1)}
        for o in others:
            if not _overlaps(probe,o): continue
            if int(o["class_id"])==target_class_id or (moving["teacher_id"] and o["teacher_id"] and int(o["teacher_id"])==int(moving["teacher_id"])):
                return RedirectResponse("/app/timetable?tab=timetable&error=Class+or+teacher+conflict",303)
            if room and o["room_id"] and int(o["room_id"])==int(room):
                return RedirectResponse("/app/timetable?tab=timetable&error=Room+conflict",303)
        cur.execute("UPDATE timetable_slots SET day_name=?,period_no=?,start_time=?,end_time=?,room_id=? WHERE id=? AND school_id=?",
                    (day_name,period_no,period["start_time"],period["end_time"],room,rid,sid))
        if target_class_id != int(moving["class_id"]):
            cur.execute("UPDATE timetable_lessons SET class_id=? WHERE id=? AND school_id=?",(target_class_id,int(moving["lesson_id"]),sid))
            if linked_classes:
                cur.execute("DELETE FROM timetable_lesson_classes WHERE school_id=? AND lesson_id=?",(sid,int(moving["lesson_id"])))
            cur.execute("INSERT OR IGNORE INTO timetable_lesson_classes(school_id,lesson_id,class_id) VALUES(?,?,?)",(sid,int(moving["lesson_id"]),target_class_id))
        con.commit()
        return RedirectResponse("/app/timetable?tab=timetable&msg=Placement+moved",303)
    finally:
        con.close()
@router.post("/app/timetable/placement/platform/{rid}")
def timetable_placement_platform(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:
        return response
    try:
        cur=con.cursor()
        slot=cur.execute("SELECT id,locked FROM timetable_slots WHERE id=? AND school_id=? AND profile_id=timetable_active_profile(school_id)",(rid,sid)).fetchone()
        if not slot:
            return RedirectResponse("/app/timetable?tab=timetable&error=Placed+card+not+found",303)
        if int(slot["locked"] or 0):
            return RedirectResponse("/app/timetable?tab=timetable&error=Locked+cards+cannot+be+returned+to+the+platform",303)
        cur.execute("DELETE FROM timetable_slots WHERE id=? AND school_id=? AND profile_id=timetable_active_profile(school_id) AND locked=0",(rid,sid))
        con.commit()
        return RedirectResponse("/app/timetable?tab=timetable&msg=Lesson+card+returned+to+platform",303)
    finally:
        con.close()

@router.post("/app/timetable/placement/delete/{rid}")
def timetable_placement_delete(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        con.execute("DELETE FROM timetable_slots WHERE id=? AND school_id=? AND profile_id=timetable_active_profile(school_id) AND locked=0",(rid,sid));con.commit()
        return RedirectResponse("/app/timetable?tab=timetable&msg=Placement+deleted",303)
    finally:con.close()


@router.post("/app/timetable/placement/lock/{rid}")
def timetable_placement_lock(request:Request,rid:int):
    sid,con,response=_guard(request,"timetable.edit")
    if response:return response
    try:
        con.execute("UPDATE timetable_slots SET locked=1 WHERE id=? AND school_id=? AND profile_id=timetable_active_profile(school_id)",(rid,sid));con.commit()
        return RedirectResponse("/app/timetable?tab=timetable&msg=Placement+locked",303)
    finally:con.close()
