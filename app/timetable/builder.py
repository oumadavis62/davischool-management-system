"""Conflict-safe manual timetable placement operations."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.timetable.setup import TimetableSetupError, _profile
from app.timetable.session_engine import _validate_constraints


def _period_span(cursor: Any, school_id: int, profile_id: int, period_id: int, duration: int):
    periods = cursor.execute(
        """SELECT * FROM ds_timetable_periods
           WHERE school_id=? AND profile_id=? ORDER BY period_no,id""",
        (school_id, profile_id),
    ).fetchall()
    start_index = next((i for i, row in enumerate(periods) if int(row["id"]) == int(period_id)), None)
    if start_index is None:
        raise TimetableSetupError("Select a teaching period from this timetable profile.")
    span = periods[start_index:start_index + int(duration)]
    if len(span) != int(duration):
        raise TimetableSetupError("There are not enough consecutive periods for this lesson.")
    for index, period in enumerate(span):
        if str(period["period_type"] or "lesson") != "lesson":
            raise TimetableSetupError("Lessons can only be placed in teaching periods.")
        if index:
            previous = span[index - 1]
            if int(period["period_no"]) != int(previous["period_no"]) + 1 or str(previous["end_time"]) != str(period["start_time"]):
                raise TimetableSetupError("A double or extended lesson must use consecutive periods without a break.")
    return span


def _overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    return str(start_a) < str(end_b) and str(end_a) > str(start_b)


def _placement_context(cursor: Any, school_id: int, profile_id: int, class_id: int, subject_id: int, teacher_id: int, day_id: int, period_id: int, room_id: int | None, exclude_lesson_id: int = 0):
    _profile(cursor, school_id, profile_id)
    day = cursor.execute(
        """SELECT * FROM ds_timetable_days
           WHERE id=? AND school_id=? AND profile_id=? AND is_instructional=1""",
        (day_id, school_id, profile_id),
    ).fetchone()
    if not day:
        raise TimetableSetupError("Choose an instructional day in the selected timetable profile.")
    allocation = cursor.execute(
        """SELECT ta.id FROM teacher_allocations ta
           JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
           JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
           JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
           WHERE ta.school_id=? AND ta.class_id=? AND ta.subject_id=? AND ta.teacher_id=? LIMIT 1""",
        (school_id, class_id, subject_id, teacher_id),
    ).fetchone()
    if not allocation:
        raise TimetableSetupError("The selected teacher is not allocated to this class and subject.")
    requirement = cursor.execute(
        """SELECT * FROM ds_timetable_class_requirements
           WHERE school_id=? AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=?""",
        (school_id, profile_id, class_id, subject_id, teacher_id),
    ).fetchone()
    if not requirement:
        raise TimetableSetupError("Set the weekly lesson requirement for this class, subject and teacher before scheduling it.")
    duration = int(requirement["duration_periods"] or 1)
    span = _period_span(cursor, school_id, profile_id, period_id, duration)
    first, last = span[0], span[-1]
    _validate_constraints(
        cursor, school_id, profile_id, "instructional", "lesson",
        subject_id, [class_id], [teacher_id], room_id, day_id, period_id,
        str(first["start_time"]), str(last["end_time"]), None,
    )
    if room_id:
        room = cursor.execute(
            "SELECT id FROM ds_timetable_rooms WHERE id=? AND school_id=? AND is_active=1",
            (room_id, school_id),
        ).fetchone()
        if not room:
            raise TimetableSetupError("Select an active room belonging to this school.")
    for period in span:
        unavailable = cursor.execute(
            """SELECT id FROM ds_timetable_teacher_availability
               WHERE school_id=? AND profile_id=? AND teacher_id=? AND day_id=? AND period_id=?
                 AND availability='unavailable' LIMIT 1""",
            (school_id, profile_id, teacher_id, day_id, period["id"]),
        ).fetchone()
        if unavailable:
            raise TimetableSetupError("The selected teacher is unavailable during this lesson.")
    breaks = cursor.execute(
        """SELECT label,start_time,end_time FROM ds_timetable_breaks
           WHERE school_id=? AND profile_id=?""",
        (school_id, profile_id),
    ).fetchall()
    for item in breaks:
        if _overlap(first["start_time"], last["end_time"], item["start_time"], item["end_time"]):
            raise TimetableSetupError("This lesson overlaps the configured " + str(item["label"]) + " break.")
    existing = cursor.execute(
        """SELECT l.* FROM ds_timetable_lessons l
           WHERE l.school_id=? AND l.profile_id=? AND l.day_id=? AND l.status='scheduled'
             AND l.id<>?""",
        (school_id, profile_id, day_id, exclude_lesson_id),
    ).fetchall()
    max_per_day = int(requirement["max_lessons_per_day"]) if requirement["max_lessons_per_day"] is not None else 0
    if max_per_day:
        same_subject_day = sum(
            1 for lesson in existing
            if int(lesson["class_id"]) == int(class_id)
            and int(lesson["subject_id"]) == int(subject_id)
            and int(lesson["teacher_id"]) == int(teacher_id)
        )
        if same_subject_day >= max_per_day:
            raise TimetableSetupError("The configured maximum lessons for this subject on the selected day has been reached.")
    for lesson in existing:
        existing_span = _period_span(
            cursor, school_id, profile_id, int(lesson["period_id"]), int(lesson["duration_periods"] or 1)
        )
        if not _overlap(first["start_time"], last["end_time"], existing_span[0]["start_time"], existing_span[-1]["end_time"]):
            continue
        if int(lesson["class_id"]) == int(class_id):
            raise TimetableSetupError("This class already has a lesson during the selected time.")
        if int(lesson["teacher_id"]) == int(teacher_id):
            raise TimetableSetupError("This teacher is already teaching another class during the selected time.")
        if room_id and lesson["room_id"] is not None and int(lesson["room_id"]) == int(room_id):
            raise TimetableSetupError("This room is already booked during the selected time.")
    if not exclude_lesson_id:
        scheduled_count = cursor.execute(
            """SELECT COUNT(*) AS total FROM ds_timetable_lessons
               WHERE school_id=? AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=? AND status='scheduled'""",
            (school_id, profile_id, class_id, subject_id, teacher_id),
        ).fetchone()
        if int(scheduled_count["total"] or 0) >= int(requirement["lessons_per_week"] or 0):
            raise TimetableSetupError("The configured weekly lesson requirement has already been fully scheduled.")
    return requirement, span


def _log_change(cursor: Any, school_id: int, profile_id: int, lesson_id: int, action: str, before: Any, after: Any, changed_by: str):
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor.execute(
        """INSERT INTO ds_timetable_change_log
           (school_id,profile_id,lesson_id,action,before_json,after_json,changed_by,changed_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            school_id, profile_id, lesson_id, action,
            json.dumps(dict(before) if before else None, default=str, sort_keys=True),
            json.dumps(dict(after) if after else None, default=str, sort_keys=True),
            changed_by, now,
        ),
    )


