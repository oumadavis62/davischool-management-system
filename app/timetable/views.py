"""Read-only school, class, teacher and room timetable views."""
from __future__ import annotations

from typing import Any

from app.timetable.setup import TimetableSetupError


def get_timetable_view(connection: Any, school_id: int, profile_id: int, view_type: str = "school", target_id: int = 0) -> dict:
    if view_type not in ("school", "class", "student", "teacher", "room"):
        raise TimetableSetupError("Choose a valid timetable view.")
    cur = connection.cursor()
    profile = cur.execute(
        "SELECT id FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    if not profile:
        raise TimetableSetupError("Select a timetable profile belonging to this school.")
    profile = cur.execute(
        "SELECT id,name,academic_year,term,status,revision_no,current_version_id FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    days = cur.execute(
        """SELECT * FROM ds_timetable_days
           WHERE school_id=? AND profile_id=? AND is_instructional=1 ORDER BY day_order,id""",
        (school_id, profile_id),
    ).fetchall()
    periods = cur.execute(
        """SELECT * FROM ds_timetable_periods
           WHERE school_id=? AND profile_id=? AND period_type='lesson' ORDER BY period_no,id""",
        (school_id, profile_id),
    ).fetchall()
    if not days or not periods:
        raise TimetableSetupError("Configure instructional days and periods before viewing this timetable.")

    breaks = cur.execute(
        """SELECT * FROM ds_timetable_breaks
           WHERE school_id=? AND profile_id=? ORDER BY start_time,break_no,id""",
        (school_id, profile_id),
    ).fetchall()
    where = ""
    params: list[Any] = [school_id, profile_id]
    title = "School-wide timetable"
    target = None
    if view_type == "class":
        target = cur.execute(
            "SELECT id,name,stream FROM classes WHERE id=? AND school_id=?",
            (target_id, school_id),
        ).fetchone()
        if not target:
            raise TimetableSetupError("Select a class or stream belonging to this school.")
        where = " AND l.class_id=?"
        params.append(target_id)
        title = str(target["name"]) + ((" " + str(target["stream"])) if target["stream"] else "") + " timetable"
    elif view_type == "student":
        target = cur.execute(
            """SELECT s.id,s.name,s.class_id,c.name class_name,c.stream
               FROM students s LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id
               WHERE s.id=? AND s.school_id=?""",
            (target_id, school_id),
        ).fetchone()
        if not target:
            raise TimetableSetupError("Select a learner belonging to this school.")
        if target["class_id"]:
            where = " AND l.class_id=?"
            params.append(int(target["class_id"]))
        else:
            where = " AND 1=0"
        title = str(target["name"]) + " — learner timetable"
    elif view_type == "teacher":
        target = cur.execute(
            "SELECT id,name FROM teachers WHERE id=? AND school_id=?",
            (target_id, school_id),
        ).fetchone()
        if not target:
            raise TimetableSetupError("Select a teacher belonging to this school.")
        where = " AND l.teacher_id=?"
        params.append(target_id)
        title = str(target["name"]) + " — teacher timetable"
    elif view_type == "room":
        target = cur.execute(
            "SELECT id,name,room_code FROM ds_timetable_rooms WHERE id=? AND school_id=? AND is_active=1",
            (target_id, school_id),
        ).fetchone()
        if not target:
            raise TimetableSetupError("Select an active room belonging to this school.")
        where = " AND l.room_id=?"
        params.append(target_id)
        title = str(target["name"]) + " — room timetable"

    lessons = cur.execute(
        """SELECT l.*,c.name class_name,c.stream,s.name subject_name,s.initial subject_initial,
                  t.name teacher_name,t.teacher_color,t.teacher_initials,
                  rm.name room_name,p.period_no,p.label period_label,p.start_time,p.end_time,d.day_name
           FROM ds_timetable_lessons l
           JOIN classes c ON c.id=l.class_id AND c.school_id=l.school_id
           JOIN subjects s ON s.id=l.subject_id AND s.school_id=l.school_id
           JOIN teachers t ON t.id=l.teacher_id AND t.school_id=l.school_id
           LEFT JOIN ds_timetable_rooms rm ON rm.id=l.room_id AND rm.school_id=l.school_id
           JOIN ds_timetable_periods p ON p.id=l.period_id AND p.profile_id=l.profile_id
           JOIN ds_timetable_days d ON d.id=l.day_id AND d.profile_id=l.profile_id
           WHERE l.school_id=? AND l.profile_id=? AND l.status='scheduled'""" + where +
        " ORDER BY d.day_order,p.period_no,c.name,s.name",
        tuple(params),
    ).fetchall()
    advanced_sessions = _load_advanced_sessions(cur, school_id, profile_id, view_type, target_id)
    weekend_sessions = [row for row in advanced_sessions if row["is_weekend"]]
    remedial_sessions = [row for row in advanced_sessions if row["is_remedial"]]
    weekday_remedials = [row for row in remedial_sessions if not row["is_weekend"]]
    dated_instructional_sessions = [
        row for row in advanced_sessions
        if row.get("session_date") and row.get("schedule_layer") == "instructional" and not row["is_weekend"]
    ]
    weekend_groups = {}
    for row in weekend_sessions:
        label = row["rotation_label"] or "Weekend schedule"
        weekend_groups.setdefault(label, []).append(row)

    return {
        "title": title,
        "profile": profile,
        "view_type": view_type,
        "target": target,
        "days": days,
        "periods": periods,
        "breaks": breaks,
        "lessons": lessons,
        "allocation_classes": cur.execute(
            """SELECT DISTINCT ta.class_id,c.name class_name,c.stream
               FROM teacher_allocations ta
               JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
               JOIN ds_timetable_class_requirements r
                 ON r.school_id=ta.school_id AND r.class_id=ta.class_id
                AND r.subject_id=ta.subject_id AND r.teacher_id=ta.teacher_id
                AND r.profile_id=?
               WHERE ta.school_id=? ORDER BY c.name,c.stream""",
            (profile_id, school_id),
        ).fetchall(),
        "advanced_sessions": advanced_sessions,
        "weekend_sessions": weekend_sessions,
        "weekend_groups": weekend_groups,
        "remedial_sessions": remedial_sessions,
        "weekday_remedials": weekday_remedials,
        "dated_instructional_sessions": dated_instructional_sessions,
    }


def _load_advanced_sessions(cur, school_id: int, profile_id: int, view_type: str, target_id: int):
    """Load normalized dated/weekly sessions for consolidated remedial/weekend sheets."""
    from app.timetable.advanced_setup import expand_calendar_occurrences

    conditions = []
    params = [school_id, profile_id]
    if view_type == "class":
        conditions.append("EXISTS(SELECT 1 FROM ds_timetable_session_classes sc WHERE sc.session_id=s.id AND sc.school_id=s.school_id AND sc.class_id=?)")
        params.append(target_id)
    elif view_type == "student":
        student = cur.execute(
            "SELECT class_id FROM students WHERE id=? AND school_id=?",
            (target_id, school_id),
        ).fetchone()
        class_id = int(student["class_id"]) if student and student["class_id"] else 0
        if class_id:
            conditions.append("(EXISTS(SELECT 1 FROM ds_timetable_session_classes sc WHERE sc.session_id=s.id AND sc.school_id=s.school_id AND sc.class_id=?) OR EXISTS(SELECT 1 FROM ds_timetable_session_learners sl WHERE sl.session_id=s.id AND sl.school_id=s.school_id AND sl.student_id=?))")
            params.extend((class_id, target_id))
        else:
            conditions.append("EXISTS(SELECT 1 FROM ds_timetable_session_learners sl WHERE sl.session_id=s.id AND sl.school_id=s.school_id AND sl.student_id=?)")
            params.append(target_id)
    elif view_type == "teacher":
        conditions.append("EXISTS(SELECT 1 FROM ds_timetable_session_teachers st WHERE st.session_id=s.id AND st.school_id=s.school_id AND st.teacher_id=?)")
        params.append(target_id)
    elif view_type == "room":
        conditions.append("s.room_id=?")
        params.append(target_id)
    where = (" AND " + " AND ".join(conditions)) if conditions else ""
    rows = cur.execute(
        """SELECT s.*,d.day_code,d.day_name,sub.name subject_name,rm.name room_name,
                  p.name programme_name
           FROM ds_timetable_sessions s
           LEFT JOIN ds_timetable_days d ON d.id=s.day_id AND d.profile_id=s.profile_id
           LEFT JOIN subjects sub ON sub.id=s.subject_id AND sub.school_id=s.school_id
           LEFT JOIN ds_timetable_rooms rm ON rm.id=s.room_id AND rm.school_id=s.school_id
           LEFT JOIN ds_timetable_learning_programmes p ON p.id=s.programme_id AND p.profile_id=s.profile_id
           WHERE s.school_id=? AND s.profile_id=? AND s.status='scheduled'""" + where +
        " ORDER BY COALESCE(s.session_date,'9999-12-31'),s.start_time,s.id",
        tuple(params),
    ).fetchall()
    sessions = [dict(row) for row in rows]
    # Aggregate linked classes and teachers in Python instead of using
    # SQLite-only group_concat; this view must work with both SQLite and
    # the PostgreSQL production database.
    if sessions:
        session_ids = [int(row["id"]) for row in sessions]
        placeholders = ",".join("?" for _ in session_ids)
        class_rows = cur.execute(
            """SELECT sc.session_id,c.name,c.stream
               FROM ds_timetable_session_classes sc
               JOIN classes c ON c.id=sc.class_id AND c.school_id=sc.school_id
               WHERE sc.school_id=? AND sc.session_id IN (""" + placeholders + """)
               ORDER BY sc.session_id,c.name,c.stream""",
            (school_id, *session_ids),
        ).fetchall()
        teacher_rows = cur.execute(
            """SELECT st.session_id,t.name
               FROM ds_timetable_session_teachers st
               JOIN teachers t ON t.id=st.teacher_id AND t.school_id=st.school_id
               WHERE st.school_id=? AND st.session_id IN (""" + placeholders + """)
               ORDER BY st.session_id,t.name""",
            (school_id, *session_ids),
        ).fetchall()
        learner_rows = cur.execute(
            """SELECT sl.session_id,s.name
               FROM ds_timetable_session_learners sl
               JOIN students s ON s.id=sl.student_id AND s.school_id=sl.school_id
               WHERE sl.school_id=? AND sl.session_id IN (""" + placeholders + """)
               ORDER BY sl.session_id,s.name""",
            (school_id, *session_ids),
        ).fetchall()
        class_names = {}
        for linked in class_rows:
            label = str(linked["name"]) + ((" " + str(linked["stream"])) if linked["stream"] else "")
            class_names.setdefault(int(linked["session_id"]), []).append(label)
        teacher_names = {}
        for linked in teacher_rows:
            teacher_names.setdefault(int(linked["session_id"]), []).append(str(linked["name"]))
        learner_names = {}
        for linked in learner_rows:
            learner_names.setdefault(int(linked["session_id"]), []).append(str(linked["name"]))
        for session in sessions:
            session["learner_names"] = ", ".join(learner_names.get(int(session["id"]), []))
            session["class_names"] = ", ".join(class_names.get(int(session["id"]), []))
            if not session["class_names"] and session["learner_names"]:
                session["class_names"] = "Individual: " + session["learner_names"]
            session["teacher_names"] = ", ".join(teacher_names.get(int(session["id"]), []))
    dated = [str(row["session_date"]) for row in sessions
             if row["session_date"] and str(row.get("day_code") or "").upper() in {"SAT", "SUN"}]
    rotation_labels = {}
    if dated:
        occurrences = expand_calendar_occurrences(
            cur.connection, school_id, profile_id, min(dated), max(dated), include_closed=True
        )
        for occurrence in occurrences:
            rotations = occurrence.get("rotations", [])
            labels = []
            for rotation in rotations:
                week = rotation.get("week") or {}
                label = str(week.get("label") or (str(rotation.get("cycle_name") or "Weekend") + " " + str(week.get("week_number") or rotation.get("week_number") or ""))).strip()
                if label not in labels:
                    labels.append(label)
            rotation_labels[occurrence["date"]] = " / ".join(labels) if labels else ""
    profile_dates = cur.execute(
        "SELECT academic_start_date FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    from datetime import date, timedelta
    academic_start = date.fromisoformat(str(profile_dates["academic_start_date"])) if profile_dates and profile_dates["academic_start_date"] else None
    first_saturday = academic_start + timedelta(days=(5 - academic_start.weekday()) % 7) if academic_start else None
    for row in sessions:
        row["rotation_label"] = rotation_labels.get(str(row["session_date"]), "") if row["session_date"] else ""
        row["is_weekend"] = str(row.get("day_code") or "").upper() in {"SAT", "SUN"}
        row["is_remedial"] = str(row.get("schedule_layer") or "") == "additional_learning"
        if row["is_weekend"] and not row["rotation_label"] and row.get("session_date") and first_saturday:
            target = date.fromisoformat(str(row["session_date"]))
            weekend_number = max(0, (target - first_saturday).days // 7) % 2 + 1
            row["rotation_label"] = "Weekend " + str(weekend_number)
        elif row["is_weekend"] and not row["rotation_label"]:
            row["rotation_label"] = "Weekend schedule"
    return sessions
