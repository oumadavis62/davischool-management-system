"""Advanced calendar, day-template, rotation and learning-programme setup.

This module is deliberately separate from the legacy weekly setup helpers.
It writes only the additive ds_timetable_* architecture and validates every
record against the owning school and editable timetable profile.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import re
from typing import Any

from app.timetable.setup import TimetableSetupError, _profile


_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _time_range(start: str, end: str) -> tuple[str, str, int]:
    start, end = (start or "").strip(), (end or "").strip()
    if not _TIME_RE.fullmatch(start) or not _TIME_RE.fullmatch(end):
        raise TimetableSetupError("Enter valid 24-hour start and end times (HH:MM).")
    minutes = lambda value: int(value[:2]) * 60 + int(value[3:])
    duration = minutes(end) - minutes(start)
    if duration <= 0:
        raise TimetableSetupError("The end time must be later than the start time.")
    return start, end, duration


def create_schedule_template(connection: Any, school_id: int, profile_id: int,
                             name: str, template_type: str = "instructional",
                             notes: str = "") -> int:
    name = (name or "").strip()
    allowed = {"instructional", "remedial", "weekend", "activity", "custom"}
    if not name or template_type not in allowed:
        raise TimetableSetupError("Give the schedule template a name and choose a valid type.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    cur.execute(
        """INSERT INTO ds_timetable_schedule_templates
           (school_id,profile_id,name,template_type,notes)
           VALUES(?,?,?,?,?)""",
        (school_id, profile_id, name, template_type, (notes or "").strip()),
    )
    row = cur.execute(
        """SELECT id FROM ds_timetable_schedule_templates
           WHERE school_id=? AND profile_id=? AND name=?""",
        (school_id, profile_id, name),
    ).fetchone()
    connection.commit()
    return int(row["id"])


def save_schedule_slot(connection: Any, school_id: int, profile_id: int,
                        template_id: int, slot_no: int, label: str,
                        slot_type: str, start_time: str, end_time: str,
                        instructional_period_no: int | None = None) -> int:
    start, end, duration = _time_range(start_time, end_time)
    label = (label or "").strip()
    allowed = {"instructional", "break", "remedial", "study", "activity", "assembly", "other"}
    if not label or slot_type not in allowed or not 1 <= int(slot_no) <= 60:
        raise TimetableSetupError("Choose a valid slot number, label and slot type.")
    if slot_type == "instructional":
        if instructional_period_no is None or not 1 <= int(instructional_period_no) <= 30:
            raise TimetableSetupError("Instructional slots require a period number from 1 to 30.")
    else:
        instructional_period_no = None
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    template = cur.execute(
        """SELECT id FROM ds_timetable_schedule_templates
           WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
        (template_id, school_id, profile_id),
    ).fetchone()
    if not template:
        raise TimetableSetupError("Select an active schedule template belonging to this profile.")
    overlap = cur.execute(
        """SELECT id FROM ds_timetable_schedule_slots
           WHERE school_id=? AND profile_id=? AND template_id=? AND slot_no<>?
             AND start_time < ? AND end_time > ? LIMIT 1""",
        (school_id, profile_id, template_id, int(slot_no), end, start),
    ).fetchone()
    if overlap:
        raise TimetableSetupError("This slot overlaps another slot in the same daily template.")
    old = cur.execute(
        """SELECT id FROM ds_timetable_schedule_slots
           WHERE school_id=? AND profile_id=? AND template_id=? AND slot_no=?""",
        (school_id, profile_id, template_id, int(slot_no)),
    ).fetchone()
    values = (label, slot_type, start, end, duration, instructional_period_no)
    if old:
        cur.execute(
            """UPDATE ds_timetable_schedule_slots SET label=?,slot_type=?,start_time=?,
               end_time=?,duration_minutes=?,instructional_period_no=?
               WHERE id=? AND school_id=?""",
            values + (old["id"], school_id),
        )
        slot_id = int(old["id"])
    else:
        cur.execute(
            """INSERT INTO ds_timetable_schedule_slots
               (school_id,profile_id,template_id,slot_no,label,slot_type,start_time,
                end_time,duration_minutes,instructional_period_no)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (school_id, profile_id, template_id, int(slot_no)) + values,
        )
        row = cur.execute(
            """SELECT id FROM ds_timetable_schedule_slots
               WHERE school_id=? AND profile_id=? AND template_id=? AND slot_no=?""",
            (school_id, profile_id, template_id, int(slot_no)),
        ).fetchone()
        slot_id = int(row["id"])
    connection.commit()
    return slot_id


def assign_day_template(connection: Any, school_id: int, profile_id: int,
                        day_id: int, template_id: int, cycle_week: int = 0) -> None:
    if not 0 <= int(cycle_week) <= 52:
        raise TimetableSetupError("Cycle week must be between 0 (every week) and 52.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    day = cur.execute(
        "SELECT id FROM ds_timetable_days WHERE id=? AND school_id=? AND profile_id=?",
        (day_id, school_id, profile_id),
    ).fetchone()
    template = cur.execute(
        "SELECT id FROM ds_timetable_schedule_templates WHERE id=? AND school_id=? AND profile_id=? AND is_active=1",
        (template_id, school_id, profile_id),
    ).fetchone()
    if not day or not template:
        raise TimetableSetupError("Choose a day and schedule template from this timetable profile.")
    old = cur.execute(
        """SELECT id FROM ds_timetable_day_templates
           WHERE school_id=? AND profile_id=? AND day_id=? AND cycle_week=?""",
        (school_id, profile_id, day_id, int(cycle_week)),
    ).fetchone()
    if old:
        cur.execute(
            "UPDATE ds_timetable_day_templates SET template_id=? WHERE id=? AND school_id=?",
            (template_id, old["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_day_templates
               (school_id,profile_id,day_id,template_id,cycle_week) VALUES(?,?,?,?,?)""",
            (school_id, profile_id, day_id, template_id, int(cycle_week)),
        )
    connection.commit()


