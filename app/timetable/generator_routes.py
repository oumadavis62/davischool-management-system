"""Automatic timetable generator workspace."""
from __future__ import annotations

from html import escape
import json
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.setup import TimetableSetupError
from app.timetable.generator import (
    generate_timetable, generate_advanced_instructional_sessions,
    generate_dated_advanced_sessions,
)


def register_timetable_generator_routes(app, get_db, get_school_obj, module_page):
    from app.timetable.navigation import timetable_workspace
    _base_module_page = module_page
    def module_page(request, title, module, body):
        return _base_module_page(request, title, module, timetable_workspace(request, body))
    def school_for(request):
        if not request.session.get("email") or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
            return None
        return get_school_obj(request)

    def redirect_generator(profile_id=0, run_id=0, message="", error=False):
        parts = []
        if profile_id:
            parts.append("profile_id=" + str(int(profile_id)))
        if run_id:
            parts.append("run_id=" + str(int(run_id)))
        if message:
            parts.append("message=" + quote(str(message)))
        if error:
            parts.append("error=1")
        return RedirectResponse("/app/timetable/automatic" + (("?" + "&".join(parts)) if parts else ""), 303)

    @app.get("/app/timetable/automatic", response_class=HTMLResponse)
    def timetable_automatic_page(request: Request, profile_id: int = 0, run_id: int = 0, message: str = "", error: int = 0):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        school_id = int(school["id"])
        con = get_db()
        cur = con.cursor()
        profiles = cur.execute(
            "SELECT * FROM ds_timetable_profiles WHERE school_id=? ORDER BY academic_year DESC,term,id DESC",
            (school_id,),
        ).fetchall()
        selected = (next((p for p in profiles if int(p["id"]) == int(profile_id)), None) or (profiles[0] if profiles else None))
        days = periods = requirements = rooms = runs = []
        advanced_requirements = 0
        run_detail = None
        if selected:
            pid = int(selected["id"])
            days = cur.execute("SELECT COUNT(*) AS total FROM ds_timetable_days WHERE school_id=? AND profile_id=? AND is_instructional=1", (school_id,pid)).fetchone()["total"]
            periods = cur.execute("SELECT COUNT(*) AS total FROM ds_timetable_periods WHERE school_id=? AND profile_id=? AND period_type='lesson'", (school_id,pid)).fetchone()["total"]
            requirements = cur.execute("SELECT COUNT(*) AS total FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=?", (school_id,pid)).fetchone()["total"]
            advanced_requirements = cur.execute("""SELECT COUNT(*) AS total FROM ds_timetable_scheduling_requirements
                WHERE school_id=? AND profile_id=? AND is_active=1""",
                (school_id,pid)).fetchone()["total"]
            advanced_instructional_requirements = cur.execute("""SELECT COUNT(*) AS total FROM ds_timetable_scheduling_requirements
                WHERE school_id=? AND profile_id=? AND is_active=1 AND schedule_layer='instructional'""",
                (school_id,pid)).fetchone()["total"]
            allocations_count = cur.execute("""SELECT COUNT(*) AS total FROM (SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id FROM teacher_allocations ta JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id WHERE ta.school_id=?) a""", (school_id,)).fetchone()["total"]
            rooms = cur.execute("SELECT COUNT(*) AS total FROM ds_timetable_rooms WHERE school_id=? AND is_active=1", (school_id,)).fetchone()["total"]
            runs = cur.execute(
                "SELECT * FROM ds_timetable_generation_runs WHERE school_id=? AND profile_id=? ORDER BY id DESC LIMIT 12",
                (school_id,pid),
            ).fetchall()
            if run_id:
                run_detail = cur.execute(
                    "SELECT * FROM ds_timetable_generation_runs WHERE id=? AND school_id=? AND profile_id=?",
                    (run_id,school_id,pid),
                ).fetchone()
        con.close()
        esc = lambda value: escape(str(value if value is not None else ""))
        pid = int(selected["id"]) if selected else 0
        notice = f"<div class='ag-alert {'error' if error else 'success'}'>{esc(message)}</div>" if message else ""
        profile_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==pid else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])}</option>"
            for p in profiles
        )
        selector = f"<form method='get' action='/app/timetable/automatic' class='ag-select'><label>Timetable profile</label><select name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>" if profiles else ""
        if not selected:
            body = "<div class='ag-empty'><h2>No timetable profile found</h2><p>Create a profile and configure the school week before automatic generation.</p><a class='ag-btn' href='/app/timetable/setup'>Open Timetable Setup</a></div>"
            return module_page(request, "Automatic Timetabling", "timetable", body)
        read_only = str(selected['status']) != 'draft'
        advanced_action = (
            f"""<form method='post' action='/app/timetable/automatic/generate-advanced'
                onsubmit="return confirm('Generate normalized sessions, including combined classes and teaching teams?')">
                <input type='hidden' name='profile_id' value='{pid}'>
                <button class='ag-btn secondary'>Generate weekly instructional sessions ({int(advanced_instructional_requirements)})</button></form>"""
            if advanced_instructional_requirements and not read_only else ""
        )
        date_range_action = (
            f"""<form method='post' action='/app/timetable/automatic/generate-dated'
                class='ag-date-form'
                onsubmit="return confirm('Generate dated sessions for every active instructional, remedial and activity requirement in this date range?')">
                <input type='hidden' name='profile_id' value='{pid}'>
                <label>From <input type='date' name='start_date' required value='{esc(selected['academic_start_date'] or '')}'
                    min='{esc(selected['academic_start_date'] or '')}' max='{esc(selected['academic_end_date'] or '')}'></label>
                <label>To <input type='date' name='end_date' required value='{esc(selected['academic_end_date'] or selected['academic_start_date'] or '')}'
                    min='{esc(selected['academic_start_date'] or '')}' max='{esc(selected['academic_end_date'] or '')}'></label>
                <button class='ag-btn'>Generate dated timetable</button>
                <p>Uses each actual date's day template, remedial/activity slots, rotation week, teacher availability and shared resource-conflict checks. Maximum range: 366 days.</p>
                </form>"""
            if advanced_requirements and not read_only else ""
        )
        result_html = ""
        if run_detail:
            try:
                summary = json.loads(run_detail["result_summary_json"] or "{}")
            except Exception:
                summary = {}
            status = str(run_detail["status"] or "unknown").lower()
            result_html = f"""<section class='ag-result'><div class='ag-result-head'><div><span class='ag-kicker'>GENERATION RESULT · RUN #{int(run_detail['id'])}</span><h3>{'Timetable generated' if status=='completed' else 'Generation needs attention'}</h3></div><span class='ag-state { 'good' if status=='completed' else 'bad' }'>{esc(status.upper())}</span></div><p>{esc(summary.get('message','No result details available.'))}</p><div class='ag-metrics'><span><b>{esc(summary.get('generated_lessons',0))}</b>Generated lessons</span><span><b>{esc(summary.get('manual_lessons_kept',0))}</b>Manual lessons kept</span><span><b>{esc(summary.get('quality_score','—'))}</b>Quality score</span><span><b>{esc(summary.get('search_nodes',0))}</b>Search steps</span></div></section>"""
        run_rows = "".join(
            f"<tr><td>#{int(r['id'])}</td><td>{esc(r['created_at'])}</td><td><span class='ag-state {'good' if r['status']=='completed' else 'bad'}'>{esc(r['status'])}</span></td><td>{esc(r['engine_version'])}</td><td><a href='/app/timetable/automatic?profile_id={pid}&run_id={int(r['id'])}'>View result</a></td></tr>"
            for r in runs
        ) or "<tr><td colspan='5' class='ag-muted'>No generation runs yet.</td></tr>"
        ready = bool(days and periods and (requirements or advanced_instructional_requirements) and not read_only)
        action_html = (
            f"""<form method='post' action='/app/timetable/automatic/generate' onsubmit="return confirm('Generate a complete timetable using the current setup? Existing manual lessons will be preserved.')"><input type='hidden' name='profile_id' value='{pid}'><button class='ag-btn'>⚡ Generate complete timetable</button></form>"""
            if ready else
            (f"""<div class='ag-warning'>This profile is {esc(selected['status']).replace('_',' ')} and is read-only. Create a new draft revision before generating or changing its timetable.</div><a class='ag-btn secondary' href='/app/timetable/publishing?profile_id={pid}'>Create Revision</a>""" if read_only else
             f"""<div class='ag-warning'>Complete the setup requirements first: add instructional days, teaching periods and a weekly requirement for every current class-subject-teacher allocation.</div><a class='ag-btn secondary' href='/app/timetable/setup?profile_id={pid}'>Complete Setup</a>""")
        )
        body = f"""
        <style>
        .ag-wrap{{max-width:1250px;margin:auto;padding:22px;color:#173d2b}}.ag-hero{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:18px}}.ag-hero h2{{font-size:26px;margin:3px 0 5px}}.ag-hero p{{font-size:13px;color:#64748b;margin:0}}.ag-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}.ag-btn{{display:inline-flex;padding:11px 15px;border:0;border-radius:9px;background:#17633b;color:white;text-decoration:none;font-size:12px;font-weight:800;cursor:pointer}}.ag-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8}}.ag-select{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}}.ag-select label{{font-size:12px;font-weight:800}}.ag-select select{{min-width:280px;padding:10px;border:1px solid #dce7de;border-radius:9px;background:white}}.ag-card,.ag-result,.ag-history{{background:white;border:1px solid #e1ebe3;border-radius:15px;padding:18px;margin-bottom:16px;box-shadow:0 3px 12px #173d2b08}}.ag-card h3,.ag-result h3{{font-size:18px;margin:4px 0;color:#173d2b}}.ag-card p,.ag-result p{{font-size:12px;color:#64748b;line-height:1.6}}.ag-checks{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:16px 0}}.ag-check{{background:#f4f8f4;border:1px solid #e5eee6;border-radius:10px;padding:12px}}.ag-check b{{display:block;font-size:22px;color:#17633b}}.ag-check span{{font-size:10px;color:#64748b}}.ag-warning{{padding:12px;background:#fff7e8;color:#8b5b14;border-radius:9px;font-size:12px;margin:12px 0}}.ag-alert{{padding:11px 14px;border-radius:9px;margin-bottom:12px;font-size:12px;font-weight:700}}.ag-alert.success{{background:#eaf5ec;color:#17633b}}.ag-alert.error{{background:#fff1f0;color:#a12828}}.ag-result-head{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}}.ag-state{{font-size:10px;font-weight:900;padding:5px 9px;border-radius:20px}}.ag-state.good{{background:#eaf5ec;color:#17633b}}.ag-state.bad{{background:#fff1f0;color:#a12828}}.ag-metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:14px}}.ag-metrics span{{background:#f5f8f5;padding:12px;border-radius:9px;color:#64748b;font-size:10px}}.ag-metrics b{{display:block;font-size:22px;color:#173d2b}}.ag-history table{{width:100%;border-collapse:collapse;min-width:500px}}.ag-history th,.ag-history td{{padding:11px;border-bottom:1px solid #edf2ed;text-align:left;font-size:11px}}.ag-history th{{background:#f0f6f1;color:#315b3e}}.ag-history a{{color:#17633b;font-weight:800;text-decoration:none}}.ag-table-scroll{{overflow:auto}}.ag-muted{{text-align:center;color:#94a3a0;padding:18px}}.ag-empty{{padding:30px;background:white;border-radius:14px;text-align:center}}.ag-date-form{{display:flex;gap:10px;align-items:end;flex-wrap:wrap;border-top:1px solid #e7eee8;margin-top:14px;padding-top:14px}}.ag-date-form label{{display:grid;gap:5px;font-size:11px;font-weight:800}}.ag-date-form input{{padding:9px;border:1px solid #dce7de;border-radius:8px;background:#fff}}.ag-date-form p{{flex-basis:100%;margin:0}}@media(max-width:650px){{.ag-wrap{{padding:13px}}.ag-checks,.ag-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ag-hero h2{{font-size:22px}}}}
        </style>
        <div class='ag-wrap'><div class='ag-hero'><div><span class='ag-kicker'>DAVISCHOOL · CONSTRAINT SOLVER</span><h2>Automatic Timetable Generator</h2><p>Generate ordinary lessons, combined classes and co-teaching together in one clash-checked weekly run.</p></div><div style='display:flex;gap:8px;flex-wrap:wrap'><a class='ag-btn secondary' href='/app/timetable/builder?profile_id={pid}'>Manual Builder</a><a class='ag-btn secondary' href='/app/timetable/views?profile_id={pid}'>Timetable Views</a><a class='ag-btn secondary' href='/app/timetable/publishing?profile_id={pid}'>Publishing & Versions</a><a class='ag-btn secondary' href='/app/timetable/setup?profile_id={pid}'>Setup</a></div></div>{notice}{selector}
        <section class='ag-card'><span class='ag-kicker'>GENERATION READINESS</span><h3>{esc(selected['name'])}</h3><p>{esc(selected['academic_year'])} · {esc(selected['term'])}. The generator preserves manual lessons and replaces an earlier automatic timetable only after it finds a complete solution.</p><div class='ag-checks'><div class='ag-check'><b>{int(days)}</b><span>Instructional days</span></div><div class='ag-check'><b>{int(periods)}</b><span>Teaching periods</span></div><div class='ag-check'><b>{int(requirements)}</b><span>Lesson requirements</span></div><div class='ag-check'><b>{int(allocations_count)}</b><span>Current allocations</span></div><div class='ag-check'><b>{int(rooms)}</b><span>Available rooms</span></div></div>
        {action_html}
                </section>{result_html}<section class='ag-history'><span class='ag-kicker'>AUDITABLE GENERATION HISTORY</span><h3>Previous runs</h3><div class='ag-table-scroll'><table><tr><th>Run</th><th>Created</th><th>Status</th><th>Engine</th><th>Result</th></tr>{run_rows}</table></div></section></div>
        """
        return module_page(request, "Automatic Timetabling", "timetable", body)

    @app.post("/app/timetable/automatic/generate-advanced")
    def run_advanced_generation(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            result = generate_advanced_instructional_sessions(
                con, int(school["id"]), profile_id, request.session.get("email", "")
            )
            return redirect_generator(profile_id, message=result.get("message", "Advanced generation completed."),
                                      error=result.get("status") != "completed")
        except TimetableSetupError as exc:
            return redirect_generator(profile_id, message=str(exc), error=True)
        finally:
            con.close()

    @app.post("/app/timetable/automatic/generate-dated")
    def run_dated_generation(request: Request, profile_id: int = Form(...),
                              start_date: str = Form(...), end_date: str = Form(...)):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        from datetime import date
        con = get_db()
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
            if end < start:
                raise TimetableSetupError("The end date must be on or after the start date.")
            if (end - start).days > 365:
                raise TimetableSetupError("Generate no more than 366 calendar days at a time.")
            result = generate_dated_advanced_sessions(
                con, int(school["id"]), profile_id, start.isoformat(), end.isoformat(),
                request.session.get("email", ""),
            )
            message = result.get("message") or (
                str(result.get("generated_sessions", 0)) + " dated sessions generated."
            )
            return redirect_generator(profile_id, message=message,
                                      error=result.get("status") != "completed")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_generator(profile_id, message=str(exc), error=True)
        finally:
            con.close()

    @app.post("/app/timetable/automatic/generate")
    def run_automatic_generation(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            advanced_result = None
            advanced_count = con.execute(
                """SELECT COUNT(*) FROM ds_timetable_scheduling_requirements
                   WHERE school_id=? AND profile_id=? AND is_active=1
                     AND schedule_layer='instructional'""",
                (int(school["id"]), profile_id),
            ).fetchone()[0]
            created_advanced_ids = []
            try:
                if int(advanced_count or 0):
                    advanced_result = generate_advanced_instructional_sessions(
                        con, int(school["id"]), profile_id, request.session.get("email", ""),
                        defer_replacement=True,
                    )
                    created_advanced_ids = list(advanced_result.get("session_ids") or [])
                result = generate_timetable(
                    con, int(school["id"]), profile_id, request.session.get("email", ""),
                    normalized_run_id=(advanced_result or {}).get("run_id"),
                )
                if result.get("status") != "completed":
                    if created_advanced_ids:
                        marks = ",".join("?" for _ in created_advanced_ids)
                        con.execute(f"DELETE FROM ds_timetable_session_classes WHERE session_id IN ({marks})", tuple(created_advanced_ids))
                        con.execute(f"DELETE FROM ds_timetable_session_teachers WHERE session_id IN ({marks})", tuple(created_advanced_ids))
                        con.execute(f"DELETE FROM ds_timetable_session_learners WHERE session_id IN ({marks})", tuple(created_advanced_ids))
                        con.execute(f"DELETE FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND id IN ({marks})",
                                    (int(school["id"]), profile_id, *created_advanced_ids))
                        if advanced_result and advanced_result.get("run_id"):
                            con.execute("UPDATE ds_timetable_generation_runs SET status='failed',finished_at=CURRENT_TIMESTAMP WHERE id=? AND school_id=?",
                                        (int(advanced_result["run_id"]), int(school["id"])))
                        con.commit()
                    return redirect_generator(profile_id, int(result.get("run_id") or 0),
                                              result.get("message", "Generation failed."), True)
                if advanced_result:
                    previous_ids = list(advanced_result.get("previous_session_ids") or [])
                    if previous_ids:
                        marks = ",".join("?" for _ in previous_ids)
                        con.execute(f"DELETE FROM ds_timetable_session_classes WHERE session_id IN ({marks})", tuple(previous_ids))
                        con.execute(f"DELETE FROM ds_timetable_session_teachers WHERE session_id IN ({marks})", tuple(previous_ids))
                        con.execute(f"DELETE FROM ds_timetable_session_learners WHERE session_id IN ({marks})", tuple(previous_ids))
                        con.execute(f"DELETE FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND id IN ({marks})",
                                    (int(school["id"]), profile_id, *previous_ids))
                        con.commit()
                    result["generated_sessions"] = int(advanced_result.get("generated_sessions") or 0)
                    result["message"] = (
                        str(result.get("message") or "Weekly timetable generated.") +
                        " Combined/co-teaching sessions: " +
                        str(result["generated_sessions"]) + "."
                    )
                return redirect_generator(profile_id, int(result.get("run_id") or 0),
                                          result.get("message", "Generation finished."), False)
            except Exception:
                if created_advanced_ids:
                    marks = ",".join("?" for _ in created_advanced_ids)
                    con.execute(f"DELETE FROM ds_timetable_session_classes WHERE session_id IN ({marks})", tuple(created_advanced_ids))
                    con.execute(f"DELETE FROM ds_timetable_session_teachers WHERE session_id IN ({marks})", tuple(created_advanced_ids))
                    con.execute(f"DELETE FROM ds_timetable_session_learners WHERE session_id IN ({marks})", tuple(created_advanced_ids))
                    con.execute(f"DELETE FROM ds_timetable_sessions WHERE school_id=? AND profile_id=? AND id IN ({marks})",
                                (int(school["id"]), profile_id, *created_advanced_ids))
                    if advanced_result and advanced_result.get("run_id"):
                        con.execute("UPDATE ds_timetable_generation_runs SET status='failed',finished_at=CURRENT_TIMESTAMP WHERE id=? AND school_id=?",
                                    (int(advanced_result["run_id"]), int(school["id"])))
                    con.commit()
                raise
        except TimetableSetupError as exc:
            return redirect_generator(profile_id, message=str(exc), error=True)
        finally:
            con.close()
