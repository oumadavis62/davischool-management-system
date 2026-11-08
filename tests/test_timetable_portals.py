"""Tests for authenticated published timetable portal target resolution."""
import sqlite3
import unittest

from app.timetable.portal_routes import get_portal_timetable_targets, build_portal_timetable_rows


class TimetablePortalTargetTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE teachers (id INTEGER, school_id INTEGER, name TEXT);
            CREATE TABLE classes (id INTEGER, school_id INTEGER, name TEXT, stream TEXT);
            CREATE TABLE students (id INTEGER, school_id INTEGER, name TEXT, class_id INTEGER);
            CREATE TABLE parent_student_links (
                school_id INTEGER, user_id INTEGER, student_id INTEGER
            );
            INSERT INTO teachers VALUES (10,1,'Teacher A'),(11,2,'Teacher B');
            INSERT INTO classes VALUES (20,1,'Grade 7','Blue'),(21,2,'Grade 8','Green');
            INSERT INTO students VALUES (30,1,'Learner A',20),(31,2,'Learner B',21),(32,1,'Learner C',20);
            INSERT INTO parent_student_links VALUES (1,100,30),(1,100,32),(2,100,31);
        """)

    def tearDown(self):
        self.db.close()

    def test_teacher_only_resolves_own_school_teacher(self):
        self.assertEqual(
            get_portal_timetable_targets(self.db, 1, "teacher", teacher_id=10),
            [("teacher", 10, "Teacher A")],
        )
        self.assertEqual(get_portal_timetable_targets(self.db, 1, "teacher", teacher_id=11), [])

    def test_student_resolves_only_own_enrolled_class(self):
        self.assertEqual(
            get_portal_timetable_targets(self.db, 1, "student", student_id=30),
            [("class", 20, "Learner A · Grade 7 Blue")],
        )
        self.assertEqual(get_portal_timetable_targets(self.db, 1, "student", student_id=31), [])

    def test_parent_sees_only_school_scoped_linked_children(self):
        targets = get_portal_timetable_targets(self.db, 1, "parent", user_id=100)
        self.assertEqual(targets, [
            ("class", 20, "Learner A · Grade 7 Blue"),
            ("class", 20, "Learner C · Grade 7 Blue"),
        ])

    def test_portal_rows_include_advanced_weekend_remedial_and_activity_sessions(self):
        view = {
            "lessons": [{"day_name": "Monday", "period_label": "Period 1", "start_time": "08:00", "end_time": "08:40", "subject_name": "Mathematics", "class_name": "Grade 7", "stream": "Blue", "teacher_name": "Teacher A", "room_name": "Room 1"}],
            "advanced_sessions": [
                {"session_date": "2027-03-06", "day_name": "Saturday", "start_time": "09:00", "end_time": "10:00", "subject_name": "Science", "programme_name": "Science Rotation", "session_type": "lesson", "class_names": "Grade 7 Blue, Grade 7 Green", "teacher_names": "Teacher A, Teacher B", "room_name": "Lab", "schedule_layer": "additional_learning"},
                {"session_date": "2027-03-08", "day_name": "Monday", "start_time": "15:00", "end_time": "16:00", "subject_name": None, "programme_name": "Clubs", "session_type": "activity", "class_names": "Grade 7 Blue", "teacher_names": "Teacher A", "room_name": "Field", "schedule_layer": "school_activity"}
            ]
        }
        rows = build_portal_timetable_rows(view)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["subject"], "Mathematics")
        self.assertEqual(rows[1]["date_day"], "2027-03-06 · Saturday")
        self.assertEqual(rows[1]["layer"], "Additional Learning")
        self.assertEqual(rows[1]["teachers"], "Teacher A, Teacher B")
        self.assertEqual(rows[2]["subject"], "Clubs")
        self.assertEqual(rows[2]["layer"], "School Activity")

    def test_unknown_role_and_missing_identity_return_no_targets(self):
        self.assertEqual(get_portal_timetable_targets(self.db, 1, "school_admin"), [])
        self.assertEqual(get_portal_timetable_targets(self.db, 1, "parent"), [])


if __name__ == "__main__":
    unittest.main()
