"""Unified session creation and resource-conflict validation.

All new timetable layers (instructional, additional learning and activities)
share this engine. Classes and teachers are represented by join rows so one
session can serve combined classes and be delivered by a teaching team.
"""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Iterable

from app.timetable.setup import TimetableSetupError, _profile

_TIME_RE = re.compile(r"^(?:[01]\\d|2[0-3]):[0-5]\\d$")


def _unique_ids(values: Iterable[Any], field: str) -> list[int]:
    try:
        result = list(dict.fromkeys(int(value) for value in values if value is not None))
    except (TypeError, ValueError):
        raise TimetableSetupError(f"Invalid {field} selection.")
    if any(value <= 0 for value in result):
        raise TimetableSetupError(f"Invalid {field} selection.")
    return result


def _validate_resources(cur: Any, school_id: int, profile_id: int,
                         class_ids: list[int], teacher_ids: list[int],
                         learner_ids: list[int], room_id: int | None,
                         start: str, end: str, day_id: int | None,
                         session_date: str | None, period_id: int | None,
                         schedule_layer: str, session_type: str) -> None:
    if not class_ids and not learner_ids and schedule_layer == "instructional":
        raise TimetableSetupError("An instructional session must include at least one class or learner.")
    for class_id in class_ids:
        if not cur.execute(
            "SELECT id FROM classes WHERE id=? AND school_id=?",
            (class_id, school_id),
        ).fetchone():
            raise TimetableSetupError("A selected class does not belong to this school.")
    for teacher_id in teacher_ids:
        if not cur.execute(
            "SELECT id FROM teachers WHERE id=? AND school_id=?",
            (teacher_id, school_id),
        ).fetchone():
            raise TimetableSetupError("A selected teacher does not belong to this school.")
    if room_id is not None:
        room = cur.execute(
            "SELECT id,capacity,is_active FROM ds_timetable_rooms WHERE id=? AND school_id=?",
            (room_id, school_id),
        ).fetchone()
        if not room or not int(room["is_active"] or 0):
            raise TimetableSetupError("Select an active room belonging to this school.")
        if room["capacity"] is not None:
            enrolled = len(learner_ids)
            if class_ids:
                marks = ",".join("?" for _ in class_ids)
                count = cur.execute(
                    f"SELECT COUNT(*) AS n FROM students WHERE school_id=? AND class_id IN ({marks})",
                    (school_id, *class_ids),
                ).fetchone()
                enrolled = max(enrolled, int(count["n"] or 0))
            if enrolled > int(room["capacity"]):
                raise TimetableSetupError(
                    f"The selected room holds {int(room['capacity'])}, but the combined group has {enrolled} learners."
                )
    if schedule_layer == "school_activity":
        activity = cur.execute(
            "SELECT id,requires_teacher,requires_room FROM ds_timetable_activity_types WHERE school_id=? AND code=?",
            (school_id, session_type),
        ).fetchone()
        if activity:
            if int(activity["requires_teacher"] or 0) and not teacher_ids:
                raise TimetableSetupError("This activity type requires at least one assigned teacher.")
            if int(activity["requires_room"] or 0) and room_id is None:
                raise TimetableSetupError("This activity type requires a venue.")
    if day_id is not None:
        if not cur.execute(
            "SELECT id FROM ds_timetable_days WHERE id=? AND school_id=? AND profile_id=?",
            (day_id, school_id, profile_id),
        ).fetchone():
            raise TimetableSetupError("The selected day is outside this timetable profile.")
    for learner_id in learner_ids:
        if not cur.execute(
            "SELECT id FROM students WHERE id=? AND school_id=?",
            (learner_id, school_id),
        ).fetchone():
            raise TimetableSetupError("A selected learner does not belong to this school.")
    if period_id is not None:
        period = cur.execute(
            "SELECT id,start_time,end_time FROM ds_timetable_periods WHERE id=? AND school_id=? AND profile_id=?",
            (period_id, school_id, profile_id),
        ).fetchone()
        if not period:
            raise TimetableSetupError("The selected period is outside this timetable profile.")
        if (start, end) != (str(period["start_time"]), str(period["end_time"])):
            raise TimetableSetupError("Session times must match the selected configured period.")
        if day_id is not None:
            for teacher_id in teacher_ids:
                availability = cur.execute(
                    """SELECT availability FROM ds_timetable_teacher_availability
                       WHERE school_id=? AND profile_id=? AND teacher_id=? AND day_id=? AND period_id=?""",
                    (school_id, profile_id, teacher_id, day_id, period_id),
                ).fetchone()
                if availability and str(availability["availability"]).lower() == "unavailable":
                    raise TimetableSetupError(f"Teacher {teacher_id} is marked unavailable for this day and period.")
    if session_date:
        try:
            parsed = date.fromisoformat(session_date)
        except ValueError:
            raise TimetableSetupError("Enter a valid session date.")
        profile = cur.execute(
            "SELECT academic_start_date,academic_end_date FROM ds_timetable_profiles WHERE id=? AND school_id=?",
            (profile_id, school_id),
        ).fetchone()
        if profile["academic_start_date"] and parsed < date.fromisoformat(str(profile["academic_start_date"])):
            raise TimetableSetupError("The session date is before the academic period.")
        if profile["academic_end_date"] and parsed > date.fromisoformat(str(profile["academic_end_date"])):
            raise TimetableSetupError("The session date is after the academic period.")


