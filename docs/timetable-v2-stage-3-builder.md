# Timetable v2 — Stage 3: Manual builder

## User workflow

- Open the Timetable sidebar entry to reach the master timetable builder.
- Choose a draft academic-year/term profile.
- Add lessons only from class/subject/teacher combinations with a configured weekly requirement.
- Choose an instructional day, a teaching period and an optional room.
- The builder uses the requirement's configured lesson duration automatically.
- Move lessons with drag-and-drop or the accessible Move controls.
- Delete lessons with confirmation; every create, move and delete is written to the timetable change log.

## Hard validation

A lesson placement is rejected when:
- The day or period does not belong to the selected school/profile.
- The day is non-instructional or the period is not a teaching period.
- The teacher is not allocated to that class and subject in the same school.
- A weekly class-subject-teacher requirement has not been configured.
- The teacher is marked unavailable in any occupied period.
- A multi-period lesson cannot occupy consecutive periods without a break.
- The lesson overlaps a configured break.
- The class, teacher or selected room is already occupied during the same time window.
- The configured weekly frequency has already been filled.

The builder validates the entire occupied time interval, not only the first period. A double lesson therefore reserves both periods for the class, teacher and room.

## Audit and isolation

- All lesson operations are scoped by school and timetable profile.
- Existing classes, subjects, teachers and teacher allocations are read-only sources of truth.
- Lesson create, move and delete actions record before/after snapshots and the actor in `ds_timetable_change_log`.
- The manual builder is a draft editing surface. Publishing and version snapshots are handled in later stages.

## Tests

SQLite unit tests cover valid placement, class conflicts, teacher conflicts across classes, room conflicts, teacher unavailability, non-consecutive double periods, move/delete behavior and audit history.
