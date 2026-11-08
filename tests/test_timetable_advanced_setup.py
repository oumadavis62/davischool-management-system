"""Tests for advanced timetable templates, weekend rotations and programmes."""
import sqlite3
import unittest

from app.timetable.schema import ensure_timetable_schema
from app.timetable.advanced_setup import (
    assign_day_template,
    create_learning_programme,
    create_rotation_cycle,
    create_schedule_template,
    save_rotation_week,
    resolve_calendar_occurrence,
    expand_calendar_occurrences,
    save_schedule_slot,
    save_requirement_session_pattern,
)
from app.timetable.setup import create_profile, save_day, TimetableSetupError


class AdvancedTimetableSetupTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        ensure_timetable_schema(self.db)
        self.profile_id = create_profile(
            self.db, 12, "2027 timetable", "2027", "Term 1",
            academic_start_date="2027-01-01", academic_end_date="2027-12-31",
        )
        for code, name, order in (
            ("SAT", "Saturday", 6), ("SUN", "Sunday", 7),
        ):
            save_day(self.db, 12, self.profile_id, code, name, order, False)

    def tearDown(self):
        self.db.close()

    def test_weekend_days_can_use_independent_templates_and_non_period_slots(self):
        saturday = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE profile_id=? AND day_code='SAT'",
            (self.profile_id,),
        ).fetchone()["id"]
        sunday = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE profile_id=? AND day_code='SUN'",
            (self.profile_id,),
        ).fetchone()["id"]
        sat_template = create_schedule_template(
            self.db, 12, self.profile_id, "Saturday remedial", "remedial"
        )
        sun_template = create_schedule_template(
            self.db, 12, self.profile_id, "Sunday remedial", "weekend"
        )
        slot_id = save_schedule_slot(
            self.db, 12, self.profile_id, sat_template, 1,
            "Morning remedial", "remedial", "08:00", "09:30",
        )
        self.assertGreater(slot_id, 0)
        assign_day_template(self.db, 12, self.profile_id, saturday, sat_template)
        assign_day_template(self.db, 12, self.profile_id, sunday, sun_template)
        rows = self.db.execute(
            "SELECT day_id,template_id FROM ds_timetable_day_templates WHERE profile_id=?",
            (self.profile_id,),
        ).fetchall()
        self.assertEqual(len(rows), 2)

    def test_overlapping_slots_are_rejected(self):
        template = create_schedule_template(self.db, 12, self.profile_id, "Weekday")
        save_schedule_slot(
            self.db, 12, self.profile_id, template, 1,
            "Period 1", "instructional", "08:00", "08:40", 1,
        )
        with self.assertRaises(TimetableSetupError):
            save_schedule_slot(
                self.db, 12, self.profile_id, template, 2,
                "Remedial", "remedial", "08:30", "09:00",
            )

    def test_three_week_department_rotation_and_weekend_programme(self):
        cycle = create_rotation_cycle(
            self.db, 12, self.profile_id, "Weekend departments", 3, "2027-01-02"
        )
        science = create_learning_programme(
            self.db, 12, self.profile_id, "Science Saturday remedial",
            programme_type="remedial", recurrence_type="rotation",
            rotation_cycle_id=cycle, department_code="SCI",
        )
        save_rotation_week(
            self.db, 12, self.profile_id, cycle, 1, "Science weekend", "SCI", science
        )
        save_rotation_week(
            self.db, 12, self.profile_id, cycle, 2, "Languages weekend", "LANG"
        )
        save_rotation_week(
            self.db, 12, self.profile_id, cycle, 3, "Humanities weekend", "HUM"
        )
        rows = self.db.execute(
            """SELECT week_number,department_code FROM ds_timetable_rotation_weeks
               WHERE cycle_id=? ORDER BY week_number""",
            (cycle,),
        ).fetchall()
        self.assertEqual(
            [(r["week_number"], r["department_code"]) for r in rows],
            [(1, "SCI"), (2, "LANG"), (3, "HUM")],
        )


    def test_weekly_pattern_must_exactly_match_allocated_periods(self):
        self.db.execute(
            """INSERT INTO ds_timetable_class_requirements
               (school_id,profile_id,class_id,subject_id,teacher_id,lessons_per_week)
               VALUES(12,?,?,101,201,5)""",
            (self.profile_id, 1),
        )
        requirement_id = self.db.execute(
            "SELECT id FROM ds_timetable_class_requirements WHERE profile_id=?",
            (self.profile_id,),
        ).fetchone()["id"]
        save_requirement_session_pattern(
            self.db, 12, self.profile_id, requirement_id,
            [
                {"duration_periods": 2, "session_label": "Double"},
                {"duration_periods": 1, "session_label": "Single 1"},
                {"duration_periods": 1, "session_label": "Single 2"},
                {"duration_periods": 1, "session_label": "Single 3"},
            ],
        )
        rows = self.db.execute(
            """SELECT duration_periods FROM ds_timetable_requirement_patterns
               WHERE requirement_id=? ORDER BY session_no""",
            (requirement_id,),
        ).fetchall()
        self.assertEqual([row["duration_periods"] for row in rows], [2, 1, 1, 1])
        with self.assertRaises(TimetableSetupError):
            save_requirement_session_pattern(
                self.db, 12, self.profile_id, requirement_id,
                [{"duration_periods": 2}, {"duration_periods": 2}],
            )
        preserved = self.db.execute(
            "SELECT COUNT(*) AS n FROM ds_timetable_requirement_patterns WHERE requirement_id=?",
            (requirement_id,),
        ).fetchone()["n"]
        self.assertEqual(preserved, 4)


    def test_calendar_occurrence_resolves_weekday_weekend_exception_and_template(self):
        from app.timetable.setup import save_day, save_calendar_exception
        from app.timetable.advanced_setup import create_schedule_template, assign_day_template

        save_day(self.db, 12, self.profile_id, "MON", "Monday", 1)
        save_day(self.db, 12, self.profile_id, "SAT", "Saturday", 6, instructional=False)
        monday = self.db.execute("SELECT id FROM ds_timetable_days WHERE profile_id=? AND day_code='MON'", (self.profile_id,)).fetchone()["id"]
        saturday = self.db.execute("SELECT id FROM ds_timetable_days WHERE profile_id=? AND day_code='SAT'", (self.profile_id,)).fetchone()["id"]
        template = create_schedule_template(self.db, 12, self.profile_id, "Saturday remedial", "weekend")
        assign_day_template(self.db, 12, self.profile_id, saturday, template)
        save_calendar_exception(
            self.db, 12, self.profile_id, "2027-03-06", "Saturday remedial",
            "special_instructional_day", instructional=True,
        )
        regular = resolve_calendar_occurrence(self.db, 12, self.profile_id, "2027-03-01")
        weekend = resolve_calendar_occurrence(self.db, 12, self.profile_id, "2027-03-06")
        self.assertEqual(regular["day_id"], monday)
        self.assertTrue(regular["is_instructional"])
        self.assertEqual(weekend["day_id"], saturday)
        self.assertTrue(weekend["is_instructional"])
        self.assertEqual(weekend["template_id"], template)
        self.assertEqual(weekend["exceptions"][0]["label"], "Saturday remedial")

    def test_calendar_occurrence_repeats_department_rotation_from_anchor(self):
        cycle = create_rotation_cycle(self.db, 12, self.profile_id, "Departments", 3, "2027-03-01")
        save_rotation_week(self.db, 12, self.profile_id, cycle, 1, "Science", "SCI")
        save_rotation_week(self.db, 12, self.profile_id, cycle, 2, "Languages", "LANG")
        save_rotation_week(self.db, 12, self.profile_id, cycle, 3, "Humanities", "HUM")
        week_one = resolve_calendar_occurrence(self.db, 12, self.profile_id, "2027-03-01")
        week_three = resolve_calendar_occurrence(self.db, 12, self.profile_id, "2027-03-15")
        week_four = resolve_calendar_occurrence(self.db, 12, self.profile_id, "2027-03-22")
        self.assertEqual(week_one["rotations"][0]["week"]["department_code"], "SCI")
        self.assertEqual(week_three["rotations"][0]["week"]["department_code"], "HUM")
        self.assertEqual(week_four["rotations"][0]["week_number"], 1)


    def test_calendar_expansion_includes_weekend_template_and_closure_when_requested(self):
        from app.timetable.setup import save_day, save_calendar_exception
        from app.timetable.advanced_setup import create_schedule_template, assign_day_template

        save_day(self.db, 12, self.profile_id, "MON", "Monday", 1)
        save_day(self.db, 12, self.profile_id, "SAT", "Saturday", 6, instructional=False)
        saturday = self.db.execute(
            "SELECT id FROM ds_timetable_days WHERE profile_id=? AND day_code='SAT'",
            (self.profile_id,),
        ).fetchone()["id"]
        weekend_template = create_schedule_template(
            self.db, 12, self.profile_id, "Saturday programme", "weekend"
        )
        assign_day_template(self.db, 12, self.profile_id, saturday, weekend_template)
        save_calendar_exception(
            self.db, 12, self.profile_id, "2027-03-02", "School closure",
            "holiday", instructional=False,
        )
        active = expand_calendar_occurrences(
            self.db, 12, self.profile_id, "2027-03-01", "2027-03-07"
        )
        all_days = expand_calendar_occurrences(
            self.db, 12, self.profile_id, "2027-03-01", "2027-03-07",
            include_closed=True,
        )
        self.assertNotIn("2027-03-02", [x["date"] for x in active])
        self.assertIn("2027-03-06", [x["date"] for x in active])
        self.assertEqual(len(all_days), 7)
        saturday_row = next(x for x in active if x["date"] == "2027-03-06")
        self.assertEqual(saturday_row["template_id"], weekend_template)

    def test_calendar_expansion_rejects_ranges_over_one_year(self):
        with self.assertRaises(TimetableSetupError):
            expand_calendar_occurrences(
                self.db, 12, self.profile_id, "2027-01-01", "2028-01-02"
            )

    def test_rotation_programme_requires_a_cycle(self):
        with self.assertRaises(TimetableSetupError):
            create_learning_programme(
                self.db, 12, self.profile_id, "Invalid rotation",
                recurrence_type="rotation",
            )


if __name__ == "__main__":
    unittest.main()
