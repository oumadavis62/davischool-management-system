"""Advanced calendar, day-template, rotation and learning-programme setup.

This module is deliberately separate from the legacy weekly setup helpers.
It writes only the additive ds_timetable_* architecture and validates every
record against the owning school and editable timetable profile.
"""
from __future__ import annotations

from datetime import date, datetime
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
