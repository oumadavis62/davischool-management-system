"""Validated setup operations for DaviSchool timetable v2."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any


_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class TimetableSetupError(ValueError):
    """A user-correctable timetable configuration error."""


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _profile(cursor: Any, school_id: int, profile_id: int):
    row = cursor.execute(
        "SELECT id,status,academic_start_date,academic_end_date FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    if not row:
        raise TimetableSetupError("Select a timetable profile belonging to this school.")
    if str(row["status"] or "draft").lower() in ("published", "archived"):
        raise TimetableSetupError("This timetable profile is locked. Create or select a draft profile.")
    return row


def _time_range(start_time: str, end_time: str) -> tuple[str, str]:
    start = (start_time or "").strip()
    end = (end_time or "").strip()
    if not _TIME_RE.fullmatch(start) or not _TIME_RE.fullmatch(end):
        raise TimetableSetupError("Enter times in 24-hour HH:MM format.")
    if start >= end:
        raise TimetableSetupError("The end time must be later than the start time.")
    return start, end


def create_profile(connection: Any, school_id: int, name: str, academic_year: str, term: str, created_by: str = "", academic_start_date: str = "", academic_end_date: str = "") -> int:
    name, academic_year, term = (name or "").strip(), (academic_year or "").strip(), (term or "").strip()
    if not name or not academic_year or not term:
        raise TimetableSetupError("Profile name, academic year and term are required.")
    academic_start_date = (academic_start_date or "").strip()
    academic_end_date = (academic_end_date or "").strip()
    if academic_start_date or academic_end_date:
        try:
            start_date = datetime.strptime(academic_start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(academic_end_date, "%Y-%m-%d").date()
        except ValueError:
            raise TimetableSetupError("Enter valid academic start and end dates.")
        if end_date <= start_date:
            raise TimetableSetupError("Academic end date must be after the start date.")
    cur = connection.cursor()
    exists = cur.execute(
        "SELECT id FROM ds_timetable_profiles WHERE school_id=? AND academic_year=? AND term=? AND status<>'archived'",
        (school_id, academic_year, term),
    ).fetchone()
    if exists:
        raise TimetableSetupError("A timetable profile already exists for this academic year and term.")
    now = _now()
    cur.execute(
        """INSERT INTO ds_timetable_profiles
           (school_id,name,academic_year,term,status,academic_start_date,academic_end_date,created_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (school_id, name, academic_year, term, "draft", academic_start_date or None, academic_end_date or None, created_by, now, now),
    )
    row = cur.execute(
        "SELECT id FROM ds_timetable_profiles WHERE school_id=? AND academic_year=? AND term=? ORDER BY id DESC LIMIT 1",
        (school_id, academic_year, term),
    ).fetchone()
    connection.commit()
    return int(row["id"])


