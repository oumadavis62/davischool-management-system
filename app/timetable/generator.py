"""Constraint-based automatic timetable generation (v1)."""
from __future__ import annotations

from datetime import datetime, timezone
from bisect import bisect_left, insort
import json
import time
from typing import Any

from app.timetable.setup import TimetableSetupError, _profile
from app.timetable.session_engine import _validate_constraints


ENGINE_VERSION = "11.0-cpsat"
DEFAULT_NODE_LIMIT = 10_000_000
GENERATION_TIME_LIMIT_SECONDS = 120.0


def _check_generation_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimetableSetupError(
            "Timetable generation reached its 120-second processing limit. "
            "Your existing timetable was preserved. Simplify conflicting constraints or split the generation into smaller sections, then retry."
        )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return str(a_start) < str(b_end) and str(a_end) > str(b_start)


def _interval_list_overlaps(intervals, start: str, end: str) -> bool:
    """Check a sorted, non-overlapping resource interval list in logarithmic time."""
    position = bisect_left(intervals, (str(start), ""))
    index = position - 1
    while index >= 0:
        prior_start, prior_end = intervals[index][0], intervals[index][1]
        if str(prior_end) <= str(start):
            break
        if _overlap(start, end, prior_start, prior_end):
            return True
        index -= 1
    return position < len(intervals) and str(intervals[position][0]) < str(end)


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
    # A class may receive a subject only once per day. A configured double
    # lesson is represented by one candidate with duration > 1, not by two
    # separate placements, so it remains valid while repeated sessions do not.
    if any(
        int(p["class_id"]) == int(task["class_id"])
        and int(p["subject_id"]) == int(task["subject_id"])
        and int(p["day_id"]) == int(candidate["day_id"])
        for p in placements
    ):
        return False

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


