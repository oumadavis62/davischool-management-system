"""CP-SAT timetable placement engine.

The database-facing generator prepares validated lesson tasks and candidate
slots. This module solves the resulting finite-domain scheduling model without
database access, using CP-SAT's Boolean placement variables and parallel search.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from ortools.sat.python import cp_model


def _overlap(a: dict, b: dict) -> bool:
    return (
        int(a["day_id"]) == int(b["day_id"])
        and str(a["start_time"]) < str(b["end_time"])
        and str(a["end_time"]) > str(b["start_time"])
    )


def _resource_ids(task: dict, field: str, singular: str) -> set[int]:
    return {int(value) for value in task.get(field, [task[singular]])}


def _build_and_solve(
    tasks: list[dict],
    candidate_lookup: dict[int, list[dict]],
    rooms_for_task,
    fixed: list[dict],
    blocked_candidates: set[tuple],
    class_limits: dict,
    time_limit: float,
    node_limit: int,
    workers: int,
    allow_fallback: bool,
) -> dict:
    model = cp_model.CpModel()
    variables: dict[int, list[tuple[Any, dict, int | None]]] = defaultdict(list)
    all_vars = []
    objective_terms = []
    fixed_by_class = defaultdict(list)
    fixed_by_teacher = defaultdict(list)
    fixed_by_room = defaultdict(list)
    fixed_week = defaultdict(int)
    fixed_day_periods = defaultdict(int)
    fixed_subject_day = set()

    for item in fixed:
        day = int(item["day_id"])
        for class_id in _resource_ids(item, "class_ids", "class_id"):
            fixed_by_class[(class_id, day)].append(item)
            fixed_week[class_id] += 1
            fixed_day_periods[(class_id, day)] += int(item.get("duration", 1))
            fixed_subject_day.add((class_id, int(item["subject_id"]), day))
        for teacher_id in _resource_ids(item, "teacher_ids", "teacher_id"):
            fixed_by_teacher[(teacher_id, day)].append(item)
        if item.get("room_id") is not None:
            fixed_by_room[(int(item["room_id"]), day)].append(item)

    for task_index, task in enumerate(tasks):
        class_ids = _resource_ids(task, "class_ids", "class_id")
        teacher_ids = _resource_ids(task, "teacher_ids", "teacher_id")
        task_vars = []
        for candidate_rank, candidate in enumerate(candidate_lookup[task_index]):
            if not allow_fallback and not candidate.get("explicitly_available"):
                continue
            day = int(candidate["day_id"])
            if any((class_id, int(task["subject_id"]), day) in fixed_subject_day for class_id in class_ids):
                continue
            if any(
                _overlap(candidate, placed)
                for class_id in class_ids for placed in fixed_by_class[(class_id, day)]
            ):
                continue
            if any(
                _overlap(candidate, placed)
                for teacher_id in teacher_ids for placed in fixed_by_teacher[(teacher_id, day)]
            ):
                continue
            room_ids = rooms_for_task(task)
            for room_id in room_ids:
                if (task_index, day, int(candidate["period_id"]), room_id) in blocked_candidates:
                    continue
                if room_id is not None and any(
                    _overlap(candidate, placed) for placed in fixed_by_room[(int(room_id), day)]
                ):
                    continue
                var = model.NewBoolVar(f"x_t{task_index}_c{candidate_rank}_r{room_id or 0}")
                placement = dict(candidate, room_id=room_id)
                variables[task_index].append((var, placement, room_id))
                task_vars.append(var)
                all_vars.append(var)
                # Preferences are soft; fallback-only cells carry a substantial
                # penalty, while preferred slots and earlier periods are favoured.
                penalty = 0
                if not candidate.get("preferred"):
                    penalty += 12
                if not candidate.get("explicitly_available"):
                    penalty += 500
                penalty += max(0, int(candidate.get("period_no", 1)) - 1)
                objective_terms.append(penalty * var)
        if not task_vars:
            return {
                "status": "INFEASIBLE",
                "placements": [],
                "branches": 0,
                "conflicts": 0,
                "wall_time": 0.0,
                "empty_domain_task": task_index,
            }
        model.AddExactlyOne(task_vars)

    # Pairwise interval conflicts. One task can share a slot across classes
    # only when those classes are explicitly linked in that same task.
    resource_buckets = defaultdict(list)
    for task_index, entries in variables.items():
        task = tasks[task_index]
        for var, placement, room_id in entries:
            day = int(placement["day_id"])
            for class_id in _resource_ids(task, "class_ids", "class_id"):
                resource_buckets[("class", class_id, day)].append((var, placement))
            for teacher_id in _resource_ids(task, "teacher_ids", "teacher_id"):
                resource_buckets[("teacher", teacher_id, day)].append((var, placement))
            if room_id is not None:
                resource_buckets[("room", int(room_id), day)].append((var, placement))

    for entries in resource_buckets.values():
        for i, (first_var, first) in enumerate(entries):
            for second_var, second in entries[i + 1:]:
                if first_var.Index() != second_var.Index() and _overlap(first, second):
                    model.Add(first_var + second_var <= 1)

    # Subject once per day and configured subject-specific daily occurrence cap.
    subject_day_vars = defaultdict(list)
    class_day_vars = defaultdict(list)
    class_week_vars = defaultdict(list)
    for task_index, entries in variables.items():
        task = tasks[task_index]
        for var, placement, _room in entries:
            day = int(placement["day_id"])
            for class_id in _resource_ids(task, "class_ids", "class_id"):
                subject_day_vars[(class_id, int(task["subject_id"]), day)].append(var)
                class_day_vars[(class_id, day)].append((var, int(placement["duration"])))
                class_week_vars[class_id].append(var)

    for key, vars_for_day in subject_day_vars.items():
        model.Add(sum(vars_for_day) <= 1)
    for task_index, task in enumerate(tasks):
        cap = task.get("max_lessons_per_day")
        if cap is None:
            continue
        class_id = int(task["class_id"])
        subject_id = int(task["subject_id"])
        teacher_id = int(task["teacher_id"])
        for day in {int(c["day_id"]) for c in candidate_lookup[task_index]}:
            vars_for_day = []
            for other_index, other_entries in variables.items():
                other = tasks[other_index]
                if (int(other["class_id"]) == class_id
                    and int(other["subject_id"]) == subject_id
                    and int(other["teacher_id"]) == teacher_id):
                    vars_for_day.extend(var for var, placement, _ in other_entries
                                        if int(placement["day_id"]) == day)
            if vars_for_day:
                model.Add(sum(vars_for_day) <= int(cap))

    for class_id, entries in class_week_vars.items():
        limit = class_limits.get(class_id)
        if limit and limit["max_lessons_per_week"] is not None:
            model.Add(sum(entries) + fixed_week[class_id] <= int(limit["max_lessons_per_week"]))
    for (class_id, day), entries in class_day_vars.items():
        limit = class_limits.get(class_id)
        if limit and limit["max_periods_per_day"] is not None:
            model.Add(
                sum(var * duration for var, duration in entries)
                + fixed_day_periods[(class_id, day)]
                <= int(limit["max_periods_per_day"])
            )

    if objective_terms:
        model.Minimize(sum(objective_terms))
    model.AddDecisionStrategy(
        all_vars,
        cp_model.CHOOSE_FIRST,
        cp_model.SELECT_MAX_VALUE,
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.05, float(time_limit))
    solver.parameters.max_number_of_conflicts = max(0, int(node_limit))
    solver.parameters.num_search_workers = max(1, int(workers))
    solver.parameters.random_seed = 17
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    chosen = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for task_index, entries in variables.items():
            selected = [placement for var, placement, _ in entries if solver.Value(var)]
            if len(selected) != 1:
                raise RuntimeError(f"CP-SAT returned {len(selected)} placements for task {task_index}")
            task = tasks[task_index]
            placement = dict(selected[0])
            placement.update({
                "class_id": int(task["class_id"]),
                "subject_id": int(task["subject_id"]),
                "teacher_id": int(task["teacher_id"]),
                "class_ids": sorted(_resource_ids(task, "class_ids", "class_id")),
                "teacher_ids": sorted(_resource_ids(task, "teacher_ids", "teacher_id")),
                "fixed": False,
            })
            chosen.append(placement)
    return {
        "status": status_name,
        "placements": chosen,
        "branches": int(solver.NumBranches()),
        "conflicts": int(solver.NumConflicts()),
        "wall_time": float(solver.WallTime()),
        "objective": float(solver.ObjectiveValue()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
    }


def solve_timetable(
    tasks: list[dict],
    candidate_lookup: dict[int, list[dict]],
    rooms_for_task,
    fixed: list[dict],
    blocked_candidates: set[tuple],
    class_limits: dict,
    deadline: float,
    node_limit: int = 10_000_000,
    workers: int = 8,
) -> dict:
    """Run strict-preference feasibility first, then a controlled fallback pass."""
    started = time.monotonic()
    remaining = max(0.1, deadline - started)
    strict_budget = max(0.1, remaining * 0.65)
    strict = _build_and_solve(
        tasks, candidate_lookup, rooms_for_task, fixed, blocked_candidates,
        class_limits, strict_budget, node_limit, workers, False,
    )
    fallback = None
    if strict["status"] not in ("OPTIMAL", "FEASIBLE") and time.monotonic() < deadline:
        fallback_budget = max(0.1, deadline - time.monotonic())
        fallback = _build_and_solve(
            tasks, candidate_lookup, rooms_for_task, fixed, blocked_candidates,
            class_limits, fallback_budget, node_limit, workers, True,
        )
    result = fallback if fallback and fallback["status"] in ("OPTIMAL", "FEASIBLE") else strict
    result["strict_status"] = strict["status"]
    result["strict_branches"] = strict["branches"]
    result["fallback_status"] = fallback["status"] if fallback else "NOT_RUN"
    result["fallback_branches"] = fallback["branches"] if fallback else 0
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result
