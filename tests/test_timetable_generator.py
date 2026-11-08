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
from app.timetable.generator import generate_timetable


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
