"""Tests for timetable class, teacher, room and school views."""
import sqlite3
import unittest

from app.timetable.schema import ensure_timetable_schema
from app.timetable.setup import create_profile, save_day, save_period, save_room, save_class_requirement, save_break
from app.timetable.builder import place_lesson
from app.timetable.views import get_timetable_view
from app.timetable.export_grid import build_export_grid


class TimetableViewTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        ensure_timetable_schema(self.db)
        self.db.executescript("""
            CREATE TABLE teachers (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, teacher_color TEXT, teacher_initials TEXT);
            CREATE TABLE students (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, class_id INTEGER);
            CREATE TABLE classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, stream TEXT, initials TEXT);
            CREATE TABLE subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, initial TEXT);
            CREATE TABLE teacher_allocations (
                id INTEGER PRIMARY KEY, school_id INTEGER, teacher_id INTEGER,
                subject_id INTEGER, class_id INTEGER
            );
        """)
        self.db.executemany("INSERT INTO teachers (id,school_id,name,teacher_color,teacher_initials) VALUES(?,?,?,?,?)", [(10,1,"Teacher A","#2563eb","TA"),(11,1,"Teacher B","#16a34a","TB")])
        self.db.executemany("INSERT INTO classes VALUES(?,?,?,?,?)", [(20,1,"Grade 7","Blue","G7"),(21,1,"Grade 8","Green","G8")])
        self.db.executemany("INSERT INTO subjects (id,school_id,name,initial) VALUES(?,?,?,?)", [(30,1,"Mathematics","M"),(31,1,"English","E")])
        self.db.executemany(
            "INSERT INTO teacher_allocations VALUES(?,?,?,?,?)",
            [(1,1,10,30,20),(2,1,11,31,21)],
        )
        self.db.commit()
        self.profile_id = create_profile(self.db, 1, "2027 Term 1", "2027", "Term 1")
        save_day(self.db, 1, self.profile_id, "MON", "Monday", 1)
        save_period(self.db, 1, self.profile_id, 1, "Period 1", "08:00", "08:40")
        save_period(self.db, 1, self.profile_id, 2, "Period 2", "08:40", "09:20")
        save_break(self.db, 1, self.profile_id, 1, "Morning Tea", "09:20", "09:40")
        save_room(self.db, 1, "R1", "Classroom 1", "classroom", 40)
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 1, 1, 1, False)
        save_class_requirement(self.db, 1, self.profile_id, 21, 31, 11, 1, 1, 1, False)
        self.day_id = self.db.execute("SELECT id FROM ds_timetable_days").fetchone()[0]
        self.p1 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=1").fetchone()[0]
        self.p2 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=2").fetchone()[0]
        self.room_id = self.db.execute("SELECT id FROM ds_timetable_rooms WHERE room_code='R1'").fetchone()[0]
        place_lesson(self.db, 1, self.profile_id, 20, 30, 10, self.day_id, self.p1, self.room_id)
        place_lesson(self.db, 1, self.profile_id, 21, 31, 11, self.day_id, self.p2, self.room_id)
        save_room(self.db, 1, "R2", "Classroom 2", "classroom", 35)
        self.room2_id = self.db.execute(
            "SELECT id FROM ds_timetable_rooms WHERE room_code='R2'"
        ).fetchone()[0]
        self.db.execute(
            "UPDATE ds_timetable_lessons SET room_id=? WHERE class_id=21",
            (self.room2_id,),
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_school_view_contains_all_lessons_in_published_profile(self):
        self.db.execute("UPDATE ds_timetable_profiles SET status='published' WHERE id=?", (self.profile_id,))
        self.db.commit()
        result = get_timetable_view(self.db, 1, self.profile_id, "school")
        self.assertEqual(len(result["lessons"]), 2)
        self.assertEqual(result["title"], "School-wide timetable")

    def test_all_timetable_view_data_includes_named_breaks_and_times(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "school")
        self.assertEqual(len(result["breaks"]), 1)
        self.assertEqual(result["breaks"][0]["label"], "Morning Tea")
        self.assertEqual(result["breaks"][0]["start_time"], "09:20")
        self.assertEqual(result["breaks"][0]["end_time"], "09:40")

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
        self.assertEqual(len(result["lessons"]), 1)
        self.assertEqual(result["lessons"][0]["class_id"], 20)
        self.assertIn("Classroom 1", result["title"])

    def test_second_room_view_excludes_lessons_in_other_rooms(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "room", self.room2_id)
        self.assertEqual(len(result["lessons"]), 1)
        self.assertEqual(result["lessons"][0]["class_id"], 21)
        self.assertIn("Classroom 2", result["title"])


    def test_weekend_sessions_are_grouped_by_configured_rotation_on_one_view_sheet(self):
        from app.timetable.advanced_setup import create_rotation_cycle, save_rotation_week
        save_day(self.db, 1, self.profile_id, "SAT", "Saturday", 6, False)
        saturday_id = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE day_code='SAT'"
        ).fetchone()[0]
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-01-01", "2027-12-31", self.profile_id),
        )
        cycle = create_rotation_cycle(
            self.db, 1, self.profile_id, "Weekend departments", 2, "2027-01-02"
        )
        save_rotation_week(self.db, 1, self.profile_id, cycle, 1, "Weekend 1", "SCIENCE")
        save_rotation_week(self.db, 1, self.profile_id, cycle, 2, "Weekend 2", "LANGUAGES")
        for session_date, label, teacher_id in [
            ("2027-01-02", "Science clinic", 10),
            ("2027-01-09", "Language clinic", 11),
        ]:
            cur = self.db.cursor()
            cur.execute(
                """INSERT INTO ds_timetable_sessions
                   (school_id,profile_id,schedule_layer,session_type,day_id,session_date,
                    start_time,end_time,duration_periods,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (1,self.profile_id,"additional_learning","remedial",saturday_id,
                 session_date,"09:00","10:00",0,"scheduled","2027-01-01","2027-01-01"),
            )
            sid = cur.lastrowid
            cur.execute(
                "INSERT INTO ds_timetable_session_teachers(school_id,profile_id,session_id,teacher_id) VALUES(?,?,?,?)",
                (1,self.profile_id,sid,teacher_id),
            )
            self.db.commit()
        result = get_timetable_view(self.db, 1, self.profile_id, "school")
        self.assertEqual(len(result["weekend_sessions"]), 2)
        self.assertEqual(set(result["weekend_groups"]), {"Weekend 1", "Weekend 2"})
        self.assertEqual(len(result["remedial_sessions"]), 2)

    def test_calendar_dated_instructional_sessions_are_exposed(self):
        cur = self.db.cursor()
        cur.execute(
            """INSERT INTO ds_timetable_sessions
               (school_id,profile_id,schedule_layer,session_type,day_id,session_date,
                subject_id,start_time,end_time,duration_periods,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (1,self.profile_id,"instructional","lesson",self.day_id,"2027-01-04",
             30,"08:00","08:40",1,"scheduled","2027-01-01","2027-01-01"),
        )
        session_id = cur.lastrowid
        cur.execute(
            "INSERT INTO ds_timetable_session_classes(school_id,profile_id,session_id,class_id) VALUES(?,?,?,?)",
            (1,self.profile_id,session_id,20),
        )
        cur.execute(
            "INSERT INTO ds_timetable_session_teachers(school_id,profile_id,session_id,teacher_id) VALUES(?,?,?,?)",
            (1,self.profile_id,session_id,10),
        )
        self.db.commit()
        result = get_timetable_view(self.db, 1, self.profile_id, "school")
        self.assertEqual(len(result["dated_instructional_sessions"]), 1)
        self.assertEqual(result["dated_instructional_sessions"][0]["session_date"], "2027-01-04")
        self.assertEqual(result["dated_instructional_sessions"][0]["class_names"], "Grade 7 Blue")


    def test_export_grid_preserves_double_lesson_colspan_and_class_rows(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "school")
        result["lessons"] = [dict(result["lessons"][0], duration_periods=2), *result["lessons"][1:]]
        layout = build_export_grid(result, "school")
        lesson_cell = next(cell for cell in layout["rows"][0]["cells"] if cell["kind"] == "lesson")
        self.assertEqual(lesson_cell["span"], 2)
        self.assertTrue(layout["show_class_column"])
        self.assertEqual(len(layout["rows"]), len(result["days"]) * 2)

    def test_export_resource_grid_embeds_class_stream_in_day_rows(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "teacher", 10)
        layout = build_export_grid(result, "teacher")
        self.assertTrue(layout["resource_view"])
        self.assertFalse(layout["show_class_column"])
        self.assertEqual(len(layout["rows"]), len(result["days"]))
        lesson_cell = next(cell for cell in layout["rows"][0]["cells"] if cell["kind"] == "lesson")
        self.assertEqual(lesson_cell["lessons"][0]["class_name"], "Grade 7")
        self.assertEqual(lesson_cell["lessons"][0]["stream"], "Blue")

    def test_room_export_grid_uses_resource_rows(self):
        result = get_timetable_view(self.db, 1, self.profile_id, "room", self.room_id)
        layout = build_export_grid(result, "room")
        self.assertTrue(layout["room_view"])
        self.assertEqual(len(layout["rows"]), len(result["days"]))
        self.assertEqual(layout["rows"][0]["cells"][0]["kind"], "lesson")

    def test_views_reject_cross_school_targets(self):
        with self.assertRaises(Exception):
            get_timetable_view(self.db, 2, self.profile_id, "class", 20)
        with self.assertRaises(Exception):
            get_timetable_view(self.db, 1, self.profile_id, "teacher", 999)


if __name__ == "__main__":
    unittest.main()
