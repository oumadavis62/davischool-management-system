"""Tests for authenticated published timetable portal target resolution."""
import sqlite3
import unittest

from app.timetable.portal_routes import get_portal_timetable_targets


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

    def test_unknown_role_and_missing_identity_return_no_targets(self):
        self.assertEqual(get_portal_timetable_targets(self.db, 1, "school_admin"), [])
        self.assertEqual(get_portal_timetable_targets(self.db, 1, "parent"), [])


if __name__ == "__main__":
    unittest.main()
