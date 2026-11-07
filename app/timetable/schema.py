"""Fresh, isolated schema for the DaviSchool timetable engine.

The timetable owns only ds_timetable_* tables. It references existing school,
class, subject and teacher IDs by value and validates those relationships in
the service layer; it never copies or modifies core school records.
"""
from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "001"


_TABLES = (
    """CREATE TABLE IF NOT EXISTS ds_timetable_profiles (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        academic_year TEXT NOT NULL,
        term TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        week_start TEXT,
        week_end TEXT,
        academic_start_date TEXT,
        academic_end_date TEXT,
        approved_by TEXT,
        approved_at TEXT,
        published_by TEXT,
        published_at TEXT,
        current_version_id INTEGER,
        revision_no INTEGER NOT NULL DEFAULT 1,
        revision_of_profile_id INTEGER,
        settings_json TEXT NOT NULL DEFAULT '{}',
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_days (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        day_code TEXT NOT NULL,
        day_name TEXT NOT NULL,
        day_order INTEGER NOT NULL,
        is_instructional INTEGER NOT NULL DEFAULT 1,
        UNIQUE (school_id, profile_id, day_code)
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_periods (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        period_no INTEGER NOT NULL,
        label TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        period_type TEXT NOT NULL DEFAULT 'lesson',
        duration_minutes INTEGER NOT NULL DEFAULT 0,
        UNIQUE (school_id, profile_id, period_no)
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_breaks (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        break_no INTEGER NOT NULL,
        label TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        applies_to TEXT NOT NULL DEFAULT 'all',
        UNIQUE (school_id, profile_id, break_no)
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_rooms (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        room_code TEXT NOT NULL,
        name TEXT NOT NULL,
        room_type TEXT NOT NULL DEFAULT 'classroom',
        capacity INTEGER,
        is_active INTEGER NOT NULL DEFAULT 1,
        UNIQUE (school_id, room_code)
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_calendar_exceptions (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        exception_date TEXT NOT NULL,
        label TEXT NOT NULL,
        exception_type TEXT NOT NULL DEFAULT 'holiday',
        notes TEXT,
        is_instructional INTEGER NOT NULL DEFAULT 0,
        UNIQUE (school_id, profile_id, exception_date, label)
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_teacher_availability (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        day_id INTEGER NOT NULL,
        period_id INTEGER NOT NULL,
        availability TEXT NOT NULL DEFAULT 'available',
        reason TEXT,
        UNIQUE (school_id, profile_id, teacher_id, day_id, period_id)
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_class_requirements (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        lessons_per_week INTEGER NOT NULL DEFAULT 1,
        duration_periods INTEGER NOT NULL DEFAULT 1,
        max_lessons_per_day INTEGER,
        min_gap_periods INTEGER NOT NULL DEFAULT 0,
        allow_double INTEGER NOT NULL DEFAULT 0,
        preferred_days_json TEXT NOT NULL DEFAULT '[]',
        UNIQUE (school_id, profile_id, class_id, subject_id, teacher_id)
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_lessons (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        room_id INTEGER,
        day_id INTEGER NOT NULL,
        period_id INTEGER NOT NULL,
        duration_periods INTEGER NOT NULL DEFAULT 1,
        lesson_group TEXT,
        generation_run_id INTEGER,
        status TEXT NOT NULL DEFAULT 'scheduled',
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_versions (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        version_no INTEGER NOT NULL,
        label TEXT NOT NULL,
        snapshot_json TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (school_id, profile_id, version_no)
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_generation_runs (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        engine_version TEXT NOT NULL,
        input_snapshot_json TEXT NOT NULL,
        result_summary_json TEXT,
        started_at TEXT,
        finished_at TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ds_timetable_change_log (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        lesson_id INTEGER,
        action TEXT NOT NULL,
        before_json TEXT,
        after_json TEXT,
        changed_by TEXT,
        changed_at TEXT NOT NULL
    )""",
)


_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_profiles_school_year ON ds_timetable_profiles(school_id, academic_year, term)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_profiles_revision ON ds_timetable_profiles(school_id, revision_of_profile_id, revision_no)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_days_profile_order ON ds_timetable_days(school_id, profile_id, day_order)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_calendar_profile_date ON ds_timetable_calendar_exceptions(school_id, profile_id, exception_date)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_periods_profile_order ON ds_timetable_periods(school_id, profile_id, period_no)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_availability_lookup ON ds_timetable_teacher_availability(school_id, profile_id, teacher_id, day_id, period_id)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_requirements_class ON ds_timetable_class_requirements(school_id, profile_id, class_id, subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_requirements_teacher ON ds_timetable_class_requirements(school_id, profile_id, teacher_id)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_lessons_class_grid ON ds_timetable_lessons(school_id, profile_id, class_id, day_id, period_id)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_lessons_teacher_grid ON ds_timetable_lessons(school_id, profile_id, teacher_id, day_id, period_id)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_lessons_room_grid ON ds_timetable_lessons(school_id, profile_id, room_id, day_id, period_id)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_lessons_generation ON ds_timetable_lessons(school_id, profile_id, generation_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_ds_tt_versions_profile ON ds_timetable_versions(school_id, profile_id, version_no)",
)


def ensure_timetable_schema(connection: Any) -> None:
    """Create the new timetable schema idempotently on SQLite or PostgreSQL.

    The schema deliberately uses only CREATE IF NOT EXISTS statements. There
    is no destructive migration and no startup-time rewrite of existing data.
    """
    cursor = connection.cursor()
    for statement in _TABLES:
        cursor.execute(statement)
    # Additive compatibility for profiles created by the first foundation
    # release before term date fields were introduced.
    cursor.execute("SELECT * FROM ds_timetable_profiles LIMIT 0")
    columns = {
        str(col.name if hasattr(col, "name") else col[0]).lower()
        for col in (cursor.description or [])
    }
    profile_column_types = {
        "academic_start_date": "TEXT",
        "academic_end_date": "TEXT",
        "approved_by": "TEXT",
        "approved_at": "TEXT",
        "published_by": "TEXT",
        "published_at": "TEXT",
        "current_version_id": "INTEGER",
        "revision_no": "INTEGER NOT NULL DEFAULT 1",
        "revision_of_profile_id": "INTEGER",
    }
    for column, column_type in profile_column_types.items():
        if column not in columns:
            cursor.execute("ALTER TABLE ds_timetable_profiles ADD COLUMN " + column + " " + column_type)
    cursor.execute("SELECT * FROM ds_timetable_lessons LIMIT 0")
    lesson_columns = {
        str(col.name if hasattr(col, "name") else col[0]).lower()
        for col in (cursor.description or [])
    }
    if "generation_run_id" not in lesson_columns:
        cursor.execute("ALTER TABLE ds_timetable_lessons ADD COLUMN generation_run_id INTEGER")
    for statement in _INDEXES:
        cursor.execute(statement)
    connection.commit()
