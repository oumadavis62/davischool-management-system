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

    def test_advanced_sessions_are_snapshotted_and_cloned_into_revisions(self):
        cur = self.db.cursor()
        cur.execute("INSERT INTO ds_timetable_schedule_templates(school_id,profile_id,name,template_type) VALUES(1,?,'Saturday','remedial')", (self.profile_id,))
        template_id = cur.lastrowid
        cur.execute("INSERT INTO ds_timetable_schedule_slots(school_id,profile_id,template_id,slot_no,label,slot_type,start_time,end_time,duration_minutes) VALUES(1,?,?,1,'Remedial','remedial','09:00','10:00',60)", (self.profile_id,template_id))
        slot_id = cur.lastrowid
        cur.execute("INSERT INTO ds_timetable_day_templates(school_id,profile_id,day_id,template_id,cycle_week) VALUES(1,?,?,?,0)", (self.profile_id,self.mon,template_id))
        cur.execute("INSERT INTO ds_timetable_rotation_cycles(school_id,profile_id,name,cycle_length_weeks,anchor_date) VALUES(1,?,'Weekend Rotation',2,'2027-01-02')", (self.profile_id,))
        cycle_id = cur.lastrowid
        cur.execute("INSERT INTO ds_timetable_learning_programmes(school_id,profile_id,name,programme_type,schedule_layer,rotation_cycle_id) VALUES(1,?,'Science Weekend','remedial','additional_learning',?)", (self.profile_id,cycle_id))
        programme_id = cur.lastrowid
        cur.execute("INSERT INTO ds_timetable_rotation_weeks(school_id,profile_id,cycle_id,week_number,label,programme_id) VALUES(1,?,?,1,'Weekend 1',?)", (self.profile_id,cycle_id,programme_id))
        cur.execute("INSERT INTO ds_timetable_teaching_groups(school_id,profile_id,name,group_type,subject_id) VALUES(1,?,'Combined Grade 7','combined_class',30)", (self.profile_id,))
        group_id = cur.lastrowid
        cur.execute("INSERT INTO ds_timetable_teaching_group_classes(school_id,profile_id,teaching_group_id,class_id) VALUES(1,?,?,20)", (self.profile_id,group_id))
        cur.execute("INSERT INTO ds_timetable_requirement_patterns(school_id,profile_id,requirement_id,session_no,duration_periods,preferred_day_id,preferred_slot_id) VALUES(1,?,?,1,1,?,?)", (self.profile_id,cur.execute("SELECT id FROM ds_timetable_class_requirements WHERE profile_id=?", (self.profile_id,)).fetchone()[0],self.mon,slot_id))
        cur.execute("INSERT INTO ds_timetable_programme_sessions(school_id,profile_id,programme_id,subject_id,teaching_group_id,day_id,start_time,end_time,duration_minutes) VALUES(1,?,?,30,?,?,'09:00','10:00',60)", (self.profile_id,programme_id,group_id,self.mon))
        cur.execute("INSERT INTO ds_timetable_scheduling_requirements(school_id,profile_id,name,schedule_layer,session_type,subject_id,programme_id,teaching_group_id,weekly_occurrences) VALUES(1,?,'Weekend Science','additional_learning','lesson',30,?,?,1)", (self.profile_id,programme_id,group_id))
        req_id = cur.lastrowid
        cur.execute("INSERT INTO ds_timetable_scheduling_requirement_classes(school_id,profile_id,requirement_id,class_id) VALUES(1,?,?,20)", (self.profile_id,req_id))
        cur.execute("INSERT INTO ds_timetable_scheduling_requirement_teachers(school_id,profile_id,requirement_id,teacher_id) VALUES(1,?,?,10)", (self.profile_id,req_id))
        cur.execute("INSERT INTO ds_timetable_scheduling_patterns(school_id,profile_id,requirement_id,session_no,duration_minutes,preferred_day_id,preferred_slot_id) VALUES(1,?, ?,1,60,?,?)", (self.profile_id,req_id,self.mon,slot_id))
        cur.execute("INSERT INTO ds_timetable_sessions(school_id,profile_id,schedule_layer,session_type,subject_id,programme_id,teaching_group_id,day_id,session_date,period_id,start_time,end_time,created_at,updated_at) VALUES(1,?,'additional_learning','lesson',30,?,?,?,'2027-03-06',?,'09:00','10:00','now','now')", (self.profile_id,programme_id,group_id,self.mon,self.p1))
        session_id = cur.lastrowid
        cur.execute("INSERT INTO ds_timetable_session_classes(school_id,profile_id,session_id,class_id) VALUES(1,?,?,20)", (self.profile_id,session_id))
        cur.execute("INSERT INTO ds_timetable_session_teachers(school_id,profile_id,session_id,teacher_id) VALUES(1,?,?,10)", (self.profile_id,session_id))
        cur.execute("INSERT INTO ds_timetable_constraints(school_id,profile_id,name,day_id,period_id,created_at,updated_at) VALUES(1,?,'No Friday',?,?,'now','now')", (self.profile_id,self.tue,self.p2))
        self.db.commit()
        submit_for_approval(self.db,1,self.profile_id,'admin@test')
        published = publish_timetable(self.db,1,self.profile_id,'admin@test')
        snapshot = json.loads(self.db.execute("SELECT snapshot_json FROM ds_timetable_versions WHERE id=?", (published['version_id'],)).fetchone()[0])
        self.assertEqual(len(snapshot['sessions']),1)
        self.assertEqual(len(snapshot['rotation_cycles']),1)
        self.assertEqual(len(snapshot['scheduling_requirements']),1)
        revision_id = create_revision(self.db,1,self.profile_id,'admin@test')
        copied = self.db.execute("SELECT * FROM ds_timetable_sessions WHERE school_id=1 AND profile_id=?", (revision_id,)).fetchone()
        self.assertIsNotNone(copied)
        self.assertNotEqual(int(copied['id']),session_id)
        self.assertEqual(copied['session_date'],'2027-03-06')
        copied_group = self.db.execute("SELECT teaching_group_id FROM ds_timetable_sessions WHERE profile_id=?", (revision_id,)).fetchone()[0]
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM ds_timetable_teaching_group_classes WHERE profile_id=? AND teaching_group_id=?", (revision_id,copied_group)).fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM ds_timetable_session_teachers st JOIN ds_timetable_sessions s ON s.id=st.session_id WHERE s.profile_id=?", (revision_id,)).fetchone()[0],1)
        self.db.execute("UPDATE ds_timetable_sessions SET start_time='10:00',end_time='11:00' WHERE profile_id=?", (revision_id,))
        self.db.commit()
        submit_for_approval(self.db,1,revision_id,'admin@test')
        second = publish_timetable(self.db,1,revision_id,'admin@test')
        comparison = compare_timetable_versions(self.db,1,published['version_id'],second['version_id'])
        self.assertEqual(len(comparison['advanced_added']),1)
        self.assertEqual(len(comparison['advanced_removed']),1)

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
        revision_tue = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE profile_id=? AND day_code='TUE'", (revision_id,)
        ).fetchone()[0]
        revision_p2 = self.db.execute(
            "SELECT id FROM ds_timetable_periods WHERE profile_id=? AND period_no=2", (revision_id,)
        ).fetchone()[0]
        move_lesson(self.db, 1, revision_id, self.db.execute(
            "SELECT id FROM ds_timetable_lessons WHERE profile_id=?", (revision_id,)
        ).fetchone()[0], revision_tue, revision_p2, "admin@test")
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
