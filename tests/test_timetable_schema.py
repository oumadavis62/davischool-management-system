"""Tests for the clean timetable v2 schema foundation."""
import sqlite3
import unittest

from app.timetable.schema import ensure_timetable_schema


class TimetableSchemaTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")

    def tearDown(self):
        self.connection.close()

    def test_schema_creation_is_idempotent(self):
        ensure_timetable_schema(self.connection)
        ensure_timetable_schema(self.connection)
        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "ds_timetable_profiles",
            "ds_timetable_days",
            "ds_timetable_periods",
            "ds_timetable_breaks",
            "ds_timetable_rooms",
            "ds_timetable_calendar_exceptions",
            "ds_timetable_teacher_availability",
            "ds_timetable_class_requirements",
            "ds_timetable_lessons",
            "ds_timetable_versions",
            "ds_timetable_generation_runs",
            "ds_timetable_change_log",
        }
        expected.update({
            "ds_timetable_schedule_templates",
            "ds_timetable_schedule_slots",
            "ds_timetable_day_templates",
            "ds_timetable_rotation_cycles",
            "ds_timetable_rotation_weeks",
            "ds_timetable_learning_programmes",
            "ds_timetable_teaching_groups",
            "ds_timetable_teaching_group_classes",
            "ds_timetable_requirement_patterns",
            "ds_timetable_programme_sessions",
            "ds_timetable_sessions",
            "ds_timetable_session_classes",
            "ds_timetable_session_teachers",
            "ds_timetable_session_learners",
            "ds_timetable_activity_types",
        })
        self.assertTrue(expected.issubset(tables))

    def test_existing_profile_schema_gets_academic_date_columns_additively(self):
        self.connection.execute(
            """CREATE TABLE ds_timetable_profiles (
                id INTEGER PRIMARY KEY, school_id INTEGER NOT NULL, name TEXT NOT NULL,
                academic_year TEXT NOT NULL, term TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
                week_start TEXT, week_end TEXT, settings_json TEXT NOT NULL DEFAULT '{}',
                created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        ensure_timetable_schema(self.connection)
        columns = {
            row[1] for row in self.connection.execute(
                "PRAGMA table_info(ds_timetable_profiles)"
            ).fetchall()
        }
        self.assertIn("academic_start_date", columns)
        self.assertIn("academic_end_date", columns)
        lesson_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(ds_timetable_lessons)").fetchall()}
        self.assertIn("generation_run_id", lesson_columns)

    def test_profile_is_tenant_scoped_and_insertable(self):
        ensure_timetable_schema(self.connection)
        self.connection.execute(
            """INSERT INTO ds_timetable_profiles
               (school_id,name,academic_year,term,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (7, "Main timetable", "2027", "Term 1", "draft", "now", "now"),
        )
        row = self.connection.execute(
            "SELECT school_id,academic_year,term,status FROM ds_timetable_profiles"
        ).fetchone()
        self.assertEqual(row, (7, "2027", "Term 1", "draft"))

    def test_profile_day_and_period_uniqueness(self):
        ensure_timetable_schema(self.connection)
        self.connection.execute(
            """INSERT INTO ds_timetable_days
               (school_id,profile_id,day_code,day_name,day_order)
               VALUES (1,1,'MON','Monday',1)"""
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO ds_timetable_days
                   (school_id,profile_id,day_code,day_name,day_order)
                   VALUES (1,1,'MON','Monday duplicate',1)"""
            )
        self.connection.execute(
            """INSERT INTO ds_timetable_periods
               (school_id,profile_id,period_no,label,start_time,end_time)
               VALUES (1,1,1,'Period 1','08:00','08:40')"""
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO ds_timetable_periods
                   (school_id,profile_id,period_no,label,start_time,end_time)
                   VALUES (1,1,1,'Duplicate','08:40','09:20')"""
            )


if __name__ == "__main__":
    unittest.main()