def generate_timetable(connection: Any, school_id: int, profile_id: int, created_by: str = "", node_limit: int = DEFAULT_NODE_LIMIT, normalized_run_id: int | None = None, deadline: float | None = None) -> dict:
    deadline = deadline if deadline is not None else time.monotonic() + GENERATION_TIME_LIMIT_SECONDS
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
            AND rt.requirement_id=r.id AND rt.role='lead'
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
        _check_generation_deadline(deadline)
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
            """SELECT duration_periods,preferred_period_id,linked_class_ids_json,co_teacher_ids_json FROM ds_timetable_requirement_patterns
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
        if configured_pattern and pattern_periods != expected_periods:
            raise TimetableSetupError(
                "The saved lesson mix for class ID " + str(key[0]) + ", subject ID " + str(key[1])
                + " currently uses " + str(pattern_periods) + " of " + str(expected_periods)
                + " required weekly periods. Add the remaining single, double, triple or quadruple sessions before generating."
            )
        if configured_pattern:
            # A saved pattern is the exact list of lesson sessions. The weekly
            # target is measured in occupied periods, so a double plus three
            # singles fulfils a five-period allocation in four sessions.
            planned_sessions = [
                {"duration": int(x["duration_periods"]), "preferred_period_id": int(x["preferred_period_id"]) if x["preferred_period_id"] is not None else None,
                 "linked_class_ids": [int(v) for v in json.loads(x["linked_class_ids_json"] or "[]") if int(v) > 0],
                 "co_teacher_ids": [int(v) for v in json.loads(x["co_teacher_ids_json"] or "[]") if int(v) > 0]}
                for x in configured_pattern
            ]
            remaining = len(planned_sessions)
        else:
            # Start with the non-manual weekly occurrences; shared sessions
            # are removed from this list immediately below.
            planned_sessions = [
                {"duration": duration, "preferred_period_id": None}
                for _ in range(max(0, weekly - already))
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
        if configured_pattern:
            # Shared sessions are already placed elsewhere, so only the
            # remaining configured sessions become solver tasks.
            remaining = len(planned_sessions)
        if len(planned_sessions) > remaining:
            raise TimetableSetupError(
                "The configured lesson pattern contains more weekly sessions than the remaining lesson requirement for class ID "
                + str(key[0]) + ", subject ID " + str(key[1]) + ". Review the weekly pattern."
            )
        if len(planned_sessions) != remaining:
            raise TimetableSetupError(
                "The weekly lesson pattern does not cover every required occurrence for class ID "
                + str(key[0]) + ", subject ID " + str(key[1]) + "."
            )
        total_required += remaining
        for occurrence, planned in enumerate(planned_sessions):
            tasks.append({
                "class_id": key[0],
                "subject_id": key[1],
                "teacher_id": key[2],
                "class_ids": sorted({key[0], *planned.get("linked_class_ids", [])}),
                "teacher_ids": sorted({key[2], *planned.get("co_teacher_ids", [])}),
                "duration": planned["duration"],
                "preferred_period_id": planned["preferred_period_id"],
                "max_lessons_per_day": int(req["max_lessons_per_day"]) if req["max_lessons_per_day"] is not None else None,
                "max_lessons_per_week": int(class_limits[key[0]]["max_lessons_per_week"]) if key[0] in class_limits and class_limits[key[0]]["max_lessons_per_week"] is not None else None,
                "max_periods_per_day": int(class_limits[key[0]]["max_periods_per_day"]) if key[0] in class_limits and class_limits[key[0]]["max_periods_per_day"] is not None else None,
                "occurrence": occurrence + 1,
            })
    if len(tasks) > 20_000:
        raise TimetableSetupError("This timetable exceeds the supported 20,000 unscheduled lesson-occurrence capacity. Reduce duplicate requirements or generate the school in separate timetable profiles.")

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
            "period_end_no": int(span[-1]["period_no"]),
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
    candidate_filter_diagnostics = {}
    for task_index, task in enumerate(tasks):
        _check_generation_deadline(deadline)
        candidates = []
        filter_reasons = {}
        def filtered(reason):
            filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
        for day in days:
            _check_generation_deadline(deadline)
            day_id = int(day["id"])
            for start_index, period in enumerate(periods):
                _check_generation_deadline(deadline)
                if task.get("preferred_period_id") is not None and int(period["id"]) != int(task["preferred_period_id"]):
                    filtered("not_the_preferred_period")
                    continue
                # A single configured lesson must fit the class's daily
                # period ceiling on its own; otherwise no placement can ever
                # satisfy the workload limit, regardless of the search order.
                if any(
                    class_limits.get(class_id) is not None
                    and class_limits[class_id]["max_periods_per_day"] is not None
                    and int(task["duration"]) > int(class_limits[class_id]["max_periods_per_day"])
                    for class_id in task.get("class_ids", [task["class_id"]])
                ):
                    filtered("lesson_duration_exceeds_class_daily_limit")
                    continue
                span = _period_span(periods, start_index, task["duration"])
                if not span:
                    filtered("no_contiguous_teaching_period_span")
                    continue
                if any((teacher_id, day_id, int(p["id"])) in unavailable for teacher_id in task.get("teacher_ids", [task["teacher_id"]]) for p in span):
                    filtered("teacher_marked_unavailable")
                    continue
                if any((task["subject_id"], day_id, int(p["id"])) in subject_unavailable for p in span):
                    filtered("subject_marked_unavailable")
                    continue
                if any(
                    _overlap(span[0]["start_time"], span[-1]["end_time"], b["start_time"], b["end_time"])
                    for b in breaks
                ):
                    filtered("overlaps_configured_break")
                    continue
                try:
                    _validate_constraints(
                        cur, school_id, profile_id, "instructional", "lesson",
                        task["subject_id"], task.get("class_ids", [task["class_id"]]), task.get("teacher_ids", [task["teacher_id"]]),
                        None, day_id, int(period["id"]),
                        str(span[0]["start_time"]), str(span[-1]["end_time"]), None,
                        cache=constraint_cache,
                    )
                except TimetableSetupError as constraint_error:
                    filtered("constraint: " + str(constraint_error))
                    continue
                candidates.append({
                    "day_id": day_id,
                    "period_id": int(period["id"]),
                    "duration": len(span),
                    "start_time": span[0]["start_time"],
                    "end_time": span[-1]["end_time"],
                    "period_no": int(period["period_no"]),
                    "period_end_no": int(span[-1]["period_no"]),
                    "preferred": any((teacher_id, day_id, int(p["id"])) in preferred for teacher_id in task.get("teacher_ids", [task["teacher_id"]]) for p in span),
                    "explicitly_available": (
                        all((teacher_id, day_id, int(p["id"])) not in fallback_only for teacher_id in task.get("teacher_ids", [task["teacher_id"]]) for p in span)
                        and all((task["subject_id"], day_id, int(p["id"])) not in subject_fallback_only for p in span)
                    ),
                })
        candidate_filter_diagnostics[task_index] = filter_reasons
        if not candidates:
            class_row = cur.execute("SELECT name FROM classes WHERE school_id=? AND id=?", (school_id, int(task["class_id"]))).fetchone()
            subject_row = cur.execute("SELECT name FROM subjects WHERE school_id=? AND id=?", (school_id, int(task["subject_id"]))).fetchone()
            teacher_row = cur.execute("SELECT name FROM teachers WHERE school_id=? AND id=?", (school_id, int(task["teacher_id"]))).fetchone()
            class_label = str(class_row["name"]) if class_row else "Class ID " + str(task["class_id"])
            subject_label = str(subject_row["name"]) if subject_row else "Subject ID " + str(task["subject_id"])
            teacher_label = str(teacher_row["name"]) if teacher_row else "Teacher ID " + str(task["teacher_id"])
            filter_detail = "; ".join(reason + ": " + str(count) for reason, count in sorted(filter_reasons.items(), key=lambda pair: -pair[1]))
            message = (
                "No eligible timetable slot exists for " + class_label + " / " + subject_label
                + " / " + teacher_label + " (lesson " + str(task["occurrence"]) + "). "
                + "The candidate scan rejected every slot. " + (filter_detail or "No candidate slot passed the configured filters.")
                + ". Check the named teacher's availability, subject restrictions, lesson duration, breaks and timetable constraints."
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
                "failure_code": "no_eligible_candidate_slots",
                "affected_lesson": {
                    "class": class_label, "class_id": int(task["class_id"]),
                    "subject": subject_label, "subject_id": int(task["subject_id"]),
                    "teacher": teacher_label, "teacher_id": int(task["teacher_id"]),
                    "lesson_occurrence": int(task["occurrence"]),
                    "lesson_duration_periods": int(task["duration"]),
                },
                "candidate_filter_rejections": filter_reasons,
                "recommended_action": "Review the availability and constraints listed in the failure details for this class, subject and teacher.",
            }
            snapshot = {
                "profile_id": profile_id,
                "engine_version": ENGINE_VERSION,
                "reason": message,
                "candidate_filter_rejections": filter_reasons,
                "affected_lesson": {"class_id": int(task["class_id"]), "subject_id": int(task["subject_id"]), "teacher_id": int(task["teacher_id"])},
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

    # Build a CP-SAT model from the already validated lesson domains.
    # The first pass searches for a solution using explicitly available slots.
    # If that is infeasible or inconclusive, a second pass permits fallback-only
    # slots. A final optimisation pass improves preferences without weakening
    # any hard scheduling rule.
    from collections import defaultdict
    from ortools.sat.python import cp_model

    candidate_lookup = {i: list(values) for i, values in candidates_by_task}
    candidate_filter_diagnostics = candidate_filter_diagnostics
    blocked_candidates = set()
    blocked_candidate_counts = {}
    rejection_counts = {}
    rejection_by_requirement = {}
    placements = list(fixed)
    nodes = 0
    strict_nodes = 0
    fallback_nodes = 0
    exhausted = False
    exhausted_reason = None
    strict_stop_reason = None
    fallback_stop_reason = None
    search_started_at = time.monotonic()

    # Load normalized shared sessions once. These are fixed anchors for the
    # legacy lesson solver and include all linked classes and co-teachers.
    existing_by_id = {}
    conflict_sql = """SELECT s.id,s.day_id,s.start_time,s.end_time,s.duration_periods,s.room_id,s.subject_id,s.schedule_layer,
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
            "classes": set(), "teachers": set(), "subject_id": int(row["subject_id"]) if row["subject_id"] is not None else None,
            "schedule_layer": str(row["schedule_layer"] or "instructional"),
            "duration_periods": int(row["duration_periods"] or 1),
        })
        if row["class_id"] is not None:
            item["classes"].add(int(row["class_id"]))
        if row["teacher_id"] is not None:
            item["teachers"].add(int(row["teacher_id"]))
    existing_sessions = list(existing_by_id.values())

    # Fixed instructional subject occupancy for each teacher/class pair.
    fixed_teacher_class_subject_period = defaultdict(set)
    for item in fixed:
        fixed_span = _period_span(
            periods, period_index[int(item["period_id"])], int(item["duration"])
        )
        for period in fixed_span or []:
            fixed_teacher_class_subject_period[
                (int(item["class_id"]), int(item["teacher_id"]), int(item["day_id"]), int(period["period_no"]))
            ].add(int(item["subject_id"]))
    for session in existing_sessions:
        if session.get("day_id") is None or session.get("schedule_layer") != "instructional" or session.get("subject_id") is None:
            continue
        for period in periods:
            if _overlap(str(period["start_time"]), str(period["end_time"]),
                        session["start_time"], session["end_time"]):
                for class_id in session["classes"]:
                    for teacher_id in session["teachers"]:
                        fixed_teacher_class_subject_period[
                            (int(class_id), int(teacher_id), int(session["day_id"]), int(period["period_no"]))
                        ].add(int(session["subject_id"]))

    # Preserve the existing database transaction boundary: all input reads
    # finish before the CPU-intensive constraint solve begins.
    connection.commit()

    day_order = {int(day["id"]): index for index, day in enumerate(days)}
    period_by_id = {int(period["id"]): period for period in periods}
    fixed_class_periods = set()
    fixed_teacher_periods = set()
    fixed_room_periods = set()
    fixed_schoolwide_block_periods = set()
    fixed_subject_days = set()
    fixed_class_week = {}
    fixed_class_day_periods = {}
    fixed_teacher_day_periods = {}
    fixed_subject_day_count = {}
    fixed_teacher_day_count = {}
    # Fixed lessons also participate in cross-day subject/period distribution.
    fixed_subject_period_days = defaultdict(set)
    for item in fixed:
        day_id = int(item["day_id"])
        class_id = int(item["class_id"])
        teacher_id = int(item["teacher_id"])
        subject_id = int(item["subject_id"])
        start_index = period_index[int(item["period_id"])]
        span = _period_span(periods, start_index, int(item["duration"]))
        period_ids = [int(p["id"]) for p in span or []]
        fixed_class_week[class_id] = fixed_class_week.get(class_id, 0) + 1
        fixed_subject_days.add((class_id, subject_id, day_id))
        fixed_subject_day_count[(class_id, subject_id, teacher_id, day_id)] = fixed_subject_day_count.get((class_id, subject_id, teacher_id, day_id), 0) + 1
        fixed_class_day_periods[(class_id, day_id)] = fixed_class_day_periods.get((class_id, day_id), 0) + len(period_ids)
        fixed_teacher_day_periods[(teacher_id, day_id)] = fixed_teacher_day_periods.get((teacher_id, day_id), 0) + len(period_ids)
        if len(period_ids) > 1:
            for pid in period_ids:
                fixed_schoolwide_block_periods.add((day_id, pid))
        for pid in period_ids:
            period_no = int(period_by_id[pid]["period_no"])
            fixed_subject_period_days[(class_id, subject_id, period_no)].add(day_id)
            fixed_class_periods.add((class_id, day_id, pid))
            fixed_teacher_periods.add((teacher_id, day_id, pid))
            if item.get("room_id") is not None:
                fixed_room_periods.add((int(item["room_id"]), day_id, pid))

    # Normalized sessions occupy their linked resources and periods. They are
    # treated as fixed for this solve, never silently moved by the legacy engine.
    shared_class_periods = set()
    shared_teacher_periods = set()
    shared_room_periods = set()
    shared_subject_days = set()
    for session in existing_sessions:
        if session["day_id"] is None:
            continue
        day_id = int(session["day_id"])
        session_periods = []
        for period in periods:
            if _overlap(str(period["start_time"]), str(period["end_time"]),
                        session["start_time"], session["end_time"]):
                pid = int(period["id"])
                session_periods.append(pid)
                for class_id in session["classes"]:
                    shared_class_periods.add((class_id, day_id, pid))
                for teacher_id in session["teachers"]:
                    shared_teacher_periods.add((teacher_id, day_id, pid))
                if session["room_id"] is not None:
                    shared_room_periods.add((int(session["room_id"]), day_id, pid))
        if session.get("schedule_layer") == "instructional":
            if int(session.get("duration_periods", 1) or 1) > 1:
                for pid in session_periods:
                    fixed_schoolwide_block_periods.add((day_id, pid))
            for class_id in session["classes"]:
                fixed_class_week[class_id] = fixed_class_week.get(class_id, 0) + 1
                fixed_class_day_periods[(class_id, day_id)] = fixed_class_day_periods.get((class_id, day_id), 0) + len(session_periods)
                if session.get("subject_id") is not None:
                    subject_id = int(session["subject_id"])
                    subject_key = (int(class_id), subject_id, day_id)
                    for pid in session_periods:
                        period_no = int(period_by_id[pid]["period_no"])
                        fixed_subject_period_days[(int(class_id), subject_id, period_no)].add(day_id)
                    for teacher_id in session["teachers"]:
                        cap_key = (int(class_id), int(session["subject_id"]), int(teacher_id), day_id)
                        fixed_subject_day_count[cap_key] = fixed_subject_day_count.get(cap_key, 0) + 1
            for teacher_id in session["teachers"]:
                teacher_key = (int(teacher_id), day_id)
                fixed_teacher_day_periods[teacher_key] = fixed_teacher_day_periods.get(teacher_key, 0) + len(session_periods)

    def build_cp_model(allow_fallback: bool):
        model = cp_model.CpModel()
        variables = {}
        variable_meta = {}
        by_class_period = defaultdict(list)
        by_teacher_period = defaultdict(list)
        by_teacher_class_period_subject = defaultdict(list)
        by_room_period = defaultdict(list)
        by_schoolwide_block_period = defaultdict(list)
        by_subject_day = defaultdict(list)
        by_subject_teacher_day = defaultdict(list)
        by_class_subject_period_day = defaultdict(list)
        by_class_day_periods = defaultdict(list)
        by_teacher_day_periods = defaultdict(list)
        by_class_week = defaultdict(list)
        by_task = defaultdict(list)
        rank_terms_by_task = defaultdict(list)
        objective_terms = []
        for task_index, task in enumerate(tasks):
            class_ids = sorted({int(v) for v in task.get("class_ids", [task["class_id"]])})
            teacher_ids = sorted({int(v) for v in task.get("teacher_ids", [task["teacher_id"]])})
            room_ids = _rooms_for_task(task)
            for candidate_rank, candidate in enumerate(candidate_lookup[task_index]):
                if not allow_fallback and not candidate.get("explicitly_available"):
                    continue
                start_index = period_index.get(int(candidate["period_id"]))
                if start_index is None:
                    continue
                span = _period_span(periods, start_index, int(candidate["duration"]))
                if not span:
                    continue
                period_ids = [int(p["id"]) for p in span]
                day_id = int(candidate["day_id"])
                for room_id in room_ids:
                    if (task_index, day_id, int(candidate["period_id"]), room_id) in blocked_candidates:
                        continue
                    conflict = False
                    if len(period_ids) > 1 and any((day_id, pid) in fixed_schoolwide_block_periods for pid in period_ids):
                        conflict = True
                    for pid in period_ids:
                        if any((cid, day_id, pid) in fixed_class_periods or (cid, day_id, pid) in shared_class_periods for cid in class_ids):
                            conflict = True
                            break
                        if any((tid, day_id, pid) in fixed_teacher_periods or (tid, day_id, pid) in shared_teacher_periods for tid in teacher_ids):
                            conflict = True
                            break
                        if room_id is not None and ((int(room_id), day_id, pid) in fixed_room_periods or (int(room_id), day_id, pid) in shared_room_periods):
                            conflict = True
                            break
                    # Leave a free period when this teacher changes subjects
                    # within the same class; the gap can be used for another class.
                    candidate_period_nos = range(
                        int(candidate["period_no"]),
                        int(candidate["period_no"]) + len(period_ids),
                    )
                    for class_id in class_ids:
                        for teacher_id in teacher_ids:
                            for period_no in candidate_period_nos:
                                for adjacent_no in (period_no - 1, period_no + 1):
                                    adjacent_subjects = fixed_teacher_class_subject_period.get(
                                        (class_id, teacher_id, day_id, adjacent_no), set()
                                    )
                                    if any(value != int(task["subject_id"]) for value in adjacent_subjects):
                                        conflict = True
                                        break
                                if conflict:
                                    break
                            if conflict:
                                break
                        if conflict:
                            break
                    if conflict:
                        continue
                    if any((cid, int(task["subject_id"]), day_id) in fixed_subject_days for cid in class_ids):
                        continue
                    key = (task_index, candidate_rank, room_id)
                    var = model.NewBoolVar("place_t{}_c{}_r{}".format(task_index, candidate_rank, room_id or 0))
                    variables[key] = var
                    variable_meta[key] = (task, candidate, room_id, period_ids)
                    by_task[task_index].append(var)
                    rank_terms_by_task[task_index].append((var, candidate_rank))
                    for cid in class_ids:
                        for pid in period_ids:
                            by_class_period[(cid, day_id, pid)].append(var)
                        by_subject_day[(cid, int(task["subject_id"]), day_id)].append(var)
                        for period_no in range(int(candidate["period_no"]), int(candidate["period_no"]) + len(period_ids)):
                            by_class_subject_period_day[(cid, int(task["subject_id"]), period_no, day_id)].append(var)
                        by_class_day_periods[(cid, day_id)].append((var, len(period_ids)))
                        by_class_week[cid].append(var)
                    for tid in teacher_ids:
                        for pid in period_ids:
                            by_teacher_period[(tid, day_id, pid)].append(var)
                        for cid in class_ids:
                            for period_no in candidate_period_nos:
                                by_teacher_class_period_subject[
                                    (cid, tid, day_id, period_no, int(task["subject_id"]))
                                ].append(var)
                        by_teacher_day_periods[(tid, day_id)].append((var, len(period_ids)))
                    if room_id is not None:
                        for pid in period_ids:
                            by_room_period[(int(room_id), day_id, pid)].append(var)
                    if len(period_ids) > 1:
                        for pid in period_ids:
                            by_schoolwide_block_period[(day_id, pid)].append(var)
                    by_subject_teacher_day[(int(task["class_id"]), int(task["subject_id"]), int(task["teacher_id"]), day_id)].append(var)
                    # Soft preferences: fallback-only cells carry a substantial
                    # penalty; preferred cells and earlier periods are favoured.
                    cost = (0 if candidate.get("explicitly_available") else 100000)
                    cost += (0 if candidate.get("preferred") else 500)
                    cost += int(candidate["period_no"]) * 5
                    cost += day_order.get(day_id, 0)
                    if room_id is not None:
                        cost += int(room_id) % 7
                    objective_terms.append((var, cost))
            if not by_task[task_index]:
                model.AddBoolOr([])
            else:
                model.Add(sum(by_task[task_index]) == 1)

        # Break permutations of identical weekly occurrences. Their candidate
        # domains are interchangeable, so require later occurrences to use a
        # candidate rank no earlier than the preceding occurrence.
        symmetry_groups = defaultdict(list)
        for task_index, task in enumerate(tasks):
            signature = (
                tuple(task.get("class_ids", [task["class_id"]])),
                tuple(task.get("teacher_ids", [task["teacher_id"]])),
                int(task["subject_id"]), int(task["duration"]),
                task.get("preferred_period_id"), task.get("max_lessons_per_day"),
                task.get("max_lessons_per_week"), task.get("max_periods_per_day"),
            )
            symmetry_groups[signature].append(task_index)
        for members in symmetry_groups.values():
            members.sort(key=lambda index: int(tasks[index]["occurrence"]))
            for previous_index, next_index in zip(members, members[1:]):
                previous_rank = sum(rank * var for var, rank in rank_terms_by_task[previous_index])
                next_rank = sum(rank * var for var, rank in rank_terms_by_task[next_index])
                model.Add(previous_rank <= next_rank)

        for group in (by_class_period, by_teacher_period, by_room_period, by_subject_day, by_schoolwide_block_period):
            for values in group.values():
                if len(values) > 1:
                    model.Add(sum(values) <= 1)

        # Different subjects taught by the same teacher to the same class
        # cannot occupy adjacent periods. Same-subject double/triple blocks
        # remain consecutive because they share one subject key.
        teacher_class_period_subjects = defaultdict(lambda: defaultdict(list))
        for (class_id, teacher_id, day_id, period_no, subject_id), values in by_teacher_class_period_subject.items():
            teacher_class_period_subjects[(class_id, teacher_id, day_id, period_no)][subject_id].extend(values)
        teacher_class_keys = {
            (class_id, teacher_id, day_id)
            for class_id, teacher_id, day_id, _period_no in teacher_class_period_subjects
        }
        for class_id, teacher_id, day_id in teacher_class_keys:
            period_numbers = sorted(
                period_no for cid, tid, day, period_no in teacher_class_period_subjects
                if cid == class_id and tid == teacher_id and day == day_id
            )
            for period_no in period_numbers:
                current_subjects = teacher_class_period_subjects[(class_id, teacher_id, day_id, period_no)]
                next_subjects = teacher_class_period_subjects.get((class_id, teacher_id, day_id, period_no + 1), {})
                for subject_id, current_vars in current_subjects.items():
                    for next_subject_id, next_vars in next_subjects.items():
                        if subject_id != next_subject_id:
                            model.Add(sum(current_vars) + sum(next_vars) <= 1)

        for key, values in by_subject_teacher_day.items():
            class_id, subject_id, teacher_id, day_id = key
            cap = next((int(task["max_lessons_per_day"]) for task in tasks
                        if int(task["class_id"]) == class_id and int(task["subject_id"]) == subject_id
                        and int(task["teacher_id"]) == teacher_id and task.get("max_lessons_per_day")), None)
            if cap is not None:
                model.Add(sum(values) + int(fixed_subject_day_count.get(key, 0)) <= cap)

        for class_id, values in by_class_week.items():
            limit = class_limits.get(class_id)
            if limit is not None and limit["max_lessons_per_week"] is not None:
                model.Add(sum(values) + int(fixed_class_week.get(class_id, 0)) <= int(limit["max_lessons_per_week"]))

        for (class_id, day_id), values in by_class_day_periods.items():
            limit = class_limits.get(class_id)
            if limit is not None and limit["max_periods_per_day"] is not None:
                model.Add(
                    sum(var * duration for var, duration in values)
                    + int(fixed_class_day_periods.get((class_id, day_id), 0))
                    <= int(limit["max_periods_per_day"])
                )

        # Discourage a class from studying the same subject in the same
        # period on multiple weekdays (e.g. Mathematics in Period 6 every day).
        # This is a soft objective: availability, manual placements, linked
        # classes, double/triple spans and all conflict rules remain intact.
        variable_days_by_subject_period = defaultdict(lambda: defaultdict(list))
        for (class_id, subject_id, period_no, day_id), values in by_class_subject_period_day.items():
            variable_days_by_subject_period[(class_id, subject_id, period_no)][day_id].extend(values)
        subject_period_keys = set(fixed_subject_period_days) | set(variable_days_by_subject_period)
        for key in subject_period_keys:
            fixed_days = set(fixed_subject_period_days.get(key, set()))
            day_variables = variable_days_by_subject_period.get(key, {})
            repeated_days = []
            for day_id, values in day_variables.items():
                if day_id in fixed_days:
                    continue
                presence = model.NewBoolVar("subject{}_class{}_period{}_day{}_present".format(key[1], key[0], key[2], day_id))
                model.Add(presence == sum(values))
                repeated_days.append(presence)
            if repeated_days:
                total_days = len(fixed_days) + sum(repeated_days)
                repeats = model.NewIntVar(0, len(days), "subject{}_class{}_period{}_repeat".format(key[1], key[0], key[2]))
                model.AddMaxEquality(repeats, [total_days - 1, 0])
                # Stronger than the ordinary period-order preference, but
                # deliberately weaker than any hard scheduling constraint.
                objective_terms.append((repeats, 300))

        # Balance daily teaching loads across the week. These are soft costs:
        # class, teacher, availability and room constraints remain hard.
        instructional_day_ids = [int(day["id"]) for day in days]
        class_ids_for_balance = {
            int(class_id) for task in tasks
            for class_id in task.get("class_ids", [task["class_id"]])
        } | {int(class_id) for class_id, _day in fixed_class_day_periods}
        for class_id in class_ids_for_balance:
            weekly_periods = sum(
                int(task["duration"]) for task in tasks
                if class_id in {int(v) for v in task.get("class_ids", [task["class_id"]])}
            ) + sum(
                value for (fixed_class_id, _day), value in fixed_class_day_periods.items()
                if fixed_class_id == class_id
            )
            if not weekly_periods:
                continue
            target = weekly_periods // max(1, len(instructional_day_ids))
            for day_id in instructional_day_ids:
                entries = by_class_day_periods.get((class_id, day_id), [])
                fixed_load = int(fixed_class_day_periods.get((class_id, day_id), 0))
                load = model.NewIntVar(0, weekly_periods, "class{}_day{}_load".format(class_id, day_id))
                model.Add(load == fixed_load + sum(var * duration for var, duration in entries))
                deviation = model.NewIntVar(0, weekly_periods, "class{}_day{}_balance".format(class_id, day_id))
                model.AddAbsEquality(deviation, load - target)
                objective_terms.append((deviation, 35))

        teacher_ids_for_balance = {
            int(teacher_id) for task in tasks
            for teacher_id in task.get("teacher_ids", [task["teacher_id"]])
        } | {int(teacher_id) for teacher_id, _day in fixed_teacher_day_periods}
        for teacher_id in teacher_ids_for_balance:
            weekly_periods = sum(
                int(task["duration"]) for task in tasks
                if teacher_id in {int(v) for v in task.get("teacher_ids", [task["teacher_id"]])}
            ) + sum(
                value for (fixed_teacher_id, _day), value in fixed_teacher_day_periods.items()
                if fixed_teacher_id == teacher_id
            )
            if not weekly_periods:
                continue
            target = weekly_periods // max(1, len(instructional_day_ids))
            for day_id in instructional_day_ids:
                entries = by_teacher_day_periods.get((teacher_id, day_id), [])
                fixed_load = int(fixed_teacher_day_periods.get((teacher_id, day_id), 0))
                load = model.NewIntVar(0, weekly_periods, "teacher{}_day{}_load".format(teacher_id, day_id))
                model.Add(load == fixed_load + sum(var * duration for var, duration in entries))
                deviation = model.NewIntVar(0, weekly_periods, "teacher{}_day{}_balance".format(teacher_id, day_id))
                model.AddAbsEquality(deviation, load - target)
                objective_terms.append((deviation, 20))

        # Keep fallback availability as a last resort, not as an equal choice.
        return model, variables, variable_meta, objective_terms

    remaining_seconds = max(0.1, deadline - time.monotonic())
    strict_budget = max(0.1, remaining_seconds * 0.55)
    model, variables, variable_meta, objective_terms = build_cp_model(False)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = strict_budget
    solver.parameters.num_search_workers = max(1, min(8, __import__("os").cpu_count() or 1))
    solver.parameters.random_seed = 17
    solver.parameters.log_search_progress = False
    strict_status = solver.Solve(model)
    strict_nodes = int(solver.NumBranches())
    strict_stop_reason = solver.StatusName(strict_status).lower()
    solution_values = None
    solution_model = model
    solution_variables = variables
    solution_meta = variable_meta
    if strict_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solution_values = {key: int(solver.Value(var)) for key, var in variables.items()}
    else:
        remaining_seconds = max(0.1, deadline - time.monotonic())
        if remaining_seconds > 0.15:
            model, variables, variable_meta, objective_terms = build_cp_model(True)
            fallback_solver = cp_model.CpSolver()
            fallback_solver.parameters.max_time_in_seconds = remaining_seconds
            fallback_solver.parameters.num_search_workers = max(1, min(8, __import__("os").cpu_count() or 1))
            fallback_solver.parameters.random_seed = 29
            fallback_solver.parameters.log_search_progress = False
            fallback_status = fallback_solver.Solve(model)
            fallback_nodes = int(fallback_solver.NumBranches())
            fallback_stop_reason = fallback_solver.StatusName(fallback_status).lower()
            if fallback_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                solver = fallback_solver
                solution_values = {key: int(solver.Value(var)) for key, var in variables.items()}
                solution_model = model
                solution_variables = variables
                solution_meta = variable_meta

    nodes = strict_nodes + fallback_nodes
    optimisation_nodes = 0
    generated = solution_values is not None
    if generated:
        # The hard-constraint feasibility pass has succeeded. Use any remaining
        # time to optimise the same feasible model; never sacrifice feasibility.
        remaining_seconds = deadline - time.monotonic()
        optimisation_budget = min(5.0, max(0.0, remaining_seconds * 0.20))
        if optimisation_budget > 0.25:
            try:
                solution_model.Minimize(sum(var * cost for var, cost in objective_terms))
                for key, var in solution_variables.items():
                    solution_model.AddHint(var, solution_values.get(key, 0))
                optimiser = cp_model.CpSolver()
                optimiser.parameters.max_time_in_seconds = optimisation_budget
                optimiser.parameters.num_search_workers = max(1, min(8, __import__("os").cpu_count() or 1))
                optimiser.parameters.random_seed = 41
                optimiser.parameters.log_search_progress = False
                optimised_status = optimiser.Solve(solution_model)
                if optimised_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    solver = optimiser
                    solution_values = {key: int(solver.Value(var)) for key, var in solution_variables.items()}
                    optimisation_nodes = int(solver.NumBranches())
            except Exception:
                # A feasible solution already exists; optimisation is best-effort.
                pass
        for key, selected in solution_values.items():
            if not selected:
                continue
            task, candidate, room_id, period_ids = solution_meta[key]
            placements.append(dict(
                candidate,
                room_id=room_id,
                class_id=int(task["class_id"]),
                subject_id=int(task["subject_id"]),
                teacher_id=int(task["teacher_id"]),
                class_ids=list(task.get("class_ids", [task["class_id"]])),
                teacher_ids=list(task.get("teacher_ids", [task["teacher_id"]])),
                fixed=False,
            ))
        exhausted_reason = None
    else:
        status_text = (fallback_stop_reason or strict_stop_reason or "unknown").upper()
        if status_text == "INFEASIBLE":
            exhausted_reason = "infeasible"
        elif status_text == "UNKNOWN":
            exhausted_reason = "deadline"
        else:
            exhausted_reason = "solver_" + status_text.lower()
        # Keep the existing diagnostic shape, with candidate-domain sizes and
        # explicit counts of candidates excluded by normalized shared sessions.
        for task_index, task in enumerate(tasks):
            key = (int(task["class_id"]), int(task["subject_id"]), int(task["teacher_id"]))
            rejection_by_requirement.setdefault(key, {})
            blocked_candidate_counts[task_index] = sum(
                1 for candidate in candidate_lookup[task_index]
                for room_id in _rooms_for_task(task)
                if (task_index, int(candidate["day_id"]), int(candidate["period_id"]), room_id) in blocked_candidates
            )
        strict_nodes = int(strict_nodes)
        fallback_nodes = int(fallback_nodes)
        exhausted = True

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
        class_names = {int(row["id"]): str(row["name"]) for row in cur.execute(
            "SELECT id,name FROM classes WHERE school_id=?", (school_id,)
        ).fetchall()}
        subject_names = {int(row["id"]): str(row["name"]) for row in cur.execute(
            "SELECT id,name FROM subjects WHERE school_id=?", (school_id,)
        ).fetchall()}
        teacher_names = {int(row["id"]): str(row["name"]) for row in cur.execute(
            "SELECT id,name FROM teachers WHERE school_id=?", (school_id,)
        ).fetchall()}
        requirement_diagnostics = []
        for task_index, task in enumerate(tasks):
            key = (int(task["class_id"]), int(task["subject_id"]), int(task["teacher_id"]))
            counts = rejection_by_requirement.get(key, {})
            requirement_diagnostics.append({
                "class": class_names.get(key[0], "Class ID " + str(key[0])),
                "class_id": key[0],
                "subject": subject_names.get(key[1], "Subject ID " + str(key[1])),
                "subject_id": key[1],
                "teacher": teacher_names.get(key[2], "Teacher ID " + str(key[2])),
                "teacher_id": key[2],
                "lesson_occurrence": int(task["occurrence"]),
                "lesson_duration_periods": int(task["duration"]),
                "configured_subject_daily_limit": task.get("max_lessons_per_day"),
                "candidate_slots_before_conflicts": len(candidate_lookup[task_index]),
                "candidate_filter_rejections": candidate_filter_diagnostics.get(task_index, {}),
                "blocked_by_existing_shared_sessions": int(blocked_candidate_counts.get(task_index, 0)),
                "rejections": counts,
            })
        requirement_diagnostics.sort(
            key=lambda item: (item["candidate_slots_before_conflicts"], -sum(item["rejections"].values()))
        )
        diagnostic_lines = []
        for item in requirement_diagnostics[:5]:
            rejection_text = ", ".join(
                reason.replace("_", " ") + ": " + str(count)
                for reason, count in sorted(item["rejections"].items(), key=lambda pair: -pair[1])[:4]
            ) or "No direct clash was isolated before search stopped"
            diagnostic_lines.append(
                item["class"] + " (class ID " + str(item["class_id"]) + ") / " + item["subject"] + " / " + item["teacher"]
                + " (lesson " + str(item["lesson_occurrence"]) + "): "
                + str(item["candidate_slots_before_conflicts"]) + " candidate slots; "
                + ("subject daily cap " + str(item["configured_subject_daily_limit"]) + "/day; "
                   if item["configured_subject_daily_limit"] is not None else "")
                + rejection_text
                + (", blocked by existing shared sessions: " + str(item["blocked_by_existing_shared_sessions"])
                   if item["blocked_by_existing_shared_sessions"] else "")
            )
        stop_reason = exhausted_reason or strict_stop_reason or fallback_stop_reason or "all_candidates_exhausted"
        if stop_reason == "deadline":
            cause = "The CP-SAT solver reached the generation time limit before finding a complete feasible timetable."
            next_step = "Review the most constrained lessons below, then check teacher availability, class limits, room use and manual placements."
        elif stop_reason == "infeasible":
            cause = "The configured requirements cannot be placed without a valid slot: CP-SAT proved that no complete timetable satisfies the current hard constraints and available teaching slots."
            next_step = "Review the affected lesson domains and mandatory constraints. Preferences were not relaxed, and existing generated lessons were preserved."
        elif stop_reason == "node_limit":
            cause = "The solver reached its configured search-node limit before finding a complete arrangement."
            next_step = "Review the most constrained lessons below; if the inputs are valid, the search strategy may need further optimization."
        elif stop_reason == "strict_pass_budget":
            cause = "The strict search pass used its allocated time; the fallback pass did not complete a full solution."
            next_step = "Review fallback-only availability and the most constrained lessons below."
        else:
            cause = "The solver exhausted the available combinations without placing every required lesson."
            next_step = "Start with lessons showing zero candidate slots or the fewest candidate slots, then review the listed constraints."
        summary = {
            "status": "failed",
            "message": (
                "Timetable generation failed. " + cause + " " + next_step
                + " Most constrained lessons: " + (" | ".join(diagnostic_lines) if diagnostic_lines else "No lesson-level rejection was recorded.")
                + " Search: " + str(strict_nodes) + " strict nodes, " + str(fallback_nodes)
                + " fallback nodes, " + str(round(time.monotonic() - search_started_at, 3)) + " seconds."
            ),
            "diagnostic_details": diagnostic_lines,
            "failure_cause": cause,
            "recommended_action": next_step,
            "failure_code": stop_reason,
            "most_constrained_lessons": requirement_diagnostics[:12],
            "constraint_rejection_totals": rejection_counts,
            "candidate_slot_count_min": min((x["candidate_slots_before_conflicts"] for x in requirement_diagnostics), default=0),
            "candidate_slot_count_max": max((x["candidate_slots_before_conflicts"] for x in requirement_diagnostics), default=0),
            "diagnostic_note": "Rejection totals count repeated solver checks, not unique timetable cells. Counts are aggregated across occurrences sharing the same class/subject/teacher requirement. A timeout identifies the search limit reached, not proof that the timetable is mathematically impossible.",
            "required_lessons": total_required,
            "manual_lessons_kept": len(manual),
            "unscheduled_lessons": len(tasks),
            "search_nodes": int(strict_nodes + fallback_nodes),
            "optimisation_nodes": int(optimisation_nodes),
            "search_nodes_by_pass": {
                "strict": int(strict_nodes),
                "fallback": int(fallback_nodes),
            },
            "search_stop_reason_by_pass": {
                "strict": strict_stop_reason or ("completed" if strict_nodes else "not_started"),
                "fallback": fallback_stop_reason or ("completed" if fallback_nodes else "not_started"),
            },
            "search_elapsed_seconds": round(time.monotonic() - search_started_at, 3),
            "overall_deadline_seconds": GENERATION_TIME_LIMIT_SECONDS,
            "search_limit_per_pass": int(node_limit),
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
                                             defer_replacement: bool = False,
                                             deadline: float | None = None) -> dict:
    """Place normalized multi-class/team-teaching requirements using the shared engine.

    This deliberately writes to ds_timetable_sessions; legacy single-class rows
    remain untouched until the new generator is fully integrated and reconciled.
    """
    from app.timetable.session_engine import create_scheduled_session, find_session_conflicts

    deadline = deadline if deadline is not None else time.monotonic() + GENERATION_TIME_LIMIT_SECONDS
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
        _check_generation_deadline(deadline)
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
        _check_generation_deadline(deadline)
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
            _check_generation_deadline(deadline)
            day_id = int(day["id"])
            for index, period in enumerate(periods):
                _check_generation_deadline(deadline)
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
                    _check_generation_deadline(deadline)
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
                        "duration": task["duration"], "period_no": int(period["period_no"]),
                        "period_end_no": int(span[-1]["period_no"])})
        if not options:
            raise TimetableSetupError("No valid slot is available for normalized requirement '" + task["name"] + "'. Check constraints, teacher availability, rooms and period patterns.")
        options.sort(key=lambda option: (preference_penalty(task, option),
                                          0 if task["preferred_day_id"] == option["day_id"] else 1,
                                          option["period_no"], option["day_id"]))
        candidates.append(options)

    # Candidate construction above completes every database-backed lookup.
    # Release the read transaction before CP-SAT optimisation so this solver
    # does not hold Supabase table locks while exploring candidate placements.
    connection.commit()

    from collections import defaultdict
    from ortools.sat.python import cp_model

    planned = []
    nodes = 0
    model = cp_model.CpModel()
    variables = {}
    option_meta = {}
    by_class_period = defaultdict(list)
    by_teacher_period = defaultdict(list)
    by_learner_period = defaultdict(list)
    by_room_period = defaultdict(list)
    by_subject_day = defaultdict(list)
    by_class_day_periods = defaultdict(list)
    by_class_week = defaultdict(list)
    objective_terms = []
    day_order = {int(day["id"]): index for index, day in enumerate(days)}

    for task_index, task in enumerate(tasks):
        task_vars = []
        for option_index, option in enumerate(candidates[task_index]):
            day_id = int(option["day_id"])
            period_ids = [
                int(period["id"]) for period in periods
                if _overlap(str(period["start_time"]), str(period["end_time"]),
                            str(option["start"]), str(option["end"]))
            ]
            if not period_ids:
                continue
            var = model.NewBoolVar("advanced_t{}_o{}".format(task_index, option_index))
            variables[(task_index, option_index)] = var
            option_meta[(task_index, option_index)] = option
            task_vars.append(var)
            for class_id in task["classes"]:
                for period_id in period_ids:
                    by_class_period[(int(class_id), day_id, period_id)].append(var)
                by_class_week[int(class_id)].append(var)
                by_class_day_periods[(int(class_id), day_id)].append((var, int(option["duration"])))
                if task.get("subject_id") is not None:
                    by_subject_day[(int(class_id), int(task["subject_id"]), day_id)].append(var)
            for teacher_id in task["teachers"]:
                for period_id in period_ids:
                    by_teacher_period[(int(teacher_id), day_id, period_id)].append(var)
            for learner_id in task["learners"]:
                for period_id in period_ids:
                    by_learner_period[(int(learner_id), day_id, period_id)].append(var)
            if option["room_id"] is not None:
                for period_id in period_ids:
                    by_room_period[(int(option["room_id"]), day_id, period_id)].append(var)

            # Preferences and distribution are soft costs; all resource and
            # workload restrictions remain hard constraints.
            cost = int(preference_penalty(task, option)) * 100
            cost += 0 if task["preferred_day_id"] == day_id else 20
            cost += int(option["period_no"]) * 3
            cost += day_order.get(day_id, 0)
            objective_terms.append((var, cost))
        if not task_vars:
            model.AddBoolOr([])
        else:
            model.Add(sum(task_vars) == 1)

    for resource_buckets in (
        by_class_period, by_teacher_period, by_learner_period, by_room_period, by_subject_day
    ):
        for bucket_vars in resource_buckets.values():
            if len(bucket_vars) > 1:
                model.Add(sum(bucket_vars) <= 1)

    for class_id, class_vars in by_class_week.items():
        limit = class_limits.get(class_id)
        if limit and limit["max_lessons_per_week"] is not None:
            model.Add(sum(class_vars) <= int(limit["max_lessons_per_week"]))

    for (class_id, day_id), entries in by_class_day_periods.items():
        limit = class_limits.get(class_id)
        if limit and limit["max_periods_per_day"] is not None:
            model.Add(
                sum(var * duration for var, duration in entries)
                <= int(limit["max_periods_per_day"])
            )

    model.Minimize(sum(var * cost for var, cost in objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.1, deadline - time.monotonic())
    solver.parameters.num_search_workers = max(1, min(8, __import__("os").cpu_count() or 1))
    solver.parameters.random_seed = 53
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    nodes = int(solver.NumBranches())
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        status_name = solver.StatusName(status)
        if status == cp_model.INFEASIBLE:
            raise TimetableSetupError(
                "CP-SAT proved that the normalized combined/co-teaching requirements cannot all fit "
                "without violating class, teacher, learner, room or workload constraints."
            )
        if status == cp_model.UNKNOWN:
            raise TimetableSetupError(
                "CP-SAT reached the timetable generation time limit before finding a complete "
                "combined/co-teaching schedule. Existing generated sessions were preserved."
            )
        raise TimetableSetupError(
            "CP-SAT could not solve the normalized instructional requirements: " + status_name
        )

    for (task_index, option_index), var in variables.items():
        if solver.Value(var):
            planned.append({
                "task": tasks[task_index],
                "option": option_meta[(task_index, option_index)],
            })


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
                    if period_ids and task["teachers"]:
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
                        "period_no": int(selected[0]["period_no"]) if selected[0]["period_no"] is not None else None,
                        "period_end_no": int(selected[-1]["period_no"]) if selected[-1]["period_no"] is not None else None,
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

    from collections import defaultdict
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    variables = {}
    option_meta = {}
    by_class_slot = defaultdict(list)
    by_teacher_slot = defaultdict(list)
    by_learner_slot = defaultdict(list)
    by_room_slot = defaultdict(list)
    by_class_week = defaultdict(list)
    by_class_date_periods = defaultdict(list)
    objective_terms = []

    for task_index, task in enumerate(tasks):
        task_vars = []
        for option_index, option in enumerate(candidates[task_index]):
            date_key = str(option["date"])
            slot_ids = [int(slot["id"]) for slot in option.get("slots", [])]
            if not slot_ids:
                continue
            var = model.NewBoolVar("dated_t{}_o{}".format(task_index, option_index))
            variables[(task_index, option_index)] = var
            option_meta[(task_index, option_index)] = option
            task_vars.append(var)
            for class_id in task["classes"]:
                for slot_id in slot_ids:
                    by_class_slot[(int(class_id), date_key, slot_id)].append(var)
                by_class_week[(int(class_id), str(task["week"]))].append(var)
                by_class_date_periods[(int(class_id), date_key)].append((var, max(1, len(option.get("slots", [])))))
            for teacher_id in task["teachers"]:
                for slot_id in slot_ids:
                    by_teacher_slot[(int(teacher_id), date_key, slot_id)].append(var)
            for learner_id in task["learners"]:
                for slot_id in slot_ids:
                    by_learner_slot[(int(learner_id), date_key, slot_id)].append(var)
            if option["room_id"] is not None:
                for slot_id in slot_ids:
                    by_room_slot[(int(option["room_id"]), date_key, slot_id)].append(var)
            cost = int(option["period_no"] or 0) * 5
            cost += int(option_index)
            objective_terms.append((var, cost))
        if not task_vars:
            model.AddBoolOr([])
        else:
            model.Add(sum(task_vars) == 1)

    for buckets in (by_class_slot, by_teacher_slot, by_learner_slot, by_room_slot):
        for bucket_vars in buckets.values():
            if len(bucket_vars) > 1:
                model.Add(sum(bucket_vars) <= 1)

    for (class_id, week_key), class_vars in by_class_week.items():
        limit = limits.get(class_id)
        if limit and limit["max_lessons_per_week"] is not None:
            model.Add(sum(class_vars) <= int(limit["max_lessons_per_week"]))

    for (class_id, date_key), entries in by_class_date_periods.items():
        limit = limits.get(class_id)
        if limit and limit["max_periods_per_day"] is not None:
            model.Add(
                sum(var * duration for var, duration in entries)
                <= int(limit["max_periods_per_day"])
            )

    model.Minimize(sum(var * cost for var, cost in objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = GENERATION_TIME_LIMIT_SECONDS
    solver.parameters.num_search_workers = max(1, min(8, __import__("os").cpu_count() or 1))
    solver.parameters.random_seed = 67
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    nodes = int(solver.NumBranches())
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.INFEASIBLE:
            raise TimetableSetupError(
                "CP-SAT proved that the dated requirements cannot all fit without clashes "
                "in the selected calendar range."
            )
        if status == cp_model.UNKNOWN:
            raise TimetableSetupError(
                "CP-SAT reached the time limit before finding a complete dated schedule. "
                "No new sessions were saved."
            )
        raise TimetableSetupError(
            "CP-SAT could not solve the dated requirements: " + solver.StatusName(status)
        )

    planned = [
        {"task": tasks[task_index], "option": option_meta[(task_index, option_index)]}
        for (task_index, option_index), var in variables.items()
        if solver.Value(var)
    ]


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