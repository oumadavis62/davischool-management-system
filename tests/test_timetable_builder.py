"""Tests for manual timetable placement and clash detection."""
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
    save_teacher_availability,
)
from app.timetable.builder import place_lesson, move_lesson, delete_lesson


class TimetableBuilderTests(unittest.TestCase):
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
            [(1,1,10,30,20),(2,1,11,31,20),(3,1,10,31,21),(4,1,11,31,21)],
        )
        self.db.commit()
        self.profile_id = create_profile(self.db, 1, "2027 Term 1", "2027", "Term 1")
        save_day(self.db, 1, self.profile_id, "MON", "Monday", 1)
        save_day(self.db, 1, self.profile_id, "TUE", "Tuesday", 2)
        save_period(self.db, 1, self.profile_id, 1, "Period 1", "08:00", "08:40")
        save_period(self.db, 1, self.profile_id, 2, "Period 2", "08:40", "09:20")
        save_period(self.db, 1, self.profile_id, 3, "Period 3", "09:20", "10:00")
        save_period(self.db, 1, self.profile_id, 4, "Period 4", "10:20", "11:00")
        self.day_mon = self.db.execute("SELECT id FROM ds_timetable_days WHERE day_code='MON'").fetchone()[0]
        self.day_tue = self.db.execute("SELECT id FROM ds_timetable_days WHERE day_code='TUE'").fetchone()[0]
        self.p1 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=1").fetchone()[0]
        self.p2 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=2").fetchone()[0]
        self.p3 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=3").fetchone()[0]
        self.p4 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=4").fetchone()[0]
        save_room(self.db, 1, "R1", "Room 1", "classroom", 40)
        self.room_id = self.db.execute("SELECT id FROM ds_timetable_rooms WHERE room_code='R1'").fetchone()[0]
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 2, 2, 1, True)
        save_class_requirement(self.db, 1, self.profile_id, 20, 31, 11, 2, 1, 2, False)
        save_class_requirement(self.db, 1, self.profile_id, 21, 31, 10, 2, 1, 2, False)
        save_class_requirement(self.db, 1, self.profile_id, 21, 31, 11, 2, 1, 2, False)

    def tearDown(self):
        self.db.close()

    def test_place_lesson_records_change_history(self):
        lesson_id = place_lesson(
            self.db, 1, self.profile_id, 20, 30, 10, self.day_mon, self.p1, self.room_id, "admin@test"
        )
        row = self.db.execute(
            "SELECT duration_periods,room_id,status FROM ds_timetable_lessons WHERE id=?",
            (lesson_id,),
        ).fetchone()
        self.assertEqual(tuple(row), (2, self.room_id, "scheduled"))
        log = self.db.execute(
            "SELECT action FROM ds_timetable_change_log WHERE lesson_id=?",
            (lesson_id,),
        ).fetchone()
        self.assertEqual(log["action"], "LESSON_CREATE")

    def test_class_teacher_and_room_double_bookings_are_rejected(self):
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, self.day_mon, self.p1, self.room_id)
        with self.assertRaises(TimetableSetupError):
            place_lesson(self.db, 1, self.profile_id, 20, 31, 11, self.day_mon, self.p2)
        with self.assertRaises(TimetableSetupError):
            place_lesson(self.db, 1, self.profile_id, 21, 31, 11, self.day_mon, self.p1, self.room_id)

    def test_teacher_double_booking_across_classes_is_rejected(self):
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, self.day_mon, self.p1, self.room_id)
        with self.assertRaises(TimetableSetupError):
            place_lesson(self.db, 1, self.profile_id, 21, 31, 10, self.day_mon, self.p1)

    def test_unavailable_teacher_cannot_be_scheduled(self):
        save_teacher_availability(self.db, 1, self.profile_id, 10, self.day_mon, self.p1, "unavailable", "Meeting")
        with self.assertRaises(TimetableSetupError):
            place_lesson(self.db, 1, self.profile_id, 20, 30, 10, self.day_mon, self.p1, self.room_id)

    def test_double_lesson_must_be_consecutive_without_break(self):
        with self.assertRaises(TimetableSetupError):
            place_lesson(self.db, 1, self.profile_id, 20, 30, 10, self.day_mon, self.p3, self.room_id)

    def test_move_and_delete_are_audited(self):
        lesson_id = place_lesson(self.db, 1, self.profile_id, 20, 30, 10, self.day_mon, self.p1, self.room_id)
        move_lesson(self.db, 1, self.profile_id, lesson_id, self.day_tue, self.p1, "admin@test")
        moved = self.db.execute("SELECT day_id FROM ds_timetable_lessons WHERE id=?", (lesson_id,)).fetchone()
        self.assertEqual(moved["day_id"], self.day_tue)
        delete_lesson(self.db, 1, self.profile_id, lesson_id, "admin@test")
        self.assertIsNone(self.db.execute("SELECT id FROM ds_timetable_lessons WHERE id=?", (lesson_id,)).fetchone())
        actions = [r["action"] for r in self.db.execute("SELECT action FROM ds_timetable_change_log WHERE lesson_id=? ORDER BY id", (lesson_id,)).fetchall()]
        self.assertEqual(actions, ["LESSON_CREATE", "LESSON_MOVE", "LESSON_DELETE"])


if __name__ == "__main__":
    unittest.main()
