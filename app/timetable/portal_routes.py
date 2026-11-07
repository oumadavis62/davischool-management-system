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
        return [("class", int(student["class_id"]), label)]
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
            ("class", int(row["class_id"]),
             str(row["name"]) + " · " + str(row["class_name"] or "Class")
             + ((" " + str(row["stream"])) if row["stream"] else ""))
            for row in rows
        ]
    return []


def register_timetable_portal_routes(app, get_db):
    @app.get("/app/timetable", response_class=HTMLResponse)
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
                """SELECT id,name,academic_year,term,revision_no,published_at
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
                    lesson_rows = []
                    for lesson in view["lessons"]:
                        lesson_rows.append(
                            "<tr><td>" + escape(str(lesson["day_name"])) + "</td><td>"
                            + escape(str(lesson["period_label"])) + "<br><small>"
                            + escape(str(lesson["start_time"])) + "–" + escape(str(lesson["end_time"]))
                            + "</small></td><td><b>" + escape(str(lesson["subject_name"]))
                            + "</b></td><td>" + escape(str(lesson["class_name"]))
                            + ((" " + escape(str(lesson["stream"]))) if lesson["stream"] else "")
                            + "</td><td>" + escape(str(lesson["teacher_name"]))
                            + "</td><td>" + escape(str(lesson["room_name"] or "—")) + "</td></tr>"
                        )
                    sections.append(
                        "<section class='tp-card'><div class='tp-head'><div><h2>"
                        + escape(label) + "</h2><p>" + escape(str(profile["academic_year"]))
                        + " · " + escape(str(profile["term"])) + " · Revision "
                        + escape(str(profile["revision_no"] or 1)) + "</p></div><span>Published</span></div>"
                        + ("<div class='tp-scroll'><table><thead><tr><th>Day</th><th>Time</th><th>Subject</th><th>Class</th><th>Teacher</th><th>Room</th></tr></thead><tbody>"
                           + "".join(lesson_rows) + "</tbody></table></div>"
                           if lesson_rows else "<p class='tp-empty'>No lessons are scheduled for this timetable.</p>")
                        + "</section>"
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
            "<title>My Timetable · DaviSchool</title><style>"
            "body{margin:0;background:#f1f7f1;color:#173d2b;font:14px Arial,sans-serif}"
            ".tp-wrap{max-width:1250px;margin:auto;padding:22px}.tp-hero{margin-bottom:18px}"
            ".tp-hero h1{margin:0 0 6px;font-size:26px}.tp-hero p,.tp-head p{color:#64748b;margin:0;font-size:12px}"
            ".tp-card{background:#fff;border:1px solid #dce9de;border-radius:14px;padding:16px;margin:14px 0}"
            ".tp-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}"
            ".tp-head h2{font-size:17px;margin:0 0 5px}.tp-head span{background:#eaf5ec;color:#17633b;padding:6px 10px;border-radius:18px;font-size:10px;font-weight:bold}"
            ".tp-scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:720px}th,td{text-align:left;padding:10px;border-bottom:1px solid #edf2ed;font-size:12px}th{background:#f0f6f1;color:#315b3e}small{color:#64748b}"
            ".tp-empty,.tp-notice{padding:18px;background:#fff;border:1px dashed #cdddcf;border-radius:12px;color:#64748b}"
            "@media(max-width:600px){.tp-wrap{padding:12px}.tp-hero h1{font-size:22px}}"
            "</style></head><body><main class='tp-wrap'><header class='tp-hero'><h1>My Timetable</h1>"
            "<p>Latest published timetable · DaviSchool</p></header>"
            + ("<div class='tp-notice'>" + escape(message) + "</div>" if message else "")
            + "".join(sections)
            + "</main></body></html>"
        )
        return HTMLResponse(body)