def create_rotation_cycle(connection: Any, school_id: int, profile_id: int,
                          name: str, cycle_length_weeks: int, anchor_date: str) -> int:
    name = (name or "").strip()
    try:
        anchor = date.fromisoformat((anchor_date or "").strip())
    except ValueError:
        raise TimetableSetupError("Choose a valid rotation start date.")
    if not name or not 1 <= int(cycle_length_weeks) <= 52:
        raise TimetableSetupError("A rotation needs a name and a cycle length from 1 to 52 weeks.")
    cur = connection.cursor()
    profile = _profile(cur, school_id, profile_id)
    if profile["academic_start_date"] and anchor < date.fromisoformat(str(profile["academic_start_date"])):
        raise TimetableSetupError("The rotation anchor date cannot be before the academic year starts.")
    cur.execute(
        """INSERT INTO ds_timetable_rotation_cycles
           (school_id,profile_id,name,cycle_length_weeks,anchor_date)
           VALUES(?,?,?,?,?)""",
        (school_id, profile_id, name, int(cycle_length_weeks), anchor.isoformat()),
    )
    row = cur.execute(
        "SELECT id FROM ds_timetable_rotation_cycles WHERE school_id=? AND profile_id=? AND name=?",
        (school_id, profile_id, name),
    ).fetchone()
    connection.commit()
    return int(row["id"])


