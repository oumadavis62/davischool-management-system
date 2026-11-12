"""Tests for automatic timetable generation."""
import sqlite3
import unittest

from app.timetable.schema import ensure_timetable_schema
from app.timetable.setup import (
    TimetableSetupError,
    create_profile,
    save_day,
    save_period,
    save_room,
    save_class_requirement,
    save_class_limits,
)
from app.timetable.builder import place_lesson
from app.timetable.generator import generate_timetable, generate_advanced_instructional_sessions
from app.timetable.advanced_setup import create_scheduling_requirement, save_scheduling_pattern


class TimetableGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        ensure_timetable_schema(self.db)
        self.db.executescript("""
            CREATE TABLE teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT);
            CREATE TABLE classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, stream TEXT, initials TEXT);
            CREATE TABLE subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT);
            CREATE TABLE teacher_allocations (
                id INTEGER PRIMARY KEY, school_id INTEGER, teacher_id INTEGER,
                subject_id INTEGER, class_id INTEGER
            );
            CREATE TABLE students (
                id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER
            );
        """)
        self.db.execute("INSERT INTO teachers VALUES(10,1,'Teacher A')")
        self.db.execute("INSERT INTO classes VALUES(20,1,'Grade 7','Blue','G7')")
        self.db.execute("INSERT INTO subjects VALUES(30,1,'Mathematics')")
        self.db.execute("INSERT INTO teacher_allocations VALUES(1,1,10,30,20)")
        self.db.commit()
        self.profile_id = create_profile(self.db, 1, "2027 Term 1", "2027", "Term 1")
        save_day(self.db, 1, self.profile_id, "MON", "Monday", 1)
        save_day(self.db, 1, self.profile_id, "TUE", "Tuesday", 2)
        save_period(self.db, 1, self.profile_id, 1, "Period 1", "08:00", "08:40")
        save_period(self.db, 1, self.profile_id, 2, "Period 2", "08:40", "09:20")
        save_room(self.db, 1, "R1", "Classroom 1", "classroom", 40)
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 2, 1, 1, False)

    def tearDown(self):
        self.db.close()

    def test_teacher_has_a_rest_period_between_different_subjects_in_same_class(self):
        # Keep one instructional day and three teaching periods so the only
        # valid way to place two different subjects is to leave a period free.
        self.db.execute(
            "UPDATE ds_timetable_days SET is_instructional=0 WHERE day_code='TUE'"
        )
        save_period(self.db, 1, self.profile_id, 3, "Period 3", "09:20", "10:00")
        save_class_requirement(
            self.db, 1, self.profile_id, 20, 30, 10, 1, 1, 1, False
        )
        self.db.execute("INSERT INTO subjects VALUES(31,1,'Integrated Science')")
        self.db.execute("INSERT INTO teacher_allocations VALUES(2,1,10,31,20)")
        save_class_requirement(
            self.db, 1, self.profile_id, 20, 31, 10, 1, 1, 1, False
        )
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "completed")
        rows = self.db.execute(
            """SELECT l.subject_id,p.period_no
               FROM ds_timetable_lessons l
               JOIN ds_timetable_periods p ON p.id=l.period_id
               WHERE l.generation_run_id=? ORDER BY p.period_no""",
            (result["run_id"],),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(int(rows[0]["period_no"]) + 1, int(rows[1]["period_no"]))
        self.assertNotEqual(int(rows[0]["subject_id"]), int(rows[1]["subject_id"]))

    def test_manual_double_span_accepts_equivalent_time_formats(self):
        from app.timetable.generator import _period_span

        periods = [
            {"id": 9, "period_no": 1, "period_type": "lesson",
             "start_time": "08:20:00", "end_time": "09:00:00"},
            {"id": 10, "period_no": 2, "period_type": "lesson",
             "start_time": "09:00", "end_time": "09:40"},
        ]
        self.assertEqual(_period_span(periods, 0, 2), periods)

    def test_generator_fills_weekly_requirement_and_assigns_room(self):
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["generated_lessons"], 2)
        rows = self.db.execute(
            "SELECT day_id,room_id,generation_run_id FROM ds_timetable_lessons ORDER BY day_id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["room_id"] is not None for row in rows))
        self.assertTrue(all(row["generation_run_id"] == result["run_id"] for row in rows))

    def test_repeated_weekly_occurrences_use_symmetry_breaking(self):
        # Forty interchangeable occurrences across eight subjects must fill
        # forty distinct weekly slots without exploring factorial permutations.
        for code, name, order in (
            ("WED", "Wednesday", 3), ("THU", "Thursday", 4), ("FRI", "Friday", 5)
        ):
            save_day(self.db, 1, self.profile_id, code, name, order)
        periods = (
            ("09:20", "10:00"), ("10:00", "10:40"), ("10:40", "11:20"),
            ("11:20", "12:00"), ("12:00", "12:40"), ("12:40", "13:20"),
        )
        for number, (start, end) in enumerate(periods, start=3):
            save_period(self.db, 1, self.profile_id, number, f"Period {number}", start, end)

        save_class_requirement(
            self.db, 1, self.profile_id, 20, 30, 10, 5, 1, 1, False
        )
        for index in range(7):
            teacher_id = 11 + index
            subject_id = 31 + index
            self.db.execute(
                "INSERT INTO teachers VALUES(?,?,?)",
                (teacher_id, 1, f"Teacher {teacher_id}"),
            )
            self.db.execute(
                "INSERT INTO subjects VALUES(?,?,?)",
                (subject_id, 1, f"Subject {subject_id}"),
            )
            self.db.execute(
                "INSERT INTO teacher_allocations VALUES(?,?,?,?,?)",
                (index + 2, 1, teacher_id, subject_id, 20),
            )
            save_class_requirement(
                self.db, 1, self.profile_id, 20, subject_id, teacher_id, 5, 1, 1, False
            )
        save_class_limits(self.db, 1, self.profile_id, 20, 40, 8)

        result = generate_timetable(
            self.db, 1, self.profile_id, "admin@test", node_limit=500
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["generated_lessons"], 40)
        self.assertLessEqual(result["search_nodes"], 5000)
        rows = self.db.execute(
            """SELECT day_id,period_id FROM ds_timetable_lessons
               WHERE generation_run_id=?""",
            (result["run_id"],),
        ).fetchall()
        self.assertEqual(len(rows), 40)
        self.assertEqual(len({(row["day_id"], row["period_id"]) for row in rows}), 40)

    def test_specialist_room_is_not_forced_for_ordinary_lessons(self):
        self.db.execute(
            "UPDATE ds_timetable_rooms SET room_type='laboratory' WHERE school_id=1"
        )
        self.db.commit()
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "completed")
        rows = self.db.execute(
            "SELECT room_id FROM ds_timetable_lessons WHERE generation_run_id=?",
            (result["run_id"],),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["room_id"] is None for row in rows))

    def test_generator_honours_configured_double_lesson_start_period(self):
        from app.timetable.advanced_setup import save_requirement_session_pattern
        requirement_id = self.db.execute(
            """SELECT id FROM ds_timetable_class_requirements
               WHERE profile_id=? AND class_id=20 AND subject_id=30 AND teacher_id=10""",
            (self.profile_id,),
        ).fetchone()["id"]
        period_one = self.db.execute(
            "SELECT id FROM ds_timetable_periods WHERE profile_id=? AND period_no=1",
            (self.profile_id,),
        ).fetchone()["id"]
        save_requirement_session_pattern(
            self.db, 1, self.profile_id, requirement_id,
            [{"duration_periods": 2, "preferred_period_id": period_one}],
        )
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "completed")
        row = self.db.execute(
            """SELECT period_id,duration_periods FROM ds_timetable_lessons
               WHERE profile_id=? AND generation_run_id IS NOT NULL""",
            (self.profile_id,),
        ).fetchone()
        self.assertEqual((row["period_id"], row["duration_periods"]), (period_one, 2))
        self.assertEqual(result["generated_lessons"], 1)
        rows = self.db.execute(
            """SELECT duration_periods FROM ds_timetable_lessons
               WHERE profile_id=? AND generation_run_id=? ORDER BY id""",
            (self.profile_id, result["run_id"]),
        ).fetchall()
        self.assertEqual([int(item["duration_periods"]) for item in rows], [2])

    def test_shared_instructional_occurrence_replaces_matching_legacy_requirement(self):
        # The ordinary allocation requires one double lesson. A shared
        # instructional session of the same duration fulfils that requirement
        # instead of causing a duplicate legacy lesson to be generated.
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 1, 2, None, True)
        requirement_id = create_scheduling_requirement(
            self.db, 1, self.profile_id, "Shared Mathematics",
            class_ids=[20], teacher_ids=[10], subject_id=30,
            weekly_occurrences=1, weekly_periods=2,
        )
        save_scheduling_pattern(
            self.db, 1, self.profile_id, requirement_id,
            [{"duration_periods": 2}],
        )
        shared = generate_advanced_instructional_sessions(
            self.db, 1, self.profile_id, "admin@test"
        )
        self.assertEqual(shared["status"], "completed")
        ordinary = generate_timetable(
            self.db, 1, self.profile_id, "admin@test",
            normalized_run_id=shared["run_id"],
        )
        self.assertEqual(ordinary["status"], "completed")
        self.assertEqual(ordinary["generated_lessons"], 0)
        self.assertEqual(
            self.db.execute(
                """SELECT COUNT(*) FROM ds_timetable_sessions
                   WHERE school_id=1 AND profile_id=? AND schedule_layer='instructional'
                     AND generation_run_id=?""",
                (self.profile_id, shared["run_id"]),
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.execute(
                """SELECT COUNT(*) FROM ds_timetable_lessons
                   WHERE school_id=1 AND profile_id=? AND status='scheduled'""",
                (self.profile_id,),
            ).fetchone()[0],
            0,
        )

    def test_generator_respects_class_weekly_lesson_ceiling(self):
        save_class_limits(self.db, 1, self.profile_id, 20, 1, None)
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_lessons WHERE school_id=1 AND profile_id=?",
                (self.profile_id,),
            ).fetchone()[0], 0)

    def test_manual_placements_are_regenerated_under_weekly_ceiling(self):
        monday = self.db.execute("SELECT id FROM ds_timetable_days WHERE day_code='MON'").fetchone()[0]
        tuesday = self.db.execute("SELECT id FROM ds_timetable_days WHERE day_code='TUE'").fetchone()[0]
        first_period = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=1").fetchone()[0]
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, monday, first_period)
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, tuesday, first_period)
        save_class_limits(self.db, 1, self.profile_id, 20, 2, None)
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["generated_lessons"], 2)
        self.assertEqual(result["manual_lessons_replaced"], 2)
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_lessons WHERE school_id=1 AND profile_id=? AND generation_run_id IS NULL",
                (self.profile_id,),
            ).fetchone()[0], 0)

    def test_generator_counts_double_periods_toward_daily_class_ceiling(self):
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 1, 2, None, True)
        save_class_limits(self.db, 1, self.profile_id, 20, None, 1)
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_lessons WHERE school_id=1 AND profile_id=?",
                (self.profile_id,),
            ).fetchone()[0], 0)

    def test_manual_placement_is_replaced_and_pattern_is_fully_regenerated(self):
        from app.timetable.advanced_setup import save_requirement_session_pattern

        save_period(self.db, 1, self.profile_id, 3, "Period 3", "09:20", "10:00")
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 3, 1, 1, False)
        requirement_id = self.db.execute(
            """SELECT id FROM ds_timetable_class_requirements
               WHERE school_id=1 AND profile_id=? AND class_id=20 AND subject_id=30 AND teacher_id=10""",
            (self.profile_id,),
        ).fetchone()["id"]
        save_requirement_session_pattern(
            self.db, 1, self.profile_id, requirement_id,
            [{"duration_periods": 2}, {"duration_periods": 1}],
        )
        tuesday = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE day_code='TUE'"
        ).fetchone()["id"]
        last_period = self.db.execute(
            "SELECT id FROM ds_timetable_periods WHERE period_no=2"
        ).fetchone()["id"]
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, tuesday, last_period)
        old_manual_id = self.db.execute(
            "SELECT id FROM ds_timetable_lessons WHERE generation_run_id IS NULL"
        ).fetchone()["id"]
        self.db.execute(
            """UPDATE ds_timetable_lessons SET duration_periods=2
               WHERE school_id=1 AND profile_id=? AND class_id=20 AND subject_id=30
                 AND teacher_id=10 AND generation_run_id IS NULL""",
            (self.profile_id,),
        )
        self.db.commit()

        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["manual_lessons_kept"], 0)
        self.assertEqual(result["manual_lessons_replaced"], 1)
        self.assertEqual(result["generated_lessons"], 2)
        rows = self.db.execute(
            """SELECT duration_periods,generation_run_id FROM ds_timetable_lessons
               WHERE school_id=1 AND profile_id=? AND class_id=20 AND subject_id=30
               ORDER BY generation_run_id IS NOT NULL""",
            (self.profile_id,),
        ).fetchall()
        self.assertEqual(sorted(int(row["duration_periods"]) for row in rows), [1, 2])
        self.assertTrue(all(row["generation_run_id"] is not None for row in rows))
        self.assertIsNotNone(self.db.execute(
            "SELECT generation_run_id FROM ds_timetable_lessons WHERE id=?", (old_manual_id,)
        ).fetchone()["generation_run_id"])

    def test_manual_lessons_are_replaced_and_all_requirements_regenerated(self):
        day_id = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE day_code='MON'"
        ).fetchone()[0]
        period_id = self.db.execute(
            "SELECT id FROM ds_timetable_periods WHERE period_no=1"
        ).fetchone()[0]
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, day_id, period_id)
        old_manual_id = self.db.execute(
            "SELECT id FROM ds_timetable_lessons WHERE generation_run_id IS NULL"
        ).fetchone()[0]
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["manual_lessons_kept"], 0)
        self.assertEqual(result["manual_lessons_replaced"], 1)
        self.assertEqual(result["generated_lessons"], 2)
        counts = self.db.execute(
            """SELECT SUM(CASE WHEN generation_run_id IS NULL THEN 1 ELSE 0 END),
                      SUM(CASE WHEN generation_run_id IS NOT NULL THEN 1 ELSE 0 END)
               FROM ds_timetable_lessons WHERE school_id=1 AND profile_id=?""",
            (self.profile_id,),
        ).fetchone()
        self.assertEqual(tuple(counts), (0, 2))
        self.assertIsNotNone(self.db.execute(
            "SELECT generation_run_id FROM ds_timetable_lessons WHERE id=?", (old_manual_id,)
        ).fetchone()["generation_run_id"])

    def test_failed_generation_keeps_manual_draft_when_replacement_cannot_complete(self):
        day_id = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE day_code='MON'"
        ).fetchone()[0]
        period_id = self.db.execute(
            "SELECT id FROM ds_timetable_periods WHERE period_no=1"
        ).fetchone()[0]
        self.db.execute(
            """INSERT INTO ds_timetable_lessons
               (school_id,profile_id,class_id,subject_id,teacher_id,day_id,period_id,
                duration_periods,generation_run_id,status,created_by,created_at,updated_at)
               VALUES(1,?,?,?,?,?,?,1,NULL,'scheduled','admin@test','2026-01-01','2026-01-01')""",
            (self.profile_id,20,30,10,day_id,period_id),
        )
        self.db.commit()
        manual_id = self.db.execute(
            "SELECT id FROM ds_timetable_lessons WHERE generation_run_id IS NULL"
        ).fetchone()[0]
        for day in self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE school_id=1 AND profile_id=?",
            (self.profile_id,),
        ).fetchall():
            for period in self.db.execute(
                "SELECT id FROM ds_timetable_periods WHERE school_id=1 AND profile_id=?",
                (self.profile_id,),
            ).fetchall():
                self.db.execute(
                    """INSERT INTO ds_timetable_teacher_availability
                       (school_id,profile_id,teacher_id,day_id,period_id,availability,reason)
                       VALUES(1,?,?,?,?, 'unavailable','Unavailable for test')""",
                    (self.profile_id,10,day["id"],period["id"]),
                )
        self.db.commit()

        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(self.db.execute(
            "SELECT id FROM ds_timetable_lessons WHERE id=? AND generation_run_id IS NULL",
            (manual_id,),
        ).fetchone())

    def test_failed_generation_keeps_previous_automatic_schedule(self):
        first = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(first["status"], "completed")
        previous_ids = [
            row["id"] for row in self.db.execute(
                "SELECT id FROM ds_timetable_lessons WHERE generation_run_id=?",
                (first["run_id"],),
            ).fetchall()
        ]
        # Make every teacher period unavailable; the next run cannot place
        # any lesson and must not delete the last valid generated timetable.
        for day in self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE school_id=1 AND profile_id=?",
            (self.profile_id,),
        ).fetchall():
            for period in self.db.execute(
                "SELECT id FROM ds_timetable_periods WHERE school_id=1 AND profile_id=?",
                (self.profile_id,),
            ).fetchall():
                self.db.execute(
                    """INSERT INTO ds_timetable_teacher_availability
                       (school_id,profile_id,teacher_id,day_id,period_id,availability,reason)
                       VALUES(1,?,?,?,?, 'unavailable','Unavailable for test')""",
                    (self.profile_id,10,day["id"],period["id"]),
                )
        self.db.commit()
        failed = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(failed["status"], "failed")
        current_ids = [
            row["id"] for row in self.db.execute(
                "SELECT id FROM ds_timetable_lessons WHERE generation_run_id=?",
                (first["run_id"],),
            ).fetchall()
        ]
        self.assertEqual(current_ids, previous_ids)

    def test_every_current_allocation_requires_a_weekly_requirement(self):
        self.db.execute("INSERT INTO subjects VALUES(31,1,'English')")
        self.db.execute("INSERT INTO teacher_allocations VALUES(2,1,10,31,20)")
        self.db.commit()
        with self.assertRaises(TimetableSetupError):
            generate_timetable(self.db, 1, self.profile_id, "admin@test")

    def test_incompatible_teacher_constraints_return_explainable_failure(self):
        self.db.execute("INSERT INTO classes VALUES(21,1,'Grade 8','Green','G8')")
        self.db.execute("INSERT INTO subjects VALUES(31,1,'English')")
        self.db.execute("INSERT INTO teacher_allocations VALUES(2,1,10,31,21)")
        save_class_requirement(self.db, 1, self.profile_id, 21, 31, 10, 2, 1, 1, False)
        # Leave only one usable slot for two required lessons.
        self.db.execute(
            "DELETE FROM ds_timetable_periods WHERE school_id=1 AND profile_id=? AND period_no=2",
            (self.profile_id,),
        )
        self.db.execute(
            "DELETE FROM ds_timetable_days WHERE school_id=1 AND profile_id=? AND day_code='TUE'",
            (self.profile_id,),
        )
        self.db.commit()
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "failed")
        self.assertIn("without a valid slot", result["message"])
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_lessons WHERE school_id=1 AND profile_id=?",
                (self.profile_id,),
            ).fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()


