"""Regression tests for the CP-SAT timetable placement engine."""
import time
import unittest

from app.timetable.cp_sat_engine import solve_timetable


def candidate(day, period, start, end, duration=1, preferred=False, available=True):
    return {
        "day_id": day, "period_id": period, "period_no": period,
        "start_time": start, "end_time": end, "duration": duration,
        "preferred": preferred, "explicitly_available": available,
    }


def task(class_id, teacher_id=1, subject_id=10, duration=1):
    return {
        "class_id": class_id, "class_ids": [class_id],
        "teacher_id": teacher_id, "teacher_ids": [teacher_id],
        "subject_id": subject_id, "duration": duration,
        "occurrence": 1,
    }


def solve(tasks, domains, fixed=None, limits=None):
    lookup = {index: domain for index, domain in enumerate(domains)}
    return solve_timetable(
        tasks, lookup, lambda _task: [None], fixed or [], set(), limits or {},
        time.monotonic() + 5, workers=1,
    )


class CpSatTimetableTests(unittest.TestCase):
    def test_double_lesson_uses_one_contiguous_candidate(self):
        result = solve(
            [task(1, duration=2)],
            [[candidate(1, 2, "09:00", "10:20", duration=2)]],
        )
        self.assertIn(result["status"], ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(result["placements"][0]["duration"], 2)
        self.assertEqual(result["placements"][0]["period_no"], 2)

    def test_teacher_cannot_teach_two_classes_at_same_time(self):
        same = candidate(1, 1, "08:00", "08:40")
        later = candidate(1, 2, "08:40", "09:20")
        result = solve([task(1), task(2)], [[same], [same, later]])
        self.assertIn(result["status"], ("OPTIMAL", "FEASIBLE"))
        chosen = result["placements"]
        self.assertEqual(len(chosen), 2)
        chosen_intervals = [(p["day_id"], p["start_time"], p["end_time"]) for p in chosen]
        self.assertEqual(len(set(chosen_intervals)), 2)
        self.assertIn((1, "08:40", "09:20"), chosen_intervals)

    def test_linked_classes_are_both_reserved(self):
        linked = task(1)
        linked["class_ids"] = [1, 2]
        result = solve(
            [linked, task(2, teacher_id=2, subject_id=11)],
            [[candidate(1, 1, "08:00", "08:40")],
             [candidate(1, 1, "08:00", "08:40")]],
        )
        self.assertEqual(result["status"], "INFEASIBLE")

    def test_fallback_availability_is_used_only_after_strict_pass(self):
        result = solve(
            [task(1)],
            [[candidate(1, 1, "08:00", "08:40", available=False)]],
        )
        self.assertIn(result["status"], ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(result["strict_status"], "INFEASIBLE")
        self.assertEqual(result["fallback_status"], "OPTIMAL")
        self.assertIn(result["optimization_status"], ("OPTIMAL", "FEASIBLE"))

    def test_manual_placement_is_preserved_as_fixed_anchor(self):
        fixed = {
            "class_id": 1, "teacher_id": 1, "subject_id": 10,
            "day_id": 1, "period_id": 1, "period_no": 1,
            "start_time": "08:00", "end_time": "08:40",
            "duration": 1, "room_id": None,
        }
        result = solve(
            [task(1, subject_id=11)],
            [[candidate(1, 1, "08:00", "08:40"),
              candidate(1, 2, "08:40", "09:20")]],
            fixed=[fixed],
        )
        self.assertIn(result["status"], ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(result["placements"][0]["period_no"], 2)

    def test_shared_learner_cannot_be_scheduled_twice(self):
        first = task(1, teacher_id=1, subject_id=10)
        second = task(2, teacher_id=2, subject_id=11)
        first["learner_ids"] = [900]
        second["learner_ids"] = [900]
        slot = candidate(1, 1, "08:00", "08:40")
        result = solve([first, second], [[slot], [slot]])
        self.assertEqual(result["status"], "INFEASIBLE")

    def test_same_room_cannot_host_two_simultaneous_lessons(self):
        slot_a = dict(candidate(1, 1, "08:00", "08:40"), room_id=7)
        slot_b = dict(candidate(1, 1, "08:00", "08:40"), room_id=7)
        result = solve(
            [task(1, teacher_id=1), task(2, teacher_id=2, subject_id=11)],
            [[slot_a], [slot_b]],
        )
        self.assertEqual(result["status"], "INFEASIBLE")

    def test_candidate_specific_room_options_are_respected(self):
        first = dict(candidate(1, 1, "08:00", "08:40"), allowed_room_ids=[7])
        second = dict(candidate(1, 1, "08:00", "08:40"), allowed_room_ids=[8])
        result = solve(
            [task(1, teacher_id=1), task(2, teacher_id=2, subject_id=11)],
            [[first], [second]],
        )
        self.assertIn(result["status"], ("OPTIMAL", "FEASIBLE"))
        self.assertEqual({item["room_id"] for item in result["placements"]}, {7, 8})

    def test_school_scale_weekly_schedule_with_145_remaining_sessions(self):
        # Mirrors the live school's 4 active classes, 36 requirements,
        # 152 required periods, five days and eight teaching periods.
        requirements = [
            (1, 1, 6, 5, []), (1, 2, 9, 5, []), (1, 3, 4, 4, []),
            (1, 4, 4, 5, []), (1, 5, 5, 4, []), (1, 6, 3, 5, []),
            (1, 8, 3, 4, []), (1, 9, 8, 4, []), (1, 10, 8, 4, []),
            (2, 1, 1, 5, []), (2, 2, 8, 5, []), (2, 3, 3, 4, []),
            (2, 4, 4, 2, [2]), (2, 5, 8, 4, []), (2, 6, 1, 5, []),
            (2, 8, 3, 4, []), (2, 9, 10, 4, []), (2, 10, 2, 4, []),
            (5, 1, 6, 5, []), (5, 2, 9, 5, []), (5, 3, 3, 4, []),
            (5, 4, 1, 3, [2, 1]), (5, 5, 9, 4, []), (5, 6, 9, 5, []),
            (5, 8, 7, 4, []), (5, 9, 10, 4, []), (5, 10, 7, 4, []),
            (6, 1, 10, 5, []), (6, 2, 8, 5, []), (6, 3, 2, 4, []),
            (6, 4, 4, 2, [2]), (6, 5, 5, 4, []), (6, 6, 10, 5, []),
            (6, 8, 9, 4, []), (6, 9, 2, 4, []), (6, 10, 7, 4, []),
        ]
        periods = [
            ("08:20", "09:00"), ("09:00", "09:40"),
            ("09:50", "10:30"), ("10:30", "11:10"),
            ("11:30", "12:10"), ("12:10", "12:50"),
            ("14:00", "14:40"), ("14:40", "15:20"),
        ]
        fixed_specs = [
            (1, 2, 9, 1, 2), (1, 1, 6, 1, 3),
            (5, 3, 3, 2, 2), (5, 1, 6, 2, 3),
        ]
        fixed = []
        fixed_counts = {}
        for class_id, subject_id, teacher_id, day_id, period_no in fixed_specs:
            start, end = periods[period_no - 1]
            fixed.append({
                "class_id": class_id, "subject_id": subject_id,
                "teacher_id": teacher_id, "day_id": day_id,
                "period_id": period_no, "period_no": period_no,
                "start_time": start, "end_time": end,
                "duration": 1, "room_id": None,
            })
            fixed_counts[(class_id, subject_id)] = fixed_counts.get((class_id, subject_id), 0) + 1

        # These are the live profile's 43 subject-unavailable cells,
        # converted from its period IDs 9-16 to period numbers 1-8.
        unavailable = {
            (1,1,6),(1,1,7),(1,1,8),(1,2,6),(1,2,7),(1,2,8),
            (1,3,6),(1,3,7),(1,4,6),(1,4,7),(1,4,8),(1,5,6),(1,5,7),(1,5,8),
            (2,1,7),(2,1,8),(2,2,7),(2,2,8),(2,3,7),(2,3,8),(2,4,7),(2,5,7),(2,5,8),
            (4,1,8),(4,2,8),(4,3,8),(4,4,8),(4,5,8),
            (6,1,1),(6,1,2),(6,1,3),(6,2,1),(6,2,2),(6,2,3),
            (6,3,1),(6,3,2),(6,3,3),(6,4,1),(6,4,2),(6,4,3),
            (6,5,1),(6,5,2),(6,5,3),
        }

        solver_tasks = []
        candidate_lookup = {}
        for class_id, subject_id, teacher_id, weekly, pattern in requirements:
            durations = list(pattern) if pattern else [1] * weekly
            for _ in range(fixed_counts.get((class_id, subject_id), 0)):
                durations.remove(1)
            for duration in durations:
                task_index = len(solver_tasks)
                solver_tasks.append({
                    "class_id": class_id, "class_ids": [class_id],
                    "teacher_id": teacher_id, "teacher_ids": [teacher_id],
                    "subject_id": subject_id, "duration": duration,
                    "max_lessons_per_day": 1,
                    "occurrence": task_index + 1,
                })
                domain = []
                starts = [3] if (
                    duration == 2 and
                    ((class_id == 5 and subject_id == 4) or (class_id == 6 and subject_id == 4))
                ) else ([1, 3, 5, 7] if duration == 2 else list(range(1, 9)))
                for day in range(1, 6):
                    for period_no in starts:
                        end_period = period_no + duration - 1
                        if any((subject_id, day, occupied) in unavailable
                               for occupied in range(period_no, end_period + 1)):
                            continue
                        start_time = periods[period_no - 1][0]
                        end_time = periods[end_period - 1][1]
                        domain.append({
                            "day_id": day, "period_id": period_no,
                            "period_no": period_no, "start_time": start_time,
                            "end_time": end_time, "duration": duration,
                            "preferred": duration == 2 and period_no == 3,
                            "explicitly_available": True,
                        })
                candidate_lookup[task_index] = domain

        result = solve_timetable(
            solver_tasks, candidate_lookup, lambda _task: [None],
            fixed, set(),
            {class_id: {"max_lessons_per_week": 40, "max_periods_per_day": 8}
             for class_id in (1, 2, 5, 6)},
            time.monotonic() + 25, workers=4,
        )
        self.assertIn(result["status"], ("OPTIMAL", "FEASIBLE"), result)
        self.assertEqual(len(result["placements"]), 145)
        combined = fixed + result["placements"]
        for class_id in (1, 2, 5, 6):
            self.assertEqual(
                sum(int(item["duration"]) for item in combined
                    if class_id in item.get("class_ids", [item["class_id"]])),
                {1: 40, 2: 37, 5: 38, 6: 37}[class_id],
            )
        for index, first in enumerate(combined):
            first_classes = set(first.get("class_ids", [first.get("class_id")])) - {None}
            first_teachers = set(first.get("teacher_ids", [first.get("teacher_id")])) - {None}
            for second in combined[index + 1:]:
                if first["day_id"] != second["day_id"]:
                    continue
                overlaps = (first["start_time"] < second["end_time"]
                            and first["end_time"] > second["start_time"])
                if not overlaps:
                    continue
                second_classes = set(second.get("class_ids", [second.get("class_id")])) - {None}
                second_teachers = set(second.get("teacher_ids", [second.get("teacher_id")])) - {None}
                self.assertFalse(first_classes & second_classes)
                self.assertFalse(first_teachers & second_teachers)

    def test_class_daily_period_limit_respects_double_duration(self):
        result = solve(
            [task(1, duration=2)],
            [[candidate(1, 1, "08:00", "09:20", duration=2)]],
            limits={1: {"max_lessons_per_week": None, "max_periods_per_day": 1}},
        )
        self.assertEqual(result["status"], "INFEASIBLE")


if __name__ == "__main__":
    unittest.main()
