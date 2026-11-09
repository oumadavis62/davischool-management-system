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
            CREATE TABLE classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, stream TEXT);
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
        self.db.execute("INSERT INTO classes VALUES(20,1,'Grade 7','Blue')")
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

    def test_generator_rejects_fixed_lessons_above_class_weekly_ceiling(self):
        monday = self.db.execute("SELECT id FROM ds_timetable_days WHERE day_code='MON'").fetchone()[0]
        tuesday = self.db.execute("SELECT id FROM ds_timetable_days WHERE day_code='TUE'").fetchone()[0]
        first_period = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=1").fetchone()[0]
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, monday, first_period)
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, tuesday, first_period)
        save_class_limits(self.db, 1, self.profile_id, 20, 1, None)
        with self.assertRaisesRegex(TimetableSetupError, "weekly lesson ceiling"):
            generate_timetable(self.db, 1, self.profile_id, "admin@test")

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

    def test_manual_lessons_are_preserved_and_generator_fills_remainder(self):
        day_id = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE day_code='MON'"
        ).fetchone()[0]
        period_id = self.db.execute(
            "SELECT id FROM ds_timetable_periods WHERE period_no=1"
        ).fetchone()[0]
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, day_id, period_id)
        result = generate_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["manual_lessons_kept"], 1)
        self.assertEqual(result["generated_lessons"], 1)
        counts = self.db.execute(
            """SELECT SUM(CASE WHEN generation_run_id IS NULL THEN 1 ELSE 0 END),
                      SUM(CASE WHEN generation_run_id IS NOT NULL THEN 1 ELSE 0 END)
               FROM ds_timetable_lessons WHERE school_id=1 AND profile_id=?""",
            (self.profile_id,),
        ).fetchone()
        self.assertEqual(tuple(counts), (1, 1))

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
        self.db.execute("INSERT INTO classes VALUES(21,1,'Grade 8','Green')")
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
