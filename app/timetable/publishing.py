"""Timetable approval, publication, immutable snapshots and revisions."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.timetable.setup import TimetableSetupError


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_dict(row):
    return dict(row) if row is not None else None


def _snapshot(cursor, school_id: int, profile_id: int) -> dict:
    profile = cursor.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    if not profile:
        raise TimetableSetupError("Timetable profile not found.")
    snapshot = {"profile": _row_dict(profile)}
    queries = {
        "days": "SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? ORDER BY day_order,id",
        "periods": "SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id",
        "breaks": "SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=? ORDER BY break_no,id",
        "calendar_exceptions": "SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=? ORDER BY exception_date,id",
        "teacher_availability": "SELECT * FROM ds_timetable_teacher_availability WHERE school_id=? AND profile_id=? ORDER BY teacher_id,day_id,period_id",
        "requirements": "SELECT * FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=? ORDER BY class_id,subject_id,teacher_id",
        "lessons": "SELECT * FROM ds_timetable_lessons WHERE school_id=? AND profile_id=? AND status='scheduled' ORDER BY day_id,period_id,class_id,subject_id",
        "rooms": "SELECT * FROM ds_timetable_rooms WHERE school_id=? ORDER BY name,id",
        "class_limits": "SELECT * FROM ds_timetable_class_limits WHERE school_id=? AND profile_id=? ORDER BY class_id",
        "schedule_templates": "SELECT * FROM ds_timetable_schedule_templates WHERE school_id=? AND profile_id=? ORDER BY id",
        "schedule_slots": "SELECT * FROM ds_timetable_schedule_slots WHERE school_id=? AND profile_id=? ORDER BY template_id,slot_no",
        "day_templates": "SELECT * FROM ds_timetable_day_templates WHERE school_id=? AND profile_id=? ORDER BY day_id,cycle_week",
        "rotation_cycles": "SELECT * FROM ds_timetable_rotation_cycles WHERE school_id=? AND profile_id=? ORDER BY id",
        "rotation_weeks": "SELECT * FROM ds_timetable_rotation_weeks WHERE school_id=? AND profile_id=? ORDER BY cycle_id,week_number",
        "learning_programmes": "SELECT * FROM ds_timetable_learning_programmes WHERE school_id=? AND profile_id=? ORDER BY id",
        "teaching_groups": "SELECT * FROM ds_timetable_teaching_groups WHERE school_id=? AND profile_id=? ORDER BY id",
        "teaching_group_classes": "SELECT * FROM ds_timetable_teaching_group_classes WHERE school_id=? AND profile_id=? ORDER BY teaching_group_id,class_id",
        "requirement_patterns": "SELECT * FROM ds_timetable_requirement_patterns WHERE school_id=? AND profile_id=? ORDER BY requirement_id,session_no",
        "programme_sessions": "SELECT * FROM ds_timetable_programme_sessions WHERE school_id=? AND profile_id=? ORDER BY id",
        "scheduling_requirements": "SELECT * FROM ds_timetable_scheduling_requirements WHERE school_id=? AND profile_id=? ORDER BY id",
        "scheduling_requirement_classes": "SELECT * FROM ds_timetable_scheduling_requirement_classes WHERE school_id=? AND profile_id=? ORDER BY requirement_id,class_id",
        "scheduling_requirement_teachers": "SELECT * FROM ds_timetable_scheduling_requirement_teachers WHERE school_id=? AND profile_id=? ORDER BY requirement_id,teacher_id",
        "scheduling_requirement_learners": "SELECT * FROM ds_timetable_scheduling_requirement_learners WHERE school_id=? AND profile_id=? ORDER BY requirement_id,student_id",
        "scheduling_patterns": "SELECT * FROM ds_timetable_scheduling_patterns WHERE school_id=? AND profile_id=? ORDER BY requirement_id,session_no",
        "sessions": "SELECT * FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND status='scheduled' ORDER BY session_date,start_time,id",
        "session_classes": "SELECT * FROM ds_timetable_session_classes WHERE school_id=? AND profile_id=? ORDER BY session_id,class_id",
        "session_teachers": "SELECT * FROM ds_timetable_session_teachers WHERE school_id=? AND profile_id=? ORDER BY session_id,teacher_id",
        "session_learners": "SELECT * FROM ds_timetable_session_learners WHERE school_id=? AND profile_id=? ORDER BY session_id,student_id",
        "constraints": "SELECT * FROM ds_timetable_constraints WHERE school_id=? AND profile_id=? ORDER BY id",
    }
    for key, query in queries.items():
        snapshot[key] = [_row_dict(row) for row in cursor.execute(query, (school_id, profile_id) if key != "rooms" else (school_id,)).fetchall()]
    return snapshot



def _clone_advanced_profile_data(cur, school_id: int, source_profile_id: int, new_profile_id: int,
                                 day_map: dict[int, int], period_map: dict[int, int],
                                 class_requirement_map: dict[int, int]) -> None:
    """Clone normalized timetable configuration and sessions with all profile-local IDs remapped."""
    maps: dict[str, dict[int, int]] = {
        "ds_timetable_days": day_map,
        "ds_timetable_periods": period_map,
        "ds_timetable_class_requirements": class_requirement_map,
    }
    specs = [
        ("ds_timetable_class_limits", {}),
        ("ds_timetable_schedule_templates", {}),
        ("ds_timetable_schedule_slots", {"template_id": "ds_timetable_schedule_templates"}),
        ("ds_timetable_day_templates", {"day_id": "ds_timetable_days", "template_id": "ds_timetable_schedule_templates"}),
        ("ds_timetable_rotation_cycles", {}),
        ("ds_timetable_learning_programmes", {"rotation_cycle_id": "ds_timetable_rotation_cycles"}),
        ("ds_timetable_rotation_weeks", {"cycle_id": "ds_timetable_rotation_cycles", "programme_id": "ds_timetable_learning_programmes"}),
        ("ds_timetable_teaching_groups", {}),
        ("ds_timetable_teaching_group_classes", {"teaching_group_id": "ds_timetable_teaching_groups"}),
        ("ds_timetable_requirement_patterns", {"requirement_id": "ds_timetable_class_requirements", "preferred_day_id": "ds_timetable_days", "preferred_slot_id": "ds_timetable_schedule_slots"}),
        ("ds_timetable_programme_sessions", {"programme_id": "ds_timetable_learning_programmes", "teaching_group_id": "ds_timetable_teaching_groups", "day_id": "ds_timetable_days"}),
        ("ds_timetable_scheduling_requirements", {"programme_id": "ds_timetable_learning_programmes", "teaching_group_id": "ds_timetable_teaching_groups"}),
        ("ds_timetable_scheduling_requirement_classes", {"requirement_id": "ds_timetable_scheduling_requirements"}),
        ("ds_timetable_scheduling_requirement_teachers", {"requirement_id": "ds_timetable_scheduling_requirements"}),
        ("ds_timetable_scheduling_requirement_learners", {"requirement_id": "ds_timetable_scheduling_requirements"}),
        ("ds_timetable_scheduling_patterns", {"requirement_id": "ds_timetable_scheduling_requirements", "preferred_day_id": "ds_timetable_days", "preferred_slot_id": "ds_timetable_schedule_slots"}),
        ("ds_timetable_sessions", {"programme_id": "ds_timetable_learning_programmes", "teaching_group_id": "ds_timetable_teaching_groups", "day_id": "ds_timetable_days", "period_id": "ds_timetable_periods"}),
        ("ds_timetable_session_classes", {"session_id": "ds_timetable_sessions"}),
        ("ds_timetable_session_teachers", {"session_id": "ds_timetable_sessions"}),
        ("ds_timetable_session_learners", {"session_id": "ds_timetable_sessions"}),
        ("ds_timetable_constraints", {"day_id": "ds_timetable_days", "period_id": "ds_timetable_periods"}),
    ]
    for table, references in specs:
        source_rows = cur.execute(
            "SELECT * FROM " + table + " WHERE school_id=? AND profile_id=? ORDER BY id",
            (school_id, source_profile_id),
        ).fetchall()
        table_map: dict[int, int] = {}
        for source_row in source_rows:
            row = dict(source_row)
            old_id = int(row.pop("id"))
            row["profile_id"] = new_profile_id
            for column, referenced_table in references.items():
                value = row.get(column)
                if value is not None:
                    mapped = maps.get(referenced_table, {}).get(int(value))
                    if mapped is None:
                        raise TimetableSetupError(
                            "Cannot create a revision because a linked advanced timetable record is missing."
                        )
                    row[column] = mapped
            if table == "ds_timetable_sessions":
                row["generation_run_id"] = None
            columns = list(row.keys())
            placeholders = ",".join("?" for _ in columns)
            cur.execute(
                "INSERT INTO " + table + " (" + ",".join(columns) + ") VALUES (" + placeholders + ")",
                tuple(row[column] for column in columns),
            )
            new_row_id = int(cur.lastrowid or 0)
            if not new_row_id:
                found = cur.execute(
                    "SELECT MAX(id) AS id FROM " + table + " WHERE school_id=? AND profile_id=?",
                    (school_id, new_profile_id),
                ).fetchone()
                new_row_id = int(found["id"] or 0)
            if not new_row_id:
                raise TimetableSetupError("A timetable revision record could not be copied.")
            table_map[old_id] = new_row_id
        maps[table] = table_map




def _cross_profile_conflicts(cur, school_id: int, profile, candidate_session_ids=None) -> list[str]:
    """Detect teacher, class and room overlaps against other active programmes.

    A revision is compared with other independent programmes, not with its own
    currently-published predecessor; this keeps the normal revision workflow
    usable while still protecting the rest of the school's timetable.
    """
    root_id = int(profile["revision_of_profile_id"] or profile["id"])
    if profile["academic_start_date"] and profile["academic_end_date"]:
        other_profiles = cur.execute(
            """SELECT id,name,profile_type FROM ds_timetable_profiles
               WHERE school_id=? AND status IN ('published','pending_approval')
                 AND COALESCE(revision_of_profile_id,id)<>?
                 AND (
                   (academic_start_date IS NOT NULL AND academic_end_date IS NOT NULL
                    AND academic_start_date<=? AND academic_end_date>=?)
                   OR ((academic_start_date IS NULL OR academic_end_date IS NULL)
                       AND academic_year=? AND term=?)
                 )""",
            (school_id, root_id, profile["academic_end_date"], profile["academic_start_date"],
             profile["academic_year"], profile["term"]),
        ).fetchall()
    else:
        other_profiles = cur.execute(
            """SELECT id,name,profile_type FROM ds_timetable_profiles
               WHERE school_id=? AND academic_year=? AND term=?
                 AND status IN ('published','pending_approval')
                 AND COALESCE(revision_of_profile_id,id)<>?""",
            (school_id, profile["academic_year"], profile["term"], root_id),
        ).fetchall()
    other_ids = [int(row["id"]) for row in other_profiles]
    if not other_ids:
        return []
    placeholders = ",".join("?" for _ in other_ids)

    def placements(profile_ids, session_ids=None):
        found = []
        lesson_rows = cur.execute(
            """SELECT l.class_id,l.teacher_id,l.room_id,d.day_code,NULL AS session_date,
                      p.start_time,p.end_time
               FROM ds_timetable_lessons l
               JOIN ds_timetable_days d ON d.id=l.day_id AND d.profile_id=l.profile_id
               JOIN ds_timetable_periods p ON p.id=l.period_id AND p.profile_id=l.profile_id
               WHERE l.school_id=? AND l.profile_id IN (""" + ",".join("?" for _ in profile_ids) + """)
                 AND l.status='scheduled'""",
            (school_id, *profile_ids),
        ).fetchall()
        for row in lesson_rows:
            found.append({
                "day_code": str(row["day_code"] or "").upper(),
                "session_date": None,
                "start": str(row["start_time"]),
                "end": str(row["end_time"]),
                "classes": {int(row["class_id"])},
                "teachers": {int(row["teacher_id"])},
                "rooms": {int(row["room_id"])} if row["room_id"] is not None else set(),
            })
        session_id_filter = ""
        session_id_params = ()
        if session_ids is not None:
            if session_ids:
                session_id_filter = " AND s.id IN (" + ",".join("?" for _ in session_ids) + ")"
                session_id_params = tuple(int(value) for value in session_ids)
            else:
                session_id_filter = " AND 1=0"
        session_rows = cur.execute(
            """SELECT s.id,s.day_id,s.session_date,s.start_time,s.end_time,s.room_id,d.day_code
               FROM ds_timetable_sessions s
               LEFT JOIN ds_timetable_days d ON d.id=s.day_id AND d.profile_id=s.profile_id
               WHERE s.school_id=? AND s.profile_id IN (""" + ",".join("?" for _ in profile_ids) + """)
                 AND s.status='scheduled'""" + session_id_filter,
            (school_id, *profile_ids, *session_id_params),
        ).fetchall()
        for row in session_rows:
            sid = int(row["id"])
            classes = {int(x["class_id"]) for x in cur.execute(
                "SELECT class_id FROM ds_timetable_session_classes WHERE school_id=? AND session_id=?",
                (school_id, sid),
            ).fetchall()}
            teachers = {int(x["teacher_id"]) for x in cur.execute(
                "SELECT teacher_id FROM ds_timetable_session_teachers WHERE school_id=? AND session_id=?",
                (school_id, sid),
            ).fetchall()}
            learner_ids = [int(x["student_id"]) for x in cur.execute(
                "SELECT student_id FROM ds_timetable_session_learners WHERE school_id=? AND session_id=?",
                (school_id, sid),
            ).fetchall()]
            if learner_ids:
                learner_marks = ",".join("?" for _ in learner_ids)
                classes.update(int(x["class_id"]) for x in cur.execute(
                    "SELECT DISTINCT class_id FROM students WHERE school_id=? AND id IN (" + learner_marks + ") AND class_id IS NOT NULL",
                    (school_id, *learner_ids),
                ).fetchall())
            day_code = str(row["day_code"] or "").upper()
            session_date = str(row["session_date"] or "")
            if session_date:
                try:
                    day_code = datetime.strptime(session_date, "%Y-%m-%d").strftime("%a").upper()
                except ValueError:
                    pass
            found.append({
                "day_code": day_code,
                "session_date": session_date or None,
                "start": str(row["start_time"]),
                "end": str(row["end_time"]),
                "classes": classes,
                "teachers": teachers,
                "rooms": {int(row["room_id"])} if row["room_id"] is not None else set(),
            })
        return found

    candidate = placements([int(profile["id"])], candidate_session_ids)
    existing = placements(other_ids)
    conflicts = []
    for first in candidate:
        for second in existing:
            if not first["day_code"] or first["day_code"] != second["day_code"]:
                continue
            if first["session_date"] and second["session_date"] and first["session_date"] != second["session_date"]:
                continue
            if not (first["start"] < second["end"] and first["end"] > second["start"]):
                continue
            if first["teachers"] & second["teachers"]:
                conflicts.append("A teacher is scheduled in overlapping lessons across independent timetables.")
            if first["classes"] & second["classes"]:
                conflicts.append("A class or learner group is scheduled in overlapping lessons across independent timetables.")
            if first["rooms"] & second["rooms"]:
                conflicts.append("A room is assigned to overlapping lessons across independent timetables.")
    return list(dict.fromkeys(conflicts))


def validate_timetable_for_publication(connection: Any, school_id: int, profile_id: int) -> dict:
    cur = connection.cursor()
    profile = cur.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    if not profile:
        raise TimetableSetupError("Select a timetable profile belonging to this school.")
    errors = []
    is_main_profile = str(profile["profile_type"] or "main").strip().lower() == "main"
    advanced_layer_filter = "schedule_layer='instructional'" if is_main_profile else "schedule_layer IN ('instructional','additional_learning')"
    if profile["status"] not in ("draft", "pending_approval"):
        errors.append("Only a draft or pending-approval timetable can be published.")
    active_run = cur.execute(
        "SELECT id FROM ds_timetable_generation_runs WHERE school_id=? AND profile_id=? AND status='running' LIMIT 1",
        (school_id, profile_id),
    ).fetchone()
    if active_run:
        errors.append("Automatic timetable generation is still running.")
    days = cur.execute(
        "SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? AND is_instructional=1",
        (school_id, profile_id),
    ).fetchall()
    periods = cur.execute(
        "SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id",
        (school_id, profile_id),
    ).fetchall()
    requirements = cur.execute(
        "SELECT * FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall()
    advanced_requirements = cur.execute(
        """SELECT * FROM ds_timetable_scheduling_requirements
           WHERE school_id=? AND profile_id=? AND is_active=1 AND """ + advanced_layer_filter + " ORDER BY id",
        (school_id, profile_id),
    ).fetchall()
    advanced_sessions = cur.execute(
        """SELECT * FROM ds_timetable_sessions
           WHERE school_id=? AND profile_id=? AND status='scheduled' AND """ + advanced_layer_filter + " ORDER BY id",
        (school_id, profile_id),
    ).fetchall()
    session_classes = {}
    for row in cur.execute(
        "SELECT session_id,class_id FROM ds_timetable_session_classes WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall():
        session_classes.setdefault(int(row["session_id"]), []).append(int(row["class_id"]))
    session_teachers = {}
    for row in cur.execute(
        "SELECT session_id,teacher_id FROM ds_timetable_session_teachers WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall():
        session_teachers.setdefault(int(row["session_id"]), []).append(int(row["teacher_id"]))
    session_learners = {}
    for row in cur.execute(
        "SELECT session_id,student_id FROM ds_timetable_session_learners WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall():
        session_learners.setdefault(int(row["session_id"]), []).append(int(row["student_id"]))
    advanced_coverage = set()
    advanced_required_lessons = 0
    advanced_required_periods = 0
    advanced_requirement_signatures = []
    for requirement in advanced_requirements:
        rid = int(requirement["id"])
        class_ids = tuple(sorted(int(row["class_id"]) for row in cur.execute(
            "SELECT class_id FROM ds_timetable_scheduling_requirement_classes WHERE school_id=? AND profile_id=? AND requirement_id=?",
            (school_id, profile_id, rid),
        ).fetchall()))
        teacher_ids = tuple(sorted(int(row["teacher_id"]) for row in cur.execute(
            "SELECT teacher_id FROM ds_timetable_scheduling_requirement_teachers WHERE school_id=? AND profile_id=? AND requirement_id=?",
            (school_id, profile_id, rid),
        ).fetchall()))
        learner_ids = tuple(sorted(int(row["student_id"]) for row in cur.execute(
            "SELECT student_id FROM ds_timetable_scheduling_requirement_learners WHERE school_id=? AND profile_id=? AND requirement_id=?",
            (school_id, profile_id, rid),
        ).fetchall()))
        patterns = cur.execute(
            "SELECT duration_periods FROM ds_timetable_scheduling_patterns WHERE school_id=? AND profile_id=? AND requirement_id=? ORDER BY session_no",
            (school_id, profile_id, rid),
        ).fetchall()
        if not class_ids and not learner_ids:
            errors.append("A combined teaching requirement has no linked classes or learners.")
        if not teacher_ids:
            errors.append("A combined teaching requirement has no assigned teacher.")
        if not patterns:
            errors.append("A combined teaching requirement has no weekly session pattern.")
        subject_id = int(requirement["subject_id"]) if requirement["subject_id"] is not None else None
        if subject_id is not None:
            for class_id in class_ids:
                for teacher_id in teacher_ids:
                    advanced_coverage.add((class_id, subject_id, teacher_id))
        expected_durations = sorted(int(row["duration_periods"] or 1) for row in patterns)
        advanced_required_lessons += len(expected_durations)
        advanced_required_periods += sum(expected_durations)
        advanced_requirement_signatures.append((class_ids, teacher_ids, learner_ids, subject_id, expected_durations,
                                                  int(requirement["teaching_group_id"]) if requirement["teaching_group_id"] is not None else None))
    if not days:
        errors.append("Configure at least one instructional day.")
    if not any(str(p["period_type"] or "lesson") == "lesson" for p in periods):
        errors.append("Configure at least one teaching period.")
    allocations = cur.execute(
        """SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id
           FROM teacher_allocations ta
           JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
           JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
           JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
           WHERE ta.school_id=?""",
        (school_id,),
    ).fetchall()
    allocation_keys = {(int(a["class_id"]),int(a["subject_id"]),int(a["teacher_id"])) for a in allocations}
    requirement_map = {
        (int(r["class_id"]),int(r["subject_id"]),int(r["teacher_id"])): r
        for r in requirements
    }
    if is_main_profile:
        for key in sorted(allocation_keys - set(requirement_map) - advanced_coverage):
            errors.append("A current class/subject/teacher allocation is missing its weekly lesson requirement.")
            break
        for key in sorted(set(requirement_map) - allocation_keys):
            errors.append("A weekly requirement no longer matches a current teacher allocation.")
            break

    breaks = cur.execute(
        "SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall()
    unavailable = {
        (int(r["teacher_id"]),int(r["day_id"]),int(r["period_id"]))
        for r in cur.execute(
            """SELECT teacher_id,day_id,period_id FROM ds_timetable_teacher_availability
               WHERE school_id=? AND profile_id=? AND availability='unavailable'""",
            (school_id, profile_id),
        ).fetchall()
    }
    room_ids = {
        int(r["id"]) for r in cur.execute(
            "SELECT id FROM ds_timetable_rooms WHERE school_id=? AND is_active=1",
            (school_id,),
        ).fetchall()
    }
    lessons = cur.execute(
        """SELECT * FROM ds_timetable_lessons
           WHERE school_id=? AND profile_id=? AND status='scheduled'""",
        (school_id, profile_id),
    ).fetchall()
    period_index = {int(p["id"]):i for i,p in enumerate(periods)}
    day_ids = {int(d["id"]) for d in days}
    lesson_counts = {}
    daily_counts = {}
    placements = []
    for lesson in lessons:
        key = (int(lesson["class_id"]),int(lesson["subject_id"]),int(lesson["teacher_id"]))
        # Weekly requirements are measured in occupied teaching periods.
        # A double/triple block must therefore contribute its full duration,
        # while daily max-lesson rules continue to count lesson occurrences.
        duration = int(lesson["duration_periods"] or 1)
        lesson_counts[key] = lesson_counts.get(key,0) + duration
        daily_key = key + (int(lesson["day_id"]),)
        daily_counts[daily_key] = daily_counts.get(daily_key,0) + 1
        if is_main_profile and key not in allocation_keys:
            errors.append("A scheduled lesson references a class/subject/teacher combination that is no longer allocated.")
        day_id = int(lesson["day_id"])
        if day_id not in day_ids:
            errors.append("A scheduled lesson is placed on a non-instructional or invalid day.")
            continue
        start_index = period_index.get(int(lesson["period_id"]))
        if start_index is None:
            errors.append("A scheduled lesson references a period outside this timetable profile.")
            continue
        span = periods[start_index:start_index + duration]
        valid_span = len(span) == duration
        if valid_span:
            for i, period in enumerate(span):
                if str(period["period_type"] or "lesson") != "lesson":
                    valid_span = False
                    break
                if i and (
                    int(period["period_no"]) != int(span[i-1]["period_no"]) + 1
                    or str(span[i-1]["end_time"]) != str(period["start_time"])
                ):
                    valid_span = False
                    break
        if not valid_span:
            errors.append("A scheduled multi-period lesson is not consecutive or crosses a non-teaching period.")
            continue
        if any((int(lesson["teacher_id"]),day_id,int(p["id"])) in unavailable for p in span):
            errors.append("A scheduled lesson falls inside a teacher's unavailable time.")
        if any(
            str(span[0]["start_time"]) < str(b["end_time"])
            and str(span[-1]["end_time"]) > str(b["start_time"])
            for b in breaks
        ):
            errors.append("A scheduled lesson overlaps a configured break.")
        room_id = int(lesson["room_id"]) if lesson["room_id"] is not None else None
        if room_id is not None and room_id not in room_ids:
            errors.append("A scheduled lesson uses an inactive or invalid room.")
        placements.append({
            "class_id":key[0],"subject_id":key[1],"teacher_id":key[2],"room_id":room_id,
            "class_ids":[key[0]],"teacher_ids":[key[2]],
            "day_id":day_id,"day_key":"day:"+str(day_id),
            "start_time":str(span[0]["start_time"]),"end_time":str(span[-1]["end_time"]),
            "start_index":start_index,"end_index":start_index + duration - 1,
        })

    period_by_start = {str(period["start_time"]): index for index, period in enumerate(periods)}
    advanced_session_durations = []
    for session in advanced_sessions:
        session_id = int(session["id"])
        class_ids = sorted(set(session_classes.get(session_id, [])))
        teacher_ids = sorted(set(session_teachers.get(session_id, [])))
        learner_ids = sorted(set(session_learners.get(session_id, [])))
        effective_class_ids = list(class_ids)
        if learner_ids:
            learner_marks = ",".join("?" for _ in learner_ids)
            effective_class_ids.extend(int(row["class_id"]) for row in cur.execute(
                "SELECT DISTINCT class_id FROM students WHERE school_id=? AND id IN (" + learner_marks + ") AND class_id IS NOT NULL",
                (school_id, *learner_ids),
            ).fetchall())
            effective_class_ids = sorted(set(effective_class_ids))
        if not class_ids and not learner_ids:
            errors.append("A scheduled combined session has no linked classes or learners.")
        if not teacher_ids:
            errors.append("A scheduled combined session has no assigned teacher.")
        if session["day_id"] is not None and int(session["day_id"]) not in day_ids:
            errors.append("A combined session is placed on a non-instructional or invalid day.")
            continue
        duration = max(1, int(session["duration_periods"] or 1))
        start_index = period_index.get(int(session["period_id"])) if session["period_id"] is not None else period_by_start.get(str(session["start_time"]))
        end_index = start_index + duration - 1 if start_index is not None else None
        if start_index is not None and (end_index >= len(periods) or any(
            str(periods[index]["period_type"] or "lesson") != "lesson"
            or (index > start_index and (
                int(periods[index]["period_no"]) != int(periods[index-1]["period_no"]) + 1
                or str(periods[index-1]["end_time"]) != str(periods[index]["start_time"])
            ))
            for index in range(start_index, end_index + 1)
        )):
            errors.append("A combined multi-period session is not consecutive or crosses a non-teaching period.")
        if session["day_id"] is not None and start_index is not None:
            occupied_periods = periods[start_index:end_index + 1]
            if any((teacher_id, int(session["day_id"]), int(period["id"])) in unavailable
                   for teacher_id in teacher_ids for period in occupied_periods):
                errors.append("A combined session falls inside a teacher's unavailable time.")
        if any(
            str(session["start_time"]) < str(br["end_time"])
            and str(session["end_time"]) > str(br["start_time"])
            for br in breaks
        ):
            errors.append("A combined session overlaps a configured break.")
        room_id = int(session["room_id"]) if session["room_id"] is not None else None
        if room_id is not None and room_id not in room_ids:
            errors.append("A combined session uses an inactive or invalid room.")
        day_id = int(session["day_id"]) if session["day_id"] is not None else None
        day_key = ("date:"+str(session["session_date"])) if session["session_date"] else ("day:"+str(day_id))
        placements.append({
            "class_id":class_ids[0] if class_ids else 0,
            "subject_id":int(session["subject_id"]) if session["subject_id"] is not None else 0,
            "teacher_id":teacher_ids[0] if teacher_ids else 0,
            "class_ids":effective_class_ids,"teacher_ids":teacher_ids,
            "room_id":room_id,"day_id":day_id,"day_key":day_key,
            "start_time":str(session["start_time"]),"end_time":str(session["end_time"]),
            "start_index":start_index,"end_index":end_index,
        })
        advanced_session_durations.append(duration)

    for class_ids, teacher_ids, learner_ids, subject_id, expected_durations, group_id in advanced_requirement_signatures:
        matched = []
        for session in advanced_sessions:
            sid = int(session["id"])
            if group_id is not None and (session["teaching_group_id"] is None or int(session["teaching_group_id"]) != group_id):
                continue
            if (int(session["subject_id"]) if session["subject_id"] is not None else None) != subject_id:
                continue
            if tuple(sorted(set(session_classes.get(sid, [])))) != class_ids:
                continue
            if tuple(sorted(set(session_teachers.get(sid, [])))) != teacher_ids:
                continue
            if tuple(sorted(set(session_learners.get(sid, [])))) != learner_ids:
                continue
            matched.append(max(1, int(session["duration_periods"] or 1)))
        if sorted(matched) != expected_durations:
            errors.append("A combined teaching requirement is not fully scheduled according to its weekly session pattern.")

    for key, requirement in requirement_map.items():
        actual = lesson_counts.get(key,0)
        expected = (
            int(requirement["lessons_per_week"] or 0)
            * int(requirement["duration_periods"] or 1)
        )
        if actual != expected:
            errors.append(
                "A weekly requirement is not fully scheduled (class ID %s, subject ID %s: %s of %s required periods)."
                % (key[0],key[1],actual,expected)
            )
        max_per_day = int(requirement["max_lessons_per_day"]) if requirement["max_lessons_per_day"] is not None else 0
        if max_per_day and any(
            count > max_per_day for daily_key, count in daily_counts.items() if daily_key[:3] == key
        ):
            errors.append("A subject exceeds its configured maximum number of lessons on a day.")
    for i, first in enumerate(placements):
        for second in placements[i+1:]:
            if first["day_key"] != second["day_key"]:
                continue
            if first["start_time"] >= second["end_time"] or first["end_time"] <= second["start_time"]:
                continue
            if set(first["class_ids"]) & set(second["class_ids"]):
                errors.append("Two lessons overlap for the same class.")
            if set(first["teacher_ids"]) & set(second["teacher_ids"]):
                errors.append("A teacher is assigned to overlapping lessons.")
            if first["room_id"] is not None and second["room_id"] is not None and first["room_id"] == second["room_id"]:
                errors.append("A room is assigned to overlapping lessons.")
    # One combined placement may contain several linked classes; that is not
    # a self-conflict. Separate placements still obey teacher spacing rules.
    for i, first in enumerate(placements):
        for second in placements[i+1:]:
            if first["day_key"] != second["day_key"]:
                continue
            if not (set(first["teacher_ids"]) & set(second["teacher_ids"])):
                continue
            if not (set(first["class_ids"]) & set(second["class_ids"])):
                continue
            if first["subject_id"] == second["subject_id"]:
                continue
            if first["end_index"] is None or second["start_index"] is None:
                continue
            if first["end_index"] + 1 == second["start_index"] or second["end_index"] + 1 == first["start_index"]:
                errors.append("A teacher cannot teach different subjects to the same class in consecutive periods.")
    errors.extend(_cross_profile_conflicts(cur, school_id, profile))
    errors = list(dict.fromkeys(errors))
    return {
        "ready": not errors,
        "errors": errors,
        # Readiness metrics use occupied periods, while the validation above
        # continues to compare lesson occurrences against weekly requirements.
        "scheduled_lessons": len(lessons) + len(advanced_sessions),
        "required_lessons": sum(int(r["lessons_per_week"] or 0) for r in requirements) + advanced_required_lessons,
        "scheduled_periods": sum(int(lesson["duration_periods"] or 1) for lesson in lessons) + sum(advanced_session_durations),
        "required_periods": sum(
            int(r["lessons_per_week"] or 0) * int(r["duration_periods"] or 1)
            for r in requirements
        ) + advanced_required_periods,
        "requirements": len(requirements) + len(advanced_requirements),
    }


def submit_for_approval(connection: Any, school_id: int, profile_id: int, actor: str = "") -> dict:
    cur = connection.cursor()
    profile = cur.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    if not profile or profile["status"] != "draft":
        raise TimetableSetupError("Only a draft timetable can be submitted for approval.")
    readiness = validate_timetable_for_publication(connection, school_id, profile_id)
    if not readiness["ready"]:
        raise TimetableSetupError("Timetable is not ready for approval: " + " ".join(readiness["errors"][:4]))
    now = _now()
    cur.execute(
        """UPDATE ds_timetable_profiles
           SET status='pending_approval',updated_at=?
           WHERE id=? AND school_id=? AND status='draft'""",
        (now,profile_id,school_id),
    )
    if getattr(cur, "rowcount", 0) != 1:
        connection.rollback()
        raise TimetableSetupError(
            "The timetable status was not changed. Refresh the profile and try submitting again."
        )
    cur.execute(
        """INSERT INTO ds_timetable_change_log
           (school_id,profile_id,action,before_json,after_json,changed_by,changed_at)
           VALUES(?,?,?,?,?,?,?)""",
        (school_id,profile_id,"SUBMIT_FOR_APPROVAL",json.dumps({"status":"draft"}),json.dumps({"status":"pending_approval"}),actor,now),
    )
    saved = cur.execute(
        "SELECT status FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id,school_id),
    ).fetchone()
    if not saved or str(saved["status"]) != "pending_approval":
        connection.rollback()
        raise TimetableSetupError(
            "The database did not save the pending-approval status. No submission was recorded."
        )
    connection.commit()
    persisted = cur.execute(
        "SELECT status FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id,school_id),
    ).fetchone()
    if not persisted or str(persisted["status"]) != "pending_approval":
        raise TimetableSetupError(
            "The submission could not be verified after saving. Please refresh and try again."
        )
    return readiness


def publish_timetable(connection: Any, school_id: int, profile_id: int, actor: str = "") -> dict:
    cur = connection.cursor()
    profile = cur.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id,school_id),
    ).fetchone()
    if not profile or profile["status"] != "pending_approval":
        raise TimetableSetupError("Submit this timetable for approval before publishing it.")
    readiness = validate_timetable_for_publication(connection,school_id,profile_id)
    if not readiness["ready"]:
        raise TimetableSetupError("Timetable is not ready to publish: " + " ".join(readiness["errors"][:4]))
    snapshot = _snapshot(cur,school_id,profile_id)
    version_no = cur.execute(
        "SELECT COALESCE(MAX(version_no),0)+1 AS next_no FROM ds_timetable_versions WHERE school_id=? AND profile_id=?",
        (school_id,profile_id),
    ).fetchone()["next_no"]
    now = _now()
    revision_no = int(profile["revision_no"] or 1)
    label = "Revision %s — Published" % revision_no
    cur.execute(
        """INSERT INTO ds_timetable_versions
           (school_id,profile_id,version_no,label,snapshot_json,created_by,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (school_id,profile_id,int(version_no),label,json.dumps(snapshot,default=str,sort_keys=True),actor,now),
    )
    version_id = int(cur.lastrowid or 0)
    if not version_id:
        version_id = int(cur.execute(
            "SELECT id FROM ds_timetable_versions WHERE school_id=? AND profile_id=? AND version_no=?",
            (school_id,profile_id,int(version_no)),
        ).fetchone()["id"])
    # A newly published revision becomes current; previous published revisions
    # remain archived and fully viewable for audit/history.
    revision_root_id = int(profile["revision_of_profile_id"] or profile["id"])
    previous = cur.execute(
        """SELECT id FROM ds_timetable_profiles
           WHERE school_id=? AND status='published' AND id<>?
             AND COALESCE(revision_of_profile_id,id)=?""",
        (school_id,profile_id,revision_root_id),
    ).fetchall()
    for old in previous:
        cur.execute(
            "UPDATE ds_timetable_profiles SET status='archived',updated_at=? WHERE id=? AND school_id=?",
            (now,int(old["id"]),school_id),
        )
        cur.execute(
            """INSERT INTO ds_timetable_change_log
               (school_id,profile_id,action,before_json,after_json,changed_by,changed_at)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id,int(old["id"]),"PROFILE_ARCHIVE",json.dumps({"status":"published"}),json.dumps({"status":"archived"}),actor,now),
        )
    cur.execute(
        """UPDATE ds_timetable_profiles
           SET status='published',approved_by=?,approved_at=?,published_by=?,published_at=?,current_version_id=?,updated_at=?
           WHERE id=? AND school_id=?""",
        (actor,now,actor,now,version_id,now,profile_id,school_id),
    )
    cur.execute(
        """INSERT INTO ds_timetable_change_log
           (school_id,profile_id,action,before_json,after_json,changed_by,changed_at)
           VALUES(?,?,?,?,?,?,?)""",
        (school_id,profile_id,"PUBLISH",json.dumps({"status":"pending_approval"}),json.dumps({"status":"published","version_id":version_id,"version_no":int(version_no)}),actor,now),
    )
    connection.commit()
    return {"version_id":version_id,"version_no":int(version_no),"readiness":readiness}


def create_revision(connection: Any, school_id: int, source_profile_id: int, actor: str = "") -> int:
    cur = connection.cursor()
    source = cur.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (source_profile_id,school_id),
    ).fetchone()
    if not source or source["status"] not in ("published","archived"):
        raise TimetableSetupError("Only a published or archived timetable can be used to create a revision.")
    root_id = int(source["revision_of_profile_id"] or source["id"])
    max_revision = cur.execute(
        """SELECT COALESCE(MAX(revision_no),1) AS max_no FROM ds_timetable_profiles
           WHERE school_id=? AND (id=? OR revision_of_profile_id=?)""",
        (school_id,root_id,root_id),
    ).fetchone()["max_no"]
    revision_no = int(max_revision or 1) + 1
    now = _now()
    name = str(source["name"] or "Timetable").split(" · Revision ")[0] + " · Revision " + str(revision_no)
    cur.execute(
        """INSERT INTO ds_timetable_profiles
           (school_id,name,academic_year,term,profile_type,status,week_start,week_end,academic_start_date,academic_end_date,
            settings_json,created_by,created_at,updated_at,revision_no,revision_of_profile_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            school_id,name,source["academic_year"],source["term"],source["profile_type"] or "main","draft",source["week_start"],source["week_end"],
            source["academic_start_date"],source["academic_end_date"],source["settings_json"],actor,now,now,
            revision_no,root_id,
        ),
    )
    new_id = int(cur.lastrowid or 0)
    if not new_id:
        new_id = int(cur.execute(
            "SELECT id FROM ds_timetable_profiles WHERE school_id=? AND name=? AND created_at=? ORDER BY id DESC LIMIT 1",
            (school_id,name,now),
        ).fetchone()["id"])
    day_map = {}
    period_map = {}
    for row in cur.execute("SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? ORDER BY day_order,id",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_days (school_id,profile_id,day_code,day_name,day_order,is_instructional)
               VALUES(?,?,?,?,?,?)""",
            (school_id,new_id,row["day_code"],row["day_name"],row["day_order"],row["is_instructional"]),
        )
        new_day_id = int(cur.lastrowid or 0)
        if not new_day_id:
            new_day_id = int(cur.execute(
                "SELECT id FROM ds_timetable_days WHERE school_id=? AND profile_id=? AND day_code=?",
                (school_id,new_id,row["day_code"]),
            ).fetchone()["id"])
        day_map[int(row["id"])] = new_day_id
    for row in cur.execute("SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_periods
               (school_id,profile_id,period_no,label,start_time,end_time,period_type,duration_minutes)
               VALUES(?,?,?,?,?,?,?,?)""",
            (school_id,new_id,row["period_no"],row["label"],row["start_time"],row["end_time"],row["period_type"],row["duration_minutes"]),
        )
        new_period_id = int(cur.lastrowid or 0)
        if not new_period_id:
            new_period_id = int(cur.execute(
                "SELECT id FROM ds_timetable_periods WHERE school_id=? AND profile_id=? AND period_no=?",
                (school_id,new_id,row["period_no"]),
            ).fetchone()["id"])
        period_map[int(row["id"])] = new_period_id
    for row in cur.execute("SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=?",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_breaks (school_id,profile_id,break_no,label,start_time,end_time,applies_to)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id,new_id,row["break_no"],row["label"],row["start_time"],row["end_time"],row["applies_to"]),
        )
    for row in cur.execute("SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=?",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_calendar_exceptions
               (school_id,profile_id,exception_date,label,exception_type,notes,is_instructional)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id,new_id,row["exception_date"],row["label"],row["exception_type"],row["notes"],row["is_instructional"]),
        )
    for row in cur.execute("SELECT * FROM ds_timetable_teacher_availability WHERE school_id=? AND profile_id=?",(school_id,source_profile_id)).fetchall():
        if int(row["day_id"]) not in day_map or int(row["period_id"]) not in period_map:
            continue
        cur.execute(
            """INSERT INTO ds_timetable_teacher_availability
               (school_id,profile_id,teacher_id,day_id,period_id,availability,reason)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id,new_id,row["teacher_id"],day_map[int(row["day_id"])],period_map[int(row["period_id"])],row["availability"],row["reason"]),
        )
    class_requirement_map = {}
    for row in cur.execute("SELECT * FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=?",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_class_requirements
               (school_id,profile_id,class_id,subject_id,teacher_id,lessons_per_week,duration_periods,max_lessons_per_day,min_gap_periods,allow_double,preferred_days_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (school_id,new_id,row["class_id"],row["subject_id"],row["teacher_id"],row["lessons_per_week"],row["duration_periods"],row["max_lessons_per_day"],row["min_gap_periods"],row["allow_double"],row["preferred_days_json"]),
        )
        copied_requirement = cur.execute(
            "SELECT id FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=?",
            (school_id,new_id,row["class_id"],row["subject_id"],row["teacher_id"]),
        ).fetchone()
        class_requirement_map[int(row["id"])] = int(copied_requirement["id"])
    _clone_advanced_profile_data(cur, school_id, source_profile_id, new_id, day_map, period_map, class_requirement_map)
    for row in cur.execute("SELECT * FROM ds_timetable_lessons WHERE school_id=? AND profile_id=? AND status='scheduled'",(school_id,source_profile_id)).fetchall():
        if int(row["day_id"]) not in day_map or int(row["period_id"]) not in period_map:
            continue
        cur.execute(
            """INSERT INTO ds_timetable_lessons
               (school_id,profile_id,class_id,subject_id,teacher_id,room_id,day_id,period_id,duration_periods,lesson_group,generation_run_id,status,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,NULL,'scheduled',?,?,?)""",
            (
                school_id,new_id,row["class_id"],row["subject_id"],row["teacher_id"],row["room_id"],
                day_map[int(row["day_id"])],period_map[int(row["period_id"])],row["duration_periods"],row["lesson_group"],
                actor,now,now,
            ),
        )
    cur.execute(
        """INSERT INTO ds_timetable_change_log
           (school_id,profile_id,action,before_json,after_json,changed_by,changed_at)
           VALUES(?,?,?,?,?,?,?)""",
        (school_id,new_id,"PROFILE_REVISION_CREATE",json.dumps({"source_profile_id":source_profile_id}),json.dumps({"revision_no":revision_no,"revision_of_profile_id":root_id}),actor,now),
    )
    connection.commit()
    return new_id


def list_profile_versions(connection: Any, school_id: int, profile_id: int):
    cur = connection.cursor()
    profile = cur.execute("SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",(profile_id,school_id)).fetchone()
    if not profile:
        raise TimetableSetupError("Timetable profile not found.")
    root_id = int(profile["revision_of_profile_id"] or profile["id"])
    return cur.execute(
        """SELECT v.*,p.name profile_name,p.revision_no,p.status profile_status
           FROM ds_timetable_versions v JOIN ds_timetable_profiles p ON p.id=v.profile_id AND p.school_id=v.school_id
           WHERE v.school_id=? AND (p.id=? OR p.revision_of_profile_id=?)
           ORDER BY p.revision_no,v.version_no""",
        (school_id,root_id,root_id),
    ).fetchall()


def compare_timetable_versions(connection: Any, school_id: int, first_version_id: int, second_version_id: int) -> dict:
    cur = connection.cursor()
    rows = cur.execute(
        """SELECT v.*,p.academic_year,p.term FROM ds_timetable_versions v
           JOIN ds_timetable_profiles p ON p.id=v.profile_id AND p.school_id=v.school_id
           WHERE v.school_id=? AND v.id IN (?,?)""",
        (school_id,first_version_id,second_version_id),
    ).fetchall()
    by_id = {int(r["id"]):r for r in rows}
    if first_version_id not in by_id or second_version_id not in by_id:
        raise TimetableSetupError("Choose two published versions belonging to this school.")
    first, second = by_id[first_version_id], by_id[second_version_id]
    if first["academic_year"] != second["academic_year"] or first["term"] != second["term"]:
        raise TimetableSetupError("Only versions from the same academic year and term can be compared.")
    first_snapshot = json.loads(first["snapshot_json"] or "{}")
    second_snapshot = json.loads(second["snapshot_json"] or "{}")
    def lesson_map(snapshot):
        day_codes = {int(d["id"]):str(d["day_code"]) for d in snapshot.get("days",[])}
        period_details = {
            int(p["id"]):(int(p["period_no"]),str(p["start_time"]),str(p["end_time"]))
            for p in snapshot.get("periods",[])
        }
        result = {}
        for lesson in snapshot.get("lessons",[]):
            period = period_details.get(int(lesson["period_id"]), (str(lesson["period_id"]),"",""))
            key = (
                int(lesson["class_id"]),int(lesson["subject_id"]),int(lesson["teacher_id"]),
                day_codes.get(int(lesson["day_id"]),str(lesson["day_id"])),
                period,int(lesson["duration_periods"] or 1),
                int(lesson["room_id"]) if lesson.get("room_id") is not None else None,
            )
            result[key] = lesson
        return result
    first_lessons = lesson_map(first_snapshot)
    second_lessons = lesson_map(second_snapshot)
    added = [second_lessons[k] for k in second_lessons.keys()-first_lessons.keys()]
    removed = [first_lessons[k] for k in first_lessons.keys()-second_lessons.keys()]

    def advanced_session_map(snapshot):
        day_codes = {int(d["id"]):str(d["day_code"]) for d in snapshot.get("days", [])}
        classes, teachers, learners = {}, {}, {}
        for key, target in (("session_classes", classes), ("session_teachers", teachers), ("session_learners", learners)):
            for link in snapshot.get(key, []):
                target.setdefault(int(link["session_id"]), []).append(
                    int(link.get("class_id", link.get("teacher_id", link.get("student_id"))))
                )
        result = {}
        for session in snapshot.get("sessions", []):
            sid = int(session["id"])
            key = (
                str(session.get("schedule_layer") or ""), str(session.get("session_type") or ""),
                int(session["subject_id"]) if session.get("subject_id") is not None else None,
                int(session["programme_id"]) if session.get("programme_id") is not None else None,
                int(session["teaching_group_id"]) if session.get("teaching_group_id") is not None else None,
                tuple(sorted(classes.get(sid, []))), tuple(sorted(teachers.get(sid, []))),
                tuple(sorted(learners.get(sid, []))),
                day_codes.get(int(session["day_id"]), "") if session.get("day_id") is not None else "",
                str(session.get("session_date") or ""), str(session.get("start_time") or ""),
                str(session.get("end_time") or ""),
                int(session["room_id"]) if session.get("room_id") is not None else None,
            )
            result[key] = session
        return result

    first_advanced = advanced_session_map(first_snapshot)
    second_advanced = advanced_session_map(second_snapshot)
    advanced_added = [second_advanced[k] for k in second_advanced.keys()-first_advanced.keys()]
    advanced_removed = [first_advanced[k] for k in first_advanced.keys()-second_advanced.keys()]
    return {
        "first_version":first,
        "second_version":second,
        "added":added,
        "removed":removed,
        "unchanged":len(first_lessons.keys() & second_lessons.keys()),
        "advanced_added":advanced_added,
        "advanced_removed":advanced_removed,
        "advanced_unchanged":len(first_advanced.keys() & second_advanced.keys()),
    }
