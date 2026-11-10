"""Published timetable access for authenticated teacher, student and parent portals.

Portal requests are resolved from the signed-in session and school-scoped records.
Only currently published profiles are returned; every request reads the latest
published profile, so a newly released revision is visible on the next refresh.
"""
from __future__ import annotations

from html import escape

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.views import get_timetable_view


PORTAL_ROLES = {"teacher", "student", "parent"}


def get_portal_timetable_targets(connection, school_id: int, role: str,
                                 teacher_id: int = 0, student_id: int = 0,
                                 user_id: int = 0) -> list[tuple[str, int, str]]:
    """Resolve only the timetable targets linked to this authenticated account."""
    cur = connection.cursor()
    role = str(role or "").strip().lower()
    if role == "teacher":
        if not teacher_id:
            return []
        teacher = cur.execute(
            "SELECT id,name FROM teachers WHERE id=? AND school_id=?",
            (int(teacher_id), int(school_id)),
        ).fetchone()
        return [("teacher", int(teacher["id"]), str(teacher["name"]))] if teacher else []
    if role == "student":
        if not student_id:
            return []
        student = cur.execute(
            """SELECT s.id,s.name,s.class_id,c.name class_name,c.stream
               FROM students s LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id
               WHERE s.id=? AND s.school_id=?""",
            (int(student_id), int(school_id)),
        ).fetchone()
        if not student or not student["class_id"]:
            return []
        label = str(student["name"]) + " · " + str(student["class_name"] or "Class")
        if student["stream"]:
            label += " " + str(student["stream"])
        return [("student", int(student["id"]), label)]
    if role == "parent":
        if not user_id:
            return []
        rows = cur.execute(
            """SELECT DISTINCT s.id,s.name,s.class_id,c.name class_name,c.stream
               FROM parent_student_links l
               JOIN students s ON s.id=l.student_id AND s.school_id=l.school_id
               LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id
               WHERE l.school_id=? AND l.user_id=? AND s.class_id IS NOT NULL
               ORDER BY s.name,s.id""",
            (int(school_id), int(user_id)),
        ).fetchall()
        return [
            ("student", int(row["id"]),
             str(row["name"]) + " · " + str(row["class_name"] or "Class")
             + ((" " + str(row["stream"])) if row["stream"] else ""))
            for row in rows
        ]
    return []



def build_portal_timetable_rows(view: dict) -> list[dict]:
    """Merge legacy weekly lessons and normalized sessions for portal display."""
    rows = []
    for lesson in view.get("lessons", []):
        rows.append({
            "date_day": str(lesson["day_name"]),
            "time": str(lesson["period_label"]) + " · " + str(lesson["start_time"]) + "–" + str(lesson["end_time"]),
            "subject": str(lesson["subject_name"]),
            "class_group": str(lesson["class_name"]) + ((" " + str(lesson["stream"])) if lesson["stream"] else ""),
            "teachers": str(lesson["teacher_name"]),
            "venue": str(lesson.get("room_name") or "—"),
            "layer": "Instructional",
            "sort_date": "",
            "sort_time": str(lesson["start_time"]),
        })
    for session in view.get("advanced_sessions", []):
        date_day = str(session.get("session_date") or session.get("day_name") or "Scheduled")
        if session.get("session_date") and session.get("day_name"):
            date_day += " · " + str(session["day_name"])
        layer = str(session.get("schedule_layer") or "instructional").replace("_", " ").title()
        rows.append({
            "date_day": date_day,
            "time": str(session.get("start_time") or "") + "–" + str(session.get("end_time") or ""),
            "subject": str(session.get("subject_name") or session.get("programme_name") or session.get("session_type") or "Session"),
            "class_group": str(session.get("class_names") or "—"),
            "teachers": str(session.get("teacher_names") or "—"),
            "venue": str(session.get("room_name") or "—"),
            "layer": layer,
            "sort_date": str(session.get("session_date") or ""),
            "sort_time": str(session.get("start_time") or ""),
        })
    return sorted(rows, key=lambda row: (row["sort_date"] or "0000-00-00", row["sort_time"], row["date_day"], row["subject"]))



