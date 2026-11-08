"""Constraint-based automatic timetable generation (v1)."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.timetable.setup import TimetableSetupError, _profile
from app.timetable.session_engine import _validate_constraints


ENGINE_VERSION = "1.3"
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
    max_week = task.get("max_lessons_per_week")
    if max_week is not None:
        weekly_count = sum(1 for p in placements if int(p["class_id"]) == task["class_id"])
        if weekly_count >= int(max_week):
            return False
    max_day_periods = task.get("max_periods_per_day")
    if max_day_periods is not None:
        used_periods = sum(
            int(p.get("duration", 1)) for p in placements
            if int(p["class_id"]) == task["class_id"] and int(p["day_id"]) == candidate["day_id"]
        )
        if used_periods + int(candidate.get("duration", 1)) > int(max_day_periods):
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


def generate_timetable(connection: Any, school_id: int, profile_id: int, created_by: str = "", node_limit: int = DEFAULT_NODE_LIMIT, normalized_run_id: int | None = None) -> dict:
    cur = connection.cursor()
    profile = _profile(cur, school_id, profile_id)
    active_run_sql = """SELECT id FROM ds_timetable_generation_runs
           WHERE school_id=? AND profile_id=? AND status='running'"""
    active_run_params = [school_id, profile_id]
    # In the unified workflow, normalized instructional sessions are created
    # first and their running audit row is passed into this solver. Exclude
    # only that parent run; any other running row still means another
    # generation is in progress and must block this request.
    if normalized_run_id is not None:
        active_run_sql += " AND id<>?"
        active_run_params.append(int(normalized_run_id))
    active_run = cur.execute(
        active_run_sql + " ORDER BY id DESC LIMIT 1",
        tuple(active_run_params),
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
    if not days or not periods:
        raise TimetableSetupError("Configure instructional days and teaching periods before automatic generation.")
    # Reconcile each shared weekly occurrence with the matching duration
    # in every participating class/subject/teacher allocation.
    covered_rows = cur.execute(
        """SELECT rc.class_id,r.subject_id,rt.teacher_id,p.duration_periods
           FROM ds_timetable_scheduling_requirements r
           JOIN ds_timetable_scheduling_requirement_classes rc
             ON rc.school_id=r.school_id AND rc.profile_id=r.profile_id
            AND rc.requirement_id=r.id
           JOIN ds_timetable_scheduling_requirement_teachers rt
             ON rt.school_id=r.school_id AND rt.profile_id=r.profile_id
            AND rt.requirement_id=r.id
           JOIN ds_timetable_scheduling_patterns p
             ON p.school_id=r.school_id AND p.profile_id=r.profile_id
            AND p.requirement_id=r.id
           WHERE r.school_id=? AND r.profile_id=? AND r.is_active=1
             AND r.schedule_layer='instructional' AND r.subject_id IS NOT NULL
           ORDER BY r.id,p.session_no""",
        (school_id, profile_id),
    ).fetchall()
    normalized_coverage = {}
    for row in covered_rows:
        key = (int(row["class_id"]), int(row["subject_id"]), int(row["teacher_id"]))
        normalized_coverage.setdefault(key, []).append(int(row["duration_periods"] or 1))
    allocations = cur.execute(
        """SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id
           FROM teacher_allocations ta
           JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
           JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
           JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
           WHERE ta.school_id=?""",
        (school_id,),
    ).fetchall()
    allocation_keys = {
        (int(a["class_id"]), int(a["subject_id"]), int(a["teacher_id"]))
        for a in allocations
        if (int(a["class_id"]), int(a["subject_id"]), int(a["teacher_id"])) not in normalized_coverage
    }
    requirement_keys = {
        (int(r["class_id"]), int(r["subject_id"]), int(r["teacher_id"]))
        for r in requirements
        if (int(r["class_id"]), int(r["subject_id"]), int(r["teacher_id"])) not in normalized_coverage
    }
    if not requirements and not normalized_coverage:
        raise TimetableSetupError("Configure at least one weekly lesson requirement or shared instructional session before automatic generation.")
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
    fallback_rows = cur.execute(
        """SELECT teacher_id,day_id,period_id FROM ds_timetable_teacher_availability
           WHERE school_id=? AND profile_id=? AND availability='fallback'""",
        (school_id, profile_id),
    ).fetchall()
    fallback_only = {
        (int(a["teacher_id"]), int(a["day_id"]), int(a["period_id"]))
        for a in fallback_rows
    }
    subject_unavailable_rows = cur.execute(
        """SELECT subject_id,day_id,period_id FROM ds_timetable_subject_availability
           WHERE school_id=? AND profile_id=? AND availability='unavailable'""",
        (school_id, profile_id),
    ).fetchall()
    subject_unavailable = {
        (int(a["subject_id"]), int(a["day_id"]), int(a["period_id"]))
        for a in subject_unavailable_rows
    }
    subject_fallback_rows = cur.execute(
        """SELECT subject_id,day_id,period_id FROM ds_timetable_subject_availability
           WHERE school_id=? AND profile_id=? AND availability='fallback'""",
        (school_id, profile_id),
    ).fetchall()
    subject_fallback_only = {
        (int(a["subject_id"]), int(a["day_id"]), int(a["period_id"]))
        for a in subject_fallback_rows
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

    class_limits = {
        int(row["class_id"]): row for row in cur.execute(
            """SELECT class_id,max_lessons_per_week,max_periods_per_day
               FROM ds_timetable_class_limits WHERE school_id=? AND profile_id=?""",
            (school_id, profile_id),
        ).fetchall()
    }
    tasks = []
    total_required = 0
    for req in requirements:
        key = (int(req["class_id"]), int(req["subject_id"]), int(req["teacher_id"]))
        weekly = int(req["lessons_per_week"] or 0)
        if weekly < 1:
            raise TimetableSetupError("Every lesson requirement must request at least one lesson per week.")
        already = manual_counts.get(key, 0)
        covered_sessions = list(normalized_coverage.get(key, []))
        if already + len(covered_sessions) > weekly:
            raise TimetableSetupError(
                "Manual placements and shared combined/co-teaching sessions exceed the weekly requirement for class ID "
                + str(key[0]) + ", subject ID " + str(key[1]) + "."
            )
        remaining = weekly - already - len(covered_sessions)
        duration = int(req["duration_periods"] or 1)
        if duration < 1 or duration > 4:
            raise TimetableSetupError("Lesson duration must be between one and four periods.")
        configured_pattern = cur.execute(
            """SELECT duration_periods,preferred_period_id FROM ds_timetable_requirement_patterns
               WHERE school_id=? AND profile_id=? AND requirement_id=(
                   SELECT id FROM ds_timetable_class_requirements
                   WHERE school_id=? AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=?
               ) ORDER BY session_no""",
            (school_id, profile_id, school_id, profile_id, key[0], key[1], key[2]),
        ).fetchall()
        if configured_pattern and already:
            raise TimetableSetupError(
                "A configured weekly lesson pattern cannot be combined with manually placed lessons for the same subject. Clear those manual placements or remove the pattern first."
            )
        expected_periods = weekly * duration
        pattern_periods = sum(int(x["duration_periods"] or 1) for x in configured_pattern)
        if configured_pattern and pattern_periods > expected_periods:
            raise TimetableSetupError("The saved lesson pattern exceeds this subject's weekly duration allocation. Edit the pattern before generating.")
        if configured_pattern:
            planned_sessions = [
                {"duration": int(x["duration_periods"]), "preferred_period_id": int(x["preferred_period_id"]) if x["preferred_period_id"] is not None else None}
                for x in configured_pattern
            ]
            planned_sessions.extend(
                {"duration": 1, "preferred_period_id": None}
                for _ in range(expected_periods - pattern_periods)
            )
        else:
            planned_sessions = [
                {"duration": duration, "preferred_period_id": None}
                for _ in range(weekly)
            ]

        for shared_duration in covered_sessions:
            match = next(
                (index for index, item in enumerate(planned_sessions)
                 if int(item["duration"]) == int(shared_duration)),
                None,
            )
            if match is None:
                raise TimetableSetupError(
                    "A combined/co-teaching session duration does not match the weekly requirement pattern for class ID "
                    + str(key[0]) + ", subject ID " + str(key[1])
                    + ". Align the shared session and subject lesson durations."
                )
            planned_sessions.pop(match)
        if len(planned_sessions) > remaining:
            planned_sessions = planned_sessions[:remaining]
        total_required += remaining
        for occurrence, planned in enumerate(planned_sessions):
            tasks.append({
                "class_id": key[0],
                "subject_id": key[1],
                "teacher_id": key[2],
                "duration": planned["duration"],
                "preferred_period_id": planned["preferred_period_id"],
                "max_lessons_per_day": int(req["max_lessons_per_day"]) if req["max_lessons_per_day"] is not None else None,
                "max_lessons_per_week": int(class_limits[key[0]]["max_lessons_per_week"]) if key[0] in class_limits and class_limits[key[0]]["max_lessons_per_week"] is not None else None,
                "max_periods_per_day": int(class_limits[key[0]]["max_periods_per_day"]) if key[0] in class_limits and class_limits[key[0]]["max_periods_per_day"] is not None else None,
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
    for class_id, limit in class_limits.items():
        class_fixed = [item for item in fixed if int(item["class_id"]) == int(class_id)]
        if limit["max_lessons_per_week"] is not None and len(class_fixed) > int(limit["max_lessons_per_week"]):
            raise TimetableSetupError("Existing manually scheduled lessons exceed the class weekly lesson ceiling. Reduce the fixed lessons or revise the class limit.")
        if limit["max_periods_per_day"] is not None:
            for day in days:
                daily_periods = sum(item["duration"] for item in class_fixed if int(item["day_id"]) == int(day["id"]))
                if daily_periods > int(limit["max_periods_per_day"]):
                    raise TimetableSetupError("Existing manually scheduled lessons exceed the class daily period ceiling. Adjust the timetable or revise the class limit.")

    for i, first in enumerate(fixed):
        for second in fixed[i + 1:]:
            if int(first["day_id"]) != int(second["day_id"]):
                continue
            if _overlap(first["start_time"], first["end_time"], second["start_time"], second["end_time"]):
                if int(first["class_id"]) == int(second["class_id"]) or int(first["teacher_id"]) == int(second["teacher_id"]) or (
                    first["room_id"] is not None and second["room_id"] is not None and int(first["room_id"]) == int(second["room_id"])
                ):
                    raise TimetableSetupError("The manually placed lessons already contain a class, teacher or room clash. Resolve it before automatic generation.")

    # Ordinary weekly lessons use classroom-type rooms only. Specialist spaces
    # (labs, libraries, halls, workshops) are not generic classrooms and must not
    # become a school-wide bottleneck simply because they are registered.
    # Dedicated classrooms are available only to their assigned class.
    def _rooms_for_task(task):
        eligible = [
            int(room["id"]) for room in rooms
            if str(room["room_type"] or "classroom").lower() == "classroom"
            and (
                str(room["allocation_mode"] or "shared").lower() != "dedicated"
                or (room["assigned_class_id"] is not None
                    and int(room["assigned_class_id"]) == int(task["class_id"]))
            )
        ]
        return eligible or [None]
    # Reuse the profile's constraint rules and period spans across all candidate
    # cells. Without this cache, candidate enumeration performs repeated SQL
    # reads for the same rules and period ordering thousands of times.
    constraint_cache = {}
    candidates_by_task = []
    for task_index, task in enumerate(tasks):
        candidates = []
        for day in days:
            day_id = int(day["id"])
            for start_index, period in enumerate(periods):
                if task.get("preferred_period_id") is not None and int(period["id"]) != int(task["preferred_period_id"]):
                    continue
                # A single configured lesson must fit the class's daily
                # period ceiling on its own; otherwise no placement can ever
                # satisfy the workload limit, regardless of the search order.
                if (task.get("max_periods_per_day") is not None
                        and int(task["duration"]) > int(task["max_periods_per_day"])):
                    continue
                span = _period_span(periods, start_index, task["duration"])
                if not span:
                    continue
                if any((task["teacher_id"], day_id, int(p["id"])) in unavailable for p in span):
                    continue
                if any((task["subject_id"], day_id, int(p["id"])) in subject_unavailable for p in span):
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
                        cache=constraint_cache,
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
                    "explicitly_available": (
                        all((task["teacher_id"], day_id, int(p["id"])) not in fallback_only for p in span)
                        and all((task["subject_id"], day_id, int(p["id"])) not in subject_fallback_only for p in span)
                    ),
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
    # Candidate ordering is static and computed once. Re-scoring every candidate
    # at every recursive backtracking node repeatedly scans the full placement
    # list (and recomputes gap counts), turning a bounded search into a very
    # expensive O(nodes * candidates * placements) workload. The solver's
    # constraints are enforced by _can_place; this ordering only guides which
    # valid slot is tried first.
    candidate_lookup = {
        i: sorted(
            candidates,
            key=lambda candidate: (
                not bool(candidate.get("preferred")),
                int(candidate["period_no"]),
                int(candidate["day_id"]),
            ),
        )
        for i, candidates in candidates_by_task
    }
    placements = list(fixed)
    nodes = 0
    exhausted = False

    # Read normalized sessions once, then evaluate resource conflicts in
    # memory. The previous implementation issued several SQL queries for every
    # task/day/period/room combination, multiplying database round-trips.
    from collections import defaultdict
    blocked_candidates = set()
    existing_by_id = {}
    conflict_sql = """SELECT s.id,s.day_id,s.start_time,s.end_time,s.room_id,
                              sc.class_id,st.teacher_id
                       FROM ds_timetable_sessions s
                       LEFT JOIN ds_timetable_session_classes sc
                         ON sc.session_id=s.id AND sc.school_id=s.school_id
                       LEFT JOIN ds_timetable_session_teachers st
                         ON st.session_id=s.id AND st.school_id=s.school_id
                       WHERE s.school_id=? AND s.profile_id=?
                         AND s.session_date IS NULL
                         AND s.status NOT IN ('cancelled','void')"""
    conflict_params = [school_id, profile_id]
    if normalized_run_id is not None:
        conflict_sql += " AND (s.generation_run_id IS NULL OR s.generation_run_id=?)"
        conflict_params.append(int(normalized_run_id))
    conflict_rows = cur.execute(conflict_sql + " ORDER BY s.id", tuple(conflict_params)).fetchall()
    for row in conflict_rows:
        item = existing_by_id.setdefault(int(row["id"]), {
            "day_id": int(row["day_id"]) if row["day_id"] is not None else None,
            "start_time": str(row["start_time"]), "end_time": str(row["end_time"]),
            "room_id": int(row["room_id"]) if row["room_id"] is not None else None,
            "classes": set(), "teachers": set(),
        })
        if row["class_id"] is not None:
            item["classes"].add(int(row["class_id"]))
        if row["teacher_id"] is not None:
            item["teachers"].add(int(row["teacher_id"]))
    existing_sessions = list(existing_by_id.values())
    for task_index, task in enumerate(tasks):
        for candidate in candidate_lookup[task_index]:
            for room_id in _rooms_for_task(task):
                for existing in existing_sessions:
                    if existing["day_id"] != int(candidate["day_id"]):
                        continue
                    if not _overlap(candidate["start_time"], candidate["end_time"],
                                    existing["start_time"], existing["end_time"]):
                        continue
                    if (
                        int(task["class_id"]) in existing["classes"]
                        or int(task["teacher_id"]) in existing["teachers"]
                        or (room_id is not None and existing["room_id"] == int(room_id))
                    ):
                        blocked_candidates.add((
                            task_index, candidate["day_id"], candidate["period_id"], room_id
                        ))
                        break

    # All database-backed inputs and conflict checks are now materialised.
    # End the read transaction before CPU-heavy recursive backtracking so this
    # solver does not hold AccessShare locks on school tables for minutes.
    connection.commit()

    def search(position: int, fallback: bool = False) -> bool:
        nonlocal nodes, exhausted
        if position >= len(order):
            return True
        if nodes >= int(node_limit):
            exhausted = True
            return False
        task_index = order[position]
        task = tasks[task_index]
        eligible_candidates = [
            candidate for candidate in candidate_lookup[task_index]
            if fallback or candidate.get("explicitly_available")
        ]
        # Preserve the precomputed candidate order during recursion. Dynamic
        # scoring here was the dominant cost for large school workloads.
        candidates = eligible_candidates
        for candidate in candidates:
            room_order = sorted(
                _rooms_for_task(task),
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
                if (
                    task_index, candidate["day_id"], candidate["period_id"], room_id
                ) in blocked_candidates:
                    continue
                if not _can_place(task, placement, placements):
                    continue
                placement.update({
                    "class_id": task["class_id"],
                    "subject_id": task["subject_id"],
                    "teacher_id": task["teacher_id"],
                    "fixed": False,
                })
                placements.append(placement)
                if search(position + 1, fallback):
                    return True
                placements.pop()
                if exhausted:
                    return False
        return False

    # First attempt a complete timetable using only explicitly available
    # cells. If that cannot satisfy all requirements, retry with blank cells
    # as fallback placements. X cells remain hard exclusions.
    generated = search(0, False)
    if not generated:
        placements[:] = list(fixed)
        nodes = 0
        exhausted = False
        generated = search(0, True)

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

    success = generated
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
                                             node_limit: int = DEFAULT_NODE_LIMIT,
                                             defer_replacement: bool = False) -> dict:
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

    class_limits = {
        int(row["class_id"]): row for row in cur.execute(
            """SELECT class_id,max_lessons_per_week,max_periods_per_day
               FROM ds_timetable_class_limits WHERE school_id=? AND profile_id=?""",
            (school_id, profile_id),
        ).fetchall()
    }
    configured_breaks = cur.execute(
        "SELECT label,start_time,end_time FROM ds_timetable_breaks WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall()
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
                "room_assignment_mode": str(req["room_assignment_mode"] or "automatic"),
                "preferred_room_id": int(req["preferred_room_id"]) if req["preferred_room_id"] is not None else None,
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

    # Read preference rules once. The previous implementation queried the
    # same table for every candidate slot, multiplying database round-trips
    # by tasks × days × periods.
    preference_rules = cur.execute(
        """SELECT * FROM ds_timetable_constraints
           WHERE school_id=? AND profile_id=? AND is_active=1
             AND constraint_type='prefer'
             AND (schedule_layer='all' OR schedule_layer='instructional')
             AND (applies_to='all' OR applies_to='lesson')""",
        (school_id, profile_id),
    ).fetchall()

    # Room inventory is also immutable during this search. Load it once and
    # filter it in memory for each requirement instead of querying it for
    # every day/period combination.
    active_rooms = cur.execute(
        """SELECT id,capacity,allocation_mode,assigned_class_id,room_type
           FROM ds_timetable_rooms WHERE school_id=? AND is_active=1
           ORDER BY capacity DESC,id""",
        (school_id,),
    ).fetchall()
    enrolment_cache = {}

    def preference_penalty(task, option):
        penalty = 0
        for rule in preference_rules:
            if rule["subject_id"] is not None and int(rule["subject_id"]) != int(task["subject_id"] or 0):
                continue
            if rule["teacher_id"] is not None and int(rule["teacher_id"]) not in task["teachers"]:
                continue
            if rule["class_id"] is not None and int(rule["class_id"]) not in task["classes"]:
                continue
            if rule["room_id"] is not None and int(rule["room_id"]) != int(option["room_id"] or 0):
                continue
            matches = True
            if rule["day_id"] is not None:
                matches = matches and int(rule["day_id"]) == int(option["day_id"])
            if rule["period_id"] is not None:
                matches = matches and int(rule["period_id"]) == int(option["period_id"])
            if rule["start_time"] and rule["end_time"]:
                matches = matches and option["start"] < str(rule["end_time"]) and option["end"] > str(rule["start_time"])
            if matches:
                penalty -= 10
        return penalty

    candidates = []
    for task in tasks:
        options = []
        class_key = (tuple(sorted(task["classes"])), tuple(sorted(task["learners"])))
        if class_key not in enrolment_cache:
            room_enrolment = len(task["learners"])
            if task["classes"]:
                class_marks = ",".join("?" for _ in task["classes"])
                enrolled_count = cur.execute(
                    f"SELECT COUNT(*) FROM students WHERE school_id=? AND class_id IN ({class_marks})",
                    (school_id, *task["classes"]),
                ).fetchone()[0]
                room_enrolment = max(room_enrolment, int(enrolled_count or 0))
            enrolment_cache[class_key] = room_enrolment
        room_enrolment = enrolment_cache[class_key]

        if task["room_assignment_mode"] == "fixed":
            room_ids_for_task = [task["preferred_room_id"]] if task["preferred_room_id"] is not None else []
        elif task["room_type"] or task["room_assignment_mode"] == "preferred":
            eligible_rooms = [
                room for room in active_rooms
                if (not task["room_type"] or str(room["room_type"] or "") == str(task["room_type"]))
                and (str(room["allocation_mode"] or "shared") != "dedicated"
                     or int(room["assigned_class_id"] or 0) in task["classes"])
                and (room["capacity"] is None or int(room["capacity"]) >= room_enrolment)
            ]
            room_ids_for_task = [int(room["id"]) for room in eligible_rooms]
            if (task["room_assignment_mode"] == "preferred"
                    and task["preferred_room_id"] is not None
                    and task["preferred_room_id"] in room_ids_for_task):
                room_ids_for_task = [task["preferred_room_id"]] + [
                    value for value in room_ids_for_task if value != task["preferred_room_id"]
                ]
        else:
            room_ids_for_task = [None]

        for day in days:
            day_id = int(day["id"])
            for index, period in enumerate(periods):
                span = span_for(index, task["duration"])
                if not span:
                    continue
                start, end = str(span[0]["start_time"]), str(span[-1]["end_time"])
                if any(_overlap(start, end, str(br["start_time"]), str(br["end_time"])) for br in configured_breaks):
                    continue
                try:
                    _validate_constraints(cur, school_id, profile_id, "instructional", "lesson",
                        task["subject_id"], task["classes"], task["teachers"], None,
                        day_id, int(period["id"]), start, end, None)
                except TimetableSetupError:
                    continue
                unavailable = cur.execute(
                    """SELECT 1 FROM ds_timetable_teacher_availability
                       WHERE school_id=? AND profile_id=? AND day_id=?
                         AND availability='unavailable' AND teacher_id IN (
                           SELECT teacher_id FROM ds_timetable_scheduling_requirement_teachers
                           WHERE school_id=? AND profile_id=? AND requirement_id=?
                         ) AND period_id IN (""" + ",".join("?" for _ in span) + ") LIMIT 1",
                    (school_id, profile_id, day_id, school_id, profile_id,
                     task["requirement_id"], *[int(p["id"]) for p in span]),
                ).fetchone()
                if unavailable:
                    continue
                for room_id in room_ids_for_task:
                    if _validate_constraints:
                        try:
                            _validate_constraints(cur, school_id, profile_id, "instructional", "lesson",
                                task["subject_id"], task["classes"], task["teachers"], room_id,
                                day_id, int(period["id"]), start, end, None)
                        except TimetableSetupError:
                            continue
                    if find_session_conflicts(connection, school_id, profile_id, start, end,
                        task["classes"], task["teachers"], task["learners"], room_id, day_id,
                        ignore_generated_sessions=True, ignore_generated_legacy_lessons=True):
                        continue
                    options.append({"day_id": day_id, "period_id": int(period["id"]),
                        "start": start, "end": end, "room_id": room_id,
                        "duration": task["duration"], "period_no": int(period["period_no"])})
        if not options:
            raise TimetableSetupError("No valid slot is available for normalized requirement '" + task["name"] + "'. Check constraints, teacher availability, rooms and period patterns.")
        options.sort(key=lambda option: (preference_penalty(task, option),
                                          0 if task["preferred_day_id"] == option["day_id"] else 1,
                                          option["period_no"], option["day_id"]))
        candidates.append(options)

    # Candidate construction above completes every database-backed lookup.
    # Release its read transaction before recursive search, which is entirely
    # in memory and can otherwise leave Supabase table locks open for minutes.
    connection.commit()

    order = sorted(range(len(tasks)), key=lambda i: (len(candidates[i]), -tasks[i]["duration"], tasks[i]["requirement_id"], tasks[i]["session_no"]))
    planned = []
    nodes = 0

    def overlaps(a, b):
        return a["day_id"] == b["day_id"] and a["start"] < b["end"] and a["end"] > b["start"]

    def compatible(task, option):
        for class_id in task["classes"]:
            limit = class_limits.get(int(class_id))
            if not limit:
                continue
            same_class_week = sum(
                1 for placed in planned if int(class_id) in placed["task"]["classes"]
            )
            if limit["max_lessons_per_week"] is not None and same_class_week >= int(limit["max_lessons_per_week"]):
                return False
            same_class_day_periods = sum(
                int(placed["option"]["duration"]) for placed in planned
                if int(class_id) in placed["task"]["classes"]
                and int(placed["option"]["day_id"]) == int(option["day_id"])
            )
            if limit["max_periods_per_day"] is not None and same_class_day_periods + int(option["duration"]) > int(limit["max_periods_per_day"]):
                return False
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

    now = _now()
    snapshot = {
        "profile_id": profile_id,
        "engine_version": ENGINE_VERSION,
        "normalized_requirement_ids": sorted({int(item["task"]["requirement_id"]) for item in planned}),
    }
    cur.execute(
        """INSERT INTO ds_timetable_generation_runs
           (school_id,profile_id,status,engine_version,input_snapshot_json,started_at,created_by,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (school_id, profile_id, "running", ENGINE_VERSION, json.dumps(snapshot, sort_keys=True),
         now, created_by, now),
    )
    run_id = int(cur.lastrowid or 0)
    if not run_id:
        run_row = cur.execute(
            """SELECT id FROM ds_timetable_generation_runs
               WHERE school_id=? AND profile_id=? AND created_at=?
               ORDER BY id DESC LIMIT 1""",
            (school_id, profile_id, now),
        ).fetchone()
        run_id = int(run_row["id"]) if run_row else 0
    if not run_id:
        raise TimetableSetupError("Could not create a generation run record for the normalized weekly timetable.")
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
                generation_run_id=run_id, ignore_generated_conflicts=True,
                ignore_generated_legacy_conflicts=True,
            ))
        old_rows = cur.execute(
            """SELECT id FROM ds_timetable_sessions
               WHERE school_id=? AND profile_id=? AND schedule_layer='instructional'
                 AND generation_run_id IS NOT NULL AND generation_run_id<>?
                 AND status='scheduled'""",
            (school_id, profile_id, run_id),
        ).fetchall()
        old_ids = [int(row["id"]) for row in old_rows]
        if old_ids and not defer_replacement:
            marks = ",".join("?" for _ in old_ids)
            cur.execute(f"DELETE FROM ds_timetable_session_classes WHERE session_id IN ({marks})", tuple(old_ids))
            cur.execute(f"DELETE FROM ds_timetable_session_teachers WHERE session_id IN ({marks})", tuple(old_ids))
            cur.execute(f"DELETE FROM ds_timetable_session_learners WHERE session_id IN ({marks})", tuple(old_ids))
            cur.execute(f"DELETE FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND id IN ({marks})",
                        (school_id, profile_id, *old_ids))
        summary = {
            "status": "completed",
            "generated_sessions": len(created),
            "search_nodes": nodes,
            "message": "Advanced instructional sessions generated with combined-class, team-teaching and shared conflict validation.",
        }
        cur.execute(
            """UPDATE ds_timetable_generation_runs
               SET status='completed',result_summary_json=?,finished_at=?
               WHERE id=? AND school_id=?""",
            (json.dumps(summary, sort_keys=True), _now(), run_id, school_id),
        )
        connection.commit()
    except Exception:
        if created:
            marks = ",".join("?" for _ in created)
            cur.execute(f"DELETE FROM ds_timetable_session_classes WHERE session_id IN ({marks})", tuple(created))
            cur.execute(f"DELETE FROM ds_timetable_session_teachers WHERE session_id IN ({marks})", tuple(created))
            cur.execute(f"DELETE FROM ds_timetable_session_learners WHERE session_id IN ({marks})", tuple(created))
            cur.execute(f"DELETE FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND id IN ({marks})",
                        (school_id, profile_id, *created))
        cur.execute(
            "UPDATE ds_timetable_generation_runs SET status='failed',finished_at=? WHERE id=? AND school_id=?",
            (_now(), run_id, school_id),
        )
        connection.commit()
        raise
    return {
        "status": "completed",
        "run_id": run_id,
        "generated_sessions": len(created),
        "session_ids": created,
        "previous_session_ids": old_ids,
        "search_nodes": nodes,
        "message": "Advanced instructional sessions generated with combined-class, team-teaching and shared conflict validation.",
    }


