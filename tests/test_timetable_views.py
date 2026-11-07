"""Tests for timetable class, teacher, room and school views."""
import sqlite3
import unittest

from app.timetable.schema import ensure_timetable_schema
from app.timetable.setup import create_profile, save_day, save_period, save_room, save_class_requirement
from app.timetable.builder import place_lesson
from app.timetable.views import get_timetable_view


class TimetableViewTests(unittest.TestCase):
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
        self.db.executemany("INSERT INTO teachers VALUES(?,?,?)", [(10,1,"Teacher A"),(11,1,"Teacher B")])
        self.db.executemany("INSERT INTO classes VALUES(?,?,?,?)", [(20,1,"Grade 7","Blue"),(21,1,"Grade 8","Green")])
        self.db.executemany("INSERT INTO subjects VALUES(?,?,?)", [(30,1,"Mathematics"),(31,1,"English")])
        self.db.executemany(
            "INSERT INTO teacher_allocations VALUES(?,?,?,?,?)",
            [(1,1,10,30,20),(2,1,11,31,21)],
        )
        self.db.commit()
        self.profile_id = create_profile(self.db, 1, "2027 Term 1", "2027", "Term 1")
        save_day(self.db, 1, self.profile_id, "MON", "Monday", 1)
        save_period(self.db, 1, self.profile_id, 1, "Period 1", "08:00", "08:40")
        save_period(self.db, 1, self.profile_id, 2, "Period 2", "08:40", "09:20")
        save_room(self.db, 1, "R1", "Classroom 1", "classroom", 40)
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 1, 1, 1, False)
        save_class_requirement(self.db, 1, self.profile_id, 21, 31, 11, 1, 1, 1, False)
        self.day_id = self.db.execute("SELECT id FROM ds_timetable_days").fetchone()[0]
        self.p1 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=1").fetchone()[0]
        self.p2 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=2").fetchone()[0]
        self.room_id = self.db.execute("SELECT id FROM ds_timetable_rooms WHERE room_code='R1'").fetchone()[0]
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, self.day_id, self.p1, self.room_id)
        place_lesson(self.db, 1, self.profile_id, 21, 31, 11, self.day_id, self.p2, self.room_id)

    def tearDown(self):
        self.db.close()

    def test_school_view_contains_all_lessons(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "school")
        self.assertEqual(len(result["lessons"]), 2)
        self.assertEqual(result["title"], "School-wide timetable")

    def test_class_view_filters_class_stream(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "class", 20)
        self.assertEqual(len(result["lessons"]), 1)
        self.assertEqual(result["lessons"][0]["class_name"], "Grade 7")
        self.assertEqual(result["lessons"][0]["stream"], "Blue")

    def test_teacher_view_filters_teacher(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "teacher", 11)
        self.assertEqual(len(result["lessons"]), 1)
        self.assertEqual(result["lessons"][0]["teacher_name"], "Teacher B")

    def test_room_view_filters_room(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "room", self.room_id)
        self.assertEqual(len(result["lessons"]), 2)
        self.assertIn("Classroom 1", result["title"])

    def test_views_reject_cross_school_targets(self):
        with self.assertRaises(Exception):
            get_timetable_view(self.db, 2, self.profile_id, "class", 20)
        with self.assertRaises(Exception):
            get_timetable_view(self.db, 1, self.profile_id, "teacher", 999)


if __name__ == "__main__":
    unittest.main()
