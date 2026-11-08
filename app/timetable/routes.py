"""Admin-facing configuration workspace for the DaviSchool timetable v2 engine."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.setup import (
    TimetableSetupError,
    create_profile,
    save_day,
    save_period,
    save_break,
    save_calendar_exception,
    save_room,
    save_teacher_availability,
    save_class_requirement,
    save_subject_requirements,
    save_class_limits,
    _profile,
)
from app.timetable.advanced_setup import save_timetable_constraint


def register_timetable_setup_routes(app, get_db, get_school_obj, module_page):
    from app.timetable.navigation import timetable_workspace
    _base_module_page = module_page
    def module_page(request, title, module, body):
        return _base_module_page(request, title, module, timetable_workspace(request, body))
    def school_for(request):
        if not request.session.get("email") or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
            return None
        return get_school_obj(request)

    def redirect_setup(profile_id=0, message="", error=False):
        parts = []
        if profile_id:
            parts.append("profile_id=" + str(int(profile_id)))
        if message:
            parts.append("message=" + quote(str(message)))
        if error:
            parts.append("error=1")
        return RedirectResponse("/app/timetable/setup" + (("?" + "&".join(parts)) if parts else ""), 303)

    @app.get("/app/timetable", response_class=HTMLResponse)
    def timetable_home(request: Request, profile_id: int = 0):
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
        selected = next((p for p in profiles if int(p["id"]) == int(profile_id)), None) or (profiles[0] if profiles else None)
        stats = {"days": 0, "periods": 0, "rooms": 0, "requirements": 0, "lessons": 0}
        if selected:
            pid = int(selected["id"])
            stats["days"] = int(cur.execute("SELECT COUNT(*) FROM ds_timetable_days WHERE school_id=? AND profile_id=? AND is_instructional=1", (school_id,pid)).fetchone()[0] or 0)
            stats["periods"] = int(cur.execute("SELECT COUNT(*) FROM ds_timetable_periods WHERE school_id=? AND profile_id=? AND period_type='lesson'", (school_id,pid)).fetchone()[0] or 0)
            stats["rooms"] = int(cur.execute("SELECT COUNT(*) FROM ds_timetable_rooms WHERE school_id=? AND is_active=1", (school_id,)).fetchone()[0] or 0)
            stats["requirements"] = int(cur.execute("SELECT COUNT(*) FROM ds_timetable_class_requirements WHERE school_id=? AND profile_id=?", (school_id,pid)).fetchone()[0] or 0)
            stats["lessons"] = int(cur.execute("SELECT COUNT(*) FROM ds_timetable_lessons WHERE school_id=? AND profile_id=? AND status='scheduled'", (school_id,pid)).fetchone()[0] or 0)
        con.close()

        esc = lambda value: escape(str(value if value is not None else ""))
        if selected:
            pid = int(selected["id"])
            profile_options = "".join(
                f"<option value='{int(p['id'])}' {'selected' if int(p['id']) == pid else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])}</option>"
                for p in profiles
            )
            profile_control = f"<form class='tt-home-profile' method='get' action='/app/timetable'><label for='tt-home-profile'>Working timetable</label><select id='tt-home-profile' name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>"
            status = esc(selected["status"]).upper()
            profile_name = esc(selected["name"])
            profile_meta = f"{esc(selected['academic_year'])} · {esc(selected['term'])}"
            progress_items = [
                ("School days", stats["days"], "Define the instructional week", "/app/timetable/setup"),
                ("Lesson periods", stats["periods"], "Set lesson times and durations", "/app/timetable/setup"),
                ("Lesson requirements", stats["requirements"], "Connect classes, subjects and teachers", "/app/timetable/setup"),
                ("Scheduled lessons", stats["lessons"], "Build and review the weekly plan", "/app/timetable/builder"),
            ]
            progress_html = "".join(
                f"<a class='tt-home-progress' href='{url}'><span class='tt-home-progress-icon'>{idx:02d}</span><span><b>{label}</b><small>{hint}</small></span><strong>{count}</strong></a>"
                for idx,(label,count,hint,url) in enumerate(progress_items,1)
            )
            builder_href = f"/app/timetable/builder?profile_id={pid}"
            setup_href = f"/app/timetable/setup?profile_id={pid}"
            views_href = f"/app/timetable/views?profile_id={pid}"
            auto_href = f"/app/timetable/automatic?profile_id={pid}"
            publish_href = f"/app/timetable/publishing?profile_id={pid}"
            profile_panel = f"""
              <section class='tt-home-profile-card'>
                <div class='tt-home-profile-top'><div><span class='tt-home-eyebrow'>CURRENT TIMETABLE PROFILE</span><h2>{profile_name}</h2><p>{profile_meta} <i></i> <span class='tt-home-status'>{status}</span></p></div><a class='tt-home-outline' href='{setup_href}'>Configure profile <span>↗</span></a></div>
                <div class='tt-home-metrics'>
                  <div><span>School days</span><b>{stats['days']}</b></div><div><span>Lesson periods</span><b>{stats['periods']}</b></div><div><span>Active rooms</span><b>{stats['rooms']}</b></div><div><span>Scheduled lessons</span><b>{stats['lessons']}</b></div>
                </div>
              </section>
              <div class='tt-home-columns'>
                <section class='tt-home-panel'><div class='tt-home-panel-head'><div><span class='tt-home-eyebrow'>WORKSPACE CHECKLIST</span><h3>Build your timetable</h3></div><a href='{setup_href}'>Open setup ↗</a></div>{progress_html}</section>
                <section class='tt-home-panel tt-home-actions'><span class='tt-home-eyebrow'>QUICK ACCESS</span><h3>What would you like to do?</h3>
                  <a class='tt-home-action tt-home-action-primary' href='{builder_href}'><span class='tt-home-action-icon'>▦</span><span><b>Open timetable builder</b><small>Create, adjust and arrange lessons</small></span><em>→</em></a>
                  <a class='tt-home-action' href='{auto_href}'><span class='tt-home-action-icon'>✳</span><span><b>Generate automatically</b><small>Build a schedule using your constraints</small></span><em>→</em></a>
                  <a class='tt-home-action' href='/app/timetable/constraints?profile_id={pid}'><span class='tt-home-action-icon'>⌁</span><span><b>Scheduling constraints</b><small>Set subject, teacher, class and time restrictions</small></span><em>→</em></a>
                  <a class='tt-home-action' href='{views_href}'><span class='tt-home-action-icon'>▤</span><span><b>View timetables</b><small>School, class, teacher and room views</small></span><em>→</em></a>
                  <a class='tt-home-action' href='{publish_href}'><span class='tt-home-action-icon'>⇧</span><span><b>Review and publish</b><small>Manage timetable release and revisions</small></span><em>→</em></a>
                </section>
              </div>"""
        else:
            profile_control = ""
            profile_panel = """
              <section class='tt-home-empty'>
                <div class='tt-home-empty-icon'>▦</div><span class='tt-home-eyebrow'>GET STARTED</span>
                <h2>Create your first timetable profile</h2>
                <p>Start by choosing the academic year and term. Then configure school days, lesson periods, rooms and teaching requirements before building your timetable.</p>
                <a class='tt-home-primary' href='/app/timetable/setup'>Create timetable profile <span>→</span></a>
              </section>"""
        body = f"""
        <style>
          .tt-home{{color:#173b31;max-width:1500px;margin:0 auto;padding:8px 0 34px}}
          .tt-home *{{box-sizing:border-box}}
          .tt-home-hero{{position:relative;overflow:hidden;border:1px solid #e2eaf2;border-radius:22px;padding:30px 34px;background:linear-gradient(110deg,#f7f9fc 0%,#f1f6fa 58%,#edf5f4 100%);color:#18324b;display:flex;align-items:center;justify-content:space-between;gap:24px;box-shadow:0 10px 28px rgba(36,62,86,.055)}}
          .tt-home-hero:after{{content:'';position:absolute;width:250px;height:250px;border:1px solid rgba(89,132,164,.13);border-radius:50%;right:8%;top:-155px;box-shadow:0 0 0 28px rgba(89,132,164,.035),0 0 0 58px rgba(89,132,164,.025)}}
          .tt-home-hero-copy{{position:relative;z-index:1}}.tt-home-eyebrow{{font-size:10px;letter-spacing:1.6px;font-weight:800;color:#66839a;display:block}}
          .tt-home-hero .tt-home-eyebrow{{color:#68879d}}.tt-home-hero h1{{font-size:clamp(25px,3vw,34px);line-height:1.15;margin:9px 0 8px;color:#1d354d;font-weight:800;letter-spacing:-.7px}}
          .tt-home-hero p{{margin:0;color:#64788a;font-size:13px;max-width:560px;line-height:1.65}}
          .tt-home-hero-mark{{position:relative;z-index:1;width:94px;height:94px;border-radius:25px;background:#fff;border:1px solid #dce8f0;color:#3d7895;display:grid;place-items:center;font-size:42px;flex:none;box-shadow:0 8px 22px rgba(47,91,120,.08)}}
          .tt-home-profile{{display:flex;align-items:center;justify-content:flex-end;gap:12px;margin:18px 2px 14px}}.tt-home-profile label{{font-size:12px;color:#61766d;font-weight:700}}.tt-home-profile select{{min-width:250px;max-width:100%;padding:10px 13px;border:1px solid #dce7e0;border-radius:10px;background:#fff;color:#234b3b;font-weight:650}}
          .tt-home-profile-card,.tt-home-panel,.tt-home-empty{{background:#fff;border:1px solid #e3ece6;border-radius:18px;box-shadow:0 5px 18px rgba(24,67,47,.045)}}
          .tt-home-profile-card{{padding:23px 25px;margin-bottom:18px}}.tt-home-profile-top{{display:flex;align-items:center;justify-content:space-between;gap:16px}}.tt-home-profile-top h2{{font-size:22px;margin:6px 0;color:#183e30}}.tt-home-profile-top p{{font-size:12px;color:#72857a;margin:0}}.tt-home-profile-top p i{{display:inline-block;width:4px;height:4px;border-radius:50%;background:#a6b7ad;margin:0 8px 2px}}
          .tt-home-status{{font-size:10px;font-weight:800;letter-spacing:.7px;color:#18734e;background:#e8f5ed;padding:5px 9px;border-radius:20px}}.tt-home-outline{{text-decoration:none!important;border:1px solid #dce8e0;border-radius:9px;padding:9px 13px;color:#236348!important;font-size:12px;font-weight:750;white-space:nowrap}}
          .tt-home-metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:22px}}.tt-home-metrics div{{padding:13px 15px;background:#f5f9f6;border-radius:12px;display:flex;align-items:center;justify-content:space-between;gap:8px}}.tt-home-metrics span{{font-size:11px;color:#6c8175;font-weight:650}}.tt-home-metrics b{{font-size:22px;color:#1d5b40}}
          .tt-home-columns{{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr);gap:20px;align-items:stretch}}.tt-home-panel{{padding:25px;min-width:0;border:1px solid #e4eaf0;border-radius:20px;box-shadow:0 8px 24px rgba(35,57,78,.045)}}.tt-home-panel:first-child{{background:#fff}}.tt-home-panel:last-child{{background:#f7f9fc;border-color:#e2e9f1}}.tt-home-panel-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}}.tt-home-panel h3{{font-size:19px;line-height:1.25;margin:6px 0 0;color:#20384f;letter-spacing:-.25px}}.tt-home-panel-head>a{{font-size:11px;color:#397895;text-decoration:none;font-weight:800;white-space:nowrap;padding:8px 11px;border:1px solid #dce8f0;border-radius:9px;background:#fff}}.tt-home-panel-head>a:hover{{background:#edf5f9;border-color:#c7dce8}}
          .tt-home-progress{{display:flex;align-items:center;gap:13px;padding:14px 13px;margin-top:9px;border:1px solid #e9eef3;border-radius:13px;background:#fbfcfd;text-decoration:none!important;color:inherit!important;transition:transform .16s,border-color .16s,background .16s,box-shadow .16s}}.tt-home-progress:hover{{transform:translateX(2px);border-color:#cbdde9;background:#f5f9fc;box-shadow:0 4px 12px rgba(42,78,103,.045)}}.tt-home-progress-icon{{width:36px;height:36px;border-radius:12px;background:#eaf2f8;color:#3d7895;display:grid;place-items:center;font-size:10px;font-weight:850;flex:none}}.tt-home-progress span:nth-child(2){{display:flex;flex-direction:column;gap:4px;min-width:0}}.tt-home-progress b{{font-size:12px;color:#29435a}}.tt-home-progress small{{font-size:10px;color:#8291a0;line-height:1.35}}.tt-home-progress strong{{margin-left:auto;min-width:34px;height:30px;padding:0 8px;border-radius:9px;background:#edf3f8;display:grid;place-items:center;font-size:14px;color:#3b718d}}
          .tt-home-actions{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-content:start;gap:11px}}.tt-home-actions>.tt-home-eyebrow,.tt-home-actions>h3{{grid-column:1/-1}}.tt-home-actions h3{{margin-bottom:5px}}.tt-home-action{{position:relative;display:flex;align-items:flex-start;gap:12px;min-height:112px;padding:16px 14px;border:1px solid #e3eaf1;border-radius:15px;margin:0;background:#fff;text-decoration:none!important;color:#29435a!important;transition:transform .17s,border-color .17s,box-shadow .17s}}.tt-home-action:hover{{transform:translateY(-3px);border-color:#bfd4e2;box-shadow:0 9px 20px rgba(40,75,99,.08)}}.tt-home-action-primary{{grid-column:1/-1;min-height:88px;align-items:center;background:#eef5fa;border-color:#d8e6ef}}.tt-home-action-icon{{width:40px;height:40px;border-radius:13px;background:#e8f0f6;color:#3b7895;display:grid;place-items:center;font-size:20px;flex:none}}.tt-home-action-primary .tt-home-action-icon{{background:#dcebf4;color:#326f8d}}.tt-home-action>span:nth-child(2){{display:flex;flex-direction:column;gap:6px;min-width:0;padding-top:2px}}.tt-home-action b{{font-size:12px;line-height:1.35;color:#29445b}}.tt-home-action small{{font-size:10px;line-height:1.45;color:#8291a0}}.tt-home-action em{{position:absolute;right:13px;bottom:10px;font-style:normal;color:#5b8ca5;font-size:17px}}
          .tt-home-empty{{text-align:center;padding:54px 25px;margin-top:18px}}.tt-home-empty-icon{{width:66px;height:66px;border-radius:20px;background:#eaf4ed;color:#24704b;display:grid;place-items:center;margin:0 auto 18px;font-size:30px}}.tt-home-empty h2{{font-size:24px;color:#1b4935;margin:8px 0}}.tt-home-empty p{{max-width:600px;margin:0 auto 22px;color:#718379;font-size:13px;line-height:1.7}}.tt-home-primary{{display:inline-flex;gap:12px;align-items:center;background:#176344;color:white!important;text-decoration:none!important;padding:12px 18px;border-radius:10px;font-weight:750;font-size:12px}}
          @media(max-width:800px){{.tt-home-hero{{padding:25px 22px}}.tt-home-hero-mark{{width:68px;height:68px;font-size:30px;border-radius:19px}}.tt-home-columns{{grid-template-columns:1fr}}.tt-home-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tt-home-panel{{padding:22px 20px}}}}
          @media(max-width:480px){{.tt-home-hero-mark{{display:none}}.tt-home-profile{{align-items:stretch;flex-direction:column;gap:7px}}.tt-home-profile select{{width:100%;min-width:0}}.tt-home-profile-card,.tt-home-panel{{padding:18px 16px}}.tt-home-profile-top{{align-items:flex-start;flex-direction:column}}.tt-home-metrics div{{padding:11px}}.tt-home-metrics span{{font-size:10px}}.tt-home-empty{{padding:38px 18px}}.tt-home-panel-head{{align-items:flex-start;flex-direction:column;gap:9px}}.tt-home-progress{{padding:12px 10px}}.tt-home-action{{min-height:96px;padding:13px 11px}}.tt-home-actions{{grid-template-columns:1fr}}.tt-home-actions>.tt-home-eyebrow,.tt-home-actions>h3,.tt-home-action-primary{{grid-column:1}}}}
        </style>
        <main class='tt-home'>
          <section class='tt-home-hero'><div class='tt-home-hero-copy'><span class='tt-home-eyebrow'>DAVISCHOOL · ACADEMIC OPERATIONS</span><h1>Smart Timetable</h1><p>Plan, organise and publish a balanced school timetable. Manage teaching requirements, build schedules and keep every class and teacher in sync.</p></div><div class='tt-home-hero-mark'>▦</div></section>
          {profile_control}
          {profile_panel}
        </main>"""
        return module_page(request, "Smart Timetable", "timetable", body)

    @app.get("/app/timetable/setup", response_class=HTMLResponse)
    def timetable_setup_page(request: Request, profile_id: int = 0, message: str = "", error: int = 0):
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
        # Prefer the explicitly requested profile. On a plain setup-page visit,
        # prefer an editable draft instead of silently landing on an older
        # published/archived profile (which intentionally has no setup forms).
        selected = next((p for p in profiles if profile_id and int(p["id"]) == int(profile_id)), None)
        if selected is None:
            selected = next((p for p in profiles if str(p["status"] or "draft").strip().lower() == "draft"), None)
        if selected is None and profiles:
            selected = profiles[0]
        selected_status = str(selected["status"] or "draft").strip().lower() if selected else ""
        has_draft_profile = any(str(p["status"] or "draft").strip().lower() == "draft" for p in profiles)
        days = periods = breaks = calendar_events = rooms = teachers = allocations = availability = requirements = class_limits = class_records = []
        if selected:
            pid = int(selected["id"])
            days = cur.execute("SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? ORDER BY day_order,id", (school_id,pid)).fetchall()
            periods = cur.execute("SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id", (school_id,pid)).fetchall()
            breaks = cur.execute("SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=? ORDER BY break_no,id", (school_id,pid)).fetchall()
            # Every positive gap between consecutive configured periods is a break candidate.
            ordered_periods = sorted(periods, key=lambda p: (str(p["start_time"]), int(p["period_no"])))
            selected_gap_keys = {(str(b["start_time"]), str(b["end_time"])) for b in breaks}
            break_candidates = []
            for previous, following in zip(ordered_periods, ordered_periods[1:]):
                gap_start, gap_end = str(previous["end_time"]), str(following["start_time"])
                if gap_start < gap_end:
                    break_candidates.append({
                        "start_time": gap_start, "end_time": gap_end,
                        "label": f"Gap after {previous['label']}",
                        "selected": (gap_start, gap_end) in selected_gap_keys,
                    })

            calendar_events = cur.execute("SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=? ORDER BY exception_date,label", (school_id,pid)).fetchall()
            rooms = cur.execute("SELECT * FROM ds_timetable_rooms WHERE school_id=? AND is_active=1 ORDER BY name", (school_id,)).fetchall()
            teachers = cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
            class_records = cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream", (school_id,)).fetchall()
            allocations = cur.execute(
                """SELECT DISTINCT ta.class_id,ta.subject_id,ta.teacher_id,c.name class_name,c.stream,
                          s.name subject_name,t.name teacher_name
                   FROM teacher_allocations ta
                   JOIN classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
                   JOIN subjects s ON s.id=ta.subject_id AND s.school_id=ta.school_id
                   JOIN teachers t ON t.id=ta.teacher_id AND t.school_id=ta.school_id
                   WHERE ta.school_id=? ORDER BY c.name,c.stream,s.name,t.name""",
                (school_id,),
            ).fetchall()
            availability = cur.execute(
                """SELECT a.*,t.name teacher_name,d.day_name,p.label period_label
                   FROM ds_timetable_teacher_availability a
                   JOIN teachers t ON t.id=a.teacher_id AND t.school_id=a.school_id
                   JOIN ds_timetable_days d ON d.id=a.day_id AND d.profile_id=a.profile_id
                   JOIN ds_timetable_periods p ON p.id=a.period_id AND p.profile_id=a.profile_id
                   WHERE a.school_id=? AND a.profile_id=? AND a.availability IN ('fallback','unavailable') ORDER BY d.day_order,p.period_no,t.name""",
                (school_id,pid),
            ).fetchall()
            subjects = cur.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
            subject_availability = cur.execute(
                """SELECT a.*,s.name subject_name,d.day_name,p.label period_label
                   FROM ds_timetable_subject_availability a
                   JOIN subjects s ON s.id=a.subject_id AND s.school_id=a.school_id
                   JOIN ds_timetable_days d ON d.id=a.day_id AND d.profile_id=a.profile_id
                   JOIN ds_timetable_periods p ON p.id=a.period_id AND p.profile_id=a.profile_id
                   WHERE a.school_id=? AND a.profile_id=? ORDER BY d.day_order,p.period_no,s.name""",
                (school_id,pid),
            ).fetchall()
            requirements = cur.execute(
                """SELECT r.*,c.name class_name,c.stream,s.name subject_name,t.name teacher_name
                   FROM ds_timetable_class_requirements r
                   JOIN classes c ON c.id=r.class_id AND c.school_id=r.school_id
                   JOIN subjects s ON s.id=r.subject_id AND s.school_id=r.school_id
                   JOIN teachers t ON t.id=r.teacher_id AND t.school_id=r.school_id
                   WHERE r.school_id=? AND r.profile_id=? ORDER BY c.name,c.stream,s.name""",
                (school_id,pid),
            ).fetchall()
            class_limits = cur.execute(
                """SELECT l.*,c.name class_name,c.stream
                   FROM ds_timetable_class_limits l
                   JOIN classes c ON c.id=l.class_id AND c.school_id=l.school_id
                   WHERE l.school_id=? AND l.profile_id=? ORDER BY c.name,c.stream""",
                (school_id,pid),
            ).fetchall()
        con.close()

        esc = lambda value: escape(str(value if value is not None else ""))
        profile_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==int(selected['id']) else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])} ({esc(p['status'])})</option>"
            for p in profiles
        )
        notice = f"<div class='tt-alert {'error' if error else 'success'}'>{esc(message)}</div>" if message else ""
        pid = int(selected["id"]) if selected else 0
        hidden = f"<input type='hidden' name='profile_id' value='{pid}'>"
        selector = f"<form method='get' action='/app/timetable/setup' class='tt-select'><label for='profile_id'>Timetable profile</label><select id='profile_id' name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>" if profiles else ""
        profile_summary = (
            f"<div class='tt-profile'><div><span class='tt-kicker'>ACTIVE CONFIGURATION</span><h2>{esc(selected['name'])}</h2><p>{esc(selected['academic_year'])} · {esc(selected['term'])} · {esc(selected['academic_start_date'] or 'Start date not set')} – {esc(selected['academic_end_date'] or 'End date not set')} · <span class='tt-status'>{esc(selected_status).upper()}</span></p></div><div class='tt-stats'><span><b>{len(days)}</b>Days</span><span><b>{len(periods)}</b>Periods</span><span><b>{len(rooms)}</b>Rooms</span></div></div>"
            if selected else "<div class='tt-empty'><b>No timetable configuration yet</b><p>Create an academic-year and term profile to begin.</p></div>"
        )
        day_rows = "".join(
            f"<tr><td>{esc(d['day_order'])}</td><td><b>{esc(d['day_name'])}</b></td><td>{esc(d['day_code'])}</td><td>{'Instructional' if d['is_instructional'] else 'Non-instructional'}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/day' class='tt-form compact'>{hidden}<input type='hidden' name='day_code' value='{esc(d['day_code'])}'><label>Name<input name='day_name' value='{esc(d['day_name'])}' required></label><label>Order<input type='number' min='1' max='7' name='day_order' value='{int(d['day_order'])}' required></label><label class='tt-check'><input type='checkbox' name='instructional' value='1' {'checked' if d['is_instructional'] else ''}> Instructional</label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this school day?&quot;)'>{hidden}<input type='hidden' name='kind' value='day'><input type='hidden' name='row_id' value='{int(d['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>" for d in days
        ) or "<tr><td colspan='5' class='tt-muted'>No school days configured.</td></tr>"
        period_rows = "".join(
            f"<tr><td>{esc(p['period_no'])}</td><td><b>{esc(p['label'])}</b></td><td>{esc(p['start_time'])}–{esc(p['end_time'])}</td><td>{esc(p['duration_minutes'])} min</td><td>{esc(p['period_type'])}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/period' class='tt-form compact'>{hidden}<input type='hidden' name='period_no' value='{int(p['period_no'])}'><label>Label<input name='label' value='{esc(p['label'])}' required></label><label>Start<input type='time' name='start_time' value='{esc(p['start_time'])}' required></label><label>End<input type='time' name='end_time' value='{esc(p['end_time'])}' required></label><label>Type<select name='period_type'><option value='lesson' {'selected' if p['period_type']=='lesson' else ''}>Lesson</option><option value='study' {'selected' if p['period_type']=='study' else ''}>Study</option><option value='assembly' {'selected' if p['period_type']=='assembly' else ''}>Assembly</option></select></label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this period? Existing linked timetable data may prevent deletion.&quot;)'>{hidden}<input type='hidden' name='kind' value='period'><input type='hidden' name='row_id' value='{int(p['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>" for p in periods
        ) or "<tr><td colspan='6' class='tt-muted'>No periods configured.</td></tr>"
        break_rows = "".join(
            f"<tr><td>{esc(b['break_no'])}</td><td><b>{esc(b['label'])}</b></td><td>{esc(b['start_time'])}–{esc(b['end_time'])}</td><td>{esc(b['applies_to'])}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/break' class='tt-form compact'>{hidden}<input type='hidden' name='break_no' value='{int(b['break_no'])}'><label>Name<input name='label' value='{esc(b['label'])}' required></label><label>Start<input type='time' name='start_time' value='{esc(b['start_time'])}' required></label><label>End<input type='time' name='end_time' value='{esc(b['end_time'])}' required></label><label>Scope<select name='applies_to'><option value='all' {'selected' if b['applies_to']=='all' else ''}>All</option><option value='selected' {'selected' if b['applies_to']=='selected' else ''}>Selected</option></select></label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this break?&quot;)'>{hidden}<input type='hidden' name='kind' value='break'><input type='hidden' name='row_id' value='{int(b['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>" for b in breaks
        ) or "<tr><td colspan='5' class='tt-muted'>No breaks configured.</td></tr>"
        def render_break_candidate_row(g):
            selected_break = next(
                (b for b in breaks if str(b["start_time"]) == str(g["start_time"]) and str(b["end_time"]) == str(g["end_time"])),
                None,
            )
            if selected_break:
                actions = (
                    "<div class='tt-break-actions' style='display:flex;align-items:center;justify-content:flex-start;gap:8px;flex-wrap:wrap;min-width:180px'>"
                    + "<details class='tt-break-edit'><summary class='tt-btn' style='cursor:pointer;list-style:none;white-space:nowrap'>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/break' class='tt-form compact' style='min-width:230px;margin-top:8px'>"
                    + hidden
                    + f"<input type='hidden' name='break_no' value='{int(selected_break['break_no'])}'>"
                    + f"<label>Name<input name='label' value='{esc(selected_break['label'])}' required></label>"
                    + f"<label>Start<input type='time' name='start_time' value='{esc(selected_break['start_time'])}' required></label>"
                    + f"<label>End<input type='time' name='end_time' value='{esc(selected_break['end_time'])}' required></label>"
                    + f"<label>Scope<select name='applies_to'><option value='all' {'selected' if selected_break['applies_to']=='all' else ''}>All</option><option value='selected' {'selected' if selected_break['applies_to']=='selected' else ''}>Selected</option></select></label>"
                    + "<button class='tt-btn'>Save changes</button></form></details>"
                    + "<form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' style='margin:0' onsubmit='return confirm(&quot;Delete this selected break?&quot;)'>"
                    + hidden
                    + f"<input type='hidden' name='kind' value='break'><input type='hidden' name='row_id' value='{int(selected_break['id'])}'>"
                    + "<button class='tt-btn danger' style='white-space:nowrap'>Delete</button></form></div>"
                )
            else:
                actions = (
                    "<form method='post' data-native-post='true' action='/app/timetable/setup/break-gap' style='display:flex;align-items:flex-end;gap:8px;flex-wrap:wrap;margin:0;min-width:220px'>"
                    + hidden
                    + "<input type='hidden' name='start_time' value='" + esc(g["start_time"]) + "'>"
                    + "<input type='hidden' name='end_time' value='" + esc(g["end_time"]) + "'>"
                    + "<label style='margin:0;min-width:130px;flex:1'>Break name<input name='label' required placeholder='e.g. Tea break'></label>"
                    + "<button class='tt-btn' style='white-space:nowrap'>Select gap</button></form>"
                )
            display_label = selected_break["label"] if selected_break else g["label"]
            return (
                f"<tr><td><b>{esc(display_label)}</b></td><td>{esc(g['start_time'])}–{esc(g['end_time'])}</td>"
                + f"<td>{'Selected' if selected_break else 'Available'}</td><td style='min-width:220px;vertical-align:middle'>{actions}</td></tr>"
            )
        break_candidate_rows = "".join(render_break_candidate_row(g) for g in break_candidates) or "<tr><td colspan='4' class='tt-muted'>No gaps detected. Adjust period times to create a gap.</td></tr>"

        calendar_rows = "".join(
            f"<tr><td>{esc(e['exception_date'])}</td><td><b>{esc(e['label'])}</b></td><td>{esc(e['exception_type'])}</td><td>{'Instructional' if e['is_instructional'] else 'Non-instructional'}</td><td>{esc(e['notes'] or '—')}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/calendar-event' class='tt-form compact'>{hidden}<input type='hidden' name='exception_date' value='{esc(e['exception_date'])}'><input type='hidden' name='label' value='{esc(e['label'])}'><label>Type<select name='exception_type'><option value='holiday' {'selected' if e['exception_type']=='holiday' else ''}>Holiday</option><option value='school_closure' {'selected' if e['exception_type']=='school_closure' else ''}>School closure</option><option value='special_instructional_day' {'selected' if e['exception_type']=='special_instructional_day' else ''}>Special instructional day</option><option value='event' {'selected' if e['exception_type']=='event' else ''}>Event</option></select></label><label>Notes<input name='notes' value='{esc(e['notes'] or '')}'></label><label class='tt-check'><input type='checkbox' name='instructional' value='1' {'checked' if e['is_instructional'] else ''}> Instructional</label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this calendar entry?&quot;)'>{hidden}<input type='hidden' name='kind' value='calendar'><input type='hidden' name='row_id' value='{int(e['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>" for e in calendar_events
        ) or "<tr><td colspan='6' class='tt-muted'>No calendar exceptions configured.</td></tr>"
        def room_type_options_for(room_type):
            return "".join(
                f"<option value='{v}' {'selected' if room_type==v else ''}>{v.title()}</option>"
                for v in ('classroom','laboratory','library','hall','workshop','sports','other')
            )
        room_rows = "".join(
            f"<tr><td><b>{esc(r['room_code'])}</b></td><td>{esc(r['name'])}</td><td>{esc(r['room_type'])}</td><td>{esc(r['capacity'] or '—')}</td><td>{esc(r['equipment'] or '—')}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/room' class='tt-form compact'>{hidden}<input type='hidden' name='room_code' value='{esc(r['room_code'])}'><label>Name<input name='name' value='{esc(r['name'])}' required></label><label>Type<select name='room_type'>{room_type_options_for(r['room_type'])}</select></label><label>Capacity<input type='number' min='1' name='capacity' value='{esc(r['capacity'] or '')}'></label><label class='wide'>Description<input name='description' value='{esc(r['description'] or '')}'></label><label class='wide'>Equipment / resources<input name='equipment' value='{esc(r['equipment'] or '')}'></label><label class='wide'>Suitable for<input name='suitable_for' value='{esc(r['suitable_for'] or '')}'></label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this room? It may be blocked if assigned to timetable sessions.&quot;)'>{hidden}<input type='hidden' name='kind' value='room'><input type='hidden' name='row_id' value='{int(r['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>" for r in rooms
        ) or "<tr><td colspan='5' class='tt-muted'>No rooms configured.</td></tr>"
        day_opts = "".join(f"<option value='{int(d['id'])}'>{esc(d['day_name'])}</option>" for d in days)
        period_opts = "".join(f"<option value='{int(p['id'])}'>{esc(p['label'])} ({esc(p['start_time'])}–{esc(p['end_time'])})</option>" for p in periods)
        teacher_opts = "".join(f"<option value='{int(t['id'])}'>{esc(t['name'])}</option>" for t in teachers)
        subject_choices = {int(a["subject_id"]): str(a["subject_name"]) for a in allocations}
        subject_opts = "".join(f"<label class='tt-check'><input type='checkbox' name='subject_ids' value='{subject_id}'> {esc(subject_name)}</label>" for subject_id, subject_name in sorted(subject_choices.items(), key=lambda item: item[1].lower()))
        availability_status = {(int(a["teacher_id"]), int(a["day_id"]), int(a["period_id"])): str(a["availability"] or "") for a in availability}
        matrix_teacher_id = int(teachers[0]["id"]) if teachers else 0
        matrix_cells = []
        for day in days:
            cells = []
            for period in periods:
                status = availability_status.get((matrix_teacher_id, int(day["id"]), int(period["id"])), "available")
                if status == "preferred":
                    status = "available"
                symbol = "✓" if status == "available" else ("X" if status == "unavailable" else "")
                status_by_teacher = ";".join(f"{tid}:{'available' if value == 'preferred' else str(value or '')}" for (tid, did, pid), value in availability_status.items() if did == int(day["id"]) and pid == int(period["id"]))
                cells.append(f"<td><button type='button' class='tt-av-cell' data-day='{int(day['id'])}' data-period='{int(period['id'])}' data-statuses='{status_by_teacher}' data-status='{status}'>{symbol}</button><input type='hidden' name='cell_status' value='{int(day['id'])}|{int(period['id'])}|{status}'></td>")
            matrix_cells.append(f"<tr><th>{esc(day['day_name'])}</th>{''.join(cells)}</tr>")
        matrix_period_headers = "".join(f"<th>{esc(p['label'])}<small>{esc(p['start_time'])}–{esc(p['end_time'])}</small></th>" for p in periods)
        matrix_day_rows = "".join(matrix_cells) or "<tr><td colspan='2' class='tt-muted'>Configure school days and teaching periods first.</td></tr>"
        total_availability_cells = len(days) * len(periods)
        # Seed from the complete school staff register so unrestricted teachers
        # are visible too, with every configured cell counted as available.
        teacher_availability_summary = {
            int(t["id"]): {"name": str(t["name"]), "fallback": 0, "unavailable": 0}
            for t in teachers
        }
        for a in availability:
            item = teacher_availability_summary.get(int(a["teacher_id"]))
            if item is not None:
                item["fallback" if a["availability"] == "fallback" else "unavailable"] += 1
        availability_rows = "".join(
            f"<tr data-availability-row data-search='{esc(item['name']).lower()}'><td>{esc(item['name'])}</td><td>{item['fallback'] + item['unavailable']}</td><td>{max(0, total_availability_cells-item['fallback']-item['unavailable'])}</td><td>{item['fallback']}</td><td>{item['unavailable']}</td><td><button type='button' class='tt-btn secondary tt-edit-availability' data-kind='teacher' data-id='{teacher_id}'>View / Edit</button></td></tr>"
            for teacher_id, item in sorted(teacher_availability_summary.items(), key=lambda pair: pair[1]["name"].lower())
        ) or "<tr><td colspan='6' class='tt-muted'>No teachers found in the school register.</td></tr>"
        subject_availability_status = {(int(a['subject_id']), int(a['day_id']), int(a['period_id'])): str(a['availability'] or '') for a in subject_availability}
        subject_matrix_cells = []
        for day in days:
            cells = []
            for period in periods:
                status = subject_availability_status.get((int(subjects[0]['id']) if subjects else 0, int(day['id']), int(period['id'])), 'available')
                symbol = '✓' if status == 'available' else ('X' if status == 'unavailable' else '')
                status_by_subject = ';'.join(f"{sid}:{value}" for (sid, did, pid), value in subject_availability_status.items() if did == int(day['id']) and pid == int(period['id']))
                cells.append(f"<td><button type='button' class='tt-sub-av-cell' data-day='{int(day['id'])}' data-period='{int(period['id'])}' data-statuses='{status_by_subject}' data-status='{status}'>{symbol}</button><input type='hidden' name='cell_status' value='{int(day['id'])}|{int(period['id'])}|{status}'></td>")
            subject_matrix_cells.append(f"<tr><th>{esc(day['day_name'])}</th>{''.join(cells)}</tr>")
        subject_matrix_period_headers = "".join(f"<th>{esc(p['label'])}<small>{esc(p['start_time'])}–{esc(p['end_time'])}</small></th>" for p in periods)
        subject_matrix_day_rows = "".join(subject_matrix_cells) or "<tr><td colspan='2' class='tt-muted'>Configure school days and teaching periods first.</td></tr>"
        # Seed from the full subject register, including subjects with no saved exceptions.
        subject_availability_summary = {
            int(s["id"]): {"name": str(s["name"]), "fallback": 0, "unavailable": 0}
            for s in subjects
        }
        for a in subject_availability:
            item = subject_availability_summary.get(int(a["subject_id"]))
            if item is not None:
                item["fallback" if a["availability"] == "fallback" else "unavailable"] += 1
        subject_availability_rows = "".join(
            f"<tr data-availability-row data-search='{esc(item['name']).lower()}'><td>{esc(item['name'])}</td><td>{item['fallback'] + item['unavailable']}</td><td>{max(0, total_availability_cells-item['fallback']-item['unavailable'])}</td><td>{item['fallback']}</td><td>{item['unavailable']}</td><td><button type='button' class='tt-btn secondary tt-edit-availability' data-kind='subject' data-id='{subject_id}'>View / Edit</button></td></tr>"
            for subject_id, item in sorted(subject_availability_summary.items(), key=lambda pair: pair[1]["name"].lower())
        ) or "<tr><td colspan='6' class='tt-muted'>No subjects found in the school register.</td></tr>"
        requirement_rows = "".join(
            f"<tr data-requirement-row data-class='{int(r['class_id'])}' data-subject='{int(r['subject_id'])}' data-teacher='{int(r['teacher_id'])}' data-search='{esc(str(r['class_name'])+' '+str(r['stream'] or '')+' '+str(r['subject_name'])+' '+str(r['teacher_name'])).lower()}'><td><b>{esc(r['class_name'])} {esc(r['stream'] or '')}</b></td><td>{esc(r['subject_name'])}</td><td><b>{esc(r['lessons_per_week'])} / wk</b><small class='tt-req-subline'>{esc(r['duration_periods'])} period(s) per lesson · {'Double allowed' if r['allow_double'] else 'Single pattern'}</small></td><td>{esc(r['teacher_name'])}</td><td><details><summary>Manage</summary><div class='tt-req-manage'><form method='post' data-native-post='true' action='/app/timetable/setup/requirement' class='tt-form compact'>{hidden}<input type='hidden' name='allocation' value='{int(r['class_id'])}|{int(r['subject_id'])}|{int(r['teacher_id'])}'><label>Lessons / week<input type='number' min='1' max='30' name='lessons_per_week' value='{int(r['lessons_per_week'])}' required></label><label>Duration<input type='number' min='1' max='4' name='duration_periods' value='{int(r['duration_periods'])}' required></label><label>Max / day<input type='number' min='1' max='10' name='max_lessons_per_day' value='{esc(r['max_lessons_per_day'] or '')}'></label><label class='tt-check'><input type='checkbox' name='allow_double' value='1' {'checked' if r['allow_double'] else ''}> Allow double</label><button class='tt-btn'>Save changes</button></form><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this subject requirement?&quot;)'>{hidden}<input type='hidden' name='kind' value='requirement'><input type='hidden' name='row_id' value='{int(r['id'])}'><button class='tt-btn danger'>Delete requirement</button></form></div></details></td></tr>" for r in requirements
        ) or "<tr><td colspan='5' class='tt-muted'>No weekly lesson requirements configured.</td></tr>"
        requirement_class_filters = "".join(f"<option value='{int(cid)}'>{esc(name)}</option>" for cid,name in sorted({(int(r['class_id']), str(r['class_name'])+' '+str(r['stream'] or '')) for r in requirements}, key=lambda x:x[1].lower()))
        requirement_subject_filters = "".join(f"<option value='{int(sid)}'>{esc(name)}</option>" for sid,name in sorted({(int(r['subject_id']), str(r['subject_name'])) for r in requirements}, key=lambda x:x[1].lower()))
        requirement_teacher_filters = "".join(f"<option value='{int(tid)}'>{esc(name)}</option>" for tid,name in sorted({(int(r['teacher_id']), str(r['teacher_name'])) for r in requirements}, key=lambda x:x[1].lower()))
        class_limit_rows = "".join(
            f"<tr><td><b>{esc(x['class_name'])} {esc(x['stream'] or '')}</b></td><td>{esc(x['max_lessons_per_week'] if x['max_lessons_per_week'] is not None else 'No limit')}</td><td>{esc(x['max_periods_per_day'] if x['max_periods_per_day'] is not None else 'No limit')}</td><td>{esc(x['notes'] or '—')}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/class-limits' class='tt-form compact'>{hidden}<input type='hidden' name='class_id' value='{int(x['class_id'])}'><label>Max lessons / week<input type='number' min='1' max='100' name='max_lessons_per_week' value='{esc(x['max_lessons_per_week'] or '')}'></label><label>Max periods / day<input type='number' min='1' max='30' name='max_periods_per_day' value='{esc(x['max_periods_per_day'] or '')}'></label><label>Notes<input name='notes' value='{esc(x['notes'] or '')}'></label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete these class workload limits?&quot;)'>{hidden}<input type='hidden' name='kind' value='class_limit'><input type='hidden' name='row_id' value='{int(x['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>"
            for x in class_limits
        ) or "<tr><td colspan='5' class='tt-muted'>No class workload limits configured.</td></tr>"
        class_limit_class_opts = "".join(
            f"<option value='{int(x['id'])}'>{esc(x['name'])} {esc(x['stream'] or '')}{' · existing limit will be updated' if int(x['id']) in {int(y['class_id']) for y in class_limits} else ''}</option>"
            for x in class_records
        )
        class_limit_form = f"""<section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>08 · CLASS WORKLOAD LIMITS</span><h3>Maximum weekly lessons and daily periods</h3><p>Set a ceiling independently for each class or stream. Double and triple lessons count by their actual period duration toward the daily period ceiling.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/class-limits' class='tt-form compact'>{hidden}<label class='wide'>Class / stream<select name='class_id' required><option value=''>Select class or stream</option>{class_limit_class_opts}</select></label><label>Maximum lessons per week<input name='max_lessons_per_week' type='number' min='1' max='100' placeholder='No limit'></label><label>Maximum periods per day<input name='max_periods_per_day' type='number' min='1' max='30' placeholder='No limit'></label><label class='wide'>Notes<input name='notes' maxlength='180' placeholder='Optional workload guidance'></label><button class='tt-btn'>Save class workload limits</button></form><div class='tt-table'><table><tr><th>Class / stream</th><th>Max lessons / week</th><th>Max periods / day</th><th>Notes</th><th>Actions</th></tr>{class_limit_rows}</table></div></div></section>"""
        bulk_requirement_form = (
            "<form method='post' data-native-post='true' action='/app/timetable/setup/requirements/bulk' class='tt-form compact'>"
            + hidden
            + "<p class='wide'>Choose each subject once. DaviSchool applies the weekly requirement to every class or stream where that subject is allocated, and links the existing teacher allocation automatically. Existing customized requirements are preserved.</p>"
            + "<div class='wide'><b>Subjects to include</b><div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;margin-top:8px'>" + subject_opts + "</div></div>"
            + "<label>Lessons per week<input name='lessons_per_week' type='number' min='1' max='30' value='5' required></label>"
            + "<label>Lesson duration<select name='duration_periods'><option value='1'>Single period</option><option value='2'>Double period</option><option value='3'>Triple period</option><option value='4'>Four periods</option></select></label>"
            + "<label>Maximum lessons per day<input name='max_lessons_per_day' type='number' min='1' max='10' placeholder='No limit'></label>"
            + "<label class='tt-check'><input type='checkbox' name='allow_double' value='1'> Allow double lessons</label>"
            + "<button class='tt-btn' type='submit'>Apply subject requirements to all classes</button></form>"
        )

        create_profile_html = """<section class='tt-card tt-profile-create-card'><span class='tt-kicker'>FIRST STEP</span><h3>Create timetable profile</h3><p>Choose the academic year and term this timetable will serve.</p><a class='tt-btn' href='#tt-profile-create-modal'>＋ Create timetable profile</a><span id='tt-profile-create-close'></span><div class='tt-modal' id='tt-profile-create-modal' role='dialog' aria-modal='true' aria-labelledby='tt-profile-create-title'><div class='tt-modal-dialog'><div class='tt-modal-head'><div><span class='tt-kicker'>FIRST STEP</span><h3 id='tt-profile-create-title'>Create timetable profile</h3><p>Choose the academic year and term for this schedule.</p></div><a class='tt-modal-close' href='#tt-profile-create-close' aria-label='Close'>&times;</a></div><form method='post' data-native-post='true' action='/app/timetable/setup/profile' class='tt-form'><label>Profile name<input name='name' required maxlength='80' placeholder='2027 Term 1 Master Timetable'></label><label>Academic year<input name='academic_year' required maxlength='20' placeholder='2027'></label><label>Term / semester<input name='term' required maxlength='40' placeholder='Term 1, Semester 1, Quarter 1…'></label><label>Academic start date<input name='academic_start_date' type='date'></label><label>Academic end date<input name='academic_end_date' type='date'></label><button class='tt-btn' type='submit'>Create profile</button></form></div></div></section>"""
        read_only_html = (
            f"<div class='tt-alert success'>This profile is {esc(selected['status']).replace('_',' ')} and cannot be edited. Create a new draft revision from <a href='/app/timetable/publishing?profile_id={pid}'>Publishing & Versions</a>.</div>"
            if selected and selected_status != "draft" else ""
        )
        sections = ""
        if selected:
            # Always render the configuration workspace for the selected profile.
            # The write handlers independently enforce draft-only edits; hiding the
            # entire workspace here made a valid saved profile look like creation failed.
            sections = f"""
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>01 · SCHOOL WEEK</span><h3>School days</h3><p>Set instructional days and their order.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/day' class='tt-form compact'>{hidden}<label>Day name<input name='day_name' required placeholder='Saturday'></label><label>Day code<input name='day_code' required maxlength='8' placeholder='SAT'></label><label>Display order<input name='day_order' required type='number' min='1' max='7' value='6'></label><label class='tt-check'><input type='checkbox' name='instructional' value='1' checked> Instructional day</label><button class='tt-btn'>Save day</button></form><div class='tt-table'><table><tr><th>Order</th><th>Day</th><th>Code</th><th>Type</th><th>Actions</th></tr>{day_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>02 · DAILY STRUCTURE</span><h3>Teaching periods</h3><p>Define period numbering and exact time boundaries.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/period' class='tt-form compact'>{hidden}<label>Period number<input name='period_no' type='number' min='1' max='30' required></label><label>Period label<input name='label' required placeholder='Period 1'></label><label>Start time<input name='start_time' type='time' required value='08:00'></label><label>End time<input name='end_time' type='time' required value='08:40'></label><label>Period type<select name='period_type'><option value='lesson'>Lesson</option><option value='study'>Study</option><option value='assembly'>Assembly</option></select></label><button class='tt-btn'>Save period</button></form><div class='tt-table'><table><tr><th>#</th><th>Period</th><th>Time</th><th>Duration</th><th>Type</th><th>Actions</th></tr>{period_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>03 · AUTOMATIC BREAK DETECTION</span><h3>Break gaps between periods</h3><p>Every positive time gap between consecutive periods is detected automatically. Select a gap, give it a name, and it becomes a break column. Unselected gaps remain available.</p></div></div><div class='tt-split'><div class='tt-table'><table><tr><th>Detected gap</th><th>Time</th><th>Status</th><th>Action</th></tr>{break_candidate_rows}</table></div><div class='tt-table'><h4>Selected breaks</h4><table><tr><th>#</th><th>Break</th><th>Time</th><th>Scope</th><th>Actions</th></tr>{break_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>04 · ACADEMIC CALENDAR</span><h3>Holidays and special dates</h3><p>Mark closures, holidays and exceptional instructional days inside this term.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/calendar-event' class='tt-form compact'>{hidden}<label>Date<input name='exception_date' type='date' required></label><label>Event name<input name='label' required placeholder='National holiday'></label><label>Event type<select name='exception_type'><option value='holiday'>Public / school holiday</option><option value='school_closure'>School closure</option><option value='special_instructional_day'>Special instructional day</option><option value='event'>School event</option></select></label><label>Notes<input name='notes' maxlength='180' placeholder='Optional details'></label><label class='tt-check'><input type='checkbox' name='instructional' value='1'> Instructional day</label><button class='tt-btn'>Save calendar date</button></form><div class='tt-table'><table><tr><th>Date</th><th>Event</th><th>Type</th><th>Day type</th><th>Notes</th><th>Actions</th></tr>{calendar_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>05 · LEARNING SPACES</span><h3>Rooms and facilities</h3><p>Optional setup: register physical spaces only if your school wants room allocation. Leave this section empty if rooms are not needed. Classes and streams are managed separately.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/room' class='tt-form compact'>{hidden}<label>Room code<input name='room_code' required placeholder='LAB-01'></label><label>Room name<input name='name' required placeholder='Science Laboratory'></label><label>Room type<select name='room_type'><option value='classroom'>Classroom</option><option value='laboratory'>Laboratory</option><option value='library'>Library</option><option value='hall'>Hall</option><option value='workshop'>Workshop</option><option value='sports'>Sports facility</option><option value='other'>Other</option></select></label><label>Capacity (optional)<input name='capacity' type='number' min='1' placeholder='Leave blank if unrestricted'></label><label class='wide'>Description (optional)<input name='description' maxlength='240' placeholder='Location or purpose'></label><label class='wide'>Equipment / resources (optional)<input name='equipment' maxlength='400' placeholder='Projector, computers, lab benches…'></label><label class='wide'>Suitable for (optional)<input name='suitable_for' maxlength='300' placeholder='Science practicals, exams, meetings…'></label><button class='tt-btn'>Save room / facility</button></form><div class='tt-table'><table><tr><th>Code</th><th>Room</th><th>Type</th><th>Capacity</th><th>Equipment / resources</th><th>Actions</th></tr>{room_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>06 · STAFF AVAILABILITY</span><h3>Teacher availability</h3><p>All teachers are available by default. Add a teacher only when you need to set fallback periods or block specific periods.</p></div></div><div class='tt-availability-editor'><form method='post' data-native-post='true' action='/app/timetable/setup/availability-matrix' class='tt-form compact'>{hidden}<label>Teacher<select name='teacher_id' id='tt-availability-teacher' required>{teacher_opts}</select></label><div class='tt-availability-legend'><span><b>✓</b> Available first</span><span><b>Blank</b> Fallback only</span><span><b>X</b> Never place</span></div><div class='tt-table tt-availability-grid'><table><thead><tr><th>Day / Period</th>{matrix_period_headers}</tr></thead><tbody>{matrix_day_rows}</tbody></table></div><p class='tt-muted'>Every cell starts ticked (available). Tap to cycle: ✓ available → blank (fallback only) → X (never place). The generator tries all ticked periods first and uses blank periods only when needed to complete the timetable.</p><button class='tt-btn'>Save teacher availability</button></form><div class='tt-availability-summary'><label class='tt-summary-search'>Search teachers<input type='search' data-availability-search='teacher' placeholder='Find teacher…'></label><div class='tt-table'><h4>Teacher restrictions</h4><table><thead><tr><th>Teacher</th><th title='Total restricted cells'>#</th><th title='Available'>✓</th><th title='Fallback only'>—</th><th title='Unavailable'>X</th><th>Actions</th></tr></thead><tbody>{availability_rows}</tbody></table></div></div></div></section>
            {class_limit_form}
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>07 · SUBJECT AVAILABILITY</span><h3>Subject availability</h3><p>All subjects are available in every configured lesson period by default. Add a subject only when you need to make certain periods fallback-only or completely unavailable.</p></div></div><div class='tt-availability-editor'><form method='post' data-native-post='true' action='/app/timetable/setup/subject-availability-matrix' class='tt-form compact'>{hidden}<label>Subject<select name='subject_id' id='tt-subject-availability' required>{''.join(f"<option value='{int(x['id'])}'>{esc(x['name'])}</option>" for x in subjects)}</select></label><div class='tt-availability-legend'><span><b>✓</b> Available first</span><span><b>Blank</b> Fallback only</span><span><b>X</b> Never schedule</span></div><div class='tt-table tt-availability-grid'><table><thead><tr><th>Day / Period</th>{subject_matrix_period_headers}</tr></thead><tbody>{subject_matrix_day_rows}</tbody></table></div><p class='tt-muted'>Every cell starts ticked. Tap to cycle: ✓ available → blank (fallback only) → X (never schedule). The generator tries ticked periods first and uses blank periods only when needed to complete the timetable.</p><button class='tt-btn'>Save subject availability</button></form><div class='tt-availability-summary'><label class='tt-summary-search'>Search subjects<input type='search' data-availability-search='subject' placeholder='Find subject…'></label><div class='tt-table'><h4>Subject restrictions</h4><table><thead><tr><th>Subject</th><th title='Total restricted cells'>#</th><th title='Available'>✓</th><th title='Fallback only'>—</th><th title='Unavailable'>X</th><th>Actions</th></tr></thead><tbody>{subject_availability_rows}</tbody></table></div></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>08 · WEEKLY LESSON LOAD</span><h3>Subject requirements</h3><p>Set each subject's weekly lesson load once and apply it across all classes and streams where it is taught. Teacher allocations are matched automatically.</p></div></div><div class='tt-split'><div>{bulk_requirement_form}</div><div class='tt-req-workspace'><div class='tt-req-toolbar'><label class='tt-req-search'><span>Search requirements</span><input type='search' id='tt-req-search' placeholder='Search class, subject or teacher…'></label><details class='tt-req-filter'><summary>⚙ Filters <span id='tt-req-filter-count'>All</span></summary><div class='tt-req-filter-panel'><div class='tt-req-filter-head'><strong>Filter requirements</strong><button type='button' class='tt-req-filter-close' aria-label='Close filters' title='Close filters'>×</button></div><label>Class / stream<select id='tt-req-class'><option value=''>All classes</option>{requirement_class_filters}</select></label><label>Subject<select id='tt-req-subject'><option value=''>All subjects</option>{requirement_subject_filters}</select></label><label>Teacher<select id='tt-req-teacher'><option value=''>All teachers</option>{requirement_teacher_filters}</select></label><button type='button' class='tt-btn secondary' id='tt-req-reset'>Clear filters</button></div></details><span class='tt-req-count' id='tt-req-count'></span></div><div class='tt-table tt-req-table'><table><thead><tr><th>Class / stream</th><th>Subject</th><th>Weekly requirement</th><th>Teacher</th><th>Manage</th></tr></thead><tbody>{requirement_rows}</tbody></table></div><div class='tt-req-pagination'><span id='tt-req-page-info'></span><div><button type='button' class='tt-btn secondary' id='tt-req-prev'>← Previous</button><button type='button' class='tt-btn secondary' id='tt-req-next'>Next →</button></div></div></div></div></section>
            """
        body = f"""
        <style>
        .tt-wrap{{max-width:1500px;margin:auto;padding:22px;color:#234638}}
        .tt-wrap *{{box-sizing:border-box}}
        .tt-wrap{{background:linear-gradient(145deg,#edf6ef 0%,#e4f0e6 42%,#f7faf7 100%);border-radius:26px;padding:24px}}
        .tt-hero{{position:relative;overflow:hidden;display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:18px;padding:28px 30px;border:1px solid #d1e3d4;border-radius:23px;background:linear-gradient(118deg,#dceede 0%,#c9e2ce 52%,#eaf4e9 100%);box-shadow:0 14px 32px rgba(39,91,57,.09)}}
        .tt-hero:after{{content:'';position:absolute;width:260px;height:260px;right:8%;top:-175px;border:1px solid rgba(55,112,73,.16);border-radius:50%;box-shadow:0 0 0 28px rgba(55,112,73,.045),0 0 0 58px rgba(55,112,73,.03)}}
        .tt-hero>div{{position:relative;z-index:1}}.tt-hero h1{{font-size:clamp(25px,3vw,34px);margin:5px 0 7px;color:#1e4934;letter-spacing:-.7px}}.tt-hero p,.tt-section-title p,.tt-card p,.tt-profile p{{color:#617a69;font-size:13px;margin:5px 0 0;line-height:1.6}}
        .tt-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}
        .tt-card,.tt-section,.tt-profile,.tt-empty{{background:rgba(255,255,255,.94);border:1px solid #dce9de;border-radius:19px;padding:20px;margin-bottom:16px;box-shadow:0 7px 22px rgba(36,83,52,.055)}}
        .tt-card h3,.tt-section h3{{font-size:17px;margin:4px 0;color:#234c37}}.tt-profile{{display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;border-left:4px solid #4d9564}}.tt-profile h2{{margin:4px 0;font-size:21px;color:#204a34}}
        .tt-stats{{display:flex;gap:18px}}.tt-stats span{{font-size:11px;color:#647b6a;text-align:center}}.tt-stats b{{display:block;font-size:22px;color:#28734a}}
        .tt-status,.tt-pill{{background:#e7f4e9;color:#23613b;border-radius:20px;padding:4px 8px;font-size:10px;font-weight:800}}
        .tt-select{{display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap}}.tt-select label{{font-size:12px;font-weight:800;color:#42634e}}.tt-select select{{min-width:260px;max-width:100%;padding:11px 13px;border:1px solid #cfe0d1;border-radius:11px;background:white;color:#254a35}}
        .tt-section-title{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:15px}}.tt-section-title>div{{min-width:180px}}
        .tt-split{{display:grid;grid-template-columns:minmax(190px,.48fr) minmax(0,1.7fr);gap:16px;align-items:start}}
        .tt-form{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-items:end}}.tt-form.compact{{grid-template-columns:repeat(2,minmax(0,1fr))}}
        .tt-form label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:#3b5946}}.tt-form label.wide{{grid-column:1/-1}}
        .tt-form input,.tt-form select{{width:100%;min-width:0;padding:11px;border:1px solid #d5e4d7;border-radius:10px;background:#fbfdfb;font:13px Arial;color:#234638;outline:none}}.tt-form input:focus,.tt-form select:focus{{border-color:#78ad85;box-shadow:0 0 0 3px rgba(91,153,107,.13)}}
        .tt-form .tt-check{{flex-direction:row;align-items:center;gap:7px;padding:9px 0}}.tt-form .tt-check input{{width:auto}}
        .tt-bulk-requirements{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px;padding:15px;border:1px solid #cfe2d2;border-radius:14px;background:linear-gradient(135deg,#f4faf4,#eaf5ec)}}
        .tt-bulk-requirements>div,.tt-bulk-requirements button{{grid-column:1/-1}}
        .tt-bulk-requirements p{{font-size:11px;color:#718477;margin:5px 0 0}}
        .tt-bulk-requirements label{{display:grid;gap:5px;font-size:11px;font-weight:700}}
        .tt-bulk-requirements input,.tt-bulk-requirements select{{width:100%;padding:10px;border:1px solid #d8e5da;border-radius:9px;background:#fff}}
        @media(max-width:600px){{.tt-bulk-requirements{{grid-template-columns:1fr}}.tt-bulk-requirements>div,.tt-bulk-requirements button{{grid-column:auto}}}}
        .tt-btn{{border:0;border-radius:10px;padding:11px 15px;background:linear-gradient(135deg,#347c50,#246441);color:white;text-decoration:none!important;font-weight:800;font-size:12px;cursor:pointer;min-height:40px;display:inline-flex;align-items:center;justify-content:center;gap:7px;box-shadow:0 5px 12px rgba(35,102,62,.13);transition:transform .16s,box-shadow .16s}}
        .tt-btn:hover{{background:linear-gradient(135deg,#286b43,#1d5636);transform:translateY(-1px);box-shadow:0 8px 16px rgba(35,102,62,.18)}}
        .tt-btn.danger{{background:linear-gradient(135deg,#c65a54,#a83d38);box-shadow:0 5px 12px rgba(168,61,56,.12)}}.tt-btn.danger:hover{{background:linear-gradient(135deg,#b94a44,#92332e)}}
        .tt-table details{{display:inline-block;position:relative;margin-right:6px}}.tt-table details summary{{cursor:pointer;list-style:none;border:1px solid #cfe2d2;background:#edf6ee;color:#2a6a43;border-radius:8px;padding:8px 10px;font-size:11px;font-weight:800}}.tt-table details summary::-webkit-details-marker{{display:none}}.tt-table details[open]{{min-width:240px;white-space:normal}}.tt-table details[open] form{{position:absolute;z-index:20;right:0;top:34px;width:260px;max-height:65vh;overflow:auto;padding:12px;background:#fff;border:1px solid #dce8de;border-radius:12px;box-shadow:0 12px 30px rgba(25,60,38,.18)}}.tt-table details label{{display:block;margin:7px 0;font-size:11px;font-weight:700;white-space:normal}}.tt-table details input,.tt-table details select{{width:100%;padding:8px;border:1px solid #d7e3d8;border-radius:7px}}.tt-table td:last-child>form{{display:inline-block}}.tt-table td:last-child>form button{{padding:8px 10px;min-height:34px}}
        .tt-btn.secondary{{background:#edf6ee;color:#2a6a43;border:1px solid #cfe2d2;box-shadow:none}}.tt-btn.secondary:hover{{background:#e2f0e4}}
        .tt-add-card{{min-height:100%;display:flex;align-items:center}}.tt-add-card .tt-btn{{width:100%;min-height:74px;white-space:normal;text-align:center}}
        .tt-req-workspace{{min-width:0}}.tt-req-toolbar{{display:flex;align-items:end;gap:9px;flex-wrap:wrap;margin:0 0 10px}}.tt-req-search{{display:flex;flex:1 1 230px;flex-direction:column;gap:5px;font-size:10px;font-weight:800;color:#557061}}.tt-req-search input{{width:100%;padding:10px 12px;border:1px solid #d5e4d7;border-radius:10px;background:#fbfdfb;font-size:12px}}.tt-req-filter{{position:relative;flex:none}}.tt-req-filter>summary{{list-style:none;cursor:pointer;border:1px solid #d5e4d7;border-radius:10px;padding:10px 13px;background:#f3f8f3;color:#326846;font-size:11px;font-weight:850}}.tt-req-filter>summary::-webkit-details-marker{{display:none}}.tt-req-filter>summary span{{margin-left:6px;padding:3px 7px;border-radius:20px;background:#e2efe4}}.tt-req-filter-panel{{position:absolute;z-index:80;right:0;top:calc(100% + 7px);width:min(290px,88vw);display:grid;gap:10px;padding:15px;background:#fff;border:1px solid #dce8de;border-radius:13px;box-shadow:0 15px 35px rgba(25,60,38,.16)}}.tt-req-filter-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;color:#234c37;font-size:12px}}.tt-req-filter-close{{display:grid;place-items:center;width:29px;height:29px;flex:none;border:1px solid #dce8de;border-radius:8px;background:#f3f8f3;color:#416b4d;font-size:20px;line-height:1;cursor:pointer}}.tt-req-filter-close:hover{{background:#e5f1e7;border-color:#bcd7c1}}.tt-req-filter-panel label{{display:grid;gap:5px;font-size:10px;font-weight:800;color:#557061}}.tt-req-filter-panel select{{width:100%;padding:9px;border:1px solid #d5e4d7;border-radius:8px;background:#fbfdfb;color:#234638}}.tt-req-count{{font-size:10px;color:#7a8d80;font-weight:750}}.tt-req-table table{{min-width:620px}}.tt-req-table th,.tt-req-table td{{padding:9px 10px}}.tt-req-subline{{display:block;margin-top:3px;color:#85958a;font-size:9px}}.tt-req-table td:last-child details{{margin:0}}.tt-req-table details[open]{{min-width:0}}.tt-req-table details[open] .tt-req-manage{{position:absolute;z-index:90;right:0;top:35px;width:min(310px,85vw);max-height:70vh;overflow:auto;padding:13px;background:#fff;border:1px solid #dce8de;border-radius:12px;box-shadow:0 12px 30px rgba(25,60,38,.18)}}.tt-req-table details[open] .tt-req-manage form{{position:static;z-index:auto;top:auto;right:auto;width:100%;max-height:none;overflow:visible;padding:0;background:transparent;border:0;border-radius:0;box-shadow:none}}.tt-req-manage .tt-form{{grid-template-columns:1fr 1fr;gap:8px}}.tt-req-manage .tt-form button,.tt-req-manage .tt-form label.wide{{grid-column:1/-1}}.tt-req-manage>form+form{{margin-top:9px}}.tt-req-pagination{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 2px}}.tt-req-pagination>div{{display:flex;gap:6px}}.tt-req-pagination .tt-btn{{min-height:33px;padding:7px 10px;font-size:10px}}.tt-req-table tr[hidden]{{display:none!important}}@media(max-width:600px){{.tt-req-toolbar{{align-items:stretch}}.tt-req-filter{{align-self:flex-start}}.tt-req-pagination{{align-items:flex-start;flex-direction:column}}.tt-req-pagination>div{{width:100%}}.tt-req-pagination button{{flex:1}}}}
        .tt-table{{overflow:auto;border:1px solid #e1ebe2;border-radius:13px;background:#fff}}.tt-table table{{width:100%;border-collapse:collapse;min-width:450px}}.tt-table th{{background:#edf5ee;color:#315b3e;text-align:left;font-size:10px;letter-spacing:.04em}}.tt-table th,.tt-table td{{padding:11px;border-bottom:1px solid #edf2ed;font-size:11px;white-space:nowrap}}.tt-table tr:last-child td{{border-bottom:0}}.tt-muted{{color:#94a39a;text-align:center;padding:18px!important}}
        .tt-alert{{padding:12px 14px;border-radius:11px;margin-bottom:14px;font-size:12px;font-weight:700}}.tt-alert.success{{background:#eaf5ec;color:#17633b}}.tt-alert.error{{background:#fff1f0;color:#a12828}}.tt-empty{{text-align:center;padding:34px}}.tt-empty b{{font-size:18px}}
        /* Compact seven-step setup accordion */
        .tt-section{{padding:16px 18px;margin-bottom:10px;border-radius:16px;transition:box-shadow .18s,border-color .18s}}
        .tt-section.tt-step-open{{border-color:#b9d8c0;box-shadow:0 8px 22px rgba(36,83,52,.075)}}
        .tt-section-title{{margin:0;gap:12px}}
        .tt-section-title>div{{flex:1;min-width:0}}
        .tt-section-toggle{{flex:none;display:inline-flex;align-items:center;gap:8px;border:1px solid #d8e7da;border-radius:10px;padding:8px 11px;background:#f5faf5;color:#326846;font-size:11px;font-weight:800;cursor:pointer}}
        .tt-section-toggle:hover{{background:#eaf5ec;border-color:#bcd9c2}}
        .tt-section-toggle .tt-chevron{{display:inline-block;transition:transform .18s;font-size:14px}}
        .tt-section.tt-step-open .tt-chevron{{transform:rotate(180deg)}}
        .tt-section-content{{padding-top:15px}}
        .tt-section-content[hidden]{{display:none!important}}
        .tt-modal-dialog:has(.tt-availability-grid){{width:min(1100px,96vw)}}
                 .tt-availability-summary{{min-width:0}}.tt-summary-search{{display:flex;flex-direction:column;gap:5px;margin-bottom:9px;color:#526b5d;font-size:11px;font-weight:800}}.tt-summary-search input{{width:100%;padding:9px 11px;border:1px solid #d5e4d7;border-radius:9px;background:#fbfdfb;color:#234638}}.tt-availability-summary .tt-table table{{min-width:430px}}.tt-availability-summary th:not(:first-child),.tt-availability-summary td:not(:first-child){{text-align:center;padding:8px 7px}}.tt-availability-summary th[title]{{cursor:help}}.tt-availability-summary .tt-btn{{min-height:32px;padding:7px 9px;font-size:10px}}.tt-availability-summary tr[hidden]{{display:none}}
         .tt-availability-editor{{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,1fr);gap:18px;align-items:start}}.tt-availability-legend{{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:#526b5d}}.tt-availability-legend b{{display:inline-block;padding:3px 8px;border-radius:7px;background:#edf5ee}}.tt-availability-grid{{overflow:auto;max-width:100%}}.tt-availability-grid table{{min-width:650px}}.tt-availability-grid th{{white-space:nowrap}}.tt-availability-grid th small{{display:block;font-weight:500;color:#718579}}.tt-av-cell{{width:38px;height:34px;border:1px solid #d7e5da;border-radius:8px;background:#fff;color:#234638;font-weight:800;cursor:pointer}}.tt-av-cell[data-status='available']{{background:#dff2e4;border-color:#65a878;color:#176b35}}.tt-av-cell[data-status='unavailable']{{background:#fde7e7;border-color:#d98b8b;color:#a32626}}.tt-availability-grid td{{text-align:center;padding:5px}}@media(max-width:850px){{.tt-availability-editor{{grid-template-columns:1fr}}}}
        .tt-modal{{position:fixed;inset:0;z-index:10050;display:none;align-items:center;justify-content:center;padding:18px;background:rgba(20,43,30,.48);backdrop-filter:blur(5px)}}.tt-modal.is-open{{display:flex;animation:ttFade .16s ease-out}}.tt-modal:target{{display:flex;animation:ttFade .16s ease-out}}.tt-profile-create-card>.tt-btn{{margin-top:12px;text-decoration:none!important}}.tt-modal-close{{display:grid;place-items:center;text-decoration:none!important}}
        .tt-modal-dialog{{position:relative;width:min(620px,100%);max-height:min(88vh,850px);overflow:auto;padding:25px;background:linear-gradient(145deg,#fff 0%,#f4faf4 100%);border:1px solid #d5e6d8;border-radius:22px;box-shadow:0 24px 70px rgba(18,52,31,.25);animation:ttPop .18s ease-out}}
        .tt-modal-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:19px}}.tt-modal-head h3{{font-size:20px;margin:4px 0;color:#214a34}}.tt-modal-head p{{font-size:12px;color:#718477;margin:0}}.tt-modal-close{{border:0;width:35px;height:35px;border-radius:11px;background:#eaf4eb;color:#326a43;font-size:21px;cursor:pointer;flex:none}}
        .tt-modal .tt-form{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tt-modal .tt-form label.wide{{grid-column:1/-1}}.tt-modal .tt-form button{{grid-column:1/-1;margin-top:4px}}
        @keyframes ttFade{{from{{opacity:0}}to{{opacity:1}}}}@keyframes ttPop{{from{{opacity:0;transform:translateY(9px) scale(.985)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
        @media(max-width:900px){{.tt-split{{grid-template-columns:1fr}}.tt-add-card .tt-btn{{min-height:48px}}.tt-form{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
        @media(max-width:600px){{.tt-wrap{{padding:12px;border-radius:17px}}.tt-hero{{padding:22px 18px}}.tt-hero h1{{font-size:24px}}.tt-form,.tt-form.compact,.tt-modal .tt-form{{grid-template-columns:1fr}}.tt-form label.wide,.tt-modal .tt-form label.wide{{grid-column:auto}}.tt-stats{{width:100%;justify-content:space-around}}.tt-modal{{padding:10px}}.tt-modal-dialog{{padding:20px 16px;border-radius:18px}}.tt-hero>div:last-child{{width:100%}}.tt-hero>div:last-child a{{flex:1}}}}
        </style>
        <div class='tt-wrap'><div class='tt-hero'><div><span class='tt-kicker'>DAVISCHOOL · SCHEDULING ENGINE</span><h1>Timetable Setup</h1><p>Set up your school week, teaching sessions, facilities and staffing rules in one guided workspace.</p></div><div style='display:flex;gap:8px;flex-wrap:wrap'><a class='tt-btn' href='/app/timetable/automatic?profile_id={pid}'>⚡ Automatic Generator</a><a class='tt-btn secondary' href='/app/timetable/builder?profile_id={pid}'>Manual Builder</a><a class='tt-btn secondary' href='/app/timetable/publishing?profile_id={pid}'>Publishing & Versions</a></div></div>{notice}{selector}{profile_summary}{read_only_html}{create_profile_html if not has_draft_profile else ""}{sections}</div>
        <script>
        (function(){{
          const root=document.querySelector('.tt-wrap'); if(!root) return;
          // The setup workspace lives inside the application's own scrolling
          // container on some devices. Do not lock body overflow for a modal:
          // that can leave the app shell unable to scroll after an AJAX refresh.
          function releaseTimetableScrollLock(){{
            document.querySelectorAll('.tt-modal.is-open').forEach(modal=>modal.classList.remove('is-open'));
            document.body.classList.remove('tt-modal-scroll-locked');
            document.documentElement.classList.remove('tt-modal-scroll-locked');
            document.body.style.removeProperty('touch-action');
            document.documentElement.style.removeProperty('touch-action');
          }}
          // Make every setup POST form carry the active tab session explicitly.
          // These forms are moved into modal containers below; this local guard
          // keeps their session identity even if the shared tab-session script
          // is delayed or unavailable on a mobile browser.
          function attachTabSession(form){{
            try{{
              const tabId=sessionStorage.getItem('davischool_tab_id')||'';
              if(!tabId) return;
              let field=form.querySelector('input[name="ds_tab"]');
              if(!field){{field=document.createElement('input');field.type='hidden';field.name='ds_tab';form.appendChild(field);}}
              field.value=tabId;
              const action=new URL(form.getAttribute('action')||window.location.href,window.location.origin);
              if(action.origin===window.location.origin){{action.searchParams.set('ds_tab',tabId);form.action=action.pathname+action.search+action.hash;}}
            }}catch(_){{}}
          }}
          root.querySelectorAll('form[method="post" i]').forEach(attachTabSession);
          root.addEventListener('submit',event=>{{
            const form=event.target;
            if(form&&form.matches&&form.matches('form[method="post" i]')) attachTabSession(form);
          }},true);
          const teacherPicker=root.querySelector('#tt-availability-teacher');
          const subjectPicker=root.querySelector('#tt-subject-availability');
          function setAvailabilityCell(button,teacherId){{
            const statusMap={{}};
            (button.dataset.statuses||'').split(';').filter(Boolean).forEach(item=>{{const parts=item.split(':');statusMap[parts[0]]=parts[1]||'';}});
            const stored=statusMap[String(teacherId)]||'available';
            const status=stored==='fallback'?'':stored;
            button.dataset.status=status;
            button.textContent=status==='available'?'✓':(status==='unavailable'?'X':'');
            button.setAttribute('role','checkbox'); button.setAttribute('aria-checked',status==='available'?'true':'false');
            const hidden=button.nextElementSibling;
            if(hidden) hidden.value=button.dataset.day+'|'+button.dataset.period+'|'+status;
          }}
          root.querySelectorAll('.tt-av-cell').forEach(button=>{{
            button.addEventListener('click',()=>{{
              const states=['available','','unavailable'];
              const current=button.dataset.status||'';
              const next=states[(states.indexOf(current)+1)%states.length];
              button.dataset.status=next;
              button.textContent=next==='available'?'✓':(next==='unavailable'?'X':'');
              button.setAttribute('aria-checked',next==='available'?'true':'false');
              const hidden=button.nextElementSibling;
              if(hidden) hidden.value=button.dataset.day+'|'+button.dataset.period+'|'+next;
            }});
          }});
          if(teacherPicker){{
            teacherPicker.addEventListener('change',()=>root.querySelectorAll('.tt-av-cell').forEach(button=>setAvailabilityCell(button,teacherPicker.value)));
            root.querySelectorAll('.tt-av-cell').forEach(button=>setAvailabilityCell(button,teacherPicker.value));
          }}
          function setSubjectAvailabilityCell(button,subjectId){{
            const statusMap={{}};
            (button.dataset.statuses||'').split(';').filter(Boolean).forEach(item=>{{const parts=item.split(':');statusMap[parts[0]]=parts[1]||'';}});
            const stored=statusMap[String(subjectId)]||'available';
            const status=stored==='fallback'?'':stored;
            button.dataset.status=status;
            button.textContent=status==='available'?'✓':(status==='unavailable'?'X':'');
            button.setAttribute('role','checkbox'); button.setAttribute('aria-checked',status==='available'?'true':'false');
            const hidden=button.nextElementSibling;
            if(hidden) hidden.value=button.dataset.day+'|'+button.dataset.period+'|'+status;
          }}
          root.querySelectorAll('.tt-sub-av-cell').forEach(button=>{{
            button.addEventListener('click',()=>{{
              const states=['available','','unavailable'];
              const current=button.dataset.status||'';
              const next=states[(states.indexOf(current)+1)%states.length];
              button.dataset.status=next;
              button.textContent=next==='available'?'✓':(next==='unavailable'?'X':'');
              button.setAttribute('aria-checked',next==='available'?'true':'false');
              const hidden=button.nextElementSibling;
              if(hidden) hidden.value=button.dataset.day+'|'+button.dataset.period+'|'+next;
            }});
          }});
          if(subjectPicker){{
            subjectPicker.addEventListener('change',()=>root.querySelectorAll('.tt-sub-av-cell').forEach(button=>setSubjectAvailabilityCell(button,subjectPicker.value)));
            root.querySelectorAll('.tt-sub-av-cell').forEach(button=>setSubjectAvailabilityCell(button,subjectPicker.value));
          }}
          // Compact, searchable subject-requirements register with filter popover and paging.
          const reqRows=Array.from(root.querySelectorAll('[data-requirement-row]'));
          if(reqRows.length){{
            const search=root.querySelector('#tt-req-search'), cls=root.querySelector('#tt-req-class'), subj=root.querySelector('#tt-req-subject'), teacher=root.querySelector('#tt-req-teacher');
            const count=root.querySelector('#tt-req-count'), info=root.querySelector('#tt-req-page-info'), prev=root.querySelector('#tt-req-prev'), next=root.querySelector('#tt-req-next'), filterCount=root.querySelector('#tt-req-filter-count');
            let page=0; const pageSize=8; let visible=[];
            function renderRequirements(){{
              const q=(search?.value||'').trim().toLowerCase(), c=cls?.value||'', s=subj?.value||'', t=teacher?.value||'';
              visible=reqRows.filter(row=>(!q||row.dataset.search.includes(q))&&(!c||row.dataset.class===c)&&(!s||row.dataset.subject===s)&&(!t||row.dataset.teacher===t));
              const pages=Math.max(1,Math.ceil(visible.length/pageSize));page=Math.min(page,pages-1);
              reqRows.forEach(row=>row.hidden=true);
              visible.slice(page*pageSize,(page+1)*pageSize).forEach(row=>row.hidden=false);
              if(count)count.textContent=visible.length+' of '+reqRows.length+' requirements';
              if(info)info.textContent='Page '+(page+1)+' of '+pages+' · Showing '+(visible.length?Math.min(page*pageSize+1,visible.length):0)+'–'+Math.min((page+1)*pageSize,visible.length);
              if(prev)prev.disabled=page===0;if(next)next.disabled=page>=pages-1;
              const active=[c,s,t].filter(Boolean).length;if(filterCount)filterCount.textContent=active?active+' active':'All';
            }}
            [search,cls,subj,teacher].forEach(el=>el&&el.addEventListener(el===search?'input':'change',()=>{{page=0;renderRequirements();}}));
            prev?.addEventListener('click',()=>{{page=Math.max(0,page-1);renderRequirements();}});
            next?.addEventListener('click',()=>{{page++;renderRequirements();}});
            const filterDetails=root.querySelector('.tt-req-filter');
            root.querySelector('.tt-req-filter-close')?.addEventListener('click',()=>{{if(filterDetails)filterDetails.open=false;}});
            root.querySelector('#tt-req-reset')?.addEventListener('click',()=>{{if(search)search.value='';if(cls)cls.value='';if(subj)subj.value='';if(teacher)teacher.value='';page=0;renderRequirements();}});
            renderRequirements();
          }}
          root.querySelectorAll('[data-availability-search]').forEach(input=>input.addEventListener('input',()=>{{
            const query=input.value.trim().toLowerCase(), table=input.closest('.tt-availability-summary');
            table.querySelectorAll('[data-availability-row]').forEach(row=>{{row.hidden=!row.dataset.search.includes(query);}});
          }}));
          root.querySelectorAll('.tt-edit-availability').forEach(button=>button.addEventListener('click',()=>{{
            const picker=button.dataset.kind==='teacher'?teacherPicker:subjectPicker;
            if(!picker) return;
            // The shared setup initializer moves each editor form into its
            // section modal. Open that modal before selecting and displaying
            // the requested teacher/subject; otherwise the control targets a
            // detached-from-layout form and appears not to respond.
            const section=button.closest('.tt-section');
            const modalOpener=section?.querySelector('.tt-add-card button');
            if(modalOpener) modalOpener.click();
            picker.value=button.dataset.id;
            picker.dispatchEvent(new Event('change',{{bubbles:true}}));
            picker.focus({{preventScroll:true}});
            picker.scrollIntoView({{behavior:'smooth',block:'center'}});
          }}));
          // Keep one document-level handler so it survives replacing .tt-wrap.
          // Identify supported actions by endpoint, not button text or submitter support.
          if(!document.documentElement.dataset.ttSetupAjaxBound){{
            document.documentElement.dataset.ttSetupAjaxBound='1';
            document.addEventListener('submit',async event=>{{
              const form=event.target;
              if(!form||!form.matches||!form.matches('form[method="post" i]')) return;
              const action=new URL(form.getAttribute('action')||window.location.href,window.location.origin);
              const endpoint=action.pathname;
              const isSetupWrite=endpoint.startsWith('/app/timetable/setup/')&&new Set(['day','period','break','calendar-event','room','availability','availability-matrix','subject-availability-matrix','requirement','class-limits','row-delete','break-gap']).has(endpoint.split('/').pop());
              if(!isSetupWrite) return;
              event.preventDefault();
              if(form.dataset.ajaxBusy==='1') return;
              form.dataset.ajaxBusy='1';
              const submitter=event.submitter||null;
              const isDelete=endpoint.endsWith('/row-delete');
              const buttons=Array.from(form.querySelectorAll('button[type="submit"],button:not([type])'));
              buttons.forEach(button=>button.disabled=true);
              const oldText=submitter?.textContent;
              if(submitter) submitter.textContent=isDelete?'Deleting…':'Saving…';
              try{{
                attachTabSession(form);
                const response=await fetch(action.href,{{
                  method:'POST',body:new FormData(form),credentials:'same-origin',
                  headers:{{'X-Requested-With':'XMLHttpRequest'}}
                }});
                if(!response.ok) throw new Error('The request could not be completed ('+response.status+').');
                const html=await response.text();
                const parsed=new DOMParser().parseFromString(html,'text/html');
                const nextRoot=parsed.querySelector('.tt-wrap');
                if(!nextRoot) throw new Error('The server response did not contain the timetable setup page. The server may have redirected your session.');
                const currentRoot=document.querySelector('.tt-wrap');
                if(!currentRoot) throw new Error('The timetable setup page is no longer available.');
                // Preserve the active scroll position (including the app's
                // nested scrolling pane) while replacing the setup workspace.
                const windowScrollY=window.scrollY||0;
                const scrollSnapshots=[];
                let scrollNode=currentRoot;
                while(scrollNode){{
                  if(scrollNode.scrollHeight>scrollNode.clientHeight+1) scrollSnapshots.push({{node:scrollNode,top:scrollNode.scrollTop,left:scrollNode.scrollLeft}});
                  scrollNode=scrollNode.parentElement;
                }}
                const openSections=Array.from(currentRoot.querySelectorAll('.tt-section.tt-step-open h3')).map(node=>node.textContent.trim());
                // Remove any stale overlay state before the old modal nodes are discarded.
                releaseTimetableScrollLock();
                currentRoot.replaceWith(nextRoot);
                const initializer=Array.from(parsed.scripts).find(script=>script.textContent.includes('Keep every setup panel collapsed'));
                if(initializer&&initializer.textContent){{
                  const fresh=document.createElement('script');
                  fresh.textContent=initializer.textContent;
                  document.body.appendChild(fresh);
                  fresh.remove();
                }}
                // Re-open the section the user was editing and restore both
                // document and application-pane scroll offsets after layout.
                openSections.forEach(title=>{{
                  const section=Array.from(nextRoot.querySelectorAll('.tt-section')).find(item=>(item.querySelector('h3')?.textContent||'').trim()===title);
                  const toggle=section?.querySelector('.tt-section-toggle');
                  if(toggle&&toggle.getAttribute('aria-expanded')!=='true') toggle.click();
                }});
                requestAnimationFrame(()=>{{
                  scrollSnapshots.forEach(item=>{{if(item.node&&item.node.isConnected){{item.node.scrollTop=item.top;item.node.scrollLeft=item.left;}}}});
                  window.scrollTo(0,windowScrollY);
                }});
              }}catch(error){{
                window.alert(error.message||'Unable to save this change. Please try again.');
                if(submitter&&oldText) submitter.textContent=oldText;
                buttons.forEach(button=>button.disabled=false);
                delete form.dataset.ajaxBusy;
              }}
            }},false);
          }}
          let serial=0;
          root.querySelectorAll('.tt-section').forEach(section=>{{
            const addForm=Array.from(section.querySelectorAll('.tt-form.compact')).find(form=>!form.closest('.tt-table')&&!form.closest('details'))||null;
            const title=section.querySelector('h3')?.textContent?.trim()||'Configuration';
            const modalId='tt-setup-modal-'+(++serial);
            const host=document.createElement('div'); host.className='tt-modal'; host.id=modalId; host.setAttribute('role','dialog'); host.setAttribute('aria-modal','true');
            const dialog=document.createElement('div'); dialog.className='tt-modal-dialog';
            const head=document.createElement('div'); head.className='tt-modal-head';
            const copy=document.createElement('div'); copy.innerHTML='<span class="tt-kicker">TIMETABLE CONFIGURATION</span><h3></h3><p>Complete the details below, then save your changes.</p>'; copy.querySelector('h3').textContent=title;
            const close=document.createElement('button'); close.type='button'; close.className='tt-modal-close'; close.setAttribute('aria-label','Close'); close.innerHTML='&times;';
            head.append(copy,close);
            const formSlot=document.createElement('div'); formSlot.className='tt-modal-form-slot';
            let open=null;
            if(addForm){{const addParent=addForm.parentNode; const card=document.createElement('div'); card.className='tt-add-card'; open=document.createElement('button'); open.type='button'; open.className='tt-btn secondary'; open.innerHTML='<span aria-hidden="true">＋</span> Add '+title.toLowerCase(); card.append(open); addParent.replaceChild(card,addForm); formSlot.append(addForm);}}
            dialog.append(head,formSlot); host.append(dialog); root.append(host);
            const openModal=(form,mode)=>{{
              formSlot.replaceChildren(form);
              copy.querySelector('h3').textContent=(mode==='edit'?'Edit ':'Add ')+title;
              host.classList.add('is-open'); close.focus();
            }};
            const closeModal=()=>{{
              host.classList.remove('is-open'); releaseTimetableScrollLock();
              formSlot.replaceChildren(...(addForm?[addForm]:[]));
              copy.querySelector('h3').textContent='Add '+title;
              if(open) open.focus();
            }};
            if(open) open.addEventListener('click',()=>openModal(addForm,'add'));
            close.addEventListener('click',closeModal);
            host.addEventListener('click',e=>{{if(e.target===host)closeModal();}});
            host.addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal();}});
            section.querySelectorAll('.tt-table details').forEach(details=>{{
              const summary=details.querySelector('summary');
              const editForm=details.querySelector('form[method="post" i]');
              if(!summary||!editForm) return;
              summary.addEventListener('click',event=>{{
                event.preventDefault();
                event.stopPropagation();
                openModal(editForm,'edit');
              }});
            }});
          }});
          // Keep every setup panel collapsed on initial page load.
          // A panel opens only after its own Open section control is activated.
          root.querySelectorAll('.tt-section').forEach(section=>{{
            const heading=section.querySelector('.tt-section-title');
            if(!heading) return;
            const content=document.createElement('div');
            content.className='tt-section-content';
            let node=heading.nextSibling;
            while(node){{
              const next=node.nextSibling;
              content.appendChild(node);
              node=next;
            }}
            section.appendChild(content);
            content.hidden=true;
            section.classList.remove('tt-step-open');
            const toggle=document.createElement('button');
            toggle.type='button';
            toggle.className='tt-section-toggle';
            toggle.setAttribute('aria-expanded','false');
            toggle.innerHTML='<span class="tt-toggle-label">Open section</span><span class="tt-chevron" aria-hidden="true">⌄</span>';
            heading.appendChild(toggle);
            toggle.addEventListener('click',()=>{{
              const opening=content.hidden;
              content.hidden=!opening;
              section.classList.toggle('tt-step-open',opening);
              toggle.setAttribute('aria-expanded',opening?'true':'false');
              toggle.querySelector('.tt-toggle-label').textContent=opening?'Close section':'Open section';
            }});
          }});
        }})();
        </script>
        """
        return module_page(request, "Timetable Setup", "timetable", body)


    @app.get("/app/timetable/constraints", response_class=HTMLResponse)
    def timetable_constraints_page(request: Request, profile_id: int = 0, message: str = "", error: int = 0):
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
        selected = next((p for p in profiles if int(p["id"]) == int(profile_id)), None) or next(
            (p for p in profiles if str(p["status"] or "draft").lower() == "draft"), None
        ) or (profiles[0] if profiles else None)
        if not selected:
            con.close()
            return module_page(request, "Timetable Constraints", "timetable",
                "<div class='tt-empty'><h2>Create a timetable profile first</h2><a href='/app/timetable/setup'>Open timetable setup</a></div>")
        pid = int(selected["id"])
        days = cur.execute("SELECT id,day_name FROM ds_timetable_days WHERE school_id=? AND profile_id=? ORDER BY day_order", (school_id,pid)).fetchall()
        periods = cur.execute("SELECT id,label FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no", (school_id,pid)).fetchall()
        classes = cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream", (school_id,)).fetchall()
        teachers = cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
        subjects = cur.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
        rooms = cur.execute("SELECT id,name FROM ds_timetable_rooms WHERE school_id=? AND is_active=1 ORDER BY name", (school_id,)).fetchall()
        rules = cur.execute(
            """SELECT r.*,s.name subject_name,t.name teacher_name,c.name class_name,d.day_name,p.label period_label,rm.name room_name
               FROM ds_timetable_constraints r
               LEFT JOIN subjects s ON s.id=r.subject_id AND s.school_id=r.school_id
               LEFT JOIN teachers t ON t.id=r.teacher_id AND t.school_id=r.school_id
               LEFT JOIN classes c ON c.id=r.class_id AND c.school_id=r.school_id
               LEFT JOIN ds_timetable_days d ON d.id=r.day_id AND d.profile_id=r.profile_id
               LEFT JOIN ds_timetable_periods p ON p.id=r.period_id AND p.profile_id=r.profile_id
               LEFT JOIN ds_timetable_rooms rm ON rm.id=r.room_id AND rm.school_id=r.school_id
               WHERE r.school_id=? AND r.profile_id=? ORDER BY r.is_active DESC,r.name""",
            (school_id,pid),
        ).fetchall()
        con.close()
        esc = lambda v: escape(str(v if v is not None else ""))
        option = lambda rows, label: "<option value=''>Any " + label + "</option>" + "".join(
            f"<option value='{int(row['id'])}'>{esc(row['name'] if 'name' in row.keys() else row[label])}</option>" for row in rows
        )
        class_opts = "<option value=''>Any class</option>" + "".join(f"<option value='{int(x['id'])}'>{esc(x['name'])} {esc(x['stream'] or '')}</option>" for x in classes)
        day_opts = "<option value=''>Any day</option>" + "".join(f"<option value='{int(x['id'])}'>{esc(x['day_name'])}</option>" for x in days)
        period_opts = "<option value=''>Any period</option>" + "".join(f"<option value='{int(x['id'])}'>{esc(x['label'])}</option>" for x in periods)
        teacher_opts = option(teachers, "teacher")
        subject_opts = option(subjects, "subject")
        room_opts = option(rooms, "room")
        notice = f"<div class='tt-alert {'error' if error else 'success'}'>{esc(message)}</div>" if message else ""
        rule_rows = "".join(
            f"<tr><td><b>{esc(r['name'])}</b><small>{esc(r['reason'] or '')}</small></td><td>{esc(r['subject_name'] or 'Any subject')} · {esc(r['teacher_name'] or 'Any teacher')} · {esc(r['class_name'] or 'Any class')}</td><td>{esc(r['day_name'] or 'Any day')} · {esc(r['period_label'] or 'Any period')}</td><td>{esc(r['start_time'] or 'Any start')}–{esc(r['end_time'] or 'Any end')}</td><td>{'Active' if int(r['is_active'] or 0) else 'Inactive'}</td></tr>"
            for r in rules
        ) or "<tr><td colspan='5'>No constraints have been configured for this profile yet.</td></tr>"
        body = f"""
        <style>
          .tt-constraints{{max-width:1400px;margin:auto;color:#23443a}}.tt-constraints .panel{{background:#fff;border:1px solid #e1ebe4;border-radius:18px;padding:22px;margin:16px 0;box-shadow:0 8px 24px #244d3510}}
          .tt-constraints h2{{margin:0 0 8px}}.tt-constraints p{{color:#667b70}}.tt-constraints .fields{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}
          .tt-constraints label{{display:block;font-size:12px;font-weight:700;margin:0 0 6px}}.tt-constraints input,.tt-constraints select{{width:100%;padding:11px;border:1px solid #d9e5dc;border-radius:10px;background:#fbfdfb;color:#244338}}
          .tt-constraints button{{border:0;border-radius:10px;background:#527d66;color:white;padding:12px 20px;font-weight:700;cursor:pointer;margin-top:14px}}
          .tt-constraints table{{width:100%;border-collapse:collapse;font-size:13px}}.tt-constraints td,.tt-constraints th{{padding:12px;border-bottom:1px solid #e9eee9;text-align:left}}.tt-constraints small{{display:block;color:#728478}}
          .tt-constraints .notice{{padding:12px;border-radius:10px;background:#eff6ef;margin:12px 0}}@media(max-width:650px){{.tt-constraints .table-wrap{{overflow:auto}}}}
        </style>
        <div class='tt-constraints'><h2>Scheduling constraints</h2>
        <p>Define hard rules that the automatic generator must obey and the manual builder must reject. Leave a target blank to apply the rule more broadly.</p>
        {notice}
        <form class='panel' method='post' action='/app/timetable/constraints'>
          <input type='hidden' name='profile_id' value='{pid}'>
          <div class='fields'>
            <div><label>Constraint name</label><input name='name' required maxlength='120' placeholder='e.g. No Mathematics after lunch'></div>
            <div><label>Rule behavior</label><select name='constraint_type'><option value='prohibit'>Prohibit this time</option><option value='require'>Require this time</option><option value='prefer'>Prefer this time (soft rule)</option></select></div>
            <div><label>Applies to</label><select name='applies_to'><option value='all'>All sessions</option><option value='lesson'>Ordinary lessons</option><option value='remedial'>Remedial lessons</option><option value='activity'>Activities</option></select></div>
            <div><label>Timetable layer</label><select name='schedule_layer'><option value='all'>All layers</option><option value='instructional'>Instructional</option><option value='additional_learning'>Additional learning</option><option value='school_activity'>School activities</option></select></div>
            <div><label>Subject</label><select name='subject_id'>{subject_opts}</select></div>
            <div><label>Teacher</label><select name='teacher_id'>{teacher_opts}</select></div>
            <div><label>Class / stream</label><select name='class_id'>{class_opts}</select></div>
            <div><label>Room / facility</label><select name='room_id'>{room_opts}</select></div>
            <div><label>Day</label><select name='day_id'>{day_opts}</select></div>
            <div><label>Period</label><select name='period_id'>{period_opts}</select></div>
            <div><label>Not before (optional)</label><input type='time' name='start_time'></div>
            <div><label>Not after (optional)</label><input type='time' name='end_time'></div>
            <div><label>Effective from</label><input type='date' name='effective_from'></div>
            <div><label>Effective until</label><input type='date' name='effective_to'></div>
            <div style='grid-column:1/-1'><label>Reason / instruction</label><input name='reason' placeholder='Explain why this time is blocked'></div>
          </div><button type='submit'>Save constraint</button>
        </form>
        <section class='panel'><h2>Configured rules</h2><div class='table-wrap'><table><thead><tr><th>Rule</th><th>Target</th><th>Day / period</th><th>Time window</th><th>Status</th></tr></thead><tbody>{rule_rows}</tbody></table></div></section>
        <p><a href='/app/timetable/setup?profile_id={pid}'>← Back to timetable setup</a></p></div>
        """
        return module_page(request, "Timetable Constraints", "timetable", body)

    @app.post("/app/timetable/constraints")
    def create_timetable_constraint(request: Request, profile_id: int = Form(...),
        name: str = Form(...), constraint_type: str = Form("prohibit"),
        applies_to: str = Form("all"), schedule_layer: str = Form("all"),
        subject_id: str = Form(""), teacher_id: str = Form(""), class_id: str = Form(""),
        room_id: str = Form(""), day_id: str = Form(""), period_id: str = Form(""),
        start_time: str = Form(""), end_time: str = Form(""), effective_from: str = Form(""),
        effective_to: str = Form(""), reason: str = Form("")):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_timetable_constraint(
                con, int(school["id"]), profile_id, name, constraint_type, applies_to, schedule_layer,
                int(subject_id) if subject_id else None, int(teacher_id) if teacher_id else None,
                int(class_id) if class_id else None, int(room_id) if room_id else None,
                int(day_id) if day_id else None, int(period_id) if period_id else None,
                start_time or None, end_time or None, effective_from or None, effective_to or None, reason,
            )
            return RedirectResponse(f"/app/timetable/constraints?profile_id={profile_id}&message=Constraint%20saved", 303)
        except (TimetableSetupError, ValueError) as exc:
            return RedirectResponse(f"/app/timetable/constraints?profile_id={profile_id}&error=1&message={quote(str(exc))}", 303)
        finally:
            con.close()

    @app.post("/app/timetable/setup/row-delete")
    def delete_timetable_setup_row(
        request: Request,
        profile_id: int = Form(...),
        kind: str = Form(...),
        row_id: int = Form(...),
    ):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            school_id = int(school["id"])
            cur = con.cursor()
            _profile(cur, school_id, profile_id)
            targets = {
                "day": ("ds_timetable_days", "profile"),
                "period": ("ds_timetable_periods", "profile"),
                "break": ("ds_timetable_breaks", "profile"),
                "calendar": ("ds_timetable_calendar_exceptions", "profile"),
                "room": ("ds_timetable_rooms", "school"),
                "availability": ("ds_timetable_teacher_availability", "profile"),
                "subject_availability": ("ds_timetable_subject_availability", "profile"),
                "requirement": ("ds_timetable_class_requirements", "profile"),
                "class_limit": ("ds_timetable_class_limits", "profile"),
            }
            if kind not in targets:
                raise TimetableSetupError("That setup row cannot be deleted from this page.")
            table, scope = targets[kind]
            where = "id=? AND school_id=?" + (" AND profile_id=?" if scope == "profile" else "")
            params = (int(row_id), school_id, profile_id) if scope == "profile" else (int(row_id), school_id)
            record = cur.execute(f"SELECT id FROM {table} WHERE {where}", params).fetchone()
            if not record:
                raise TimetableSetupError("That row was not found in the selected timetable profile.")
            references = {
                "day": (("ds_timetable_teacher_availability", "day_id"),
                        ("ds_timetable_day_templates", "day_id"),
                        ("ds_timetable_lessons", "day_id"),
                        ("ds_timetable_sessions", "day_id"),
                        ("ds_timetable_constraints", "day_id")),
                "period": (("ds_timetable_teacher_availability", "period_id"),
                           ("ds_timetable_lessons", "period_id"),
                           ("ds_timetable_sessions", "period_id"),
                           ("ds_timetable_constraints", "period_id")),
                "room": (("ds_timetable_lessons", "room_id"),
                         ("ds_timetable_sessions", "room_id"),
                         ("ds_timetable_constraints", "room_id")),
            }
            if kind == "period":
                # Availability preferences and period-specific constraints are
                # setup metadata; remove them with the period. Actual scheduled
                # lessons/sessions must be reassigned before a period is removed.
                for ref_table in ("ds_timetable_lessons", "ds_timetable_sessions"):
                    used = cur.execute(
                        f"SELECT 1 FROM {ref_table} WHERE school_id=? AND profile_id=? AND period_id=? LIMIT 1",
                        (school_id, int(profile_id), int(row_id)),
                    ).fetchone()
                    if used:
                        raise TimetableSetupError(
                            "This teaching period is already used by a scheduled lesson or timetable session. Reassign those lessons first."
                        )
                cur.execute(
                    "DELETE FROM ds_timetable_teacher_availability WHERE school_id=? AND profile_id=? AND period_id=?",
                    (school_id, int(profile_id), int(row_id)),
                )
                cur.execute(
                    "DELETE FROM ds_timetable_constraints WHERE school_id=? AND profile_id=? AND period_id=?",
                    (school_id, int(profile_id), int(row_id)),
                )
            else:
                for ref_table, ref_column in references.get(kind, ()):
                    used = cur.execute(
                        f"SELECT 1 FROM {ref_table} WHERE school_id=? AND {ref_column}=? LIMIT 1",
                        (school_id, int(row_id)),
                    ).fetchone()
                    if used:
                        raise TimetableSetupError(
                            "This row is already used by timetable records. Remove or reassign those records first."
                        )
            cur.execute(f"DELETE FROM {table} WHERE {where}", params)
            con.commit()
            return redirect_setup(profile_id, "Setup row deleted.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_setup(profile_id, str(exc), True)
        finally:
            con.close()

    # Compatibility endpoint: older cached setup pages submitted to the page URL.
    # Keep this alias so profile creation cannot fail with 405 on stale markup.
    @app.post("/app/timetable/setup")
    @app.post("/app/timetable/setup/profile")
    def create_timetable_profile(request: Request, name: str = Form(...), academic_year: str = Form(...), term: str = Form(...), academic_start_date: str = Form(""), academic_end_date: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            pid = create_profile(con, int(school["id"]), name, academic_year, term, request.session.get("email", ""), academic_start_date, academic_end_date)
            return redirect_setup(pid, "Timetable profile created. Configure the school days and periods next.")
        except TimetableSetupError as exc:
            return redirect_setup(message=str(exc), error=True)
        finally:
            con.close()

    @app.post("/app/timetable/setup/standard-week")
    def create_standard_week(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            for order, (code, name) in enumerate((("MON","Monday"),("TUE","Tuesday"),("WED","Wednesday"),("THU","Thursday"),("FRI","Friday")), 1):
                save_day(con, int(school["id"]), profile_id, code, name, order, True)
            return redirect_setup(profile_id, "Standard Monday–Friday school week saved.")
        except TimetableSetupError as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/setup/day")
    def create_timetable_day(request: Request, profile_id: int = Form(...), day_name: str = Form(...), day_code: str = Form(...), day_order: int = Form(...), instructional: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_day(con, int(school["id"]), profile_id, day_code, day_name, day_order, instructional == "1")
            return redirect_setup(profile_id, "School day saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/setup/period")
    def create_timetable_period(request: Request, profile_id: int = Form(...), period_no: int = Form(...), label: str = Form(...), start_time: str = Form(...), end_time: str = Form(...), period_type: str = Form("lesson")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_period(con, int(school["id"]), profile_id, period_no, label, start_time, end_time, period_type)
            return redirect_setup(profile_id, "Teaching period saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/setup/break-gap")
    def select_timetable_break_gap(request: Request, profile_id: int = Form(...),
        label: str = Form(...), start_time: str = Form(...), end_time: str = Form(...)):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            cur = con.cursor()
            _profile(cur, int(school["id"]), profile_id)
            periods = cur.execute(
                "SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY start_time,period_no",
                (int(school["id"]), profile_id),
            ).fetchall()
            valid_gaps = {(str(a["end_time"]), str(b["start_time"])) for a,b in zip(periods, periods[1:]) if str(a["end_time"]) < str(b["start_time"])}
            if (start_time, end_time) not in valid_gaps:
                raise TimetableSetupError("That gap is no longer available. Refresh and select a current detected gap.")
            exists = cur.execute(
                "SELECT id FROM ds_timetable_breaks WHERE school_id=? AND profile_id=? AND start_time=? AND end_time=?",
                (int(school["id"]), profile_id, start_time, end_time),
            ).fetchone()
            if exists:
                raise TimetableSetupError("That break gap has already been selected.")
            next_no = int(cur.execute(
                "SELECT COALESCE(MAX(break_no),0)+1 FROM ds_timetable_breaks WHERE school_id=? AND profile_id=?",
                (int(school["id"]), profile_id),
            ).fetchone()[0])
            save_break(con, int(school["id"]), profile_id, next_no, label, start_time, end_time, "all")
            return redirect_setup(profile_id, "Detected break gap selected. Other gaps remain available.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally:
            con.close()

    @app.post("/app/timetable/setup/break")
    def create_timetable_break(request: Request, profile_id: int = Form(...), break_no: int = Form(...), label: str = Form(...), start_time: str = Form(...), end_time: str = Form(...), applies_to: str = Form("all")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_break(con, int(school["id"]), profile_id, break_no, label, start_time, end_time, applies_to)
            return redirect_setup(profile_id, "Break saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/setup/calendar-event")
    def create_timetable_calendar_event(request: Request, profile_id: int = Form(...), exception_date: str = Form(...), label: str = Form(...), exception_type: str = Form("holiday"), notes: str = Form(""), instructional: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_calendar_exception(con, int(school["id"]), profile_id, exception_date, label, exception_type, notes, instructional == "1")
            return redirect_setup(profile_id, "Academic calendar date saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/setup/room")
    def create_timetable_room(request: Request, room_code: str = Form(...), name: str = Form(...), room_type: str = Form("classroom"), capacity: str = Form(""), description: str = Form(""), equipment: str = Form(""), suitable_for: str = Form(""), profile_id: int = Form(0)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_room(con, int(school["id"]), room_code, name, room_type, int(capacity) if capacity.strip() else None, description, equipment, suitable_for)
            return redirect_setup(profile_id, "Room or facility saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(message=str(exc), error=True)
        finally: con.close()

    @app.post("/app/timetable/setup/availability-matrix")
    def save_timetable_availability_matrix(request: Request, profile_id: int = Form(...), teacher_id: int = Form(...), cell_status: list[str] = Form([])):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            teacher = con.execute("SELECT id FROM teachers WHERE id=? AND school_id=?", (teacher_id, int(school["id"]))).fetchone()
            if not teacher:
                raise TimetableSetupError("Select a valid teacher.")
            configured_days = {int(r["id"]) for r in con.execute("SELECT id FROM ds_timetable_days WHERE school_id=? AND profile_id=?", (int(school["id"]), profile_id)).fetchall()}
            configured_periods = {int(r["id"]) for r in con.execute("SELECT id FROM ds_timetable_periods WHERE school_id=? AND profile_id=?", (int(school["id"]), profile_id)).fetchall()}
            for item in cell_status:
                parts = item.split("|", 2)
                if len(parts) != 3:
                    continue
                day_id, period_id = int(parts[0]), int(parts[1])
                status = parts[2].strip()
                if day_id not in configured_days or period_id not in configured_periods or status not in ("", "available", "unavailable"):
                    raise TimetableSetupError("The availability matrix contains an invalid day, period or status.")
                stored_status = status or "fallback"
                con.execute(
                    """INSERT INTO ds_timetable_teacher_availability
                       (school_id,profile_id,teacher_id,day_id,period_id,availability,reason)
                       VALUES(?,?,?,?,?,?, '')
                       ON CONFLICT(school_id,profile_id,teacher_id,day_id,period_id)
                       DO UPDATE SET availability=excluded.availability,reason=''""",
                    (int(school["id"]), profile_id, teacher_id, day_id, period_id, stored_status),
                )
            con.commit()
            return redirect_setup(profile_id, "Teacher availability matrix saved.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_setup(profile_id, str(exc), True)
        finally:
            con.close()

    @app.post("/app/timetable/setup/subject-availability-matrix")
    def save_timetable_subject_availability_matrix(request: Request, profile_id: int = Form(...), subject_id: int = Form(...), cell_status: list[str] = Form([])):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            subject = con.execute("SELECT id FROM subjects WHERE id=? AND school_id=?", (subject_id, int(school["id"]))).fetchone()
            if not subject:
                raise TimetableSetupError("Select a valid subject.")
            configured_days = {int(r["id"]) for r in con.execute("SELECT id FROM ds_timetable_days WHERE school_id=? AND profile_id=?", (int(school["id"]), profile_id)).fetchall()}
            configured_periods = {int(r["id"]) for r in con.execute("SELECT id FROM ds_timetable_periods WHERE school_id=? AND profile_id=?", (int(school["id"]), profile_id)).fetchall()}
            for item in cell_status:
                parts = item.split("|", 2)
                if len(parts) != 3: continue
                day_id, period_id = int(parts[0]), int(parts[1])
                status = parts[2].strip()
                if day_id not in configured_days or period_id not in configured_periods or status not in ("", "available", "unavailable"):
                    raise TimetableSetupError("The subject availability matrix contains an invalid day, period or status.")
                if status == "available":
                    con.execute("DELETE FROM ds_timetable_subject_availability WHERE school_id=? AND profile_id=? AND subject_id=? AND day_id=? AND period_id=?", (int(school["id"]), profile_id, subject_id, day_id, period_id))
                else:
                    stored_status = status or "fallback"
                    con.execute(
                        """INSERT INTO ds_timetable_subject_availability
                           (school_id,profile_id,subject_id,day_id,period_id,availability)
                           VALUES(?,?,?,?,?,?)
                           ON CONFLICT(school_id,profile_id,subject_id,day_id,period_id)
                           DO UPDATE SET availability=excluded.availability""",
                        (int(school["id"]), profile_id, subject_id, day_id, period_id, stored_status),
                    )
            con.commit()
            return redirect_setup(profile_id, "Subject availability matrix saved.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_setup(profile_id, str(exc), True)
        finally:
            con.close()

    @app.post("/app/timetable/setup/availability")
    def create_timetable_availability(request: Request, profile_id: int = Form(...), teacher_id: int = Form(...), day_id: int = Form(...), period_id: int = Form(...), availability: str = Form(...), reason: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_teacher_availability(con, int(school["id"]), profile_id, teacher_id, day_id, period_id, availability, reason)
            return redirect_setup(profile_id, "Teacher availability saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()

    @app.post("/app/timetable/setup/requirements/bulk")
    def create_timetable_requirements_bulk(
        request: Request,
        profile_id: int = Form(...),
        subject_ids: list[int] = Form(...),
        lessons_per_week: int = Form(5),
        duration_periods: int = Form(1),
        max_lessons_per_day: str = Form(""),
        allow_double: str = Form(""),
    ):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            selected, created, preserved = save_subject_requirements(
                con, int(school["id"]), profile_id, subject_ids,
                lessons_per_week, duration_periods,
                int(max_lessons_per_day) if max_lessons_per_day.strip() else None,
                allow_double == "1",
            )
            return redirect_setup(
                profile_id,
                f"Subject requirements applied: {selected} subject(s), {created} class/teacher requirements added; {preserved} existing customized requirements preserved.",
            )
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally:
            con.close()

    @app.post("/app/timetable/setup/class-limits")
    def create_class_timetable_limits(request: Request, profile_id: int = Form(...),
        class_id: int = Form(...), max_lessons_per_week: str = Form(""),
        max_periods_per_day: str = Form(""), notes: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_class_limits(
                con, int(school["id"]), profile_id, class_id,
                int(max_lessons_per_week) if max_lessons_per_week.strip() else None,
                int(max_periods_per_day) if max_periods_per_day.strip() else None,
                notes,
            )
            return redirect_setup(profile_id, "Class workload limits saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally:
            con.close()

    @app.post("/app/timetable/setup/requirement")
    def create_timetable_requirement(request: Request, profile_id: int = Form(...), allocation: str = Form(...), lessons_per_week: int = Form(...), duration_periods: int = Form(1), max_lessons_per_day: str = Form(""), allow_double: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            parts = allocation.split("|")
            if len(parts) != 3:
                raise TimetableSetupError("Select a valid teacher allocation.")
            class_id, subject_id, teacher_id = (int(part) for part in parts)
            save_class_requirement(con, int(school["id"]), profile_id, class_id, subject_id, teacher_id, lessons_per_week, duration_periods, int(max_lessons_per_day) if max_lessons_per_day.strip() else None, allow_double == "1")
            return redirect_setup(profile_id, "Weekly lesson requirement saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True)
        finally: con.close()
