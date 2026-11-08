"""Unified session creation and resource-conflict validation.

All new timetable layers (instructional, additional learning and activities)
share this engine. Classes and teachers are represented by join rows so one
session can serve combined classes and be delivered by a teaching team.
"""
from __future__ import annotations

from datetime import date, timedelta, datetime
import re
from typing import Any, Iterable

from app.timetable.setup import TimetableSetupError, _profile
from app.timetable.advanced_setup import resolve_calendar_occurrence

_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _unique_ids(values: Iterable[Any], field: str) -> list[int]:
    try:
        result = list(dict.fromkeys(int(value) for value in values if value is not None))
    except (TypeError, ValueError):
        raise TimetableSetupError(f"Invalid {field} selection.")
    if any(value <= 0 for value in result):
        raise TimetableSetupError(f"Invalid {field} selection.")
    return result


def _validate_calendar_session(cur: Any, school_id: int, profile_id: int,
                                session_date: str | None, day_id: int | None,
                                start: str, end: str, schedule_layer: str,
                                programme_id: int | None = None) -> None:
    """Ensure every dated session fits its calendar day, rotation and layer slots."""
    if not session_date:
        return
    occurrence = resolve_calendar_occurrence(
        cur.connection, school_id, profile_id, session_date
    )
    if day_id is not None and occurrence["day_id"] != int(day_id):
        raise TimetableSetupError("The selected timetable day does not match the session date.")

    allowed_types = {
        "instructional": {"instructional", "lesson", "teaching"},
        "additional_learning": {"remedial", "study"},
        "school_activity": {"activity", "assembly", "other"},
    }.get(schedule_layer, set())
    if schedule_layer == "instructional" and not occurrence["is_instructional"]:
        raise TimetableSetupError("The selected date is closed for instructional lessons.")
    if schedule_layer == "additional_learning" and not (
        occurrence["is_instructional"] or occurrence["template_id"] is not None
    ):
        raise TimetableSetupError("Additional learning requires an instructional day or a configured day template.")
    if programme_id is not None:
        active_programmes = {
            int(item["programme_id"]) for item in occurrence["rotations"]
            if item.get("programme_id") is not None
        }
        if active_programmes and int(programme_id) not in active_programmes:
            raise TimetableSetupError("This learning programme is not active in the selected rotation week.")
    slots = occurrence["schedule_slots"]
    if not slots:
        raise TimetableSetupError("The selected date has no configured day template; dated sessions cannot be placed.")
    matching = [
        slot for slot in slots
        if str(slot["slot_type"]).lower() in allowed_types
        and str(slot["start_time"]) >= start and str(slot["end_time"]) <= end
    ]
    if not matching or str(matching[0]["start_time"]) != start or str(matching[-1]["end_time"]) != end:
        if schedule_layer == "instructional":
            raise TimetableSetupError("The session time does not match the selected date's instructional template.")
        layer_name = {
            "additional_learning": "remedial or study",
            "school_activity": "activity",
        }.get(schedule_layer, "configured")
        raise TimetableSetupError(
            f"The session time does not match the selected date's {layer_name} slots."
        )
    for previous, current in zip(matching, matching[1:]):
        if (str(previous["end_time"]) != str(current["start_time"])
                or int(current["slot_no"]) != int(previous["slot_no"]) + 1):
            raise TimetableSetupError("A session cannot span a break or non-teaching slot.")