def build_teacher_timetable_grid(view: dict) -> str:
    """Render the teacher's personal timetable using the same weekly grid language as admin views."""
    days = view.get("days", [])
    periods = view.get("periods", [])
    breaks = view.get("breaks", [])
    lessons = view.get("lessons", [])
    if not days or not periods:
        return "<div class='tp-empty'>No weekly timetable grid is configured.</div>"

    timeline = sorted(
        [(str(p["start_time"]), "period", p) for p in periods]
        + [(str(br["start_time"]), "break", br) for br in breaks],
        key=lambda item: (item[0], 0 if item[1] == "period" else 1),
    )
    period_index = {int(p["id"]): i for i, p in enumerate(periods)}
    by_slot = {}
    occupied = {}
    for lesson in lessons:
        key = (int(lesson["day_id"]), int(lesson["period_id"]))
        by_slot.setdefault(key, []).append(lesson)
        start = period_index.get(int(lesson["period_id"]))
        duration = max(1, int(lesson.get("duration_periods") or 1))
        if start is not None:
            for offset in range(1, duration):
                if start + offset < len(periods):
                    occupied.setdefault(
                        (int(lesson["day_id"]), int(periods[start + offset]["id"])), []
                    ).append(lesson)

    headers = ["<th class='tp-day-col'>Day</th>"]
    for _, kind, item in timeline:
        if kind == "break":
            headers.append(
                "<th class='tp-break-head'><b>" + escape(str(item["label"]))
                + "</b><span>" + escape(str(item["start_time"])) + "–"
                + escape(str(item["end_time"])) + "</span></th>"
            )
        else:
            headers.append(
                "<th class='tp-period-head'><b>" + escape(str(item["label"]))
                + "</b><span>" + escape(str(item["start_time"])) + "–"
                + escape(str(item["end_time"])) + "</span></th>"
            )

    rows = []
    for day in days:
        cells = ["<th class='tp-day-col'>" + escape(str(day.get("day_code") or day["day_name"])) + "</th>"]
        merged = set()
        for pos, (_, kind, item) in enumerate(timeline):
            if kind == "break":
                cells.append(
                    "<td class='tp-break-cell'><b>" + escape(str(item["label"]))
                    + "</b><span>" + escape(str(item["start_time"])) + "–"
                    + escape(str(item["end_time"])) + "</span></td>"
                )
                continue
            period_id = int(item["id"])
            if period_id in merged:
                continue
            slot = by_slot.get((int(day["id"]), period_id), [])
            continued = occupied.get((int(day["id"]), period_id), [])
            if slot:
                cards = []
                span = 1
                for lesson in slot:
                    duration = max(1, int(lesson.get("duration_periods") or 1))
                    start = period_index.get(period_id)
                    span_periods = [periods[start + offset] for offset in range(duration)
                                    if start is not None and start + offset < len(periods)]
                    can_merge = len(span_periods) == duration and all(
                        next((p for p, entry in enumerate(timeline)
                              if entry[1] == "period" and int(entry[2]["id"]) == int(span_periods[offset]["id"])), -2) == pos + offset
                        for offset in range(duration)
                    )
                    if can_merge and duration > span:
                        span = duration
                        merged.update(int(p["id"]) for p in span_periods[1:])
                    color = str(lesson.get("teacher_color") or "#347b50")
                    if not (len(color) == 7 and color.startswith("#")
                            and all(ch in "0123456789abcdefABCDEF" for ch in color[1:])):
                        color = "#347b50"
                    class_label = str(lesson.get("class_name") or "Class")
                    if lesson.get("stream"):
                        class_label += " · " + str(lesson["stream"])
                    room = str(lesson.get("room_name") or "Room not assigned")
                    cards.append(
                        "<article class='tp-lesson' style='--lesson-color:" + escape(color) + "'>"
                        "<div class='tp-lesson-top'><b>" + escape(str(lesson.get("subject_name") or "Lesson"))
                        + "</b><span>" + str(duration) + "P</span></div>"
                        "<div class='tp-lesson-class'>" + escape(class_label) + "</div>"
                        "<div class='tp-lesson-room'>⌂ " + escape(room) + "</div></article>"
                    )
                cells.append("<td class='tp-slot' colspan='" + str(span) + "'>" + "".join(cards) + "</td>")
            elif continued:
                cells.append(
                    "<td class='tp-continued'>↳ " + " · ".join(
                        escape(str(item.get("subject_name") or "Lesson")) + " continues"
                        for item in continued
                    ) + "</td>"
                )
            else:
                cells.append("<td class='tp-free'></td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<div class='tp-grid-scroll'><table class='tp-grid'><thead><tr>"
        + "".join(headers) + "</tr></thead><tbody>" + "".join(rows)
        + "</tbody></table></div>"
    )