def find_session_conflicts(connection: Any, school_id: int, profile_id: int,
                           start_time: str, end_time: str,
                           class_ids: Iterable[int] = (),
                           teacher_ids: Iterable[int] = (),
                           learner_ids: Iterable[int] = (),
                           room_id: int | None = None,
                           day_id: int | None = None,
                           session_date: str | None = None,
                           exclude_session_id: int | None = None) -> list[dict[str, Any]]:
    """Return every overlapping new-engine session sharing a resource."""
    classes = _unique_ids(class_ids, "class")
    teachers = _unique_ids(teacher_ids, "teacher")
    learners = _unique_ids(learner_ids, "learner")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    conflicts: dict[int, dict[str, Any]] = {}

    def collect(sql: str, params: tuple[Any, ...], reason: str) -> None:
        for row in cur.execute(sql, params).fetchall():
            sid = int(row["id"])
            if sid not in conflicts:
                conflicts[sid] = {
                    "session_id": sid, "start_time": row["start_time"],
                    "end_time": row["end_time"], "session_type": row["session_type"],
                    "schedule_layer": row["schedule_layer"], "reasons": [],
                }
            if reason not in conflicts[sid]["reasons"]:
                conflicts[sid]["reasons"].append(reason)

    base = """SELECT DISTINCT s.id,s.start_time,s.end_time,s.session_type,s.schedule_layer
              FROM ds_timetable_sessions s
              WHERE s.school_id=? AND s.profile_id=?
                AND s.start_time < ? AND s.end_time > ?
                AND s.status NOT IN ('cancelled','void')"""
    params: tuple[Any, ...] = (school_id, profile_id, end_time, start_time)
    if exclude_session_id is not None:
        base += " AND s.id<>?"
        params += (exclude_session_id,)
    if session_date:
        base += " AND (s.session_date=? OR (s.session_date IS NULL AND s.day_id=?))"
        params += (session_date, day_id if day_id is not None else -1)
    elif day_id is not None:
        base += " AND s.day_id=? AND s.session_date IS NULL"
        params += (day_id,)
    else:
        base += " AND s.session_date IS NULL"
    for value in classes:
        collect(base + """ AND EXISTS(SELECT 1 FROM ds_timetable_session_classes x
                    WHERE x.session_id=s.id AND x.school_id=s.school_id AND x.class_id=?)""",
                params + (value,), f"class:{value}")
    for value in teachers:
        collect(base + """ AND EXISTS(SELECT 1 FROM ds_timetable_session_teachers x
                    WHERE x.session_id=s.id AND x.school_id=s.school_id AND x.teacher_id=?)""",
                params + (value,), f"teacher:{value}")
    for value in learners:
        collect(base + """ AND EXISTS(SELECT 1 FROM ds_timetable_session_learners x
                    WHERE x.session_id=s.id AND x.school_id=s.school_id AND x.student_id=?)""",
                params + (value,), f"learner:{value}")
    if room_id is not None:
        collect(base + " AND s.room_id=?", params + (room_id,), f"room:{room_id}")
    return list(conflicts.values())


