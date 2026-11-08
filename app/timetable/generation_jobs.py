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

from app.timetable.generator import (
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
        cur = con.execute(
            """INSERT INTO ds_timetable_generation_jobs
               (school_id, profile_id, requested_by, status, stage)
               VALUES (?, ?, ?, 'queued', 'queued')""",
            (int(school_id), int(profile_id), str(requested_by or "")),
        )
        job_id = int(cur.lastrowid)
        con.commit()
        return job_id
    finally:
        con.close()


def get_generation_job(get_db: Callable, school_id: int, job_id: int):
    con = get_db()
    try:
        ensure_generation_jobs_table(con)
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
            if hasattr(value, "isoformat"):
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


def _execute_job(get_db, job):
    job_id = int(job["id"])
    school_id = int(job["school_id"])
    profile_id = int(job["profile_id"])
    email = str(job["requested_by"] or "")
    con = get_db()
    advanced_result = None
    created_advanced_ids = []
    try:
        _set_job(get_db, job_id, stage="checking requirements")
        advanced_count = con.execute(
            """SELECT COUNT(*) FROM ds_timetable_scheduling_requirements
               WHERE school_id=? AND profile_id=? AND is_active=1
                 AND schedule_layer='instructional'""",
            (school_id, profile_id),
        ).fetchone()[0]
        if int(advanced_count or 0):
            _set_job(get_db, job_id, stage="generating combined and co-teaching lessons")
            advanced_result = generate_advanced_instructional_sessions(
                con, school_id, profile_id, email, defer_replacement=True
            )
            created_advanced_ids = list(advanced_result.get("session_ids") or [])

        _set_job(get_db, job_id, stage="generating ordinary lessons")
        result = generate_timetable(
            con, school_id, profile_id, email,
            normalized_run_id=(advanced_result or {}).get("run_id"),
        )
        if result.get("status") != "completed":
            _delete_sessions(con, school_id, profile_id, created_advanced_ids)
            if advanced_result and advanced_result.get("run_id"):
                con.execute(
                    """UPDATE ds_timetable_generation_runs
                       SET status='failed', finished_at=CURRENT_TIMESTAMP
                       WHERE id=? AND school_id=?""",
                    (int(advanced_result["run_id"]), school_id),
                )
            con.commit()
            _set_job(
                get_db, job_id, status="failed", stage="failed",
                result_run_id=int(result.get("run_id") or 0) or None,
                message=str(result.get("message") or "The solver could not find a complete timetable."),
            )
            con.execute("UPDATE ds_timetable_generation_jobs SET finished_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
            con.commit()
            return

        if advanced_result:
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
               SET finished_at=CURRENT_TIMESTAMP WHERE id=?""", (job_id,)
        )
        con.commit()
    except Exception as exc:
        log.exception(
            "Background timetable generation failed (job_id=%s school_id=%s profile_id=%s)",
            job_id, school_id, profile_id,
        )
        try:
            con.rollback()
            _delete_sessions(con, school_id, profile_id, created_advanced_ids)
            if advanced_result and advanced_result.get("run_id"):
                con.execute(
                    """UPDATE ds_timetable_generation_runs
                       SET status='failed', finished_at=CURRENT_TIMESTAMP
                       WHERE id=? AND school_id=?""",
                    (int(advanced_result["run_id"]), school_id),
                )
            con.commit()
        except Exception:
            con.rollback()
        _set_job(
            get_db, job_id, status="failed", stage="failed",
            message="Generation failed: " + str(exc)[:700],
        )
        con.execute(
            "UPDATE ds_timetable_generation_jobs SET finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (job_id,),
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
                       SET status='running', stage='starting', started_at=CURRENT_TIMESTAMP
                       WHERE id=? AND status='queued'""",
                    (int(row["id"]),),
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
            _execute_job(get_db, job)
        else:
            _STOP.wait(2.0)


def start_generation_worker(get_db) -> None:
    global _worker_thread
    setup = get_db()
    try:
        ensure_generation_jobs_table(setup)
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
