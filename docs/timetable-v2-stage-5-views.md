# Timetable v2 — Stage 5: Multiple timetable views

## Read-only views

- **School-wide:** all scheduled lessons in the selected profile.
- **Class/stream:** one class timetable with subject, allocated teacher and room.
- **Teacher:** all lessons assigned to one teacher, across their allocated classes.
- **Room/facility:** every booking for one active school room.

## Presentation

- Shared weekly day-by-period grid.
- Multi-period lessons show continuation cells.
- School-wide view can show multiple lesson cards in a cell.
- Profile and target selectors are school-scoped.
- Published and archived profiles remain available in read-only views.
- Print-friendly layout hides controls and formats the grid for paper/PDF printing.
- Views link back to the manual builder, automatic generator and setup workspace.

## Safety

- The view service validates profile and target ownership against the authenticated school.
- View routes never modify timetable records.
- Only scheduled lesson rows are displayed; drafts and deleted lessons are not exposed as published schedule entries.

## Tests

SQLite tests cover whole-school, class, teacher and room filtering, plus cross-school target rejection.

## CI execution

The repository workflow compiles application and test modules and runs the full unittest suite for pull requests targeting `main`.
