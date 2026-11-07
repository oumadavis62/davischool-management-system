# Timetable v2 — Stage 4: Automatic generation

## Generation workflow

- Select a draft academic-year/term profile and run the generator.
- The engine expands every weekly requirement into individual lesson occurrences.
- Every current teacher allocation must have exactly one matching weekly lesson requirement.
- Existing manually placed lessons are fixed anchors and are preserved.
- A previous automatic timetable is replaced only after the engine finds a complete valid solution.
- Failed runs retain the previous generated timetable and record an explanation in generation history.

## Hard constraints

- Every lesson is placed on an instructional day and in a teaching period.
- Multi-period lessons must use consecutive teaching periods with no intervening break.
- Teacher unavailability is a hard restriction.
- Class, teacher and room double-bookings are prohibited.
- Configured breaks cannot be crossed by a lesson.
- Per-day subject frequency and weekly lesson totals are respected.
- All current class/subject/teacher allocations must be covered by requirements.
- Existing manual lessons remain fixed and count toward weekly subject frequency.

## Optimization preferences

The deterministic most-constrained-first search scores candidate placements to:
- Spread the same subject across different days.
- Balance daily class and teacher workloads.
- Reduce idle gaps in class and teacher schedules.
- Prefer earlier periods where other constraints are equal.
- Prefer teacher-marked preferred periods.
- Assign a room that is free during the full lesson interval.

The solver uses bounded backtracking. If it cannot find a complete timetable within the search budget, it records a failed run and does not replace the last valid generated schedule.

## Audit and recovery

- Each attempt is recorded in `ds_timetable_generation_runs` with engine version, input snapshot, status and result summary.
- Generated lesson rows link to their run through `generation_run_id`.
- Every generated or replaced lesson is recorded in the timetable change log.
- Manually moved generated lessons are converted to manual overrides and are preserved by later runs.
- Only one generation run can execute for a profile at a time.

## Tests

SQLite tests cover complete generation, room assignment, manual lesson preservation, safe replacement behavior, failure recovery, weekly constraints and missing allocation requirements.