def save_rotation_week(connection: Any, school_id: int, profile_id: int,
                       cycle_id: int, week_number: int, label: str,
                       department_code: str = "", programme_id: int | None = None) -> None:
    label = (label or "").strip()
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    cycle = cur.execute(
        """SELECT cycle_length_weeks FROM ds_timetable_rotation_cycles
           WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
        (cycle_id, school_id, profile_id),
    ).fetchone()
    if not cycle or not 1 <= int(week_number) <= int(cycle["cycle_length_weeks"]) or not label:
        raise TimetableSetupError("Choose a valid cycle and a week number within its length.")
    if programme_id is not None:
        programme = cur.execute(
            """SELECT id FROM ds_timetable_learning_programmes
               WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
            (programme_id, school_id, profile_id),
        ).fetchone()
        if not programme:
            raise TimetableSetupError("The selected learning programme does not belong to this profile.")
    old = cur.execute(
        """SELECT id FROM ds_timetable_rotation_weeks
           WHERE school_id=? AND profile_id=? AND cycle_id=? AND week_number=?""",
        (school_id, profile_id, cycle_id, int(week_number)),
    ).fetchone()
    values = (label, (department_code or "").strip().upper() or None, programme_id)
    if old:
        cur.execute(
            """UPDATE ds_timetable_rotation_weeks SET label=?,department_code=?,programme_id=?
               WHERE id=? AND school_id=?""",
            values + (old["id"], school_id),
        )
    else:
        cur.execute(
            """INSERT INTO ds_timetable_rotation_weeks
               (school_id,profile_id,cycle_id,week_number,label,department_code,programme_id)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id, profile_id, cycle_id, int(week_number)) + values,
        )
    connection.commit()


def create_learning_programme(connection: Any, school_id: int, profile_id: int,
                               name: str, programme_type: str = "remedial",
                               schedule_layer: str = "additional_learning",
                               recurrence_type: str = "weekly",
                               recurrence: dict[str, Any] | None = None,
                               rotation_cycle_id: int | None = None,
                               department_code: str = "",
                               counts_toward_curriculum: bool = False) -> int:
    name = (name or "").strip()
    types = {"remedial", "catch_up", "revision", "supervised_study", "club", "sports", "other"}
    layers = {"additional_learning", "school_activity"}
    recurrences = {"daily", "weekly", "weekends", "date_list", "rotation", "once"}
    if not name or programme_type not in types or schedule_layer not in layers or recurrence_type not in recurrences:
        raise TimetableSetupError("Choose a name and valid programme, schedule layer and recurrence.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    if recurrence_type == "rotation":
        cycle = cur.execute(
            """SELECT id FROM ds_timetable_rotation_cycles
               WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
            (rotation_cycle_id, school_id, profile_id),
        ).fetchone()
        if not cycle:
            raise TimetableSetupError("A rotation programme must be linked to an active rotation cycle.")
    elif rotation_cycle_id is not None:
        raise TimetableSetupError("Only rotation programmes may reference a rotation cycle.")
    payload = json.dumps(recurrence or {}, sort_keys=True)
    cur.execute(
        """INSERT INTO ds_timetable_learning_programmes
           (school_id,profile_id,name,programme_type,schedule_layer,recurrence_type,
            recurrence_json,rotation_cycle_id,department_code,counts_toward_curriculum)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (school_id, profile_id, name, programme_type, schedule_layer, recurrence_type,
         payload, rotation_cycle_id, (department_code or "").strip().upper() or None,
         1 if counts_toward_curriculum else 0),
    )
    row = cur.execute(
        "SELECT id FROM ds_timetable_learning_programmes WHERE school_id=? AND profile_id=? AND name=?",
        (school_id, profile_id, name),
    ).fetchone()
    connection.commit()
    return int(row["id"])


def save_requirement_session_pattern(connection: Any, school_id: int, profile_id: int,
                                     requirement_id: int,
                                     sessions: list[dict[str, Any]]) -> None:
    """Replace a requirement's single/double/triple session pattern atomically.

    The sum of session durations must exactly equal the requirement's weekly
    period allocation. Optional day and slot preferences are profile-scoped.
    """
    if not isinstance(sessions, list) or not sessions:
        raise TimetableSetupError("Add at least one lesson session to the weekly pattern.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    requirement = cur.execute(
        """SELECT id,lessons_per_week FROM ds_timetable_class_requirements
           WHERE id=? AND school_id=? AND profile_id=?""",
        (requirement_id, school_id, profile_id),
    ).fetchone()
    if not requirement:
        raise TimetableSetupError("The selected subject requirement does not belong to this timetable.")
    normalized = []
    total_periods = 0
    for index, session in enumerate(sessions, start=1):
        try:
            duration = int(session.get("duration_periods", 1))
            day_id = session.get("preferred_day_id")
            slot_id = session.get("preferred_slot_id")
        except (AttributeError, TypeError, ValueError):
            raise TimetableSetupError("Each weekly session must have a valid duration and preferences.")
        if not 1 <= duration <= 4:
            raise TimetableSetupError("Each lesson session must occupy between 1 and 4 consecutive periods.")
        if day_id is not None:
            day = cur.execute(
                "SELECT id FROM ds_timetable_days WHERE id=? AND school_id=? AND profile_id=?",
                (int(day_id), school_id, profile_id),
            ).fetchone()
            if not day:
                raise TimetableSetupError("A preferred lesson day is outside this timetable profile.")
        if slot_id is not None:
            slot = cur.execute(
                """SELECT id,slot_type FROM ds_timetable_schedule_slots
                   WHERE id=? AND school_id=? AND profile_id=?""",
                (int(slot_id), school_id, profile_id),
            ).fetchone()
            if not slot or str(slot["slot_type"]) != "instructional":
                raise TimetableSetupError("A preferred slot must be an instructional slot in this profile.")
        label = str(session.get("session_label") or "").strip()[:80] or f"Session {index}"
        normalized.append((index, duration, int(day_id) if day_id is not None else None,
                           int(slot_id) if slot_id is not None else None, label))
        total_periods += duration
    expected = int(requirement["lessons_per_week"])
    if total_periods != expected:
        raise TimetableSetupError(
            f"Lesson pattern totals {total_periods} periods, but this subject is allocated {expected} per week."
        )
    try:
        cur.execute(
            "DELETE FROM ds_timetable_requirement_patterns WHERE school_id=? AND profile_id=? AND requirement_id=?",
            (school_id, profile_id, requirement_id),
        )
        for session_no, duration, day_id, slot_id, label in normalized:
            cur.execute(
                """INSERT INTO ds_timetable_requirement_patterns
                   (school_id,profile_id,requirement_id,session_no,duration_periods,
                    preferred_day_id,preferred_slot_id,session_label)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (school_id, profile_id, requirement_id, session_no, duration, day_id, slot_id, label),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def save_activity_type(connection: Any, school_id: int, code: str, name: str,
                       requires_teacher: bool = False,
                       requires_room: bool = False,
                       tracks_attendance: bool = False) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or len(code) > 30 or not name:
        raise TimetableSetupError("Activity code and name are required.")
    cur = connection.cursor()
    old = cur.execute(
        "SELECT id FROM ds_timetable_activity_types WHERE school_id=? AND code=?",
        (school_id, code),
    ).fetchone()
    flags = (name, int(bool(requires_teacher)), int(bool(requires_room)), int(bool(tracks_attendance)))
    if old:
        cur.execute(
            """UPDATE ds_timetable_activity_types SET name=?,requires_teacher=?,
               requires_room=?,tracks_attendance=? WHERE id=? AND school_id=?""",
            flags + (old["id"], school_id),
        )
        activity_id = int(old["id"])
    else:
        cur.execute(
            """INSERT INTO ds_timetable_activity_types
               (school_id,code,name,requires_teacher,requires_room,tracks_attendance)
               VALUES(?,?,?,?,?,?)""",
            (school_id, code) + flags,
        )
        row = cur.execute(
            "SELECT id FROM ds_timetable_activity_types WHERE school_id=? AND code=?",
            (school_id, code),
        ).fetchone()
        activity_id = int(row["id"])
    connection.commit()
    return activity_id


def save_programme_session(connection: Any, school_id: int, profile_id: int,
                            programme_id: int, start_time: str, end_time: str,
                            duration_minutes: int,
                            day_id: int | None = None, cycle_week: int = 0,
                            subject_id: int | None = None,
                            teaching_group_id: int | None = None,
                            required_teacher_count: int = 1,
                            room_type: str = "",
                            recurrence: dict[str, Any] | None = None) -> int:
    start, end, actual_duration = _time_range(start_time, end_time)
    if int(duration_minutes) != actual_duration:
        raise TimetableSetupError("Programme duration must match its configured start and end times.")
    if not 1 <= int(required_teacher_count) <= 20 or not 0 <= int(cycle_week) <= 52:
        raise TimetableSetupError("Teacher count must be 1–20 and cycle week must be 0–52.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    programme = cur.execute(
        """SELECT id,rotation_cycle_id,recurrence_type FROM ds_timetable_learning_programmes
           WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
        (programme_id, school_id, profile_id),
    ).fetchone()
    if not programme:
        raise TimetableSetupError("Select an active learning programme from this timetable profile.")
    if programme["recurrence_type"] == "rotation" and int(cycle_week) == 0:
        raise TimetableSetupError("A rotating programme session must specify its cycle week.")
    if day_id is not None and not cur.execute(
        "SELECT id FROM ds_timetable_days WHERE id=? AND school_id=? AND profile_id=?",
        (day_id, school_id, profile_id),
    ).fetchone():
        raise TimetableSetupError("Select a day belonging to this timetable profile.")
    if teaching_group_id is not None and not cur.execute(
        "SELECT id FROM ds_timetable_teaching_groups WHERE id=? AND school_id=? AND profile_id=? AND is_active=1",
        (teaching_group_id, school_id, profile_id),
    ).fetchone():
        raise TimetableSetupError("Select a teaching group belonging to this timetable profile.")
    if room_type and room_type not in {"classroom", "laboratory", "library", "hall", "workshop", "sports", "other"}:
        raise TimetableSetupError("Choose a valid room type.")
    cur.execute(
        """INSERT INTO ds_timetable_programme_sessions
           (school_id,profile_id,programme_id,subject_id,teaching_group_id,day_id,
            cycle_week,start_time,end_time,duration_minutes,recurrence_json,
            required_teacher_count,room_type)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (school_id, profile_id, programme_id, subject_id, teaching_group_id, day_id,
         int(cycle_week), start, end, int(duration_minutes),
         json.dumps(recurrence or {}, sort_keys=True), int(required_teacher_count), room_type or None),
    )
    row = cur.execute(
        """SELECT id FROM ds_timetable_programme_sessions
           WHERE school_id=? AND profile_id=? AND programme_id=? ORDER BY id DESC LIMIT 1""",
        (school_id, profile_id, programme_id),
    ).fetchone()
    connection.commit()
    return int(row["id"])


def create_scheduling_requirement(connection: Any, school_id: int, profile_id: int,
                                  name: str, class_ids: list[int] | None = None,
                                  teacher_ids: list[int] | None = None,
                                  learner_ids: list[int] | None = None,
                                  schedule_layer: str = "instructional",
                                  session_type: str = "lesson",
                                  subject_id: int | None = None,
                                  programme_id: int | None = None,
                                  teaching_group_id: int | None = None,
                                  weekly_occurrences: int = 1,
                                  weekly_periods: int = 0,
                                  counts_toward_curriculum: bool = True,
                                  min_teacher_count: int = 1,
                                  room_type: str = "") -> int:
    """Create a normalized requirement with many classes, teachers and learners."""
    name = (name or "").strip()
    classes = list(dict.fromkeys(int(v) for v in (class_ids or [])))
    teachers = list(dict.fromkeys(int(v) for v in (teacher_ids or [])))
    learners = list(dict.fromkeys(int(v) for v in (learner_ids or [])))
    if not name or schedule_layer not in {"instructional", "additional_learning", "school_activity"}:
        raise TimetableSetupError("Give the scheduling requirement a name and valid schedule layer.")
    if not 1 <= int(weekly_occurrences) <= 70 or not 0 <= int(weekly_periods) <= 210:
        raise TimetableSetupError("Weekly sessions must be 1–70 and weekly periods 0–210.")
    if not 1 <= int(min_teacher_count) <= 20:
        raise TimetableSetupError("Minimum teacher count must be between 1 and 20.")
    if schedule_layer == "instructional" and not classes and not learners and teaching_group_id is None:
        raise TimetableSetupError("An instructional requirement must target classes, a teaching group or learners.")
    if len(teachers) < int(min_teacher_count):
        raise TimetableSetupError("The selected teaching team is smaller than the required teacher count.")
    if room_type and room_type not in {"classroom", "laboratory", "library", "hall", "workshop", "sports", "other"}:
        raise TimetableSetupError("Choose a valid room type.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    if teaching_group_id is not None:
        group = cur.execute(
            "SELECT id FROM ds_timetable_teaching_groups WHERE id=? AND school_id=? AND profile_id=? AND is_active=1",
            (teaching_group_id, school_id, profile_id),
        ).fetchone()
        if not group:
            raise TimetableSetupError("Select an active teaching group from this timetable profile.")
        group_classes = [int(row["class_id"]) for row in cur.execute(
            "SELECT class_id FROM ds_timetable_teaching_group_classes WHERE teaching_group_id=? AND school_id=?",
            (teaching_group_id, school_id),
        ).fetchall()]
        if classes and set(classes) != set(group_classes):
            raise TimetableSetupError("Requirement classes must match all classes in the selected teaching group.")
        classes = group_classes
    for class_id in classes:
        if not cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?", (class_id, school_id)).fetchone():
            raise TimetableSetupError("A selected class does not belong to this school.")
    for teacher_id in teachers:
        if not cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?", (teacher_id, school_id)).fetchone():
            raise TimetableSetupError("A selected teacher does not belong to this school.")
    for learner_id in learners:
        if not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?", (learner_id, school_id)).fetchone():
            raise TimetableSetupError("A selected learner does not belong to this school.")
    if programme_id is not None and not cur.execute(
        "SELECT id FROM ds_timetable_learning_programmes WHERE id=? AND school_id=? AND profile_id=? AND is_active=1",
        (programme_id, school_id, profile_id),
    ).fetchone():
        raise TimetableSetupError("Select a learning programme belonging to this timetable profile.")
    cur.execute(
        """INSERT INTO ds_timetable_scheduling_requirements
           (school_id,profile_id,name,schedule_layer,session_type,subject_id,programme_id,
            teaching_group_id,weekly_occurrences,weekly_periods,counts_toward_curriculum,
            min_teacher_count,room_type)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (school_id, profile_id, name, schedule_layer, session_type, subject_id, programme_id,
         teaching_group_id, int(weekly_occurrences), int(weekly_periods),
         int(bool(counts_toward_curriculum)), int(min_teacher_count), room_type or None),
    )
    row = cur.execute(
        "SELECT id FROM ds_timetable_scheduling_requirements WHERE school_id=? AND profile_id=? AND name=?",
        (school_id, profile_id, name),
    ).fetchone()
    requirement_id = int(row["id"])
    try:
        for class_id in classes:
            cur.execute(
                """INSERT INTO ds_timetable_scheduling_requirement_classes
                   (school_id,profile_id,requirement_id,class_id) VALUES(?,?,?,?)""",
                (school_id, profile_id, requirement_id, class_id),
            )
        for index, teacher_id in enumerate(teachers):
            cur.execute(
                """INSERT INTO ds_timetable_scheduling_requirement_teachers
                   (school_id,profile_id,requirement_id,teacher_id,role) VALUES(?,?,?,?,?)""",
                (school_id, profile_id, requirement_id, teacher_id, "lead" if index == 0 else "support"),
            )
        for learner_id in learners:
            cur.execute(
                """INSERT INTO ds_timetable_scheduling_requirement_learners
                   (school_id,profile_id,requirement_id,student_id) VALUES(?,?,?,?)""",
                (school_id, profile_id, requirement_id, learner_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return requirement_id


def save_scheduling_pattern(connection: Any, school_id: int, profile_id: int,
                            requirement_id: int, sessions: list[dict[str, Any]]) -> None:
    """Save exact session pattern; both session count and period total must balance."""
    if not isinstance(sessions, list) or not sessions:
        raise TimetableSetupError("Add at least one session to the scheduling pattern.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    requirement = cur.execute(
        """SELECT weekly_occurrences,weekly_periods,schedule_layer
           FROM ds_timetable_scheduling_requirements
           WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
        (requirement_id, school_id, profile_id),
    ).fetchone()
    if not requirement:
        raise TimetableSetupError("The scheduling requirement does not belong to this timetable profile.")
    if len(sessions) != int(requirement["weekly_occurrences"]):
        raise TimetableSetupError(
            f"This requirement needs {int(requirement['weekly_occurrences'])} sessions per week; you supplied {len(sessions)}."
        )
    normalized = []
    period_total = 0
    for index, item in enumerate(sessions, start=1):
        duration = int(item.get("duration_periods", 0) or 0)
        minutes = int(item.get("duration_minutes", 0) or 0)
        if requirement["schedule_layer"] == "instructional":
            if not 1 <= duration <= 4:
                raise TimetableSetupError("Instructional sessions must occupy 1–4 consecutive periods.")
            period_total += duration
        elif duration < 0 or minutes < 1:
            raise TimetableSetupError("Additional-learning and activity sessions require a duration in minutes.")
        day_id, slot_id = item.get("preferred_day_id"), item.get("preferred_slot_id")
        if day_id is not None and not cur.execute(
            "SELECT id FROM ds_timetable_days WHERE id=? AND school_id=? AND profile_id=?",
            (int(day_id), school_id, profile_id),
        ).fetchone():
            raise TimetableSetupError("A preferred day is outside this timetable profile.")
        if slot_id is not None and not cur.execute(
            "SELECT id FROM ds_timetable_schedule_slots WHERE id=? AND school_id=? AND profile_id=?",
            (int(slot_id), school_id, profile_id),
        ).fetchone():
            raise TimetableSetupError("A preferred slot is outside this timetable profile.")
        normalized.append((index, duration, minutes or None,
                           int(day_id) if day_id is not None else None,
                           int(slot_id) if slot_id is not None else None,
                           str(item.get("session_label") or f"Session {index}")[:80]))
    expected_periods = int(requirement["weekly_periods"] or 0)
    if requirement["schedule_layer"] == "instructional" and expected_periods and period_total != expected_periods:
        raise TimetableSetupError(
            f"The pattern totals {period_total} periods, but the weekly allocation is {expected_periods}."
        )
    try:
        cur.execute(
            "DELETE FROM ds_timetable_scheduling_patterns WHERE school_id=? AND profile_id=? AND requirement_id=?",
            (school_id, profile_id, requirement_id),
        )
        for values in normalized:
            cur.execute(
                """INSERT INTO ds_timetable_scheduling_patterns
                   (school_id,profile_id,requirement_id,session_no,duration_periods,
                    duration_minutes,preferred_day_id,preferred_slot_id,session_label)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (school_id, profile_id, requirement_id) + values,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise



def save_timetable_constraint(connection: Any, school_id: int, profile_id: int,
                              name: str, constraint_type: str = "prohibit",
                              applies_to: str = "all", schedule_layer: str = "all",
                              subject_id: int | None = None,
                              teacher_id: int | None = None,
                              class_id: int | None = None,
                              room_id: int | None = None,
                              day_id: int | None = None,
                              period_id: int | None = None,
                              start_time: str | None = None,
                              end_time: str | None = None,
                              effective_from: str | None = None,
                              effective_to: str | None = None,
                              reason: str = "",
                              constraint_id: int | None = None) -> int:
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise TimetableSetupError("Give this timetable constraint a name (maximum 120 characters).")
    if constraint_type not in {"prohibit", "prefer", "require"}:
        raise TimetableSetupError("Choose prohibit, prefer or require as the constraint type.")
    if applies_to not in {"all", "lesson", "remedial", "activity"}:
        raise TimetableSetupError("Choose a valid session scope.")
    if schedule_layer not in {"all", "instructional", "additional_learning", "school_activity"}:
        raise TimetableSetupError("Choose a valid timetable layer.")
    if (start_time is None) != (end_time is None):
        raise TimetableSetupError("Enter both start and end times for a time-window constraint.")
    if constraint_type == "require" and day_id is None and period_id is None and start_time is None:
        raise TimetableSetupError("A required-time rule must specify a day, period or time window.")
    if start_time is not None:
        start_time, end_time, _ = _time_range(start_time, end_time)
    for value in (effective_from, effective_to):
        if value:
            try:
                date.fromisoformat(str(value))
            except ValueError:
                raise TimetableSetupError("Constraint effective dates must use YYYY-MM-DD.")
    if effective_from and effective_to and effective_from > effective_to:
        raise TimetableSetupError("Constraint end date cannot be before its start date.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    for table, value, label in (
        ("ds_timetable_days", day_id, "day"),
        ("ds_timetable_periods", period_id, "period"),
    ):
        if value is not None and not cur.execute(
            f"SELECT id FROM {table} WHERE id=? AND school_id=? AND profile_id=?",
            (int(value), school_id, profile_id),
        ).fetchone():
            raise TimetableSetupError(f"Select a {label} from this timetable profile.")
    for table, value, label in (
        ("subjects", subject_id, "subject"),
        ("teachers", teacher_id, "teacher"),
        ("classes", class_id, "class"),
        ("ds_timetable_rooms", room_id, "room"),
    ):
        if value is not None and not cur.execute(
            f"SELECT id FROM {table} WHERE id=? AND school_id=?",
            (int(value), school_id),
        ).fetchone():
            raise TimetableSetupError(f"The selected {label} does not belong to this school.")
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    values = (name,constraint_type,applies_to,schedule_layer,subject_id,teacher_id,
              class_id,room_id,day_id,period_id,start_time,end_time,effective_from,
              effective_to,(reason or "").strip(),now)
    if constraint_id is not None:
        existing = cur.execute(
            "SELECT id FROM ds_timetable_constraints WHERE id=? AND school_id=? AND profile_id=?",
            (int(constraint_id),school_id,profile_id),
        ).fetchone()
        if not existing:
            raise TimetableSetupError("That constraint no longer exists in this timetable profile.")
        cur.execute(
            """UPDATE ds_timetable_constraints SET name=?,constraint_type=?,applies_to=?,
               schedule_layer=?,subject_id=?,teacher_id=?,class_id=?,room_id=?,day_id=?,
               period_id=?,start_time=?,end_time=?,effective_from=?,effective_to=?,reason=?,updated_at=?
               WHERE id=? AND school_id=? AND profile_id=?""",
            values + (int(constraint_id),school_id,profile_id),
        )
        saved_id = int(constraint_id)
    else:
        cur.execute(
            """INSERT INTO ds_timetable_constraints
               (school_id,profile_id,name,constraint_type,applies_to,schedule_layer,
                subject_id,teacher_id,class_id,room_id,day_id,period_id,start_time,end_time,
                effective_from,effective_to,reason,is_active,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (school_id,profile_id)+values,
        )
        saved_id = int(cur.lastrowid)
    connection.commit()
    return saved_id


def resolve_calendar_occurrence(connection: Any, school_id: int, profile_id: int,
                                occurrence_date: str) -> dict[str, Any]:
    """Resolve one calendar date to its day, applicable day template and rotations.

    This is the date-aware foundation for expanding weekly, weekend and
    rotating programmes. Calendar exceptions override the normal weekday flag;
    a day template for a numbered cycle week takes precedence over the default
    (cycle_week=0) template.
    """
    try:
        target = date.fromisoformat((occurrence_date or "").strip())
    except ValueError:
        raise TimetableSetupError("Choose a valid timetable date in YYYY-MM-DD format.")

    cur = connection.cursor()
    profile = _profile(cur, school_id, profile_id)
    start_value = profile["academic_start_date"]
    end_value = profile["academic_end_date"]
    academic_start = date.fromisoformat(str(start_value)) if start_value else None
    academic_end = date.fromisoformat(str(end_value)) if end_value else None
    if academic_start and target < academic_start:
        raise TimetableSetupError("The selected date is before this timetable's academic start date.")
    if academic_end and target > academic_end:
        raise TimetableSetupError("The selected date is after this timetable's academic end date.")

    day_codes = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    day_code = day_codes[target.weekday()]
    day = cur.execute(
        """SELECT id,day_code,day_name,day_order,is_instructional
           FROM ds_timetable_days
           WHERE school_id=? AND profile_id=? AND day_code=?""",
        (school_id, profile_id, day_code),
    ).fetchone()

    exceptions = cur.execute(
        """SELECT id,label,exception_type,notes,is_instructional
           FROM ds_timetable_calendar_exceptions
           WHERE school_id=? AND profile_id=? AND exception_date=?
           ORDER BY id""",
        (school_id, profile_id, target.isoformat()),
    ).fetchall()
    # Multiple labels may be recorded on one date. Any explicitly instructional
    # exception keeps the date open; otherwise the exception closes it.
    instructional = bool(day and day["is_instructional"])
    if exceptions:
        instructional = any(bool(item["is_instructional"]) for item in exceptions)

    template_id = None
    cycle_week = 0
    if academic_start:
        elapsed_weeks = (target - academic_start).days // 7
        cycle_week = (elapsed_weeks % 52) + 1
    if day:
        template = cur.execute(
            """SELECT template_id FROM ds_timetable_day_templates
               WHERE school_id=? AND profile_id=? AND day_id=? AND cycle_week IN (?,0)
               ORDER BY CASE WHEN cycle_week=? THEN 0 ELSE 1 END LIMIT 1""",
            (school_id, profile_id, int(day["id"]), cycle_week, cycle_week),
        ).fetchone()
        if template:
            template_id = int(template["template_id"])

    schedule_slots = []
    if template_id is not None:
        schedule_slots = [
            dict(slot) for slot in cur.execute(
                """SELECT id,slot_no,label,slot_type,start_time,end_time,
                          instructional_period_no AS period_no
                   FROM ds_timetable_schedule_slots
                   WHERE school_id=? AND profile_id=? AND template_id=?
                   ORDER BY slot_no,id""",
                (school_id, profile_id, template_id),
            ).fetchall()
        ]

    rotations = []
    for cycle in cur.execute(
        """SELECT id,name,cycle_length_weeks,anchor_date
           FROM ds_timetable_rotation_cycles
           WHERE school_id=? AND profile_id=? AND is_active=1
           ORDER BY id""",
        (school_id, profile_id),
    ).fetchall():
        anchor = date.fromisoformat(str(cycle["anchor_date"]))
        if target < anchor:
            continue
        week_number = (((target - anchor).days // 7) % int(cycle["cycle_length_weeks"])) + 1
        rotation = cur.execute(
            """SELECT week_number,label,department_code,programme_id
               FROM ds_timetable_rotation_weeks
               WHERE school_id=? AND profile_id=? AND cycle_id=? AND week_number=?""",
            (school_id, profile_id, int(cycle["id"]), week_number),
        ).fetchone()
        rotations.append({
            "cycle_id": int(cycle["id"]),
            "cycle_name": str(cycle["name"]),
            "week_number": week_number,
            "week": dict(rotation) if rotation else None,
            "programme_id": int(rotation["programme_id"]) if rotation and rotation["programme_id"] is not None else None,
        })

    return {
        "date": target.isoformat(),
        "day_code": day_code,
        "day_id": int(day["id"]) if day else None,
        "day_name": str(day["day_name"]) if day else day_code.title(),
        "is_configured": bool(day),
        "is_instructional": instructional,
        "template_id": template_id,
        "schedule_slots": schedule_slots,
        "cycle_week": cycle_week,
        "exceptions": [dict(item) for item in exceptions],
        "rotations": rotations,
    }


def expand_calendar_occurrences(connection: Any, school_id: int, profile_id: int,
                                start_date: str, end_date: str,
                                include_closed: bool = False) -> list[dict[str, Any]]:
    """Expand a bounded date range using the profile's date-aware calendar."""
    try:
        start = date.fromisoformat((start_date or "").strip())
        end = date.fromisoformat((end_date or "").strip())
    except ValueError:
        raise TimetableSetupError("Enter valid calendar dates in YYYY-MM-DD format.")
    if end < start:
        raise TimetableSetupError("The calendar end date must not be before its start date.")
    span = (end - start).days
    if span > 365:
        raise TimetableSetupError("Expand no more than 366 calendar dates at a time.")
    occurrences = []
    for offset in range(span + 1):
        occurrence = resolve_calendar_occurrence(
            connection, school_id, profile_id, (start + timedelta(days=offset)).isoformat()
        )
        if (include_closed or occurrence["is_instructional"]
                or occurrence["template_id"] is not None or occurrence["rotations"]):
            occurrences.append(occurrence)
    return occurrences
