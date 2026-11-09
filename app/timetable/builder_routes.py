"""Manual timetable builder with days as rows and period/break columns."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.timetable.setup import TimetableSetupError
from app.timetable.builder import place_lesson, move_lesson, delete_lesson, place_advanced_requirement_session, place_dated_advanced_requirement_session
from app.timetable.session_engine import create_teaching_group
from app.timetable.advanced_setup import create_scheduling_requirement, save_scheduling_pattern
from app.timetable.advanced_setup import resolve_calendar_occurrence


def register_timetable_builder_routes(app, get_db, get_school_obj, module_page):
    from app.timetable.navigation import timetable_workspace
    _base_module_page = module_page
    def module_page(request, title, module, body):
        return _base_module_page(request, title, module, timetable_workspace(request, body))
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
        return RedirectResponse("/app/timetable/builder" + (("?" + "&".join(parts)) if parts else ""), 303)

    @app.post("/app/timetable/builder")
    async def timetable_builder_post_fallback(request: Request):
        """Accept legacy/current-page form posts and dispatch them to the same validated operations."""
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        form = await request.form()
        def value(name, default=""):
            return str(form.get(name, default) or default).strip()
        def integer(name, default=0):
            try:
                return int(value(name, str(default)))
            except (TypeError, ValueError):
                return default
        profile_id = integer("profile_id")
        school_id = int(school["id"])
        con = get_db()
        try:
            if value("allocation"):
                parts = value("allocation").split("|")
                if len(parts) != 3:
                    raise TimetableSetupError("Select a valid class, subject and teacher allocation.")
                place_lesson(con, school_id, profile_id, *(int(part) for part in parts),
                    integer("day_id"), integer("period_id"), integer("room_id") or None,
                    request.session.get("email", ""))
                message = "Lesson added to the timetable."
            elif value("lesson_id") and value("day_id") and value("period_id"):
                move_lesson(con, school_id, profile_id, integer("lesson_id"),
                    integer("day_id"), integer("period_id"), request.session.get("email", ""),
                    integer("room_id") or None)
                message = "Lesson moved successfully."
            elif value("lesson_id"):
                delete_lesson(con, school_id, profile_id, integer("lesson_id"),
                    request.session.get("email", ""))
                message = "Lesson removed from the timetable."
            elif value("session_id"):
                con.execute("UPDATE ds_timetable_sessions SET status='cancelled' WHERE id=? AND school_id=? AND profile_id=? AND status='scheduled'",
                    (integer("session_id"), school_id, profile_id))
                con.commit()
                message = "Session removed from the active timetable; its record is retained."
            elif value("group_id"):
                group_id = integer("group_id")
                row = con.execute("SELECT id FROM ds_timetable_teaching_groups WHERE id=? AND school_id=? AND profile_id=?",
                    (group_id, school_id, profile_id)).fetchone()
                if not row:
                    raise TimetableSetupError("Combined teaching group not found.")
                con.execute("UPDATE ds_timetable_scheduling_requirements SET is_active=0 WHERE school_id=? AND profile_id=? AND teaching_group_id=?",
                    (school_id, profile_id, group_id))
                con.execute("UPDATE ds_timetable_teaching_groups SET is_active=0 WHERE id=? AND school_id=? AND profile_id=?",
                    (group_id, school_id, profile_id))
                con.commit()
                message = "Combined group deactivated; saved history is retained."
            elif value("requirement_id") and value("room_assignment_mode"):
                mode = value("room_assignment_mode").lower()
                room_id = integer("preferred_room_id") or None
                if mode not in {"automatic", "preferred", "fixed"}:
                    raise TimetableSetupError("Choose Automatic, Preferred or Fixed room allocation.")
                if mode in {"preferred", "fixed"} and room_id is None:
                    raise TimetableSetupError("Choose a room for Preferred or Fixed allocation.")
                requirement = con.execute("SELECT room_type FROM ds_timetable_scheduling_requirements WHERE id=? AND school_id=? AND profile_id=? AND is_active=1",
                    (integer("requirement_id"), school_id, profile_id)).fetchone()
                if not requirement:
                    raise TimetableSetupError("Select a valid scheduling requirement.")
                if room_id is not None:
                    room = con.execute("SELECT room_type,is_active FROM ds_timetable_rooms WHERE id=? AND school_id=?",
                        (room_id, school_id)).fetchone()
                    if not room or not int(room["is_active"] or 0):
                        raise TimetableSetupError("Select an active room.")
                    if requirement["room_type"] and str(room["room_type"]) != str(requirement["room_type"]):
                        raise TimetableSetupError("The selected room does not match the required room type.")
                con.execute("UPDATE ds_timetable_scheduling_requirements SET room_assignment_mode=?,preferred_room_id=? WHERE id=? AND school_id=? AND profile_id=?",
                    (mode, None if mode == "automatic" else room_id, integer("requirement_id"), school_id, profile_id))
                con.commit()
                message = "Room allocation rule saved."
            elif value("requirement_id") and value("day_id") and value("period_id"):
                place_advanced_requirement_session(con, school_id, profile_id,
                    integer("requirement_id"), integer("session_no", 1), integer("day_id"),
                    integer("period_id"), integer("room_id") or None,
                    request.session.get("email", ""))
                message = "Advanced session placed successfully."
            elif value("requirement_id"):
                requirement_id = integer("requirement_id")
                row = con.execute("SELECT teaching_group_id FROM ds_timetable_scheduling_requirements WHERE id=? AND school_id=? AND profile_id=? AND is_active=1",
                    (requirement_id, school_id, profile_id)).fetchone()
                if not row:
                    raise TimetableSetupError("Active scheduling requirement not found.")
                con.execute("UPDATE ds_timetable_scheduling_requirements SET is_active=0 WHERE id=? AND school_id=? AND profile_id=?",
                    (requirement_id, school_id, profile_id))
                if row["teaching_group_id"] is not None:
                    con.execute("UPDATE ds_timetable_teaching_groups SET is_active=0 WHERE id=? AND school_id=? AND profile_id=?",
                        (int(row["teaching_group_id"]), school_id, profile_id))
                con.commit()
                message = "Scheduling requirement deactivated; saved session history is retained."
            elif value("name") and form.getlist("class_ids") and form.getlist("teacher_ids"):
                classes = list(dict.fromkeys(int(v) for v in form.getlist("class_ids")))
                teachers = list(dict.fromkeys(int(v) for v in form.getlist("teacher_ids")))
                subject_id = integer("subject_id")
                duration = integer("duration_periods", 1)
                mode = value("room_assignment_mode", "automatic").lower()
                room_id = integer("preferred_room_id") or None
                if len(classes) < 2 or not teachers or not 1 <= duration <= 4:
                    raise TimetableSetupError("Select at least two classes, one teacher and a duration of 1–4 periods.")
                if mode not in {"automatic", "preferred", "fixed"}:
                    raise TimetableSetupError("Choose a valid room allocation mode.")
                if mode in {"preferred", "fixed"} and room_id is None:
                    raise TimetableSetupError("Choose a preferred or fixed room.")
                group_id = create_teaching_group(con, school_id, profile_id, value("name"), classes,
                    group_type="combined_class", subject_id=subject_id,
                    notes="Combined class session with a shared teaching team.")
                req_id = create_scheduling_requirement(con, school_id, profile_id,
                    value("name") + " — combined session", class_ids=classes, teacher_ids=teachers,
                    schedule_layer="instructional", session_type="lesson", subject_id=subject_id,
                    teaching_group_id=group_id, weekly_occurrences=1, weekly_periods=duration,
                    counts_toward_curriculum=True, min_teacher_count=1, room_type=value("room_type", "classroom"),
                    room_assignment_mode=mode, preferred_room_id=room_id)
                save_scheduling_pattern(con, school_id, profile_id, req_id,
                    [{"duration_periods": duration, "session_label": "Combined lesson"}])
                message = "Combined class and co-teaching requirement created."
            else:
                raise TimetableSetupError("The submitted builder action could not be identified. Reopen the action and try again.")
            return redirect_builder(profile_id, message)
        except (TimetableSetupError, ValueError, TypeError) as exc:
            con.rollback()
            return redirect_builder(profile_id, str(exc), True)
        finally:
            con.close()

    @app.get("/app/timetable/builder", response_class=HTMLResponse)
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
        days = periods = breaks = rooms = allocations = requirements = lessons = calendar_events = advanced_requirements = advanced_sessions = []
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
            breaks = cur.execute(
                "SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=? ORDER BY start_time,break_no,id",
                (school_id,pid),
            ).fetchall()
            rooms = cur.execute(
                "SELECT * FROM ds_timetable_rooms WHERE school_id=? AND is_active=1 ORDER BY name",
                (school_id,),
            ).fetchall()
            class_records = cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream", (school_id,)).fetchall()
            teacher_records = cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
            subject_records = cur.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
            requirements = cur.execute(
                "SELECT * FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=? ORDER BY class_id,subject_id",
                (school_id,pid),
            ).fetchall()
            advanced_requirements = cur.execute(
                """SELECT r.id,r.name,r.weekly_occurrences,r.weekly_periods,r.schedule_layer,
                          r.room_type,r.room_assignment_mode,r.preferred_room_id
                   FROM ds_timetable_scheduling_requirements r
                   WHERE r.school_id=? AND r.profile_id=? AND r.is_active=1
                   ORDER BY r.schedule_layer,r.name""",
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
            advanced_sessions = cur.execute(
                """SELECT s.*,sub.name subject_name,d.day_name,p.label period_label,
                          STRING_AGG(DISTINCT (c.name || COALESCE(' ' || c.stream,''))::text, ', ') class_names,
                          STRING_AGG(DISTINCT t.name::text, ', ') teacher_names,rm.name room_name
                   FROM ds_timetable_sessions s
                   LEFT JOIN subjects sub ON sub.id=s.subject_id AND sub.school_id=s.school_id
                   LEFT JOIN ds_timetable_days d ON d.id=s.day_id AND d.profile_id=s.profile_id
                   LEFT JOIN ds_timetable_periods p ON p.id=s.period_id AND p.profile_id=s.profile_id
                   LEFT JOIN ds_timetable_rooms rm ON rm.id=s.room_id AND rm.school_id=s.school_id
                   LEFT JOIN ds_timetable_session_classes sc ON sc.session_id=s.id AND sc.school_id=s.school_id
                   LEFT JOIN classes c ON c.id=sc.class_id AND c.school_id=sc.school_id
                   LEFT JOIN ds_timetable_session_teachers st ON st.session_id=s.id AND st.school_id=s.school_id
                   LEFT JOIN teachers t ON t.id=st.teacher_id AND t.school_id=st.school_id
                   WHERE s.school_id=? AND s.profile_id=? AND s.status='scheduled'
                   GROUP BY s.id,sub.name,d.day_name,p.label,rm.name,d.day_order,p.period_no ORDER BY d.day_order,p.period_no,s.start_time""",
                (school_id,pid),
            ).fetchall()
            calendar_events = cur.execute(
                "SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=? ORDER BY exception_date",
                (school_id,pid),
            ).fetchall()
            teaching_groups = cur.execute(
                """SELECT id,name,group_type,subject_id,is_active FROM ds_timetable_teaching_groups
                   WHERE school_id=? AND profile_id=? ORDER BY name,id""", (school_id,pid)
            ).fetchall()
            room_rules = cur.execute(
                """SELECT r.id,r.name,r.room_type,r.room_assignment_mode,r.preferred_room_id,rm.name preferred_room_name
                   FROM ds_timetable_scheduling_requirements r
                   LEFT JOIN ds_timetable_rooms rm ON rm.id=r.preferred_room_id AND rm.school_id=r.school_id
                   WHERE r.school_id=? AND r.profile_id=? AND r.is_active=1 ORDER BY r.name""", (school_id,pid)
            ).fetchall()
        else:
            teaching_groups = []
            room_rules = []

        esc = lambda value: escape(str(value if value is not None else ""))
        pid = int(selected["id"]) if selected else 0
        read_only = bool(selected and str(selected["status"] or "draft").strip().lower() in ("published", "archived"))
        notice = f"<div class='tb-alert {'error' if error else 'success'}'>{esc(message)}</div>" if message else ""
        profile_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==pid else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])}</option>"
            for p in profiles
        )
        profile_selector = f"<form method='get' action='/app/timetable/builder' class='tb-profile-select'><label>Timetable profile</label><select name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>" if profiles else ""
        if not selected:
            body = f"""<style>.tb-empty{{max-width:800px;margin:30px auto;background:white;padding:30px;border-radius:16px;text-align:center}}</style><div class='tb-empty'><h2>No timetable profile yet</h2><p>Create an academic-year and term profile before building the weekly timetable.</p><a href='/app/timetable/setup' class='btn'>Open Timetable Setup</a></div>"""
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
        # Keep the original day/period grid, but give each class/stream its own row.
        # This prevents parallel classes from stacking inside the same period cell.
        class_rows_by_id = {}
        for allocation in allocations:
            class_rows_by_id[int(allocation["class_id"])] = {
                "class_id": int(allocation["class_id"]),
                "class_name": allocation["class_name"],
                "stream": allocation["stream"] or "",
            }
        for lesson in lessons:
            class_rows_by_id.setdefault(int(lesson["class_id"]), {
                "class_id": int(lesson["class_id"]),
                "class_name": lesson["class_name"],
                "stream": lesson["stream"] or "",
            })
        class_rows = sorted(class_rows_by_id.values(), key=lambda item: (
            str(item["class_name"]).casefold(), str(item["stream"]).casefold()
        ))
        lesson_by_start = {}
        for lesson in lessons:
            lesson_by_start.setdefault(
                (int(lesson["day_id"]), int(lesson["class_id"]), int(lesson["period_id"])), []
            ).append(lesson)
        occupied = {}
        for lesson in lessons:
            start = period_index.get(int(lesson["period_id"]))
            if start is None:
                continue
            for offset in range(1, int(lesson["duration_periods"] or 1)):
                if start + offset < len(periods):
                    occupied.setdefault(
                        (int(lesson["day_id"]), int(lesson["class_id"]), int(periods[start+offset]["id"])), []
                    ).append(lesson)
        timeline = sorted(
            [(str(p["start_time"]), "period", p) for p in periods] +
            [(str(br["start_time"]), "break", br) for br in breaks],
            key=lambda item: (item[0], 0 if item[1] == "period" else 1),
        )
        headers = ["<th class='tb-day-heading'>Day</th>", "<th class='tb-class-heading'>Class / Stream</th>"]
        for _, item_type, item in timeline:
            if item_type == "break":
                headers.append(f"<th class='tb-break-heading'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></th>")
            else:
                headers.append(f"<th class='tb-period-heading'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></th>")
        rows = []
        for day in days:
            day_class_rows = class_rows or [{"class_id": 0, "class_name": "—", "stream": ""}]
            for class_index, class_row in enumerate(day_class_rows):
                cells = []
                if class_index == 0:
                    cells.append(
                        f"<th class='tb-day-heading' rowspan='{len(day_class_rows)}'>{esc(day['day_name'])}</th>"
                    )
                class_name_html = f"<b class='tb-class-name'>{esc(class_row['class_name'])}</b>"
                stream_html = f"<span class='tb-stream-name'>{esc(class_row['stream'])}</span>" if class_row["stream"] else ""
                cells.append(f"<th class='tb-class-heading'>{class_name_html}{stream_html}</th>")
                for _, item_type, item in timeline:
                    if item_type == "break":
                        cells.append(f"<td class='tb-break-cell'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></td>")
                        continue
                    period = item
                    key = (int(day["id"]), int(class_row["class_id"]), int(period["id"]))
                    slot_lessons = lesson_by_start.get(key, [])
                    continued_lessons = occupied.get(key, [])
                    if slot_lessons:
                        cards = []
                        for lesson in slot_lessons:
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
                            manage_html = ""
                            if not read_only:
                                manage_html = f"""<details class='tb-actions'><summary>Manage</summary><form method='post' action='/app/timetable/builder/move'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='lesson_id' value='{int(lesson['id'])}'><label>Move to day<select name='day_id'>{move_day_opts}</select></label><label>Start period<select name='period_id'>{move_period_opts}</select></label><label>Room<select name='room_id'>{move_room_opts}</select></label><button class='tb-small'>Move lesson</button></form><form method='post' action='/app/timetable/builder/delete' onsubmit="return confirm('Remove this lesson from the timetable?')"><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='lesson_id' value='{int(lesson['id'])}'><button class='tb-delete'>Delete lesson</button></form></details>"""
                            cards.append(f"""<div class='tb-lesson' draggable='{'false' if read_only else 'true'}' data-lesson-id='{int(lesson['id'])}' ondragstart='dragTimetableLesson(event)'><div class='tb-lesson-top'><b>{esc(lesson['subject_name'])}</b><span>{duration}P</span></div><div class='tb-meta'>{esc(lesson['teacher_name'])}</div><div class='tb-meta'>⌂ {room_label}</div>{manage_html}</div>""")
                        cells.append(f"<td class='tb-cell tb-cell-multi' data-day-id='{int(day['id'])}' data-period-id='{int(period['id'])}' ondragover='event.preventDefault()' ondrop='dropTimetableLesson(event,this)'>{''.join(cards)}</td>")
                    elif continued_lessons:
                        continued_html = "".join(
                            f"<div class='tb-continued-item'>↳ {esc(item['subject_name'])} continues</div>"
                            for item in continued_lessons
                        )
                        cells.append(f"<td class='tb-cell tb-continued' data-day-id='{int(day['id'])}' data-period-id='{int(period['id'])}' ondragover='event.preventDefault()' ondrop='dropTimetableLesson(event,this)'>{continued_html}</td>")
                    else:
                        cells.append(f"<td class='tb-cell tb-free' data-day-id='{int(day['id'])}' data-period-id='{int(period['id'])}' ondragover='event.preventDefault()' ondrop='dropTimetableLesson(event,this)'><span>Free period</span></td>")
                row_class = " class='tb-day-end'" if class_index == len(day_class_rows) - 1 else ""
                rows.append(f"<tr{row_class}>{''.join(cells)}</tr>")
        grid = f"<div class='tb-grid-scroll'><table class='tb-grid'><thead><tr>{''.join(headers)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>" if days and periods else "<div class='tb-empty'>Configure at least one instructional day and one teaching period in Timetable Setup.</div>"
        add_form = (
            f"""<section class='tb-panel'><div><span class='tb-kicker'>MANUAL SCHEDULING</span><h3>Add a lesson</h3><p>Choose an existing class, subject and allocated teacher. Lesson duration follows the weekly requirement.</p></div><form method='post' action='/app/timetable/builder/add' class='tb-add-form'><input type='hidden' name='profile_id' value='{pid}'><label class='wide'>Class · subject · teacher<select name='allocation' required><option value=''>Select configured requirement</option>{allocation_options}</select></label><label>Day<select name='day_id' required><option value=''>Select day</option>{day_options}</select></label><label>Start period<select name='period_id' required><option value=''>Select period</option>{period_options}</select></label><label>Room<select name='room_id'>{room_options}</select></label><button class='tb-btn'>＋ Add lesson</button></form></section>"""
            if not read_only and allocations and days and periods else
            (f"<section class='tb-panel'><h3>Published timetable is read-only</h3><p>Create a new draft revision before making changes.</p><a class='tb-btn' href='/app/timetable/publishing?profile_id={pid}'>Create Revision</a></section>" if read_only else
             "<section class='tb-panel'><h3>Complete setup first</h3><p>Configure school days, teaching periods and weekly class-subject requirements before placing lessons.</p><a class='tb-btn' href='/app/timetable/setup'>Open Timetable Setup</a></section>")
        )
        advanced_options = "".join(
            f"<option value='{int(r['id'])}'>{esc(r['name'])} · {esc(r['schedule_layer'])} · {int(r['weekly_occurrences'])} sessions / {int(r['weekly_periods'])} periods weekly</option>"
            for r in advanced_requirements
        )
        room_policy_form = (
            f"""<section class='tb-panel'><h3>Room allocation rules</h3><p>Automatic chooses any suitable free room. Preferred tries your chosen room first, then another suitable room. Fixed requires the selected room.</p>
            <form method='post' action='/app/timetable/builder/room-policy' class='tb-add-form'>
            <input type='hidden' name='profile_id' value='{pid}'>
            <label class='wide'>Scheduling requirement<select id='tb-room-requirement' name='requirement_id' required><option value=''>Select requirement</option>{advanced_options}</select></label>
            <label>Allocation mode<select id='tb-room-mode' name='room_assignment_mode'><option value='automatic'>Automatic</option><option value='preferred'>Preferred (fallback allowed)</option><option value='fixed'>Fixed (no fallback)</option></select></label>
            <label>Preferred / fixed room<select id='tb-room-choice' name='preferred_room_id'>{room_options}</select></label>
            <button class='tb-btn'>Save room rule</button></form></section>"""
            if not read_only and advanced_requirements else ""
        )
        class_group_options = "".join(f"<option value='{int(c['id'])}'>{esc(c['name'])} {esc(c['stream'] or '')}</option>" for c in class_records)
        teacher_group_options = "".join(f"<option value='{int(t['id'])}'>{esc(t['name'])}</option>" for t in teacher_records)
        subject_group_options = "".join(f"<option value='{int(x['id'])}'>{esc(x['name'])}</option>" for x in subject_records)
        combined_group_form = (
            f"""<section class='tb-panel'><h3>Combined classes and co-teaching</h3><p>Merge two or more classes into one shared session, assign one or more teachers and reserve a single room for the combined group.</p>
            <form method='post' action='/app/timetable/builder/create-combined' class='tb-add-form'>
            <input type='hidden' name='profile_id' value='{pid}'>
            <label class='wide'>Combined lesson name<input name='name' required maxlength='120' placeholder='e.g. Grade 7 combined Mathematics'></label>
            <label>Classes / streams<select name='class_ids' multiple required size='5'>{class_group_options}</select></label>
            <label>Co-teaching team<select name='teacher_ids' multiple required size='5'>{teacher_group_options}</select></label>
            <label>Subject<select name='subject_id' required><option value=''>Choose subject</option>{subject_group_options}</select></label>
            <label>Session duration<select name='duration_periods'><option value='1'>1 period</option><option value='2'>2 consecutive periods</option><option value='3'>3 consecutive periods</option><option value='4'>4 consecutive periods</option></select></label>
            <label>Room type<select name='room_type'><option value='classroom'>Classroom</option><option value='laboratory'>Laboratory</option><option value='library'>Library</option><option value='hall'>Hall</option><option value='workshop'>Workshop</option><option value='sports'>Sports facility</option><option value='other'>Other</option></select></label>
            <label>Room allocation<select name='room_assignment_mode'><option value='automatic'>Automatic</option><option value='preferred'>Preferred</option><option value='fixed'>Fixed</option></select></label>
            <label>Preferred / fixed room<select name='preferred_room_id'>{room_options}</select></label>
            <button class='tb-btn'>＋ Create combined lesson</button></form></section>"""
            if not read_only and class_records and teacher_records and subject_records else ""
        )
        advanced_form = (
            f"""<section class='tb-panel'><div><span class='tb-kicker'>ADVANCED MANUAL SCHEDULING</span><h3>Place a combined or team-taught session</h3><p>Uses the normalized requirement, configured session pattern and the same constraint/conflict engine as automatic generation.</p></div>
            <form method='post' action='/app/timetable/builder/add-advanced' class='tb-add-form'>
            <input type='hidden' name='profile_id' value='{pid}'>
            <label class='wide'>Scheduling requirement<select id='tb-advanced-requirement' name='requirement_id' required><option value=''>Select advanced requirement</option>{advanced_options}</select></label>
            <label>Weekly session number<input type='number' name='session_no' min='1' value='1' required></label>
            <label>Day<select name='day_id' required><option value=''>Select day</option>{day_options}</select></label>
            <label>Start period<select name='period_id' required><option value=''>Select period</option>{period_options}</select></label>
            <label>Room<select name='room_id'>{room_options}</select></label><button class='tb-btn'>＋ Place advanced session</button></form></section>"""
            if not read_only and advanced_requirements and days and periods else ""
        )
        dated_form = (
            f"""<section class='tb-panel tb-dated-panel'><div><span class='tb-kicker'>CALENDAR-DATED MANUAL SCHEDULING</span><h3>Place a session on a specific date</h3><p>Choose an instructional lesson, remedial programme or school activity. Available slots are filtered to the selected session layer and that date's assigned schedule template.</p></div>
            <form method='post' action='/app/timetable/builder/add-dated' class='tb-add-form' id='tb-dated-session-form'>
            <input type='hidden' name='profile_id' value='{pid}'>
            <label class='wide'>Scheduling requirement<select name='requirement_id' required><option value=''>Select scheduling requirement</option>{advanced_options}</select></label>
            <label>Session number<input type='number' name='session_no' min='1' value='1' required></label>
            <label>Calendar date<input type='date' name='session_date' id='tb-session-date' min='{esc(selected['academic_start_date'] or '')}' max='{esc(selected['academic_end_date'] or '')}' required></label>
            <label class='wide'>Available date slots<select name='slot_no' id='tb-date-slot' required disabled><option value=''>Choose a date to load available slots</option></select></label>
            <label>Room<select name='room_id'>{room_options}</select></label><button class='tb-btn' id='tb-place-dated' disabled>＋ Place dated lesson</button>
            <p class='tb-date-slot-status wide' id='tb-date-slot-status' aria-live='polite'>Select a date to see its configured schedule.</p></form></section>
            <script>
            (function(){{
              const dateInput=document.getElementById('tb-session-date');
              const slotSelect=document.getElementById('tb-date-slot');
              const submitButton=document.getElementById('tb-place-dated');
              const status=document.getElementById('tb-date-slot-status');
              const requirementSelect=document.querySelector('#tb-dated-session-form select[name="requirement_id"]');
              const profileId='{pid}';
              if(!dateInput||!slotSelect||!requirementSelect)return;
              async function loadDateSlots(){{
                slotSelect.disabled=true;submitButton.disabled=true;
                slotSelect.innerHTML='<option value="">Loading available slots…</option>';
                if(!dateInput.value||!requirementSelect.value){{slotSelect.innerHTML='<option value="">Choose a requirement and date first</option>';status.textContent='Choose a scheduling requirement and date to load suitable slots.';return;}}
                status.textContent='Loading the selected date schedule…';
                try{{
                  const response=await fetch('/app/timetable/builder/date-slots?profile_id='+encodeURIComponent(profileId)+'&requirement_id='+encodeURIComponent(requirementSelect.value)+'&session_date='+encodeURIComponent(dateInput.value),{{credentials:'same-origin',headers:{{'Accept':'application/json'}}}});
                  const data=await response.json();
                  if(!response.ok||!data.ok)throw new Error(data.error||'Could not load this date schedule.');
                  slotSelect.innerHTML='<option value="">Select a configured slot</option>';
                  (data.slots||[]).forEach(function(slot){{
                    const option=document.createElement('option');option.value=slot.slot_no;
                    option.textContent=slot.label+' · '+slot.start_time+'–'+slot.end_time+' · '+slot.slot_type;
                    slotSelect.appendChild(option);
                  }});
                  slotSelect.disabled=!(data.slots||[]).length;
                  status.textContent=(data.day_name||'Selected date')+' · '+((data.slots||[]).length)+' configured slots'+(data.rotations&&data.rotations.length?' · '+data.rotations.join(', '):'');
                  if(!(data.slots||[]).length)slotSelect.innerHTML='<option value="">No configured slots for this date</option>';
                }}catch(error){{
                  slotSelect.innerHTML='<option value="">Schedule unavailable</option>';
                  status.textContent=error.message||'Could not load this date schedule.';
                }}
              }}
              dateInput.addEventListener('change',loadDateSlots);
              requirementSelect.addEventListener('change',loadDateSlots);
              slotSelect.addEventListener('change',function(){{submitButton.disabled=!slotSelect.value;}});
            }})();
            </script>"""
            if not read_only and advanced_requirements else ""
        )
        basic_lesson_rows = "".join(
            f"""<tr><td>{esc(x['class_name'])} {esc(x['stream'] or '')}</td><td>{esc(x['subject_name'])}</td><td>{esc(x['teacher_name'])}</td><td>{esc(x['day_name'])}</td><td>{esc(x['period_label'])}</td><td>{esc(x['room_name'] or 'Not assigned')}</td><td><details class='tb-row-actions'><summary>Actions</summary><form method='post' action='/app/timetable/builder/move'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='lesson_id' value='{int(x['id'])}'><label>Day<select name='day_id'>{"".join(f"<option value='{int(d['id'])}' {'selected' if int(d['id'])==int(x['day_id']) else ''}>{esc(d['day_name'])}</option>" for d in days)}</select></label><label>Start period<select name='period_id'>{"".join(f"<option value='{int(p['id'])}' {'selected' if int(p['id'])==int(x['period_id']) else ''}>{esc(p['label'])} · {esc(p['start_time'])}</option>" for p in periods)}</select></label><label>Room<select name='room_id'><option value=''>Keep current room</option>{"".join(f"<option value='{int(r['id'])}' {'selected' if x['room_id'] is not None and int(r['id'])==int(x['room_id']) else ''}>{esc(r['name'])}</option>" for r in rooms)}</select></label><button type='submit' class='tb-small'>Save move</button></form><form method='post' action='/app/timetable/builder/delete' onsubmit="return confirm('Delete this lesson?')"><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='lesson_id' value='{int(x['id'])}'><button type='submit' class='tb-delete'>Delete</button></form></details></td></tr>"""
            for x in lessons
        ) or "<tr><td colspan='7' class='tb-empty-cell'>No standard lessons saved yet.</td></tr>"
        basic_lesson_table = f"""<section class='tb-panel tb-data-section'><div class='tb-section-head'><div><span class='tb-kicker'>SAVED LESSONS</span><h3>Class timetable entries</h3><p>Every saved lesson appears here. Move or delete individual entries using Actions.</p></div><span class='tb-count'>{len(lessons)} records</span></div><div class='tb-table-scroll'><table class='tb-data-table'><thead><tr><th>Class / stream</th><th>Subject</th><th>Teacher</th><th>Day</th><th>Period</th><th>Room</th><th>Actions</th></tr></thead><tbody>{basic_lesson_rows}</tbody></table></div></section>"""
        group_rows = []
        for group in teaching_groups:
            req = cur.execute("SELECT id,weekly_occurrences FROM ds_timetable_scheduling_requirements WHERE school_id=? AND profile_id=? AND teaching_group_id=? AND is_active=1 LIMIT 1", (school_id,pid,int(group["id"]))).fetchone()
            group_classes = cur.execute("""SELECT c.name,c.stream FROM ds_timetable_scheduling_requirement_classes rc JOIN classes c ON c.id=rc.class_id AND c.school_id=rc.school_id WHERE rc.school_id=? AND rc.profile_id=? AND rc.requirement_id=? ORDER BY c.name,c.stream""", (school_id,pid,int(req["id"]))).fetchall() if req else []
            subject = next((z["name"] for z in subject_records if int(z["id"])==int(group["subject_id"] or 0)), "—")
            place_action = ""
            if req and not read_only and days and periods:
                place_action = f"""<details class='tb-row-actions'><summary>Place session</summary><form method='post' action='/app/timetable/builder/add-advanced'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='requirement_id' value='{int(req["id"])}'><label>Session number<input type='number' name='session_no' min='1' max='{max(1,int(req["weekly_occurrences"] or 1))}' value='1' required></label><label>Day<select name='day_id' required><option value=''>Select day</option>{day_options}</select></label><label>Start period<select name='period_id' required><option value=''>Select period</option>{period_options}</select></label><label>Room<select name='room_id'>{room_options}</select></label><button type='submit' class='tb-small'>Place session now</button></form></details>"""
            deactivate_action = f"""<form method='post' action='/app/timetable/builder/deactivate-group' onsubmit="return confirm('Deactivate this combined group and its requirement?')"><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='group_id' value='{int(group["id"])}'><button type='submit' class='tb-delete' {'disabled' if read_only or not int(group['is_active'] or 0) else ''}>Deactivate</button></form>"""
            group_rows.append(f"""<tr><td>{esc(group['name'])}</td><td>{esc(group['group_type'])}</td><td>{esc(subject)}</td><td>{esc(', '.join(str(z['name']) + (' '+str(z['stream']) if z['stream'] else '') for z in group_classes))}</td><td>{'Active' if int(group['is_active'] or 0) else 'Inactive'}</td><td><div class='tb-action-stack'>{place_action}{deactivate_action}</div></td></tr>""")
        group_table = f"""<section class='tb-panel tb-data-section'><div class='tb-section-head'><div><span class='tb-kicker'>SAVED GROUPS</span><h3>Combined classes & co-teaching groups</h3><p>Place a session directly from its row or deactivate the group while retaining history.</p></div><span class='tb-count'>{len(teaching_groups)} records</span></div><div class='tb-table-scroll'><table class='tb-data-table'><thead><tr><th>Group</th><th>Type</th><th>Subject</th><th>Classes / streams</th><th>Status</th><th>Actions</th></tr></thead><tbody>{''.join(group_rows) or "<tr><td colspan='6' class='tb-empty-cell'>No combined groups saved yet.</td></tr>"}</tbody></table></div></section>"""
        requirement_rows = []
        for x in advanced_requirements:
            place_action = ""
            if not read_only and days and periods:
                place_action = f"""<details class='tb-row-actions'><summary>Place session</summary><form method='post' action='/app/timetable/builder/add-advanced'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='requirement_id' value='{int(x["id"])}'><label>Session number<input type='number' name='session_no' min='1' max='{max(1,int(x["weekly_occurrences"] or 1))}' value='1' required></label><label>Day<select name='day_id' required><option value=''>Select day</option>{day_options}</select></label><label>Start period<select name='period_id' required><option value=''>Select period</option>{period_options}</select></label><label>Room<select name='room_id'>{room_options}</select></label><button type='submit' class='tb-small'>Place session now</button></form></details>"""
            deactivate_action = f"""<form method='post' action='/app/timetable/builder/deactivate-requirement' onsubmit="return confirm('Deactivate this scheduling requirement?')"><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='requirement_id' value='{int(x["id"])}'><button type='submit' class='tb-delete' {'disabled' if read_only else ''}>Deactivate</button></form>"""
            requirement_rows.append(f"""<tr><td>{esc(x['name'])}</td><td>{esc(x['schedule_layer'])}</td><td>{int(x['weekly_occurrences'])}</td><td>{int(x['weekly_periods'])}</td><td>{esc(x['room_type'] or 'Any')}</td><td><div class='tb-action-stack'>{place_action}{deactivate_action}</div></td></tr>""")
        requirement_table = f"""<section class='tb-panel tb-data-section'><div class='tb-section-head'><div><span class='tb-kicker'>SAVED REQUIREMENTS</span><h3>Advanced scheduling requirements</h3><p>Place each session directly from its row; existing conflict and resource checks remain enforced.</p></div><span class='tb-count'>{len(advanced_requirements)} records</span></div><div class='tb-table-scroll'><table class='tb-data-table'><thead><tr><th>Requirement</th><th>Layer</th><th>Sessions / week</th><th>Periods / week</th><th>Room type</th><th>Actions</th></tr></thead><tbody>{''.join(requirement_rows) or "<tr><td colspan='6' class='tb-empty-cell'>No active scheduling requirements saved yet.</td></tr>"}</tbody></table></div></section>"""
        room_rule_rows = []
        for x in room_rules:
            matching_rooms = [r for r in rooms if not x["room_type"] or str(r["room_type"]) == str(x["room_type"])]
            rule_room_options = "<option value=''>No room selected</option>" + "".join(
                f"<option value='{int(r['id'])}' {'selected' if x['preferred_room_id'] is not None and int(r['id'])==int(x['preferred_room_id']) else ''}>{esc(r['name'])} ({esc(r['room_type'])})</option>" for r in matching_rooms
            )
            mode = str(x["room_assignment_mode"] or "automatic")
            rule_mode_options = "".join(
                f"<option value='{value}' {'selected' if mode==value else ''}>{label}</option>"
                for value,label in (("automatic","Automatic"),("preferred","Preferred (fallback allowed)"),("fixed","Fixed (no fallback)"))
            )
            edit_action = f"""<details class='tb-row-actions'><summary>Edit rule</summary><form method='post' action='/app/timetable/builder/room-policy'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='requirement_id' value='{int(x["id"])}'><label>Allocation mode<select name='room_assignment_mode'>{rule_mode_options}</select></label><label>Preferred / fixed room<select name='preferred_room_id'>{rule_room_options}</select></label><button type='submit' class='tb-small' {'disabled' if read_only else ''}>Save this rule</button></form></details>"""
            room_rule_rows.append(f"""<tr><td>{esc(x['name'])}</td><td>{esc(x['room_type'] or 'Any suitable room')}</td><td>{esc(mode)}</td><td>{esc(x['preferred_room_name'] or '—')}</td><td>{edit_action}</td></tr>""")
        room_rule_table = f"""<section class='tb-panel tb-data-section'><div class='tb-section-head'><div><span class='tb-kicker'>SAVED ROOM RULES</span><h3>Room allocation rules</h3><p>Edit and save each rule directly in its row.</p></div><span class='tb-count'>{len(room_rules)} records</span></div><div class='tb-table-scroll'><table class='tb-data-table'><thead><tr><th>Requirement</th><th>Room type</th><th>Mode</th><th>Selected room</th><th>Actions</th></tr></thead><tbody>{''.join(room_rule_rows) or "<tr><td colspan='5' class='tb-empty-cell'>No room rules saved yet.</td></tr>"}</tbody></table></div></section>"""
        con.close()
        advanced_session_rows = "".join(
            f"""<tr><td>{esc(x['day_name'] or x['session_date'] or '—')}</td><td>{esc(x['period_label'] or (str(x['start_time'])+'–'+str(x['end_time'])))}</td><td>{esc(x['subject_name'] or x['session_type'])}</td><td>{esc(x['class_names'] or 'Learner group')}</td><td>{esc(x['teacher_names'] or '—')}</td><td>{esc(x['room_name'] or 'No room')}</td><td><form method='post' action='/app/timetable/builder/cancel-session' onsubmit="return confirm('Remove this session from the timetable?')"><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='session_id' value='{int(x['id'])}'><button class='tb-delete' {'disabled' if read_only else ''}>Remove</button></form></td></tr>"""
            for x in advanced_sessions
        ) or "<tr><td colspan='7' class='tb-empty-cell'>No advanced sessions placed yet.</td></tr>"
        advanced_session_table = f"""<section class='tb-panel tb-data-section'><div class='tb-section-head'><div><span class='tb-kicker'>SAVED ADVANCED SESSIONS</span><h3>Combined classes and team-taught lessons</h3><p>Saved normalized sessions and dated placements.</p></div><span class='tb-count'>{len(advanced_sessions)} records</span></div><div class='tb-table-scroll'><table class='tb-data-table'><thead><tr><th>Day / date</th><th>Time</th><th>Subject / activity</th><th>Classes</th><th>Teaching team</th><th>Room</th><th>Actions</th></tr></thead><tbody>{advanced_session_rows}</tbody></table></div></section>"""
        builder_tools = [
            ("add","＋ Add lesson", bool(not read_only and allocations and days and periods)),
            ("advanced","Advanced scheduling", bool(not read_only and advanced_requirements)),
            ("entries","Saved lessons", bool(lessons)),
            ("groups","Groups & sessions", bool(teaching_groups or advanced_sessions)),
            ("rooms","Room rules", bool(not read_only and advanced_requirements or room_rules)),
            ("dated","Dated sessions", bool(not read_only and advanced_requirements)),
        ]
        builder_tool_buttons = "".join(
            f"<button type='button' class='tb-tool-button' data-modal-open='tb-modal-{key}'>{label}</button>"
            for key,label,visible in builder_tools if visible
        )
        builder_modals = (
            f"<div class='tb-modal' id='tb-modal-add' aria-hidden='true'><div class='tb-modal-dialog' role='dialog' aria-modal='true' aria-labelledby='tb-modal-add-title'><div class='tb-modal-head'><div><span class='tb-kicker'>MANUAL SCHEDULING</span><h3 id='tb-modal-add-title'>Add a lesson</h3><p>Place a configured class-subject allocation.</p></div><button type='button' class='tb-modal-close' data-modal-close aria-label='Close'>×</button></div>{add_form}</div></div>"
            f"<div class='tb-modal' id='tb-modal-advanced' aria-hidden='true'><div class='tb-modal-dialog' role='dialog' aria-modal='true' aria-labelledby='tb-modal-advanced-title'><div class='tb-modal-head'><div><span class='tb-kicker'>ADVANCED SCHEDULING</span><h3 id='tb-modal-advanced-title'>Advanced scheduling</h3><p>Combined, team-taught and normalized sessions.</p></div><button type='button' class='tb-modal-close' data-modal-close aria-label='Close'>×</button></div>{combined_group_form}{advanced_form}{requirement_table}</div></div>"
            f"<div class='tb-modal' id='tb-modal-entries' aria-hidden='true'><div class='tb-modal-dialog' role='dialog' aria-modal='true' aria-labelledby='tb-modal-entries-title'><div class='tb-modal-head'><div><span class='tb-kicker'>TIMETABLE RECORDS</span><h3 id='tb-modal-entries-title'>Saved lessons</h3><p>Review, move or remove scheduled entries.</p></div><button type='button' class='tb-modal-close' data-modal-close aria-label='Close'>×</button></div>{basic_lesson_table}</div></div>"
            f"<div class='tb-modal' id='tb-modal-groups' aria-hidden='true'><div class='tb-modal-dialog' role='dialog' aria-modal='true' aria-labelledby='tb-modal-groups-title'><div class='tb-modal-head'><div><span class='tb-kicker'>GROUPS & SESSIONS</span><h3 id='tb-modal-groups-title'>Groups and sessions</h3><p>Manage combined groups and placed sessions.</p></div><button type='button' class='tb-modal-close' data-modal-close aria-label='Close'>×</button></div>{group_table}{advanced_session_table}</div></div>"
            f"<div class='tb-modal' id='tb-modal-rooms' aria-hidden='true'><div class='tb-modal-dialog' role='dialog' aria-modal='true' aria-labelledby='tb-modal-rooms-title'><div class='tb-modal-head'><div><span class='tb-kicker'>ROOM MANAGEMENT</span><h3 id='tb-modal-rooms-title'>Room rules</h3><p>Set room assignment preferences.</p></div><button type='button' class='tb-modal-close' data-modal-close aria-label='Close'>×</button></div>{room_policy_form}{room_rule_table}</div></div>"
            f"<div class='tb-modal' id='tb-modal-dated' aria-hidden='true'><div class='tb-modal-dialog' role='dialog' aria-modal='true' aria-labelledby='tb-modal-dated-title'><div class='tb-modal-head'><div><span class='tb-kicker'>CALENDAR SCHEDULING</span><h3 id='tb-modal-dated-title'>Dated sessions</h3><p>Place a lesson or activity on a specific date.</p></div><button type='button' class='tb-modal-close' data-modal-close aria-label='Close'>×</button></div>{dated_form}</div></div>"
        )
        body = f"""
        <style>
        .tb-wrap{{max-width:1700px;margin:auto;padding:12px;color:#234638;background:linear-gradient(145deg,#edf6ef 0%,#e3f0e5 45%,#f8fbf8 100%);border-radius:25px}}
        .tb-wrap *{{box-sizing:border-box}}.tb-hero{{position:relative;overflow:hidden;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:8px;padding:12px 16px;border:1px solid #d1e3d4;border-radius:22px;background:linear-gradient(118deg,#dceede 0%,#c9e2ce 53%,#edf5eb 100%);box-shadow:0 12px 28px rgba(39,91,57,.08)}}
        .tb-hero:after{{content:'';position:absolute;width:250px;height:250px;right:10%;top:-175px;border:1px solid rgba(55,112,73,.16);border-radius:50%;box-shadow:0 0 0 28px rgba(55,112,73,.04),0 0 0 58px rgba(55,112,73,.025)}}
        .tb-hero>div{{position:relative;z-index:1}}.tb-hero h2{{font-size:clamp(19px,2vw,24px);margin:2px 0;color:#1e4934;letter-spacing:-.6px}}.tb-hero p{{display:none}}
        .tb-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}
        .tb-btn{{display:inline-flex;align-items:center;justify-content:center;padding:11px 15px;border:0;border-radius:10px;background:linear-gradient(135deg,#347c50,#246441);color:white!important;text-decoration:none!important;font-size:12px;font-weight:800;cursor:pointer;min-height:40px;box-shadow:0 5px 12px rgba(35,102,62,.12);transition:transform .16s,box-shadow .16s}}
        .tb-btn:hover{{transform:translateY(-1px);box-shadow:0 8px 16px rgba(35,102,62,.17)}}.tb-btn.secondary{{background:#edf6ee;color:#2a6a43!important;border:1px solid #cfe2d2;box-shadow:none}}
        .tb-toolbar{{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin:0 0 8px}}.tb-profile-select{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0}}.tb-profile-select label{{font-size:11px;font-weight:850;color:#42634e}}.tb-profile-select select{{min-width:min(320px,72vw);max-width:100%;padding:10px 12px;border:1px solid #cfe0d1;border-radius:10px;background:#fff;color:#254a35;font-size:12px}}.tb-profile-context{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;color:#496653;font-size:11px}}.tb-profile-context strong{{color:#214a34;font-size:12px}}.tb-summary{{display:none}}.tb-summary>div{{display:flex;align-items:center;gap:10px;padding:12px 14px;background:#fff;border:1px solid #dce9de;border-radius:13px}}.tb-summary strong{{font-size:21px;line-height:1;color:#246441;font-weight:900}}.tb-summary span{{font-size:10px;font-weight:750;color:#688071}}
        .tb-panel{{background:rgba(255,255,255,.95);border:1px solid #dce9de;border-radius:17px;padding:18px;margin-bottom:16px;box-shadow:0 6px 20px rgba(36,83,52,.05)}}.tb-panel h3{{margin:4px 0;color:#234c37;font-size:17px}}.tb-panel p{{margin:4px 0 12px;color:#687f70;font-size:12px;line-height:1.55}}
        .tb-add-form{{display:grid;grid-template-columns:2fr 1fr 1fr 1fr auto;gap:10px;align-items:end}}.tb-add-form label,.tb-actions label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:#3b5946}}.tb-add-form label.wide{{grid-column:auto}}
        .tb-add-form select,.tb-actions select{{width:100%;min-width:0;padding:11px;border:1px solid #d5e4d7;border-radius:10px;background:#fbfdfb;font-size:12px;color:#234638}}.tb-add-form select:focus,.tb-actions select:focus{{outline:none;border-color:#78ad85;box-shadow:0 0 0 3px rgba(91,153,107,.12)}}
        .tb-grid-scroll{{overflow:auto;border:1px solid #dce8de;border-radius:15px;background:white;box-shadow:0 6px 20px rgba(36,83,52,.045)}}.tb-grid{{width:100%;border-collapse:separate;border-spacing:0;min-width:995px}}
        .tb-grid thead th{{background:linear-gradient(110deg,#347b50,#286743);color:white;padding:8px 7px;text-align:center;font-size:12px;position:sticky;top:0;min-width:135px;border-bottom:5px solid #b7d1bc!important}}.tb-grid tbody tr:first-child>th,.tb-grid tbody tr:first-child>td{{border-top:0}}
        .tb-grid .tb-day-heading{{min-width:115px;background:#edf5ee;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:0;z-index:2}}.tb-grid .tb-class-heading{{width:76px;min-width:76px;max-width:76px;box-sizing:border-box;padding:6px 4px;background:#f5f9f5;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:115px;z-index:1;font-size:9px;line-height:1.15;overflow-wrap:anywhere}}.tb-grid tbody .tb-class-heading .tb-class-name{{display:block;font-size:9px;font-weight:800;line-height:1.15}}.tb-grid tbody .tb-class-heading .tb-stream-name{{display:block;margin-top:2px;color:#64816a;font-size:8px;font-weight:700;line-height:1.1}}.tb-period-heading b,.tb-period-heading span,.tb-break-heading b,.tb-break-heading span{{display:block}}.tb-grid tbody .tb-day-heading{{display:table-cell;vertical-align:middle;text-align:center;height:100%;white-space:nowrap}}.tb-grid tbody tr>th,.tb-grid tbody tr>td{{border-bottom:2px solid #c7d9ca!important}}.tb-grid tbody tr.tb-day-end>th,.tb-grid tbody tr.tb-day-end>td{{border-bottom:5px solid #6f9b78!important}}.tb-grid tbody .tb-day-heading{{box-shadow:inset 0 -3px 0 #6f9b78}}.tb-period-heading span,.tb-break-heading span{{font-size:10px;color:#e4efe5;font-weight:600;margin-top:4px}}.tb-break-heading,.tb-break-cell{{background:#f1ead8!important;color:#75551d;text-align:center;min-width:115px;padding:10px 8px}}.tb-break-heading span{{color:#75551d}}.tb-break-cell span{{display:block;font-size:10px;margin-top:4px}}
        .tb-cell{{height:82px;min-width:125px;vertical-align:top;padding:4px;border-right:1px solid #edf2ed;border-bottom:1px solid #edf2ed;background:#fff}}.tb-cell-multi{{height:auto;min-height:82px;vertical-align:top;display:table-cell}}.tb-cell-multi .tb-lesson{{margin-bottom:4px}}.tb-cell-multi .tb-lesson:last-child{{margin-bottom:0}}.tb-continued-item{{padding:3px 2px;border-bottom:1px dashed #dce9de;font-size:9px;line-height:1.3}}.tb-continued-item:last-child{{border-bottom:0}}.tb-free{{background:#fbfdfb;text-align:center;vertical-align:middle;color:#a2b3a5;font-size:10px}}.tb-free:hover{{background:#eff8f0}}.tb-continued{{background:#f6faf6;color:#7b9480;text-align:center;vertical-align:middle;font-size:10px}}
        .tb-lesson{{background:linear-gradient(145deg,#edf7ee,#e3f1e5);border:1px solid #d6e8d9;border-left:3px solid #43845a;border-radius:8px;padding:5px;min-height:66px;color:#234638;cursor:grab;box-shadow:0 2px 7px rgba(35,83,51,.07);transition:box-shadow .16s,transform .16s}}.tb-lesson:hover{{box-shadow:0 6px 14px rgba(35,83,51,.12);transform:translateY(-1px)}}.tb-lesson:active{{cursor:grabbing}}
        .tb-lesson-top{{display:flex;justify-content:space-between;gap:4px;font-size:10px}}.tb-lesson-top span{{font-size:9px;background:#d5e9d9;border-radius:10px;padding:2px 5px;white-space:nowrap}}.tb-class{{font-size:9px;font-weight:800;margin-top:3px}}.tb-meta{{font-size:8px;color:#55705d;margin-top:2px}}
        .tb-actions{{margin-top:6px;font-size:10px}}.tb-actions summary{{cursor:pointer;color:#17633b;font-weight:800;list-style:none}}.tb-actions summary::-webkit-details-marker{{display:none}}.tb-actions summary:before{{content:'•••';letter-spacing:2px;margin-right:5px}}.tb-actions form{{display:grid;gap:9px;margin-top:7px}}.tb-small,.tb-delete{{padding:9px;border:0;border-radius:8px;font-size:11px;font-weight:800;cursor:pointer}}.tb-small{{background:#287447;color:white}}.tb-delete{{background:#fff0ef;color:#a12828}}
        .tb-section-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap}}.tb-count{{padding:6px 10px;border-radius:999px;background:#edf6ee;color:#34764b;font-size:10px;font-weight:900;white-space:nowrap}}.tb-table-scroll{{overflow:auto;border:1px solid #e0eae1;border-radius:12px}}.tb-data-table{{width:100%;min-width:760px;border-collapse:collapse;background:#fff;font-size:11px}}.tb-data-table th{{background:#edf5ee;color:#315b3e;text-align:left;font-size:10px;letter-spacing:.03em;padding:11px 10px;white-space:nowrap}}.tb-data-table td{{padding:10px;border-top:1px solid #edf2ed;color:#3d5945;vertical-align:middle}}.tb-data-table tr:hover td{{background:#f8fcf8}}.tb-empty-cell{{text-align:center!important;color:#87988b!important;padding:22px!important}}.tb-row-actions summary{{cursor:pointer;color:#17633b;font-weight:900}}.tb-row-actions form{{display:grid;gap:7px;padding:8px 0}}.tb-row-actions label{{display:grid;gap:4px;font-size:10px;font-weight:800}}.tb-row-actions select{{padding:7px;border:1px solid #d5e4d7;border-radius:8px;min-width:110px}}.tb-row-actions button:disabled{{opacity:.45;cursor:not-allowed}}.tb-action-stack{{display:grid;gap:8px;min-width:135px}}.tb-action-stack>form{{margin:0}}.tb-row-actions{{min-width:135px}}.tb-row-actions[open]{{padding:8px;border:1px solid #dce9de;border-radius:9px;background:#fbfdfb}}.tb-row-actions form button{{width:100%;min-height:36px}}.tb-alert{{padding:11px 14px;border-radius:10px;margin-bottom:12px;font-size:12px;font-weight:700}}.tb-alert.success{{background:#eaf5ec;color:#17633b}}.tb-alert.error{{background:#fff1f0;color:#a12828}}.tb-empty{{padding:30px;text-align:center;color:#647b6a;background:#fff;border:1px dashed #cdddcf;border-radius:13px}}
        .tb-toolbar.tb-toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}}.tb-tool-button{{border:1px solid #cfe2d2;border-radius:10px;background:#fff;color:#286743;padding:10px 13px;font-size:11px;font-weight:850;cursor:pointer;box-shadow:0 2px 7px rgba(35,83,51,.05)}}.tb-tool-button:hover{{background:#eaf5ec;border-color:#9fc9a7}}.tb-modal-dialog>.tb-panel{{margin:0 0 12px}}.tb-modal-dialog .tb-table-scroll{{max-height:52vh;overflow:auto}}
        .tb-modal{{position:fixed;inset:0;z-index:10060;display:none;align-items:center;justify-content:center;padding:18px;background:rgba(20,43,30,.5);backdrop-filter:blur(5px)}}.tb-modal.is-open{{display:flex;animation:tbFade .16s ease-out}}.tb-modal-dialog{{width:min(680px,100%);max-height:88vh;overflow:auto;padding:25px;background:linear-gradient(145deg,#fff,#f3f9f3);border:1px solid #d5e6d8;border-radius:22px;box-shadow:0 24px 70px rgba(18,52,31,.25);animation:tbPop .18s ease-out}}
        .tb-modal-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:19px}}.tb-modal-head h3{{font-size:20px;margin:4px 0;color:#214a34}}.tb-modal-head p{{font-size:12px;color:#718477;margin:0}}.tb-modal-close{{border:0;width:36px;height:36px;border-radius:11px;background:#eaf4eb;color:#326a43;font-size:22px;cursor:pointer;flex:none}}
        .tb-modal .tb-add-form{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tb-modal .tb-add-form label.wide,.tb-modal .tb-add-form button{{grid-column:1/-1}}.tb-modal .tb-actions form{{display:grid;grid-template-columns:1fr 1fr;gap:11px}}.tb-modal .tb-actions form button{{grid-column:1/-1}}.tb-modal .tb-actions label{{min-width:0}}
        @keyframes tbFade{{from{{opacity:0}}to{{opacity:1}}}}@keyframes tbPop{{from{{opacity:0;transform:translateY(9px) scale(.985)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
        @media(max-width:900px){{.tb-add-form{{grid-template-columns:1fr 1fr}}.tb-add-form label.wide{{grid-column:1/-1}}}}
        @media(max-width:600px){{.tb-summary{{grid-template-columns:1fr 1fr}}.tb-summary>div:last-child{{grid-column:1/-1}}.tb-toolbar{{align-items:stretch}}.tb-profile-select{{width:100%}}.tb-profile-select select{{min-width:0;width:100%}}.tb-wrap{{padding:12px;border-radius:17px}}.tb-hero{{padding:21px 17px}}.tb-hero h2{{font-size:23px}}.tb-add-form,.tb-modal .tb-add-form,.tb-modal .tb-actions form{{grid-template-columns:1fr}}.tb-add-form label.wide,.tb-modal .tb-add-form label.wide,.tb-modal .tb-add-form button,.tb-modal .tb-actions form button{{grid-column:auto}}.tb-modal{{padding:10px}}.tb-modal-dialog{{padding:20px 16px;border-radius:18px}}.tb-hero>div:last-child{{width:100%}}.tb-hero>div:last-child a{{flex:1}}}}
        </style>
        <div class='tb-wrap'><header class='tb-hero'><div><span class='tb-kicker'>DAVISCHOOL · TIMETABLE WORKSPACE</span><h2>Manual Timetable Builder</h2><p>Drag to move · Select a tool for other actions.</p></div></header>{notice}<div class='tb-toolbar'>{profile_selector}<div class='tb-profile-context'><strong>{esc(selected['name'])}</strong><span>{esc(selected['academic_year'])} · {esc(selected['term'])}</span></div></div><nav class='tb-toolbar' aria-label='Builder tools'>{builder_tool_buttons}</nav>{grid}{builder_modals}</div>
        <script>
        (function(){{
          const modals=Array.from(document.querySelectorAll('.tb-modal'));
          function closeAll(){{modals.forEach(function(m){{m.classList.remove('is-open');m.setAttribute('aria-hidden','true');}});document.body.style.overflow='';}}
          document.addEventListener('click',function(event){{
            const open=event.target.closest('[data-modal-open]');
            if(open){{const modal=document.getElementById(open.dataset.modalOpen);if(modal){{closeAll();modal.classList.add('is-open');modal.setAttribute('aria-hidden','false');document.body.style.overflow='hidden';}}return;}}
            if(event.target.closest('[data-modal-close]')||event.target.classList.contains('tb-modal'))closeAll();
          }});
          document.addEventListener('keydown',function(event){{if(event.key==='Escape')closeAll();}});
        }})();
        function dragTimetableLesson(event){{var card=event.target.closest('[data-lesson-id]');if(card)event.dataTransfer.setData('text/plain',card.dataset.lessonId);}}
        function dropTimetableLesson(event,cell){{event.preventDefault();var lessonId=event.dataTransfer.getData('text/plain');if(!lessonId)return;var form=document.createElement('form');form.method='POST';form.action='/app/timetable/builder/move';[['profile_id','{pid}'],['lesson_id',lessonId],['day_id',cell.dataset.dayId],['period_id',cell.dataset.periodId]].forEach(function(pair){{var input=document.createElement('input');input.type='hidden';input.name=pair[0];input.value=pair[1];form.appendChild(input);}});document.body.appendChild(form);form.submit();}}
        </script>
        """
        return module_page(request, "Timetable Builder", "timetable", body)

    @app.get("/app/timetable/builder/date-slots")
    def timetable_builder_date_slots(request: Request, profile_id: int = 0, requirement_id: int = 0, session_date: str = ""):
        school = school_for(request)
        if not school:
            return JSONResponse({"ok": False, "error": "Your session has expired. Sign in again."}, status_code=401)
        con = get_db()
        try:
            cur = con.cursor()
            requirement = cur.execute(
                """SELECT schedule_layer FROM ds_timetable_scheduling_requirements
                   WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
                (requirement_id, int(school["id"]), profile_id),
            ).fetchone()
            if not requirement:
                raise TimetableSetupError("Select an active scheduling requirement from this timetable profile.")
            layer = str(requirement["schedule_layer"])
            allowed_types = {
                "instructional": {"instructional"},
                "additional_learning": {"remedial", "study"},
                "school_activity": {"activity", "assembly", "other"},
            }.get(layer, set())
            occurrence = resolve_calendar_occurrence(con, int(school["id"]), profile_id, session_date)
            slots = [
                {
                    "slot_no": int(slot["slot_no"]),
                    "label": str(slot["label"]),
                    "slot_type": str(slot["slot_type"]),
                    "start_time": str(slot["start_time"]),
                    "end_time": str(slot["end_time"]),
                }
                for slot in occurrence["schedule_slots"]
                if str(slot["slot_type"]).lower() in allowed_types
                and (layer != "instructional" or occurrence["is_instructional"])
            ]
            rotations = [
                str((item.get("week") or {}).get("label") or item.get("cycle_name") or "Active rotation")
                for item in occurrence.get("rotations", [])
            ]
            return JSONResponse({
                "ok": True,
                "date": session_date,
                "day_code": occurrence.get("day_code"),
                "day_name": occurrence.get("day_name"),
                "is_instructional": bool(occurrence.get("is_instructional")),
                "schedule_layer": layer,
                "slots": slots,
                "rotations": rotations,
            })
        except (TimetableSetupError, ValueError, TypeError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        finally:
            con.close()

    @app.post("/app/timetable/builder/add-dated")
    def add_dated_builder_session(request: Request, profile_id: int = Form(...),
        requirement_id: int = Form(...), session_no: int = Form(...),
        session_date: str = Form(...), slot_no: int = Form(...), room_id: str = Form("")):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            place_dated_advanced_requirement_session(
                con, int(school["id"]), profile_id, requirement_id, session_no,
                session_date, slot_no, int(room_id) if room_id else None,
                request.session.get("email", ""),
            )
            return redirect_builder(profile_id, "Calendar-dated lesson placed successfully.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_builder(profile_id, str(exc), True)
        finally:
            con.close()

    @app.post("/app/timetable/builder/room-policy")
    def save_builder_room_policy(request: Request, profile_id: int = Form(...),
        requirement_id: int = Form(...), room_assignment_mode: str = Form("automatic"),
        preferred_room_id: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            mode = (room_assignment_mode or "automatic").strip().lower()
            if mode not in {"automatic", "preferred", "fixed"}:
                raise TimetableSetupError("Choose Automatic, Preferred or Fixed room allocation.")
            room_id = int(preferred_room_id) if preferred_room_id.strip() else None
            if mode in {"preferred", "fixed"} and room_id is None:
                raise TimetableSetupError("Choose a room for Preferred or Fixed allocation.")
            requirement = con.execute("SELECT room_type FROM ds_timetable_scheduling_requirements WHERE id=? AND school_id=? AND profile_id=? AND is_active=1", (requirement_id, int(school["id"]), profile_id)).fetchone()
            if not requirement: raise TimetableSetupError("Select a valid scheduling requirement.")
            if room_id is not None:
                room = con.execute("SELECT room_type,is_active FROM ds_timetable_rooms WHERE id=? AND school_id=?", (room_id, int(school["id"]))).fetchone()
                if not room or not int(room["is_active"] or 0): raise TimetableSetupError("Select an active room.")
                if requirement["room_type"] and str(room["room_type"]) != str(requirement["room_type"]):
                    raise TimetableSetupError("The selected room does not match the required room type.")
            if mode == "automatic": room_id = None
            con.execute("UPDATE ds_timetable_scheduling_requirements SET room_assignment_mode=?,preferred_room_id=? WHERE id=? AND school_id=? AND profile_id=?", (mode, room_id, requirement_id, int(school["id"]), profile_id))
            con.commit()
            return redirect_builder(profile_id, "Room allocation rule saved.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_builder(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/builder/create-combined")
    def create_combined_builder_requirement(request: Request, profile_id: int = Form(...),
        name: str = Form(...), class_ids: list[int] = Form(...),
        teacher_ids: list[int] = Form(...), subject_id: int = Form(...),
        duration_periods: int = Form(1), room_type: str = Form("classroom"),
        room_assignment_mode: str = Form("automatic"), preferred_room_id: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            classes = list(dict.fromkeys(int(value) for value in class_ids))
            teachers = list(dict.fromkeys(int(value) for value in teacher_ids))
            if len(classes) < 2: raise TimetableSetupError("Select at least two classes to create a combined lesson.")
            if not teachers: raise TimetableSetupError("Select at least one teacher for the combined lesson.")
            if not 1 <= int(duration_periods) <= 4: raise TimetableSetupError("A combined lesson must occupy 1–4 consecutive periods.")
            mode = (room_assignment_mode or "automatic").strip().lower()
            room_id = int(preferred_room_id) if preferred_room_id.strip() else None
            if mode not in {"automatic", "preferred", "fixed"}: raise TimetableSetupError("Choose Automatic, Preferred or Fixed room allocation.")
            if mode in {"preferred", "fixed"} and room_id is None: raise TimetableSetupError("Choose a room for Preferred or Fixed allocation.")
            school_id = int(school["id"])
            if con.execute("SELECT id FROM ds_timetable_teaching_groups WHERE school_id=? AND profile_id=? AND name=? AND is_active=1", (school_id, profile_id, name.strip())).fetchone():
                raise TimetableSetupError("A combined teaching group with that name already exists in this timetable.")
            if con.execute("SELECT id FROM ds_timetable_scheduling_requirements WHERE school_id=? AND profile_id=? AND name=? AND is_active=1", (school_id, profile_id, name.strip() + " — combined session")).fetchone():
                raise TimetableSetupError("A combined scheduling requirement with that name already exists.")
            if not con.execute("SELECT id FROM subjects WHERE id=? AND school_id=?", (subject_id, school_id)).fetchone():
                raise TimetableSetupError("Choose a subject belonging to this school.")
            if room_id is not None:
                room = con.execute("SELECT room_type,is_active FROM ds_timetable_rooms WHERE id=? AND school_id=?", (room_id, school_id)).fetchone()
                if not room or not int(room["is_active"] or 0):
                    raise TimetableSetupError("Choose an active room belonging to this school.")
                if room_type and str(room["room_type"]) != room_type:
                    raise TimetableSetupError("The preferred or fixed room must match the selected room type.")
            group_id = create_teaching_group(con, int(school["id"]), profile_id, name, classes,
                group_type="combined_class", subject_id=subject_id,
                notes="Combined class session with a shared teaching team.")
            requirement_id = create_scheduling_requirement(
                con, int(school["id"]), profile_id, name + " — combined session",
                class_ids=classes, teacher_ids=teachers, schedule_layer="instructional",
                session_type="lesson", subject_id=subject_id, teaching_group_id=group_id,
                weekly_occurrences=1, weekly_periods=int(duration_periods),
                counts_toward_curriculum=True, min_teacher_count=1,
                room_type=room_type, room_assignment_mode=mode, preferred_room_id=room_id,
            )
            save_scheduling_pattern(con, int(school["id"]), profile_id, requirement_id,
                [{"duration_periods": int(duration_periods), "session_label": "Combined lesson"}])
            return redirect_builder(profile_id, "Combined class and co-teaching requirement created. It is ready to place in the timetable.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_builder(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/builder/deactivate-group")
    def deactivate_builder_group(request: Request, profile_id: int = Form(...), group_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            school_id = int(school["id"])
            group = con.execute(
                "SELECT id FROM ds_timetable_teaching_groups WHERE id=? AND school_id=? AND profile_id=?",
                (group_id, school_id, profile_id),
            ).fetchone()
            if not group: raise TimetableSetupError("Combined teaching group not found.")
            con.execute(
                "UPDATE ds_timetable_scheduling_requirements SET is_active=0 WHERE school_id=? AND profile_id=? AND teaching_group_id=?",
                (school_id, profile_id, group_id),
            )
            con.execute(
                "UPDATE ds_timetable_teaching_groups SET is_active=0 WHERE id=? AND school_id=? AND profile_id=?",
                (group_id, school_id, profile_id),
            )
            con.commit()
            return redirect_builder(profile_id, "Combined group deactivated; saved history is retained.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_builder(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/builder/deactivate-requirement")
    def deactivate_builder_requirement(request: Request, profile_id: int = Form(...), requirement_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            cur = con.cursor()
            row = cur.execute(
                "SELECT teaching_group_id FROM ds_timetable_scheduling_requirements WHERE id=? AND school_id=? AND profile_id=? AND is_active=1",
                (requirement_id, int(school["id"]), profile_id),
            ).fetchone()
            if not row: raise TimetableSetupError("Active scheduling requirement not found.")
            cur.execute(
                "UPDATE ds_timetable_scheduling_requirements SET is_active=0 WHERE id=? AND school_id=? AND profile_id=?",
                (requirement_id, int(school["id"]), profile_id),
            )
            if row["teaching_group_id"] is not None:
                cur.execute(
                    "UPDATE ds_timetable_teaching_groups SET is_active=0 WHERE id=? AND school_id=? AND profile_id=?",
                    (int(row["teaching_group_id"]), int(school["id"]), profile_id),
                )
            con.commit()
            return redirect_builder(profile_id, "Scheduling requirement deactivated; saved session history is retained.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_builder(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/builder/cancel-session")
    def cancel_builder_session(request: Request, profile_id: int = Form(...), session_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            cur = con.cursor()
            row = cur.execute(
                "SELECT id FROM ds_timetable_sessions WHERE id=? AND school_id=? AND profile_id=? AND status='scheduled'",
                (session_id, int(school["id"]), profile_id),
            ).fetchone()
            if not row: raise TimetableSetupError("Scheduled session not found.")
            cur.execute(
                "UPDATE ds_timetable_sessions SET status='cancelled' WHERE id=? AND school_id=? AND profile_id=?",
                (session_id, int(school["id"]), profile_id),
            )
            con.commit()
            return redirect_builder(profile_id, "Session removed from the active timetable; its record is retained.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_builder(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/builder/add-advanced")
    def add_advanced_builder_session(request: Request, profile_id: int = Form(...),
        requirement_id: int = Form(...), session_no: int = Form(...),
        day_id: int = Form(...), period_id: int = Form(...), room_id: str = Form("")):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            place_advanced_requirement_session(
                con, int(school["id"]), profile_id, requirement_id, session_no,
                day_id, period_id, int(room_id) if room_id else None,
                request.session.get("email", ""),
            )
            return redirect_builder(profile_id, "Advanced session placed successfully.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_builder(profile_id, str(exc), True)
        finally:
            con.close()

    @app.post("/app/timetable/builder/add")
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

    @app.post("/app/timetable/builder/move")
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

    @app.post("/app/timetable/builder/delete")
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
