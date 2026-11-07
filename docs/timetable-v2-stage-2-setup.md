# Timetable v2 — Stage 2: Setup workspace

Stage 2 adds an administrator-facing configuration workspace at `/school/timetable/setup`.

## Capabilities

- Create a draft profile for an academic year and term, with optional academic start and end dates.
- Configure ordered instructional/non-instructional school days, including a Monday–Friday starter.
- Define teaching periods with 24-hour start/end times and period type.
- Define breaks and lunch; prevent breaks from overlapping lessons or other breaks.
- Register school-owned classrooms and specialist rooms with type and capacity.
- Record teacher availability as available, unavailable or preferred for a specific day/period.
- Define weekly class/subject lesson requirements from existing teacher allocations, including lesson duration, maximum daily frequency and double-lesson permission.

## Access and data safety

- Only authenticated school administrators and registrars can use the setup workspace.
- Every profile operation is scoped to the authenticated school.
- Teacher availability must reference a teacher, day and period belonging to that school and selected profile.
- Lesson requirements must match a real row in the school's existing `teacher_allocations` table.
- The module reads existing classes, subjects, teachers and allocations; it does not duplicate or modify those records.
- Published or archived profiles are read-only at the setup-service layer.

## Validation

- Profile name, year and term are required; only one non-archived profile per school/year/term is allowed. When supplied, the academic start/end dates must be valid and ordered.
- Times must be valid 24-hour values and end after start.
- Teaching periods cannot overlap one another.
- Breaks cannot overlap a teaching period or another break.
- Room codes are unique per school and updates reuse the existing room record.
- Weekly lesson frequency is 1–30; lesson duration is 1–4 periods.

## Test coverage

SQLite unit tests cover profile uniqueness and academic date ranges, period overlap, break overlap, room upsert, school/profile-safe teacher availability and allocation-backed lesson requirements. Existing profile tables receive the two date columns through an additive startup migration.
