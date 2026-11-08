"""Integration tests for combined teaching and cross-layer conflicts."""
import sqlite3
import unittest

from app.timetable.schema import ensure_timetable_schema
from app.timetable.setup import create_profile, save_day, save_period, save_room, save_class_limits, TimetableSetupError
from app.timetable.advanced_setup import create_learning_programme, save_programme_session, save_activity_type, create_scheduling_requirement, save_scheduling_pattern, save_timetable_constraint, create_schedule_template, save_schedule_slot, assign_day_template, create_rotation_cycle, save_rotation_week
from app.timetable.session_engine import (
    create_scheduled_session,
    create_teaching_group,
    find_session_conflicts,
)
from app.timetable.generator import generate_advanced_instructional_sessions, generate_dated_advanced_sessions
from app.timetable.builder import place_advanced_requirement_session, place_dated_advanced_requirement_session


class TimetableSessionEngineTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        ensure_timetable_schema(self.db)
        self.db.execute("CREATE TABLE classes (id INTEGER PRIMARY KEY, school_id INTEGER NOT NULL, name TEXT)")
        self.db.execute("CREATE TABLE teachers (id INTEGER PRIMARY KEY, school_id INTEGER NOT NULL, name TEXT)")
        self.db.execute("CREATE TABLE subjects (id INTEGER PRIMARY KEY, school_id INTEGER NOT NULL, name TEXT)")
        self.db.executemany("INSERT INTO subjects(id,school_id,name) VALUES(?,?,?)", [(5,8,"Science"),(9,8,"Mathematics")])
        self.db.execute("CREATE TABLE students (id INTEGER PRIMARY KEY, school_id INTEGER NOT NULL, class_id INTEGER)")
        self.db.executemany(
            "INSERT INTO classes(id,school_id,name) VALUES(?,?,?)",
            [(1, 8, "Grade 7 Blue"), (2, 8, "Grade 7 Green"), (3, 8, "Grade 8 Blue")],
        )
        self.db.executemany(
            "INSERT INTO teachers(id,school_id,name) VALUES(?,?,?)",
            [(11, 8, "Teacher A"), (12, 8, "Teacher B"), (13, 9, "Other school")],
        )
        self.db.executemany(
            "INSERT INTO students(id,school_id,class_id) VALUES(?,?,?)",
            [(101, 8, 1), (102, 8, 1), (103, 8, 2), (201, 9, 1)],
        )
        self.profile_id = create_profile(self.db, 8, "2027", "2027", "Term 1")
        save_day(self.db, 8, self.profile_id, "MON", "Monday", 1)
        self.day_id = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE profile_id=?", (self.profile_id,)
        ).fetchone()["id"]
        save_period(self.db, 8, self.profile_id, 1, "Period 1", "08:00", "08:40")
        self.period_id = self.db.execute(
            "SELECT id FROM ds_timetable_periods WHERE profile_id=?", (self.profile_id,)
        ).fetchone()["id"]
        save_room(self.db, 8, "LAB1", "Science Lab", "laboratory", 2)
        self.room_id = self.db.execute(
            "SELECT id FROM ds_timetable_rooms WHERE school_id=8"
        ).fetchone()["id"]

    def tearDown(self):
        self.db.close()


    def test_dated_instructional_session_obeys_date_template_and_breaks(self):
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-03-01", "2027-12-31", self.profile_id),
        )
        template = create_schedule_template(
            self.db, 8, self.profile_id, "Monday teaching day", "instructional"
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 1, "Period 1",
            "instructional", "08:00", "08:40", 1,
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 2, "Morning break",
            "break", "08:40", "09:00",
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 3, "Period 2",
            "instructional", "09:00", "09:40", 2,
        )
        assign_day_template(self.db, 8, self.profile_id, self.day_id, template)
        valid = create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "08:40",
            class_ids=[1], teacher_ids=[11], day_id=self.day_id,
            session_date="2027-03-01",
        )
        self.assertGreater(valid, 0)
        with self.assertRaisesRegex(TimetableSetupError, "date's instructional template"):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:40", "09:00",
                class_ids=[2], teacher_ids=[12], day_id=self.day_id,
                session_date="2027-03-01",
            )
        with self.assertRaisesRegex(TimetableSetupError, "cannot span a break"):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:40",
                class_ids=[3], teacher_ids=[12], day_id=self.day_id,
                session_date="2027-03-01",
            )

    def test_dated_programme_session_must_match_active_rotation_week(self):
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-03-01", "2027-12-31", self.profile_id),
        )
        cycle = create_rotation_cycle(
            self.db, 8, self.profile_id, "Department rotation", 2, "2027-03-01"
        )
        science = create_learning_programme(
            self.db, 8, self.profile_id, "Science weekend",
            rotation_cycle_id=cycle, recurrence_type="rotation",
        )
        languages = create_learning_programme(
            self.db, 8, self.profile_id, "Languages weekend",
            rotation_cycle_id=cycle, recurrence_type="rotation",
        )
        save_rotation_week(self.db, 8, self.profile_id, cycle, 1, "Science week", "SCI", science)
        save_rotation_week(self.db, 8, self.profile_id, cycle, 2, "Languages week", "LANG", languages)
        template = create_schedule_template(
            self.db, 8, self.profile_id, "Monday remedial", "instructional"
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 1, "Remedial",
            "remedial", "08:00", "09:00",
        )
        assign_day_template(self.db, 8, self.profile_id, self.day_id, template)
        with self.assertRaisesRegex(TimetableSetupError, "not active in the selected rotation week"):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                schedule_layer="additional_learning", session_type="remedial",
                class_ids=[1], teacher_ids=[11], day_id=self.day_id,
                session_date="2027-03-01", programme_id=languages,
            )

    def test_dated_remedial_and_activity_sessions_must_use_their_own_slot_types(self):
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-03-01", "2027-12-31", self.profile_id),
        )
        template = create_schedule_template(
            self.db, 8, self.profile_id, "Monday mixed programme", "instructional"
        )
        save_schedule_slot(self.db, 8, self.profile_id, template, 1, "Lesson", "instructional", "08:00", "08:40", 1)
        save_schedule_slot(self.db, 8, self.profile_id, template, 2, "Break", "break", "08:40", "09:00")
        save_schedule_slot(self.db, 8, self.profile_id, template, 3, "Remedial", "remedial", "09:00", "09:40")
        save_schedule_slot(self.db, 8, self.profile_id, template, 4, "Assembly", "assembly", "09:40", "10:00")
        assign_day_template(self.db, 8, self.profile_id, self.day_id, template)
        remedial = create_scheduled_session(
            self.db, 8, self.profile_id, "09:00", "09:40",
            schedule_layer="additional_learning", session_type="remedial",
            class_ids=[1], teacher_ids=[11], day_id=self.day_id,
            session_date="2027-03-01",
        )
        activity = create_scheduled_session(
            self.db, 8, self.profile_id, "09:40", "10:00",
            schedule_layer="school_activity", session_type="assembly",
            teacher_ids=[12], day_id=self.day_id, session_date="2027-03-01",
        )
        self.assertGreater(remedial, 0)
        self.assertGreater(activity, 0)
        with self.assertRaisesRegex(TimetableSetupError, "remedial or study slots"):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "08:40",
                schedule_layer="additional_learning", session_type="remedial",
                class_ids=[2], teacher_ids=[12], day_id=self.day_id,
                session_date="2027-03-01",
            )
    def test_combined_classes_and_team_teaching_are_saved_once(self):
        group = create_teaching_group(
            self.db, 8, self.profile_id, "Grade 7 combined science", [1, 2],
            subject_id=5,
        )
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "08:40",
                teacher_ids=[11], room_id=self.room_id, day_id=self.day_id,
                period_id=self.period_id, teaching_group_id=group,
            )
        session = create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "08:40",
            class_ids=[1, 2], teacher_ids=[11, 12], learner_ids=[101, 102, 103],
            room_id=None, day_id=self.day_id, period_id=self.period_id,
            teaching_group_id=group, subject_id=5,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_session_classes WHERE session_id=?",
                (session,),
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_session_teachers WHERE session_id=?",
                (session,),
            ).fetchone()[0],
            2,
        )

    def test_extended_instructional_session_must_match_consecutive_period_span(self):
        second_period = save_period(
            self.db, 8, self.profile_id, 2, "Period 2", "08:40", "09:20"
        )
        session = create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "09:20",
            class_ids=[1], teacher_ids=[11], day_id=self.day_id,
            period_id=self.period_id, duration_periods=2,
        )
        self.assertGreater(session, 0)
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                class_ids=[2], teacher_ids=[12], day_id=self.day_id,
                period_id=self.period_id, duration_periods=2,
            )

    def test_teacher_period_constraint_blocks_manual_session(self):
        save_timetable_constraint(
            self.db, 8, self.profile_id, "Teacher A unavailable Monday P1",
            teacher_id=11, day_id=self.day_id, period_id=self.period_id,
            reason="Teacher has a departmental meeting.",
        )
        with self.assertRaisesRegex(TimetableSetupError, "departmental meeting"):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "08:40",
                class_ids=[1], teacher_ids=[11], day_id=self.day_id,
                period_id=self.period_id,
            )

    def test_subject_time_constraint_blocks_session_but_not_other_subject(self):
        save_timetable_constraint(
            self.db, 8, self.profile_id, "No Science in first period",
            subject_id=5, period_id=self.period_id,
            reason="Laboratory is closed for maintenance.",
        )
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "08:40",
                class_ids=[1], teacher_ids=[11], subject_id=5,
                day_id=self.day_id, period_id=self.period_id,
            )
        session = create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "08:40",
            class_ids=[2], teacher_ids=[12], subject_id=9,
            day_id=self.day_id, period_id=self.period_id,
        )
        self.assertGreater(session, 0)

    def test_advanced_generator_places_combined_class_and_team_once(self):
        group = create_teaching_group(
            self.db, 8, self.profile_id, "Combined Grade 7 Science", [1, 2],
            subject_id=5,
        )
        requirement = create_scheduling_requirement(
            self.db, 8, self.profile_id, "Shared Science",
            class_ids=[1, 2], teacher_ids=[11, 12], learner_ids=[101, 102, 103],
            subject_id=5, teaching_group_id=group,
            weekly_occurrences=1, weekly_periods=1, min_teacher_count=2,
        )
        save_scheduling_pattern(
            self.db, 8, self.profile_id, requirement,
            [{"duration_periods": 1, "preferred_day_id": self.day_id}],
        )
        result = generate_advanced_instructional_sessions(
            self.db, 8, self.profile_id, "admin@test"
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["generated_sessions"], 1)
        session_id = result["session_ids"][0]
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM ds_timetable_session_classes WHERE session_id=?",
                            (session_id,)).fetchone()[0], 2)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM ds_timetable_session_teachers WHERE session_id=?",
                            (session_id,)).fetchone()[0], 2)

    def test_manual_builder_places_normalized_requirement_session(self):
        group = create_teaching_group(
            self.db, 8, self.profile_id, "Manual combined group", [1, 2],
            subject_id=5,
        )
        requirement = create_scheduling_requirement(
            self.db, 8, self.profile_id, "Manual shared Science",
            class_ids=[1, 2], teacher_ids=[11, 12],
            subject_id=5, teaching_group_id=group,
            weekly_occurrences=1, weekly_periods=1, min_teacher_count=2,
        )
        save_scheduling_pattern(
            self.db, 8, self.profile_id, requirement,
            [{"duration_periods": 1}],
        )
        session_id = place_advanced_requirement_session(
            self.db, 8, self.profile_id, requirement, 1,
            self.day_id, self.period_id,
        )
        self.assertGreater(session_id, 0)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM ds_timetable_session_teachers WHERE session_id=?",
                            (session_id,)).fetchone()[0], 2)


    def test_manual_builder_places_requirement_on_resolved_calendar_date(self):
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-03-01", "2027-12-31", self.profile_id),
        )
        template = create_schedule_template(
            self.db, 8, self.profile_id, "Monday date template", "instructional"
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 1, "Period 1",
            "instructional", "08:00", "08:40", 1,
        )
        assign_day_template(self.db, 8, self.profile_id, self.day_id, template)
        requirement = create_scheduling_requirement(
            self.db, 8, self.profile_id, "Dated Science",
            class_ids=[1], teacher_ids=[11], subject_id=5,
            weekly_occurrences=1, weekly_periods=1,
        )
        save_scheduling_pattern(
            self.db, 8, self.profile_id, requirement,
            [{"duration_periods": 1}],
        )
        session_id = place_dated_advanced_requirement_session(
            self.db, 8, self.profile_id, requirement, 1,
            "2027-03-01", 1,
        )
        row = self.db.execute(
            "SELECT session_date,day_id,start_time,end_time FROM ds_timetable_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        self.assertEqual(row["session_date"], "2027-03-01")
        self.assertEqual(row["day_id"], self.day_id)
        self.assertEqual((row["start_time"], row["end_time"]), ("08:00", "08:40"))



    def test_dated_manual_builder_rejects_break_and_non_instructional_slots(self):
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-03-01", "2027-12-31", self.profile_id),
        )
        template = create_schedule_template(
            self.db, 8, self.profile_id, "Monday with break", "instructional"
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 1, "Period 1",
            "instructional", "08:00", "08:40", 1,
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 2, "Morning break",
            "break", "08:40", "09:00",
        )
        assign_day_template(self.db, 8, self.profile_id, self.day_id, template)
        requirement = create_scheduling_requirement(
            self.db, 8, self.profile_id, "Manual dated Mathematics",
            class_ids=[1], teacher_ids=[11], subject_id=9,
            weekly_occurrences=1, weekly_periods=1,
        )
        save_scheduling_pattern(
            self.db, 8, self.profile_id, requirement,
            [{"duration_periods": 1}],
        )
        with self.assertRaisesRegex(TimetableSetupError, "not have enough consecutive slots"):
            place_dated_advanced_requirement_session(
                self.db, 8, self.profile_id, requirement, 1,
                "2027-03-01", 2,
            )

    def test_date_range_generator_repeats_weekly_pattern_on_calendar_dates(self):
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-03-01", "2027-12-31", self.profile_id),
        )
        template = create_schedule_template(
            self.db, 8, self.profile_id, "Monday timetable", "instructional"
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 1, "Period 1",
            "instructional", "08:00", "08:40", 1,
        )
        assign_day_template(self.db, 8, self.profile_id, self.day_id, template)
        requirement = create_scheduling_requirement(
            self.db, 8, self.profile_id, "Weekly Science",
            class_ids=[1], teacher_ids=[11], subject_id=5,
            weekly_occurrences=1, weekly_periods=1,
        )
        save_scheduling_pattern(
            self.db, 8, self.profile_id, requirement,
            [{"duration_periods": 1}],
        )
        result = generate_dated_advanced_sessions(
            self.db, 8, self.profile_id, "2027-03-01", "2027-03-14"
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["generated_sessions"], 2)
        dates = [r["session_date"] for r in self.db.execute(
            "SELECT session_date FROM ds_timetable_sessions WHERE school_id=8 AND profile_id=? AND subject_id=5 AND session_date IS NOT NULL ORDER BY session_date",
            (self.profile_id,),
        ).fetchall()]
        self.assertEqual(dates, ["2027-03-01", "2027-03-08"])

    def test_dated_builder_respects_active_rotation_programme(self):
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-03-01", "2027-12-31", self.profile_id),
        )
        cycle = create_rotation_cycle(
            self.db, 8, self.profile_id, "Weekend department rotation", 2, "2027-03-01"
        )
        science = create_learning_programme(
            self.db, 8, self.profile_id, "Science remedial",
            programme_type="remedial", schedule_layer="additional_learning",
            recurrence_type="rotation", rotation_cycle_id=cycle,
        )
        languages = create_learning_programme(
            self.db, 8, self.profile_id, "Languages remedial",
            programme_type="remedial", schedule_layer="additional_learning",
            recurrence_type="rotation", rotation_cycle_id=cycle,
        )
        save_rotation_week(self.db, 8, self.profile_id, cycle, 1, "Science", "SCI", science)
        save_rotation_week(self.db, 8, self.profile_id, cycle, 2, "Languages", "LAN", languages)
        template = create_schedule_template(
            self.db, 8, self.profile_id, "Remedial day", "remedial"
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 1, "Morning remedial",
            "remedial", "07:00", "07:40",
        )
        assign_day_template(self.db, 8, self.profile_id, self.day_id, template)
        requirement = create_scheduling_requirement(
            self.db, 8, self.profile_id, "Science rotation session",
            class_ids=[1], teacher_ids=[11], programme_id=science,
            schedule_layer="additional_learning", session_type="remedial",
            weekly_occurrences=1, weekly_periods=1,
        )
        save_scheduling_pattern(
            self.db, 8, self.profile_id, requirement,
            [{"duration_periods": 1, "duration_minutes": 40}],
        )
        with self.assertRaisesRegex(TimetableSetupError, "not active in the selected rotation week"):
            place_dated_advanced_requirement_session(
                self.db, 8, self.profile_id, requirement, 1,
                "2027-03-08", 1,
            )

    def test_normalized_sessions_enforce_class_daily_period_ceiling(self):
        save_class_limits(self.db, 8, self.profile_id, 1, None, 1)
        create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "08:40",
            class_ids=[1], teacher_ids=[11], subject_id=5,
            day_id=self.day_id, period_id=self.period_id, duration_periods=1,
        )
        second_period = save_period(
            self.db, 8, self.profile_id, 2, "Period 2", "08:40", "09:20"
        )
        with self.assertRaisesRegex(TimetableSetupError, "maximum periods per day"):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:40", "09:20",
                class_ids=[1], teacher_ids=[11], subject_id=5,
                day_id=self.day_id, period_id=second_period, duration_periods=1,
            )

    def test_required_period_constraint_rejects_other_period(self):
        second = save_period(self.db, 8, self.profile_id, 2, "Period 2", "08:40", "09:20")
        save_timetable_constraint(
            self.db, 8, self.profile_id, "Science must be first period",
            constraint_type="require", subject_id=5, period_id=self.period_id,
            reason="Science practicals are scheduled first.",
        )
        with self.assertRaisesRegex(TimetableSetupError, "requires a different"):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:40", "09:20",
                class_ids=[1], teacher_ids=[11], subject_id=5,
                day_id=self.day_id, period_id=second,
            )

    def test_teacher_and_class_conflicts_are_detected_across_layers(self):
        create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "09:00",
            schedule_layer="additional_learning", session_type="remedial",
            class_ids=[1], teacher_ids=[11], day_id=self.day_id,
        )
        conflicts = find_session_conflicts(
            self.db, 8, self.profile_id, "08:30", "09:10",
            class_ids=[1], teacher_ids=[11], day_id=self.day_id,
        )
        self.assertEqual(len(conflicts), 1)
        self.assertIn("class:1", conflicts[0]["reasons"])
        self.assertIn("teacher:11", conflicts[0]["reasons"])

    def test_dated_cross_layer_conflicts_cover_classes_teachers_learners_and_rooms(self):
        self.db.execute(
            "UPDATE ds_timetable_profiles SET academic_start_date=?,academic_end_date=? WHERE id=?",
            ("2027-03-01", "2027-12-31", self.profile_id),
        )
        template = create_schedule_template(
            self.db, 8, self.profile_id, "Monday remedial day", "instructional"
        )
        save_schedule_slot(
            self.db, 8, self.profile_id, template, 1, "Remedial session",
            "remedial", "08:00", "09:00",
        )
        assign_day_template(self.db, 8, self.profile_id, self.day_id, template)
        create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "09:00",
            schedule_layer="additional_learning", session_type="remedial",
            class_ids=[1], teacher_ids=[11], learner_ids=[101], room_id=self.room_id,
            day_id=self.day_id, session_date="2027-03-01",
        )
        conflicts = find_session_conflicts(
            self.db, 8, self.profile_id, "08:30", "09:10",
            class_ids=[1], teacher_ids=[11], learner_ids=[101], room_id=self.room_id,
            day_id=self.day_id, session_date="2027-03-01",
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(
            set(conflicts[0]["reasons"]),
            {"class:1", "teacher:11", "learner:101", f"room:{self.room_id}"},
        )
        other_date = find_session_conflicts(
            self.db, 8, self.profile_id, "08:30", "09:10",
            class_ids=[1], teacher_ids=[11], learner_ids=[101], room_id=self.room_id,
            day_id=self.day_id, session_date="2027-03-08",
        )
        self.assertEqual(other_date, [])
    def test_room_capacity_and_school_tenant_boundaries_are_enforced(self):
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                schedule_layer="additional_learning", session_type="remedial",
                learner_ids=[101, 102, 103], room_id=self.room_id,
                day_id=self.day_id,
            )
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                class_ids=[1], teacher_ids=[13], day_id=self.day_id,
            )
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                learner_ids=[201], day_id=self.day_id,
            )


    def test_dedicated_room_rejects_other_class_but_accepts_assigned_class(self):
        from app.timetable.setup import save_room
        save_room(self.db, 8, "DED1", "Grade 7 room", "classroom", 40,
                  allocation_mode="dedicated", assigned_class_id=1)
        dedicated_id = self.db.execute(
            "SELECT id FROM ds_timetable_rooms WHERE room_code='DED1'"
        ).fetchone()["id"]
        with self.assertRaisesRegex(TimetableSetupError, "permanently assigned"):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                class_ids=[2], room_id=dedicated_id, day_id=self.day_id,
            )
        allowed = create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "09:00",
            class_ids=[1], room_id=dedicated_id, day_id=self.day_id,
        )
        self.assertGreater(allowed, 0)

    def test_room_capacity_counts_combined_class_enrolment(self):
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                class_ids=[1, 2], room_id=self.room_id, day_id=self.day_id,
            )


    def test_programme_enforces_team_size_and_room_type(self):
        programme = create_learning_programme(
            self.db, 8, self.profile_id, "Saturday science remedial",
            programme_type="remedial", schedule_layer="additional_learning",
        )
        save_programme_session(
            self.db, 8, self.profile_id, programme, "08:00", "09:00", 60,
            day_id=self.day_id, required_teacher_count=2, room_type="laboratory",
        )
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                schedule_layer="additional_learning", session_type="remedial",
                teacher_ids=[11], room_id=self.room_id, day_id=self.day_id,
                programme_id=programme,
            )
        session = create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "09:00",
            schedule_layer="additional_learning", session_type="remedial",
            teacher_ids=[11, 12], room_id=self.room_id, day_id=self.day_id,
            programme_id=programme,
        )
        self.assertGreater(session, 0)

    def test_activity_type_setup_is_school_scoped(self):
        activity_id = save_activity_type(
            self.db, 8, "ASSEMBLY", "Assembly",
            requires_teacher=True, requires_room=True, tracks_attendance=True,
        )
        self.assertGreater(activity_id, 0)
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                schedule_layer="school_activity", session_type="ASSEMBLY",
                day_id=self.day_id,
            )


    def test_generic_requirement_supports_combined_classes_team_and_exact_pattern(self):
        group = create_teaching_group(
            self.db, 8, self.profile_id, "Shared Grade 7 science", [1, 2],
            subject_id=5,
        )
        requirement = create_scheduling_requirement(
            self.db, 8, self.profile_id, "Shared science weekly allocation",
            teacher_ids=[11, 12], teaching_group_id=group, subject_id=5,
            weekly_occurrences=4, weekly_periods=5, min_teacher_count=2,
        )
        save_scheduling_pattern(
            self.db, 8, self.profile_id, requirement,
            [
                {"duration_periods": 2, "preferred_day_id": self.day_id, "session_label": "Double"},
                {"duration_periods": 1, "session_label": "Single 1"},
                {"duration_periods": 1, "session_label": "Single 2"},
                {"duration_periods": 1, "session_label": "Single 3"},
            ],
        )
        rows = self.db.execute(
            """SELECT duration_periods FROM ds_timetable_scheduling_patterns
               WHERE requirement_id=? ORDER BY session_no""",
            (requirement,),
        ).fetchall()
        self.assertEqual([row["duration_periods"] for row in rows], [2, 1, 1, 1])
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_scheduling_requirement_classes WHERE requirement_id=?",
                (requirement,),
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_scheduling_requirement_teachers WHERE requirement_id=?",
                (requirement,),
            ).fetchone()[0],
            2,
        )

        session = create_scheduled_session(
            self.db, 8, self.profile_id, "08:00", "09:20",
            class_ids=[], teacher_ids=[], day_id=self.day_id,
            duration_periods=2, scheduling_requirement_id=requirement,
            pattern_session_no=1,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_session_classes WHERE session_id=?",
                (session,),
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM ds_timetable_session_teachers WHERE session_id=?",
                (session,),
            ).fetchone()[0],
            2,
        )

    def test_generic_requirement_rejects_unbalanced_patterns_without_erasing_old_one(self):
        requirement = create_scheduling_requirement(
            self.db, 8, self.profile_id, "Grade 8 mathematics",
            class_ids=[3], teacher_ids=[11], subject_id=9,
            weekly_occurrences=2, weekly_periods=3,
        )
        save_scheduling_pattern(
            self.db, 8, self.profile_id, requirement,
            [{"duration_periods": 2}, {"duration_periods": 1}],
        )
        with self.assertRaises(TimetableSetupError):
            save_scheduling_pattern(
                self.db, 8, self.profile_id, requirement,
                [{"duration_periods": 2}, {"duration_periods": 2}],
            )
        count = self.db.execute(
            "SELECT COUNT(*) FROM ds_timetable_scheduling_patterns WHERE requirement_id=?",
            (requirement,),
        ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_activity_type_can_require_teacher_and_venue(self):
        self.db.execute(
            """INSERT INTO ds_timetable_activity_types
               (school_id,code,name,requires_teacher,requires_room)
               VALUES(8,'ASSEMBLY','Assembly',1,1)"""
        )
        with self.assertRaises(TimetableSetupError):
            create_scheduled_session(
                self.db, 8, self.profile_id, "08:00", "09:00",
                schedule_layer="school_activity", session_type="ASSEMBLY",
                day_id=self.day_id,
            )


if __name__ == "__main__":
    unittest.main()
