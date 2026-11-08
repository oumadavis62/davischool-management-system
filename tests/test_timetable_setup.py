"""Unit tests for validated timetable setup operations."""
import sqlite3
import unittest

from app.timetable.schema import ensure_timetable_schema
from app.timetable.setup import (
    TimetableSetupError,
    create_profile,
    save_day,
    save_period,
    save_break,
    save_calendar_exception,
    save_room,
    save_teacher_availability,
    save_class_requirement,
    save_class_limits,
)


class TimetableSetupTests(unittest.TestCase):
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

    def tearDown(self):
        self.db.close()

    def test_profile_rejects_duplicate_year_and_term(self):
        with self.assertRaises(TimetableSetupError):
            create_profile(self.db, 1, "Duplicate", "2027", "Term 1")

    def test_academic_calendar_dates_are_saved_and_ordered(self):
        pid = create_profile(
            self.db, 1, "2027 Term 2", "2027", "Term 2",
            academic_start_date="2027-05-03",
            academic_end_date="2027-08-06",
        )
        row = self.db.execute(
            "SELECT academic_start_date,academic_end_date FROM ds_timetable_profiles WHERE id=?",
            (pid,),
        ).fetchone()
        self.assertEqual(tuple(row), ("2027-05-03", "2027-08-06"))
        with self.assertRaises(TimetableSetupError):
            create_profile(
                self.db, 1, "Bad dates", "2028", "Term 1",
                academic_start_date="2028-03-01",
                academic_end_date="2028-02-01",
            )

    def test_days_and_periods_are_saved_and_period_overlap_rejected(self):
        save_day(self.db, 1, self.profile_id, "MON", "Monday", 1)
        save_period(self.db, 1, self.profile_id, 1, "Period 1", "08:00", "08:40")
        with self.assertRaises(TimetableSetupError):
            save_period(self.db, 1, self.profile_id, 2, "Period 2", "08:30", "09:10")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM ds_timetable_periods"
        ).fetchone()[0], 1)

    def test_break_cannot_overlap_a_teaching_period(self):
        save_period(self.db, 1, self.profile_id, 1, "Period 1", "08:00", "08:40")
        with self.assertRaises(TimetableSetupError):
            save_break(self.db, 1, self.profile_id, 1, "Tea", "08:30", "08:50")

    def test_calendar_exceptions_must_fall_within_term_dates(self):
        pid = create_profile(
            self.db, 1, "2027 Term 2", "2027", "Term 2",
            academic_start_date="2027-05-03",
            academic_end_date="2027-08-06",
        )
        save_calendar_exception(
            self.db, 1, pid, "2027-06-01", "Public holiday", "holiday"
        )
        with self.assertRaises(TimetableSetupError):
            save_calendar_exception(
                self.db, 1, pid, "2027-09-01", "Outside term", "holiday"
            )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_calendar_exceptions WHERE profile_id=?",
                (pid,),
            ).fetchone()[0],
            1,
        )

    def test_room_is_school_scoped_and_upserted(self):
        save_room(self.db, 1, "LAB1", "Science Lab", "laboratory", 32)
        save_room(self.db, 1, "LAB1", "Main Science Lab", "laboratory", 36)
        row = self.db.execute(
            "SELECT name,capacity FROM ds_timetable_rooms WHERE school_id=1 AND room_code='LAB1'"
        ).fetchone()
        self.assertEqual(tuple(row), ("Main Science Lab", 36))

    def test_teacher_availability_validates_school_and_profile(self):
        save_day(self.db, 1, self.profile_id, "MON", "Monday", 1)
        save_period(self.db, 1, self.profile_id, 1, "Period 1", "08:00", "08:40")
        day_id = self.db.execute("SELECT id FROM ds_timetable_days").fetchone()[0]
        period_id = self.db.execute("SELECT id FROM ds_timetable_periods").fetchone()[0]
        save_teacher_availability(self.db, 1, self.profile_id, 10, day_id, period_id, "unavailable", "Staff meeting")
        with self.assertRaises(TimetableSetupError):
            save_teacher_availability(self.db, 2, self.profile_id, 10, day_id, period_id, "available")

    def test_class_workload_limits_are_saved_and_updated(self):
        save_class_limits(self.db, 1, self.profile_id, 20, 28, 7, "Grade 7 weekly ceiling")
        save_class_limits(self.db, 1, self.profile_id, 20, 25, 6, "Updated limits")
        row = self.db.execute(
            """SELECT max_lessons_per_week,max_periods_per_day,notes
               FROM ds_timetable_class_limits WHERE school_id=1 AND profile_id=? AND class_id=20""",
            (self.profile_id,),
        ).fetchone()
        self.assertEqual(tuple(row), (25, 6, "Updated limits"))
        with self.assertRaises(TimetableSetupError):
            save_class_limits(self.db, 1, self.profile_id, 999, 20, 6)
        with self.assertRaises(TimetableSetupError):
            save_class_limits(self.db, 1, self.profile_id, 20, 101, 6)

    def test_weekly_requirements_must_match_existing_allocation(self):
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 5, 1, 2, True)
        with self.assertRaises(TimetableSetupError):
            save_class_requirement(self.db, 1, self.profile_id, 20, 30, 99, 5)
        row = self.db.execute(
            "SELECT lessons_per_week,allow_double FROM ds_timetable_class_requirements"
        ).fetchone()
        self.assertEqual(tuple(row), (5, 1))


if __name__ == "__main__":
    unittest.main()
