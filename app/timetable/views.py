"""Read-only school, class, teacher and room timetable views."""
from __future__ import annotations

from typing import Any

from app.timetable.setup import TimetableSetupError


def get_timetable_view(connection: Any, school_id: int, profile_id: int, view_type: str = "school", target_id: int = 0) -> dict:
    if view_type not in ("school", "class", "teacher", "room"):
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
           WHERE school_id=? AND profile_id=? ORDER BY period_no,id""",
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
        """SELECT l.*,c.name class_name,c.stream,s.name subject_name,t.name teacher_name,
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
    weekend_groups = {}
    for row in weekend_sessions:
        label = row["rotation_label"] or ("Weekend " + ("1" if row.get("session_date") and __import__("datetime").date.fromisoformat(str(row["session_date"])).isocalendar().week % 2 else "2"))
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
        "advanced_sessions": advanced_sessions,
        "weekend_sessions": weekend_sessions,
        "weekend_groups": weekend_groups,
        "remedial_sessions": remedial_sessions,
        "weekday_remedials": weekday_remedials,
    }


def _load_advanced_sessions(cur, school_id: int, profile_id: int, view_type: str, target_id: int):
    """Load normalized dated/weekly sessions for consolidated remedial/weekend sheets."""
    from app.timetable.advanced_setup import expand_calendar_occurrences

    conditions = []
    params = [school_id, profile_id]
    if view_type == "class":
        conditions.append("EXISTS(SELECT 1 FROM ds_timetable_session_classes sc WHERE sc.session_id=s.id AND sc.school_id=s.school_id AND sc.class_id=?)")
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
                  p.name programme_name,
                  (SELECT group_concat(c.name || CASE WHEN COALESCE(c.stream,'')='' THEN '' ELSE ' ' || c.stream END, ', ')
                   FROM ds_timetable_session_classes sc JOIN classes c ON c.id=sc.class_id AND c.school_id=sc.school_id
                   WHERE sc.session_id=s.id AND sc.school_id=s.school_id) class_names,
                  (SELECT group_concat(t.name, ', ')
                   FROM ds_timetable_session_teachers st JOIN teachers t ON t.id=st.teacher_id AND t.school_id=st.school_id
                   WHERE st.session_id=s.id AND st.school_id=s.school_id) teacher_names
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
    dated = [str(row["session_date"]) for row in sessions if row["session_date"]]
    rotation_labels = {}
    if dated:
        occurrences = expand_calendar_occurrences(
            cur.connection, school_id, profile_id, min(dated), max(dated), include_closed=True
        )
        for occurrence in occurrences:
            rotations = occurrence.get("rotations", [])
            labels = []
            for rotation in rotations:
                label = str(rotation.get("label") or ("Weekend " + str(rotation.get("week_number"))))
                if label not in labels:
                    labels.append(label)
            rotation_labels[occurrence["date"]] = " / ".join(labels) if labels else ""
    for row in sessions:
        row["rotation_label"] = rotation_labels.get(str(row["session_date"]), "") if row["session_date"] else ""
        row["is_weekend"] = str(row.get("day_code") or "").upper() in {"SAT", "SUN"}
        row["is_remedial"] = str(row.get("schedule_layer") or "") == "additional_learning"
    return sessions