def _validate_resources(cur: Any, school_id: int, profile_id: int,
                         class_ids: list[int], teacher_ids: list[int],
                         learner_ids: list[int], room_id: int | None,
                         start: str, end: str, day_id: int | None,
                         session_date: str | None, period_id: int | None,
                         schedule_layer: str, session_type: str,
                         duration_periods: int = 0) -> None:
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
        periods = cur.execute(
            """SELECT id,period_no,start_time,end_time,period_type
               FROM ds_timetable_periods
               WHERE school_id=? AND profile_id=? ORDER BY period_no,id""",
            (school_id, profile_id),
        ).fetchall()
        start_index = next((i for i, row in enumerate(periods) if int(row["id"]) == period_id), None)
        if start_index is None:
            raise TimetableSetupError("The selected period is outside this timetable profile.")
        duration = max(1, int(duration_periods or 1))
        span = periods[start_index:start_index + duration]
        if len(span) != duration or str(span[0]["start_time"]) != start or str(span[-1]["end_time"]) != end:
            raise TimetableSetupError("Session times must match the selected configured period span.")
        for index, slot in enumerate(span):
            if str(slot["period_type"] or "lesson") != "lesson":
                raise TimetableSetupError("Instructional sessions can only occupy teaching periods.")
            if index:
                previous = span[index - 1]
                if int(slot["period_no"]) != int(previous["period_no"]) + 1 or str(previous["end_time"]) != str(slot["start_time"]):
                    raise TimetableSetupError("An extended lesson must occupy consecutive periods without a break.")
        if day_id is not None:
            span_ids = [int(slot["id"]) for slot in span]
            marks = ",".join("?" for _ in span_ids)
            for teacher_id in teacher_ids:
                unavailable = cur.execute(
                    f"""SELECT period_id FROM ds_timetable_teacher_availability
                        WHERE school_id=? AND profile_id=? AND teacher_id=? AND day_id=?
                          AND availability='unavailable' AND period_id IN ({marks}) LIMIT 1""",
                    (school_id, profile_id, teacher_id, day_id, *span_ids),
                ).fetchone()
                if unavailable:
                    raise TimetableSetupError(f"Teacher {teacher_id} is marked unavailable during this session span.")
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


