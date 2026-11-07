"""Tests for timetable approval, immutable publication versions and revisions."""
import json
import sqlite3
import unittest

from app.timetable.schema import ensure_timetable_schema
from app.timetable.setup import create_profile, save_day, save_period, save_room, save_class_requirement
from app.timetable.builder import place_lesson, move_lesson
from app.timetable.publishing import (
    validate_timetable_for_publication,
    submit_for_approval,
    publish_timetable,
    create_revision,
    list_profile_versions,
    compare_timetable_versions,
)


class TimetablePublishingTests(unittest.TestCase):
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
        save_class_requirement(self.db, 1, self.profile_id, 20, 30, 10, 1, 1, 1, False)
        self.mon = self.db.execute("SELECT id FROM ds_timetable_days WHERE day_code='MON'").fetchone()[0]
        self.tue = self.db.execute("SELECT id FROM ds_timetable_days WHERE day_code='TUE'").fetchone()[0]
        self.p1 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=1").fetchone()[0]
        self.p2 = self.db.execute("SELECT id FROM ds_timetable_periods WHERE period_no=2").fetchone()[0]
        self.lesson_id = place_lesson(self.db, 1, self.profile_id, 20, 30, 10, self.mon, self.p1)

    def tearDown(self):
        self.db.close()

    def test_publication_validation_requires_complete_weekly_schedule(self):
        result = validate_timetable_for_publication(self.db, 1, self.profile_id)
        self.assertTrue(result["ready"])
        self.assertEqual(result["scheduled_lessons"], 1)
        self.assertEqual(result["required_lessons"], 1)

    def test_incomplete_schedule_cannot_be_submitted(self):
        self.db.execute("DELETE FROM ds_timetable_lessons WHERE id=?", (self.lesson_id,))
        self.db.commit()
        result = validate_timetable_for_publication(self.db, 1, self.profile_id)
        self.assertFalse(result["ready"])
        self.assertTrue(any("not fully scheduled" in error for error in result["errors"]))
        with self.assertRaises(Exception):
            submit_for_approval(self.db, 1, self.profile_id, "admin@test")

    def test_submit_publish_and_create_immutable_version(self):
        submit_for_approval(self.db, 1, self.profile_id, "registrar@test")
        status = self.db.execute("SELECT status FROM ds_timetable_profiles WHERE id=?", (self.profile_id,)).fetchone()[0]
        self.assertEqual(status, "pending_approval")
        result = publish_timetable(self.db, 1, self.profile_id, "admin@test")
        self.assertEqual(result["version_no"], 1)
        profile = self.db.execute(
            "SELECT status,current_version_id,published_by FROM ds_timetable_profiles WHERE id=?",
            (self.profile_id,),
        ).fetchone()
        self.assertEqual(profile["status"], "published")
        self.assertEqual(profile["current_version_id"], result["version_id"])
        self.assertEqual(profile["published_by"], "admin@test")
        version = self.db.execute("SELECT snapshot_json FROM ds_timetable_versions WHERE id=?", (result["version_id"],)).fetchone()
        snapshot = json.loads(version["snapshot_json"])
        self.assertEqual(len(snapshot["lessons"]), 1)
        self.assertEqual(snapshot["profile"]["status"], "pending_approval")

    def test_revision_clones_published_schedule_and_version_comparison_detects_change(self):
        submit_for_approval(self.db, 1, self.profile_id, "admin@test")
        first = publish_timetable(self.db, 1, self.profile_id, "admin@test")
        revision_id = create_revision(self.db, 1, self.profile_id, "admin@test")
        revision = self.db.execute(
            "SELECT status,revision_no,revision_of_profile_id FROM ds_timetable_profiles WHERE id=?",
            (revision_id,),
        ).fetchone()
        self.assertEqual(tuple(revision), ("draft", 2, self.profile_id))
        copied = self.db.execute(
            "SELECT day_id,period_id,generation_run_id FROM ds_timetable_lessons WHERE profile_id=?",
            (revision_id,),
        ).fetchone()
        self.assertIsNone(copied["generation_run_id"])
        move_lesson(self.db, 1, revision_id, self.db.execute(
            "SELECT id FROM ds_timetable_lessons WHERE profile_id=?", (revision_id,)
        ).fetchone()[0], self.tue, self.p2, "admin@test")
        submit_for_approval(self.db, 1, revision_id, "admin@test")
        second = publish_timetable(self.db, 1, revision_id, "admin@test")
        old_status = self.db.execute("SELECT status FROM ds_timetable_profiles WHERE id=?", (self.profile_id,)).fetchone()[0]
        self.assertEqual(old_status, "archived")
        versions = list_profile_versions(self.db, 1, revision_id)
        self.assertEqual(len(versions), 2)
        comparison = compare_timetable_versions(self.db, 1, first["version_id"], second["version_id"])
        self.assertEqual(len(comparison["added"]), 1)
        self.assertEqual(len(comparison["removed"]), 1)
        self.assertEqual(comparison["unchanged"], 0)


if __name__ == "__main__":
    unittest.main()