def create_teaching_group(connection: Any, school_id: int, profile_id: int,
                          name: str, class_ids: Iterable[int],
                          group_type: str = "combined_class",
                          subject_id: int | None = None,
                          notes: str = "") -> int:
    name = (name or "").strip()
    classes = _unique_ids(class_ids, "class")
    if not name or len(classes) < 2:
        raise TimetableSetupError("A combined teaching group needs a name and at least two classes.")
    if group_type not in {"combined_class", "elective", "remedial_group", "activity_group"}:
        raise TimetableSetupError("Choose a valid teaching group type.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    for class_id in classes:
        if not cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?", (class_id, school_id)).fetchone():
            raise TimetableSetupError("Every class in the group must belong to this school.")
    cur.execute(
        """INSERT INTO ds_timetable_teaching_groups
           (school_id,profile_id,name,group_type,subject_id,notes)
           VALUES(?,?,?,?,?,?)""",
        (school_id, profile_id, name, group_type, subject_id, (notes or "").strip()),
    )
    group = cur.execute(
        "SELECT id FROM ds_timetable_teaching_groups WHERE school_id=? AND profile_id=? AND name=?",
        (school_id, profile_id, name),
    ).fetchone()
    group_id = int(group["id"])
    try:
        for class_id in classes:
            cur.execute(
                """INSERT INTO ds_timetable_teaching_group_classes
                   (school_id,profile_id,teaching_group_id,class_id) VALUES(?,?,?,?)""",
                (school_id, profile_id, group_id, class_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return group_id


def create_scheduled_session(connection: Any, school_id: int, profile_id: int,
                             start_time: str, end_time: str,
                             schedule_layer: str = "instructional",
                             session_type: str = "lesson",
                             class_ids: Iterable[int] = (),
                             teacher_ids: Iterable[int] = (),
                             learner_ids: Iterable[int] = (),
                             room_id: int | None = None,
                             day_id: int | None = None,
                             session_date: str | None = None,
                             period_id: int | None = None,
                             subject_id: int | None = None,
                             programme_id: int | None = None,
                             teaching_group_id: int | None = None,
                             duration_periods: int = 0,
                             created_by: str = "") -> int:
    start_time, end_time = (start_time or "").strip(), (end_time or "").strip()
    if not _TIME_RE.fullmatch(start_time) or not _TIME_RE.fullmatch(end_time) or start_time >= end_time:
        raise TimetableSetupError("Enter a valid start and end time in 24-hour HH:MM format.")
    if schedule_layer not in {"instructional", "additional_learning", "school_activity"}:
        raise TimetableSetupError("Choose a valid timetable layer.")
    if not session_type or len(session_type) > 40:
        raise TimetableSetupError("Choose a valid session type.")
    classes = _unique_ids(class_ids, "class")
    teachers = _unique_ids(teacher_ids, "teacher")
    learners = _unique_ids(learner_ids, "learner")
    room_id = int(room_id) if room_id is not None else None
    day_id = int(day_id) if day_id is not None else None
    period_id = int(period_id) if period_id is not None else None
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    _validate_resources(
        cur, school_id, profile_id, classes, teachers, learners, room_id,
        start_time, end_time, day_id, session_date, period_id,
        schedule_layer, session_type,
    )
    if teaching_group_id is not None:
        group = cur.execute(
            "SELECT id FROM ds_timetable_teaching_groups WHERE id=? AND school_id=? AND profile_id=? AND is_active=1",
            (int(teaching_group_id), school_id, profile_id),
        ).fetchone()
        if not group:
            raise TimetableSetupError("Select an active teaching group from this timetable profile.")
        group_classes = [int(r["class_id"]) for r in cur.execute(
            "SELECT class_id FROM ds_timetable_teaching_group_classes WHERE teaching_group_id=? AND school_id=?",
            (int(teaching_group_id), school_id),
        ).fetchall()]
        if classes and set(classes) != set(group_classes):
            raise TimetableSetupError("Session classes must match all classes in the selected combined group.")
        classes = group_classes
    conflicts = find_session_conflicts(
        connection, school_id, profile_id, start_time, end_time,
        classes, teachers, learners, room_id, day_id, session_date,
    )
    if conflicts:
        summary = "; ".join(
            f"session {item['session_id']} ({', '.join(item['reasons'])})"
            for item in conflicts
        )
        raise TimetableSetupError("This session conflicts with " + summary + ".")
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    try:
        cur.execute(
            """INSERT INTO ds_timetable_sessions
               (school_id,profile_id,schedule_layer,session_type,subject_id,programme_id,
                teaching_group_id,day_id,session_date,period_id,start_time,end_time,
                duration_periods,room_id,status,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (school_id, profile_id, schedule_layer, session_type, subject_id, programme_id,
             teaching_group_id, day_id, session_date, period_id, start_time, end_time,
             int(duration_periods), room_id, "scheduled", created_by, now, now),
        )
        row = cur.execute(
            """SELECT id FROM ds_timetable_sessions
               WHERE school_id=? AND profile_id=? AND created_at=? ORDER BY id DESC LIMIT 1""",
            (school_id, profile_id, now),
        ).fetchone()
        session_id = int(row["id"])
        for class_id in classes:
            cur.execute(
                "INSERT INTO ds_timetable_session_classes(school_id,profile_id,session_id,class_id) VALUES(?,?,?,?)",
                (school_id, profile_id, session_id, class_id),
            )
        for teacher_id in teachers:
            cur.execute(
                "INSERT INTO ds_timetable_session_teachers(school_id,profile_id,session_id,teacher_id,role) VALUES(?,?,?,?,?)",
                (school_id, profile_id, session_id, teacher_id, "lead" if teacher_id == teachers[0] else "support"),
            )
        for learner_id in learners:
            cur.execute(
                "INSERT INTO ds_timetable_session_learners(school_id,profile_id,session_id,student_id) VALUES(?,?,?,?)",
                (school_id, profile_id, session_id, learner_id),
            )
        connection.commit()
        return session_id
    except Exception:
        connection.rollback()
        raise
