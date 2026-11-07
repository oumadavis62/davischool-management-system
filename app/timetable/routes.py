"""Admin-facing configuration workspace for the DaviSchool timetable v2 engine."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.setup import (
    TimetableSetupError,
    create_profile,
    save_day,
    save_period,
    save_break,
    save_calendar_exception,
    save_room,
    save_teacher_availability,
    save_class_requirement,
)


def register_timetable_setup_routes(app, get_db, get_school_obj, module_page):
    def school_for(request):
        if not request.session.get("email") or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
            return None
        return get_school_obj(request)

    def redirect_setup(profile_id=0, message="", error=False):
        parts = []
        if profile_id:
            parts.append("profile_id=" + str(int(profile_id)))
        if message:
            parts.append("message=" + quote(str(message)))
        if error:
            parts.append("error=1")
        return RedirectResponse("/school/timetable/setup" + (("?" + "&".join(parts)) if parts else ""), 303)

    @app.get("/school/timetable", response_class=HTMLResponse)
    def timetable_home(request: Request):
        if not school_for(request):
            return RedirectResponse("/", 303)
        return RedirectResponse("/school/timetable/builder", 303)

    @app.get("/school/timetable/setup", response_class=HTMLResponse)
    def timetable_setup_page(request: Request, profile_id: int = 0, message: str = "", error: int = 0):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        school_id = int(school["id"])
        con = get_db()
        cur = con.cursor()
        profiles = cur.execute(
            "SELECT * FROM ds_timetable_profiles WHERE school_id=? ORDER BY academic_year DESC,term,id DESC",
            (school_id,),
        ).fetchall()
        selected = (next((p for p in profiles if int(p["id"]) == int(profile_id)), None) or (profiles[0] if profiles else None))
        days = periods = breaks = calendar_events = rooms = teachers = allocations = availability = requirements = []
        if selected:
            pid = int(selected["id"])
            days = cur.execute("SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? ORDER BY day_order,id", (school_id,pid)).fetchall()
            periods = cur.execute("SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id", (school_id,pid)).fetchall()
            breaks = cur.execute("SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=? ORDER BY break_no,id", (school_id,pid)).fetchall()
            calendar_events = cur.execute("SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=? ORDER BY exception_date,label", (school_id,pid)).fetchall()
            rooms = cur.execute("SELECT * FROM ds_timetable_rooms WHERE school_id=? AND is_active=1 ORDER BY name", (school_id,)).fetchall()
            teachers = cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
            allocations = cur.execute(
                """SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id,c.name class_name,c.stream,
                          s.name subject_name,t.name teacher_name
                   FROM teacher_allocations ta
                   JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
                   JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
                   JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
                   WHERE ta.school_id=? ORDER BY c.name,c.stream,s.name,t.name""",
                (school_id,),
            ).fetchall()
            availability = cur.execute(
                """SELECT a.*,t.name teacher_name,d.day_name,p.label period_label
                   FROM ds_timetable_teacher_availability a
                   JOIN teachers t ON t.id=a.teacher_id AND t.school_id=a.school_id
                   JOIN ds_timetable_days d ON d.id=a.day_id AND d.profile_id=a.profile_id
                   JOIN ds_timetable_periods p ON p.id=a.period_id AND p.profile_id=a.profile_id
                   WHERE a.school_id=? AND a.profile_id=? ORDER BY d.day_order,p.period_no,t.name""",
                (school_id,pid),
            ).fetchall()
            requirements = cur.execute(
                """SELECT r.*,c.name class_name,c.stream,s.name subject_name,t.name teacher_name
                   FROM ds_timetable_class_requirements r
                   JOIN classes c ON c.id=r.class_id AND c.school_id=r.school_id
                   JOIN subjects s ON s.id=r.subject_id AND s.school_id=r.school_id
                   JOIN teachers t ON t.id=r.teacher_id AND t.school_id=r.school_id
                   WHERE r.school_id=? AND r.profile_id=? ORDER BY c.name,c.stream,s.name""",
                (school_id,pid),
            ).fetchall()
        con.close()

        esc = lambda value: escape(str(value if value is not None else ""))
        profile_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==int(selected['id']) else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])} ({esc(p['status'])})</option>"
            for p in profiles
        )
        notice = f"<div class='tt-alert {'error' if error else 'success'}'>{esc(message)}</div>" if message else ""
        pid = int(selected["id"]) if selected else 0
        hidden = f"<input type='hidden' name='profile_id' value='{pid}'>"
        selector = f"<form method='get' action='/school/timetable/setup' class='tt-select'><label for='profile_id'>Timetable profile</label><select id='profile_id' name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>" if profiles else ""
        profile_summary = (
            f"<div class='tt-profile'><div><span class='tt-kicker'>ACTIVE CONFIGURATION</span><h2>{esc(selected['name'])}</h2><p>{esc(selected['academic_year'])} · {esc(selected['term'])} · {esc(selected['academic_start_date'] or 'Start date not set')} – {esc(selected['academic_end_date'] or 'End date not set')} · <span class='tt-status'>{esc(selected['status']).upper()}</span></p></div><div class='tt-stats'><span><b>{len(days)}</b>Days</span><span><b>{len(periods)}</b>Periods</span><span><b>{len(rooms)}</b>Rooms</span></div></div>"
            if selected else "<div class='tt-empty'><b>No timetable configuration yet</b><p>Create an academic-year and term profile to begin.</p></div>"
        )
        day_rows = "".join(f"<tr><td>{esc(d['day_order'])}</td><td><b>{esc(d['day_name'])}</b></td><td>{esc(d['day_code'])}</td><td>{'Instructional' if d['is_instructional'] else 'Non-instructional'}</td></tr>" for d in days) or "<tr><td colspan='4' class='tt-muted'>No school days configured.</td></tr>"
        period_rows = "".join(f"<tr><td>{esc(p['period_no'])}</td><td><b>{esc(p['label'])}</b></td><td>{esc(p['start_time'])}–{esc(p['end_time'])}</td><td>{esc(p['duration_minutes'])} min</td><td>{esc(p['period_type'])}</td></tr>" for p in periods) or "<tr><td colspan='5' class='tt-muted'>No periods configured.</td></tr>"
        break_rows = "".join(f"<tr><td>{esc(b['break_no'])}</td><td><b>{esc(b['label'])}</b></td><td>{esc(b['start_time'])}–{esc(b['end_time'])}</td><td>{esc(b['applies_to'])}</td></tr>" for b in breaks) or "<tr><td colspan='4' class='tt-muted'>No breaks configured.</td></tr>"
        calendar_rows = "".join(f"<tr><td>{esc(e['exception_date'])}</td><td><b>{esc(e['label'])}</b></td><td>{esc(e['exception_type'])}</td><td>{'Instructional' if e['is_instructional'] else 'Non-instructional'}</td><td>{esc(e['notes'] or '—')}</td></tr>" for e in calendar_events) or "<tr><td colspan='5' class='tt-muted'>No calendar exceptions configured.</td></tr>"
        room_rows = "".join(f"<tr><td><b>{esc(r['room_code'])}</b></td><td>{esc(r['name'])}</td><td>{esc(r['room_type'])}</td><td>{esc(r['capacity'] or '—')}</td></tr>" for r in rooms) or "<tr><td colspan='4' class='tt-muted'>No rooms configured.</td></tr>"
        day_opts = "".join(f"<option value='{int(d['id'])}'>{esc(d['day_name'])}</option>" for d in days)
        period_opts = "".join(f"<option value='{int(p['id'])}'>{esc(p['label'])} ({esc(p['start_time'])}–{esc(p['end_time'])})</option>" for p in periods)
        teacher_opts = "".join(f"<option value='{int(t['id'])}'>{esc(t['name'])}</option>" for t in teachers)
        allocation_opts = "".join(f"<option value='{int(a['class_id'])}|{int(a['subject_id'])}|{int(a['teacher_id'])}'>{esc(a['class_name'])} {esc(a['stream'] or '')} · {esc(a['subject_name'])} · {esc(a['teacher_name'])}</option>" for a in allocations)
        availability_rows = "".join(f"<tr><td>{esc(a['teacher_name'])}</td><td>{esc(a['day_name'])}</td><td>{esc(a['period_label'])}</td><td><span class='tt-pill'>{esc(a['availability'])}</span></td><td>{esc(a['reason'] or '—')}</td></tr>" for a in availability) or "<tr><td colspan='5' class='tt-muted'>No teacher availability rules yet.</td></tr>"
        requirement_rows = "".join(f"<tr><td>{esc(r['class_name'])} {esc(r['stream'] or '')}</td><td>{esc(r['subject_name'])}</td><td>{esc(r['teacher_name'])}</td><td>{esc(r['lessons_per_week'])}</td><td>{esc(r['duration_periods'])}</td><td>{'Yes' if r['allow_double'] else 'No'}</td></tr>" for r in requirements) or "<tr><td colspan='6' class='tt-muted'>No weekly lesson requirements configured.</td></tr>"

        create_profile_html = """<section class='tt-card'><span class='tt-kicker'>FIRST STEP</span><h3>Create timetable profile</h3><p>Choose the academic year and term this timetable will serve.</p><form method='post' action='/school/timetable/setup/profile' class='tt-form'><label>Profile name<input name='name' required maxlength='80' placeholder='2027 Term 1 Master Timetable'></label><label>Academic year<input name='academic_year' required maxlength='20' placeholder='2027'></label><label>Term / semester<input name='term' required maxlength='40' placeholder='Term 1, Semester 1, Quarter 1…'></label><label>Academic start date<input name='academic_start_date' type='date'></label><label>Academic end date<input name='academic_end_date' type='date'></label><button class='tt-btn'>Create profile</button></form></section>"""
        sections = ""
        if selected:
            sections = f"""
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>01 · SCHOOL WEEK</span><h3>School days</h3><p>Set instructional days and their order.</p></div><form method='post' action='/school/timetable/setup/standard-week'>{hidden}<button class='tt-btn secondary'>Add Monday–Friday</button></form></div><div class='tt-split'><form method='post' action='/school/timetable/setup/day' class='tt-form compact'>{hidden}<label>Day name<input name='day_name' required placeholder='Saturday'></label><label>Day code<input name='day_code' required maxlength='8' placeholder='SAT'></label><label>Display order<input name='day_order' required type='number' min='1' max='7' value='6'></label><label class='tt-check'><input type='checkbox' name='instructional' value='1' checked> Instructional day</label><button class='tt-btn'>Save day</button></form><div class='tt-table'><table><tr><th>Order</th><th>Day</th><th>Code</th><th>Type</th></tr>{day_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>02 · DAILY STRUCTURE</span><h3>Teaching periods</h3><p>Define period numbering and exact time boundaries.</p></div></div><div class='tt-split'><form method='post' action='/school/timetable/setup/period' class='tt-form compact'>{hidden}<label>Period number<input name='period_no' type='number' min='1' max='30' required></label><label>Period label<input name='label' required placeholder='Period 1'></label><label>Start time<input name='start_time' type='time' required value='08:00'></label><label>End time<input name='end_time' type='time' required value='08:40'></label><label>Period type<select name='period_type'><option value='lesson'>Lesson</option><option value='study'>Study</option><option value='assembly'>Assembly</option></select></label><button class='tt-btn'>Save period</button></form><div class='tt-table'><table><tr><th>#</th><th>Period</th><th>Time</th><th>Duration</th><th>Type</th></tr>{period_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>03 · NON-TEACHING TIME</span><h3>Breaks and lunch</h3><p>Prevent lesson allocation during configured breaks.</p></div></div><div class='tt-split'><form method='post' action='/school/timetable/setup/break' class='tt-form compact'>{hidden}<label>Break number<input name='break_no' type='number' min='1' max='20' required></label><label>Break name<input name='label' required placeholder='Tea break'></label><label>Start time<input name='start_time' type='time' required value='10:00'></label><label>End time<input name='end_time' type='time' required value='10:20'></label><label>Applies to<select name='applies_to'><option value='all'>All classes</option><option value='selected'>Selected groups (configure later)</option></select></label><button class='tt-btn'>Save break</button></form><div class='tt-table'><table><tr><th>#</th><th>Break</th><th>Time</th><th>Scope</th></tr>{break_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>04 · ACADEMIC CALENDAR</span><h3>Holidays and special dates</h3><p>Mark closures, holidays and exceptional instructional days inside this term.</p></div></div><div class='tt-split'><form method='post' action='/school/timetable/setup/calendar-event' class='tt-form compact'>{hidden}<label>Date<input name='exception_date' type='date' required></label><label>Event name<input name='label' required placeholder='National holiday'></label><label>Event type<select name='exception_type'><option value='holiday'>Public / school holiday</option><option value='school_closure'>School closure</option><option value='special_instructional_day'>Special instructional day</option><option value='event'>School event</option></select></label><label>Notes<input name='notes' maxlength='180' placeholder='Optional details'></label><label class='tt-check'><input type='checkbox' name='instructional' value='1'> Instructional day</label><button class='tt-btn'>Save calendar date</button></form><div class='tt-table'><table><tr><th>Date</th><th>Event</th><th>Type</th><th>Day type</th><th>Notes</th></tr>{calendar_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>05 · LEARNING SPACES</span><h3>Rooms and facilities</h3><p>Register classrooms, laboratories, halls and specialist spaces.</p></div></div><div class='tt-split'><form method='post' action='/school/timetable/setup/room' class='tt-form compact'>{hidden}<label>Room code<input name='room_code' required placeholder='LAB-01'></label><label>Room name<input name='name' required placeholder='Science Laboratory'></label><label>Room type<select name='room_type'><option value='classroom'>Classroom</option><option value='laboratory'>Laboratory</option><option value='library'>Library</option><option value='hall'>Hall</option><option value='workshop'>Workshop</option><option value='sports'>Sports facility</option><option value='other'>Other</option></select></label><label>Capacity<input name='capacity' type='number' min='1' placeholder='40'></label><button class='tt-btn'>Save room</button></form><div class='tt-table'><table><tr><th>Code</th><th>Room</th><th>Type</th><th>Capacity</th></tr>{room_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>06 · STAFF AVAILABILITY</span><h3>Teacher availability</h3><p>Mark unavailable or preferred teacher periods.</p></div></div><div class='tt-split'><form method='post' action='/school/timetable/setup/availability' class='tt-form compact'>{hidden}<label>Teacher<select name='teacher_id' required><option value=''>Select teacher</option>{teacher_opts}</select></label><label>Day<select name='day_id' required><option value=''>Select day</option>{day_opts}</select></label><label>Period<select name='period_id' required><option value=''>Select period</option>{period_opts}</select></label><label>Availability<select name='availability'><option value='unavailable'>Unavailable</option><option value='preferred'>Preferred</option><option value='available'>Available</option></select></label><label>Reason<input name='reason' maxlength='160' placeholder='e.g. Part-time availability'></label><button class='tt-btn'>Save availability</button></form><div class='tt-table'><table><tr><th>Teacher</th><th>Day</th><th>Period</th><th>Status</th><th>Reason</th></tr>{availability_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>07 · WEEKLY LESSON LOAD</span><h3>Class subject requirements</h3><p>Set weekly lesson frequency using existing teacher allocations.</p></div></div><div class='tt-split'><form method='post' action='/school/timetable/setup/requirement' class='tt-form compact'>{hidden}<label class='wide'>Allocated class · subject · teacher<select name='allocation' required><option value=''>Select existing allocation</option>{allocation_opts}</select></label><label>Lessons per week<input name='lessons_per_week' type='number' min='1' max='30' required value='5'></label><label>Duration<select name='duration_periods'><option value='1'>Single period</option><option value='2'>Double period</option><option value='3'>Triple period</option></select></label><label>Maximum per day<input name='max_lessons_per_day' type='number' min='1' max='10' placeholder='No limit'></label><label class='tt-check'><input type='checkbox' name='allow_double' value='1'> Allow double lessons</label><button class='tt-btn'>Save requirement</button></form><div class='tt-table'><table><tr><th>Class / Stream</th><th>Subject</th><th>Teacher</th><th>Weekly</th><th>Duration</th><th>Double</th></tr>{requirement_rows}</table></div></div></section>
            """
        body = f"""
        <style>
        .tt-wrap{{max-width:1500px;margin:auto;padding:22px;color:#163b2a}}.tt-hero{{display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:18px}}.tt-hero h1{{font-size:28px;margin:3px 0 6px;color:#173d2b}}.tt-hero p,.tt-section-title p,.tt-card p,.tt-profile p{{color:#64748b;font-size:13px;margin:5px 0 0}}.tt-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}.tt-card,.tt-section,.tt-profile,.tt-empty{{background:#fff;border:1px solid #e1ebe3;border-radius:16px;padding:18px;margin-bottom:16px;box-shadow:0 3px 12px #173d2b08}}.tt-card h3,.tt-section h3{{font-size:17px;margin:4px 0;color:#173d2b}}.tt-profile{{display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;border-left:4px solid #287447}}.tt-profile h2{{margin:4px 0;font-size:21px}}.tt-stats{{display:flex;gap:18px}}.tt-stats span{{font-size:11px;color:#64748b;text-align:center}}.tt-stats b{{display:block;font-size:22px;color:#173d2b}}.tt-status,.tt-pill{{background:#eaf5ec;color:#23613b;border-radius:20px;padding:4px 8px;font-size:10px;font-weight:800}}.tt-select{{display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap}}.tt-select label{{font-size:12px;font-weight:800}}.tt-select select{{min-width:260px;max-width:100%;padding:10px;border:1px solid #d7e5d9;border-radius:9px;background:white}}.tt-section-title{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:14px}}.tt-split{{display:grid;grid-template-columns:minmax(240px,.85fr) minmax(0,1.4fr);gap:16px;align-items:start}}.tt-form{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-items:end}}.tt-form.compact{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tt-form label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:#334155}}.tt-form label.wide{{grid-column:1/-1}}.tt-form input,.tt-form select{{width:100%;min-width:0;padding:10px;border:1px solid #dce7de;border-radius:9px;background:#fff;font:13px Arial;color:#173d2b}}.tt-form .tt-check{{flex-direction:row;align-items:center;gap:7px;padding:9px 0}}.tt-form .tt-check input{{width:auto}}.tt-btn{{border:0;border-radius:9px;padding:11px 15px;background:#17633b;color:white;font-weight:800;font-size:12px;cursor:pointer;min-height:39px}}.tt-btn:hover{{background:#104b2c}}.tt-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8}}.tt-table{{overflow:auto;border:1px solid #e7eee8;border-radius:10px}}.tt-table table{{width:100%;border-collapse:collapse;min-width:450px}}.tt-table th{{background:#f0f6f1;color:#315b3e;text-align:left;font-size:10px;letter-spacing:.04em}}.tt-table th,.tt-table td{{padding:10px;border-bottom:1px solid #edf2ed;font-size:11px;white-space:nowrap}}.tt-muted{{color:#94a3a0;text-align:center;padding:18px!important}}.tt-alert{{padding:12px 14px;border-radius:10px;margin-bottom:14px;font-size:12px;font-weight:700}}.tt-alert.success{{background:#eaf5ec;color:#17633b}}.tt-alert.error{{background:#fff1f0;color:#a12828}}.tt-empty{{text-align:center;padding:34px}}.tt-empty b{{font-size:18px}}@media(max-width:900px){{.tt-split{{grid-template-columns:1fr}}.tt-form{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:600px){{.tt-wrap{{padding:14px}}.tt-hero h1{{font-size:23px}}.tt-form,.tt-form.compact{{grid-template-columns:1fr}}.tt-form label.wide{{grid-column:auto}}.tt-stats{{width:100%;justify-content:space-around}}}}
        </style><div class='tt-wrap'><div class='tt-hero'><div><span class='tt-kicker'>DAVISCHOOL · SCHEDULING ENGINE</span><h1>Timetable Setup</h1><p>Configure your academic calendar, school week, teaching periods, facilities and lesson requirements.</p></div><div style='display:flex;gap:8px;flex-wrap:wrap'><a class='tt-btn' href='/school/timetable/builder?profile_id={profile_id_value}'>Open Manual Builder</a><a class='tt-btn secondary' href='/school/dashboard'>← School overview</a></div></div>{notice}{selector}{profile_summary}{create_profile_html if not profiles else ""}{sections}</div>
        """
        return module_page(request, "Timetable Setup", "timetable", body)

    @app.post("/school/timetable/setup/profile")
    def create_timetable_profile(request: Request, name: str = Form(...), academic_year: str = Form(...), term: str = Form(...), academic_start_date: str = Form(""), academic_end_date: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            pid = create_profile(con, int(school["id"]), name, academic_year, term, request.session.get("email", ""), academic_start_date, academic_end_date)
            return redirect_setup(pid, "Timetable profile created. Configure the school days and periods next.")
        except TimetableSetupError as exc:
            return redirect_setup(message=str(exc), error=True)
        finally:
            con.close()

    @app.post("/school/timetable/setup/standard-week")
    def create_standard_week(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            for order, (code, name) in enumerate((("MON","Monday"),("TUE","Tuesday"),("WED","Wednesday"),("THU","Thursday"),("FRI","Friday")), 1):
                save_day(con, int(school["id"]), profile_id, code, name, order, True)
            return redirect_setup(profile_id, "Standard Monday–Friday school week saved.")
        except TimetableSetupError as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/school/timetable/setup/day")
    def create_timetable_day(request: Request, profile_id: int = Form(...), day_name: str = Form(...), day_code: str = Form(...), day_order: int = Form(...), instructional: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_day(con, int(school["id"]), profile_id, day_code, day_name, day_order, instructional == "1")
            return redirect_setup(profile_id, "School day saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/school/timetable/setup/period")
    def create_timetable_period(request: Request, profile_id: int = Form(...), period_no: int = Form(...), label: str = Form(...), start_time: str = Form(...), end_time: str = Form(...), period_type: str = Form("lesson")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_period(con, int(school["id"]), profile_id, period_no, label, start_time, end_time, period_type)
            return redirect_setup(profile_id, "Teaching period saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/school/timetable/setup/break")
    def create_timetable_break(request: Request, profile_id: int = Form(...), break_no: int = Form(...), label: str = Form(...), start_time: str = Form(...), end_time: str = Form(...), applies_to: str = Form("all")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_break(con, int(school["id"]), profile_id, break_no, label, start_time, end_time, applies_to)
            return redirect_setup(profile_id, "Break saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/school/timetable/setup/calendar-event")
    def create_timetable_calendar_event(request: Request, profile_id: int = Form(...), exception_date: str = Form(...), label: str = Form(...), exception_type: str = Form("holiday"), notes: str = Form(""), instructional: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_calendar_exception(con, int(school["id"]), profile_id, exception_date, label, exception_type, notes, instructional == "1")
            return redirect_setup(profile_id, "Academic calendar date saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/school/timetable/setup/room")
    def create_timetable_room(request: Request, room_code: str = Form(...), name: str = Form(...), room_type: str = Form("classroom"), capacity: str = Form(""), profile_id: int = Form(0)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_room(con, int(school["id"]), room_code, name, room_type, int(capacity) if capacity.strip() else None)
            return redirect_setup(profile_id, "Room or facility saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(message=str(exc), error=True)
        finally: con.close()

    @app.post("/school/timetable/setup/availability")
    def create_timetable_availability(request: Request, profile_id: int = Form(...), teacher_id: int = Form(...), day_id: int = Form(...), period_id: int = Form(...), availability: str = Form(...), reason: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_teacher_availability(con, int(school["id"]), profile_id, teacher_id, day_id, period_id, availability, reason)
            return redirect_setup(profile_id, "Teacher availability saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/school/timetable/setup/requirement")
    def create_timetable_requirement(request: Request, profile_id: int = Form(...), allocation: str = Form(...), lessons_per_week: int = Form(...), duration_periods: int = Form(1), max_lessons_per_day: str = Form(""), allow_double: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            parts = allocation.split("|")
            if len(parts) != 3:
                raise TimetableSetupError("Select a valid teacher allocation.")
            class_id, subject_id, teacher_id = (int(part) for part in parts)
            save_class_requirement(con, int(school["id"]), profile_id, class_id, subject_id, teacher_id, lessons_per_week, duration_periods, int(max_lessons_per_day) if max_lessons_per_day.strip() else None, allow_double == "1")
            return redirect_setup(profile_id, "Weekly lesson requirement saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()
