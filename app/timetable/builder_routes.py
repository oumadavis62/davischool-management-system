"""Manual timetable builder UI and actions."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.setup import TimetableSetupError
from app.timetable.builder import place_lesson, move_lesson, delete_lesson


def register_timetable_builder_routes(app, get_db, get_school_obj, module_page):
    def school_for(request):
        if not request.session.get("email") or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
            return None
        return get_school_obj(request)

    def redirect_builder(profile_id=0, message="", error=False):
        parts = []
        if profile_id:
            parts.append("profile_id=" + str(int(profile_id)))
        if message:
            parts.append("message=" + quote(str(message)))
        if error:
            parts.append("error=1")
        return RedirectResponse("/school/timetable/builder" + (("?" + "&".join(parts)) if parts else ""), 303)

    @app.get("/school/timetable/builder", response_class=HTMLResponse)
    def timetable_builder_page(request: Request, profile_id: int = 0, day_id: int = 0, period_id: int = 0, message: str = "", error: int = 0):
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
        days = periods = rooms = allocations = requirements = lessons = calendar_events = []
        if selected:
            pid = int(selected["id"])
            days = cur.execute(
                "SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? AND is_instructional=1 ORDER BY day_order,id",
                (school_id,pid),
            ).fetchall()
            periods = cur.execute(
                "SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? AND period_type='lesson' ORDER BY period_no,id",
                (school_id,pid),
            ).fetchall()
            rooms = cur.execute(
                "SELECT * FROM ds_timetable_rooms WHERE school_id=? AND is_active=1 ORDER BY name",
                (school_id,),
            ).fetchall()
            requirements = cur.execute(
                "SELECT * FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=? ORDER BY class_id,subject_id",
                (school_id,pid),
            ).fetchall()
            allocations = cur.execute(
                """SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id,c.name class_name,c.stream,
                          s.name subject_name,t.name teacher_name,r.duration_periods,r.lessons_per_week
                   FROM teacher_allocations ta
                   JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
                   JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
                   JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
                   JOIN ds_timetable_class_requirements r
                     ON r.school_id=ta.school_id AND r.class_id=ta.class_id
                    AND r.subject_id=ta.subject_id AND r.teacher_id=ta.teacher_id
                    AND r.profile_id=?
                   WHERE ta.school_id=? ORDER BY c.name,c.stream,s.name,t.name""",
                (pid,school_id),
            ).fetchall()
            lessons = cur.execute(
                """SELECT l.*,c.name class_name,c.stream,s.name subject_name,t.name teacher_name,
                          rm.name room_name,p.period_no,p.label period_label,p.start_time,p.end_time,d.day_name
                   FROM ds_timetable_lessons l
                   JOIN classes c ON c.id=l.class_id AND c.school_id=l.school_id
                   JOIN subjects s ON s.id=l.subject_id AND s.school_id=l.school_id
                   JOIN teachers t ON t.id=l.teacher_id AND t.school_id=l.school_id
                   LEFT JOIN ds_timetable_rooms rm ON rm.id=l.room_id AND rm.school_id=l.school_id
                   JOIN ds_timetable_periods p ON p.id=l.period_id AND p.profile_id=l.profile_id
                   JOIN ds_timetable_days d ON d.id=l.day_id AND d.profile_id=l.profile_id
                   WHERE l.school_id=? AND l.profile_id=? AND l.status='scheduled'
                   ORDER BY d.day_order,p.period_no,c.name,s.name""",
                (school_id,pid),
            ).fetchall()
            calendar_events = cur.execute(
                "SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=? ORDER BY exception_date",
                (school_id,pid),
            ).fetchall()
        con.close()

        esc = lambda value: escape(str(value if value is not None else ""))
        pid = int(selected["id"]) if selected else 0
        notice = f"<div class='tb-alert {'error' if error else 'success'}'>{esc(message)}</div>" if message else ""
        profile_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==pid else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])}</option>"
            for p in profiles
        )
        profile_selector = f"<form method='get' action='/school/timetable/builder' class='tb-profile-select'><label>Timetable profile</label><select name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>" if profiles else ""
        if not selected:
            body = f"""<style>.tb-empty{{max-width:800px;margin:30px auto;background:white;padding:30px;border-radius:16px;text-align:center}}</style><div class='tb-empty'><h2>No timetable profile yet</h2><p>Create an academic-year and term profile before building the weekly timetable.</p><a href='/school/timetable/setup' class='btn'>Open Timetable Setup</a></div>"""
            return module_page(request, "Timetable Builder", "timetable", body)

        allocation_options = "".join(
            f"<option value='{int(a['class_id'])}|{int(a['subject_id'])}|{int(a['teacher_id'])}'>{esc(a['class_name'])} {esc(a['stream'] or '')} · {esc(a['subject_name'])} · {esc(a['teacher_name'])} ({esc(a['lessons_per_week'])}/week, {esc(a['duration_periods'])} period)</option>"
            for a in allocations
        )
        day_options = "".join(
            f"<option value='{int(d['id'])}' {'selected' if int(d['id'])==int(day_id) else ''}>{esc(d['day_name'])}</option>"
            for d in days
        )
        period_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if int(p['id'])==int(period_id) else ''}>{esc(p['label'])} · {esc(p['start_time'])}–{esc(p['end_time'])}</option>"
            for p in periods
        )
        room_options = "<option value=''>No room assigned</option>" + "".join(
            f"<option value='{int(r['id'])}'>{esc(r['name'])} ({esc(r['room_type'])})</option>" for r in rooms
        )
        period_index = {int(p["id"]): i for i,p in enumerate(periods)}
        lesson_by_start = {(int(l["day_id"]),int(l["period_id"])):l for l in lessons}
        occupied = {}
        for lesson in lessons:
            start = period_index.get(int(lesson["period_id"]))
            if start is None:
                continue
            for offset in range(1,int(lesson["duration_periods"] or 1)):
                if start + offset < len(periods):
                    occupied[(int(lesson["day_id"]),int(periods[start+offset]["id"]))] = lesson
        rows = []
        for period in periods:
            cells = []
            for day in days:
                key = (int(day["id"]),int(period["id"]))
                lesson = lesson_by_start.get(key)
                if lesson:
                    duration = int(lesson["duration_periods"] or 1)
                    room_label = esc(lesson["room_name"] or "Room not assigned")
                    move_day_opts = "".join(
                        f"<option value='{int(d['id'])}' {'selected' if int(d['id'])==int(lesson['day_id']) else ''}>{esc(d['day_name'])}</option>" for d in days
                    )
                    move_period_opts = "".join(
                        f"<option value='{int(p['id'])}' {'selected' if int(p['id'])==int(lesson['period_id']) else ''}>{esc(p['label'])} ({esc(p['start_time'])})</option>" for p in periods
                    )
                    move_room_opts = "<option value=''>Keep current room</option>" + "".join(
                        f"<option value='{int(r['id'])}' {'selected' if lesson['room_id'] is not None and int(r['id'])==int(lesson['room_id']) else ''}>{esc(r['name'])}</option>" for r in rooms
                    )
                    card = f"""<div class='tb-lesson' draggable='true' data-lesson-id='{int(lesson['id'])}' ondragstart='dragTimetableLesson(event)'><div class='tb-lesson-top'><b>{esc(lesson['subject_name'])}</b><span>{duration}P</span></div><div class='tb-class'>{esc(lesson['class_name'])} {esc(lesson['stream'] or '')}</div><div class='tb-meta'>{esc(lesson['teacher_name'])}</div><div class='tb-meta'>⌂ {room_label}</div><details class='tb-actions'><summary>Manage</summary><form method='post' action='/school/timetable/builder/move'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='lesson_id' value='{int(lesson['id'])}'><label>Move to day<select name='day_id'>{move_day_opts}</select></label><label>Start period<select name='period_id'>{move_period_opts}</select></label><label>Room<select name='room_id'>{move_room_opts}</select></label><button class='tb-small'>Move lesson</button></form><form method='post' action='/school/timetable/builder/delete' onsubmit='return confirm("Remove this lesson from the timetable?")'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='lesson_id' value='{int(lesson['id'])}'><button class='tb-delete'>Delete lesson</button></form></details></div>"""
                    cells.append(f"<td class='tb-cell' data-day-id='{int(day['id'])}' data-period-id='{int(period['id'])}' ondragover='event.preventDefault()' ondrop='dropTimetableLesson(event,this)'>{card}</td>")
                elif key in occupied:
                    continued = occupied[key]
                    cells.append(f"<td class='tb-cell tb-continued' data-day-id='{int(day['id'])}' data-period-id='{int(period['id'])}' ondragover='event.preventDefault()' ondrop='dropTimetableLesson(event,this)'>↳ {esc(continued['subject_name'])} continues</td>")
                else:
                    cells.append(f"<td class='tb-cell tb-free' data-day-id='{int(day['id'])}' data-period-id='{int(period['id'])}' ondragover='event.preventDefault()' ondrop='dropTimetableLesson(event,this)'><span>Free period</span></td>")
            rows.append(f"<tr><th class='tb-period'><b>{esc(period['label'])}</b><span>{esc(period['start_time'])}–{esc(period['end_time'])}</span></th>{''.join(cells)}</tr>")
        day_headers = "".join("<th>" + esc(d["day_name"]) + "</th>" for d in days)
        grid = f"<div class='tb-grid-scroll'><table class='tb-grid'><thead><tr><th>Period</th>{day_headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>" if days and periods else "<div class='tb-empty'>Configure at least one instructional day and one teaching period in Timetable Setup.</div>"
        add_form = (
            f"""<section class='tb-panel'><div><span class='tb-kicker'>MANUAL SCHEDULING</span><h3>Add a lesson</h3><p>Choose an existing class, subject and allocated teacher. Lesson duration follows the weekly requirement.</p></div><form method='post' action='/school/timetable/builder/add' class='tb-add-form'><input type='hidden' name='profile_id' value='{pid}'><label class='wide'>Class · subject · teacher<select name='allocation' required><option value=''>Select configured requirement</option>{allocation_options}</select></label><label>Day<select name='day_id' required><option value=''>Select day</option>{day_options}</select></label><label>Start period<select name='period_id' required><option value=''>Select period</option>{period_options}</select></label><label>Room<select name='room_id'>{room_options}</select></label><button class='tb-btn'>＋ Add lesson</button></form></section>"""
            if allocations and days and periods else
            "<section class='tb-panel'><h3>Complete setup first</h3><p>Configure school days, teaching periods and weekly class-subject requirements before placing lessons.</p><a class='tb-btn' href='/school/timetable/setup'>Open Timetable Setup</a></section>"
        )
        body = f"""
        <style>
        .tb-wrap{{max-width:1700px;margin:auto;padding:20px;color:#173d2b}}.tb-hero{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}}.tb-hero h2{{font-size:26px;margin:3px 0 5px}}.tb-hero p{{font-size:13px;color:#64748b;margin:0}}.tb-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}.tb-btn{{display:inline-flex;align-items:center;justify-content:center;padding:10px 14px;border:0;border-radius:9px;background:#17633b;color:white;text-decoration:none;font-size:12px;font-weight:800;cursor:pointer}}.tb-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8}}.tb-profile-select{{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}}.tb-profile-select label{{font-size:12px;font-weight:800}}.tb-profile-select select{{min-width:280px;padding:10px;border:1px solid #dce7de;border-radius:9px;background:white}}.tb-panel{{background:white;border:1px solid #e1ebe3;border-radius:15px;padding:16px;margin-bottom:16px;box-shadow:0 3px 12px #173d2b08}}.tb-panel h3{{margin:4px 0;color:#173d2b;font-size:17px}}.tb-panel p{{margin:4px 0 12px;color:#64748b;font-size:12px}}.tb-add-form{{display:grid;grid-template-columns:2fr 1fr 1fr 1fr auto;gap:10px;align-items:end}}.tb-add-form label,.tb-actions label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:#334155}}.tb-add-form label.wide{{grid-column:auto}}.tb-add-form select,.tb-actions select{{width:100%;min-width:0;padding:10px;border:1px solid #dce7de;border-radius:9px;background:white;font-size:12px}}.tb-grid-scroll{{overflow:auto;border:1px solid #dce7de;border-radius:13px;background:white}}.tb-grid{{width:100%;border-collapse:separate;border-spacing:0;min-width:850px}}.tb-grid thead th{{background:#17633b;color:white;padding:13px 10px;text-align:center;font-size:12px;position:sticky;top:0}}.tb-grid .tb-period{{min-width:115px;background:#f0f6f1;color:#315b3e;text-align:left;position:sticky;left:0;z-index:1}}.tb-period b,.tb-period span{{display:block}}.tb-period span{{font-size:10px;color:#64748b;font-weight:500;margin-top:4px}}.tb-cell{{height:120px;min-width:150px;vertical-align:top;padding:7px;border-right:1px solid #edf2ed;border-bottom:1px solid #edf2ed;background:#fff}}.tb-free{{background:#fbfdfb;text-align:center;vertical-align:middle;color:#a2b3a5;font-size:10px}}.tb-free:hover{{background:#eff8f0}}.tb-continued{{background:#f6faf6;color:#7b9480;text-align:center;vertical-align:middle;font-size:10px;border-top:0}}.tb-lesson{{background:#eaf5ec;border-left:3px solid #287447;border-radius:9px;padding:8px;min-height:100px;color:#173d2b;cursor:grab;box-shadow:0 1px 4px #173d2b10}}.tb-lesson:active{{cursor:grabbing}}.tb-lesson-top{{display:flex;justify-content:space-between;gap:5px;font-size:11px}}.tb-lesson-top span{{font-size:9px;background:#d5e9d9;border-radius:10px;padding:2px 5px;white-space:nowrap}}.tb-class{{font-size:10px;font-weight:800;margin-top:5px}}.tb-meta{{font-size:9px;color:#55705d;margin-top:4px}}.tb-actions{{margin-top:6px;font-size:10px}}.tb-actions summary{{cursor:pointer;color:#17633b;font-weight:800}}.tb-actions form{{display:grid;gap:6px;margin-top:7px}}.tb-small,.tb-delete{{padding:7px;border:0;border-radius:7px;font-size:10px;font-weight:800;cursor:pointer}}.tb-small{{background:#17633b;color:white}}.tb-delete{{background:#fff0ef;color:#a12828}}.tb-alert{{padding:11px 14px;border-radius:9px;margin-bottom:12px;font-size:12px;font-weight:700}}.tb-alert.success{{background:#eaf5ec;color:#17633b}}.tb-alert.error{{background:#fff1f0;color:#a12828}}.tb-empty{{padding:30px;text-align:center;color:#64748b;background:#fff;border:1px dashed #cdddcf;border-radius:12px}}@media(max-width:900px){{.tb-add-form{{grid-template-columns:1fr 1fr}}.tb-add-form label.wide{{grid-column:1/-1}}}}@media(max-width:600px){{.tb-wrap{{padding:12px}}.tb-hero h2{{font-size:22px}}.tb-add-form{{grid-template-columns:1fr}}.tb-add-form label.wide{{grid-column:auto}}}}
        </style>
        <div class='tb-wrap'><div class='tb-hero'><div><span class='tb-kicker'>DAVISCHOOL · MANUAL SCHEDULING</span><h2>Master Timetable Builder</h2><p>Place lessons, move them between periods and resolve clashes as you build.</p></div><div style='display:flex;gap:8px;flex-wrap:wrap'><a class='tb-btn secondary' href='/school/timetable/setup?profile_id={pid}'>⚙ Setup</a><a class='tb-btn secondary' href='/school/dashboard'>School overview</a></div></div>{notice}{profile_selector}<div class='tb-panel'><b>{esc(selected['name'])}</b><span style='font-size:11px;color:#64748b'> · {esc(selected['academic_year'])} · {esc(selected['term'])}</span><span style='float:right;font-size:11px;color:#17633b;font-weight:800'>{len(lessons)} scheduled lessons · {len(requirements)} requirements · {len(calendar_events)} calendar dates</span></div>{add_form}{grid}</div>
        <script>
        function dragTimetableLesson(event){{var card=event.target.closest('[data-lesson-id]');if(card)event.dataTransfer.setData('text/plain',card.dataset.lessonId);}}
        function dropTimetableLesson(event,cell){{event.preventDefault();var lessonId=event.dataTransfer.getData('text/plain');if(!lessonId)return;var form=document.createElement('form');form.method='POST';form.action='/school/timetable/builder/move';[['profile_id','{pid}'],['lesson_id',lessonId],['day_id',cell.dataset.dayId],['period_id',cell.dataset.periodId]].forEach(function(pair){{var input=document.createElement('input');input.type='hidden';input.name=pair[0];input.value=pair[1];form.appendChild(input);}});document.body.appendChild(form);form.submit();}}
        </script>
        """
        return module_page(request, "Timetable Builder", "timetable", body)

    @app.post("/school/timetable/builder/add")
    def timetable_builder_add(request: Request, profile_id: int = Form(...), allocation: str = Form(...), day_id: int = Form(...), period_id: int = Form(...), room_id: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            parts = allocation.split("|")
            if len(parts) != 3:
                raise TimetableSetupError("Select a valid class, subject and teacher allocation.")
            class_id, subject_id, teacher_id = (int(part) for part in parts)
            lesson_id = place_lesson(
                con, int(school["id"]), profile_id, class_id, subject_id, teacher_id,
                day_id, period_id, int(room_id) if room_id.strip() else None,
                request.session.get("email", ""),
            )
            return redirect_builder(profile_id, "Lesson added to the timetable.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_builder(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/school/timetable/builder/move")
    def timetable_builder_move(request: Request, profile_id: int = Form(...), lesson_id: int = Form(...), day_id: int = Form(...), period_id: int = Form(...), room_id: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            move_lesson(con, int(school["id"]), profile_id, lesson_id, day_id, period_id, request.session.get("email", ""), int(room_id) if room_id.strip() else None)
            return redirect_builder(profile_id, "Lesson moved successfully.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_builder(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/school/timetable/builder/delete")
    def timetable_builder_delete(request: Request, profile_id: int = Form(...), lesson_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            delete_lesson(con, int(school["id"]), profile_id, lesson_id, request.session.get("email", ""))
            return redirect_builder(profile_id, "Lesson removed from the timetable.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_builder(profile_id, str(exc), True)
        finally: con.close()
