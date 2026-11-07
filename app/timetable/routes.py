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
)


def register_timetable_setup_routes(app, get_db, get_school_obj, module_page):
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
        days = periods = breaks = calendar_events = rooms = teachers = allocations = availability = requirements = []
        if selected:
            pid = int(selected["id"])
            days = cur.execute("SELECT * FROM ds_timetable_days WHERE school_id=? AND profile_id=? ORDER BY day_order,id", (school_id,pid)).fetchall()
            periods = cur.execute("SELECT * FROM ds_timetable_periods WHERE school_id=? AND profile_id=? ORDER BY period_no,id", (school_id,pid)).fetchall()
            breaks = cur.execute("SELECT * FROM ds_timetable_breaks WHERE school_id=? AND profile_id=? ORDER BY break_no,id", (school_id,pid)).fetchall()
            calendar_events = cur.execute("SELECT * FROM ds_timetable_calendar_exceptions WHERE school_id=? AND profile_id=? ORDER BY exception_date,label", (school_id,pid)).fetchall()
            rooms = cur.execute("SELECT * FROM ds_timetable_rooms WHERE school_id=? AND is_active=1 ORDER BY name", (school_id,)).fetchall()
            teachers = cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
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
                   WHERE a.school_id=? AND a.profile_id=? ORDER BY d.day_order,p.period_no,t.name""",
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
        day_rows = "".join(f"<tr><td>{esc(d['day_order'])}</td><td><b>{esc(d['day_name'])}</b></td><td>{esc(d['day_code'])}</td><td>{'Instructional' if d['is_instructional'] else 'Non-instructional'}</td></tr>" for d in days) or "<tr><td colspan='4' class='tt-muted'>No school days configured.</td></tr>"
        period_rows = "".join(f"<tr><td>{esc(p['period_no'])}</td><td><b>{esc(p['label'])}</b></td><td>{esc(p['start_time'])}–{esc(p['end_time'])}</td><td>{esc(p['duration_minutes'])} min</td><td>{esc(p['period_type'])}</td></tr>" for p in periods) or "<tr><td colspan='5' class='tt-muted'>No periods configured.</td></tr>"
        break_rows = "".join(f"<tr><td>{esc(b['break_no'])}</td><td><b>{esc(b['label'])}</b></td><td>{esc(b['start_time'])}–{esc(b['end_time'])}</td><td>{esc(b['applies_to'])}</td></tr>" for b in breaks) or "<tr><td colspan='4' class='tt-muted'>No breaks configured.</td></tr>"
        calendar_rows = "".join(f"<tr><td>{esc(e['exception_date'])}</td><td><b>{esc(e['label'])}</b></td><td>{esc(e['exception_type'])}</td><td>{'Instructional' if e['is_instructional'] else 'Non-instructional'}</td><td>{esc(e['notes'] or '—')}</td></tr>" for e in calendar_events) or "<tr><td colspan='5' class='tt-muted'>No calendar exceptions configured.</td></tr>"
        room_rows = "".join(f"<tr><td><b>{esc(r['room_code'])}</b></td><td>{esc(r['name'])}</td><td>{esc(r['room_type'])}</td><td>{esc(r['capacity'] or '—')}</td></tr>" for r in rooms) or "<tr><td colspan='4' class='tt-muted'>No rooms configured.</td></tr>"
        day_opts = "".join(f"<option value='{int(d['id'])}'>{esc(d['day_name'])}</option>" for d in days)
        period_opts = "".join(f"<option value='{int(p['id'])}'>{esc(p['label'])} ({esc(p['start_time'])}–{esc(p['end_time'])})</option>" for p in periods)
        teacher_opts = "".join(f"<option value='{int(t['id'])}'>{esc(t['name'])}</option>" for t in teachers)
        allocation_opts = "".join(f"<option value='{int(a['class_id'])}|{int(a['subject_id'])}|{int(a['teacher_id'])}'>{esc(a['class_name'])} {esc(a['stream'] or '')} · {esc(a['subject_name'])} · {esc(a['teacher_name'])}</option>" for a in allocations)
        availability_rows = "".join(f"<tr><td>{esc(a['teacher_name'])}</td><td>{esc(a['day_name'])}</td><td>{esc(a['period_label'])}</td><td><span class='tt-pill'>{esc(a['availability'])}</span></td><td>{esc(a['reason'] or '—')}</td></tr>" for a in availability) or "<tr><td colspan='5' class='tt-muted'>No teacher availability rules yet.</td></tr>"
        requirement_rows = "".join(f"<tr><td>{esc(r['class_name'])} {esc(r['stream'] or '')}</td><td>{esc(r['subject_name'])}</td><td>{esc(r['teacher_name'])}</td><td>{esc(r['lessons_per_week'])}</td><td>{esc(r['duration_periods'])}</td><td>{'Yes' if r['allow_double'] else 'No'}</td></tr>" for r in requirements) or "<tr><td colspan='6' class='tt-muted'>No weekly lesson requirements configured.</td></tr>"

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
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>01 · SCHOOL WEEK</span><h3>School days</h3><p>Set instructional days and their order.</p></div><form method='post' data-native-post='true' action='/app/timetable/setup/standard-week'>{hidden}<button class='tt-btn secondary'>Add Monday–Friday</button></form></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/day' class='tt-form compact'>{hidden}<label>Day name<input name='day_name' required placeholder='Saturday'></label><label>Day code<input name='day_code' required maxlength='8' placeholder='SAT'></label><label>Display order<input name='day_order' required type='number' min='1' max='7' value='6'></label><label class='tt-check'><input type='checkbox' name='instructional' value='1' checked> Instructional day</label><button class='tt-btn'>Save day</button></form><div class='tt-table'><table><tr><th>Order</th><th>Day</th><th>Code</th><th>Type</th></tr>{day_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>02 · DAILY STRUCTURE</span><h3>Teaching periods</h3><p>Define period numbering and exact time boundaries.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/period' class='tt-form compact'>{hidden}<label>Period number<input name='period_no' type='number' min='1' max='30' required></label><label>Period label<input name='label' required placeholder='Period 1'></label><label>Start time<input name='start_time' type='time' required value='08:00'></label><label>End time<input name='end_time' type='time' required value='08:40'></label><label>Period type<select name='period_type'><option value='lesson'>Lesson</option><option value='study'>Study</option><option value='assembly'>Assembly</option></select></label><button class='tt-btn'>Save period</button></form><div class='tt-table'><table><tr><th>#</th><th>Period</th><th>Time</th><th>Duration</th><th>Type</th></tr>{period_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>03 · NON-TEACHING TIME</span><h3>Breaks and lunch</h3><p>Prevent lesson allocation during configured breaks.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/break' class='tt-form compact'>{hidden}<label>Break number<input name='break_no' type='number' min='1' max='20' required></label><label>Break name<input name='label' required placeholder='Tea break'></label><label>Start time<input name='start_time' type='time' required value='10:00'></label><label>End time<input name='end_time' type='time' required value='10:20'></label><label>Applies to<select name='applies_to'><option value='all'>All classes</option><option value='selected'>Selected groups (configure later)</option></select></label><button class='tt-btn'>Save break</button></form><div class='tt-table'><table><tr><th>#</th><th>Break</th><th>Time</th><th>Scope</th></tr>{break_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>04 · ACADEMIC CALENDAR</span><h3>Holidays and special dates</h3><p>Mark closures, holidays and exceptional instructional days inside this term.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/calendar-event' class='tt-form compact'>{hidden}<label>Date<input name='exception_date' type='date' required></label><label>Event name<input name='label' required placeholder='National holiday'></label><label>Event type<select name='exception_type'><option value='holiday'>Public / school holiday</option><option value='school_closure'>School closure</option><option value='special_instructional_day'>Special instructional day</option><option value='event'>School event</option></select></label><label>Notes<input name='notes' maxlength='180' placeholder='Optional details'></label><label class='tt-check'><input type='checkbox' name='instructional' value='1'> Instructional day</label><button class='tt-btn'>Save calendar date</button></form><div class='tt-table'><table><tr><th>Date</th><th>Event</th><th>Type</th><th>Day type</th><th>Notes</th></tr>{calendar_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>05 · LEARNING SPACES</span><h3>Rooms and facilities</h3><p>Register classrooms, laboratories, halls and specialist spaces.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/room' class='tt-form compact'>{hidden}<label>Room code<input name='room_code' required placeholder='LAB-01'></label><label>Room name<input name='name' required placeholder='Science Laboratory'></label><label>Room type<select name='room_type'><option value='classroom'>Classroom</option><option value='laboratory'>Laboratory</option><option value='library'>Library</option><option value='hall'>Hall</option><option value='workshop'>Workshop</option><option value='sports'>Sports facility</option><option value='other'>Other</option></select></label><label>Capacity<input name='capacity' type='number' min='1' placeholder='40'></label><button class='tt-btn'>Save room</button></form><div class='tt-table'><table><tr><th>Code</th><th>Room</th><th>Type</th><th>Capacity</th></tr>{room_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>06 · STAFF AVAILABILITY</span><h3>Teacher availability</h3><p>Mark unavailable or preferred teacher periods.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/availability' class='tt-form compact'>{hidden}<label>Teacher<select name='teacher_id' required><option value=''>Select teacher</option>{teacher_opts}</select></label><label>Day<select name='day_id' required><option value=''>Select day</option>{day_opts}</select></label><label>Period<select name='period_id' required><option value=''>Select period</option>{period_opts}</select></label><label>Availability<select name='availability'><option value='unavailable'>Unavailable</option><option value='preferred'>Preferred</option><option value='available'>Available</option></select></label><label>Reason<input name='reason' maxlength='160' placeholder='e.g. Part-time availability'></label><button class='tt-btn'>Save availability</button></form><div class='tt-table'><table><tr><th>Teacher</th><th>Day</th><th>Period</th><th>Status</th><th>Reason</th></tr>{availability_rows}</table></div></div></section>
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>07 · WEEKLY LESSON LOAD</span><h3>Class subject requirements</h3><p>Set weekly lesson frequency using existing teacher allocations.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/requirement' class='tt-form compact'>{hidden}<label class='wide'>Allocated class · subject · teacher<select name='allocation' required><option value=''>Select existing allocation</option>{allocation_opts}</select></label><label>Lessons per week<input name='lessons_per_week' type='number' min='1' max='30' required value='5'></label><label>Duration<select name='duration_periods'><option value='1'>Single period</option><option value='2'>Double period</option><option value='3'>Triple period</option></select></label><label>Maximum per day<input name='max_lessons_per_day' type='number' min='1' max='10' placeholder='No limit'></label><label class='tt-check'><input type='checkbox' name='allow_double' value='1'> Allow double lessons</label><button class='tt-btn'>Save requirement</button></form><div class='tt-table'><table><tr><th>Class / Stream</th><th>Subject</th><th>Teacher</th><th>Weekly</th><th>Duration</th><th>Double</th></tr>{requirement_rows}</table></div></div></section>
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
        .tt-btn{{border:0;border-radius:10px;padding:11px 15px;background:linear-gradient(135deg,#347c50,#246441);color:white;text-decoration:none!important;font-weight:800;font-size:12px;cursor:pointer;min-height:40px;display:inline-flex;align-items:center;justify-content:center;gap:7px;box-shadow:0 5px 12px rgba(35,102,62,.13);transition:transform .16s,box-shadow .16s}}
        .tt-btn:hover{{background:linear-gradient(135deg,#286b43,#1d5636);transform:translateY(-1px);box-shadow:0 8px 16px rgba(35,102,62,.18)}}
        .tt-btn.secondary{{background:#edf6ee;color:#2a6a43;border:1px solid #cfe2d2;box-shadow:none}}.tt-btn.secondary:hover{{background:#e2f0e4}}
        .tt-add-card{{min-height:100%;display:flex;align-items:center}}.tt-add-card .tt-btn{{width:100%;min-height:74px;white-space:normal;text-align:center}}
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
        .tt-modal{{position:fixed;inset:0;z-index:10050;display:none;align-items:center;justify-content:center;padding:18px;background:rgba(20,43,30,.48);backdrop-filter:blur(5px)}}.tt-modal.is-open{{display:flex;animation:ttFade .16s ease-out}}.tt-modal:target{{display:flex;animation:ttFade .16s ease-out}}.tt-profile-create-card>.tt-btn{{margin-top:12px;text-decoration:none!important}}.tt-modal-close{{display:grid;place-items:center;text-decoration:none!important}}
        .tt-modal-dialog{{position:relative;width:min(620px,100%);max-height:min(88vh,850px);overflow:auto;padding:25px;background:linear-gradient(145deg,#fff 0%,#f4faf4 100%);border:1px solid #d5e6d8;border-radius:22px;box-shadow:0 24px 70px rgba(18,52,31,.25);animation:ttPop .18s ease-out}}
        .tt-modal-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:19px}}.tt-modal-head h3{{font-size:20px;margin:4px 0;color:#214a34}}.tt-modal-head p{{font-size:12px;color:#718477;margin:0}}.tt-modal-close{{border:0;width:35px;height:35px;border-radius:11px;background:#eaf4eb;color:#326a43;font-size:21px;cursor:pointer;flex:none}}
        .tt-modal .tt-form{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tt-modal .tt-form label.wide{{grid-column:1/-1}}.tt-modal .tt-form button{{grid-column:1/-1;margin-top:4px}}
        @keyframes ttFade{{from{{opacity:0}}to{{opacity:1}}}}@keyframes ttPop{{from{{opacity:0;transform:translateY(9px) scale(.985)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
        @media(max-width:900px){{.tt-split{{grid-template-columns:1fr}}.tt-add-card .tt-btn{{min-height:48px}}.tt-form{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
        @media(max-width:600px){{.tt-wrap{{padding:12px;border-radius:17px}}.tt-hero{{padding:22px 18px}}.tt-hero h1{{font-size:24px}}.tt-form,.tt-form.compact,.tt-modal .tt-form{{grid-template-columns:1fr}}.tt-form label.wide,.tt-modal .tt-form label.wide{{grid-column:auto}}.tt-stats{{width:100%;justify-content:space-around}}.tt-modal{{padding:10px}}.tt-modal-dialog{{padding:20px 16px;border-radius:18px}}.tt-hero>div:last-child{{width:100%}}.tt-hero>div:last-child a{{flex:1}}}}
        </style>
        <div class='tt-wrap'><div class='tt-hero'><div><span class='tt-kicker'>DAVISCHOOL · SCHEDULING ENGINE</span><h1>Timetable Setup</h1><p>Set up your school week, teaching sessions, facilities and staffing rules in one guided workspace.</p></div><div style='display:flex;gap:8px;flex-wrap:wrap'><a class='tt-btn' href='/app/timetable/builder?profile_id={pid}'>Open Manual Builder</a><a class='tt-btn secondary' href='/app/timetable/publishing?profile_id={pid}'>Publishing & Versions</a></div></div>{notice}{selector}{profile_summary}{read_only_html}{create_profile_html if not has_draft_profile else ""}{sections}</div>
        <script>
        (function(){{
          const root=document.querySelector('.tt-wrap'); if(!root) return;
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
          let serial=0;
          root.querySelectorAll('.tt-section').forEach(section=>{{
            const form=section.querySelector('.tt-form.compact'); if(!form) return;
            const title=section.querySelector('h3')?.textContent?.trim()||'Add configuration';
            const modalId='tt-setup-modal-'+(++serial);
            const host=document.createElement('div'); host.className='tt-modal'; host.id=modalId; host.setAttribute('role','dialog'); host.setAttribute('aria-modal','true');
            const dialog=document.createElement('div'); dialog.className='tt-modal-dialog';
            const head=document.createElement('div'); head.className='tt-modal-head';
            const copy=document.createElement('div'); copy.innerHTML='<span class="tt-kicker">TIMETABLE CONFIGURATION</span><h3></h3><p>Complete the details below, then save your changes.</p>'; copy.querySelector('h3').textContent=title;
            const close=document.createElement('button'); close.type='button'; close.className='tt-modal-close'; close.setAttribute('aria-label','Close'); close.innerHTML='&times;';
            head.append(copy,close);
            const originalParent=form.parentNode;
            const card=document.createElement('div'); card.className='tt-add-card'; const open=document.createElement('button'); open.type='button'; open.className='tt-btn secondary'; open.innerHTML='<span aria-hidden="true">＋</span> Add '+title.toLowerCase(); card.append(open);
            originalParent.replaceChild(card,form);
            dialog.append(head,form); host.append(dialog); root.append(host);
            const closeModal=()=>{{host.classList.remove('is-open');document.body.style.overflow='';open.focus();}};
            open.addEventListener('click',()=>{{host.classList.add('is-open');document.body.style.overflow='hidden';close.focus();}});
            close.addEventListener('click',closeModal); host.addEventListener('click',e=>{{if(e.target===host)closeModal();}});
            host.addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal();}});
          }});
          // Turn the seven long setup panels into a compact, accessible accordion.
          // Keep the first step open; all remaining steps stay visible as concise headers.
          root.querySelectorAll('.tt-section').forEach((section,index)=>{{
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
            const toggle=document.createElement('button');
            toggle.type='button';
            toggle.className='tt-section-toggle';
            toggle.setAttribute('aria-expanded',index===0?'true':'false');
            toggle.innerHTML='<span class="tt-toggle-label">'+(index===0?'Close section':'Open section')+'</span><span class="tt-chevron" aria-hidden="true">⌄</span>';
            heading.appendChild(toggle);
            if(index!==0) content.hidden=true;
            else section.classList.add('tt-step-open');
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
    def create_timetable_room(request: Request, room_code: str = Form(...), name: str = Form(...), room_type: str = Form("classroom"), capacity: str = Form(""), profile_id: int = Form(0)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_room(con, int(school["id"]), room_code, name, room_type, int(capacity) if capacity.strip() else None)
            return redirect_setup(profile_id, "Room or facility saved.")
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(message=str(exc), error=True)
        finally: con.close()

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