def _validate_constraints(cur: Any, school_id: int, profile_id: int,
                           schedule_layer: str, session_type: str,
                           subject_id: int | None, class_ids: list[int],
                           teacher_ids: list[int], room_id: int | None,
                           day_id: int | None, period_id: int | None,
                           start: str, end: str, session_date: str | None) -> None:
    rules = cur.execute(
        """SELECT * FROM ds_timetable_constraints
           WHERE school_id=? AND profile_id=? AND is_active=1
             AND constraint_type IN ('prohibit','require')
             AND (schedule_layer='all' OR schedule_layer=?)
             AND (applies_to='all' OR applies_to=? OR applies_to=?)""",
        (school_id, profile_id, schedule_layer, session_type,
         "lesson" if schedule_layer == "instructional" else
         "remedial" if schedule_layer == "additional_learning" else "activity"),
    ).fetchall()
    def minutes(value):
        return int(str(value)[:2]) * 60 + int(str(value)[3:])
    for rule in rules:
        if rule["subject_id"] is not None and int(rule["subject_id"]) != int(subject_id or 0):
            continue
        if rule["teacher_id"] is not None and int(rule["teacher_id"]) not in teacher_ids:
            continue
        if rule["class_id"] is not None and int(rule["class_id"]) not in class_ids:
            continue
        if rule["room_id"] is not None and int(rule["room_id"]) != int(room_id or 0):
            continue
        slot_matches = True
        has_slot_target = False
        if rule["day_id"] is not None:
            has_slot_target = True
            slot_matches = slot_matches and int(rule["day_id"]) == int(day_id or 0)
        if rule["period_id"] is not None:
            has_slot_target = True
            if period_id is None:
                slot_matches = False
            else:
                ordered = cur.execute(
                    """SELECT id,period_no FROM ds_timetable_periods
                       WHERE school_id=? AND profile_id=? ORDER BY period_no,id""",
                    (school_id, profile_id),
                ).fetchall()
                start_index = next((i for i, row in enumerate(ordered)
                                    if int(row["id"]) == int(period_id)), None)
                span_ids = []
                if start_index is not None:
                    periods = cur.execute(
                        """SELECT id,end_time FROM ds_timetable_periods
                           WHERE school_id=? AND profile_id=? AND period_no>=?
                           ORDER BY period_no,id""",
                        (school_id, profile_id, int(ordered[start_index]["period_no"])),
                    ).fetchall()
                    for item in periods:
                        span_ids.append(int(item["id"]))
                        if str(item["end_time"]) == end:
                            break
                slot_matches = slot_matches and int(rule["period_id"]) in span_ids
        if rule["start_time"] and rule["end_time"]:
            has_slot_target = True
            overlaps = minutes(start) < minutes(rule["end_time"]) and minutes(end) > minutes(rule["start_time"])
            slot_matches = slot_matches and overlaps
        if rule["effective_from"] or rule["effective_to"]:
            has_slot_target = True
            date_matches = bool(session_date)
            if session_date and rule["effective_from"]:
                date_matches = date_matches and session_date >= str(rule["effective_from"])
            if session_date and rule["effective_to"]:
                date_matches = date_matches and session_date <= str(rule["effective_to"])
            slot_matches = slot_matches and date_matches
        if not has_slot_target:
            continue
        reason = str(rule["reason"] or rule["name"])
        if rule["constraint_type"] == "prohibit" and slot_matches:
            raise TimetableSetupError(
                f"Scheduling constraint '{rule['name']}' blocks this session: {reason}"
            )
        if rule["constraint_type"] == "require" and not slot_matches:
            raise TimetableSetupError(
                f"Scheduling requirement '{rule['name']}' requires a different day or time: {reason}"
            )


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
                             scheduling_requirement_id: int | None = None,
                             pattern_session_no: int | None = None,
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
    if scheduling_requirement_id is not None:
        requirement = cur.execute(
            """SELECT * FROM ds_timetable_scheduling_requirements
               WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
            (int(scheduling_requirement_id), school_id, profile_id),
        ).fetchone()
        if not requirement:
            raise TimetableSetupError("Select an active scheduling requirement from this timetable profile.")
        if str(requirement["schedule_layer"]) != schedule_layer or str(requirement["session_type"]) != session_type:
            raise TimetableSetupError("The session layer and type must match its scheduling requirement.")
        req_classes = [int(r["class_id"]) for r in cur.execute(
            "SELECT class_id FROM ds_timetable_scheduling_requirement_classes WHERE requirement_id=? AND school_id=?",
            (int(scheduling_requirement_id), school_id),
        ).fetchall()]
        req_teachers = [int(r["teacher_id"]) for r in cur.execute(
            "SELECT teacher_id FROM ds_timetable_scheduling_requirement_teachers WHERE requirement_id=? AND school_id=?",
            (int(scheduling_requirement_id), school_id),
        ).fetchall()]
        req_learners = [int(r["student_id"]) for r in cur.execute(
            "SELECT student_id FROM ds_timetable_scheduling_requirement_learners WHERE requirement_id=? AND school_id=?",
            (int(scheduling_requirement_id), school_id),
        ).fetchall()]
        if classes and set(classes) != set(req_classes):
            raise TimetableSetupError("Session classes must match its scheduling requirement.")
        if teachers and set(teachers) != set(req_teachers):
            raise TimetableSetupError("Session teachers must match its assigned teaching team.")
        if learners and set(learners) != set(req_learners):
            raise TimetableSetupError("Session learners must match its scheduling requirement.")
        classes, teachers, learners = req_classes, req_teachers, req_learners
        if len(teachers) < int(requirement["min_teacher_count"] or 1):
            raise TimetableSetupError("The assigned teaching team does not meet the required teacher count.")
        if requirement["teaching_group_id"] is not None:
            if teaching_group_id is not None and int(teaching_group_id) != int(requirement["teaching_group_id"]):
                raise TimetableSetupError("Session teaching group does not match its scheduling requirement.")
            teaching_group_id = int(requirement["teaching_group_id"])
        if requirement["programme_id"] is not None:
            if programme_id is not None and int(programme_id) != int(requirement["programme_id"]):
                raise TimetableSetupError("Session programme does not match its scheduling requirement.")
            programme_id = int(requirement["programme_id"])
        if requirement["room_type"]:
            requested_room = cur.execute(
                "SELECT room_type FROM ds_timetable_rooms WHERE id=? AND school_id=? AND is_active=1",
                (room_id, school_id),
            ).fetchone() if room_id is not None else None
            if not requested_room or str(requested_room["room_type"]) != str(requirement["room_type"]):
                raise TimetableSetupError("This requirement needs a " + str(requirement["room_type"]) + " venue.")
        if pattern_session_no is not None:
            pattern = cur.execute(
                """SELECT duration_periods,duration_minutes FROM ds_timetable_scheduling_patterns
                   WHERE school_id=? AND profile_id=? AND requirement_id=? AND session_no=?""",
                (school_id, profile_id, int(scheduling_requirement_id), int(pattern_session_no)),
            ).fetchone()
            if not pattern:
                raise TimetableSetupError("Select a configured session number from this requirement's weekly pattern.")
            if int(pattern["duration_periods"] or 0) and int(duration_periods) != int(pattern["duration_periods"]):
                raise TimetableSetupError("Session period duration does not match its weekly pattern.")
            actual_minutes = (int(end_time[:2]) * 60 + int(end_time[3:])) - (int(start_time[:2]) * 60 + int(start_time[3:]))
            if pattern["duration_minutes"] is not None and actual_minutes != int(pattern["duration_minutes"]):
                raise TimetableSetupError("Session duration in minutes does not match its weekly pattern.")
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

    if schedule_layer == "instructional" and classes:
        for class_id in classes:
            limit = cur.execute(
                """SELECT max_lessons_per_week,max_periods_per_day
                   FROM ds_timetable_class_limits
                   WHERE school_id=? AND profile_id=? AND class_id=?""",
                (school_id, profile_id, class_id),
            ).fetchone()
            if not limit:
                continue
            legacy_week = int(cur.execute(
                """SELECT COUNT(*) FROM ds_timetable_lessons
                   WHERE school_id=? AND profile_id=? AND class_id=? AND status='scheduled'""",
                (school_id, profile_id, class_id),
            ).fetchone()[0] or 0)
            if session_date:
                dated = date.fromisoformat(session_date)
                week_start = (dated - timedelta(days=dated.weekday())).isoformat()
                week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
                normalized_week = int(cur.execute(
                    """SELECT COUNT(DISTINCT s.id) FROM ds_timetable_sessions s
                       JOIN ds_timetable_session_classes sc ON sc.session_id=s.id AND sc.school_id=s.school_id
                       WHERE s.school_id=? AND s.profile_id=? AND sc.class_id=?
                         AND s.schedule_layer='instructional' AND s.status='scheduled'
                         AND (s.session_date BETWEEN ? AND ? OR s.session_date IS NULL)""",
                    (school_id, profile_id, class_id, week_start, week_end),
                ).fetchone()[0] or 0)
            else:
                normalized_week = int(cur.execute(
                    """SELECT COUNT(DISTINCT s.id) FROM ds_timetable_sessions s
                       JOIN ds_timetable_session_classes sc ON sc.session_id=s.id AND sc.school_id=s.school_id
                       WHERE s.school_id=? AND s.profile_id=? AND sc.class_id=?
                         AND s.schedule_layer='instructional' AND s.status='scheduled'
                         AND s.session_date IS NULL""",
                    (school_id, profile_id, class_id),
                ).fetchone()[0] or 0)
            if limit["max_lessons_per_week"] is not None and legacy_week + normalized_week >= int(limit["max_lessons_per_week"]):
                raise TimetableSetupError("The class has reached its maximum number of lessons per week.")
            if day_id is not None and limit["max_periods_per_day"] is not None:
                legacy_daily = int(cur.execute(
                    """SELECT COALESCE(SUM(duration_periods),0) FROM ds_timetable_lessons
                       WHERE school_id=? AND profile_id=? AND class_id=? AND day_id=? AND status='scheduled'""",
                    (school_id, profile_id, class_id, day_id),
                ).fetchone()[0] or 0)
                if session_date:
                    normalized_daily = int(cur.execute(
                        """SELECT COALESCE(SUM(s.duration_periods),0) FROM ds_timetable_sessions s
                           JOIN ds_timetable_session_classes sc ON sc.session_id=s.id AND sc.school_id=s.school_id
                           WHERE s.school_id=? AND s.profile_id=? AND sc.class_id=? AND s.day_id=?
                             AND s.schedule_layer='instructional' AND s.status='scheduled'
                             AND (s.session_date=? OR s.session_date IS NULL)""",
                        (school_id, profile_id, class_id, day_id, session_date),
                    ).fetchone()[0] or 0)
                else:
                    normalized_daily = int(cur.execute(
                        """SELECT COALESCE(SUM(s.duration_periods),0) FROM ds_timetable_sessions s
                           JOIN ds_timetable_session_classes sc ON sc.session_id=s.id AND sc.school_id=s.school_id
                           WHERE s.school_id=? AND s.profile_id=? AND sc.class_id=? AND s.day_id=?
                             AND s.schedule_layer='instructional' AND s.status='scheduled'
                             AND s.session_date IS NULL""",
                        (school_id, profile_id, class_id, day_id),
                    ).fetchone()[0] or 0)
                if legacy_daily + normalized_daily + max(1, int(duration_periods or 1)) > int(limit["max_periods_per_day"]):
                    raise TimetableSetupError("This session would exceed the class maximum periods per day.")

    _validate_resources(
        cur, school_id, profile_id, classes, teachers, learners, room_id,
        start_time, end_time, day_id, session_date, period_id,
        schedule_layer, session_type, duration_periods,
    )
    _validate_calendar_session(
        cur, school_id, profile_id, session_date, day_id,
        start_time, end_time, schedule_layer, programme_id,
    )
    _validate_constraints(
        cur, school_id, profile_id, schedule_layer, session_type, subject_id,
        classes, teachers, room_id, day_id, period_id,
        start_time, end_time, session_date,
    )
    if programme_id is not None:
        programme = cur.execute(
            """SELECT id,schedule_layer FROM ds_timetable_learning_programmes
               WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
            (int(programme_id), school_id, profile_id),
        ).fetchone()
        if not programme:
            raise TimetableSetupError("Select an active programme belonging to this timetable profile.")
        if str(programme["schedule_layer"]) != schedule_layer:
            raise TimetableSetupError("The session layer must match the selected learning programme.")
        definitions = cur.execute(
            """SELECT required_teacher_count,room_type FROM ds_timetable_programme_sessions
               WHERE school_id=? AND profile_id=? AND programme_id=? AND is_active=1
                 AND (day_id IS NULL OR day_id=?) AND start_time=? AND end_time=?""",
            (school_id, profile_id, int(programme_id), day_id, start_time, end_time),
        ).fetchall()
        if definitions:
            required_count = max(int(row["required_teacher_count"] or 1) for row in definitions)
            if len(teachers) < required_count:
                raise TimetableSetupError(
                    f"This programme session requires at least {required_count} teachers."
                )
            required_room_types = {str(row["room_type"]) for row in definitions if row["room_type"]}
            if required_room_types:
                room = cur.execute(
                    "SELECT room_type FROM ds_timetable_rooms WHERE id=? AND school_id=? AND is_active=1",
                    (room_id, school_id),
                ).fetchone() if room_id is not None else None
                if not room or str(room["room_type"]) not in required_room_types:
                    raise TimetableSetupError(
                        "This programme session requires a venue of type " + " or ".join(sorted(required_room_types)) + "."
                    )
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