def register_timetable_portal_routes(app, get_db):
    @app.get("/app/timetable/my", response_class=HTMLResponse)
    def published_portal_timetable(request: Request):
        role = str(request.session.get("role") or "").strip().lower()
        if not request.session.get("email") or role not in PORTAL_ROLES:
            return RedirectResponse("/", status_code=303)
        try:
            school_id = int(request.session.get("school_id") or 0)
        except (TypeError, ValueError):
            school_id = 0
        if school_id <= 0:
            return HTMLResponse("Your account is not linked to a school.", status_code=403)

        con = get_db()
        try:
            targets = get_portal_timetable_targets(
                con, school_id, role,
                int(request.session.get("teacher_id") or 0),
                int(request.session.get("student_id") or 0),
                int(request.session.get("user_id") or 0),
            )
            profiles = con.execute(
                """SELECT id,name,academic_year,term,revision_no,published_at,profile_type
                   FROM ds_timetable_profiles
                   WHERE school_id=? AND status='published'
                   ORDER BY academic_year DESC,term DESC,published_at DESC,id DESC""",
                (school_id,),
            ).fetchall()
            sections = []
            for profile in profiles:
                for view_type, target_id, label in targets:
                    try:
                        view = get_timetable_view(con, school_id, int(profile["id"]), view_type, target_id)
                    except Exception:
                        # A profile without a usable day/period setup is not
                        # allowed to break access to other published profiles.
                        continue
                    if role == "teacher":
                        schedule_html = build_teacher_timetable_grid(view)
                    else:
                        portal_rows = build_portal_timetable_rows(view)
                        lesson_rows = []
                        for row in portal_rows:
                            lesson_rows.append(
                                "<tr><td>" + escape(row["date_day"]) + "</td><td>"
                                + escape(row["time"]) + "</td><td><b>" + escape(row["subject"])
                                + "</b><br><small>" + escape(row["layer"]) + "</small></td><td>"
                                + escape(row["class_group"]) + "</td><td>" + escape(row["teachers"])
                                + "</td><td>" + escape(row["venue"]) + "</td></tr>"
                            )
                        schedule_html = (
                            "<div class='tp-scroll'><table><thead><tr><th>Date / Day</th><th>Time</th><th>Subject / Activity</th><th>Class</th><th>Teacher</th><th>Room</th></tr></thead><tbody>"
                            + "".join(lesson_rows) + "</tbody></table></div>"
                            if lesson_rows else "<p class='tp-empty'>No lessons are scheduled for this timetable.</p>"
                        )
                    sections.append(
                        "<section class='tp-card'><div class='tp-head'><div><h2>"
                        + escape(label) + "</h2><p>" + escape(str(profile["academic_year"]))
                        + " · " + escape(str(profile["term"])) + " · " + escape(str(profile["profile_type"] or "main").replace("_", " ").title()) + " · Revision "
                        + escape(str(profile["revision_no"] or 1)) + "</p></div><span>Published</span></div>"
                        + schedule_html + "</section>"
                    )
            if not targets:
                message = ("This account is not linked to a teacher profile." if role == "teacher"
                           else "This account is not linked to a learner." if role == "student"
                           else "No learners are linked to this parent account.")
            elif not profiles:
                message = "There is no published timetable for your school yet."
            else:
                message = ""
        finally:
            con.close()

        body = (
            "<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>My Timetable · DaviSchool</title><meta http-equiv='refresh' content='60'><style>"
            "body{margin:0;background:#f1f7f1;color:#173d2b;font:14px Arial,sans-serif}"
            ".tp-wrap{max-width:1250px;margin:auto;padding:22px}.tp-hero{margin-bottom:18px}"
            ".tp-hero h1{margin:0 0 6px;font-size:26px}.tp-hero-top{display:flex;align-items:center;justify-content:space-between;gap:12px}.tp-sidebar-toggle{width:36px;height:36px;flex:0 0 36px;border:1px solid #cfe0d2;border-radius:10px;background:#fff;color:#245b39;font-size:19px;cursor:pointer;display:grid;place-items:center}.tp-sidebar-toggle:hover{background:#e8f4eb}.tp-hero p,.tp-head p{color:#64748b;margin:0;font-size:12px}"
            ".tp-card{background:#fff;border:1px solid #dce9de;border-radius:14px;padding:16px;margin:14px 0}"
            ".tp-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}"
            ".tp-head h2{font-size:17px;margin:0 0 5px}.tp-head span{background:#eaf5ec;color:#17633b;padding:6px 10px;border-radius:18px;font-size:10px;font-weight:bold}"
            ".tp-scroll,.tp-grid-scroll{overflow:auto;border:1px solid #dce8de;border-radius:14px;background:#fff}"
            ".tp-scroll table{border-collapse:collapse;width:100%;min-width:720px}.tp-scroll th,.tp-scroll td{text-align:left;padding:10px;border-bottom:1px solid #edf2ed;font-size:12px}.tp-scroll th{background:#f0f6f1;color:#315b3e}small{color:#64748b}"
            ".tp-grid{width:100%;min-width:1000px;border-collapse:separate;border-spacing:0}.tp-grid thead th{background:linear-gradient(110deg,#347b50,#286743);color:#fff;padding:10px 8px;text-align:center;font-size:12px;position:sticky;top:0;min-width:135px;border-bottom:5px solid #b7d1bc}.tp-grid thead th b,.tp-grid thead th span{display:block}.tp-grid thead th span{font-size:10px;margin-top:4px;color:#e1efe4}.tp-grid .tp-day-col{width:56px;min-width:56px;max-width:56px;padding:6px 2px;background:#edf5ee;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:0;z-index:2;white-space:normal;overflow-wrap:anywhere;font-size:10px}.tp-grid tbody th,.tp-grid tbody td{border-bottom:3px solid #c7d9ca}.tp-grid .tp-break-head,.tp-grid .tp-break-cell{min-width:70px;background:#f1ead8;color:#75551d;text-align:center;padding:8px}.tp-grid .tp-break-cell b,.tp-grid .tp-break-cell span{display:block}.tp-grid .tp-break-cell b{writing-mode:vertical-rl;margin:auto}.tp-grid .tp-break-cell span{font-size:9px;margin-top:5px}.tp-grid .tp-slot,.tp-grid .tp-free,.tp-grid .tp-continued{height:94px;min-width:125px;padding:5px;border-right:2px solid #b4cbb8;vertical-align:middle;text-align:center}.tp-grid .tp-free{background:#fbfdfb}.tp-grid .tp-continued{background:#f6faf6;color:#7b9480;font-size:10px}.tp-lesson{--lesson-color:#347b50;background:color-mix(in srgb,var(--lesson-color) 17%,white);border:1px solid color-mix(in srgb,var(--lesson-color) 48%,white);border-left:4px solid var(--lesson-color);border-radius:9px;padding:8px 7px;min-height:74px;display:flex;flex-direction:column;justify-content:center;gap:5px;color:#234638;box-shadow:0 2px 7px rgba(35,83,51,.07)}.tp-lesson-top{display:flex;justify-content:center;align-items:center;gap:8px}.tp-lesson-top b{font-size:12px}.tp-lesson-top span{font-size:9px;background:#d5e9d9;border-radius:10px;padding:2px 5px;white-space:nowrap}.tp-lesson-class{font-size:10px;font-weight:850;color:#315f43}.tp-lesson-room{font-size:9px;color:#55705d}.tp-empty,.tp-notice{padding:18px;background:#fff;border:1px dashed #cdddcf;border-radius:12px;color:#64748b}"
            "@media(max-width:600px){.tp-wrap{padding:12px}.tp-hero h1{font-size:22px}.tp-card{padding:11px}.tp-grid-scroll{border-radius:11px}}"
            "</style></head><body><main class='tp-wrap'><header class='tp-hero'><div class='tp-hero-top'><h1>My Timetable</h1><button class='tp-sidebar-toggle' type='button' aria-label='Hide Sidebar' title='Hide Sidebar' onclick='(function(){var docs=[document];try{if(window.parent&&window.parent!==window)docs.push(window.parent.document)}catch(e){}for(var d of docs){var b=Array.from(d.querySelectorAll("button,a,[role=button]" )).find(function(x){var t=((x.innerText||x.getAttribute("aria-label")||x.getAttribute("title")||"").trim()).toLowerCase();return t==="hide sidebar"||t==="show sidebar"||t.includes("hide sidebar")||t.includes("show sidebar")});if(b){b.click();return}}})();'><span aria-hidden='true'>◧</span></button></div>"
            "<p>Latest published timetable · DaviSchool</p></header>"
            + ("<div class='tp-notice'>" + escape(message) + "</div>" if message else "")
            + "".join(sections)
            + "</main></body></html>"
        )
        return HTMLResponse(body)