def generate_dated_advanced_sessions(connection: Any, school_id: int, profile_id: int,
                                     start_date: str, end_date: str,
                                     created_by: str = "", node_limit: int = DEFAULT_NODE_LIMIT) -> dict:
    """Generate normalized sessions against actual calendar dates and day templates.

    Weekly patterns are repeated per calendar week in the requested range. Each
    dated placement uses that date's day template, rotation and shared conflict
    engine; recurring weekly templates are not rewritten.
    """
    from datetime import date, timedelta
    from app.timetable.advanced_setup import expand_calendar_occurrences
    from app.timetable.session_engine import create_scheduled_session, find_session_conflicts

    occurrences = expand_calendar_occurrences(
        connection, school_id, profile_id, start_date, end_date, include_closed=True
    )
    if not occurrences:
        raise TimetableSetupError("No calendar dates were found in the requested range.")
    cur = connection.cursor()
    _profile(cur, school_id, profile_id)
    requirements = cur.execute(
        """SELECT * FROM ds_timetable_scheduling_requirements
           WHERE school_id=? AND profile_id=? AND is_active=1 ORDER BY id""",
        (school_id, profile_id),
    ).fetchall()
    if not requirements:
        raise TimetableSetupError("No active normalized scheduling requirements are configured.")

    limits = {
        int(row["class_id"]): row for row in cur.execute(
            """SELECT class_id,max_lessons_per_week,max_periods_per_day
               FROM ds_timetable_class_limits WHERE school_id=? AND profile_id=?""",
            (school_id, profile_id),
        ).fetchall()
    }
    date_rows = {item["date"]: item for item in occurrences}
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    week_dates: dict[str, list[str]] = {}
    for offset in range((end - start).days + 1):
        current = start + timedelta(days=offset)
        monday = current - timedelta(days=current.weekday())
        week_dates.setdefault(monday.isoformat(), []).append(current.isoformat())

    tasks = []
    for week_key, dates in sorted(week_dates.items()):
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
                raise TimetableSetupError("Requirement '" + str(req["name"]) + "' needs a complete weekly session pattern.")
            if not classes and not learners and req["schedule_layer"] == "instructional":
                raise TimetableSetupError("Requirement '" + str(req["name"]) + "' has no assigned classes or learners.")
            for pattern in patterns:
                tasks.append({
                    "week": week_key, "dates": dates, "requirement_id": rid,
                    "session_no": int(pattern["session_no"]), "pattern": dict(pattern),
                    "classes": classes, "teachers": teachers, "learners": learners,
                    "subject_id": int(req["subject_id"]) if req["subject_id"] is not None else None,
                    "programme_id": int(req["programme_id"]) if req["programme_id"] is not None else None,
                    "group_id": int(req["teaching_group_id"]) if req["teaching_group_id"] is not None else None,
                    "layer": str(req["schedule_layer"]), "session_type": str(req["session_type"]),
                    "room_type": req["room_type"], "name": str(req["name"]),
                })

    def active_rotation(occurrence, programme_id):
        if programme_id is None:
            return True
        programme = cur.execute(
            """SELECT rotation_cycle_id FROM ds_timetable_learning_programmes
               WHERE id=? AND school_id=? AND profile_id=? AND is_active=1""",
            (programme_id, school_id, profile_id),
        ).fetchone()
        cycle_id = int(programme["rotation_cycle_id"]) if programme and programme["rotation_cycle_id"] is not None else None
        relevant = [r for r in occurrence["rotations"]
                    if r.get("week") and (cycle_id is None or int(r["cycle_id"]) == cycle_id)]
        if not relevant:
            return True
        return any(r.get("programme_id") == programme_id for r in relevant)

    def slot_span(slots, index, task):
        pattern = task["pattern"]
        duration = int(pattern["duration_periods"] or 0)
        minutes = int(pattern["duration_minutes"] or 0)
        layer = task["layer"]
        allowed = {
            "instructional": {"instructional", "lesson", "teaching"},
            "additional_learning": {"remedial", "study"},
            "school_activity": {"activity", "assembly", "other"},
        }.get(layer, set())
        if duration:
            selected = slots[index:index + duration]
        else:
            selected = [slots[index]]
        if not selected or any(str(s["slot_type"]).lower() not in allowed for s in selected):
            return None
        if duration and len(selected) != duration:
            return None
        if minutes:
            actual = (int(str(selected[-1]["end_time"])[:2]) * 60 + int(str(selected[-1]["end_time"])[3:])) - (int(str(selected[0]["start_time"])[:2]) * 60 + int(str(selected[0]["start_time"])[3:]))
            if actual != minutes:
                return None
        for prev, current in zip(selected, selected[1:]):
            if int(current["slot_no"]) != int(prev["slot_no"]) + 1 or str(prev["end_time"]) != str(current["start_time"]):
                return None
        return selected

    candidates = []
    for task in tasks:
        options = []
        for occurrence_date in task["dates"]:
            occurrence = date_rows.get(occurrence_date)
            if not occurrence or occurrence["day_id"] is None:
                continue
            if task["layer"] == "instructional" and not occurrence["is_instructional"]:
                continue
            if task["layer"] != "instructional" and not (
                occurrence["is_instructional"] or occurrence["template_id"] is not None
            ):
                continue
            if not active_rotation(occurrence, task["programme_id"]):
                continue
            slots = occurrence["schedule_slots"]
            preferred_slot = task["pattern"]["preferred_slot_id"]
            for index, slot in enumerate(slots):
                if preferred_slot is not None and int(slot["id"]) != int(preferred_slot):
                    continue
                selected = slot_span(slots, index, task)
                if not selected:
                    continue
                start_time, end_time = str(selected[0]["start_time"]), str(selected[-1]["end_time"])
                period_id = None
                period_no = selected[0]["period_no"]
                if period_no is not None:
                    period = cur.execute(
                        "SELECT id FROM ds_timetable_periods WHERE school_id=? AND profile_id=? AND period_no=?",
                        (school_id, profile_id, int(period_no)),
                    ).fetchone()
                    period_id = int(period["id"]) if period else None
                if task["pattern"]["preferred_day_id"] is not None and int(task["pattern"]["preferred_day_id"]) != int(occurrence["day_id"]):
                    continue
                try:
                    _validate_constraints(
                        cur, school_id, profile_id, task["layer"], task["session_type"],
                        task["subject_id"], task["classes"], task["teachers"], None,
                        int(occurrence["day_id"]), period_id, start_time, end_time, occurrence_date,
                    )
                except TimetableSetupError:
                    continue
                room_ids = [None]
                if task["room_type"]:
                    room_ids = [
                        int(r["id"]) for r in cur.execute(
                            """SELECT id,allocation_mode,assigned_class_id FROM ds_timetable_rooms
                               WHERE school_id=? AND is_active=1 AND room_type=?
                               ORDER BY capacity DESC,id""",
                            (school_id, task["room_type"]),
                        ).fetchall()
                        if str(r["allocation_mode"] or "shared") != "dedicated"
                        or int(r["assigned_class_id"] or 0) in task["classes"]
                    ]
                for room_id in room_ids:
                    try:
                        _validate_constraints(
                            cur, school_id, profile_id, task["layer"], task["session_type"],
                            task["subject_id"], task["classes"], task["teachers"], room_id,
                            int(occurrence["day_id"]), period_id, start_time, end_time, occurrence_date,
                        )
                    except TimetableSetupError:
                        continue
                    period_ids = [
                        int(p["id"]) for p in cur.execute(
                            "SELECT id FROM ds_timetable_periods WHERE school_id=? AND profile_id=? AND period_no BETWEEN ? AND ?",
                            (school_id, profile_id,
                             int(selected[0]["period_no"] or 0),
                             int(selected[-1]["period_no"] or 0)),
                        ).fetchall()
                    ] if selected[0]["period_no"] is not None else []
                    if period_ids and teachers:
                        marks = ",".join("?" for _ in period_ids)
                        unavailable = cur.execute(
                            """SELECT 1 FROM ds_timetable_teacher_availability
                               WHERE school_id=? AND profile_id=? AND day_id=?
                                 AND availability='unavailable' AND teacher_id IN (
                                   SELECT teacher_id FROM ds_timetable_scheduling_requirement_teachers
                                   WHERE school_id=? AND profile_id=? AND requirement_id=?
                                 ) AND period_id IN (""" + marks + ") LIMIT 1",
                            (school_id, profile_id, int(occurrence["day_id"]),
                             school_id, profile_id, task["requirement_id"], *period_ids),
                        ).fetchone()
                        if unavailable:
                            continue
                    if find_session_conflicts(
                        connection, school_id, profile_id, start_time, end_time,
                        task["classes"], task["teachers"], task["learners"],
                        room_id, int(occurrence["day_id"]), occurrence_date,
                    ):
                        continue
                    options.append({
                        "date": occurrence_date, "day_id": int(occurrence["day_id"]),
                        "period_id": period_id, "start": start_time, "end": end_time,
                        "room_id": room_id, "duration": int(task["pattern"]["duration_periods"] or 0),
                        "slots": selected,
                    })
        if not options:
            raise TimetableSetupError(
                "No date and slot can satisfy '" + task["name"] + "' session " +
                str(task["session_no"]) + " in week " + task["week"] +
                ". Check day templates, rotations, constraints and availability."
            )
        candidates.append(options)

    order = sorted(range(len(tasks)), key=lambda i: (len(candidates[i]), -int(tasks[i]["pattern"]["duration_periods"] or 0), tasks[i]["requirement_id"], tasks[i]["session_no"]))
    planned = []
    nodes = 0

    def compatible(task, option):
        for class_id in task["classes"]:
            limit = limits.get(int(class_id))
            if not limit:
                continue
            same_week = sum(1 for item in planned
                            if item["task"]["week"] == task["week"]
                            and int(class_id) in item["task"]["classes"])
            if limit["max_lessons_per_week"] is not None and same_week >= int(limit["max_lessons_per_week"]):
                return False
            same_day = sum(int(item["option"]["duration"] or 1) for item in planned
                           if item["option"]["date"] == option["date"]
                           and int(class_id) in item["task"]["classes"])
            if limit["max_periods_per_day"] is not None and same_day + int(option["duration"] or 1) > int(limit["max_periods_per_day"]):
                return False
        for item in planned:
            other = item["option"]
            if other["date"] != option["date"] or not _overlap(option["start"], option["end"], other["start"], other["end"]):
                continue
            other_task = item["task"]
            if (set(task["classes"]) & set(other_task["classes"])
                or set(task["teachers"]) & set(other_task["teachers"])
                or set(task["learners"]) & set(other_task["learners"])
                or (option["room_id"] is not None and option["room_id"] == other["room_id"])):
                return False
        return True

    def search(position):
        nonlocal nodes
        if position >= len(order):
            return True
        index = order[position]
        for option in candidates[index]:
            nodes += 1
            if nodes > int(node_limit):
                return False
            if compatible(tasks[index], option):
                planned.append({"task": tasks[index], "option": option})
                if search(position + 1):
                    return True
                planned.pop()
        return False

    if not search(0):
        raise TimetableSetupError("The dated requirements cannot all fit without clashes in the selected calendar range.")

    created = []
    try:
        for item in planned:
            task, option = item["task"], item["option"]
            created.append(create_scheduled_session(
                connection, school_id, profile_id, option["start"], option["end"],
                schedule_layer=task["layer"], session_type=task["session_type"],
                class_ids=task["classes"], teacher_ids=task["teachers"],
                learner_ids=task["learners"], room_id=option["room_id"],
                day_id=option["day_id"], session_date=option["date"],
                period_id=option["period_id"], subject_id=task["subject_id"],
                programme_id=task["programme_id"], teaching_group_id=task["group_id"],
                duration_periods=option["duration"],
                scheduling_requirement_id=task["requirement_id"],
                pattern_session_no=task["session_no"], created_by=created_by,
            ))
    except Exception:
        if created:
            marks = ",".join("?" for _ in created)
            for table in ("ds_timetable_session_classes", "ds_timetable_session_teachers", "ds_timetable_session_learners"):
                cur.execute(f"DELETE FROM {table} WHERE session_id IN ({marks})", tuple(created))
            cur.execute(
                f"DELETE FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND id IN ({marks})",
                (school_id, profile_id, *created),
            )
            connection.commit()
        raise
    return {
        "status": "completed", "generated_sessions": len(created),
        "session_ids": created, "search_nodes": nodes,
        "date_range": {"start": start_date, "end": end_date},
        "message": "Dated sessions generated from calendar templates and active rotation programmes.",
    }
