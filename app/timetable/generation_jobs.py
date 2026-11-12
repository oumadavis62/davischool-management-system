"""Durable, database-backed background jobs for complete timetable generation.

The web request only enqueues work. A single process-local consumer claims jobs
from PostgreSQL and runs the existing solvers outside the request lifecycle.
Jobs survive browser disconnects and are recoverable after process restarts.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from app.timetable.time_utils import format_eat, now_eat

from app.timetable.generator import (
    GENERATION_TIME_LIMIT_SECONDS,
    generate_timetable,
    generate_advanced_instructional_sessions,
)

log = logging.getLogger("davischool.timetable.jobs")
_worker_lock = threading.Lock()
_worker_thread = None
_STOP = threading.Event()


def ensure_generation_jobs_table(con) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS ds_timetable_generation_jobs (
            id INTEGER PRIMARY KEY,
            school_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            requested_by TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            stage TEXT NOT NULL DEFAULT 'queued',
            result_run_id INTEGER,
            message TEXT,
            created_at TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP
        )"""
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_ds_timetable_jobs_queue "
        "ON ds_timetable_generation_jobs(status, created_at)"
    )
    con.commit()


def enqueue_generation_job(get_db: Callable, school_id: int, profile_id: int, requested_by: str) -> int:
    con = get_db()
    try:
        ensure_generation_jobs_table(con)
        existing = con.execute(
            """SELECT id FROM ds_timetable_generation_jobs
               WHERE school_id=? AND profile_id=? AND status IN ('queued','running')
               ORDER BY id DESC LIMIT 1""",
            (int(school_id), int(profile_id)),
        ).fetchone()
        if existing:
            con.commit()
            return int(existing["id"])
        cur = con.execute(
            """INSERT INTO ds_timetable_generation_jobs
               (school_id, profile_id, requested_by, status, stage, created_at)
               VALUES (?, ?, ?, 'queued', 'queued', ?)""",
            (int(school_id), int(profile_id), str(requested_by or ""), now_eat()),
        )
        job_id = int(cur.lastrowid)
        con.commit()
        return job_id
    finally:
        con.close()