def place_lesson(connection: Any, school_id: int, profile_id: int, class_id: int, subject_id: int, teacher_id: int, day_id: int, period_id: int, room_id: int | None = None, created_by: str = "") -> int:
    cur = connection.cursor()
    requirement, span = _placement_context(
        cur, school_id, profile_id, class_id, subject_id, teacher_id, day_id, period_id, room_id
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cur.execute(
        """INSERT INTO ds_timetable_lessons
           (school_id,profile_id,class_id,subject_id,teacher_id,room_id,day_id,period_id,duration_periods,status,created_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            school_id, profile_id, class_id, subject_id, teacher_id, room_id, day_id, period_id,
            len(span), "scheduled", created_by, now, now,
        ),
    )
    lesson_id = int(cur.lastrowid or 0)
    if not lesson_id:
        row = cur.execute(
            """SELECT id FROM ds_timetable_lessons
               WHERE school_id=? AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=?
                 AND day_id=? AND period_id=? ORDER BY id DESC LIMIT 1""",
            (school_id, profile_id, class_id, subject_id, teacher_id, day_id, period_id),
        ).fetchone()
        lesson_id = int(row["id"])
    after = cur.execute("SELECT * FROM ds_timetable_lessons WHERE id=? AND school_id=?", (lesson_id, school_id)).fetchone()
    _log_change(cur, school_id, profile_id, lesson_id, "LESSON_CREATE", None, after, created_by)
    connection.commit()
    return lesson_id


def move_lesson(connection: Any, school_id: int, profile_id: int, lesson_id: int, day_id: int, period_id: int, changed_by: str = "", room_id: int | None = None) -> None:
    cur = connection.cursor()
    existing = cur.execute(
        "SELECT * FROM ds_timetable_lessons WHERE id=? AND school_id=? AND profile_id=? AND status='scheduled'",
        (lesson_id, school_id, profile_id),
    ).fetchone()
    if not existing:
        raise TimetableSetupError("The selected lesson no longer exists in this timetable.")
    requirement, span = _placement_context(
        cur, school_id, profile_id, int(existing["class_id"]), int(existing["subject_id"]),
        int(existing["teacher_id"]), day_id, period_id,
        room_id if room_id is not None else (int(existing["room_id"]) if existing["room_id"] is not None else None),
        exclude_lesson_id=lesson_id,
    )
    before = dict(existing)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cur.execute(
        "UPDATE ds_timetable_lessons SET day_id=?,period_id=?,room_id=?,duration_periods=?,generation_run_id=NULL,updated_at=? WHERE id=? AND school_id=? AND profile_id=?",
        (day_id, period_id, room_id if room_id is not None else existing["room_id"], len(span), now, lesson_id, school_id, profile_id),
    )
    after = cur.execute("SELECT * FROM ds_timetable_lessons WHERE id=? AND school_id=?", (lesson_id, school_id)).fetchone()
    _log_change(cur, school_id, profile_id, lesson_id, "LESSON_MOVE", before, after, changed_by)
    connection.commit()


def delete_lesson(connection: Any, school_id: int, profile_id: int, lesson_id: int, changed_by: str = "") -> None:
    cur = connection.cursor()
    existing = cur.execute(
        "SELECT * FROM ds_timetable_lessons WHERE id=? AND school_id=? AND profile_id=?",
        (lesson_id, school_id, profile_id),
    ).fetchone()
    if not existing:
        raise TimetableSetupError("The selected lesson no longer exists in this timetable.")
    _log_change(cur, school_id, profile_id, lesson_id, "LESSON_DELETE", existing, None, changed_by)
    cur.execute(
        "DELETE FROM ds_timetable_lessons WHERE id=? AND school_id=? AND profile_id=?",
        (lesson_id, school_id, profile_id),
    )
    connection.commit()



def place_advanced_requirement_session(connection: Any, school_id: int, profile_id: int,
                                       requirement_id: int, session_no: int,
                                       day_id: int, period_id: int,
                                       room_id: int | None = None,
                                       created_by: str = "") -> int:
    """Manually place one normalized requirement pattern through the shared validator."""
    from app.timetable.session_engine import create_scheduled_session
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    requirement = cur.execute(
        """SELECT * FROM ds_timetable_scheduling_requirements
           WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
        (requirement_id, school_id, profile_id),
    ).fetchone()
    if not requirement:
        raise TimetableSetupError("Select an active scheduling requirement from this timetable profile.")
    pattern = cur.execute(
        """SELECT * FROM ds_timetable_scheduling_patterns
           WHERE school_id=? AND profile_id=? AND requirement_id=? AND session_no=?""",
        (school_id, profile_id, requirement_id, session_no),
    ).fetchone()
    if not pattern:
        raise TimetableSetupError("Select a configured session number from this requirement's weekly pattern.")
    if requirement["schedule_layer"] != "instructional":
        raise TimetableSetupError("This manual period-grid action supports instructional sessions; use the programme scheduler for additional learning and activities.")
    span = _period_span(cur, school_id, profile_id, period_id, int(pattern["duration_periods"] or 1))
    if pattern["preferred_day_id"] is not None and int(pattern["preferred_day_id"]) != int(day_id):
        raise TimetableSetupError("This session pattern is assigned to a different preferred day.")
    return create_scheduled_session(
        connection, school_id, profile_id,
        str(span[0]["start_time"]), str(span[-1]["end_time"]),
        schedule_layer="instructional", session_type=str(requirement["session_type"]),
        room_id=room_id, day_id=day_id, period_id=period_id,
        subject_id=int(requirement["subject_id"]) if requirement["subject_id"] is not None else None,
        programme_id=int(requirement["programme_id"]) if requirement["programme_id"] is not None else None,
        teaching_group_id=int(requirement["teaching_group_id"]) if requirement["teaching_group_id"] is not None else None,
        duration_periods=len(span), scheduling_requirement_id=requirement_id,
        pattern_session_no=session_no, created_by=created_by,
    )