class TimetableSchoolSnapshotIntegrationTests(unittest.TestCase):
    """Regression test using the four-class, five-day school timetable that timed out."""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        ensure_timetable_schema(self.db)
        self.db.executescript("""
            CREATE TABLE teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT);
            CREATE TABLE classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, stream TEXT, initials TEXT);
            CREATE TABLE subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT);
            CREATE TABLE teacher_allocations (
                id INTEGER PRIMARY KEY, school_id INTEGER, teacher_id INTEGER,
                subject_id INTEGER, class_id INTEGER
            );
            CREATE TABLE students (id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER);
        """)
        self.db.execute("INSERT INTO teachers VALUES(10,1,'Existing teacher')")
        self.db.execute("INSERT INTO classes VALUES(20,1,'Existing class','Blue','EC')")
        self.db.execute("INSERT INTO subjects VALUES(30,1,'Existing subject')")
        self.db.execute("INSERT INTO teacher_allocations VALUES(1,1,10,30,20)")
        self.db.commit()
        self.profile_id = create_profile(self.db, 1, "School snapshot regression", "2027", "Term 1")
        save_day(self.db, 1, self.profile_id, "MON", "Monday", 1)
        save_day(self.db, 1, self.profile_id, "TUE", "Tuesday", 2)
        for code, name, order in (("WED", "Wednesday", 3), ("THU", "Thursday", 4), ("FRI", "Friday", 5)):
            save_day(self.db, 1, self.profile_id, code, name, order)
        save_period(self.db, 1, self.profile_id, 1, "Period 1", "08:20", "09:00")
        save_period(self.db, 1, self.profile_id, 2, "Period 2", "09:00", "09:40")
        period_times = (
            (3, "09:50", "10:30"), (4, "10:30", "11:10"),
            (5, "11:30", "12:10"), (6, "12:10", "12:50"),
            (7, "14:00", "14:40"), (8, "14:40", "15:20"),
        )
        for number, start, end in period_times:
            save_period(self.db, 1, self.profile_id, number, f"Period {number}", start, end)
        self.days = {
            row["day_code"]: int(row["id"])
            for row in self.db.execute(
                "SELECT id,day_code FROM ds_timetable_days WHERE profile_id=?",
                (self.profile_id,),
            )
        }
        self.periods = {
            int(row["period_no"]): int(row["id"])
            for row in self.db.execute(
                "SELECT id,period_no FROM ds_timetable_periods WHERE profile_id=?",
                (self.profile_id,),
            )
        }

    def tearDown(self):
        self.db.close()

    def test_real_school_snapshot_regenerates_all_weekly_sessions(self):
        from app.timetable.advanced_setup import save_requirement_session_pattern

        class_map = {1: 101, 2: 102, 5: 105, 6: 106}
        subject_map = {value: 200 + value for value in (1, 2, 3, 4, 5, 6, 8, 9, 10)}
        teacher_map = {value: 300 + value for value in range(1, 11)}
        class_names = {1: "GRADE 9", 2: "GRADE 9", 5: "GRADE 8", 6: "GRADE 8"}
        for source_id, target_id in class_map.items():
            self.db.execute(
                "INSERT INTO classes VALUES(?,?,?,?,?)",
                (target_id, 1, class_names[source_id], "Blue" if source_id in (1, 5) else "Green"),
            )
        teacher_names = {
            1: "DAVIS OUMA", 2: "ALVIN OUMA", 3: "ANN NDILU", 4: "HELLEN AKEYO",
            5: "RAEL ODUNGA", 6: "EUNICE ORONDO", 7: "MAUREEN OTIATO",
            8: "ARNOLD MUGENI", 9: "LEVINA AUMA", 10: "MARIA NABWIRE",
        }
        for source_id, target_id in teacher_map.items():
            self.db.execute("INSERT INTO teachers VALUES(?,?,?)", (target_id, 1, teacher_names[source_id]))
        subject_names = {
            1: "MATHEMATICS", 2: "ENGLISH", 3: "KISWAHILI", 4: "INTEGRATED SCIENCE",
            5: "AGRICULTURE", 6: "CREATIVE ARTS & SPORTS",
            8: "CHRISTIAN RELIGIOUS EDUCATION", 9: "SOCIAL STUDIES",
            10: "PRE-TECHNICAL STUDIES",
        }
        for source_id, target_id in subject_map.items():
            self.db.execute("INSERT INTO subjects VALUES(?,?,?)", (target_id, 1, subject_names[source_id]))

        # Remove the tiny setUp fixture's allocation; this test replaces it
        # with the complete allocation matrix from the school snapshot.
        self.db.execute("DELETE FROM teacher_allocations WHERE school_id=1")
        # (class, subject, teacher, weekly occurrences, max lessons/day)
        requirements = [
            (1,1,6,5,None),(1,2,9,5,None),(1,3,4,4,1),(1,4,4,5,1),(1,5,5,4,1),
            (1,6,3,5,1),(1,8,3,4,1),(1,9,8,4,1),(1,10,8,4,1),
            (2,1,1,5,None),(2,2,8,5,None),(2,3,3,4,1),(2,4,4,2,None),(2,5,8,4,1),
            (2,6,1,5,1),(2,8,3,4,1),(2,9,10,4,1),(2,10,2,4,1),
            (5,1,6,5,None),(5,2,9,5,1),(5,3,3,4,None),(5,4,1,3,1),(5,5,9,4,1),
            (5,6,9,5,1),(5,8,7,4,1),(5,9,10,4,1),(5,10,7,4,None),
            (6,1,10,5,None),(6,2,8,5,None),(6,3,2,4,1),(6,4,4,2,1),(6,5,5,4,1),
            (6,6,10,5,1),(6,8,9,4,1),(6,9,2,4,1),(6,10,7,4,1),
        ]
        requirement_ids = {}
        allocation_id = 10
        for class_id, subject_id, teacher_id, weekly, daily_cap in requirements:
            mapped = (class_map[class_id], subject_map[subject_id], teacher_map[teacher_id])
            self.db.execute(
                "INSERT INTO teacher_allocations VALUES(?,?,?,?,?)",
                (allocation_id, 1, mapped[2], mapped[1], mapped[0]),
            )
            allocation_id += 1
            save_class_requirement(
                self.db, 1, self.profile_id, mapped[0], mapped[1], mapped[2],
                weekly, 1, daily_cap, False,
            )
            requirement_ids[(class_id, subject_id, teacher_id)] = int(
                self.db.execute(
                    """SELECT id FROM ds_timetable_class_requirements
                       WHERE school_id=1 AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=?""",
                    (self.profile_id, *mapped),
                ).fetchone()["id"]
            )

        for class_id in class_map.values():
            save_class_limits(self.db, 1, self.profile_id, class_id, 40, 8)

        # Reproduce the three saved double/single mixes, including preferred starts.
        save_requirement_session_pattern(
            self.db, 1, self.profile_id, requirement_ids[(5,4,1)],
            [{"duration_periods":2,"preferred_period_id":self.periods[3]},
             {"duration_periods":1}],
        )
        save_requirement_session_pattern(
            self.db, 1, self.profile_id, requirement_ids[(2,4,4)],
            [{"duration_periods":2}],
        )
        save_requirement_session_pattern(
            self.db, 1, self.profile_id, requirement_ids[(6,4,4)],
            [{"duration_periods":2,"preferred_period_id":self.periods[3]}],
        )

        # Keep the four manual placements from the failing production run.
        manual = [
            (1,1,6,"MON",3),(1,2,9,"MON",2),
            (5,1,6,"TUE",3),(5,3,3,"TUE",2),
        ]
        for class_id, subject_id, teacher_id, day_code, period_no in manual:
            self.db.execute(
                """INSERT INTO ds_timetable_lessons
                   (school_id,profile_id,class_id,subject_id,teacher_id,room_id,day_id,period_id,
                    duration_periods,generation_run_id,status,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,?,NULL,?,?,1,NULL,'scheduled','snapshot-test',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                (
                    1, self.profile_id, class_map[class_id], subject_map[subject_id],
                    teacher_map[teacher_id], self.days[day_code], self.periods[period_no],
                ),
            )

        # Mirror the production subject windows: unavailable and fallback-only periods.
        subject_rules = []
        for day in range(1, 6):
            subject_rules.append((1, day, 5, "fallback"))
            subject_rules.extend((1, day, period, "unavailable") for period in (6, 7))
            if day != 3:
                subject_rules.append((1, day, 8, "unavailable"))
            subject_rules.append((2, day, 7, "unavailable"))
            if day != 4:
                subject_rules.append((2, day, 8, "unavailable"))
            subject_rules.append((4, day, 7, "fallback"))
            subject_rules.append((4, day, 8, "unavailable"))
            subject_rules.extend((6, day, period, "unavailable") for period in (1, 2, 3))
            subject_rules.append((6, day, 5, "fallback"))
        for subject_id, day, period, availability in subject_rules:
            self.db.execute(
                """INSERT INTO ds_timetable_subject_availability
                   (school_id,profile_id,subject_id,day_id,period_id,availability)
                   VALUES(?,?,?,?,?,?)""",
                (1, self.profile_id, subject_map[subject_id], self.days[("MON","TUE","WED","THU","FRI")[day-1]],
                 self.periods[period], availability),
            )
        # The one production room is a specialist laboratory, not a generic classroom.
        self.db.execute("UPDATE ds_timetable_rooms SET room_type='laboratory' WHERE school_id=1")
        self.db.commit()

        result = generate_timetable(self.db, 1, self.profile_id, "snapshot-test")
        self.assertEqual(result["status"], "completed", result.get("message"))
        self.assertEqual(result["generated_lessons"], 149)
        self.assertEqual(result["generated_session_blocks"], 149)
        self.assertEqual(result["required_periods"], 152)
        self.assertEqual(result["allocated_periods"], 152)
        self.assertTrue(result["allocation_complete"])
        generated = self.db.execute(
            """SELECT class_id,subject_id,teacher_id,day_id,period_id,duration_periods
               FROM ds_timetable_lessons WHERE profile_id=? AND generation_run_id=?""",
            (self.profile_id, result["run_id"]),
        ).fetchall()
        self.assertEqual(len(generated), 149)
        self.assertEqual(sum(int(row["duration_periods"]) for row in generated), 152)
        # Every school-wide double/triple reserves its occupied periods,
        # even when the lessons belong to different classes.
        extended_slots = set()
        for row in generated:
            duration = int(row["duration_periods"] or 1)
            if duration <= 1:
                continue
            start_no = next(
                number for number, period_id in self.periods.items()
                if period_id == int(row["period_id"])
            )
            for period_no in range(start_no, start_no + duration):
                key = (int(row["day_id"]), period_no)
                self.assertNotIn(key, extended_slots)
                extended_slots.add(key)
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) total FROM ds_timetable_lessons WHERE profile_id=? AND generation_run_id IS NULL AND status='scheduled'",
                (self.profile_id,),
            ).fetchone()["total"],
            0,
        )