def get_generation_job(get_db: Callable, school_id: int, job_id: int):
    con = get_db()
    try:
        row = con.execute(
            """SELECT id, profile_id, status, stage, result_run_id, message,
                      created_at, started_at, finished_at
               FROM ds_timetable_generation_jobs
               WHERE id=? AND school_id=?""",
            (int(job_id), int(school_id)),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        for key, value in result.items():
            if key in ("created_at", "started_at", "finished_at"):
                result[key] = format_eat(value)
            elif hasattr(value, "isoformat"):
                result[key] = value.isoformat()
        return result
    finally:
        con.close()


def _set_job(get_db, job_id: int, **fields) -> None:
    allowed = {"status", "stage", "result_run_id", "message", "started_at", "finished_at"}
    fields = {key: value for key, value in fields.items() if key in allowed}
    if not fields:
        return
    con = get_db()
    try:
        assignments = ", ".join(key + " = ?" for key in fields)
        con.execute(
            "UPDATE ds_timetable_generation_jobs SET " + assignments + " WHERE id=?",
            (*fields.values(), int(job_id)),
        )
        con.commit()
    finally:
        con.close()


def _delete_sessions(con, school_id: int, profile_id: int, session_ids) -> None:
    ids = [int(value) for value in (session_ids or []) if value]
    if not ids:
        return
    marks = ",".join("?" for _ in ids)
    con.execute(
        f"DELETE FROM ds_timetable_session_classes WHERE session_id IN ({marks})", tuple(ids)
    )
    con.execute(
        f"DELETE FROM ds_timetable_session_teachers WHERE session_id IN ({marks})", tuple(ids)
    )
    con.execute(
        f"DELETE FROM ds_timetable_session_learners WHERE session_id IN ({marks})", tuple(ids)
    )
    con.execute(
        f"DELETE FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND id IN ({marks})",
        (int(school_id), int(profile_id), *ids),
    )



def _reconcile_profile_runs(con, school_id: int, profile_id: int, current_job_id: int) -> int:
    """Close abandoned solver rows when no other job owns this profile."""
    other_job = con.execute(
        """SELECT id FROM ds_timetable_generation_jobs
           WHERE school_id=? AND profile_id=? AND status='running' AND id<>?
           LIMIT 1""",
        (int(school_id), int(profile_id), int(current_job_id)),
    ).fetchone()
    if other_job:
        return 0
    cur = con.execute(
        """UPDATE ds_timetable_generation_runs
           SET status='failed', finished_at=?
           WHERE school_id=? AND profile_id=? AND status='running'""",
        (now_eat(), int(school_id), int(profile_id)),
    )
    con.commit()
    return int(getattr(cur, "rowcount", 0) or 0)


def _execute_job(get_db, job):
    job_id = int(job["id"])
    school_id = int(job["school_id"])
    profile_id = int(job["profile_id"])
    email = str(job["requested_by"] or "")
    # One shared wall-clock budget covers normalized sessions, ordinary
    # lessons, and their database-backed candidate preparation. Keep this
    # aligned with the solver's advertised 120-second generation limit.
    deadline = time.monotonic() + GENERATION_TIME_LIMIT_SECONDS
    con = get_db()
    advanced_result = None
    created_advanced_ids = []
    try:
        # A previous worker may have died after creating a run row. Reconcile
        # it before the solver's running-run guard is evaluated.
        _reconcile_profile_runs(con, school_id, profile_id, job_id)
        _set_job(get_db, job_id, stage="checking requirements")
        profile_row = con.execute(
            "SELECT profile_type FROM ds_timetable_profiles WHERE id=? AND school_id=?",
            (profile_id, school_id),
        ).fetchone()
        profile_type = str(profile_row["profile_type"] or "main").lower() if profile_row else "main"
        advanced_layer_filter = "schedule_layer='instructional'" if profile_type == "main" else "schedule_layer IN ('instructional','additional_learning')"
        advanced_count = con.execute(
            """SELECT COUNT(*) FROM ds_timetable_scheduling_requirements
               WHERE school_id=? AND profile_id=? AND is_active=1 AND """ + advanced_layer_filter,
            (school_id, profile_id),
        ).fetchone()[0]
        legacy_count = con.execute(
            "SELECT COUNT(*) FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=?",
            (school_id, profile_id),
        ).fetchone()[0]
        if int(advanced_count or 0):
            _set_job(get_db, job_id, stage="generating combined and co-teaching lessons")
            advanced_result = generate_advanced_instructional_sessions(
                con, school_id, profile_id, email, defer_replacement=True,
                deadline=deadline
            )
            created_advanced_ids = list(advanced_result.get("session_ids") or [])
            _delete_sessions(con, school_id, profile_id, advanced_result.get("previous_session_ids") or [])

        if profile_type != "main" and advanced_result and not int(legacy_count or 0):
            con.execute(
                "DELETE FROM ds_timetable_lessons WHERE school_id=? AND profile_id=? AND status='scheduled'",
                (school_id, profile_id),
            )
            from app.timetable.publishing import _cross_profile_conflicts
            profile_for_conflicts = con.execute(
                "SELECT * FROM ds_timetable_profiles WHERE id=? AND school_id=?",
                (profile_id, school_id),
            ).fetchone()
            cross_conflicts = _cross_profile_conflicts(con.cursor(), school_id, profile_for_conflicts)
            if cross_conflicts:
                raise TimetableSetupError("Generation found cross-timetable conflicts: " + " ".join(cross_conflicts[:3]))
            result = {
                "status": "completed",
                "run_id": int(advanced_result["run_id"]),
                "generated_lessons": 0,
                "generated_sessions": int(advanced_result.get("generated_sessions") or 0),
                "message": "Specialized teaching sessions generated successfully.",
            }
        else:
            _set_job(get_db, job_id, stage="generating ordinary lessons")
            result = generate_timetable(
                con, school_id, profile_id, email,
                normalized_run_id=(advanced_result or {}).get("run_id"),
                deadline=deadline,
            )
        if result.get("status") != "completed":
            _delete_sessions(con, school_id, profile_id, created_advanced_ids)
            if advanced_result and advanced_result.get("run_id"):
                con.execute(
                    """UPDATE ds_timetable_generation_runs
                       SET status='failed', finished_at=?
                       WHERE id=? AND school_id=?""",
                    (now_eat(), int(advanced_result["run_id"]), school_id),
                )
            con.commit()
            _set_job(
                get_db, job_id, status="failed", stage="failed",
                result_run_id=int(result.get("run_id") or 0) or None,
                message=str(result.get("message") or "The solver could not find a complete timetable."),
            )
            con.execute("UPDATE ds_timetable_generation_jobs SET finished_at=? WHERE id=?", (now_eat(), job_id))
            con.commit()
            _reconcile_profile_runs(con, school_id, profile_id, job_id)
            return

        if advanced_result:
            # Normalized sessions and ordinary lessons form one generation.
            con.execute(
                """UPDATE ds_timetable_generation_runs
                   SET status='completed', finished_at=?
                   WHERE id=? AND school_id=? AND status='running'""",
                (now_eat(), int(advanced_result["run_id"]), school_id),
            )
            previous_ids = list(advanced_result.get("previous_session_ids") or [])
            _delete_sessions(con, school_id, profile_id, previous_ids)
            con.commit()
            result["generated_sessions"] = int(advanced_result.get("generated_sessions") or 0)
            result["message"] = (
                str(result.get("message") or "Weekly timetable generated.")
                + " Combined/co-teaching sessions: "
                + str(result["generated_sessions"]) + "."
            )

        _set_job(
            get_db, job_id, status="completed", stage="completed",
            result_run_id=int(result.get("run_id") or 0) or None,
            message=str(result.get("message") or "Timetable generated successfully."),
            finished_at=None,
        )
        con.execute(
            """UPDATE ds_timetable_generation_jobs
               SET finished_at=? WHERE id=?""", (now_eat(), job_id)
        )
        con.commit()
        _reconcile_profile_runs(con, school_id, profile_id, job_id)
    except Exception as exc:
        log.exception(
            "Background timetable generation failed (job_id=%s school_id=%s profile_id=%s)",
            job_id, school_id, profile_id,
        )
        try:
            con.rollback()
            _delete_sessions(con, school_id, profile_id, created_advanced_ids)
            _reconcile_profile_runs(con, school_id, profile_id, job_id)
            if advanced_result and advanced_result.get("run_id"):
                con.execute(
                    """UPDATE ds_timetable_generation_runs
                       SET status='failed', finished_at=?
                       WHERE id=? AND school_id=?""",
                    (now_eat(), int(advanced_result["run_id"]), school_id),
                )
            con.commit()
        except Exception:
            con.rollback()
        _set_job(
            get_db, job_id, status="failed", stage="failed",
            message="Generation failed: " + str(exc)[:700],
        )
        con.execute(
            "UPDATE ds_timetable_generation_jobs SET finished_at=? WHERE id=?",
            (now_eat(), job_id),
        )
        con.commit()
    finally:
        con.close()


def _worker_loop(get_db):
    log.info("Timetable background generation worker started")
    while not _STOP.is_set():
        con = None
        job = None
        try:
            con = get_db()
            # Queue schema is created once when the worker starts.
            # One consumer per web process; the conditional update also prevents
            # duplicate claims if a second consumer is accidentally started.
            row = con.execute(
                """SELECT id, school_id, profile_id, requested_by
                   FROM ds_timetable_generation_jobs
                   WHERE status='queued' ORDER BY id LIMIT 1"""
            ).fetchone()
            if row:
                claimed = con.execute(
                    """UPDATE ds_timetable_generation_jobs
                       SET status='running', stage='starting', started_at=?
                       WHERE id=? AND status='queued'""",
                    (now_eat(), int(row["id"])),
                )
                con.commit()
                if getattr(claimed, "rowcount", 1):
                    job = dict(row)
            else:
                con.commit()
        except Exception:
            if con:
                try:
                    con.rollback()
                except Exception:
                    pass
            log.exception("Could not poll timetable generation queue")
        finally:
            if con:
                con.close()
        if job:
            try:
                _execute_job(get_db, job)
            except Exception:
                log.exception("Timetable job worker failed before completing job_id=%s", job.get("id"))
                try:
                    _set_job(
                        get_db, int(job["id"]), status="queued",
                        stage="retrying after a temporary database error",
                        message="The worker encountered a temporary database error and will retry.",
                    )
                except Exception:
                    log.exception("Could not requeue timetable job_id=%s after worker failure", job.get("id"))
        else:
            _STOP.wait(2.0)


def start_generation_worker(get_db) -> None:
    global _worker_thread
    setup = get_db()
    try:
        ensure_generation_jobs_table(setup)
        # A process restart means no previous in-process consumer can still be
        # executing. Close its orphaned solver rows before requeuing interrupted jobs.
        interrupted = setup.execute(
            """SELECT DISTINCT school_id, profile_id
               FROM ds_timetable_generation_jobs WHERE status='running'"""
        ).fetchall()
        for item in interrupted:
            setup.execute(
                """UPDATE ds_timetable_generation_runs
                   SET status='failed', finished_at=?
                   WHERE school_id=? AND profile_id=? AND status='running'""",
                (now_eat(), int(item["school_id"]), int(item["profile_id"])),
            )
        setup.execute(
            """UPDATE ds_timetable_generation_jobs
               SET status='queued', stage='resuming after service restart'
               WHERE status='running'"""
        )
        setup.commit()
    finally:
        setup.close()
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _STOP.clear()
        _worker_thread = threading.Thread(
            target=_worker_loop, args=(get_db,),
            name="davischool-timetable-worker", daemon=True,
        )
        _worker_thread.start()


def stop_generation_worker() -> None:
    _STOP.set()
