"""Timetable approval, publication, immutable snapshots and revisions."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.timetable.setup import TimetableSetupError


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_dict(row):
    return dict(row) if row is not None else None


def _snapshot(cursor, school_id: int, profile_id: int) -> dict:
    profile = cursor.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    if not profile:
        raise TimetableSetupError("Timetable profile not found.")
    snapshot = {"profile": _row_dict(profile)}
    queries = {
        "days": "SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? ORDER BY day_order,id",
        "periods": "SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id",
        "breaks": "SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=? ORDER BY break_no,id",
        "calendar_exceptions": "SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=? ORDER BY exception_date,id",
        "teacher_availability": "SELECT * FROM ds_timetable_teacher_availability WHERE school_id=? AND profile_id=? ORDER BY teacher_id,day_id,period_id",
        "requirements": "SELECT * FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=? ORDER BY class_id,subject_id,teacher_id",
        "lessons": "SELECT * FROM ds_timetable_lessons WHERE school_id=? AND profile_id=? AND status='scheduled' ORDER BY day_id,period_id,class_id,subject_id",
        "rooms": "SELECT * FROM ds_timetable_rooms WHERE school_id=? ORDER BY name,id",
    }
    for key, query in queries.items():
        snapshot[key] = [_row_dict(row) for row in cursor.execute(query, (school_id, profile_id) if key != "rooms" else (school_id,)).fetchall()]
    return snapshot


def validate_timetable_for_publication(connection: Any, school_id: int, profile_id: int) -> dict:
    cur = connection.cursor()
    profile = cur.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    if not profile:
        raise TimetableSetupError("Select a timetable profile belonging to this school.")
    errors = []
    if profile["status"] not in ("draft", "pending_approval"):
        errors.append("Only a draft or pending-approval timetable can be published.")
    active_run = cur.execute(
        "SELECT id FROM ds_timetable_generation_runs WHERE school_id=? AND profile_id=? AND status='running' LIMIT 1",
        (school_id, profile_id),
    ).fetchone()
    if active_run:
        errors.append("Automatic timetable generation is still running.")
    days = cur.execute(
        "SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? AND is_instructional=1",
        (school_id, profile_id),
    ).fetchall()
    periods = cur.execute(
        "SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id",
        (school_id, profile_id),
    ).fetchall()
    requirements = cur.execute(
        "SELECT * FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall()
    if not days:
        errors.append("Configure at least one instructional day.")
    if not any(str(p["period_type"] or "lesson") == "lesson" for p in periods):
        errors.append("Configure at least one teaching period.")
    if not requirements:
        errors.append("Configure weekly lesson requirements before publishing.")

    allocations = cur.execute(
        """SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id
           FROM teacher_allocations ta
           JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
           JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
           JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
           WHERE ta.school_id=?""",
        (school_id,),
    ).fetchall()
    allocation_keys = {(int(a["class_id"]),int(a["subject_id"]),int(a["teacher_id"])) for a in allocations}
    requirement_map = {
        (int(r["class_id"]),int(r["subject_id"]),int(r["teacher_id"])): r
        for r in requirements
    }
    for key in sorted(allocation_keys - set(requirement_map)):
        errors.append("A current class/subject/teacher allocation is missing its weekly lesson requirement.")
        break
    for key in sorted(set(requirement_map) - allocation_keys):
        errors.append("A weekly requirement no longer matches a current teacher allocation.")
        break

    breaks = cur.execute(
        "SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=?",
        (school_id, profile_id),
    ).fetchall()
    unavailable = {
        (int(r["teacher_id"]),int(r["day_id"]),int(r["period_id"]))
        for r in cur.execute(
            """SELECT teacher_id,day_id,period_id FROM ds_timetable_teacher_availability
               WHERE school_id=? AND profile_id=? AND availability='unavailable'""",
            (school_id, profile_id),
        ).fetchall()
    }
    room_ids = {
        int(r["id"]) for r in cur.execute(
            "SELECT id FROM ds_timetable_rooms WHERE school_id=? AND is_active=1",
            (school_id,),
        ).fetchall()
    }
    lessons = cur.execute(
        """SELECT * FROM ds_timetable_lessons
           WHERE school_id=? AND profile_id=? AND status='scheduled'""",
        (school_id, profile_id),
    ).fetchall()
    period_index = {int(p["id"]):i for i,p in enumerate(periods)}
    day_ids = {int(d["id"]) for d in days}
    lesson_counts = {}
    daily_counts = {}
    placements = []
    for lesson in lessons:
        key = (int(lesson["class_id"]),int(lesson["subject_id"]),int(lesson["teacher_id"]))
        lesson_counts[key] = lesson_counts.get(key,0) + 1
        daily_key = key + (int(lesson["day_id"]),)
        daily_counts[daily_key] = daily_counts.get(daily_key,0) + 1
        if key not in allocation_keys:
            errors.append("A scheduled lesson references a class/subject/teacher combination that is no longer allocated.")
        day_id = int(lesson["day_id"])
        if day_id not in day_ids:
            errors.append("A scheduled lesson is placed on a non-instructional or invalid day.")
            continue
        start_index = period_index.get(int(lesson["period_id"]))
        if start_index is None:
            errors.append("A scheduled lesson references a period outside this timetable profile.")
            continue
        duration = int(lesson["duration_periods"] or 1)
        span = periods[start_index:start_index + duration]
        valid_span = len(span) == duration
        if valid_span:
            for i, period in enumerate(span):
                if str(period["period_type"] or "lesson") != "lesson":
                    valid_span = False
                    break
                if i and (
                    int(period["period_no"]) != int(span[i-1]["period_no"]) + 1
                    or str(span[i-1]["end_time"]) != str(period["start_time"])
                ):
                    valid_span = False
                    break
        if not valid_span:
            errors.append("A scheduled multi-period lesson is not consecutive or crosses a non-teaching period.")
            continue
        if any((int(lesson["teacher_id"]),day_id,int(p["id"])) in unavailable for p in span):
            errors.append("A scheduled lesson falls inside a teacher's unavailable time.")
        if any(
            str(span[0]["start_time"]) < str(b["end_time"])
            and str(span[-1]["end_time"]) > str(b["start_time"])
            for b in breaks
        ):
            errors.append("A scheduled lesson overlaps a configured break.")
        room_id = int(lesson["room_id"]) if lesson["room_id"] is not None else None
        if room_id is not None and room_id not in room_ids:
            errors.append("A scheduled lesson uses an inactive or invalid room.")
        placements.append({
            "class_id":key[0],"subject_id":key[1],"teacher_id":key[2],"room_id":room_id,
            "day_id":day_id,"start_time":str(span[0]["start_time"]),"end_time":str(span[-1]["end_time"]),
        })

    for key, requirement in requirement_map.items():
        actual = lesson_counts.get(key,0)
        expected = int(requirement["lessons_per_week"] or 0)
        if actual != expected:
            errors.append(
                "A weekly requirement is not fully scheduled (class ID %s, subject ID %s: %s of %s lessons)."
                % (key[0],key[1],actual,expected)
            )
        max_per_day = int(requirement["max_lessons_per_day"]) if requirement["max_lessons_per_day"] is not None else 0
        if max_per_day and any(
            count > max_per_day for daily_key, count in daily_counts.items() if daily_key[:3] == key
        ):
            errors.append("A subject exceeds its configured maximum number of lessons on a day.")
    for i, first in enumerate(placements):
        for second in placements[i+1:]:
            if first["day_id"] != second["day_id"]:
                continue
            if first["start_time"] >= second["end_time"] or first["end_time"] <= second["start_time"]:
                continue
            if first["class_id"] == second["class_id"]:
                errors.append("Two lessons overlap for the same class.")
            if first["teacher_id"] == second["teacher_id"]:
                errors.append("A teacher is assigned to overlapping lessons.")
            if first["room_id"] is not None and second["room_id"] is not None and first["room_id"] == second["room_id"]:
                errors.append("A room is assigned to overlapping lessons.")
    errors = list(dict.fromkeys(errors))
    return {
        "ready": not errors,
        "errors": errors,
        "scheduled_lessons": len(lessons),
        "required_lessons": sum(int(r["lessons_per_week"] or 0) for r in requirements),
        "requirements": len(requirements),
    }


def submit_for_approval(connection: Any, school_id: int, profile_id: int, actor: str = "") -> dict:
    cur = connection.cursor()
    profile = cur.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id, school_id),
    ).fetchone()
    if not profile or profile["status"] != "draft":
        raise TimetableSetupError("Only a draft timetable can be submitted for approval.")
    readiness = validate_timetable_for_publication(connection, school_id, profile_id)
    if not readiness["ready"]:
        raise TimetableSetupError("Timetable is not ready for approval: " + " ".join(readiness["errors"][:4]))
    now = _now()
    cur.execute(
        "UPDATE ds_timetable_profiles SET status='pending_approval',updated_at=? WHERE id=? AND school_id=?",
        (now,profile_id,school_id),
    )
    cur.execute(
        """INSERT INTO ds_timetable_change_log
           (school_id,profile_id,action,before_json,after_json,changed_by,changed_at)
           VALUES(?,?,?,?,?,?,?)""",
        (school_id,profile_id,"SUBMIT_FOR_APPROVAL",json.dumps({"status":"draft"}),json.dumps({"status":"pending_approval"}),actor,now),
    )
    connection.commit()
    return readiness


def publish_timetable(connection: Any, school_id: int, profile_id: int, actor: str = "") -> dict:
    cur = connection.cursor()
    profile = cur.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (profile_id,school_id),
    ).fetchone()
    if not profile or profile["status"] != "pending_approval":
        raise TimetableSetupError("Submit this timetable for approval before publishing it.")
    readiness = validate_timetable_for_publication(connection,school_id,profile_id)
    if not readiness["ready"]:
        raise TimetableSetupError("Timetable is not ready to publish: " + " ".join(readiness["errors"][:4]))
    snapshot = _snapshot(cur,school_id,profile_id)
    version_no = cur.execute(
        "SELECT COALESCE(MAX(version_no),0)+1 AS next_no FROM ds_timetable_versions WHERE school_id=? AND profile_id=?",
        (school_id,profile_id),
    ).fetchone()["next_no"]
    now = _now()
    revision_no = int(profile["revision_no"] or 1)
    label = "Revision %s — Published" % revision_no
    cur.execute(
        """INSERT INTO ds_timetable_versions
           (school_id,profile_id,version_no,label,snapshot_json,created_by,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (school_id,profile_id,int(version_no),label,json.dumps(snapshot,default=str,sort_keys=True),actor,now),
    )
    version_id = int(cur.lastrowid or 0)
    if not version_id:
        version_id = int(cur.execute(
            "SELECT id FROM ds_timetable_versions WHERE school_id=? AND profile_id=? AND version_no=?",
            (school_id,profile_id,int(version_no)),
        ).fetchone()["id"])
    # A newly published revision becomes current; previous published revisions
    # remain archived and fully viewable for audit/history.
    previous = cur.execute(
        """SELECT id FROM ds_timetable_profiles
           WHERE school_id=? AND academic_year=? AND term=? AND status='published' AND id<>?""",
        (school_id,profile["academic_year"],profile["term"],profile_id),
    ).fetchall()
    for old in previous:
        cur.execute(
            "UPDATE ds_timetable_profiles SET status='archived',updated_at=? WHERE id=? AND school_id=?",
            (now,int(old["id"]),school_id),
        )
        cur.execute(
            """INSERT INTO ds_timetable_change_log
               (school_id,profile_id,action,before_json,after_json,changed_by,changed_at)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id,int(old["id"]),"PROFILE_ARCHIVE",json.dumps({"status":"published"}),json.dumps({"status":"archived"}),actor,now),
        )
    cur.execute(
        """UPDATE ds_timetable_profiles
           SET status='published',approved_by=?,approved_at=?,published_by=?,published_at=?,current_version_id=?,updated_at=?
           WHERE id=? AND school_id=?""",
        (actor,now,actor,now,version_id,now,profile_id,school_id),
    )
    cur.execute(
        """INSERT INTO ds_timetable_change_log
           (school_id,profile_id,action,before_json,after_json,changed_by,changed_at)
           VALUES(?,?,?,?,?,?,?)""",
        (school_id,profile_id,"PUBLISH",json.dumps({"status":"pending_approval"}),json.dumps({"status":"published","version_id":version_id,"version_no":int(version_no)}),actor,now),
    )
    connection.commit()
    return {"version_id":version_id,"version_no":int(version_no),"readiness":readiness}


def create_revision(connection: Any, school_id: int, source_profile_id: int, actor: str = "") -> int:
    cur = connection.cursor()
    source = cur.execute(
        "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
        (source_profile_id,school_id),
    ).fetchone()
    if not source or source["status"] not in ("published","archived"):
        raise TimetableSetupError("Only a published or archived timetable can be used to create a revision.")
    root_id = int(source["revision_of_profile_id"] or source["id"])
    max_revision = cur.execute(
        """SELECT COALESCE(MAX(revision_no),1) AS max_no FROM ds_timetable_profiles
           WHERE school_id=? AND (id=? OR revision_of_profile_id=?)""",
        (school_id,root_id,root_id),
    ).fetchone()["max_no"]
    revision_no = int(max_revision or 1) + 1
    now = _now()
    name = str(source["name"] or "Timetable").split(" · Revision ")[0] + " · Revision " + str(revision_no)
    cur.execute(
        """INSERT INTO ds_timetable_profiles
           (school_id,name,academic_year,term,status,week_start,week_end,academic_start_date,academic_end_date,
            settings_json,created_by,created_at,updated_at,revision_no,revision_of_profile_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            school_id,name,source["academic_year"],source["term"],"draft",source["week_start"],source["week_end"],
            source["academic_start_date"],source["academic_end_date"],source["settings_json"],actor,now,now,
            revision_no,root_id,
        ),
    )
    new_id = int(cur.lastrowid or 0)
    if not new_id:
        new_id = int(cur.execute(
            "SELECT id FROM ds_timetable_profiles WHERE school_id=? AND name=? AND created_at=? ORDER BY id DESC LIMIT 1",
            (school_id,name,now),
        ).fetchone()["id"])
    day_map = {}
    period_map = {}
    for row in cur.execute("SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? ORDER BY day_order,id",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_days (school_id,profile_id,day_code,day_name,day_order,is_instructional)
               VALUES(?,?,?,?,?,?)""",
            (school_id,new_id,row["day_code"],row["day_name"],row["day_order"],row["is_instructional"]),
        )
        day_map[int(row["id"])] = int(cur.lastrowid)
    for row in cur.execute("SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_periods
               (school_id,profile_id,period_no,label,start_time,end_time,period_type,duration_minutes)
               VALUES(?,?,?,?,?,?,?,?)""",
            (school_id,new_id,row["period_no"],row["label"],row["start_time"],row["end_time"],row["period_type"],row["duration_minutes"]),
        )
        period_map[int(row["id"])] = int(cur.lastrowid)
    for row in cur.execute("SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=?",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_breaks (school_id,profile_id,break_no,label,start_time,end_time,applies_to)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id,new_id,row["break_no"],row["label"],row["start_time"],row["end_time"],row["applies_to"]),
        )
    for row in cur.execute("SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=?",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_calendar_exceptions
               (school_id,profile_id,exception_date,label,exception_type,notes,is_instructional)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id,new_id,row["exception_date"],row["label"],row["exception_type"],row["notes"],row["is_instructional"]),
        )
    for row in cur.execute("SELECT * FROM ds_timetable_teacher_availability WHERE school_id=? AND profile_id=?",(school_id,source_profile_id)).fetchall():
        if int(row["day_id"]) not in day_map or int(row["period_id"]) not in period_map:
            continue
        cur.execute(
            """INSERT INTO ds_timetable_teacher_availability
               (school_id,profile_id,teacher_id,day_id,period_id,availability,reason)
               VALUES(?,?,?,?,?,?,?)""",
            (school_id,new_id,row["teacher_id"],day_map[int(row["day_id"])],period_map[int(row["period_id"])],row["availability"],row["reason"]),
        )
    for row in cur.execute("SELECT * FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=?",(school_id,source_profile_id)).fetchall():
        cur.execute(
            """INSERT INTO ds_timetable_class_requirements
               (school_id,profile_id,class_id,subject_id,teacher_id,lessons_per_week,duration_periods,max_lessons_per_day,min_gap_periods,allow_double,preferred_days_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (school_id,new_id,row["class_id"],row["subject_id"],row["teacher_id"],row["lessons_per_week"],row["duration_periods"],row["max_lessons_per_day"],row["min_gap_periods"],row["allow_double"],row["preferred_days_json"]),
        )
    for row in cur.execute("SELECT * FROM ds_timetable_lessons WHERE school_id=? AND profile_id=? AND status='scheduled'",(school_id,source_profile_id)).fetchall():
        if int(row["day_id"]) not in day_map or int(row["period_id"]) not in period_map:
            continue
        cur.execute(
            """INSERT INTO ds_timetable_lessons
               (school_id,profile_id,class_id,subject_id,teacher_id,room_id,day_id,period_id,duration_periods,generation_run_id,status,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,NULL,'scheduled',?,?,?)""",
            (
                school_id,new_id,row["class_id"],row["subject_id"],row["teacher_id"],row["room_id"],
                day_map[int(row["day_id"])],period_map[int(row["period_id"])],row["duration_periods"],
                actor,now,now,
            ),
        )
    cur.execute(
        """INSERT INTO ds_timetable_change_log
           (school_id,profile_id,action,before_json,after_json,changed_by,changed_at)
           VALUES(?,?,?,?,?,?,?)""",
        (school_id,new_id,"PROFILE_REVISION_CREATE",json.dumps({"source_profile_id":source_profile_id}),json.dumps({"revision_no":revision_no,"revision_of_profile_id":root_id}),actor,now),
    )
    connection.commit()
    return new_id


def list_profile_versions(connection: Any, school_id: int, profile_id: int):
    cur = connection.cursor()
    profile = cur.execute("SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",(profile_id,school_id)).fetchone()
    if not profile:
        raise TimetableSetupError("Timetable profile not found.")
    root_id = int(profile["revision_of_profile_id"] or profile["id"])
    return cur.execute(
        """SELECT v.*,p.name profile_name,p.revision_no,p.status profile_status
           FROM ds_timetable_versions v JOIN ds_timetable_profiles p ON p.id=v.profile_id AND p.school_id=v.school_id
           WHERE v.school_id=? AND (p.id=? OR p.revision_of_profile_id=?)
           ORDER BY p.revision_no,v.version_no""",
        (school_id,root_id,root_id),
    ).fetchall()


def compare_timetable_versions(connection: Any, school_id: int, first_version_id: int, second_version_id: int) -> dict:
    cur = connection.cursor()
    rows = cur.execute(
        """SELECT v.*,p.academic_year,p.term FROM ds_timetable_versions v
           JOIN ds_timetable_profiles p ON p.id=v.profile_id AND p.school_id=v.school_id
           WHERE v.school_id=? AND v.id IN (?,?)""",
        (school_id,first_version_id,second_version_id),
    ).fetchall()
    by_id = {int(r["id"]):r for r in rows}
    if first_version_id not in by_id or second_version_id not in by_id:
        raise TimetableSetupError("Choose two published versions belonging to this school.")
    first, second = by_id[first_version_id], by_id[second_version_id]
    if first["academic_year"] != second["academic_year"] or first["term"] != second["term"]:
        raise TimetableSetupError("Only versions from the same academic year and term can be compared.")
    first_snapshot = json.loads(first["snapshot_json"] or "{}")
    second_snapshot = json.loads(second["snapshot_json"] or "{}")
    def lesson_map(snapshot):
        day_codes = {int(d["id"]):str(d["day_code"]) for d in snapshot.get("days",[])}
        period_details = {
            int(p["id"]):(int(p["period_no"]),str(p["start_time"]),str(p["end_time"]))
            for p in snapshot.get("periods",[])
        }
        result = {}
        for lesson in snapshot.get("lessons",[]):
            period = period_details.get(int(lesson["period_id"]), (str(lesson["period_id"]),"",""))
            key = (
                int(lesson["class_id"]),int(lesson["subject_id"]),int(lesson["teacher_id"]),
                day_codes.get(int(lesson["day_id"]),str(lesson["day_id"])),
                period,int(lesson["duration_periods"] or 1),
                int(lesson["room_id"]) if lesson.get("room_id") is not None else None,
            )
            result[key] = lesson
        return result
    first_lessons = lesson_map(first_snapshot)
    second_lessons = lesson_map(second_snapshot)
    added = [second_lessons[k] for k in second_lessons.keys()-first_lessons.keys()]
    removed = [first_lessons[k] for k in first_lessons.keys()-second_lessons.keys()]
    return {
        "first_version":first,
        "second_version":second,
        "added":added,
        "removed":removed,
        "unchanged":len(first_lessons.keys() & second_lessons.keys()),
    }
