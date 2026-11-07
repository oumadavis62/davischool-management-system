# DaviSchool Timetable v2 — Architecture

## Foundation principles

- The timetable is a bounded module under `app/timetable/`; its schema uses the `ds_timetable_*` namespace.
- Existing schools, classes, subjects, teachers and teacher allocations remain the source of truth. Timetable rows store their IDs and are tenant-scoped by `school_id`; they do not copy or mutate those records.
- All timetable records belong to a school and a timetable profile (the academic-year/term planning context).
- Schema creation is additive and idempotent. It must never drop, rename, truncate or rewrite timetable-independent school data.
- The old `timetable_*` entities are retired. New code must not reuse those names, so the one-time legacy retirement migration cannot remove v2 data.
- Timetable requests must be lazy-loaded. Database initialization creates only the small schema; it must not generate schedules or scan teacher/student records.

## Data model

| Table | Responsibility |
|---|---|
| `ds_timetable_profiles` | One planning/publishing context per school, academic year and term |
| `ds_timetable_days` | Ordered instructional days within a profile |
| `ds_timetable_periods` | Teaching periods and their exact time boundaries |
| `ds_timetable_breaks` | Breaks, lunch and non-teaching intervals |
| `ds_timetable_rooms` | School-owned classrooms and specialist facilities |
| `ds_timetable_teacher_availability` | Per-profile teacher availability by day and period |
| `ds_timetable_class_requirements` | Required weekly lesson frequency and scheduling preferences |
| `ds_timetable_lessons` | Actual scheduled lesson placements |
| `ds_timetable_versions` | Immutable snapshots for comparison and rollback |
| `ds_timetable_generation_runs` | Auditable automatic-generation jobs and outcomes |
| `ds_timetable_change_log` | Who changed what, and when |

## Scheduling invariants

Hard constraints (never violate):
- A class/stream cannot have two lessons in an overlapping period.
- A teacher cannot teach two classes in an overlapping period.
- A room cannot host two lessons in an overlapping period.
- Lessons must fit within instructional periods and cannot overlap configured breaks.
- A lesson must reference active, same-school classes, subjects, teachers and rooms.
- Weekly subject requirements must be met before a timetable can be published.

Soft constraints (optimize and report):
- Balance subject distribution across the week.
- Avoid excessive teacher and learner idle gaps.
- Respect preferred days, double-lesson preferences and workload balance.
- Avoid placing demanding subjects repeatedly at the end of the day.

## Delivery sequence

1. **Foundation:** isolated schema, tenant-safe data contracts and tests.
2. **Setup:** academic profile, days, periods, breaks, rooms and availability.
3. **Manual builder:** weekly grid, placement validation, move/resize and draft save.
4. **Automatic engine:** constraint solver, explainable failures and quality scoring.
5. **Views:** school, class/stream, teacher and room schedules.
6. **Publishing:** approvals, immutable versions, exports and print layouts.
7. **Operations:** substitutions, change notifications and audit history.
8. **Hardening:** integration tests, performance tests, access checks and production verification.

Each stage is independently testable and reversible. The new module must remain isolated from marks, attendance, student records and teacher portals.
