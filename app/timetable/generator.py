"""Constraint-based automatic timetable generation (v1)."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.timetable.setup import TimetableSetupError, _profile
from app.timetable.session_engine import _validate_constraints


ENGINE_VERSION = "1.0"
DEFAULT_NODE_LIMIT = 100000


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return str(a_start) < str(b_end) and str(a_end) > str(b_start)


def _period_span(periods, start_index: int, duration: int):
    span = periods[start_index:start_index + duration]
    if len(span) != duration:
        return None
    for i, period in enumerate(span):
        if str(period["period_type"] or "lesson") != "lesson":
            return None
        if i:
            previous = span[i - 1]
            if int(period["period_no"]) != int(previous["period_no"]) + 1:
                return None
            if str(previous["end_time"]) != str(period["start_time"]):
                return None
    return span


def _gaps(placements, field: str, value: int, day_id: int) -> int:
    intervals = sorted(
        (p["start_time"], p["end_time"])
        for p in placements
        if int(p[field]) == value and int(p["day_id"]) == day_id
    )
    return sum(1 for i in range(1, len(intervals)) if intervals[i - 1][1] < intervals[i][0])


def _can_place(task, candidate, placements) -> bool:
    max_per_day = task.get("max_lessons_per_day")
    if max_per_day:
        same_subject_day = sum(
            1 for p in placements
            if int(p["class_id"]) == task["class_id"]
            and int(p["subject_id"]) == task["subject_id"]
            and int(p["teacher_id"]) == task["teacher_id"]
            and int(p["day_id"]) == candidate["day_id"]
        )
        if same_subject_day >= int(max_per_day):
            return False
    for other in placements:
        if int(other["day_id"]) != candidate["day_id"]:
            continue
        if not _overlap(candidate["start_time"], candidate["end_time"], other["start_time"], other["end_time"]):
            continue
        if int(other["class_id"]) == task["class_id"]:
            return False
        if int(other["teacher_id"]) == task["teacher_id"]:
            return False
        if candidate["room_id"] is not None and other.get("room_id") is not None and int(other["room_id"]) == int(candidate["room_id"]):
            return False
    return True


def _score(task, candidate, placements) -> float:
    day_id = candidate["day_id"]
    score = candidate["period_no"] * 0.15
    if candidate.get("preferred"):
        score -= 4.0
    same_subject_day = sum(
        1 for p in placements
        if int(p["class_id"]) == task["class_id"]
        and int(p["subject_id"]) == task["subject_id"]
        and int(p["day_id"]) == day_id
    )
    score += same_subject_day * 22.0
    score += sum(1 for p in placements if int(p["class_id"]) == task["class_id"] and int(p["day_id"]) == day_id) * 0.9
    score += sum(1 for p in placements if int(p["teacher_id"]) == task["teacher_id"] and int(p["day_id"]) == day_id) * 1.2
    before_class_gaps = _gaps(placements, "class_id", task["class_id"], day_id)
    before_teacher_gaps = _gaps(placements, "teacher_id", task["teacher_id"], day_id)
    after = placements + [dict(candidate, class_id=task["class_id"], subject_id=task["subject_id"], teacher_id=task["teacher_id"])]
    score += max(0, _gaps(after, "class_id", task["class_id"], day_id) - before_class_gaps) * 5.0
    score += max(0, _gaps(after, "teacher_id", task["teacher_id"], day_id) - before_teacher_gaps) * 4.0
    return score


def generate_timetable(connection: Any, school_id: int, profile_id: int, created_by: str = "", node_limit: int = DEFAULT_NODE_LIMIT) -> dict:
    cur = connection.cursor()
    profile = _profile(cur, school_id, profile_id)
    active_run = cur.execute(
        """SELECT id FROM ds_timetable_generation_runs
           WHERE school_id=? AND profile_id=? AND status='running' ORDER BY id DESC LIMIT 1""",
        (school_id, profile_id),
    ).fetchone()
    if active_run:
        raise TimetableSetupError("Automatic timetable generation is already running for this profile.")
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
    requirements = cur.execute(
        """SELECT * FROM ds_timetable_class_requirements
           WHERE school_id=? AND profile_id=? ORDER BY class_id,subject_id,teacher_id""",
        (school_id, profile_id),
    ).fetchall()
    if not days or not periods or not requirements:
        raise TimetableSetupError("Configure instructional days, teaching periods and weekly lesson requirements before automatic generation.")
    allocations = cur.execute(
        """SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id
           FROM teacher_allocations ta
           JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
           JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
           JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
           WHERE ta.school_id=?""",
        (school_id,),
    ).fetchall()
    allocation_keys = {(int(a["class_id"]), int(a["subject_id"]), int(a["teacher_id"])) for a in allocations}
    requirement_keys = {(int(r["class_id"]), int(r["subject_id"]), int(r["teacher_id"])) for r in requirements}
    missing_requirements = allocation_keys - requirement_keys
    stale_requirements = requirement_keys - allocation_keys
    if missing_requirements:
        raise TimetableSetupError(
            str(len(missing_requirements)) + " existing class/subject/teacher allocations are missing weekly lesson requirements. Configure every allocation before generating a complete timetable."
        )
    if stale_requirements:
        raise TimetableSetupError(
            "Some weekly requirements no longer match current teacher allocations. Review Timetable Setup before generating."
        )
    teaching_periods = [p for p in periods if str(p["period_type"] or "lesson") == "lesson"]
    if not teaching_periods:
        raise TimetableSetupError("No teaching periods are configured for this timetable profile.")
    rooms = cur.execute(
        "SELECT * FROM ds_timetable_rooms WHERE school_id=? AND is_active=1 ORDER BY capacity DESC,name",
        (school_id,),
    ).fetchall()
    breaks = cur.execute(
        "SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall()
    availability = cur.execute(
        """SELECT teacher_id,day_id,period_id FROM ds_timetable_teacher_availability
           WHERE school_id=? AND profile_id=? AND availability='unavailable'""",
        (school_id, profile_id),
    ).fetchall()
    unavailable = {
        (int(a["teacher_id"]), int(a["day_id"]), int(a["period_id"]))
        for a in availability
    }
    preferred_rows = cur.execute(
        """SELECT teacher_id,day_id,period_id FROM ds_timetable_teacher_availability
           WHERE school_id=? AND profile_id=? AND availability='preferred'""",
        (school_id, profile_id),
    ).fetchall()
    preferred = {
        (int(a["teacher_id"]), int(a["day_id"]), int(a["period_id"]))
        for a in preferred_rows
    }
    manual = cur.execute(
        """SELECT * FROM ds_timetable_lessons
           WHERE school_id=? AND profile_id=? AND generation_run_id IS NULL AND status='scheduled'""",
        (school_id, profile_id),
    ).fetchall()
    previous_generated = cur.execute(
        """SELECT * FROM ds_timetable_lessons
           WHERE school_id=? AND profile_id=? AND generation_run_id IS NOT NULL AND status='scheduled'""",
        (school_id, profile_id),
    ).fetchall()

    manual_counts = {}
    for lesson in manual:
        key = (int(lesson["class_id"]), int(lesson["subject_id"]), int(lesson["teacher_id"]))
        manual_counts[key] = manual_counts.get(key, 0) + 1

    tasks = []
    total_required = 0
    for req in requirements:
        key = (int(req["class_id"]), int(req["subject_id"]), int(req["teacher_id"]))
        weekly = int(req["lessons_per_week"] or 0)
        if weekly < 1:
            raise TimetableSetupError("Every lesson requirement must request at least one lesson per week.")
        already = manual_counts.get(key, 0)
        if already > weekly:
            raise TimetableSetupError("A manually scheduled class/subject/teacher combination already exceeds its weekly requirement.")
        duration = int(req["duration_periods"] or 1)
        if duration < 1 or duration > 4:
            raise TimetableSetupError("Lesson duration must be between one and four periods.")
        remaining = weekly - already
        total_required += weekly
        for occurrence in range(remaining):
            tasks.append({
                "class_id": key[0],
                "subject_id": key[1],
                "teacher_id": key[2],
                "duration": duration,
                "max_lessons_per_day": int(req["max_lessons_per_day"]) if req["max_lessons_per_day"] is not None else None,
                "occurrence": occurrence + 1,
            })
    if len(tasks) > 700:
        raise TimetableSetupError("This timetable contains more than 700 unscheduled lesson occurrences. Split the generation by school section or reduce the weekly requirements.")

    # Existing manual lessons are fixed anchors. A previous automatic version
    # is excluded from the search and is replaced only after a complete solution.
    period_index = {int(p["id"]): i for i,p in enumerate(periods)}
    fixed = []
    for lesson in manual:
        start_index = period_index.get(int(lesson["period_id"]))
        if start_index is None:
            raise TimetableSetupError("A manually scheduled lesson references a missing period. Review the draft before generating.")
        span = _period_span(periods, start_index, int(lesson["duration_periods"] or 1))
        if not span:
            raise TimetableSetupError("A manually scheduled multi-period lesson is no longer consecutive. Correct it before generating.")
        fixed.append({
            "class_id": int(lesson["class_id"]),
            "subject_id": int(lesson["subject_id"]),
            "teacher_id": int(lesson["teacher_id"]),
            "room_id": int(lesson["room_id"]) if lesson["room_id"] is not None else None,
            "day_id": int(lesson["day_id"]),
            "period_id": int(lesson["period_id"]),
            "duration": len(span),
            "start_time": span[0]["start_time"],
            "end_time": span[-1]["end_time"],
            "period_no": int(span[0]["period_no"]),
            "fixed": True,
        })
    for i, first in enumerate(fixed):
        for second in fixed[i + 1:]:
            if int(first["day_id"]) != int(second["day_id"]):
                continue
            if _overlap(first["start_time"], first["end_time"], second["start_time"], second["end_time"]):
                if int(first["class_id"]) == int(second["class_id"]) or int(first["teacher_id"]) == int(second["teacher_id"]) or (
                    first["room_id"] is not None and second["room_id"] is not None and int(first["room_id"]) == int(second["room_id"])
                ):
                    raise TimetableSetupError("The manually placed lessons already contain a class, teacher or room clash. Resolve it before automatic generation.")

    room_ids = [int(r["id"]) for r in rooms] or [None]
    candidates_by_task = []
    for task_index, task in enumerate(tasks):
        candidates = []
        for day in days:
            day_id = int(day["id"])
            for start_index, period in enumerate(periods):
                span = _period_span(periods, start_index, task["duration"])
                if not span:
                    continue
                if any((task["teacher_id"], day_id, int(p["id"])) in unavailable for p in span):
                    continue
                if any(
                    _overlap(span[0]["start_time"], span[-1]["end_time"], b["start_time"], b["end_time"])
                    for b in breaks
                ):
                    continue
                try:
                    _validate_constraints(
                        cur, school_id, profile_id, "instructional", "lesson",
                        task["subject_id"], [task["class_id"]], [task["teacher_id"]],
                        None, day_id, int(period["id"]),
                        str(span[0]["start_time"]), str(span[-1]["end_time"]), None,
                    )
                except TimetableSetupError:
                    continue
                candidates.append({
                    "day_id": day_id,
                    "period_id": int(period["id"]),
                    "duration": len(span),
                    "start_time": span[0]["start_time"],
                    "end_time": span[-1]["end_time"],
                    "period_no": int(period["period_no"]),
                    "preferred": any((task["teacher_id"], day_id, int(p["id"])) in preferred for p in span),
                })
        if not candidates:
            message = (
                "No valid time slots are available for class ID " + str(task["class_id"]) +
                ", subject ID " + str(task["subject_id"]) + ". Check teacher availability, periods and breaks."
            )
            now = _now()
            summary = {
                "status": "failed",
                "message": message,
                "required_lessons": total_required,
                "manual_lessons_kept": len(manual),
                "unscheduled_lessons": len(tasks),
                "search_nodes": 0,
                "search_limit": int(node_limit),
            }
            snapshot = {
                "profile_id": profile_id,
                "engine_version": ENGINE_VERSION,
                "reason": message,
                "manual_lesson_ids": [int(l["id"]) for l in manual],
                "previous_generated_ids": [int(l["id"]) for l in previous_generated],
            }
            cur.execute(
                """INSERT INTO ds_timetable_generation_runs
                   (school_id,profile_id,status,engine_version,input_snapshot_json,result_summary_json,started_at,finished_at,created_by,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (school_id, profile_id, "failed", ENGINE_VERSION, json.dumps(snapshot, sort_keys=True),
                 json.dumps(summary, sort_keys=True), now, now, created_by, now),
            )
            run_id = int(cur.lastrowid or 0)
            if not run_id:
                row = cur.execute(
                    "SELECT id FROM ds_timetable_generation_runs WHERE school_id=? AND profile_id=? AND created_at=? ORDER BY id DESC LIMIT 1",
                    (school_id, profile_id, now),
                ).fetchone()
                run_id = int(row["id"])
            connection.commit()
            return {"run_id": run_id, **summary}
        candidates_by_task.append((task_index, candidates))

    # Most-constrained-first reduces search. Stable ordering keeps generation
    # deterministic and makes runs reproducible.
    order = sorted(
        range(len(tasks)),
        key=lambda i: (len(candidates_by_task[i][1]), -tasks[i]["duration"], tasks[i]["class_id"], tasks[i]["subject_id"], tasks[i]["occurrence"]),
    )
    candidate_lookup = {i: candidates for i, candidates in candidates_by_task}
    placements = list(fixed)
    nodes = 0
    exhausted = False

    def search(position: int) -> bool:
        nonlocal nodes, exhausted
        if position >= len(order):
            return True
        if nodes >= int(node_limit):
            exhausted = True
            return False
        task_index = order[position]
        task = tasks[task_index]
        candidates = sorted(
            candidate_lookup[task_index],
            key=lambda candidate: _score(task, candidate, placements),
        )
        for candidate in candidates:
            room_order = sorted(
                room_ids,
                key=lambda room: sum(
                    1 for placed in placements
                    if int(placed["day_id"]) == int(candidate["day_id"])
                    and placed.get("room_id") is not None
                    and room is not None
                    and int(placed["room_id"]) == int(room)
                    and _overlap(candidate["start_time"], candidate["end_time"], placed["start_time"], placed["end_time"])
                ),
            )
            for room_id in room_order:
                nodes += 1
                if nodes > int(node_limit):
                    exhausted = True
                    return False
                placement = dict(candidate, room_id=room_id)
                if not _can_place(task, placement, placements):
                    continue
                placement.update({
                    "class_id": task["class_id"],
                    "subject_id": task["subject_id"],
                    "teacher_id": task["teacher_id"],
                    "fixed": False,
                })
                placements.append(placement)
                if search(position + 1):
                    return True
                placements.pop()
                if exhausted:
                    return False
        return False

    snapshot = {
        "profile_id": profile_id,
        "engine_version": ENGINE_VERSION,
        "days": [{"id": int(d["id"]), "code": d["day_code"]} for d in days],
        "periods": [{"id": int(p["id"]), "number": int(p["period_no"]), "start": p["start_time"], "end": p["end_time"]} for p in periods],
        "requirements": [{"class_id": int(r["class_id"]), "subject_id": int(r["subject_id"]), "teacher_id": int(r["teacher_id"]), "weekly": int(r["lessons_per_week"]), "duration": int(r["duration_periods"] or 1)} for r in requirements],
        "manual_lesson_ids": [int(l["id"]) for l in manual],
        "previous_generated_ids": [int(l["id"]) for l in previous_generated],
    }
    now = _now()
    cur.execute(
        """INSERT INTO ds_timetable_generation_runs
           (school_id,profile_id,status,engine_version,input_snapshot_json,started_at,created_by,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (school_id, profile_id, "running", ENGINE_VERSION, json.dumps(snapshot, sort_keys=True), now, created_by, now),
    )
    run_id = int(cur.lastrowid or 0)
    if not run_id:
        run = cur.execute(
            """SELECT id FROM ds_timetable_generation_runs
               WHERE school_id=? AND profile_id=? AND created_at=? ORDER BY id DESC LIMIT 1""",
            (school_id, profile_id, now),
        ).fetchone()
        run_id = int(run["id"])
    connection.commit()

    success = search(0)
    if not success:
        summary = {
            "status": "failed",
            "message": "No complete clash-free timetable was found within the search limit." if exhausted else "The configured constraints leave at least one lesson without a valid slot.",
            "required_lessons": total_required,
            "manual_lessons_kept": len(manual),
            "unscheduled_lessons": len(tasks),
            "search_nodes": nodes,
            "search_limit": int(node_limit),
        }
        cur.execute(
            "UPDATE ds_timetable_generation_runs SET status='failed',result_summary_json=?,finished_at=? WHERE id=? AND school_id=?",
            (json.dumps(summary, sort_keys=True), _now(), run_id, school_id),
        )
        connection.commit()
        return {"run_id": run_id, **summary}

    generated = [p for p in placements if not p.get("fixed")]
    # Preserve the previous automatic timetable if the new run failed. Only
    # after a complete solution exists do we replace its generated lessons.
    for old in previous_generated:
        cur.execute(
            """INSERT INTO ds_timetable_change_log
               (school_id,profile_id,lesson_id,action,before_json,after_json,changed_by,changed_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (school_id, profile_id, int(old["id"]), "AUTO_REPLACE_DELETE", json.dumps(dict(old), default=str, sort_keys=True), None, created_by, _now()),
        )
    cur.execute(
        """DELETE FROM ds_timetable_lessons
           WHERE school_id=? AND profile_id=? AND generation_run_id IS NOT NULL""",
        (school_id, profile_id),
    )
    for placement in generated:
        now = _now()
        cur.execute(
            """INSERT INTO ds_timetable_lessons
               (school_id,profile_id,class_id,subject_id,teacher_id,room_id,day_id,period_id,duration_periods,generation_run_id,status,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                school_id, profile_id, placement["class_id"], placement["subject_id"], placement["teacher_id"],
                placement["room_id"], placement["day_id"], placement["period_id"], placement["duration"],
                run_id, "scheduled", created_by, now, now,
            ),
        )
        lesson_id = int(cur.lastrowid or 0)
        if not lesson_id:
            row = cur.execute(
                """SELECT id FROM ds_timetable_lessons
                   WHERE school_id=? AND profile_id=? AND generation_run_id=? AND class_id=? AND subject_id=?
                     AND teacher_id=? AND day_id=? AND period_id=? ORDER BY id DESC LIMIT 1""",
                (school_id, profile_id, run_id, placement["class_id"], placement["subject_id"], placement["teacher_id"], placement["day_id"], placement["period_id"]),
            ).fetchone()
            lesson_id = int(row["id"])
        after = cur.execute("SELECT * FROM ds_timetable_lessons WHERE id=? AND school_id=?", (lesson_id, school_id)).fetchone()
        cur.execute(
            """INSERT INTO ds_timetable_change_log
               (school_id,profile_id,lesson_id,action,before_json,after_json,changed_by,changed_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (school_id, profile_id, lesson_id, "AUTO_GENERATE", None, json.dumps(dict(after), default=str, sort_keys=True), created_by, _now()),
        )
    day_loads = {}
    for placement in placements:
        day_key = int(placement["day_id"])
        day_loads[day_key] = day_loads.get(day_key, 0) + 1
    load_spread = (max(day_loads.values()) - min(day_loads.values())) if day_loads else 0
    search_penalty = min(30, nodes // max(1, len(tasks) * 20))
    balance_penalty = min(40, load_spread * 5)
    quality_score = max(0, 100 - search_penalty - balance_penalty)
    summary = {
        "status": "completed",
        "message": "Automatic timetable generated successfully. Existing manual lessons were preserved.",
        "required_lessons": total_required,
        "manual_lessons_kept": len(manual),
        "generated_lessons": len(generated),
        "total_scheduled_lessons": len(manual) + len(generated),
        "search_nodes": nodes,
        "quality_score": quality_score,
    }
    cur.execute(
        "UPDATE ds_timetable_generation_runs SET status='completed',result_summary_json=?,finished_at=? WHERE id=? AND school_id=?",
        (json.dumps(summary, sort_keys=True), _now(), run_id, school_id),
    )
    connection.commit()
    return {"run_id": run_id, **summary}



def generate_advanced_instructional_sessions(connection: Any, school_id: int,
                                             profile_id: int, created_by: str = "",
                                             node_limit: int = DEFAULT_NODE_LIMIT) -> dict:
    """Place normalized multi-class/team-teaching requirements using the shared engine.

    This deliberately writes to ds_timetable_sessions; legacy single-class rows
    remain untouched until the new generator is fully integrated and reconciled.
    """
    from app.timetable.session_engine import create_scheduled_session, find_session_conflicts

    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    requirements = cur.execute(
        """SELECT * FROM ds_timetable_scheduling_requirements
           WHERE school_id=? AND profile_id=? AND is_active=1
             AND schedule_layer='instructional'
           ORDER BY id""",
        (school_id, profile_id),
    ).fetchall()
    if not requirements:
        raise TimetableSetupError("No active normalized instructional requirements are configured.")
    days = cur.execute(
        """SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=?
           AND is_instructional=1 ORDER BY day_order,id""",
        (school_id, profile_id),
    ).fetchall()
    periods = cur.execute(
        """SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=?
           ORDER BY period_no,id""",
        (school_id, profile_id),
    ).fetchall()
    if not days or not periods:
        raise TimetableSetupError("Configure instructional days and periods before generating advanced sessions.")

    tasks = []
    for req in requirements:
        rid = int(req["id"])
        classes = [int(x["class_id"]) for x in cur.execute(
            "SELECT class_id FROM ds_timetable_scheduling_requirement_classes WHERE school_id=? AND profile_id=? AND requirement_id=? ORDER BY class_id",
            (school_id, profile_id, rid)).fetchall()]
        teachers = [int(x["teacher_id"]) for x in cur.execute(
            "SELECT teacher_id FROM ds_timetable_scheduling_requirement_teachers WHERE school_id=? AND profile_id=? AND requirement_id=? ORDER BY role,teacher_id",
            (school_id, profile_id, rid)).fetchall()]
        learners = [int(x["student_id"]) for x in cur.execute(
            "SELECT student_id FROM ds_timetable_scheduling_requirement_learners WHERE school_id=? AND profile_id=? AND requirement_id=? ORDER BY student_id",
            (school_id, profile_id, rid)).fetchall()]
        patterns = cur.execute(
            """SELECT * FROM ds_timetable_scheduling_patterns
               WHERE school_id=? AND profile_id=? AND requirement_id=? ORDER BY session_no""",
            (school_id, profile_id, rid),
        ).fetchall()
        if len(patterns) != int(req["weekly_occurrences"]):
            raise TimetableSetupError("Requirement '" + str(req["name"]) + "' needs a complete configured weekly session pattern.")
        if not classes and not learners:
            raise TimetableSetupError("Requirement '" + str(req["name"]) + "' has no assigned classes or learners.")
        if len(teachers) < int(req["min_teacher_count"] or 1):
            raise TimetableSetupError("Requirement '" + str(req["name"]) + "' does not have enough assigned teachers.")
        for pattern in patterns:
            duration = int(pattern["duration_periods"] or 1)
            if duration < 1 or duration > 4:
                raise TimetableSetupError("Advanced instructional sessions must span one to four consecutive periods.")
            tasks.append({
                "requirement_id": rid, "session_no": int(pattern["session_no"]),
                "duration": duration, "classes": classes, "teachers": teachers,
                "learners": learners, "subject_id": int(req["subject_id"]) if req["subject_id"] is not None else None,
                "programme_id": int(req["programme_id"]) if req["programme_id"] is not None else None,
                "group_id": int(req["teaching_group_id"]) if req["teaching_group_id"] is not None else None,
                "session_type": str(req["session_type"]), "room_type": req["room_type"],
                "preferred_day_id": int(pattern["preferred_day_id"]) if pattern["preferred_day_id"] is not None else None,
                "name": str(req["name"]),
            })

    def span_for(start_index, duration):
        span = periods[start_index:start_index + duration]
        if len(span) != duration:
            return None
        for index, period in enumerate(span):
            if str(period["period_type"] or "lesson") != "lesson":
                return None
            if index and (int(period["period_no"]) != int(span[index-1]["period_no"]) + 1
                          or str(span[index-1]["end_time"]) != str(period["start_time"])):
                return None
        return span

    candidates = []
    for task in tasks:
        options = []
        for day in days:
            day_id = int(day["id"])
            if task["preferred_day_id"] and day_id != task["preferred_day_id"]:
                continue
            for index, period in enumerate(periods):
                span = span_for(index, task["duration"])
                if not span:
                    continue
                start, end = str(span[0]["start_time"]), str(span[-1]["end_time"])
                try:
                    _validate_constraints(cur, school_id, profile_id, "instructional", "lesson",
                        task["subject_id"], task["classes"], task["teachers"], None,
                        day_id, int(period["id"]), start, end, None)
                except TimetableSetupError:
                    continue
                rooms = cur.execute(
                    """SELECT id FROM ds_timetable_rooms WHERE school_id=? AND is_active=1
                       AND (? IS NULL OR room_type=?) ORDER BY capacity DESC,id""",
                    (school_id, task["room_type"], task["room_type"]),
                ).fetchall()
                room_ids = [int(r["id"]) for r in rooms] if rooms else ([None] if not task["room_type"] else [])
                for room_id in room_ids:
                    if find_session_conflicts(connection, school_id, profile_id, start, end,
                        task["classes"], task["teachers"], task["learners"], room_id, day_id):
                        continue
                    options.append({"day_id": day_id, "period_id": int(period["id"]),
                        "start": start, "end": end, "room_id": room_id,
                        "duration": task["duration"], "period_no": int(period["period_no"])})
        if not options:
            raise TimetableSetupError("No valid slot is available for normalized requirement '" + task["name"] + "'. Check constraints, teacher availability, rooms and period patterns.")
        candidates.append(options)

    order = sorted(range(len(tasks)), key=lambda i: (len(candidates[i]), -tasks[i]["duration"], tasks[i]["requirement_id"], tasks[i]["session_no"]))
    planned = []
    nodes = 0

    def overlaps(a, b):
        return a["day_id"] == b["day_id"] and a["start"] < b["end"] and a["end"] > b["start"]

    def compatible(task, option):
        for placed in planned:
            if not overlaps(option, placed["option"]):
                continue
            other = placed["task"]
            if (set(task["classes"]) & set(other["classes"])
                or set(task["teachers"]) & set(other["teachers"])
                or set(task["learners"]) & set(other["learners"])
                or (option["room_id"] is not None and option["room_id"] == placed["option"]["room_id"])):
                return False
        return True

    def search(position):
        nonlocal nodes
        if position == len(order):
            return True
        index = order[position]
        task = tasks[index]
        for option in candidates[index]:
            nodes += 1
            if nodes > int(node_limit):
                return False
            if not compatible(task, option):
                continue
            planned.append({"task": task, "option": option})
            if search(position + 1):
                return True
            planned.pop()
        return False

    if not search(0):
        raise TimetableSetupError("The normalized requirements cannot all fit without clashes under the configured constraints.")

    created = []
    try:
        for item in planned:
            task, option = item["task"], item["option"]
            created.append(create_scheduled_session(
                connection, school_id, profile_id, option["start"], option["end"],
                schedule_layer="instructional", session_type=task["session_type"],
                class_ids=task["classes"], teacher_ids=task["teachers"],
                learner_ids=task["learners"], room_id=option["room_id"],
                day_id=option["day_id"], period_id=option["period_id"],
                subject_id=task["subject_id"], programme_id=task["programme_id"],
                teaching_group_id=task["group_id"], duration_periods=option["duration"],
                scheduling_requirement_id=task["requirement_id"],
                pattern_session_no=task["session_no"], created_by=created_by,
            ))
    except Exception:
        if created:
            marks = ",".join("?" for _ in created)
            cur.execute(f"DELETE FROM ds_timetable_session_classes WHERE session_id IN ({marks})", tuple(created))
            cur.execute(f"DELETE FROM ds_timetable_session_teachers WHERE session_id IN ({marks})", tuple(created))
            cur.execute(f"DELETE FROM ds_timetable_session_learners WHERE session_id IN ({marks})", tuple(created))
            cur.execute(f"DELETE FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND id IN ({marks})",
                        (school_id, profile_id, *created))
            connection.commit()
        raise
    return {"status": "completed", "generated_sessions": len(created),
            "session_ids": created, "search_nodes": nodes,
            "message": "Advanced instructional sessions generated with combined-class, team-teaching and shared conflict validation."}
