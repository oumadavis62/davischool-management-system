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

    def test_class_daily_period_limit_respects_double_duration(self):
        result = solve(
            [task(1, duration=2)],
            [[candidate(1, 1, "08:00", "09:20", duration=2)]],
            limits={1: {"max_lessons_per_week": None, "max_periods_per_day": 1}},
        )
        self.assertEqual(result["status"], "INFEASIBLE")


if __name__ == "__main__":
    unittest.main()
