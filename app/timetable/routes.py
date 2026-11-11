"""Admin-facing configuration workspace for the DaviSchool timetable v2 engine."""
from __future__ import annotations

from html import escape
import json
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.setup import (
    TimetableSetupError,
    create_profile,
    update_profile,
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
from app.timetable.advanced_setup import save_timetable_constraint, save_requirement_session_pattern, create_scheduling_requirement, save_scheduling_pattern
from app.timetable.session_engine import create_teaching_group
from app.timetable.publishing import profile_display_name


def register_timetable_setup_routes(app, get_db, get_school_obj, module_page):
    from app.timetable.navigation import timetable_workspace
    _base_module_page = module_page
    def module_page(request, title, module, body):
        return _base_module_page(request, title, module, timetable_workspace(request, body))
    def school_for(request):
        if not request.session.get("email") or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
            return None
        return get_school_obj(request)

    def redirect_setup(profile_id=0, message="", error=False, focus="", request=None, tab="", section=""):
        parts = []
        if profile_id:
            parts.append("profile_id=" + str(int(profile_id)))
        if tab:
            parts.append("tab=" + quote(str(tab), safe=""))
        if section:
            parts.append("section=" + quote(str(section), safe=""))
        if message:
            parts.append("message=" + quote(str(message)))
        if error:
            parts.append("error=1")
        if request is not None:
            tab_id = str(request.scope.get("davischool_tab_id") or request.query_params.get("ds_tab") or "").strip()
            if tab_id:
                parts.append("ds_tab=" + quote(tab_id, safe=""))
        suffix = ("?" + "&".join(parts)) if parts else ""
        return RedirectResponse("/app/timetable/setup" + suffix, 303)

    @app.get("/app/timetable", response_class=HTMLResponse)
    def timetable_home(request: Request, profile_id: int = 0, message: str = "", error: int = 0):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        school_id = int(school["id"])
        con = get_db()
        cur = con.cursor()
        profiles = cur.execute(
            "SELECT * FROM ds_timetable_profiles WHERE school_id=? AND status IN ('draft','pending_approval','published') ORDER BY academic_year DESC,term,id DESC",
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
        home_tab_id = str(request.scope.get("davischool_tab_id") or request.query_params.get("ds_tab") or "")
        if selected:
            pid = int(selected["id"])
            profile_options = "".join(
                f"<option value='{int(p['id'])}' {'selected' if int(p['id']) == pid else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(profile_display_name(p['name']))} · {esc(str(p['profile_type'] or 'main').replace('_',' ').title())}</option>"
                for p in profiles
            )
            profile_control = f"<form class='tt-home-profile' method='get' action='/app/timetable'><label for='tt-home-profile'>Working timetable</label><select id='tt-home-profile' name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>"
            status = esc(selected["status"]).upper()
            profile_name = esc(profile_display_name(selected["name"]))
            profile_meta = f"{esc(selected['academic_year'])} · {esc(selected['term'])} · {esc(str(selected['profile_type'] or 'main').replace('_',' ').title())}"
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
                <div class='tt-home-profile-top'><div><span class='tt-home-eyebrow'>CURRENT TIMETABLE PROFILE</span><h2>{profile_name}</h2><p>{profile_meta} <i></i> <span class='tt-home-status'>{status}</span></p></div><div style='display:flex;gap:8px;flex-wrap:wrap'><a class='tt-home-outline' href='/app/timetable/setup#tt-profile-create-modal'>＋ Create new timetable</a><button class='tt-home-outline' type='button' data-open-profile-edit>Configure profile <span>↗</span></button></div></div>
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
                  <a class='tt-home-action' href='/app/timetable/room-allocation?profile_id={pid}'><span class='tt-home-action-icon'>▣</span><span><b>Allocate rooms to classes</b><small>Assign dedicated classrooms and manage capacity</small></span><em>→</em></a>
                  <a class='tt-home-action' href='{views_href}'><span class='tt-home-action-icon'>▤</span><span><b>View timetables</b><small>School, class, teacher and room views</small></span><em>→</em></a>
                  <a class='tt-home-action' href='{publish_href}'><span class='tt-home-action-icon'>⇧</span><span><b>Review and publish</b><small>Manage timetable release and revisions</small></span><em>→</em></a>
                </section>
              </div>"""
            profile_edit_modal = (f"""
              <dialog class='tt-home-profile-modal' id='tt-home-profile-edit-modal'>
                <div class='tt-home-profile-modal-head'><div><span class='tt-home-eyebrow'>TIMETABLE PROFILE</span><h3>Edit timetable profile</h3><p>Update the details of the selected timetable.</p></div><button type='button' data-close-profile-edit aria-label='Close'>×</button></div>
                <form method='post' data-native-post='true' action='/app/timetable/setup/profile/update' class='tt-home-profile-form'>
                  <input type='hidden' name='profile_id' value='{pid}'>
                  <input type='hidden' name='ds_tab' value='{escape(home_tab_id)}'>
                  <label>Timetable type<select name='profile_type' required><option value='main' {'selected' if str(selected['profile_type'] or 'main')=='main' else ''}>Main School Timetable</option><option value='weekend' {'selected' if str(selected['profile_type'] or '')=='weekend' else ''}>Weekend Lessons</option><option value='remedial' {'selected' if str(selected['profile_type'] or '')=='remedial' else ''}>Weekday Remedials</option><option value='special' {'selected' if str(selected['profile_type'] or '')=='special' else ''}>Other / Special Timetable</option></select></label>
                  <label>Profile name<input name='name' required maxlength='80' value='{profile_name}'></label>
                  <label>Academic year<input name='academic_year' required maxlength='20' value='{esc(selected['academic_year'])}'></label>
                  <label>Term / semester<input name='term' required maxlength='40' value='{esc(selected['term'])}'></label>
                  <label>Academic start date<input name='academic_start_date' type='date' value='{esc(selected['academic_start_date'] or '')}'></label>
                  <label>Academic end date<input name='academic_end_date' type='date' value='{esc(selected['academic_end_date'] or '')}'></label>
                  <div class='tt-home-profile-modal-actions'><button type='button' class='tt-home-profile-cancel' data-close-profile-edit>Cancel</button><button type='submit' class='tt-home-profile-save'>Save changes</button></div>
                </form>
              </dialog>
            """ if selected else "")
        else:
            profile_control = ""
            profile_edit_modal = ""
            profile_panel = """
              <section class='tt-home-empty'>
                <div class='tt-home-empty-icon'>▦</div><span class='tt-home-eyebrow'>GET STARTED</span>
                <h2>Create your first timetable profile</h2>
                <p>Start by choosing the academic year and term. Then configure school days, lesson periods, rooms and teaching requirements before building your timetable.</p>
                <a class='tt-home-primary' href='/app/timetable/setup'>Create timetable profile <span>→</span></a>
              </section>"""
        notice = f"<div class='tt-home-notice {'error' if error else 'success'}'>{escape(message)}</div>" if message else ""
        profile_catalog_html = (
            "<section class='tt-home-catalog'><div><span class='tt-home-eyebrow'>ALL TIMETABLE PROGRAMMES</span><h3>Independent timetables</h3><p>Each programme has its own configuration, publishing status and revision history.</p></div><div class='tt-home-catalog-list'>"
            + "".join(
                "<a href='/app/timetable?profile_id=" + str(int(p["id"])) + "'><span><b>" + esc(profile_display_name(p["name"])) + "</b><small>"
                + esc(p["academic_year"]) + " · " + esc(p["term"]) + " · " + esc(str(p["profile_type"] or "main").replace("_", " ").title())
                + "</small></span><em>" + esc(str(p["status"]).replace("_", " ").title()) + "</em></a>"
                for p in profiles
            ) + "</div></section>"
        ) if profiles else ""
        body = f"""
        <style>
           .tt-home-notice{{padding:10px 14px;border-radius:10px;margin:0 0 14px;font-size:12px;font-weight:700;background:#eaf5ec;color:#17633b}}.tt-home-notice.error{{background:#fff1f0;color:#a12828}}
          .tt-home-profile-modal{{width:min(560px,calc(100% - 28px));max-height:88vh;overflow:auto;border:1px solid #dce9df;border-radius:18px;padding:22px;background:#fff;color:#173d2b;box-shadow:0 22px 70px #102c1b40}}
          .tt-home-profile-modal::backdrop{{background:#102c1b70;backdrop-filter:blur(2px)}}
          .tt-home-profile-modal-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:18px}}
          .tt-home-profile-modal-head h3{{font-size:19px;margin:5px 0;color:#204b34}}.tt-home-profile-modal-head p{{font-size:12px;color:#718477;margin:0}}
          .tt-home-profile-modal-head>button{{border:0;background:#eff5f0;color:#315b3e;border-radius:9px;width:34px;height:34px;font-size:22px;cursor:pointer}}
          .tt-home-profile-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}.tt-home-profile-form label{{display:grid;gap:6px;font-size:11px;font-weight:800;color:#385b43}}
          .tt-home-profile-form input,.tt-home-profile-form select{{width:100%;min-width:0;padding:11px;border:1px solid #dce7de;border-radius:9px;background:#fff;color:#173d2b;font:inherit}}
          .tt-home-profile-modal-actions{{grid-column:1/-1;display:flex;justify-content:flex-end;gap:8px;margin-top:5px}}
          .tt-home-profile-modal-actions button{{border:0;border-radius:9px;padding:10px 15px;font-size:12px;font-weight:800;cursor:pointer}}
          .tt-home-profile-cancel{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8!important}}.tt-home-profile-save{{background:#17633b;color:#fff}}
          @media(max-width:560px){{.tt-home-profile-form{{grid-template-columns:1fr}}.tt-home-profile-modal{{padding:16px}}}}
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
           .tt-home-outline{{background:#fff;cursor:pointer;font:inherit}}
          .tt-home-status{{font-size:10px;font-weight:800;letter-spacing:.7px;color:#18734e;background:#e8f5ed;padding:5px 9px;border-radius:20px}}.tt-home-outline{{text-decoration:none!important;border:1px solid #dce8e0;border-radius:9px;padding:9px 13px;color:#236348!important;font-size:12px;font-weight:750;white-space:nowrap}}
          .tt-home-metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:22px}}.tt-home-metrics div{{padding:13px 15px;background:#f5f9f6;border-radius:12px;display:flex;align-items:center;justify-content:space-between;gap:8px}}.tt-home-metrics span{{font-size:11px;color:#6c8175;font-weight:650}}.tt-home-metrics b{{font-size:22px;color:#1d5b40}}
          .tt-home-columns{{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr);gap:20px;align-items:stretch}}.tt-home-panel{{padding:25px;min-width:0;border:1px solid #e4eaf0;border-radius:20px;box-shadow:0 8px 24px rgba(35,57,78,.045)}}.tt-home-panel:first-child{{background:#fff}}.tt-home-panel:last-child{{background:#f7f9fc;border-color:#e2e9f1}}.tt-home-panel-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}}.tt-home-panel h3{{font-size:19px;line-height:1.25;margin:6px 0 0;color:#20384f;letter-spacing:-.25px}}.tt-home-panel-head>a{{font-size:11px;color:#397895;text-decoration:none;font-weight:800;white-space:nowrap;padding:8px 11px;border:1px solid #dce8f0;border-radius:9px;background:#fff}}.tt-home-panel-head>a:hover{{background:#edf5f9;border-color:#c7dce8}}
          .tt-home-progress{{display:flex;align-items:center;gap:13px;padding:14px 13px;margin-top:9px;border:1px solid #e9eef3;border-radius:13px;background:#fbfcfd;text-decoration:none!important;color:inherit!important;transition:transform .16s,border-color .16s,background .16s,box-shadow .16s}}.tt-home-progress:hover{{transform:translateX(2px);border-color:#cbdde9;background:#f5f9fc;box-shadow:0 4px 12px rgba(42,78,103,.045)}}.tt-home-progress-icon{{width:36px;height:36px;border-radius:12px;background:#eaf2f8;color:#3d7895;display:grid;place-items:center;font-size:10px;font-weight:850;flex:none}}.tt-home-progress span:nth-child(2){{display:flex;flex-direction:column;gap:4px;min-width:0}}.tt-home-progress b{{font-size:12px;color:#29435a}}.tt-home-progress small{{font-size:10px;color:#8291a0;line-height:1.35}}.tt-home-progress strong{{margin-left:auto;min-width:34px;height:30px;padding:0 8px;border-radius:9px;background:#edf3f8;display:grid;place-items:center;font-size:14px;color:#3b718d}}
          .tt-home-actions{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-content:start;gap:11px}}.tt-home-actions>.tt-home-eyebrow,.tt-home-actions>h3{{grid-column:1/-1}}.tt-home-actions h3{{margin-bottom:5px}}.tt-home-action{{position:relative;display:flex;align-items:flex-start;gap:12px;min-height:112px;padding:16px 14px;border:1px solid #e3eaf1;border-radius:15px;margin:0;background:#fff;text-decoration:none!important;color:#29435a!important;transition:transform .17s,border-color .17s,box-shadow .17s}}.tt-home-action:hover{{transform:translateY(-3px);border-color:#bfd4e2;box-shadow:0 9px 20px rgba(40,75,99,.08)}}.tt-home-action-primary{{grid-column:1/-1;min-height:88px;align-items:center;background:#eef5fa;border-color:#d8e6ef}}.tt-home-action-icon{{width:40px;height:40px;border-radius:13px;background:#e8f0f6;color:#3b7895;display:grid;place-items:center;font-size:20px;flex:none}}.tt-home-action-primary .tt-home-action-icon{{background:#dcebf4;color:#326f8d}}.tt-home-action>span:nth-child(2){{display:flex;flex-direction:column;gap:6px;min-width:0;padding-top:2px}}.tt-home-action b{{font-size:12px;line-height:1.35;color:#29445b}}.tt-home-action small{{font-size:10px;line-height:1.45;color:#8291a0}}.tt-home-action em{{position:absolute;right:13px;bottom:10px;font-style:normal;color:#5b8ca5;font-size:17px}}
          .tt-home-catalog{{margin-top:18px;padding:20px 22px;background:#fff;border:1px solid #e3ece6;border-radius:18px;box-shadow:0 5px 18px rgba(24,67,47,.045)}}.tt-home-catalog h3{{margin:5px 0;color:#204b34;font-size:17px}}.tt-home-catalog p{{margin:0;color:#718379;font-size:11px}}.tt-home-catalog-list{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:14px}}.tt-home-catalog-list a{{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px;border:1px solid #e5eee6;border-radius:11px;color:#234638;text-decoration:none;background:#fbfdfb}}.tt-home-catalog-list a:hover{{background:#f0f7f1;border-color:#cbded0}}.tt-home-catalog-list b,.tt-home-catalog-list small{{display:block}}.tt-home-catalog-list b{{font-size:12px}}.tt-home-catalog-list small{{font-size:10px;color:#75877a;margin-top:4px}}.tt-home-catalog-list em{{font-size:9px;font-style:normal;font-weight:800;text-transform:uppercase;background:#eaf5ec;color:#17633b;padding:5px 8px;border-radius:15px;white-space:nowrap}}@media(max-width:600px){{.tt-home-catalog-list{{grid-template-columns:1fr}}}}
          .tt-home-empty{{text-align:center;padding:54px 25px;margin-top:18px}}.tt-home-empty-icon{{width:66px;height:66px;border-radius:20px;background:#eaf4ed;color:#24704b;display:grid;place-items:center;margin:0 auto 18px;font-size:30px}}.tt-home-empty h2{{font-size:24px;color:#1b4935;margin:8px 0}}.tt-home-empty p{{max-width:600px;margin:0 auto 22px;color:#718379;font-size:13px;line-height:1.7}}.tt-home-primary{{display:inline-flex;gap:12px;align-items:center;background:#176344;color:white!important;text-decoration:none!important;padding:12px 18px;border-radius:10px;font-weight:750;font-size:12px}}
          @media(max-width:800px){{.tt-home-hero{{padding:25px 22px}}.tt-home-hero-mark{{width:68px;height:68px;font-size:30px;border-radius:19px}}.tt-home-columns{{grid-template-columns:1fr}}.tt-home-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tt-home-panel{{padding:22px 20px}}}}
          @media(max-width:480px){{.tt-home-hero-mark{{display:none}}.tt-home-profile{{align-items:stretch;flex-direction:column;gap:7px}}.tt-home-profile select{{width:100%;min-width:0}}.tt-home-profile-card,.tt-home-panel{{padding:18px 16px}}.tt-home-profile-top{{align-items:flex-start;flex-direction:column}}.tt-home-metrics div{{padding:11px}}.tt-home-metrics span{{font-size:10px}}.tt-home-empty{{padding:38px 18px}}.tt-home-panel-head{{align-items:flex-start;flex-direction:column;gap:9px}}.tt-home-progress{{padding:12px 10px}}.tt-home-action{{min-height:96px;padding:13px 11px}}.tt-home-actions{{grid-template-columns:1fr}}.tt-home-actions>.tt-home-eyebrow,.tt-home-actions>h3,.tt-home-action-primary{{grid-column:1}}}}
        </style>
        <main class='tt-home'>
          <section class='tt-home-hero'><div class='tt-home-hero-copy'><span class='tt-home-eyebrow'>DAVISCHOOL · ACADEMIC OPERATIONS</span><h1>Smart Timetable</h1><p>Plan, organise and publish a balanced school timetable. Manage teaching requirements, build schedules and keep every class and teacher in sync.</p></div><div class='tt-home-hero-mark'>▦</div></section>
          {profile_control}
          {notice}
          {profile_panel}
          {profile_catalog_html}
          {profile_edit_modal}
        </main>
        <script>(function(){{const dialog=document.getElementById('tt-home-profile-edit-modal');if(!dialog)return;document.querySelector('[data-open-profile-edit]')?.addEventListener('click',()=>dialog.showModal());dialog.querySelectorAll('[data-close-profile-edit]').forEach(b=>b.addEventListener('click',()=>dialog.close()));dialog.addEventListener('click',e=>{{if(e.target===dialog)dialog.close();}});}})();</script>"""
        return module_page(request, "Smart Timetable", "timetable", body)

    @app.get("/app/timetable/room-allocation", response_class=HTMLResponse)
    def timetable_room_allocation_page(request: Request, profile_id: int = 0, message: str = "", error: int = 0):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        school_id = int(school["id"])
        con = get_db()
        try:
            classes = con.execute(
                """SELECT c.id,c.name,c.stream,COUNT(st.id) AS learner_count,
                          rm.id AS room_id,rm.room_code,rm.name AS room_name,rm.capacity
                   FROM classes c
                   LEFT JOIN students st ON st.school_id=c.school_id AND st.class_id=c.id
                   LEFT JOIN ds_timetable_rooms rm ON rm.school_id=c.school_id
                        AND rm.assigned_class_id=c.id AND rm.allocation_mode='dedicated'
                        AND rm.is_active=1 AND rm.room_type='classroom'
                   WHERE c.school_id=?
                   GROUP BY c.id,c.name,c.stream,rm.id,rm.room_code,rm.name,rm.capacity
                   ORDER BY c.name,c.stream""",
                (school_id,),
            ).fetchall()
            rooms = con.execute(
                """SELECT id,room_code,name,capacity,assigned_class_id
                   FROM ds_timetable_rooms
                   WHERE school_id=? AND is_active=1 AND room_type='classroom'
                   ORDER BY name""",
                (school_id,),
            ).fetchall()
            assigned_count = sum(1 for row in classes if row["room_id"] is not None)
            total_learners = sum(int(row["learner_count"] or 0) for row in classes)
        finally:
            con.close()
        esc = lambda value: escape(str(value if value is not None else ""))
        notice = ""
        if message:
            notice = f"<div class='ra-notice {'error' if error else 'success'}'>{esc(message)}</div>"
        room_rows = []
        for row in classes:
            class_label = str(row["name"]) + ((" · " + str(row["stream"])) if row["stream"] else "")
            options = ["<option value=''>No dedicated classroom</option>"]
            for room in rooms:
                current_owner = int(room["assigned_class_id"]) if room["assigned_class_id"] is not None else None
                if current_owner not in (None, int(row["id"])):
                    continue
                selected = " selected" if row["room_id"] is not None and int(row["room_id"]) == int(room["id"]) else ""
                capacity = f" · capacity {int(room['capacity'])}" if room["capacity"] is not None else ""
                options.append(f"<option value='{int(room['id'])}'{selected}>{esc(room['room_code'])} — {esc(room['name'])}{capacity}</option>")
            current = esc(row["room_name"] or "Not assigned")
            capacity_text = esc(row["capacity"] if row["capacity"] is not None else "—")
            learner_count = int(row["learner_count"] or 0)
            room_rows.append(
                f"<tr><td><b>{esc(class_label)}</b><small class='ra-sub'>{learner_count} learners</small></td>"
                f"<td>{current}</td><td>{capacity_text}</td><td><form method='post' action='/app/timetable/room-allocation' class='ra-inline'>"
                f"<input type='hidden' name='profile_id' value='{int(profile_id)}'><input type='hidden' name='class_id' value='{int(row['id'])}'>"
                f"<select name='room_id' aria-label='Classroom for {esc(class_label)}'>{''.join(options)}</select>"
                f"<button class='ra-save'>Save</button></form></td></tr>"
            )
        rows_html = "".join(room_rows) or "<tr><td colspan='4'>No classes found for this school.</td></tr>"
        empty_rooms = "" if rooms else (
            "<div class='ra-empty'><b>No classrooms registered yet.</b>"
            "<p>Add your physical classrooms first, then return here to allocate them to classes.</p>"
            "<a href='/app/timetable/setup?tab=setup'>Open Rooms and Facilities ↗</a></div>"
        )
        body = f"""
        <main class='ra-page'>
          <header class='ra-head'><div><span>SMART TIMETABLE · LEARNING SPACES</span><h1>Room Allocation</h1>
          <p>Assign a dedicated classroom to each class. The automatic timetable generator will reserve that classroom for the assigned class and prevent other classes from using it.</p></div>
          <a href='/app/timetable'>← Timetable workspace</a></header>
          {notice}
          <section class='ra-stats'><div><span>Classes</span><b>{len(classes)}</b></div><div><span>Assigned classrooms</span><b>{assigned_count}</b></div><div><span>Unassigned classes</span><b>{max(0,len(classes)-assigned_count)}</b></div><div><span>Learners covered</span><b>{total_learners}</b></div></section>
          {empty_rooms}
          <section class='ra-panel'><div class='ra-panel-head'><div><h2>Classroom assignments</h2><p>Choose one registered classroom for each class. Leave the selection blank to release its dedicated room.</p></div></div>
          <div class='ra-table-wrap'><table><thead><tr><th>Class / Stream</th><th>Current classroom</th><th>Room capacity</th><th>Change allocation</th></tr></thead><tbody>{rows_html}</tbody></table></div></section>
          <p class='ra-foot'>Only active rooms of type Classroom appear here. Laboratories, halls and other specialist spaces remain available for subject-specific room rules.</p>
        </main>
        <style>
        .ra-page{{max-width:1450px;margin:0 auto;padding:22px;color:#234638}}.ra-page *{{box-sizing:border-box}}
        .ra-head{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;padding:23px 25px;border:1px solid #dce9de;border-radius:16px;background:linear-gradient(115deg,#e5f2e7,#f7faf7)}}
        .ra-head span{{font-size:10px;letter-spacing:1.4px;font-weight:800;color:#398052}}.ra-head h1{{margin:6px 0;color:#204b34;font-size:26px}}.ra-head p{{max-width:760px;margin:0;color:#637b6a;font-size:12px;line-height:1.6}}
        .ra-head>a,.ra-empty a{{color:#286443;font-size:12px;font-weight:800;text-decoration:none}}.ra-stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}}
        .ra-stats>div{{padding:14px 16px;background:#fff;border:1px solid #e1ece2;border-radius:12px}}.ra-stats span{{display:block;color:#718477;font-size:10px;font-weight:700}}.ra-stats b{{display:block;color:#286443;font-size:23px;margin-top:4px}}
        .ra-panel{{background:#fff;border:1px solid #e1ece2;border-radius:15px;overflow:hidden}}.ra-panel-head{{padding:17px 20px;border-bottom:1px solid #e7eee8}}.ra-panel-head h2{{margin:0 0 5px;color:#254d36;font-size:16px}}.ra-panel-head p,.ra-foot{{margin:0;color:#718477;font-size:11px;line-height:1.6}}
        .ra-table-wrap{{width:100%;overflow-x:auto}}.ra-table-wrap table{{width:100%;border-collapse:collapse;min-width:720px}}.ra-table-wrap th,.ra-table-wrap td{{padding:12px 14px;text-align:left;border-bottom:1px solid #edf2ed;font-size:12px}}.ra-table-wrap th{{background:#f7faf7;color:#607968;font-size:10px;text-transform:uppercase;letter-spacing:.5px}}.ra-sub{{display:block;color:#849287;font-size:10px;margin-top:3px}}
        .ra-inline{{display:flex;align-items:center;gap:8px;min-width:280px}}.ra-inline select{{flex:1;min-width:0;padding:9px 10px;border:1px solid #d8e5da;border-radius:9px;background:#fff;color:#294b38;font-size:12px}}.ra-save{{padding:9px 14px;border:0;border-radius:9px;background:#287348;color:#fff;font-weight:800;cursor:pointer}}
        .ra-notice{{margin:12px 0;padding:12px 15px;border-radius:10px;font-size:12px;font-weight:700}}.ra-notice.success{{background:#edf7ef;color:#24623d}}.ra-notice.error{{background:#fff1ef;color:#a23c32}}
        .ra-empty{{margin:14px 0;padding:17px;border:1px dashed #b9d3bf;border-radius:12px;background:#f8fcf8}}.ra-empty p{{font-size:12px;color:#718477}}.ra-foot{{margin:12px 2px}}
        @media(max-width:700px){{.ra-page{{padding:12px}}.ra-head{{padding:18px}}.ra-stats{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ra-head h1{{font-size:22px}}}}
        </style>"""
        return module_page(request, "Room Allocation", "timetable", body)

    @app.post("/app/timetable/room-allocation")
    def save_timetable_room_allocation(request: Request, class_id: int = Form(...), room_id: str = Form(""), profile_id: int = Form(0)):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            from app.timetable.setup import save_classroom_assignment
            save_classroom_assignment(
                con, int(school["id"]), class_id,
                int(room_id) if room_id.strip() else None,
            )
            message = "Classroom allocation saved." if room_id.strip() else "Dedicated classroom released; the class can use shared rooms."
            return RedirectResponse(
                f"/app/timetable/room-allocation?profile_id={profile_id}&message={quote(message)}", 303
            )
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return RedirectResponse(
                f"/app/timetable/room-allocation?profile_id={profile_id}&error=1&message={quote(str(exc))}", 303
            )
        finally:
            con.close()

    @app.get("/app/timetable/setup", response_class=HTMLResponse)
    def timetable_setup_page(request: Request, profile_id: int = 0, message: str = "", error: int = 0, class_id: int = 0, focus: str = "", tab: str = ""):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        school_id = int(school["id"])
        con = get_db()
        cur = con.cursor()
        profiles = cur.execute(
            "SELECT * FROM ds_timetable_profiles WHERE school_id=? AND status IN ('draft','pending_approval','published') ORDER BY academic_year DESC,term,id DESC",
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
            teachers = cur.execute("SELECT id,name,teacher_color,teacher_initials FROM teachers WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
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
        class_group_options = "".join(f"<option value='{int(row['id'])}'>{esc(row['name'])} {esc(row['stream'] or '')}</option>" for row in class_records)
        teacher_group_options = "".join(f"<option value='{int(row['id'])}'>{esc(row['name'])}</option>" for row in teachers)
        subject_group_options = "".join(f"<option value='{int(row['id'])}'>{esc(row['name'])}</option>" for row in subjects) if selected else ""
        room_options = "<option value=''>No room preference</option>" + "".join(f"<option value='{int(row['id'])}'>{esc(row['name'])} ({esc(row['room_type'])})</option>" for row in rooms)
        profile_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==int(selected['id']) else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(profile_display_name(p['name']))} ({esc(p['status'])})</option>"
            for p in profiles
        )
        notice = f"<div class='tt-alert {'error' if error else 'success'}'>{esc(message)}</div>" if message else ""
        pid = int(selected["id"]) if selected else 0
        hidden = f"<input type='hidden' name='profile_id' value='{pid}'>"
        teacher_color_tab_id = str(request.scope.get("davischool_tab_id") or request.query_params.get("ds_tab") or "")
        teacher_color_tab_field = f"<input type='hidden' name='ds_tab' value='{esc(teacher_color_tab_id)}'>"
        selector = f"<form method='get' action='/app/timetable/setup' class='tt-select'><label for='profile_id'>Timetable profile</label><select id='profile_id' name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>" if profiles else ""
        profile_summary = (
            f"<div class='tt-profile'><div><span class='tt-kicker'>ACTIVE CONFIGURATION</span><h2>{esc(profile_display_name(selected['name']))}</h2><p>{esc(selected['academic_year'])} · {esc(selected['term'])} · {esc(str(selected['profile_type'] or 'main').replace('_',' ').title())} · {esc(selected['academic_start_date'] or 'Start date not set')} – {esc(selected['academic_end_date'] or 'End date not set')} · <span class='tt-status'>{esc(selected_status).upper()}</span></p></div><div class='tt-stats'><span><b>{len(days)}</b>Days</span><span><b>{len(periods)}</b>Periods</span><span><b>{len(rooms)}</b>Rooms</span></div></div>"
            if selected else "<div class='tt-empty'><b>No timetable configuration yet</b><p>Create an academic-year and term profile to begin.</p></div>"
        )
        day_rows = "".join(
            f"<tr><td>{esc(d['day_order'])}</td><td><b>{esc(d['day_name'])}</b></td><td>{esc(d['day_code'])}</td><td>{'Instructional' if d['is_instructional'] else 'Non-instructional'}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/day' class='tt-form compact'>{hidden}<input type='hidden' name='day_code' value='{esc(d['day_code'])}'><label>Name<input name='day_name' value='{esc(d['day_name'])}' required></label><label>Order<input type='number' min='1' max='7' name='day_order' value='{int(d['day_order'])}' required></label><label class='tt-check'><input type='checkbox' name='instructional' value='1' {'checked' if d['is_instructional'] else ''}> Instructional</label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this school day?&quot;)'>{hidden}<input type='hidden' name='kind' value='day'><input type='hidden' name='row_id' value='{int(d['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>" for d in days
        ) or "<tr><td colspan='5' class='tt-muted'>No school days configured.</td></tr>"
        period_rows = "".join(
            f"<tr><td>{esc(p['period_no'])}</td><td><b>{esc(p['label'])}</b></td><td>{esc(p['start_time'])}–{esc(p['end_time'])}</td><td>{esc(p['duration_minutes'])} min</td><td>{esc(p['period_type'])}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/period' class='tt-form compact'>{hidden}<input type='hidden' name='period_id' value='{int(p['id'])}'><label>Period number<input name='period_no' type='number' min='1' max='30' value='{int(p['period_no'])}' required></label><label>Label<input name='label' value='{esc(p['label'])}' required></label><label>Start<input type='time' name='start_time' value='{esc(p['start_time'])}' required></label><label>End<input type='time' name='end_time' value='{esc(p['end_time'])}' required></label><label>Type<select name='period_type'><option value='lesson' {'selected' if p['period_type']=='lesson' else ''}>Lesson</option><option value='study' {'selected' if p['period_type']=='study' else ''}>Study</option><option value='assembly' {'selected' if p['period_type']=='assembly' else ''}>Assembly</option></select></label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this period? Existing linked timetable data may prevent deletion.&quot;)'>{hidden}<input type='hidden' name='kind' value='period'><input type='hidden' name='row_id' value='{int(p['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>" for p in periods
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
        def room_policy_fields(mode, assigned_id):
            selected_class = int(assigned_id or 0)
            class_options = "<option value=''>Choose class / stream</option>" + "".join(
                f"<option value='{int(c['id'])}' {'selected' if int(c['id'])==selected_class else ''}>{esc(c['name'])} {esc(c['stream'] or '')}</option>" for c in class_records
            )
            return (f"<label>Room use<select name='allocation_mode'><option value='shared' {'selected' if (mode or 'shared')=='shared' else ''}>Shared by classes at different times</option><option value='dedicated' {'selected' if mode=='dedicated' else ''}>Permanently assigned to one class</option></select></label>"
                    f"<label>Assigned class (dedicated only)<select name='assigned_class_id'>{class_options}</select></label>")
        room_rows = "".join(
            f"<tr><td><b>{esc(r['room_code'])}</b></td><td>{esc(r['name'])}</td><td>{esc(r['room_type'])}</td><td>{esc(r['capacity'] or '—')}</td><td>{'Dedicated' if str(r['allocation_mode'] or 'shared')=='dedicated' else 'Shared'}</td><td>{esc(r['equipment'] or '—')}</td><td><details><summary>Edit</summary><form method='post' data-native-post='true' action='/app/timetable/setup/room' class='tt-form compact'>{hidden}<input type='hidden' name='room_code' value='{esc(r['room_code'])}'><label>Name<input name='name' value='{esc(r['name'])}' required></label><label>Type<select name='room_type'>{room_type_options_for(r['room_type'])}</select></label><label>Capacity<input type='number' min='1' name='capacity' value='{esc(r['capacity'] or '')}'></label>{room_policy_fields(r['allocation_mode'],r['assigned_class_id'])}<label class='wide'>Description<input name='description' value='{esc(r['description'] or '')}'></label><label class='wide'>Equipment / resources<input name='equipment' value='{esc(r['equipment'] or '')}'></label><label class='wide'>Suitable for<input name='suitable_for' value='{esc(r['suitable_for'] or '')}'></label><button class='tt-btn'>Save changes</button></form></details><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this room? It may be blocked if assigned to timetable sessions.&quot;)'>{hidden}<input type='hidden' name='kind' value='room'><input type='hidden' name='row_id' value='{int(r['id'])}'><button class='tt-btn danger'>Delete</button></form></td></tr>" for r in rooms
        ) or "<tr><td colspan='7' class='tt-muted'>No rooms configured.</td></tr>"
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
            f"<tr data-availability-row data-search='{esc(item['name']).lower()}'><td><b>{esc(item['name'])}</b></td><td>{item['fallback'] + item['unavailable']}</td><td>{max(0, total_availability_cells-item['fallback']-item['unavailable'])}</td><td>{item['fallback']}</td><td>{item['unavailable']}</td><td class='tt-availability-actions'><button type='button' class='tt-btn secondary tt-edit-availability' data-kind='subject' data-id='{subject_id}'>Edit in popup</button><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete all availability settings for this subject in the selected timetable profile?&quot;)'>{hidden}<input type='hidden' name='kind' value='subject_availability_subject'><input type='hidden' name='row_id' value='{subject_id}'><button type='submit' class='tt-btn danger'>Delete</button></form></td></tr>"
            for subject_id, item in sorted(subject_availability_summary.items(), key=lambda pair: pair[1]["name"].lower())
        ) or "<tr><td colspan='6' class='tt-muted'>No subjects found in the school register.</td></tr>"
        period_start_options = "".join(
            f"<option value='{int(p['period_no'])}'>P{int(p['period_no'])} · {esc(p['label'])}</option>"
            for p in periods if str(p["period_type"] or "lesson") == "lesson"
        )
        requirement_pattern_values = {}
        requirement_links_values = {}
        requirement_pattern_display = {}
        for req in requirements:
            saved_pattern = cur.execute(
                """SELECT rp.duration_periods,p.period_no,rp.linked_class_ids_json,rp.co_teacher_ids_json
                   FROM ds_timetable_requirement_patterns rp
                   LEFT JOIN ds_timetable_periods p ON p.id=rp.preferred_period_id
                   WHERE rp.school_id=? AND rp.profile_id=? AND rp.requirement_id=?
                   ORDER BY rp.session_no""",
                (school_id, pid, int(req["id"])),
            ).fetchall()
            requirement_links_values[int(req["id"])] = json.dumps([
                {"classes": json.loads(item["linked_class_ids_json"] or "[]"),
                 "teachers": json.loads(item["co_teacher_ids_json"] or "[]")}
                for item in saved_pattern
            ])
            requirement_pattern_values[int(req["id"])] = ", ".join(
                str(int(item["duration_periods"])) +
                (("@" + str(int(item["period_no"]))) if item["period_no"] is not None else "")
                for item in saved_pattern
            )
            # A legacy requirement without explicit session rows already carries
            # its full weekly allocation. Show that saved allocation rather than
            # incorrectly reporting zero configured periods.
            used = (
                sum(int(item["duration_periods"]) for item in saved_pattern)
                if saved_pattern
                else int(req["lessons_per_week"] or 0) * int(req["duration_periods"] or 1)
            )
            requirement_pattern_display[int(req["id"])] = (
                "".join(
                    f"<span class='tt-session-chip' title='Session {index}: {int(item['duration_periods'])} period(s)'>"
                    f"{'Single' if int(item['duration_periods']) == 1 else ('Double' if int(item['duration_periods']) == 2 else ('Triple' if int(item['duration_periods']) == 3 else str(int(item['duration_periods'])) + ' periods'))}"
                    f"</span>" for index, item in enumerate(saved_pattern, 1)
                ) or "<span class='tt-session-chip muted'>Not yet broken into sessions</span>"
            ) + f"<small class='tt-req-subline'>{used} of {int(req['lessons_per_week'])} periods configured · {max(0, int(req['lessons_per_week'])-used)} remaining</small>"
        requirement_cards_by_class = {}
        for r in requirements:
            cid = int(r["class_id"])
            class_label = str(r["class_name"]) + (" " + str(r["stream"] or "")).rstrip()
            search_text = (class_label + " " + str(r["subject_name"]) + " " + str(r["teacher_name"])).lower()
            manage_form = f"""<form method='post' data-native-post='true' action='/app/timetable/setup/requirement' class='tt-form compact'>{hidden}<input type='hidden' name='allocation' value='{int(r['class_id'])}|{int(r['subject_id'])}|{int(r['teacher_id'])}'><label>Weekly period target<input type='number' min='1' max='30' name='lessons_per_week' value='{int(r['lessons_per_week'])}' required></label><label>Max / day<input type='number' min='1' max='10' name='max_lessons_per_day' value='{esc(r['max_lessons_per_day'] or '')}'></label><div class='tt-session-guidance'>Choose Single, Double, Triple or Quadruple for each saved session. A selected start period anchors the full consecutive block; for example, a Triple starting at Period 3 occupies Periods 3, 4 and 5.</div><div class='wide tt-session-editor' data-session-editor> <div class='tt-session-editor-head'><b>Weekly session planner</b><span>Edit every weekly occurrence independently</span></div> <div class='tt-session-linking'> <label>Link another class<select data-link-class><option value=''>Choose class to link</option>{class_group_options}</select></label> <label>Add co-teacher<select data-link-teacher><option value=''>Choose additional teacher</option>{teacher_group_options}</select></label> </div> <div class='tt-session-list' data-session-list><div class='tt-session-row'><span class='tt-session-number'>1</span><label>Lesson type<select data-session-duration><option value='1'>Single · 1 period</option><option value='2'>Double · 2 periods</option><option value='3'>Triple · 3 periods</option><option value='4'>Quadruple · 4 periods</option></select></label><label>Start period<select data-session-period><option value=''>Auto</option>{period_start_options}</select></label><small data-session-span>Auto placement</small><button type='button' data-remove-session disabled>Remove</button></div></div> <button type='button' class='tt-btn secondary' data-add-session>＋ Add another session</button> <input type='hidden' name='weekly_pattern' data-weekly-pattern value='{esc(requirement_pattern_values.get(int(r['id']), ''))}'><input type='hidden' name='weekly_links' value='{esc(requirement_links_values.get(int(r['id']), '[]'))}'> <small>Set the duration and starting period for every occurrence (Single, Double, Triple or Quadruple). Optional class and co-teacher selections link that same session across allocations.</small> </div><button class='tt-btn'>Save changes</button></form><form method='post' data-native-post='true' action='/app/timetable/setup/row-delete' onsubmit='return confirm(&quot;Delete this subject requirement?&quot;)'>{hidden}<input type='hidden' name='kind' value='requirement'><input type='hidden' name='row_id' value='{int(r['id'])}'><button class='tt-btn danger'>Delete requirement</button></form>"""
            manage_editor = f"""<button type="button" class="tt-req-manage-button" data-req-manage-open="tt-req-manage-{int(r['id'])}">Manage</button><div class="tt-modal tt-req-manage-modal" id="tt-req-manage-{int(r['id'])}" role="dialog" aria-modal="true" aria-labelledby="tt-req-manage-title-{int(r['id'])}"><div class="tt-modal-dialog tt-req-manage-dialog"><div class="tt-modal-head"><div><span class="tt-kicker">SUBJECT REQUIREMENT</span><h3 id="tt-req-manage-title-{int(r['id'])}">Manage {esc(r['subject_name'])}</h3><p>{esc(class_label)} · {esc(r['teacher_name'])}</p></div><button type="button" class="tt-modal-close" data-req-manage-close aria-label="Close">&times;</button></div><div class="tt-req-manage-content">{manage_form}</div></div></div>"""
            card = (
                f"<article class='tt-req-card' data-requirement-row data-class='{cid}' "
                f"data-subject='{int(r['subject_id'])}' data-teacher='{int(r['teacher_id'])}' "
                f"data-search='{esc(search_text)}'>"
                f"<div class='tt-req-card-main'><div class='tt-req-card-title'>"
                f"<span class='tt-req-card-subject'>{esc(r['subject_name'])}</span>"
                f"<span class='tt-req-card-teacher'>Lead teacher · {esc(r['teacher_name'])}</span></div>"
                f"<div class='tt-req-card-load'><div class='tt-session-chip-list'>{requirement_pattern_display.get(int(r['id']), '')}</div>"
                f"<small class='tt-req-subline'>Weekly target · {int(r['lessons_per_week'])} periods</small></div>"
                f"<div class='tt-req-card-action'>{manage_editor}</div></div></article>"
            )
            requirement_cards_by_class.setdefault(cid, {"label": class_label, "cards": []})["cards"].append(card)
        requirement_rows = "".join(
            f"<section class='tt-req-class-group' data-requirement-group><header><b>{esc(group['label'])}</b>"
            f"<span>{len(group['cards'])} subject(s)</span></header>{''.join(group['cards'])}</section>"
            for _, group in sorted(requirement_cards_by_class.items(), key=lambda item: item[1]["label"].lower())
        ) or "<div class='tt-req-empty'>No weekly subject requirements configured yet. Use <b>Add subject requirement</b> to begin.</div>"
        requirement_class_filters = "".join(f"<option value='{int(cid)}' {'selected' if class_id and int(cid)==int(class_id) else ''}>{esc(name)}</option>" for cid,name in sorted({(int(r['class_id']), str(r['class_name'])+' '+str(r['stream'] or '')) for r in requirements}, key=lambda x:x[1].lower()))
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
        teacher_color_rows = "".join(
            f"<tr><td><b>{esc(t['name'])}</b></td><td><form method='post' data-native-post='true' action='/app/timetable/setup/teacher-color' class='tt-teacher-color-form'>{hidden}{teacher_color_tab_field}<input type='hidden' name='teacher_id' value='{int(t['id'])}'><label class='tt-teacher-initials-field'>Initials<input name='teacher_initials' value='{esc(t['teacher_initials'] or '')}' maxlength='4' pattern='[A-Za-z]{1,4}' placeholder='e.g. JM' required></label><label class='tt-teacher-colour-field'>Colour<input aria-label='Colour for {esc(t['name'])}' type='color' name='teacher_color' value='{esc(t['teacher_color'] or '#2563EB')}' required></label><span class='tt-teacher-color-code'>{esc(t['teacher_color'] or '#2563EB')}</span><button class='tt-btn'>Save</button></form></td></tr>"
            for t in teachers
        ) or "<tr><td colspan='2' class='tt-muted'>No teachers are registered yet.</td></tr>"
        teacher_colour_section = f"""
        <section class='tt-section tt-teacher-colours'>
          <div class='tt-section-title'><div><span class='tt-kicker'>09 · TIMETABLE APPEARANCE</span><h3>Teacher colours</h3><p>Set each teacher’s short initials and colour. The initials appear at the bottom-right of their lesson cells.</p></div></div>
          <style>.tt-teacher-colours .tt-teacher-color-form{{display:flex;align-items:end;gap:10px;flex-wrap:wrap}}.tt-teacher-initials-field,.tt-teacher-colour-field{{display:grid;gap:4px;font-size:10px;font-weight:800;color:#55705d}}.tt-teacher-initials-field input{{width:72px;height:36px;box-sizing:border-box;border:1px solid #d5e4d7;border-radius:8px;padding:6px;text-transform:uppercase;font-weight:900;letter-spacing:.08em}}.tt-teacher-colours input[type=color]{{width:52px;height:38px;padding:2px;border:1px solid #d5e4d7;border-radius:9px;background:#fff;cursor:pointer}}.tt-teacher-color-code{{font:700 11px ui-monospace,monospace;color:#607669;min-width:65px}}.tt-teacher-colours table{{min-width:360px}}</style>
          <div class='tt-table'><table><thead><tr><th>Teacher</th><th>Timetable label & colour</th></tr></thead><tbody>{teacher_color_rows}</tbody></table></div>
        </section>"""
        # Current allocation monitor: compare the weekly lessons configured for each
        # allocated class/stream with its own workload ceiling before generation.
        requirements_by_allocation = {
            (int(r["class_id"]), int(r["subject_id"]), int(r["teacher_id"])): r
            for r in requirements
        }
        limits_by_class = {int(x["class_id"]): x for x in class_limits}
        allocation_groups = {}
        for a in allocations:
            cid = int(a["class_id"])
            group = allocation_groups.setdefault(cid, {
                "class_name": str(a["class_name"]), "stream": str(a["stream"] or ""),
                "subjects": [], "total": 0, "configured": 0,
            })
            req = requirements_by_allocation.get((cid, int(a["subject_id"]), int(a["teacher_id"])))
            lessons = int(req["lessons_per_week"]) if req else 0
            group["subjects"].append({
                "subject": str(a["subject_name"]), "teacher": str(a["teacher_name"]),
                "lessons": lessons, "configured": req is not None,
            })
            group["total"] += lessons
            group["configured"] += 1 if req is not None else 0
        allocation_monitor_rows = []
        for cid, group in sorted(allocation_groups.items(), key=lambda item: (item[1]["class_name"].lower(), item[1]["stream"].lower())):
            limit = limits_by_class.get(cid)
            maximum = limit["max_lessons_per_week"] if limit else None
            maximum_value = int(maximum) if maximum is not None else None
            if maximum_value is None:
                status_text, status_class = "Maximum not set", "neutral"
            elif group["total"] > maximum_value:
                status_text, status_class = f"Over by {group['total'] - maximum_value}", "over"
            elif group["total"] < maximum_value:
                status_text, status_class = f"{maximum_value - group['total']} available", "under"
            else:
                status_text, status_class = "At maximum", "match"
            subject_lines = "".join(
                f"<tr><td>{esc(item['subject'])}</td><td>{esc(item['teacher'])}</td><td><b>{item['lessons']}</b> / week</td><td>{'Configured' if item['configured'] else 'Not configured'}</td></tr>"
                for item in sorted(group["subjects"], key=lambda x: x["subject"].lower())
            )
            modal_id = f"tt-subject-breakdown-{cid}"
            allocation_editor_url = f"/app/timetable/setup?profile_id={pid}&class_id={int(cid)}"
            current_tab_id = str(request.scope.get("davischool_tab_id") or "")
            if current_tab_id:
                allocation_editor_url += "&ds_tab=" + quote(current_tab_id, safe="")
            allocation_monitor_rows.append(
                f"<tr class='tt-allocation-summary'><td><b>{esc(group['class_name'])} {esc(group['stream'])}</b><small>{group['configured']} of {len(group['subjects'])} subject loads configured</small></td>"
                f"<td><b>{group['total']}</b> lessons / week</td><td>{maximum_value if maximum_value is not None else 'Not set'}</td>"
                f"<td><span class='tt-allocation-status {status_class}'>{esc(status_text)}</span></td>"
                f"<td><a class='tt-btn secondary' href='{allocation_editor_url}'>Edit allocation</a></td></tr>"
                f"<tr class='tt-allocation-details'><td colspan='5'><button type='button' class='tt-breakdown-open' data-breakdown-target='{modal_id}' aria-haspopup='dialog'>View subject breakdown ({len(group['subjects'])})</button>"
                f"<div class='tt-breakdown-modal' id='{modal_id}' role='dialog' aria-modal='true' aria-label='Subject breakdown for {esc(group['class_name'])} {esc(group['stream'])}' hidden>"
                f"<div class='tt-breakdown-dialog'><div class='tt-breakdown-head'><div><span class='tt-kicker'>CURRENT ALLOCATIONS</span><h4>{esc(group['class_name'])} {esc(group['stream'])} · Subject breakdown</h4></div><button type='button' class='tt-breakdown-close' aria-label='Close'>&times;</button></div>"
                f"<div class='tt-table'><table><thead><tr><th>Subject</th><th>Allocated teacher</th><th>Weekly lessons</th><th>Setup</th></tr></thead><tbody>{subject_lines}</tbody></table></div></div></div></td></tr>"
            )
        allocation_monitor_section = f"""
        <section class='tt-section tt-allocation-monitor'>
          <style>
            .tt-allocation-monitor .tt-breakdown-open{{border:0;background:transparent;color:#267348;font:700 12px inherit;text-decoration:underline;text-underline-offset:3px;padding:9px 2px;cursor:pointer}}
            .tt-allocation-monitor .tt-breakdown-modal[hidden]{{display:none!important}}
            .tt-allocation-monitor .tt-breakdown-modal{{position:fixed;inset:0;z-index:10050;display:flex;align-items:center;justify-content:center;padding:18px;background:rgba(15,35,27,.55)}}
            .tt-allocation-monitor .tt-breakdown-dialog{{width:min(760px,100%);max-height:min(82vh,720px);overflow:auto;background:#fff;border:1px solid #dce9df;border-radius:18px;padding:20px;box-shadow:0 24px 70px rgba(0,0,0,.22)}}
            .tt-allocation-monitor .tt-breakdown-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:15px}}
            .tt-allocation-monitor .tt-breakdown-head h4{{margin:5px 0 0;color:#214b35;font-size:17px}}
            .tt-allocation-monitor .tt-breakdown-close{{width:34px;height:34px;border:1px solid #dce8df;border-radius:10px;background:#f7faf7;color:#345b43;font-size:23px;cursor:pointer;line-height:1}}
            .tt-allocation-monitor .tt-breakdown-modal table{{min-width:540px}}
            @media(max-width:600px){{.tt-allocation-monitor .tt-breakdown-dialog{{padding:14px;border-radius:14px}}}}
          </style>
          <div class='tt-section-title'><div><span class='tt-kicker'>CURRENT ALLOCATIONS</span><h3>Track class lesson allocations</h3>
          <p>Compare the weekly lessons assigned to each class or stream with its configured maximum. Open a breakdown to inspect subject and teacher allocations.</p></div></div>
          <div class='tt-table'><table><thead><tr><th>Class / stream</th><th>Current weekly load</th><th>Maximum</th><th>Balance</th><th>Action</th></tr></thead>
          <tbody>{"".join(allocation_monitor_rows) or "<tr><td colspan='5' class='tt-muted'>No current subject allocations found. Add allocations to begin tracking class lesson loads.</td></tr>"}</tbody></table></div>
          <p class='tt-muted'>Weekly totals are calculated from the saved subject requirements. If a subject has no weekly lesson requirement yet, it is shown as not configured and contributes zero until configured.</p>
          <script>
          (function(){{
            const root=document.currentScript.closest('.tt-allocation-monitor');
            if(!root||root.dataset.breakdownReady)return;
            root.dataset.breakdownReady='1';
            let active=null;
            function closeModal(modal){{if(!modal)return;modal.hidden=true;if(active===modal)active=null;}}
            root.addEventListener('click',event=>{{
              const opener=event.target.closest('[data-breakdown-target]');
              if(opener){{active=root.querySelector('#'+CSS.escape(opener.dataset.breakdownTarget));if(active){{active.hidden=false;active.querySelector('.tt-breakdown-close')?.focus();}}return;}}
              const close=event.target.closest('.tt-breakdown-close');
              if(close){{closeModal(close.closest('.tt-breakdown-modal'));return;}}
              if(event.target.classList.contains('tt-breakdown-modal'))closeModal(event.target);
            }});
            root.addEventListener('keydown',event=>{{if(event.key==='Escape'&&active)closeModal(active);}});
          }})();
          </script>
        </section>
        """
        requirement_by_allocation = {
            (int(req["class_id"]), int(req["subject_id"]), int(req["teacher_id"])): req
            for req in requirements
        }
        requirement_allocation_option_rows = []
        for allocation_row in allocations:
            allocation_key = (int(allocation_row["class_id"]), int(allocation_row["subject_id"]), int(allocation_row["teacher_id"]))
            existing_requirement = requirement_by_allocation.get(allocation_key)
            if existing_requirement:
                existing_id = int(existing_requirement["id"])
                existing_pattern = requirement_pattern_values.get(existing_id, "")
                if not existing_pattern:
                    existing_pattern = ",".join(["1"] * max(1, int(existing_requirement["lessons_per_week"] or 1)))
                existing_links = requirement_links_values.get(existing_id, "[]")
                existing_target = int(existing_requirement["lessons_per_week"] or 1)
                existing_max_day = existing_requirement["max_lessons_per_day"] or ""
            else:
                existing_pattern, existing_links, existing_target, existing_max_day = "1", "[]", 5, ""
            class_label = str(allocation_row["class_name"]) + (" " + str(allocation_row["stream"] or "")).rstrip()
            requirement_allocation_option_rows.append(
                f"<option value='{allocation_key[0]}|{allocation_key[1]}|{allocation_key[2]}' "
                f"data-class-id='{allocation_key[0]}' data-class-label='{esc(class_label)}' "
                f"data-subject-id='{allocation_key[1]}' data-subject-label='{esc(allocation_row['subject_name'])}' "
                f"data-teacher-id='{allocation_key[2]}' data-teacher-label='{esc(allocation_row['teacher_name'])}' "
                f"data-weekly-target='{existing_target}' data-max-day='{esc(existing_max_day)}' "
                f"data-pattern='{esc(existing_pattern)}' data-links='{esc(existing_links)}'>"
                f"{esc(class_label)} · {esc(allocation_row['subject_name'])} · {esc(allocation_row['teacher_name'])}</option>"
            )
        requirement_allocation_options = "".join(requirement_allocation_option_rows)
        # Render allocated classes into the Add Subject Requirement dialog on
        # the server. This keeps the class selector usable even if client-side
        # filter initialisation is delayed or interrupted.
        allocated_class_labels = {
            int(row["class_id"]): str(row["class_name"]) + (" " + str(row["stream"] or "")).rstrip()
            for row in allocations
        }
        requirement_class_options = "".join(
            f"<option value='{class_id}'>{esc(label)}</option>"
            for class_id, label in sorted(allocated_class_labels.items(), key=lambda item: item[1].casefold())
        )
        allocated_teacher_labels = {int(row["teacher_id"]): str(row["teacher_name"]) for row in allocations}
        allocated_subject_labels = {int(row["subject_id"]): str(row["subject_name"]) for row in allocations}
        requirement_teacher_options = "".join(
            f"<option value='{teacher_id}'>{esc(label)}</option>"
            for teacher_id, label in sorted(allocated_teacher_labels.items(), key=lambda item: item[1].casefold())
        )
        requirement_subject_options = "".join(
            f"<option value='{subject_id}'>{esc(label)}</option>"
            for subject_id, label in sorted(allocated_subject_labels.items(), key=lambda item: item[1].casefold())
        )
        bulk_requirement_form = f"""
          <div class='tt-req-add-modal' id='tt-req-add-modal' role='dialog' aria-modal='true' aria-labelledby='tt-req-add-title' hidden>
            <div class='tt-req-add-dialog'>
              <div class='tt-req-add-head'>
                <div><span class='tt-kicker'>WEEKLY LESSON LOAD</span><h3 id='tt-req-add-title'>Set subject requirement</h3><p>Build the complete weekly mix of single, double and triple lessons for one allocated subject.</p></div>
                <button type='button' class='tt-req-add-close' data-req-add-close aria-label='Close'>&times;</button>
              </div>
              <form method='post' data-native-post='true' action='/app/timetable/setup/requirement' class='tt-form compact tt-req-add-form'>
                {hidden}
                <label>Class / stream
                  <select name='class_id' data-allocation-filter='class' required><option value=''>Choose class / stream</option>{requirement_class_options}</select>
                </label>
                <label>Teacher
                  <select name='teacher_id' data-allocation-filter='teacher' required><option value=''>Choose teacher</option>{requirement_teacher_options}</select>
                </label>
                <label class='wide'>Subject
                  <select name='subject_id' data-allocation-filter='subject' required><option value=''>Choose subject</option>{requirement_subject_options}</select>
                  <small data-allocation-match>Choose any one filter first. The other fields will narrow to valid teacher allocations.</small>
                </label>
                <select name='allocation' data-allocation-source hidden>
                  <option value=''>Select an allocated subject</option>{requirement_allocation_options}
                </select>
                <label>Weekly period target<input type='number' min='1' max='30' name='lessons_per_week' value='5' required></label>
                <label>Maximum lessons per day<input type='number' min='1' max='10' name='max_lessons_per_day' placeholder='No daily limit'></label>
                <div class='wide tt-session-editor' data-session-editor>
                  <div class='tt-session-editor-head'><div><b>Session-by-session plan</b><span>One row represents one occurrence in the week</span></div><span class='tt-session-step'>1 · Set durations</span></div>
                  <div class='tt-session-balance' data-session-balance>1 of 5 periods assigned · 4 remaining</div>
                  <div class='tt-session-list' data-session-list>
                    <div class='tt-session-row'>
                      <div class='tt-session-row-main'><span class='tt-session-number'>1</span>
                        <label>Lesson duration<select data-session-duration><option value='1'>Single · 1 period</option><option value='2'>Double · 2 periods</option><option value='3'>Triple · 3 periods</option><option value='4'>Quadruple · 4 periods</option></select></label>
                        <label>Preferred start<select data-session-period><option value=''>Automatic</option>{period_start_options}</select></label>
                        <small data-session-span>Automatic placement</small><button type='button' data-remove-session disabled>Remove</button>
                      </div>
                      <details class='tt-session-sharing-details'><summary>Optional sharing · link classes or co-teachers</summary><div class='tt-session-row-sharing'><label>Link another class<select multiple data-session-classes>{class_group_options}</select></label><label>Add co-teacher<select multiple data-session-teachers>{teacher_group_options}</select></label></div></details>
                    </div>
                  </div>
                  <button type='button' class='tt-btn secondary' data-add-session>＋ Add another occurrence</button>
                  <input type='hidden' name='weekly_pattern' data-weekly-pattern><input type='hidden' name='weekly_links' value='[]'><input type='hidden' name='pattern_mode' value='replace'>
                  <p class='tt-session-instructions'>Set each occurrence's duration until the assigned total matches the weekly target. Leave start periods on Automatic if you have no preference. Optional class and co-teacher links are tucked away under each session.</p>
                </div>
                <div class='tt-req-add-footer'><button type='button' class='tt-btn secondary' data-req-add-close>Cancel</button><button class='tt-btn' type='submit'>Save weekly plan</button></div>
              </form>
            </div>
          </div>
          <script>
          (function(){{
            const init=()=>{{
            const root=document.querySelector('.tt-requirements-section');
            if(!root||root.dataset.reqAddReady)return;
            root.dataset.reqAddReady='1';
            const modal=root.querySelector('#tt-req-add-modal');
            if(!modal)return;
            const open=()=>{{modal.hidden=false;document.body.classList.add('tt-modal-scroll-locked');}};
            root.querySelectorAll('[data-session-editor]').forEach(ed=>{{
              const list=ed.querySelector('[data-session-list]'), hidden=ed.querySelector('[data-weekly-pattern]');
              const periodOptions="<option value=''>Auto</option>{period_start_options}";
              const makeRow=(duration,periodNo,classes=[],teachers=[])=>{{const row=document.createElement('div');row.className='tt-session-row';row.innerHTML="<div class='tt-session-row-main'><span class='tt-session-number'></span><label>Lesson duration<select data-session-duration><option value='1'>Single · 1 period</option><option value='2'>Double · 2 periods</option><option value='3'>Triple · 3 periods</option><option value='4'>Quadruple · 4 periods</option></select></label><label>Preferred start<select data-session-period>"+periodOptions+"</select></label><small data-session-span>Automatic placement</small><button type='button' data-remove-session>Remove</button></div><details class='tt-session-sharing-details'><summary>Optional sharing · link classes or co-teachers</summary><div class='tt-session-row-sharing'><label>Link another class<select multiple data-session-classes>{class_group_options}</select></label><label>Add co-teacher<select multiple data-session-teachers>{teacher_group_options}</select></label></div></details>";row.querySelector('[data-session-duration]').value=duration;row.querySelector('[data-session-period]').value=periodNo||'';classes.forEach(v=>{{const o=[...row.querySelectorAll('[data-session-classes] option')].find(x=>x.value===String(v));if(o)o.selected=true;}});teachers.forEach(v=>{{const o=[...row.querySelectorAll('[data-session-teachers] option')].find(x=>x.value===String(v));if(o)o.selected=true;}});return row;}};
              const sync=()=>{{const vals=[...list.querySelectorAll('.tt-session-row')].map(row=>{{const duration=row.querySelector('[data-session-duration]')?.value||'1',period=row.querySelector('[data-session-period]')?.value||'',span=row.querySelector('[data-session-span]');if(span)span.textContent=period?'Starts P'+period+' · occupies P'+period+(Number(duration)>1?'–P'+(Number(period)+Number(duration)-1):''):'Automatic placement'+(Number(duration)>1?' · '+duration+' consecutive periods':'');return {{pattern:duration+(period?'@'+period:''),classes:[...row.querySelectorAll('[data-session-classes] option:checked')].map(o=>o.value),teachers:[...row.querySelectorAll('[data-session-teachers] option:checked')].map(o=>o.value)}};}});hidden.value=vals.map(v=>v.pattern).join(',');const linkField=ed.querySelector('[name=weekly_links]');if(linkField)linkField.value=JSON.stringify(vals.map(v=>({{classes:v.classes,teachers:v.teachers}})));[...list.children].forEach((x,i)=>{{const number=x.querySelector('.tt-session-number');if(number)number.textContent=String(i+1);}});list.querySelectorAll('[data-remove-session]').forEach(x=>x.disabled=list.children.length===1);const total=vals.reduce((n,v)=>n+Number(v.pattern.split('@')[0]||0),0),target=Number(ed.closest('form')?.querySelector('[name=lessons_per_week]')?.value||0),remaining=target-total,balance=ed.querySelector('[data-session-balance]');if(balance)balance.textContent=total+' of '+target+' periods assigned · '+(remaining>0?remaining+' remaining':remaining<0?Math.abs(remaining)+' over target':'Weekly target reached')+' · '+vals.length+' occurrence(s)';}};
              const linkField=ed.querySelector('[name=weekly_links]');const parsePattern=(pattern,linksJson)=>{{let links=[];try{{links=JSON.parse(linksJson||'[]');}}catch(e){{links=[];}}return (pattern||'').split(',').map((x,i)=>{{const bits=x.trim().split('@'),item=links[i]||{{}};return {{duration:parseInt(bits[0],10),period:bits[1]||'',classes:item.classes||[],teachers:item.teachers||[]}};}}).filter(x=>x.duration>=1&&x.duration<=4);}};const initial=parsePattern(hidden.value,linkField?.value);if(initial.length){{list.innerHTML='';initial.forEach(v=>list.appendChild(makeRow(v.duration,v.period,v.classes,v.teachers)));}}
              const addForm=ed.closest('.tt-req-add-form');if(addForm){{const allocationSelect=addForm.querySelector('[name=allocation]'),targetInput=addForm.querySelector('[name=lessons_per_week]'),maxDayInput=addForm.querySelector('[name=max_lessons_per_day]'),filterSelects={{class:addForm.querySelector('[data-allocation-filter=class]'),teacher:addForm.querySelector('[data-allocation-filter=teacher]'),subject:addForm.querySelector('[data-allocation-filter=subject]')}},matchNote=addForm.querySelector('[data-allocation-match]');const allocationRows=[...allocationSelect.options].filter(o=>o.value).map(o=>({{value:o.value,classId:o.dataset.classId,classLabel:o.dataset.classLabel,teacherId:o.dataset.teacherId,teacherLabel:o.dataset.teacherLabel,subjectId:o.dataset.subjectId,subjectLabel:o.dataset.subjectLabel,option:o}}));const unique=(rows,id,label)=>{{const found=new Map();rows.forEach(row=>found.set(row[id],row[label]));return [...found].map(([value,text])=>({{value,text}})).sort((a,b)=>a.text.localeCompare(b.text));}};const fillSelect=(select,items,placeholder,current)=>{{const keep=items.some(x=>x.value===current)?current:'';select.innerHTML='';const first=document.createElement('option');first.value='';first.textContent=placeholder;select.appendChild(first);items.forEach(item=>{{const option=document.createElement('option');option.value=item.value;option.textContent=item.text;select.appendChild(option);}});select.value=keep;}};const loadAllocation=()=>{{const option=allocationSelect?.selectedOptions?.[0];if(!option||!option.value)return;targetInput.value=option.dataset.weeklyTarget||'5';maxDayInput.value=option.dataset.maxDay||'';const rows=parsePattern(option.dataset.pattern||'1',option.dataset.links||'[]');list.innerHTML='';(rows.length?rows:[{{duration:1,period:'',classes:[],teachers:[]}}]).forEach(v=>list.appendChild(makeRow(v.duration,v.period,v.classes,v.teachers)));sync();}};const refreshAllocationFilters=(changed)=>{{const classId=filterSelects.class.value;const teacherId=filterSelects.teacher.value;const subjectId=filterSelects.subject.value;const classRows=allocationRows.filter(row=>!classId||row.classId===classId);const teachers=unique(classRows,'teacherId','teacherLabel');if(changed==='class'){{filterSelects.teacher.value='';filterSelects.subject.value='';}}fillSelect(filterSelects.teacher,teachers,'Choose teacher',changed==='class'?'':teacherId);const activeTeacher=filterSelects.teacher.value;const teacherRows=classRows.filter(row=>!activeTeacher||row.teacherId===activeTeacher);const subjects=unique(teacherRows,'subjectId','subjectLabel');if(changed==='teacher')filterSelects.subject.value='';fillSelect(filterSelects.subject,subjects,'Choose subject',filterSelects.subject.value||subjectId);if(subjects.length===1)filterSelects.subject.value=subjects[0].value;const selectedSubject=filterSelects.subject.value;const exact=allocationRows.find(row=>row.classId===classId&&row.teacherId===activeTeacher&&row.subjectId===selectedSubject);allocationSelect.value=exact?exact.value:'';if(exact){{loadAllocation();matchNote.textContent='Matched allocation: '+exact.classLabel+' · '+exact.teacherLabel+' · '+exact.subjectLabel;}}else if(!classId){{matchNote.textContent='Choose a class / stream to see its allocated teachers.';}}else if(!activeTeacher){{matchNote.textContent=teachers.length+' teacher(s) allocated to this class. Choose a teacher.';}}else if(subjects.length===1){{matchNote.textContent='The allocated subject has been selected automatically.';}}else{{matchNote.textContent=subjects.length+' subject(s) allocated to this teacher in this class. Choose a subject.';}}}};filterSelects.teacher.disabled=true;filterSelects.subject.disabled=true;filterSelects.class.addEventListener('change',()=>{{filterSelects.teacher.disabled=!filterSelects.class.value;filterSelects.subject.disabled=true;refreshAllocationFilters('class');}});filterSelects.teacher.addEventListener('change',()=>{{filterSelects.subject.disabled=!filterSelects.teacher.value;refreshAllocationFilters('teacher');}});filterSelects.subject.addEventListener('change',()=>refreshAllocationFilters('subject'));refreshAllocationFilters('');targetInput?.addEventListener('input',sync);maxDayInput?.addEventListener('input',sync);}}
              ed.querySelectorAll('[data-add-session]').forEach(button=>button.addEventListener('click',e=>{{e.preventDefault();list.appendChild(makeRow(1));sync();}}));ed.addEventListener('click',e=>{{const rm=e.target.closest('[data-remove-session]');if(rm&&!rm.disabled&&ed.contains(rm)){{e.preventDefault();rm.closest('.tt-session-row').remove();sync();}}}});
              ed.addEventListener('change',e=>{{if(e.target.matches('[data-session-duration],[data-session-period],[data-session-classes],[data-session-teachers]'))sync();}});
              const filter=()=>{{const c=(ed.querySelector('[data-class-filter]')?.value||'').toLowerCase(),t=(ed.querySelector('[data-teacher-filter]')?.value||'').toLowerCase();[...ed.querySelectorAll('[data-link-class] option')].forEach((o,i)=>{{if(i)o.hidden=!!(c&&!o.text.toLowerCase().includes(c));}});[...ed.querySelectorAll('[data-link-teacher] option')].forEach((o,i)=>{{if(i)o.hidden=!!(t&&!o.text.toLowerCase().includes(t));}});}};
              ed.querySelectorAll('[data-class-filter],[data-teacher-filter]').forEach(x=>x.addEventListener('input',filter));sync();ed.closest('form')?.addEventListener('submit',()=>sync());
            }});
            const close=()=>{{modal.hidden=true;document.body.classList.remove('tt-modal-scroll-locked');}};
            root.addEventListener('click',event=>{{
              const manageOpen=event.target.closest('[data-req-manage-open]');
              if(manageOpen){{const target=root.querySelector('#'+manageOpen.dataset.reqManageOpen);if(target){{target.classList.add('is-open');document.body.classList.add('tt-modal-scroll-locked');target.querySelector('input,select,button')?.focus();}}return;}}
              const manageClose=event.target.closest('[data-req-manage-close]');
              if(manageClose){{const target=manageClose.closest('.tt-req-manage-modal');target?.classList.remove('is-open');if(!root.querySelector('.tt-modal.is-open'))document.body.classList.remove('tt-modal-scroll-locked');return;}}
              const manageBackdrop=event.target.classList.contains('tt-req-manage-modal')?event.target:null;
              if(manageBackdrop){{manageBackdrop.classList.remove('is-open');if(!root.querySelector('.tt-modal.is-open'))document.body.classList.remove('tt-modal-scroll-locked');return;}}
              if(event.target.closest('[data-req-add-open]')){{open();return;}}
              if(event.target.closest('[data-req-add-close]')||event.target===modal)close();
            }});
            const addForm=modal.querySelector('.tt-req-add-form');addForm?.addEventListener('submit',event=>{{const allocationSelect=addForm.querySelector('[name=allocation]'),matchNote=addForm.querySelector('[data-allocation-match]');if(!allocationSelect?.value){{event.preventDefault();if(matchNote)matchNote.textContent='Please narrow the filters until one valid class, teacher and subject allocation is matched.';return;}}if(addForm.dataset.saving==='1'){{event.preventDefault();return;}}addForm.dataset.saving='1';const submit=addForm.querySelector('button[type=submit]');if(submit){{submit.disabled=true;submit.textContent='Saving weekly plan…';submit.style.opacity='.75';}}}});
            root.addEventListener('keydown',event=>{{if(event.key==='Escape'){{const active=root.querySelector('.tt-req-manage-modal.is-open');if(active){{active.classList.remove('is-open');if(!root.querySelector('.tt-modal.is-open'))document.body.classList.remove('tt-modal-scroll-locked');}}else if(!modal.hidden)close();}}}});
            }};
            if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{{once:true}});else init();
          }})();
          </script>
        """

        create_profile_html = """<section class='tt-card tt-profile-create-card'><span class='tt-kicker'>FIRST STEP</span><h3>Create timetable profile</h3><p>Create a separate main, weekend, remedial or special timetable. Each programme has its own setup and publishing history.</p><a class='tt-btn' href='#tt-profile-create-modal'>＋ Create timetable profile</a><span id='tt-profile-create-close'></span><div class='tt-modal' id='tt-profile-create-modal' role='dialog' aria-modal='true' aria-labelledby='tt-profile-create-title'><div class='tt-modal-dialog'><div class='tt-modal-head'><div><span class='tt-kicker'>FIRST STEP</span><h3 id='tt-profile-create-title'>Create timetable profile</h3><p>Choose the academic year and term for this schedule.</p></div><a class='tt-modal-close' href='#tt-profile-create-close' aria-label='Close'>&times;</a></div><form method='post' data-native-post='true' action='/app/timetable/setup/profile' class='tt-form'><label>Timetable type<select name='profile_type' required><option value='main'>Main School Timetable</option><option value='weekend'>Weekend Lessons</option><option value='remedial'>Weekday Remedials</option><option value='special'>Other / Special Timetable</option></select></label><label>Profile name<input name='name' required maxlength='80' placeholder='e.g. 2027 Term 1 Weekend Lessons'></label><label>Academic year<input name='academic_year' required maxlength='20' placeholder='2027'></label><label>Term / semester<input name='term' required maxlength='40' placeholder='Term 1, Semester 1, Quarter 1…'></label><label>Academic start date<input name='academic_start_date' type='date'></label><label>Academic end date<input name='academic_end_date' type='date'></label><button class='tt-btn' type='submit'>Create profile</button></form></div></div></section>"""
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
            <section class='tt-section'><div class='tt-section-title'><div><span class='tt-kicker'>05 · LEARNING SPACES</span><h3>Rooms and facilities</h3><p>Optional setup: register physical spaces only if your school wants room allocation. Leave this section empty if rooms are not needed. Classes and streams are managed separately.</p></div></div><div class='tt-split'><form method='post' data-native-post='true' action='/app/timetable/setup/room' class='tt-form compact'>{hidden}<label>Room code<input name='room_code' required placeholder='LAB-01'></label><label>Room name<input name='name' required placeholder='Science Laboratory'></label><label>Room type<select name='room_type'><option value='classroom'>Classroom</option><option value='laboratory'>Laboratory</option><option value='library'>Library</option><option value='hall'>Hall</option><option value='workshop'>Workshop</option><option value='sports'>Sports facility</option><option value='other'>Other</option></select></label><label>Capacity (optional)<input name='capacity' type='number' min='1' placeholder='Leave blank if unrestricted'></label>{room_policy_fields('shared',None)}<label class='wide'>Description (optional)<input name='description' maxlength='240' placeholder='Location or purpose'></label><label class='wide'>Equipment / resources (optional)<input name='equipment' maxlength='400' placeholder='Projector, computers, lab benches…'></label><label class='wide'>Suitable for (optional)<input name='suitable_for' maxlength='300' placeholder='Science practicals, exams, meetings…'></label><button class='tt-btn'>Save room / facility</button></form><div class='tt-table'><table><tr><th>Code</th><th>Room</th><th>Type</th><th>Capacity</th><th>Allocation</th><th>Equipment / resources</th><th>Actions</th></tr>{room_rows}</table></div></div></section>
            <section class='tt-section tt-availability-workspace'>
              <style>
                .tt-availability-tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px;padding:6px;background:#f0f6f1;border:1px solid #dce9df;border-radius:13px;width:fit-content;max-width:100%}}
                .tt-availability-tab{{border:1px solid transparent;border-radius:9px;padding:10px 16px;background:transparent;color:#557064;font-size:12px;font-weight:800;cursor:pointer}}
                .tt-availability-tab[aria-selected='true']{{background:#176344;color:#fff;box-shadow:0 3px 9px rgba(23,99,68,.16)}}
                .tt-availability-tab-panel[hidden]{{display:none!important}}
                @media(max-width:520px){{.tt-availability-tabs{{width:100%}}.tt-availability-tab{{flex:1;padding:10px 9px}}}}
              </style>
              <div class='tt-section-title'><div><span class='tt-kicker'>06 · AVAILABILITY</span><h3>Staff and subject availability</h3><p>Manage when individual staff members and subjects can be scheduled. Both settings apply to the selected timetable profile.</p></div></div>
              <div class='tt-availability-tabs' role='tablist' aria-label='Availability settings'>
                <button type='button' class='tt-availability-tab' role='tab' id='tt-tab-staff-availability' aria-controls='tt-panel-staff-availability' aria-selected='true' data-availability-tab='staff'>Staff availability</button>
                <button type='button' class='tt-availability-tab' role='tab' id='tt-tab-subject-availability' aria-controls='tt-panel-subject-availability' aria-selected='false' data-availability-tab='subject'>Subject availability</button>
              </div>
              <div class='tt-availability-tab-panel' role='tabpanel' id='tt-panel-staff-availability' aria-labelledby='tt-tab-staff-availability' data-availability-panel='staff'>
<div class='tt-section-title'><div><span class='tt-kicker'>06 · STAFF AVAILABILITY</span><h3>Teacher availability</h3><p>All teachers are available by default. Add a teacher only when you need to set fallback periods or block specific periods.</p></div></div><div class='tt-availability-editor'><form method='post' data-native-post='true' action='/app/timetable/setup/availability-matrix' class='tt-form compact'>{hidden}<label>Teacher<select name='teacher_id' id='tt-availability-teacher' required>{teacher_opts}</select></label><div class='tt-availability-legend'><span><b>✓</b> Available first</span><span><b>Blank</b> Fallback only</span><span><b>X</b> Never place</span></div><div class='tt-table tt-availability-grid'><table><thead><tr><th>Day / Period</th>{matrix_period_headers}</tr></thead><tbody>{matrix_day_rows}</tbody></table></div><p class='tt-muted'>Every cell starts ticked (available). Tap to cycle: ✓ available → blank (fallback only) → X (never place). The generator tries all ticked periods first and uses blank periods only when needed to complete the timetable.</p><button class='tt-btn'>Save teacher availability</button></form><div class='tt-availability-summary'><label class='tt-summary-search'>Search teachers<input type='search' data-availability-search='teacher' placeholder='Find teacher…'></label><div class='tt-table'><h4>Teacher restrictions</h4><table><thead><tr><th>Teacher</th><th title='Total restricted cells'>#</th><th title='Available'>✓</th><th title='Fallback only'>—</th><th title='Unavailable'>X</th><th>Actions</th></tr></thead><tbody>{availability_rows}</tbody></table></div></div></div>
              </div>
              <div class='tt-availability-tab-panel' role='tabpanel' id='tt-panel-subject-availability' aria-labelledby='tt-tab-subject-availability' data-availability-panel='subject' hidden>
<div class='tt-availability-summary tt-subject-restrictions-register'>
  <label class='tt-summary-search'>Search subjects<input type='search' data-availability-search='subject' placeholder='Find subject…'></label>
  <div class='tt-table'><h4>Subject restrictions</h4><table><thead><tr><th>Subject</th><th title='Total restricted cells'>#</th><th title='Available'>✓</th><th title='Fallback only'>—</th><th title='Unavailable'>X</th><th>Actions</th></tr></thead><tbody>{subject_availability_rows}</tbody></table></div>
</div>
<div class='tt-modal tt-subject-availability-modal' id='tt-subject-availability-modal' role='dialog' aria-modal='true' aria-labelledby='tt-subject-availability-modal-title'>
  <div class='tt-modal-dialog'>
    <div class='tt-modal-head'><div><span class='tt-kicker'>SUBJECT RESTRICTIONS</span><h3 id='tt-subject-availability-modal-title'>Edit subject availability</h3><p>Choose the periods this subject may use.</p></div><button type='button' class='tt-modal-close' data-subject-av-close aria-label='Close'>&times;</button></div>
    <form method='post' data-native-post='true' action='/app/timetable/setup/subject-availability-matrix' class='tt-form compact tt-subject-availability-editor'>{hidden}
      <label>Subject<select name='subject_id' id='tt-subject-availability' required>{''.join(f"<option value='{int(x['id'])}'>{esc(x['name'])}</option>" for x in subjects)}</select></label>
      <div class='tt-availability-legend'><span><b>✓</b> Available first</span><span><b>Blank</b> Fallback only</span><span><b>X</b> Never schedule</span></div>
      <div class='tt-table tt-availability-grid'><table><thead><tr><th>Day / Period</th>{subject_matrix_period_headers}</tr></thead><tbody>{subject_matrix_day_rows}</tbody></table></div>
      <p class='tt-muted'>Tap each cell to cycle: ✓ available → blank (fallback only) → X (never schedule).</p>
      <div class='tt-modal-actions'><button type='button' class='tt-btn secondary' data-subject-av-close>Cancel</button><button class='tt-btn'>Save subject restrictions</button></div>
    </form>
  </div>
</div>
              </div>
            </section>
            {class_limit_form}
            {teacher_colour_section}
            {allocation_monitor_section}
            <section class='tt-section tt-requirements-section' id='tt-subject-requirements'>
 <div class='tt-req-page-head'>
  <div><span class='tt-kicker'>WEEKLY LESSON PLANNING</span><h2>Subject requirements</h2><p>Set each class-subject weekly workload, define its single and double sessions, and review teacher allocations before timetable generation.</p></div>
  <div class='tt-req-head-actions'><button type='button' class='tt-btn' data-req-add-open>＋ Add subject requirement</button></div>
 </div>
 {bulk_requirement_form}
 <div class='tt-req-overview'>
  <div><span>Configured requirements</span><b>{len(requirements)}</b><small>Class · subject allocations</small></div>
  <div><span>Allocated classes</span><b>{len(set(int(x['class_id']) for x in requirements))}</b><small>With weekly requirements</small></div>
  <div><span>Weekly periods</span><b>{sum(int(x['lessons_per_week'] or 0)*int(x['duration_periods'] or 1) for x in requirements)}</b><small>Configured period load</small></div>
  <div><span>Teachers involved</span><b>{len(set(int(x['teacher_id']) for x in requirements))}</b><small>Lead allocations</small></div>
 </div>
 <div class='tt-req-main-layout'>
  <div class='tt-req-workspace'>
   <div class='tt-req-toolbar'>
    <label class='tt-req-search'><span>Search requirements</span><input type='search' id='tt-req-search' placeholder='Search class, subject or teacher…'></label>
    <details class='tt-req-filter'><summary>⚙ Filters <span id='tt-req-filter-count'>All</span></summary><div class='tt-req-filter-panel'><div class='tt-req-filter-head'><strong>Filter requirements</strong><button type='button' class='tt-req-filter-close' aria-label='Close filters' title='Close filters'>×</button></div><label>Class / stream<select id='tt-req-class'><option value=''>All classes</option>{requirement_class_filters}</select></label><label>Subject<select id='tt-req-subject'><option value=''>All subjects</option>{requirement_subject_filters}</select></label><label>Teacher<select id='tt-req-teacher'><option value=''>All teachers</option>{requirement_teacher_filters}</select></label><button type='button' class='tt-btn secondary' id='tt-req-reset'>Clear filters</button></div></details>
    <span class='tt-req-count' id='tt-req-count'></span>
   </div>
   <div class='tt-req-results-head'><div><h3>Configured weekly requirements</h3><p>Open Manage to edit the weekly target and session pattern.</p></div><span class='tt-req-results-total'>{len(requirements)} records</span></div>
   <div class='tt-req-groups'>{requirement_rows}</div>
   <div class='tt-req-pagination'><span id='tt-req-page-info'></span><div><button type='button' class='tt-btn secondary' id='tt-req-prev'>← Previous</button><button type='button' class='tt-btn secondary' id='tt-req-next'>Next →</button></div></div>
  </div>
 </div>
</section>
            """
        body = f"""
        <style>
        .tt-wrap{{max-width:1500px;margin:auto;padding:22px;color:#234638}}
        .tt-requirements-section{{padding:0!important;overflow:hidden}}
        .tt-req-page-head{{display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;padding:24px 26px;background:linear-gradient(115deg,#e5f2e7,#f6faf6);border-bottom:1px solid #dce9de}}
        .tt-req-page-head h2{{margin:5px 0 6px;color:#204b34;font-size:25px;letter-spacing:-.5px}}
        .tt-req-page-head p{{max-width:720px;color:#637b6a;font-size:12px;line-height:1.6;margin:0}}
        .tt-req-head-actions{{display:flex;gap:8px;align-items:center}}
        .tt-req-overview{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:15px 20px;background:#fff;border-bottom:1px solid #e5eee6}}
        .tt-req-overview>div{{padding:12px 14px;border:1px solid #e1ece2;border-radius:12px;background:#fbfdfb;min-width:0}}
        .tt-req-overview span,.tt-req-overview small{{display:block;color:#718477;font-size:10px;font-weight:700}}
        .tt-req-overview b{{display:block;color:#286443;font-size:23px;line-height:1.35;margin:2px 0}}
        .tt-req-main-layout{{display:block;min-width:0}}
        
        .tt-req-results-head h3{{font-size:15px;color:#254d36;margin:4px 0}}
        .tt-req-results-head p{{font-size:11px;color:#718477;line-height:1.5;margin:0 0 14px}}
        .tt-req-workspace{{padding:20px;min-width:0}}
        .tt-req-toolbar{{margin-bottom:14px}}
        .tt-req-results-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:8px 0 12px}}
        .tt-req-results-total{{white-space:nowrap;padding:6px 9px;border-radius:20px;background:#edf6ee;color:#316b45;font-size:10px;font-weight:800}}
        .tt-req-table{{border:1px solid #e0eae1;border-radius:13px;overflow-x:auto;background:#fff}}
        .tt-req-table table{{min-width:680px}}
        .tt-req-table thead th{{background:#f1f7f2;color:#486651;font-size:10px;text-transform:uppercase;letter-spacing:.04em;padding:12px}}
        .tt-req-table tbody td{{padding:12px;font-size:12px;vertical-align:middle}}
        .tt-req-table tbody tr:nth-child(even){{background:#fbfdfb}}
        .tt-req-table tbody tr:hover{{background:#f2f8f3}}
        .tt-req-table .tt-req-subline{{display:block;color:#7a8c7f;font-size:10px;margin-top:4px}}
        .tt-req-groups{{display:grid;gap:15px}}
        .tt-req-class-group{{border:1px solid #dfeae1;border-radius:15px;background:#fff;overflow:hidden}}
        .tt-req-class-group[hidden]{{display:none!important}}
        .tt-req-class-group>header{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 16px;background:#f1f7f2;border-bottom:1px solid #e2ece3;color:#28543a}}
        .tt-req-class-group>header b{{font-size:13px}}
        .tt-req-class-group>header span{{font-size:10px;font-weight:800;color:#6e8574;background:#fff;border:1px solid #e0eae1;border-radius:20px;padding:5px 9px}}
        .tt-req-card{{padding:14px 16px;border-bottom:1px solid #edf2ed;background:#fff}}
        .tt-req-card:last-child{{border-bottom:0}}
        .tt-req-card[hidden]{{display:none!important}}
        .tt-req-card:hover{{background:#fbfdfb}}
        .tt-req-card-main{{display:grid;grid-template-columns:minmax(150px,1fr) minmax(200px,1.25fr) auto;align-items:center;gap:18px}}
        .tt-req-card-title{{display:grid;gap:5px;min-width:0}}
        .tt-req-card-subject{{font-size:13px;font-weight:850;color:#254d36}}
        .tt-req-card-teacher{{font-size:10px;color:#718477}}
        .tt-req-card-load{{min-width:0}}
        .tt-req-card-action{{display:flex;justify-content:flex-end}}
        .tt-req-manage-button{{border:1px solid #d7e6da;background:#f8fcf8;color:#286443;border-radius:9px;padding:9px 13px;font-size:11px;font-weight:850;white-space:nowrap;cursor:pointer}}
        .tt-req-manage-button:hover{{background:#eaf5ec;border-color:#a9cbb0}}
        .tt-req-manage-dialog{{width:min(820px,100%);}}
        .tt-req-manage-content{{max-height:calc(88vh - 115px);overflow:auto;padding-right:3px}}
        .tt-req-manage-content .tt-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
        .tt-req-manage-content .tt-form label.wide{{grid-column:1/-1}}
        .tt-req-manage-content .tt-form button{{grid-column:1/-1}}
        .tt-req-manage-content form+form{{margin-top:12px;padding-top:12px;border-top:1px solid #e2ebe3}}
        .tt-req-manage-content form+form button{{width:auto}}
        @media(max-width:600px){{.tt-req-manage-dialog{{width:100%;max-height:94vh;padding:18px 14px}}.tt-req-manage-content .tt-form{{grid-template-columns:1fr}}.tt-req-manage-content .tt-form label.wide{{grid-column:auto}}}}
        .tt-req-card-action>details{{position:relative}}
        .tt-req-card-action>details>summary{{list-style:none;cursor:pointer;border:1px solid #d7e6da;background:#f8fcf8;color:#286443;border-radius:9px;padding:9px 13px;font-size:11px;font-weight:850;white-space:nowrap}}
        .tt-req-card-action>details>summary::-webkit-details-marker{{display:none}}
        .tt-req-card-action>details[open]{{grid-column:1/-1}}
        .tt-req-card-action>details[open] .tt-req-manage{{margin-top:10px;padding:14px;border:1px solid #e0ebe2;border-radius:12px;background:#f8fbf8;min-width:min(680px,80vw)}}
        .tt-req-empty{{padding:35px 20px;text-align:center;border:1px dashed #cfdfd2;border-radius:14px;background:#fbfdfb;color:#6c8172;font-size:12px}}
        @media(max-width:700px){{.tt-req-card-main{{grid-template-columns:minmax(0,1fr) auto;gap:10px}}.tt-req-card-load{{grid-column:1/-1;grid-row:2}}.tt-req-card-action{{grid-column:2;grid-row:1}}.tt-req-card-action>details[open]{{grid-column:1/-1}}.tt-req-card-action>details[open] .tt-req-manage{{min-width:0;width:calc(100vw - 82px)}}.tt-req-class-group>header{{padding:11px 13px}}.tt-req-card{{padding:12px 13px}}}}

        .tt-req-pagination{{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding-top:13px}}
        .tt-req-pagination>div{{display:flex;gap:7px}}
        .tt-req-filter-panel{{z-index:30}}
        .tt-req-add-modal{{position:fixed;inset:0;z-index:10000;background:rgba(18,42,27,.48);display:flex;align-items:center;justify-content:center;padding:18px}}
        .tt-req-add-modal[hidden]{{display:none}}
        .tt-req-add-dialog{{width:min(900px,100%);max-height:88vh;overflow:auto;background:#fff;border-radius:20px;box-shadow:0 24px 80px rgba(12,37,21,.25)}}
        .tt-session-chip-list{{display:flex;gap:5px;flex-wrap:wrap;align-items:center}}.tt-session-chip{{display:inline-flex;padding:5px 8px;border-radius:7px;background:#e8f4ea;color:#286541;font-size:10px;font-weight:850;white-space:nowrap}}.tt-session-chip.muted{{background:#f0f3f0;color:#718077}}.tt-session-editor{{grid-column:1/-1;border:1px solid #dce9de;border-radius:13px;padding:13px;background:#f8fbf8}}
        .tt-session-editor-head{{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:10px;color:#28543a;font-size:12px}}
        .tt-session-editor-head span{{font-size:10px;color:#728477}}
        .tt-session-filters,.tt-session-linking{{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:9px 0}}
        .tt-session-editor label{{display:grid;gap:5px;font-size:10px;font-weight:800;color:#496451}}
        .tt-session-editor input,.tt-session-editor select{{width:100%;min-width:0;padding:9px;border:1px solid #d5e4d7;border-radius:9px;background:white;color:#234638}}
        .tt-session-list{{display:grid;gap:9px;margin:12px 0}}.tt-session-balance{{padding:11px 13px;border:1px solid #cfe3d2;border-radius:10px;background:#eaf5ec;color:#286541;font-size:12px;font-weight:850}}
        .tt-session-row{{display:grid;gap:7px;padding:9px;background:#fff;border:1px solid #dce9de;border-radius:11px}}
        .tt-session-row-main{{display:grid;grid-template-columns:28px minmax(0,1fr) minmax(0,1fr) auto;align-items:end;gap:8px}}
        .tt-session-sharing-details{{border-top:1px dashed #e1ebe2;padding-top:6px}}.tt-session-sharing-details>summary{{cursor:pointer;color:#52745c;font-size:10px;font-weight:750}}.tt-session-row-sharing{{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding-top:8px}}
        .tt-session-number{{width:27px;height:27px;display:grid;place-items:center;border-radius:8px;background:#e8f3e9;color:#2b6943;font-size:11px;font-weight:900;flex:none}}
        .tt-session-row-main label,.tt-session-row-sharing label{{min-width:0}}
        .tt-session-row-main small{{grid-column:2/-1;font-size:10px;color:#64806b;line-height:1.3;padding:0}}
        .tt-session-row button{{border:1px solid #ead6d4;border-radius:8px;padding:9px 10px;background:#fff5f4;color:#9d4842;font-size:11px;font-weight:800;white-space:nowrap}}
        .tt-session-row button:disabled{{opacity:.45}}
         .tt-session-instructions{{margin:6px 0 0;padding:8px 10px;border-left:3px solid #78a984;border-radius:7px;background:#f1f7f1;color:#58705e;font-size:10px;line-height:1.55}}
        .tt-session-step{{padding:5px 8px;border-radius:7px;background:#e8f3e9;color:#376a48;font-size:10px;font-weight:800}}
        @media(max-width:640px){{.tt-session-row-main{{grid-template-columns:28px 1fr 1fr}}.tt-session-row-main small{{grid-column:2/-1}}.tt-session-row-main button{{grid-column:3}}.tt-session-row-sharing{{grid-template-columns:1fr}}}}
        @media(max-width:600px){{.tt-req-overview{{grid-template-columns:repeat(2,minmax(0,1fr));padding:12px}}.tt-req-page-head,.tt-req-workspace{{padding:15px}}.tt-session-filters,.tt-session-linking{{grid-template-columns:1fr}}.tt-req-pagination .tt-btn{{padding:9px}}}}

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
        .tt-allocation-summary small{{display:block;color:#748779;font-size:10px;margin-top:4px}}.tt-allocation-details>td{{padding:0 12px 12px!important;background:#f8fbf8}}.tt-allocation-details details{{padding:8px 0}}.tt-allocation-details summary{{cursor:pointer;color:#37684a;font-size:12px;font-weight:800}}.tt-allocation-details .tt-table{{margin-top:10px}}.tt-allocation-status{{display:inline-block;padding:5px 9px;border-radius:20px;font-size:10px;font-weight:800;white-space:nowrap}}.tt-allocation-status.over{{background:#fff0ed;color:#a33b2d}}.tt-allocation-status.under{{background:#fff7df;color:#8a6416}}.tt-allocation-status.match{{background:#e6f4e9;color:#28653c}}.tt-allocation-status.neutral{{background:#eef1ef;color:#59675e}}
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
        .tt-req-workspace{{min-width:0}}.tt-req-toolbar{{display:flex;align-items:end;gap:9px;flex-wrap:wrap;margin:0 0 10px}}.tt-req-search{{display:flex;flex:1 1 230px;flex-direction:column;gap:5px;font-size:10px;font-weight:800;color:#557061}}.tt-req-search input{{width:100%;padding:10px 12px;border:1px solid #d5e4d7;border-radius:10px;background:#fbfdfb;font-size:12px}}.tt-req-filter{{position:relative;flex:none}}.tt-req-filter>summary{{list-style:none;cursor:pointer;border:1px solid #d5e4d7;border-radius:10px;padding:10px 13px;background:#f3f8f3;color:#326846;font-size:11px;font-weight:850}}.tt-req-filter>summary::-webkit-details-marker{{display:none}}.tt-req-filter>summary span{{margin-left:6px;padding:3px 7px;border-radius:20px;background:#e2efe4}}.tt-req-filter-panel{{position:absolute;z-index:80;right:0;top:calc(100% + 7px);width:min(290px,88vw);display:grid;gap:10px;padding:15px;background:#fff;border:1px solid #dce8de;border-radius:13px;box-shadow:0 15px 35px rgba(25,60,38,.16)}}.tt-req-filter-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;color:#234c37;font-size:12px}}.tt-req-filter-close{{display:grid;place-items:center;width:29px;height:29px;flex:none;border:1px solid #dce8de;border-radius:8px;background:#f3f8f3;color:#416b4d;font-size:20px;line-height:1;cursor:pointer}}.tt-req-filter-close:hover{{background:#e5f1e7;border-color:#bcd7c1}}.tt-req-filter-panel label{{display:grid;gap:5px;font-size:10px;font-weight:800;color:#557061}}.tt-req-filter-panel select{{width:100%;padding:9px;border:1px solid #d5e4d7;border-radius:8px;background:#fbfdfb;color:#234638}}.tt-req-count{{font-size:10px;color:#7a8d80;font-weight:750}}
        .tt-req-add-actions{{display:flex;flex-direction:column;gap:12px;min-width:0}}
        .tt-req-add-actions>.tt-btn{{align-self:flex-start}}
        .tt-req-bulk-details{{font-size:11px;color:#557061}}
        .tt-req-bulk-details>summary{{cursor:pointer;font-weight:750;padding:8px 0}}
        .tt-req-bulk-details[open]{{padding:10px;border:1px solid #e0ebe1;border-radius:12px;background:#fbfdfb}}
        .tt-req-add-modal[hidden]{{display:none!important}}
        .tt-req-add-modal{{position:fixed;inset:0;z-index:10060;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(15,35,27,.58)}}
        .tt-req-add-dialog{{width:min(900px,100%);max-height:min(90vh,820px);overflow:auto;padding:20px;background:#fff;border:1px solid #dce8de;border-radius:18px;box-shadow:0 24px 70px rgba(0,0,0,.24)}}
        .tt-req-add-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:16px}}
        .tt-req-add-head h3{{margin:5px 0;color:#234c37;font-size:18px}}
        .tt-req-add-head p{{margin:4px 0 0;color:#718579;font-size:11px;line-height:1.5}}
        .tt-req-add-close{{width:34px;height:34px;flex:none;border:1px solid #dce8de;border-radius:9px;background:#f5faf5;color:#345b43;font-size:23px;line-height:1;cursor:pointer}}
        .tt-req-add-form{{grid-template-columns:1fr 1fr;gap:10px}}
        .tt-req-add-form label.wide,.tt-req-add-footer{{grid-column:1/-1}}
        .tt-req-add-form small{{display:block;margin-top:5px;color:#7a8d80;font-size:9px;line-height:1.5;font-weight:500}}
        .tt-req-add-footer{{display:flex;justify-content:flex-end;gap:8px;margin-top:4px}}
        @media(max-width:560px){{.tt-req-add-dialog{{padding:15px;border-radius:14px}}.tt-req-add-form{{grid-template-columns:1fr}}.tt-req-add-form label.wide,.tt-req-add-footer{{grid-column:1}}.tt-req-add-footer button{{flex:1}}}}
        .tt-req-table table{{min-width:620px}}.tt-req-table th,.tt-req-table td{{padding:9px 10px}}.tt-req-subline{{display:block;margin-top:3px;color:#85958a;font-size:9px}}.tt-req-table td:last-child details{{margin:0}}.tt-req-table details[open]{{min-width:0}}.tt-req-table details[open] .tt-req-manage{{position:absolute;z-index:90;right:0;top:35px;width:min(310px,85vw);max-height:70vh;overflow:auto;padding:13px;background:#fff;border:1px solid #dce8de;border-radius:12px;box-shadow:0 12px 30px rgba(25,60,38,.18)}}.tt-req-table details[open] .tt-req-manage form{{position:static;z-index:auto;top:auto;right:auto;width:100%;max-height:none;overflow:visible;padding:0;background:transparent;border:0;border-radius:0;box-shadow:none}}.tt-req-manage .tt-form{{grid-template-columns:1fr 1fr;gap:8px}}.tt-req-manage .tt-form button,.tt-req-manage .tt-form label.wide{{grid-column:1/-1}}.tt-req-manage>form+form{{margin-top:9px}}.tt-req-pagination{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 2px}}.tt-req-pagination>div{{display:flex;gap:6px}}.tt-req-pagination .tt-btn{{min-height:33px;padding:7px 10px;font-size:10px}}.tt-req-table tr[hidden]{{display:none!important}}@media(max-width:600px){{.tt-req-toolbar{{align-items:stretch}}.tt-req-filter{{align-self:flex-start}}.tt-req-pagination{{align-items:flex-start;flex-direction:column}}.tt-req-pagination>div{{width:100%}}.tt-req-pagination button{{flex:1}}}}
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
                 .tt-availability-summary{{min-width:0}}.tt-summary-search{{display:flex;flex-direction:column;gap:5px;margin-bottom:9px;color:#526b5d;font-size:11px;font-weight:800}}.tt-summary-search input{{width:100%;padding:9px 11px;border:1px solid #d5e4d7;border-radius:9px;background:#fbfdfb;color:#234638}}.tt-availability-summary .tt-table table{{min-width:430px}}.tt-availability-summary th:not(:first-child),.tt-availability-summary td:not(:first-child){{text-align:center;padding:8px 7px}}.tt-availability-summary th[title]{{cursor:help}}.tt-availability-summary .tt-btn{{min-height:32px;padding:7px 9px;font-size:10px}}.tt-availability-summary tr[hidden]{{display:none}}.tt-availability-actions{{display:flex;align-items:center;justify-content:center;gap:6px;white-space:nowrap}}.tt-availability-actions form{{display:inline-flex;margin:0}}.tt-sub-av-cell{{width:38px;height:34px;border:1px solid #d7e5da;border-radius:8px;background:#fff;color:#234638;font-weight:800;cursor:pointer}}.tt-sub-av-cell[data-status='available']{{background:#dff2e4;border-color:#65a878;color:#176b35}}.tt-sub-av-cell[data-status='unavailable']{{background:#fde7e7;border-color:#d98b8b;color:#a32626}}.tt-subject-availability-editor .tt-availability-grid{{border:1px solid #e1ebe3;border-radius:12px;background:#fff;padding:8px}}.tt-subject-availability-editor .tt-availability-legend{{margin:8px 0 12px}}.tt-subject-availability-modal .tt-modal-dialog{{width:min(900px,calc(100vw - 28px));max-height:90vh;overflow:auto}}.tt-subject-availability-modal .tt-modal-actions{{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}}.tt-subject-restrictions-register{{display:block;min-width:0}}
         .tt-availability-editor{{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,1fr);gap:18px;align-items:start}}.tt-availability-legend{{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:#526b5d}}.tt-availability-legend b{{display:inline-block;padding:3px 8px;border-radius:7px;background:#edf5ee}}.tt-availability-grid{{overflow:auto;max-width:100%}}.tt-availability-grid table{{min-width:650px}}.tt-availability-grid th{{white-space:nowrap}}.tt-availability-grid th small{{display:block;font-weight:500;color:#718579}}.tt-av-cell{{width:38px;height:34px;border:1px solid #d7e5da;border-radius:8px;background:#fff;color:#234638;font-weight:800;cursor:pointer}}.tt-av-cell[data-status='available']{{background:#dff2e4;border-color:#65a878;color:#176b35}}.tt-av-cell[data-status='unavailable']{{background:#fde7e7;border-color:#d98b8b;color:#a32626}}.tt-availability-grid td{{text-align:center;padding:5px}}@media(max-width:850px){{.tt-availability-editor{{grid-template-columns:1fr}}}}
        .tt-modal{{position:fixed;inset:0;z-index:10050;display:none;align-items:center;justify-content:center;padding:18px;background:rgba(20,43,30,.48);backdrop-filter:blur(5px)}}.tt-modal.is-open{{display:flex;animation:ttFade .16s ease-out}}.tt-modal:target{{display:flex;animation:ttFade .16s ease-out}}.tt-profile-create-card>.tt-btn{{margin-top:12px;text-decoration:none!important}}.tt-modal-close{{display:grid;place-items:center;text-decoration:none!important}}
        .tt-modal-dialog{{position:relative;width:min(620px,100%);max-height:min(88vh,850px);overflow:auto;padding:25px;background:linear-gradient(145deg,#fff 0%,#f4faf4 100%);border:1px solid #d5e6d8;border-radius:22px;box-shadow:0 24px 70px rgba(18,52,31,.25);animation:ttPop .18s ease-out}}
        .tt-modal-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:19px}}.tt-modal-head h3{{font-size:20px;margin:4px 0;color:#214a34}}.tt-modal-head p{{font-size:12px;color:#718477;margin:0}}.tt-modal-close{{border:0;width:35px;height:35px;border-radius:11px;background:#eaf4eb;color:#326a43;font-size:21px;cursor:pointer;flex:none}}
        .tt-modal .tt-form{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tt-modal .tt-form label.wide{{grid-column:1/-1}}.tt-modal .tt-form button{{grid-column:1/-1;margin-top:4px}}
        @keyframes ttFade{{from{{opacity:0}}to{{opacity:1}}}}@keyframes ttPop{{from{{opacity:0;transform:translateY(9px) scale(.985)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
        @media(max-width:900px){{.tt-split{{grid-template-columns:1fr}}.tt-add-card .tt-btn{{min-height:48px}}.tt-form{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
        @media(max-width:600px){{.tt-wrap{{padding:12px;border-radius:17px}}.tt-hero{{padding:22px 18px}}.tt-hero h1{{font-size:24px}}.tt-form,.tt-form.compact,.tt-modal .tt-form{{grid-template-columns:1fr}}.tt-form label.wide,.tt-modal .tt-form label.wide{{grid-column:auto}}.tt-stats{{width:100%;justify-content:space-around}}.tt-modal{{padding:10px}}.tt-modal-dialog{{padding:20px 16px;border-radius:18px}}.tt-hero>div:last-child{{width:100%}}.tt-hero>div:last-child a{{flex:1}}}}

         /* Timetable Setup redesign: calm, responsive control-centre layout */
         .tt-wrap{{
           max-width:1540px;margin:0 auto;padding:clamp(12px,2vw,26px);
           color:#203d2d;background:#f3f7f3;border:1px solid #e3ece4;border-radius:22px
         }}
         .tt-hero{{
           align-items:flex-start;min-height:150px;margin:0 0 16px;padding:25px 28px;
           border:1px solid #dce9de;border-left:5px solid #398253;border-radius:17px;
           background:#fff;box-shadow:0 5px 18px rgba(29,65,41,.045)
         }}
         .tt-hero:after{{display:none}}
         .tt-hero .tt-kicker{{display:inline-flex;padding:6px 9px;border-radius:6px;background:#edf6ee;color:#39784d}}
         .tt-hero h1{{font-size:clamp(25px,3vw,32px);letter-spacing:-.8px;margin:10px 0 5px;color:#1e4934}}
         .tt-hero p{{max-width:690px;font-size:13px;line-height:1.65;color:#6b7f70}}
         .tt-hero>div:last-child{{display:flex;gap:8px;flex-wrap:wrap;align-self:center}}
         .tt-hero>div:last-child .tt-btn{{min-height:38px;padding:9px 13px}}
         .tt-select{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 13px;padding:13px 16px;background:#fff;border:1px solid #e0e9e1;border-radius:13px}}
         .tt-select label{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#627968}}
         .tt-select select{{min-width:min(360px,65vw);padding:10px 12px;border:1px solid #d6e4d8;border-radius:9px;background:#fbfdfb;font-size:12px;font-weight:700;color:#244b34}}
         .tt-profile{{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 19px;margin:0 0 15px;border:1px solid #dce9de;border-left:4px solid #398253;border-radius:14px;background:#fff;box-shadow:0 4px 15px rgba(29,65,41,.035)}}
         .tt-profile h2{{font-size:18px;margin:5px 0;color:#204a34}}
         .tt-profile p{{font-size:11px;color:#77877b}}
         .tt-stats{{gap:8px;flex-wrap:wrap}}
         .tt-stats span{{min-width:82px;padding:9px 12px;border:1px solid #e4ece5;border-radius:10px;background:#f8fbf8;font-size:10px}}
         .tt-stats b{{font-size:19px;color:#28734a}}
         .tt-section{{padding:17px 18px;margin:0 0 11px;border:1px solid #e0e9e1;border-radius:14px;background:#fff;box-shadow:0 3px 12px rgba(29,65,41,.025)}}
         .tt-section:hover{{border-color:#c9ddcc}}
         .tt-section.tt-step-open{{border-color:#b8d5bd;box-shadow:0 6px 18px rgba(36,83,52,.06)}}
         .tt-section-title{{align-items:center;margin:0;gap:14px}}
         .tt-section-title>div{{display:grid;grid-template-columns:1fr;gap:3px}}
         .tt-section-title .tt-kicker{{display:inline-flex;width:max-content;max-width:100%;padding:4px 7px;border-radius:5px;background:#f0f6f0;color:#5a8063;font-size:9px}}
         .tt-section h3{{font-size:15px;letter-spacing:-.2px;margin:2px 0;color:#254d35}}
         .tt-section-title p{{font-size:11px;line-height:1.5;color:#78877c;max-width:850px}}
         .tt-section-toggle{{padding:8px 11px;border-radius:8px;background:#f7faf7;font-size:10px}}
         .tt-section-content{{padding-top:17px}}
         .tt-split{{grid-template-columns:minmax(250px,.62fr) minmax(0,1.65fr);gap:14px}}
         .tt-form{{gap:11px}}
         .tt-form label{{font-size:10px;color:#536b59}}
         .tt-form input,.tt-form select{{padding:10px 11px;border-radius:8px;background:#fcfdfc;border-color:#dfe8e0;font-size:12px}}
         .tt-btn{{border-radius:8px;box-shadow:none;font-size:11px}}
         .tt-btn:hover{{box-shadow:0 5px 12px rgba(35,102,62,.12)}}
         .tt-btn.secondary{{background:#f1f6f1;border-color:#dce8dd}}
         .tt-table{{border-color:#e3ebe4;border-radius:10px}}
         .tt-table th{{background:#f2f7f2;color:#496b51;font-size:9px;text-transform:uppercase;letter-spacing:.035em}}
         .tt-table th,.tt-table td{{padding:10px 11px;font-size:10px}}
         .tt-table tr:hover td{{background:#fbfdfb}}
         .tt-table details summary{{border-radius:7px;font-size:10px}}
         .tt-alert{{border:1px solid transparent;border-radius:9px}}
         .tt-alert.success{{border-color:#d4e8d7}}
         .tt-alert.error{{border-color:#f1d4d1}}
         .tt-empty{{background:#fff;border:1px dashed #cbdccd;box-shadow:none}}
         .tt-empty b{{color:#285239}}
         .tt-availability-editor{{gap:14px}}
         .tt-availability-legend{{font-size:10px}}
         .tt-availability-grid .tt-av-cell{{border-radius:6px}}
         .tt-req-toolbar{{gap:8px}}
         .tt-req-search input{{border-radius:8px}}
         @media(max-width:900px){{.tt-split{{grid-template-columns:1fr}}.tt-hero{{align-items:flex-start}}.tt-hero>div:last-child{{align-self:flex-start}}}}
         @media(max-width:600px){{
           .tt-wrap{{padding:9px;border-radius:14px}}
           .tt-hero{{min-height:0;padding:19px 16px;border-radius:12px;gap:14px}}
           .tt-hero h1{{font-size:24px}}
           .tt-hero>div:last-child{{width:100%}}
           .tt-hero>div:last-child a{{flex:1}}
           .tt-select{{align-items:stretch;flex-direction:column;padding:12px}}
           .tt-select select{{width:100%;min-width:0}}
           .tt-profile{{align-items:flex-start;flex-direction:column;padding:14px}}
           .tt-stats{{width:100%;justify-content:flex-start}}
           .tt-stats span{{flex:1;min-width:0}}
           .tt-section{{padding:14px 12px;border-radius:11px}}
           .tt-section-title{{align-items:flex-start}}
           .tt-section-title p{{font-size:10px}}
           .tt-section-toggle{{padding:7px 8px;white-space:nowrap}}
           .tt-section-content{{padding-top:13px}}
         }}
        </style>
        <div class='tt-wrap'>{notice}{selector}{profile_summary}{read_only_html}{create_profile_html}{sections}</div>
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
          root.querySelectorAll('[data-availability-tab]').forEach(tab=>{{
            tab.addEventListener('click',()=>{{
              const target=tab.dataset.availabilityTab;
              root.querySelectorAll('[data-availability-tab]').forEach(item=>item.setAttribute('aria-selected',item===tab?'true':'false'));
              root.querySelectorAll('[data-availability-panel]').forEach(panel=>{{panel.hidden=panel.dataset.availabilityPanel!==target;}});
            }});
          }});
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
              root.querySelectorAll('[data-requirement-group]').forEach(group=>{{group.hidden=!group.querySelector('[data-requirement-row]:not([hidden])');}});
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
            if(button.dataset.kind==='subject'){{
              const modal=root.querySelector('#tt-subject-availability-modal');
              if(modal){{modal.classList.add('is-open');document.body.classList.add('tt-modal-scroll-locked');}}
            }}else{{
              const section=button.closest('.tt-section');
              const modalOpener=section?.querySelector('.tt-add-card button');
              if(modalOpener) modalOpener.click();
            }}
            picker.value=button.dataset.id;
            picker.dispatchEvent(new Event('change',{{bubbles:true}}));
            picker.focus({{preventScroll:true}});
          }}));
          const subjectAvailabilityModal=root.querySelector('#tt-subject-availability-modal');
          if(subjectAvailabilityModal){{
            const closeSubjectAvailability=()=>{{subjectAvailabilityModal.classList.remove('is-open');releaseTimetableScrollLock();}};
            subjectAvailabilityModal.querySelectorAll('[data-subject-av-close]').forEach(button=>button.addEventListener('click',closeSubjectAvailability));
            subjectAvailabilityModal.addEventListener('click',event=>{{if(event.target===subjectAvailabilityModal)closeSubjectAvailability();}});
            subjectAvailabilityModal.addEventListener('keydown',event=>{{if(event.key==='Escape')closeSubjectAvailability();}});
          }}
          // Keep one document-level handler so it survives replacing .tt-wrap.
          // Identify supported actions by endpoint, not button text or submitter support.
          if(!document.documentElement.dataset.ttSetupAjaxBound){{
            document.documentElement.dataset.ttSetupAjaxBound='1';
            document.addEventListener('submit',async event=>{{
              const form=event.target;
              if(!form||!form.matches||!form.matches('form[method="post" i]')) return;
              const action=new URL(form.getAttribute('action')||window.location.href,window.location.origin);
              const endpoint=action.pathname;
              const isRequirementSave=endpoint==='/app/timetable/setup/requirement';
              const isRequirementDelete=endpoint==='/app/timetable/setup/row-delete'&&form.querySelector('input[name="kind"]')?.value==='requirement';
              // Requirement saves must perform a real document navigation. The
              // setup AJAX replacement only swaps .tt-wrap, while the two-tab
              // Teaching Requirements navigation lives outside that element;
              // using AJAX therefore leaves the old full-setup tab state in place.
              // A normal POST follows the server's tab=requirements redirect and
              // rebuilds the complete two-tab workspace with the correct state.
              if(isRequirementSave||isRequirementDelete) return;
              const isSetupWrite=endpoint.startsWith('/app/timetable/setup/')&&new Set(['day','period','break','calendar-event','room','availability','availability-matrix','subject-availability-matrix','requirement','bulk','class-limits','row-delete','break-gap']).has(endpoint.split('/').pop());
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
                // Scripts returned by fetch + DOMParser are inert. Re-run every
                // setup initializer after replacing the workspace, including the
                // subject-requirements controls, so the saved page remains usable.
                Array.from(nextRoot.querySelectorAll('script')).forEach(script=>{{
                  if(!script.textContent.trim()) return;
                  const fresh=document.createElement('script');
                  fresh.textContent=script.textContent;
                  document.body.appendChild(fresh);
                  fresh.remove();
                }});
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
          // Keep the Teaching Requirements add/manage dialogs responsive even
          // when the two-tab workspace is restored or its inline initializer runs
          // before the section is fully attached to the document.
          if(!document.documentElement.dataset.ttRequirementDialogsBound){{
            document.documentElement.dataset.ttRequirementDialogsBound='1';
            document.addEventListener('click',event=>{{
              const addButton=event.target.closest('[data-req-add-open]');
              if(addButton){{
                const modal=document.getElementById('tt-req-add-modal');
                if(modal&&modal.hidden){{modal.hidden=false;document.body.classList.add('tt-modal-scroll-locked');}}
                return;
              }}
              const manageButton=event.target.closest('[data-req-manage-open]');
              if(manageButton){{
                const modal=document.getElementById(manageButton.dataset.reqManageOpen);
                if(modal&&!modal.classList.contains('is-open')){{modal.classList.add('is-open');document.body.classList.add('tt-modal-scroll-locked');modal.querySelector('input,select,button')?.focus();}}
                return;
              }}
              const closeButton=event.target.closest('[data-req-manage-close],[data-req-add-close]');
              if(closeButton){{
                const manage=closeButton.closest('.tt-req-manage-modal');
                if(manage)manage.classList.remove('is-open');
                const add=document.getElementById('tt-req-add-modal');
                if(add&&(closeButton.closest('#tt-req-add-modal')||closeButton.dataset.reqAddClose!==undefined))add.hidden=true;
                if(!document.querySelector('.tt-req-manage-modal.is-open')&&(!add||add.hidden))document.body.classList.remove('tt-modal-scroll-locked');
                return;
              }}
              if(event.target.classList?.contains('tt-req-manage-modal')){{
                event.target.classList.remove('is-open');
                if(!document.querySelector('.tt-req-manage-modal.is-open'))document.body.classList.remove('tt-modal-scroll-locked');
              }}
              const addModal=document.getElementById('tt-req-add-modal');
              if(addModal&&event.target===addModal){{addModal.hidden=true;document.body.classList.remove('tt-modal-scroll-locked');}}
            }});
            document.addEventListener('keydown',event=>{{
              if(event.key!=='Escape')return;
              document.querySelectorAll('.tt-req-manage-modal.is-open').forEach(modal=>modal.classList.remove('is-open'));
              const add=document.getElementById('tt-req-add-modal');
              if(add)add.hidden=true;
              if(!document.querySelector('.tt-req-manage-modal.is-open'))document.body.classList.remove('tt-modal-scroll-locked');
            }});
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
            "SELECT * FROM ds_timetable_profiles WHERE school_id=? AND status IN ('draft','pending_approval','published') ORDER BY academic_year DESC,term,id DESC",
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
        esc = lambda v, quote=False: escape(str(v if v is not None else ""), quote=quote)
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
        def target_text(r):
            parts = [label + ": " + str(r[key]) for key,label in (("subject_name","Subject"),("teacher_name","Teacher"),("class_name","Class"),("room_name","Room")) if r[key]]
            return " · ".join(parts) or "All matching sessions"
        rule_rows = "".join(
            f"<tr data-rule data-search='{esc(str(r['name'])+' '+str(r['reason'] or '')+' '+target_text(r)).lower()}' data-type='{esc(r['constraint_type'])}' data-status='{'active' if int(r['is_active'] or 0) else 'inactive'}'>"
            f"<td><b>{esc(r['name'])}</b><small>{esc(r['reason'] or 'No additional instruction')}</small></td>"
            f"<td><span class='tt-rule-kind {esc(r['constraint_type'])}'>{esc(str(r['constraint_type']).title())}</span><small>{esc(str(r['applies_to']).title())} · {esc(str(r['schedule_layer']).replace('_',' ').title())}</small></td>"
            f"<td>{esc(target_text(r))}</td><td>{esc(r['day_name'] or 'Any day')} · {esc(r['period_label'] or 'Any period')}<small>{esc(r['start_time'] or 'Any start')} – {esc(r['end_time'] or 'Any end')}</small></td>"
            f"<td>{'Active' if int(r['is_active'] or 0) else 'Inactive'}</td>"
            f"<td><button type='button' class='tt-rule-edit' data-id='{int(r['id'])}' data-name='{esc(r['name'], quote=True)}' data-type='{esc(r['constraint_type'])}' data-applies='{esc(r['applies_to'])}' data-layer='{esc(r['schedule_layer'])}' data-subject='{esc(r['subject_id'] or '')}' data-teacher='{esc(r['teacher_id'] or '')}' data-class='{esc(r['class_id'] or '')}' data-room='{esc(r['room_id'] or '')}' data-day='{esc(r['day_id'] or '')}' data-period='{esc(r['period_id'] or '')}' data-start='{esc(r['start_time'] or '')}' data-end='{esc(r['end_time'] or '')}' data-from='{esc(r['effective_from'] or '')}' data-until='{esc(r['effective_to'] or '')}' data-reason='{esc(r['reason'] or '', quote=True)}'>Edit</button>"
            f"<form method='post' action='/app/timetable/constraints/delete' class='tt-inline-delete' onsubmit='return confirm(&quot;Delete this rule?&quot;)'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='constraint_id' value='{int(r['id'])}'><button type='submit' class='tt-rule-delete'>Delete</button></form></td></tr>"
            for r in rules
        ) or "<tr><td colspan='6' class='tt-empty'>No constraints configured yet. Add a rule to guide timetable placement.</td></tr>"
        active_count = sum(1 for r in rules if int(r["is_active"] or 0))
        prohibit_count = sum(1 for r in rules if r["constraint_type"] == "prohibit")
        prefer_count = sum(1 for r in rules if r["constraint_type"] == "prefer")
        notice = f"<div class='tt-notice {'error' if error else ''}'>{esc(message)}</div>" if message else ""
        body = f"""
        <style>
        .tt-constraints{{max-width:1450px;margin:auto;color:#244b38}}.tt-constraints *{{box-sizing:border-box}}
        .tt-constraints .hero{{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap;padding:25px 27px;border:1px solid #d5e6d8;border-radius:22px;background:linear-gradient(120deg,#e3f1e5,#f8fbf8);box-shadow:0 12px 30px #285a3c0c}}
        .tt-constraints .eyebrow{{font-size:10px;font-weight:900;letter-spacing:.14em;color:#398052}}.tt-constraints h2{{font-size:clamp(22px,3vw,30px);margin:6px 0;color:#1f4a34}}
        .tt-constraints .hero p{{margin:0;max-width:680px;color:#6a8071;font-size:13px;line-height:1.6}}
        .tt-constraints button{{border:0;border-radius:10px;padding:10px 14px;font-size:12px;font-weight:800;cursor:pointer}}
        .tt-constraints .primary{{background:#246b43;color:#fff}}.tt-constraints .secondary{{background:#edf5ee;color:#286442;border:1px solid #dceade}}
        .tt-constraints .stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:15px 0}}
        .tt-constraints .stat{{padding:15px 17px;background:#fff;border:1px solid #e0ebe2;border-radius:15px}}.tt-constraints .stat b{{display:block;font-size:23px;color:#245a3a}}.tt-constraints .stat span{{display:block;margin-top:5px;font-size:10px;font-weight:800;text-transform:uppercase;color:#809184}}
        .tt-constraints .panel{{margin-top:15px;padding:18px;background:#fff;border:1px solid #dfeae1;border-radius:19px;box-shadow:0 8px 25px #244d3508}}
        .tt-constraints .panel-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:13px}}.tt-constraints h3{{margin:0;font-size:16px;color:#24553a}}
        .tt-constraints .toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}.tt-constraints input,.tt-constraints select{{width:100%;padding:11px 12px;border:1px solid #d9e6dc;border-radius:10px;background:#fbfdfb;color:#244338;font-size:12px}}
        .tt-constraints .search{{min-width:230px;flex:1}}.tt-constraints label{{display:block;margin:0 0 6px;font-size:11px;font-weight:800;color:#526e5b}}
        .tt-constraints .table-wrap{{overflow:auto;border:1px solid #e7eee8;border-radius:13px}}.tt-constraints table{{width:100%;min-width:850px;border-collapse:collapse;font-size:12px}}
        .tt-constraints th{{padding:12px;background:#f5f9f5;color:#6b8070;text-align:left;font-size:10px;text-transform:uppercase;white-space:nowrap}}
        .tt-constraints td{{padding:13px;border-top:1px solid #edf2ed;vertical-align:middle;color:#405d49}}.tt-constraints td small{{display:block;margin-top:4px;color:#829187;font-size:10px}}
        .tt-constraints .tt-rule-kind{{display:inline-flex;padding:5px 8px;border-radius:20px;font-size:10px;font-weight:900}}.tt-constraints .prohibit{{background:#fff0ed;color:#a94b39}}.tt-constraints .require{{background:#eaf3ff;color:#35649b}}.tt-constraints .prefer{{background:#fff6df;color:#946c20}}
        .tt-constraints .tt-rule-edit{{background:#edf5ee;color:#286442;padding:8px 11px}}.tt-constraints .tt-rule-delete{{background:#fff0ee;color:#a44c40;padding:8px 11px}}.tt-constraints .tt-inline-delete{{display:inline;margin-left:5px}}
        .tt-constraints .notice{{margin:12px 0;padding:12px 14px;border-radius:11px;background:#eaf5ec;color:#286342;font-size:12px;font-weight:700}}.tt-constraints .notice.error{{background:#fff0ed;color:#a3473b}}
        .tt-constraints .empty{{padding:25px;text-align:center;color:#829187}}.tt-constraints tr[hidden]{{display:none}}
        .tt-constraints .modal{{position:fixed;inset:0;z-index:9999;display:none;align-items:center;justify-content:center;padding:16px;background:#14291dbb;backdrop-filter:blur(5px)}}.tt-constraints .modal.open{{display:flex}}
        .tt-constraints .modal-card{{width:min(850px,100%);max-height:90vh;overflow:auto;background:#fff;border:1px solid #dce9df;border-radius:20px;box-shadow:0 24px 80px #0e241866}}
        .tt-constraints .modal-head{{position:sticky;top:0;z-index:2;display:flex;align-items:center;justify-content:space-between;padding:16px 19px;background:#f7fbf7;border-bottom:1px solid #e5eee6}}
        .tt-constraints .modal-head h3{{margin:0}}.tt-constraints .close{{width:34px;height:34px;padding:0;background:#eaf3eb;color:#315f41;font-size:22px}}
        .tt-constraints .form-body{{padding:19px}}.tt-constraints .form-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}
        .tt-constraints .wide{{grid-column:1/-1}}.tt-constraints .form-foot{{display:flex;justify-content:flex-end;gap:9px;padding-top:15px;margin-top:15px;border-top:1px solid #edf2ed}}
        .tt-constraints .filter-card{{width:min(440px,100%)}}.tt-constraints .filter-body{{padding:19px;display:grid;gap:14px}}
        @media(max-width:700px){{.tt-constraints .stats{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tt-constraints .hero{{padding:19px}}}}
        @media(max-width:520px){{.tt-constraints .form-grid{{grid-template-columns:1fr}}.tt-constraints .wide{{grid-column:auto}}.tt-constraints .panel{{padding:12px}}.tt-constraints .hero .primary{{width:100%}}}}
        </style>
        <div class='tt-constraints'>
          <section class='hero'><div><span class='eyebrow'>SMART TIMETABLE · RULE ENGINE</span><h2>Scheduling constraints</h2><p>Set the boundaries and preferences that guide automatic generation and keep manual timetable changes within your school's rules.</p></div><button type='button' class='primary' id='tt-rule-add'>＋ Add constraint</button></section>
          {notice}
          <section class='stats'><div class='stat'><b>{len(rules)}</b><span>Total rules</span></div><div class='stat'><b>{active_count}</b><span>Active rules</span></div><div class='stat'><b>{prohibit_count}</b><span>Prohibited windows</span></div><div class='stat'><b>{prefer_count}</b><span>Preferred windows</span></div></section>
          <section class='panel'><div class='panel-head'><div><h3>Configured rules</h3><small style='color:#809184'>Manage rules for this timetable profile.</small></div><div class='toolbar'><input class='search' id='tt-rule-search' type='search' placeholder='Search rules, targets or notes…'><button type='button' class='secondary' id='tt-rule-filter-open'>Filters</button><button type='button' class='secondary' id='tt-rule-clear'>Clear</button></div></div>
          <div class='table-wrap'><table><thead><tr><th>Rule</th><th>Behavior / scope</th><th>Applies to</th><th>Day / time</th><th>Status</th><th>Actions</th></tr></thead><tbody>{rule_rows}</tbody></table></div><div id='tt-rule-empty' class='empty' hidden>No rules match the current search or filters.</div></section>
          <div class='modal' id='tt-rule-editor' aria-hidden='true'><div class='modal-card' role='dialog' aria-modal='true'><div class='modal-head'><h3 id='tt-rule-editor-title'>Add scheduling constraint</h3><button type='button' class='close' data-close='tt-rule-editor'>×</button></div>
          <form method='post' action='/app/timetable/constraints' id='tt-rule-form'><div class='form-body'><input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='constraint_id' id='tt-rule-id'>
          <div class='form-grid'><div class='wide'><label>Constraint name</label><input name='name' id='tt-rule-name' required maxlength='120' placeholder='e.g. No Mathematics after lunch'></div>
          <div><label>Rule behavior</label><select name='constraint_type' id='tt-rule-type'><option value='prohibit'>Prohibit this time</option><option value='require'>Require this time</option><option value='prefer'>Prefer this time</option></select></div>
          <div><label>Applies to</label><select name='applies_to' id='tt-rule-applies'><option value='all'>All sessions</option><option value='lesson'>Ordinary lessons</option><option value='remedial'>Remedial lessons</option><option value='activity'>Activities</option></select></div>
          <div><label>Timetable layer</label><select name='schedule_layer' id='tt-rule-layer'><option value='all'>All layers</option><option value='instructional'>Instructional</option><option value='additional_learning'>Additional learning</option><option value='school_activity'>School activities</option></select></div>
          <div><label>Subject</label><select name='subject_id' id='tt-rule-subject'>{subject_opts}</select></div><div><label>Teacher</label><select name='teacher_id' id='tt-rule-teacher'>{teacher_opts}</select></div>
          <div><label>Class / stream</label><select name='class_id' id='tt-rule-class'>{class_opts}</select></div><div><label>Room / facility</label><select name='room_id' id='tt-rule-room'>{room_opts}</select></div>
          <div><label>Day</label><select name='day_id' id='tt-rule-day'>{day_opts}</select></div><div><label>Period</label><select name='period_id' id='tt-rule-period'>{period_opts}</select></div>
          <div><label>Not before</label><input type='time' name='start_time' id='tt-rule-start'></div><div><label>Not after</label><input type='time' name='end_time' id='tt-rule-end'></div>
          <div><label>Effective from</label><input type='date' name='effective_from' id='tt-rule-from'></div><div><label>Effective until</label><input type='date' name='effective_to' id='tt-rule-until'></div>
          <div class='wide'><label>Reason / instruction</label><input name='reason' id='tt-rule-reason' maxlength='500' placeholder='Explain why this rule is needed'></div></div>
          <div class='form-foot'><button type='button' class='secondary' data-close='tt-rule-editor'>Cancel</button><button type='submit' class='primary'>Save constraint</button></div></div></form></div></div>
          <div class='modal' id='tt-rule-filter' aria-hidden='true'><div class='modal-card filter-card' role='dialog' aria-modal='true'><div class='modal-head'><h3>Filter constraints</h3><button type='button' class='close' data-close='tt-rule-filter'>×</button></div><div class='filter-body'><div><label>Behavior</label><select id='tt-rule-type-filter'><option value=''>All behaviors</option><option value='prohibit'>Prohibit</option><option value='require'>Require</option><option value='prefer'>Prefer</option></select></div><div><label>Status</label><select id='tt-rule-status-filter'><option value=''>All statuses</option><option value='active'>Active</option><option value='inactive'>Inactive</option></select></div><div class='form-foot'><button type='button' class='secondary' id='tt-rule-reset'>Reset</button><button type='button' class='primary' data-close='tt-rule-filter'>Apply</button></div></div></div></div>
        </div>
        <script>
        (function(){{
          const root=document.querySelector('.tt-constraints');if(!root||root.dataset.bound==='1')return;root.dataset.bound='1';
          const editor=root.querySelector('#tt-rule-editor'),filter=root.querySelector('#tt-rule-filter'),form=root.querySelector('#tt-rule-form');
          const ids={{id:'tt-rule-id',name:'tt-rule-name',constraint_type:'tt-rule-type',applies_to:'tt-rule-applies',schedule_layer:'tt-rule-layer',subject_id:'tt-rule-subject',teacher_id:'tt-rule-teacher',class_id:'tt-rule-class',room_id:'tt-rule-room',day_id:'tt-rule-day',period_id:'tt-rule-period',start_time:'tt-rule-start',end_time:'tt-rule-end',effective_from:'tt-rule-from',effective_to:'tt-rule-until',reason:'tt-rule-reason'}};
          const dataKeys={{id:'id',name:'name',constraint_type:'type',applies_to:'applies',schedule_layer:'layer',subject_id:'subject',teacher_id:'teacher',class_id:'class',room_id:'room',day_id:'day',period_id:'period',start_time:'start',end_time:'end',effective_from:'from',effective_to:'until',reason:'reason'}};
          const show=m=>{{m.classList.add('open');m.setAttribute('aria-hidden','false');document.body.style.overflow='hidden';}};
          const hide=m=>{{m.classList.remove('open');m.setAttribute('aria-hidden','true');document.body.style.removeProperty('overflow');}};
          const reset=()=>{{form.reset();root.querySelector('#tt-rule-id').value='';root.querySelector('#tt-rule-editor-title').textContent='Add scheduling constraint';}};
          root.querySelector('#tt-rule-add').addEventListener('click',()=>{{reset();show(editor);root.querySelector('#tt-rule-name').focus();}});
          root.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>hide(root.querySelector('#'+b.dataset.close))));
          [editor,filter].forEach(m=>m.addEventListener('click',e=>{{if(e.target===m)hide(m);}}));
          document.addEventListener('keydown',e=>{{if(e.key==='Escape'){{hide(editor);hide(filter);}}}});
          root.querySelectorAll('.tt-rule-edit').forEach(b=>b.addEventListener('click',()=>{{reset();Object.entries(ids).forEach(([key,id])=>{{root.querySelector('#'+id).value=b.dataset[dataKeys[key]]||'';}});root.querySelector('#tt-rule-editor-title').textContent='Edit scheduling constraint';show(editor);}}));
          const rows=[...root.querySelectorAll('[data-rule]')],search=root.querySelector('#tt-rule-search'),type=root.querySelector('#tt-rule-type-filter'),status=root.querySelector('#tt-rule-status-filter');
          function apply(){{const q=search.value.trim().toLowerCase();let n=0;rows.forEach(r=>{{const ok=(!q||r.dataset.search.includes(q))&&(!type.value||r.dataset.type===type.value)&&(!status.value||r.dataset.status===status.value);r.hidden=!ok;if(ok)n++;}});root.querySelector('#tt-rule-empty').hidden=n>0;}}
          search.addEventListener('input',apply);type.addEventListener('change',apply);status.addEventListener('change',apply);
          root.querySelector('#tt-rule-filter-open').addEventListener('click',()=>show(filter));
          root.querySelector('#tt-rule-clear').addEventListener('click',()=>{{search.value='';type.value='';status.value='';apply();}});
          root.querySelector('#tt-rule-reset').addEventListener('click',()=>{{type.value='';status.value='';apply();}});
          apply();
        }})();
        </script>
        """
        return module_page(request, "Timetable Constraints", "timetable", body)

    @app.post("/app/timetable/constraints/delete")
    def delete_timetable_constraint(request: Request, profile_id: int = Form(...), constraint_id: int = Form(...)):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            _profile(con.cursor(), int(school["id"]), profile_id)
            result = con.execute(
                "DELETE FROM ds_timetable_constraints WHERE id=? AND school_id=? AND profile_id=?",
                (constraint_id, int(school["id"]), profile_id),
            )
            if result.rowcount != 1:
                raise TimetableSetupError("That constraint was not found in this timetable profile.")
            con.commit()
            return RedirectResponse(f"/app/timetable/constraints?profile_id={profile_id}&message=Constraint%20deleted", 303)
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return RedirectResponse(f"/app/timetable/constraints?profile_id={profile_id}&error=1&message={quote(str(exc))}", 303)
        finally:
            con.close()

    @app.post("/app/timetable/constraints")
    def create_timetable_constraint(request: Request, profile_id: int = Form(...),
        name: str = Form(...), constraint_type: str = Form("prohibit"),
        applies_to: str = Form("all"), schedule_layer: str = Form("all"),
        subject_id: str = Form(""), teacher_id: str = Form(""), class_id: str = Form(""),
        room_id: str = Form(""), day_id: str = Form(""), period_id: str = Form(""),
        start_time: str = Form(""), end_time: str = Form(""), effective_from: str = Form(""),
        effective_to: str = Form(""), reason: str = Form(""), constraint_id: str = Form("")):
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
                int(constraint_id) if constraint_id else None,
            )
            return RedirectResponse(f"/app/timetable/constraints?profile_id={profile_id}&message=Constraint%20saved", 303)
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return RedirectResponse(f"/app/timetable/constraints?profile_id={profile_id}&error=1&message={quote(str(exc))}", 303)
        except Exception:
            con.rollback()
            logger.exception("Failed to save timetable constraint for profile %s", profile_id)
            message = "The constraint could not be saved because of a server or database error. Please review the rule and try again."
            return RedirectResponse(f"/app/timetable/constraints?profile_id={profile_id}&error=1&message={quote(message)}", 303)
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
            # Subject availability is a set of per-cell rows. Its register-level
            # Delete action removes all exceptions for one subject in this profile.
            if kind == "subject_availability_subject":
                subject = cur.execute(
                    "SELECT id FROM subjects WHERE id=? AND school_id=?",
                    (int(row_id), school_id),
                ).fetchone()
                if not subject:
                    raise TimetableSetupError("That subject was not found in this school.")
                cur.execute(
                    "DELETE FROM ds_timetable_subject_availability WHERE school_id=? AND profile_id=? AND subject_id=?",
                    (school_id, int(profile_id), int(row_id)),
                )
                con.commit()
                return redirect_setup(profile_id, "Subject availability settings deleted.", request=request, tab="availability")
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
            if kind == "requirement":
                return redirect_setup(profile_id, "Subject requirement deleted.", request=request, tab="requirements", section="subject")
            return redirect_setup(profile_id, "Setup row deleted.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            if kind == "requirement":
                return redirect_setup(profile_id, str(exc), True, request=request, tab="requirements", section="subject")
            return redirect_setup(profile_id, str(exc), True)
        finally:
            con.close()

    # Compatibility endpoint: older cached setup pages submitted to the page URL.
    # Keep this alias so profile creation cannot fail with 405 on stale markup.
    @app.post("/app/timetable/setup")
    @app.post("/app/timetable/setup/profile")
    def create_timetable_profile(request: Request, name: str = Form(...), academic_year: str = Form(...), term: str = Form(...), academic_start_date: str = Form(""), academic_end_date: str = Form(""), profile_type: str = Form("main")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            pid = create_profile(con, int(school["id"]), name, academic_year, term, request.session.get("email", ""), academic_start_date, academic_end_date, profile_type)
            return redirect_setup(pid, "Timetable profile created. Configure the school days and periods next.")
        except TimetableSetupError as exc:
            return redirect_setup(message=str(exc), error=True)
        finally:
            con.close()

    @app.post("/app/timetable/setup/profile/update")
    def update_timetable_profile(request: Request, profile_id: int = Form(...), name: str = Form(...), academic_year: str = Form(...), term: str = Form(...), academic_start_date: str = Form(""), academic_end_date: str = Form(""), profile_type: str = Form("main"), ds_tab: str = Form("")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            update_profile(con, int(school["id"]), profile_id, name, academic_year, term, academic_start_date, academic_end_date, profile_type)
            tab_id = str(request.scope.get("davischool_tab_id") or ds_tab or "")
            tab_query = "&ds_tab=" + quote(tab_id, safe="") if tab_id else ""
            return RedirectResponse(f"/app/timetable?profile_id={profile_id}&message=Timetable%20profile%20updated{tab_query}", 303)
        except TimetableSetupError as exc:
            tab_id = str(request.scope.get("davischool_tab_id") or ds_tab or "")
            tab_query = "&ds_tab=" + quote(tab_id, safe="") if tab_id else ""
            return RedirectResponse(f"/app/timetable?profile_id={profile_id}&error=1&message={quote(str(exc))}{tab_query}", 303)
        finally:
            con.close()

    @app.post("/app/timetable/setup/standard-week")
    def create_standard_week(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            profile = con.execute("SELECT profile_type FROM ds_timetable_profiles WHERE id=? AND school_id=?", (profile_id, int(school["id"]))).fetchone()
            profile_type = str(profile["profile_type"] or "main").lower() if profile else "main"
            standard_days = (("SAT","Saturday"),("SUN","Sunday")) if profile_type == "weekend" else (("MON","Monday"),("TUE","Tuesday"),("WED","Wednesday"),("THU","Thursday"),("FRI","Friday"))
            for order, (code, name) in enumerate(standard_days, 1):
                save_day(con, int(school["id"]), profile_id, code, name, order, True)
            return redirect_setup(profile_id, "Standard " + ("Saturday–Sunday weekend" if profile_type == "weekend" else "Monday–Friday") + " timetable days saved.")
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
    def create_timetable_period(request: Request, profile_id: int = Form(...), period_no: int = Form(...), label: str = Form(...), start_time: str = Form(...), end_time: str = Form(...), period_type: str = Form("lesson"), period_id: int | None = Form(None)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_period(con, int(school["id"]), profile_id, period_no, label, start_time, end_time, period_type, period_id=period_id)
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
    def create_timetable_room(request: Request, room_code: str = Form(...), name: str = Form(...), room_type: str = Form("classroom"), capacity: str = Form(""), description: str = Form(""), equipment: str = Form(""), suitable_for: str = Form(""), allocation_mode: str = Form("shared"), assigned_class_id: str = Form(""), profile_id: int = Form(0)):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            save_room(con, int(school["id"]), room_code, name, room_type, int(capacity) if capacity.strip() else None, description, equipment, suitable_for, allocation_mode, int(assigned_class_id) if assigned_class_id.strip() else None)
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
            return redirect_setup(profile_id, "Subject availability matrix saved.", request=request, tab="availability")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_setup(profile_id, str(exc), True, request=request, tab="availability")
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
                request=request, tab="requirements", section="subject",
            )
        except (TimetableSetupError, ValueError) as exc:
            return redirect_setup(profile_id, str(exc), True, request=request, tab="requirements", section="subject")
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

    @app.post("/app/timetable/setup/teacher-color")
    def save_timetable_teacher_color(
        request: Request,
        profile_id: int = Form(0),
        teacher_id: int = Form(...),
        teacher_color: str = Form(...),
        teacher_initials: str = Form(...),
    ):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        color = teacher_color.strip().upper()
        initials = teacher_initials.strip().upper()
        if not re.fullmatch(r"[A-Z]{1,4}", initials):
            return redirect_setup(profile_id, "Enter 1–4 letters for teacher initials.", True)
        if len(color) != 7 or not color.startswith("#") or not all(ch in "0123456789ABCDEF" for ch in color[1:]):
            return redirect_setup(profile_id, "Choose a valid teacher colour.", True)
        con = get_db()
        try:
            result = con.execute(
                "UPDATE teachers SET teacher_color=?,teacher_initials=? WHERE id=? AND school_id=?",
                (color, initials, teacher_id, int(school["id"])),
            )
            if result.rowcount != 1:
                raise TimetableSetupError("The selected teacher could not be found.")
            con.commit()
            return redirect_setup(profile_id, "Teacher timetable colour saved.")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_setup(profile_id, str(exc), True)
        finally:
            con.close()

    @app.post("/app/timetable/setup/requirement")
    def create_timetable_requirement(request: Request, profile_id: int = Form(...), allocation: str = Form(""), class_id: int = Form(0), teacher_id: int = Form(0), subject_id: int = Form(0), lessons_per_week: int = Form(...), duration_periods: int = Form(1), max_lessons_per_day: str = Form(""), allow_double: str = Form(""), weekly_pattern: str = Form(""), weekly_links: str = Form(""), pattern_mode: str = Form("replace")):
        school = school_for(request)
        if not school: return RedirectResponse("/", 303)
        con = get_db()
        try:
            if allocation.strip():
                parts = allocation.split("|")
                if len(parts) != 3:
                    raise TimetableSetupError("Select a valid teacher allocation.")
                class_id, subject_id, teacher_id = (int(part) for part in parts)
            else:
                class_id, teacher_id, subject_id = int(class_id or 0), int(teacher_id or 0), int(subject_id or 0)
            valid_allocation = con.execute(
                """SELECT 1 FROM teacher_allocations
                   WHERE school_id=? AND class_id=? AND teacher_id=? AND subject_id=? LIMIT 1""",
                (int(school["id"]), class_id, teacher_id, subject_id),
            ).fetchone()
            if not valid_allocation:
                raise TimetableSetupError("That teacher is not allocated to the selected subject in this class. Choose a valid class, teacher and subject combination.")
            save_class_requirement(con, int(school["id"]), profile_id, class_id, subject_id, teacher_id, lessons_per_week, 1, int(max_lessons_per_day) if max_lessons_per_day.strip() else None, False, commit=False)
            requirement = con.execute(
                """SELECT id FROM ds_timetable_class_requirements
                   WHERE school_id=? AND profile_id=? AND class_id=? AND subject_id=? AND teacher_id=?""",
                (int(school["id"]), profile_id, class_id, subject_id, teacher_id),
            ).fetchone()
            if weekly_pattern.strip().lower() == "auto":
                con.execute(
                    "DELETE FROM ds_timetable_requirement_patterns WHERE school_id=? AND profile_id=? AND requirement_id=?",
                    (int(school["id"]), profile_id, int(requirement["id"])),
                )
                con.commit()
            elif weekly_pattern.strip():
                sessions = []
                try:
                    session_links = json.loads(weekly_links or "[]")
                except (TypeError, ValueError):
                    raise TimetableSetupError("Session links are invalid.")
                if not isinstance(session_links, list):
                    raise TimetableSetupError("Session links must be a list.")
                for session_index, item in enumerate(weekly_pattern.split(",")):
                    token = item.strip()
                    if not token:
                        continue
                    if "@" in token:
                        duration_text, period_text = token.split("@", 1)
                        duration, period_no = int(duration_text.strip()), int(period_text.strip())
                        period = con.execute(
                            "SELECT id FROM ds_timetable_periods WHERE school_id=? AND profile_id=? AND period_no=? AND period_type='lesson'",
                            (int(school["id"]), profile_id, period_no),
                        ).fetchone()
                        if not period:
                            raise TimetableSetupError("A preferred start period does not exist or is not a teaching period.")
                        preferred_period_id = int(period["id"])
                    else:
                        duration, preferred_period_id = int(token), None
                    links = session_links[session_index] if session_index < len(session_links) and isinstance(session_links[session_index], dict) else {}
                    sessions.append({"duration_periods": duration, "preferred_period_id": preferred_period_id,
                                      "linked_class_ids": links.get("classes", []), "co_teacher_ids": links.get("teachers", [])})
                if pattern_mode == "append":
                    existing = con.execute(
                        """SELECT duration_periods,preferred_period_id,linked_class_ids_json,co_teacher_ids_json FROM ds_timetable_requirement_patterns
                           WHERE school_id=? AND profile_id=? AND requirement_id=? ORDER BY session_no""",
                        (int(school["id"]), profile_id, int(requirement["id"])),
                    ).fetchall()
                    sessions = [
                        {"duration_periods": int(row["duration_periods"]), "preferred_period_id": row["preferred_period_id"],
                         "linked_class_ids": json.loads(row["linked_class_ids_json"] or "[]"),
                         "co_teacher_ids": json.loads(row["co_teacher_ids_json"] or "[]")}
                        for row in existing
                    ] + sessions
                used_periods = sum(int(item["duration_periods"]) for item in sessions)
                if used_periods > int(lessons_per_week):
                    raise TimetableSetupError(
                        f"These sessions use {used_periods} periods, exceeding the weekly target of {int(lessons_per_week)}. "
                        f"{max(0, int(lessons_per_week) - sum(int(row['duration_periods']) for row in existing) if pattern_mode == 'append' else int(lessons_per_week))} periods were available before this save."
                    )
                save_requirement_session_pattern(con, int(school["id"]), profile_id, int(requirement["id"]), sessions)
            else:
                con.commit()
            return redirect_setup(profile_id, "Weekly lesson requirement and lesson pattern saved.", request=request, tab="requirements", section="subject")
        except (TimetableSetupError, ValueError) as exc:
            con.rollback()
            return redirect_setup(profile_id, str(exc), True, request=request, tab="requirements", section="subject")
        finally: con.close()
