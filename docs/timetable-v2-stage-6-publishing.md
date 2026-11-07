# Timetable v2 — Stage 6: Approval, publishing and exports

## Approval lifecycle

- Draft profiles are editable.
- Submitting for approval runs a full publication-readiness validation and locks the profile.
- Pending-approval profiles are read-only.
- Publishing performs the validation again, records an immutable version snapshot, and marks the profile published.
- Publishing a newer revision archives the previous published profile for the same school, academic year and term.
- Published and archived profiles remain available in read-only timetable views.

## Publication checks

The timetable cannot be published unless:
- Every current class/subject/teacher allocation has a weekly lesson requirement.
- Every weekly lesson requirement is scheduled exactly.
- No class, teacher or room has overlapping lessons.
- Teachers are not scheduled during unavailable periods.
- Lessons use valid instructional days and teaching periods.
- Multi-period lessons are consecutive and do not cross breaks.
- Rooms are active and configured per school.
- Configured per-day subject limits are respected.
- No automatic generation run is still active.

## Immutable versions and revisions

- Publishing stores a complete JSON snapshot of the profile, calendar, days, periods, breaks, rooms, teacher availability, requirements and scheduled lessons.
- Version rows are immutable.
- Version history is grouped across profile revisions.
- Two published versions can be compared to show added, removed and unchanged lessons.
- Creating a revision clones the published configuration and timetable into a new draft profile.
- The previous published profile remains archived and unchanged.

## Exports

- Branded landscape PDF timetable.
- Excel workbook with a weekly grid and a separate lesson-detail sheet.
- Exports support whole-school, class, teacher and room views.
- The read-only views also include browser print formatting.

## Tests

SQLite tests cover publication readiness, approval locking, version snapshots, revision cloning, archiving, version comparison and export/view data integrity.
