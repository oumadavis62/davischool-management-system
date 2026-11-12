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
    if str(row["status"] or "draft").lower() in ("published", "pending_approval", "archived"):
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


def create_profile(connection: Any, school_id: int, name: str, academic_year: str, term: str, created_by: str = "", academic_start_date: str = "", academic_end_date: str = "", profile_type: str = "main") -> int:
    name, academic_year, term = (name or "").strip(), (academic_year or "").strip(), (term or "").strip()
    if not name or not academic_year or not term:
        raise TimetableSetupError("Profile name, academic year and term are required.")
    profile_type = (profile_type or "main").strip().lower()
    if profile_type not in {"main", "weekend", "remedial", "special"}:
        raise TimetableSetupError("Choose a valid timetable programme type.")
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
    if profile_type == "main":
        exists = cur.execute(
            "SELECT id FROM ds_timetable_profiles WHERE school_id=? AND academic_year=? AND term=? AND profile_type='main' AND status<>'archived'",
            (school_id, academic_year, term),
        ).fetchone()
        if exists:
            raise TimetableSetupError("A main school timetable already exists for this academic year and term. Create a revision from its published profile instead.")
    else:
        exists = cur.execute(
            """SELECT p.id FROM ds_timetable_profiles p
               LEFT JOIN ds_timetable_profiles root
                 ON root.id=COALESCE(p.revision_of_profile_id,p.id)
               WHERE p.school_id=? AND p.academic_year=? AND p.term=?
                 AND p.profile_type=? AND root.name=? AND p.status<>'archived'""",
            (school_id, academic_year, term, profile_type, name),
        ).fetchone()
        if exists:
            raise TimetableSetupError("A timetable with this name and programme type already exists for this academic year and term.")
    now = _now()
    cur.execute(
        """INSERT INTO ds_timetable_profiles
           (school_id,name,academic_year,term,profile_type,status,academic_start_date,academic_end_date,created_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (school_id, name, academic_year, term, profile_type, "draft", academic_start_date or None, academic_end_date or None, created_by, now, now),
    )
    row = cur.execute(
        "SELECT id FROM ds_timetable_profiles WHERE school_id=? AND academic_year=? AND term=? AND profile_type=? AND created_at=? ORDER BY id DESC LIMIT 1",
        (school_id, academic_year, term, profile_type, now),
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


def save_period(connection: Any, school_id: int, profile_id: int, period_no: int, label: str, start_time: str, end_time: str, period_type: str = "lesson", period_id: int | None = None) -> None:
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    start, end = _time_range(start_time, end_time)
    number, label = int(period_no), (label or "").strip()
    if not 1 <= number <= 30 or not label:
        raise TimetableSetupError("Period number must be 1–30 and its label is required.")
    if period_type not in ("lesson", "study", "assembly"):
        raise TimetableSetupError("Choose a valid period type.")

    existing = None
    if period_id is not None:
        existing = cur.execute(
            "SELECT id FROM ds_timetable_periods WHERE id=? AND school_id=? AND profile_id=?",
            (int(period_id), school_id, profile_id),
        ).fetchone()
        if not existing:
            raise TimetableSetupError("The period being edited no longer exists in this timetable profile. Refresh and try again.")

    duplicate = cur.execute(
        """SELECT id FROM ds_timetable_periods
           WHERE school_id=? AND profile_id=? AND period_no=? AND id<>?
           LIMIT 1""",
        (school_id, profile_id, number, int(existing["id"]) if existing else -1),
    ).fetchone()
    if duplicate:
        raise TimetableSetupError("That period number is already assigned. Choose a different number.")

    overlap = cur.execute(
        """SELECT id FROM ds_timetable_periods
           WHERE school_id=? AND profile_id=? AND id<>?
             AND start_time < ? AND end_time > ? LIMIT 1""",
        (school_id, profile_id, int(existing["id"]) if existing else -1, end, start),
    ).fetchone()
    if overlap:
        raise TimetableSetupError("This period overlaps another configured period.")

    duration = (int(end[:2])*60+int(end[3:]))-(int(start[:2])*60+int(start[3:]))
    if existing:
        cur.execute(
            """UPDATE ds_timetable_periods
               SET period_no=?,label=?,start_time=?,end_time=?,period_type=?,duration_minutes=?
               WHERE id=? AND school_id=? AND profile_id=?""",
            (number, label, start, end, period_type, duration, existing["id"], school_id, profile_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_periods
               (school_id,profile_id,period_no,label,start_time,end_time,period_type,duration_minutes)
               VALUES(?,?,?,?,?,?,?,?)""",
            (school_id, profile_id, number, label, start, end, period_type, duration),
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


def save_room(connection: Any, school_id: int, room_code: str, name: str, room_type: str = "classroom", capacity: int | None = None, description: str = "", equipment: str = "", suitable_for: str = "", allocation_mode: str = "shared", assigned_class_id: int | None = None) -> None:
    code, name = (room_code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise TimetableSetupError("Room code and room name are required.")
    if room_type not in ("classroom", "laboratory", "library", "hall", "workshop", "sports", "other"):
        raise TimetableSetupError("Choose a valid room type.")
    if capacity is not None and int(capacity) < 1:
        raise TimetableSetupError("Room capacity must be at least one.")
    allocation_mode = (allocation_mode or "shared").strip().lower()
    if allocation_mode not in ("shared", "dedicated"):
        raise TimetableSetupError("Choose shared or dedicated classroom allocation.")
    if allocation_mode == "dedicated" and assigned_class_id is None:
        raise TimetableSetupError("Choose the class permanently assigned to this dedicated room.")
    if allocation_mode == "shared":
        assigned_class_id = None
    if assigned_class_id is not None:
        assigned_class_id = int(assigned_class_id)
        if not connection.cursor().execute(
            "SELECT id FROM classes WHERE id=? AND school_id=?",
            (assigned_class_id, school_id),
        ).fetchone():
            raise TimetableSetupError("The dedicated room class must belong to this school.")
    cur = connection.cursor()
    existing = cur.execute(
        "SELECT id FROM ds_timetable_rooms WHERE school_id=? AND room_code=?",
        (school_id, code),
    ).fetchone()
    if existing:
        cur.execute(
            """UPDATE ds_timetable_rooms SET name=?,room_type=?,capacity=?,description=?,equipment=?,suitable_for=?,
               allocation_mode=?,assigned_class_id=?,is_active=1 WHERE id=? AND school_id=?""",
            (name, room_type, capacity, (description or "").strip(), (equipment or "").strip(),
             (suitable_for or "").strip(), allocation_mode, assigned_class_id, existing["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_rooms
               (school_id,room_code,name,room_type,capacity,description,equipment,suitable_for,allocation_mode,assigned_class_id)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (school_id, code, name, room_type, capacity, (description or "").strip(),
             (equipment or "").strip(), (suitable_for or "").strip(), allocation_mode, assigned_class_id),
        )
    connection.commit()


def save_classroom_assignment(connection: Any, school_id: int, class_id: int, room_id: int | None) -> None:
    """Assign one dedicated classroom to a class, or release its current room."""
    cur = connection.cursor()
    class_row = cur.execute(
        "SELECT id FROM classes WHERE id=? AND school_id=?",
        (int(class_id), int(school_id)),
    ).fetchone()
    if not class_row:
        raise TimetableSetupError("Select a class belonging to this school.")
    if room_id is None:
        cur.execute(
            """UPDATE ds_timetable_rooms SET allocation_mode='shared',assigned_class_id=NULL
               WHERE school_id=? AND assigned_class_id=? AND allocation_mode='dedicated'""",
            (int(school_id), int(class_id)),
        )
        connection.commit()
        return
    room = cur.execute(
        """SELECT id,room_type,is_active,capacity,allocation_mode,assigned_class_id
           FROM ds_timetable_rooms WHERE id=? AND school_id=?""",
        (int(room_id), int(school_id)),
    ).fetchone()
    if not room or not int(room["is_active"] or 0):
        raise TimetableSetupError("Select an active classroom registered to this school.")
    if str(room["room_type"] or "").lower() != "classroom":
        raise TimetableSetupError("Only rooms registered as Classrooms can be permanently assigned to a class.")
    owner = room["assigned_class_id"]
    if str(room["allocation_mode"] or "shared").lower() == "dedicated" and owner is not None and int(owner) != int(class_id):
        raise TimetableSetupError("That classroom is already dedicated to another class.")
    enrolled = int(cur.execute(
        "SELECT COUNT(*) FROM students WHERE school_id=? AND class_id=?",
        (int(school_id), int(class_id)),
    ).fetchone()[0] or 0)
    if room["capacity"] is not None and int(room["capacity"]) < enrolled:
        raise TimetableSetupError(
            f"This class has {enrolled} learners, but the selected room holds only {int(room['capacity'])}. Choose a larger classroom."
        )
    # Keep a single primary classroom per class. Release its previous room
    # before assigning the newly selected room, in the same transaction.
    cur.execute(
        """UPDATE ds_timetable_rooms SET allocation_mode='shared',assigned_class_id=NULL
           WHERE school_id=? AND assigned_class_id=? AND allocation_mode='dedicated' AND id<>?""",
        (int(school_id), int(class_id), int(room_id)),
    )
    cur.execute(
        """UPDATE ds_timetable_rooms SET allocation_mode='dedicated',assigned_class_id=?
           WHERE id=? AND school_id=? AND is_active=1""",
        (int(class_id), int(room_id), int(school_id)),
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
                     max_periods_per_day: int | None, notes: str = "",
                     class_initials: str = "") -> None:
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
    initials = (class_initials or "").strip().upper()
    if len(initials) > 8:
        raise TimetableSetupError("Class initials must be 8 characters or fewer.")
    cur.execute("UPDATE classes SET initials=? WHERE id=? AND school_id=?", (initials or None, int(class_id), int(school_id)))
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


def save_class_requirement(connection: Any, school_id: int, profile_id: int, class_id: int, subject_id: int, teacher_id: int, lessons_per_week: int, duration_periods: int = 1, max_lessons_per_day: int | None = None, allow_double: bool = False, commit: bool = True) -> None:
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
    if commit:
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


def update_profile(connection: Any, school_id: int, profile_id: int, name: str, academic_year: str, term: str, academic_start_date: str = "", academic_end_date: str = "", profile_type: str = "main") -> None:
    """Update descriptive settings of an existing current timetable profile."""
    name, academic_year, term = (name or "").strip(), (academic_year or "").strip(), (term or "").strip()
    if not name or not academic_year or not term:
        raise TimetableSetupError("Profile name, academic year and term are required.")
    profile_type = (profile_type or "main").strip().lower()
    if profile_type not in {"main", "weekend", "remedial", "special"}:
        raise TimetableSetupError("Choose a valid timetable programme type.")
    academic_start_date, academic_end_date = (academic_start_date or "").strip(), (academic_end_date or "").strip()
    if academic_start_date or academic_end_date:
        try:
            start_date = datetime.strptime(academic_start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(academic_end_date, "%Y-%m-%d").date()
        except ValueError:
            raise TimetableSetupError("Enter valid academic start and end dates.")
        if end_date <= start_date:
            raise TimetableSetupError("Academic end date must be after the start date.")
    cur = connection.cursor()
    current = cur.execute("SELECT id,status,revision_of_profile_id FROM ds_timetable_profiles WHERE id=? AND school_id=?", (int(profile_id), int(school_id))).fetchone()
    if not current:
        raise TimetableSetupError("The selected timetable profile could not be found.")
    if str(current["status"] or "draft").lower() not in {"draft", "pending_approval", "published"}:
        raise TimetableSetupError("Only a current timetable profile can be edited here.")
    root_id = int(current["revision_of_profile_id"] or current["id"])
    if profile_type == "main":
        duplicate = cur.execute("""SELECT id FROM ds_timetable_profiles WHERE school_id=? AND academic_year=? AND term=? AND profile_type='main' AND status IN ('draft','pending_approval','published') AND COALESCE(revision_of_profile_id,id)<>? LIMIT 1""", (int(school_id), academic_year, term, root_id)).fetchone()
        if duplicate:
            raise TimetableSetupError("A main timetable already exists for this academic year and term.")
    else:
        duplicate = cur.execute("""SELECT id FROM ds_timetable_profiles WHERE school_id=? AND academic_year=? AND term=? AND profile_type=? AND name=? AND status IN ('draft','pending_approval','published') AND COALESCE(revision_of_profile_id,id)<>? LIMIT 1""", (int(school_id), academic_year, term, profile_type, name, root_id)).fetchone()
        if duplicate:
            raise TimetableSetupError("A timetable with this name and programme type already exists for this academic year and term.")
    cur.execute("""UPDATE ds_timetable_profiles SET name=?,academic_year=?,term=?,profile_type=?,academic_start_date=?,academic_end_date=?,updated_at=? WHERE id=? AND school_id=?""", (name, academic_year, term, profile_type, academic_start_date or None, academic_end_date or None, _now(), int(profile_id), int(school_id)))
    connection.commit()