def save_day(connection: Any, school_id: int, profile_id: int, day_code: str, day_name: str, day_order: int, instructional: bool = True) -> None:
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    code, name = (day_code or "").strip().upper(), (day_name or "").strip()
    if not code or not name or not 1 <= int(day_order) <= 7:
        raise TimetableSetupError("Choose a valid day name and an order from 1 to 7.")
    existing = cur.execute(
        "SELECT id FROM ds_timetable_days WHERE school_id=? AND profile_id=? AND day_code=?",
        (school_id, profile_id, code),
    ).fetchone()
    if existing:
        cur.execute(
            "UPDATE ds_timetable_days SET day_name=?,day_order=?,is_instructional=? WHERE id=? AND school_id=?",
            (name, int(day_order), 1 if instructional else 0, existing["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_days
               (school_id,profile_id,day_code,day_name,day_order,is_instructional)
               VALUES(?,?,?,?,?,?)""",
            (school_id, profile_id, code, name, int(day_order), 1 if instructional else 0),
        )
    connection.commit()


def save_period(connection: Any, school_id: int, profile_id: int, period_no: int, label: str, start_time: str, end_time: str, period_type: str = "lesson") -> None:
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    start, end = _time_range(start_time, end_time)
    number, label = int(period_no), (label or "").strip()
    if not 1 <= number <= 30 or not label:
        raise TimetableSetupError("Period number must be 1–30 and its label is required.")
    if period_type not in ("lesson", "study", "assembly"):
        raise TimetableSetupError("Choose a valid period type.")
    overlap = cur.execute(
        """SELECT id FROM ds_timetable_periods
           WHERE school_id=? AND profile_id=? AND period_no<>?
             AND start_time < ? AND end_time > ? LIMIT 1""",
        (school_id, profile_id, number, end, start),
    ).fetchone()
    if overlap:
        raise TimetableSetupError("This period overlaps another configured period.")
    existing = cur.execute(
        "SELECT id FROM ds_timetable_periods WHERE school_id=? AND profile_id=? AND period_no=?",
        (school_id, profile_id, number),
    ).fetchone()
    values = (label, start, end, period_type, (int(end[:2])*60+int(end[3:]))-(int(start[:2])*60+int(start[3:])))
    if existing:
        cur.execute(
            """UPDATE ds_timetable_periods SET label=?,start_time=?,end_time=?,period_type=?,duration_minutes=?
               WHERE id=? AND school_id=?""",
            values + (existing["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_periods
               (school_id,profile_id,period_no,label,start_time,end_time,period_type,duration_minutes)
               VALUES(?,?,?,?,?,?,?,?)""",
            (school_id, profile_id, number) + values,
        )
    connection.commit()


def save_break(connection: Any, school_id: int, profile_id: int, break_no: int, label: str, start_time: str, end_time: str, applies_to: str = "all") -> None:
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    start, end = _time_range(start_time, end_time)
    number, label = int(break_no), (label or "").strip()
    if not 1 <= number <= 20 or not label:
        raise TimetableSetupError("Break number and name are required.")
    if applies_to not in ("all", "selected"):
        raise TimetableSetupError("Choose a valid break scope.")
    existing = cur.execute(
        "SELECT id FROM ds_timetable_breaks WHERE school_id=? AND profile_id=? AND break_no=?",
        (school_id, profile_id, number),
    ).fetchone()
    overlap = cur.execute(
        """SELECT id FROM ds_timetable_periods
           WHERE school_id=? AND profile_id=? AND start_time < ? AND end_time > ? LIMIT 1""",
        (school_id, profile_id, end, start),
    ).fetchone()
    if overlap:
        raise TimetableSetupError("A break cannot overlap a teaching period.")
    break_overlap = cur.execute(
        """SELECT id FROM ds_timetable_breaks
           WHERE school_id=? AND profile_id=? AND break_no<>?
             AND start_time < ? AND end_time > ? LIMIT 1""",
        (school_id, profile_id, number, end, start),
    ).fetchone()
    if break_overlap:
        raise TimetableSetupError("This break overlaps another configured break.")
    if existing:
        cur.execute(
            """UPDATE ds_timetable_breaks SET label=?,start_time=?,end_time=?,applies_to=?
               WHERE id=? AND school_id=?""",
            (label, start, end, applies_to, existing["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_breaks
               (school_id,profile_id,break_no,label,start_time,end_time,applies_to)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id, profile_id, number, label, start, end, applies_to),
        )
    connection.commit()



def save_calendar_exception(connection: Any, school_id: int, profile_id: int, exception_date: str, label: str, exception_type: str = "holiday", notes: str = "", instructional: bool = False) -> None:
    cur = connection.cursor()
    profile = _profile(cur, school_id, profile_id)
    date_value, label = (exception_date or "").strip(), (label or "").strip()
    try:
        from datetime import date
        parsed_date = date.fromisoformat(date_value)
    except ValueError:
        raise TimetableSetupError("Choose a valid calendar date.")
    if not label:
        raise TimetableSetupError("Calendar event name is required.")
    if exception_type not in ("holiday", "school_closure", "special_instructional_day", "event"):
        raise TimetableSetupError("Choose a valid calendar event type.")
    start_date, end_date = profile["academic_start_date"], profile["academic_end_date"]
    if start_date and parsed_date < date.fromisoformat(str(start_date)):
        raise TimetableSetupError("Calendar event is before the academic start date.")
    if end_date and parsed_date > date.fromisoformat(str(end_date)):
        raise TimetableSetupError("Calendar event is after the academic end date.")
    existing = cur.execute(
        """SELECT id FROM ds_timetable_calendar_exceptions
           WHERE school_id=? AND profile_id=? AND exception_date=? AND label=?""",
        (school_id, profile_id, date_value, label),
    ).fetchone()
    values = (exception_type, (notes or "").strip(), 1 if instructional else 0)
    if existing:
        cur.execute(
            """UPDATE ds_timetable_calendar_exceptions
               SET exception_type=?,notes=?,is_instructional=? WHERE id=? AND school_id=?""",
            values + (existing["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_calendar_exceptions
               (school_id,profile_id,exception_date,label,exception_type,notes,is_instructional)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id, profile_id, date_value, label) + values,
        )
    connection.commit()


def save_room(connection: Any, school_id: int, room_code: str, name: str, room_type: str = "classroom", capacity: int | None = None, description: str = "", equipment: str = "", suitable_for: str = "") -> None:
    code, name = (room_code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise TimetableSetupError("Room code and room name are required.")
    if room_type not in ("classroom", "laboratory", "library", "hall", "workshop", "sports", "other"):
        raise TimetableSetupError("Choose a valid room type.")
    if capacity is not None and int(capacity) < 1:
        raise TimetableSetupError("Room capacity must be at least one.")
    cur = connection.cursor()
    existing = cur.execute(
        "SELECT id FROM ds_timetable_rooms WHERE school_id=? AND room_code=?",
        (school_id, code),
    ).fetchone()
    if existing:
        cur.execute(
            """UPDATE ds_timetable_rooms SET name=?,room_type=?,capacity=?,description=?,equipment=?,suitable_for=?,is_active=1
               WHERE id=? AND school_id=?""",
            (name, room_type, capacity, (description or "").strip(), (equipment or "").strip(), (suitable_for or "").strip(), existing["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_rooms(school_id,room_code,name,room_type,capacity,description,equipment,suitable_for)
               VALUES(?,?,?,?,?,?,?,?)""",
            (school_id, code, name, room_type, capacity, (description or "").strip(), (equipment or "").strip(), (suitable_for or "").strip()),
        )
    connection.commit()


def save_teacher_availability(connection: Any, school_id: int, profile_id: int, teacher_id: int, day_id: int, period_id: int, availability: str, reason: str = "") -> None:
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    if availability not in ("available", "unavailable", "preferred"):
        raise TimetableSetupError("Choose available, unavailable or preferred.")
    teacher = cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?", (teacher_id, school_id)).fetchone()
    day = cur.execute("SELECT id FROM ds_timetable_days WHERE id=? AND profile_id=? AND school_id=?", (day_id, profile_id, school_id)).fetchone()
    period = cur.execute("SELECT id FROM ds_timetable_periods WHERE id=? AND profile_id=? AND school_id=?", (period_id, profile_id, school_id)).fetchone()
    if not teacher or not day or not period:
        raise TimetableSetupError("Teacher, day or period does not belong to this school's selected timetable.")
    old = cur.execute(
        """SELECT id FROM ds_timetable_teacher_availability
           WHERE school_id=? AND profile_id=? AND teacher_id=? AND day_id=? AND period_id=?""",
        (school_id, profile_id, teacher_id, day_id, period_id),
    ).fetchone()
    if old:
        cur.execute(
            "UPDATE ds_timetable_teacher_availability SET availability=?,reason=? WHERE id=? AND school_id=?",
            (availability, (reason or "").strip(), old["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_teacher_availability
               (school_id,profile_id,teacher_id,day_id,period_id,availability,reason)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id, profile_id, teacher_id, day_id, period_id, availability, (reason or "").strip()),
        )
    connection.commit()


def save_class_limits(connection: Any, school_id: int, profile_id: int,
                     class_id: int, max_lessons_per_week: int | None,
                     max_periods_per_day: int | None, notes: str = "") -> None:
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    target = cur.execute(
        "SELECT id FROM classes WHERE id=? AND school_id=?",
        (int(class_id), int(school_id)),
    ).fetchone()
    if not target:
        raise TimetableSetupError("Select a class or stream belonging to this school.")
    if max_lessons_per_week is not None and not 1 <= int(max_lessons_per_week) <= 100:
        raise TimetableSetupError("Maximum lessons per week must be between 1 and 100.")
    if max_periods_per_day is not None and not 1 <= int(max_periods_per_day) <= 30:
        raise TimetableSetupError("Maximum periods per day must be between 1 and 30.")
    if max_lessons_per_week is None and max_periods_per_day is None:
        raise TimetableSetupError("Set at least one class workload limit.")
    existing = cur.execute(
        """SELECT id FROM ds_timetable_class_limits
           WHERE school_id=? AND profile_id=? AND class_id=?""",
        (school_id, profile_id, class_id),
    ).fetchone()
    values = (max_lessons_per_week, max_periods_per_day, (notes or "").strip())
    if existing:
        cur.execute(
            """UPDATE ds_timetable_class_limits
               SET max_lessons_per_week=?,max_periods_per_day=?,notes=?,updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND school_id=?""",
            values + (existing["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_class_limits
               (school_id,profile_id,class_id,max_lessons_per_week,max_periods_per_day,notes)
               VALUES(?,?,?,?,?,?)""",
            (school_id, profile_id, class_id) + values,
        )
    connection.commit()


def save_class_requirement(connection: Any, school_id: int, profile_id: int, class_id: int, subject_id: int, teacher_id: int, lessons_per_week: int, duration_periods: int = 1, max_lessons_per_day: int | None = None, allow_double: bool = False) -> None:
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    if not 1 <= int(lessons_per_week) <= 30 or not 1 <= int(duration_periods) <= 4:
        raise TimetableSetupError("Weekly lessons must be 1–30 and lesson duration must be 1–4 periods.")
    if max_lessons_per_day is not None and not 1 <= int(max_lessons_per_day) <= 10:
        raise TimetableSetupError("Maximum lessons per day must be 1–10.")
    allocation = cur.execute(
        """SELECT id FROM teacher_allocations
           WHERE school_id=? AND class_id=? AND subject_id=? AND teacher_id=? LIMIT 1""",
        (school_id, class_id, subject_id, teacher_id),
    ).fetchone()
    if not allocation:
        raise TimetableSetupError("That teacher is not allocated to the selected class and subject.")
    old = cur.execute(
        """SELECT id FROM ds_timetable_class_requirements
           WHERE school_id=? AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=?""",
        (school_id, profile_id, class_id, subject_id, teacher_id),
    ).fetchone()
    values = (int(lessons_per_week), int(duration_periods), max_lessons_per_day, 1 if allow_double else 0)
    if old:
        cur.execute(
            """UPDATE ds_timetable_class_requirements
               SET lessons_per_week=?,duration_periods=?,max_lessons_per_day=?,allow_double=?
               WHERE id=? AND school_id=?""",
            values + (old["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_class_requirements
               (school_id,profile_id,class_id,subject_id,teacher_id,lessons_per_week,duration_periods,max_lessons_per_day,allow_double)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (school_id, profile_id, class_id, subject_id, teacher_id) + values,
        )
    connection.commit()


def save_subject_requirements(connection: Any, school_id: int, profile_id: int,
                              subject_ids: list[int], lessons_per_week: int,
                              duration_periods: int = 1,
                              max_lessons_per_day: int | None = None,
                              allow_double: bool = False) -> tuple[int, int, int]:
    """Apply selected subject loads to every allocated class/teacher combination.

    The user selects subjects, not individual allocations. Existing teacher
    allocations supply the class and teacher links required by the legacy
    timetable generator. Existing customized requirements are never replaced.
    Returns (selected_subject_count, created_count, preserved_count).
    """
    selected_subjects = sorted({int(value) for value in subject_ids})
    if not selected_subjects:
        raise TimetableSetupError("Select at least one subject.")
    if not 1 <= int(lessons_per_week) <= 30 or not 1 <= int(duration_periods) <= 4:
        raise TimetableSetupError("Choose a valid weekly lesson load and lesson duration.")
    if max_lessons_per_day is not None and not 1 <= int(max_lessons_per_day) <= 10:
        raise TimetableSetupError("Maximum lessons per day must be between 1 and 10.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    placeholders = ",".join("?" for _ in selected_subjects)
    rows = cur.execute(
        f"""SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id
            FROM teacher_allocations ta
            JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
            JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
            JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
            WHERE ta.school_id=? AND ta.subject_id IN ({placeholders})
            ORDER BY ta.subject_id,ta.class_id,ta.teacher_id""",
        (int(school_id), *selected_subjects),
    ).fetchall()
    if not rows:
        raise TimetableSetupError(
            "The selected subjects have no active class and teacher allocations in this school."
        )
    created = preserved = 0
    for row in rows:
        exists = cur.execute(
            """SELECT id FROM ds_timetable_class_requirements
               WHERE school_id=? AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=? LIMIT 1""",
            (school_id, profile_id, row["class_id"], row["subject_id"], row["teacher_id"]),
        ).fetchone()
        if exists:
            preserved += 1
            continue
        save_class_requirement(
            connection, school_id, profile_id, int(row["class_id"]),
            int(row["subject_id"]), int(row["teacher_id"]), int(lessons_per_week),
            int(duration_periods), max_lessons_per_day, allow_double,
        )
        created += 1
    return len(selected_subjects), created, preserved
