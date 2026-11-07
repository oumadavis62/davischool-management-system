# Timetable v2 — Stage 7: Portal distribution

## Portal access

- Authenticated teacher accounts open `/app/timetable` and see lessons assigned to their linked teacher record.
- Authenticated student accounts see the timetable for their linked learner's current class and stream.
- Authenticated parent accounts see the timetable for each learner linked through `parent_student_links`.
- Every identity lookup is constrained by the signed-in school ID. A user cannot choose an arbitrary teacher, learner, class, parent or school ID in the URL.
- Only profiles whose current status is `published` are distributed. Draft, pending-approval and archived profiles are not exposed.

## Revision distribution

The portal resolves published profiles on each request instead of caching a timetable snapshot in the browser. It refreshes every 60 seconds so a newly published revision becomes visible to an already-open portal page without a manual reload.

## Verification

SQLite tests cover teacher-to-school scoping, student-to-class scoping, parent-to-linked-children scoping, cross-school link exclusion and missing/unknown identities. Production browser verification and end-to-end login testing remain part of Stage 8.
