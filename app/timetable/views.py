"""Read-only school, class, teacher and room timetable views."""
from __future__ import annotations

from typing import Any

from app.timetable.setup import TimetableSetupError, _profile


def get_timetable_view(connection: Any, school_id: int, profile_id: int, view_type: str = "school", target_id: int = 0) -> dict:
    if view_type not in ("school", "class", "teacher", "room"):
        raise TimetableSetupError("Choose a valid timetable view.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
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
    return {
        "title": title,
        "view_type": view_type,
        "target": target,
        "days": days,
        "periods": periods,
        "lessons": lessons,
    }
