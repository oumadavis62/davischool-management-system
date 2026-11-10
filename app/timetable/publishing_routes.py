"""Publishing, approval and timetable version management workspace."""
from __future__ import annotations

from html import escape
import logging
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.setup import TimetableSetupError
from app.timetable.publishing import (
    validate_timetable_for_publication,
    submit_for_approval,
    publish_timetable,
    create_revision,
    list_profile_versions,
    compare_timetable_versions,
)


def register_timetable_publishing_routes(app, get_db, get_school_obj, module_page):
    from app.timetable.navigation import timetable_workspace
    _base_module_page = module_page
    def module_page(request, title, module, body):
        return _base_module_page(request, title, module, timetable_workspace(request, body))
    def school_for(request):
        if not request.session.get("email") or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
            return None
        return get_school_obj(request)

    def redirect_publishing(profile_id=0, message="", error=False, run_profile_id=0):
        parts = []
        if profile_id:
            parts.append("profile_id=" + str(int(profile_id)))
        if run_profile_id:
            parts.append("compare_profile_id=" + str(int(run_profile_id)))
        if message:
            parts.append("message=" + quote(str(message)))
        if error:
            parts.append("error=1")
        return RedirectResponse("/app/timetable/publishing" + (("?" + "&".join(parts)) if parts else ""), 303)

    @app.get("/app/timetable/publishing", response_class=HTMLResponse)
    def timetable_publishing_page(
        request: Request,
        profile_id: int = 0,
        compare_first: int = 0,
        compare_second: int = 0,
        message: str = "",
        error: int = 0,
    ):
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
        readiness = None
        versions = []
        comparison = None
        compare_error = ""
        if selected:
            pid = int(selected["id"])
            if selected["status"] in ("draft","pending_approval"):
                readiness = validate_timetable_for_publication(con,school_id,pid)
            versions = list_profile_versions(con,school_id,pid)
            if compare_first and compare_second:
                try:
                    comparison = compare_timetable_versions(con,school_id,compare_first,compare_second)
                except TimetableSetupError as exc:
                    compare_error = str(exc)
        con.close()

        esc = lambda value: escape(str(value if value is not None else ""))
        pid = int(selected["id"]) if selected else 0
        notice = f"<div class='pub-alert {'error' if error else 'success'}'>{esc(message)}</div>" if message else ""
        profile_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==pid else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])} · {esc(str(p['profile_type'] or 'main').replace('_',' ').title())} ({esc(p['status'])})</option>"
            for p in profiles
        )
        if not selected:
            body = "<div class='pub-empty'><h2>No timetable profile found</h2><p>Create and configure a timetable profile first.</p><a class='pub-btn' href='/app/timetable/setup'>Open Timetable Setup</a></div>"
            return module_page(request,"Publishing & Versions","timetable",body)

        status = str(selected["status"] or "draft")
        errors = readiness["errors"] if readiness else []
        error_list = "".join("<li>"+esc(item)+"</li>" for item in errors)
        error_html = ("<ul class='pub-errors'>" + error_list + "</ul>") if errors else "<p class='pub-ok'>All weekly requirements and scheduling constraints are satisfied.</p>"
        readiness_html = (
            f"""<section class='pub-card'><div class='pub-card-head'><div><span class='pub-kicker'>PUBLISHING READINESS</span><h3>{'Ready to submit' if readiness['ready'] else 'Action required before publishing'}</h3></div><span class='pub-state {'good' if readiness['ready'] else 'bad'}'>{'READY' if readiness['ready'] else 'NOT READY'}</span></div><div class='pub-metrics'><span><b>{int(readiness['scheduled_periods'])}</b>Scheduled periods</span><span><b>{int(readiness['required_periods'])}</b>Required periods</span><span><b>{int(readiness['requirements'])}</b>Lesson requirements</span></div>{error_html}</section>"""
            if readiness else ""
        )
        action_html = ""
        action_submit_html = ""
        if status == "draft":
            action_html = "<button type='button' class='pub-btn' data-open='pub-action-dialog'>Confirm and Submit for approval</button>"
            action_submit_html = f"""<form id='pub-submit-form' method='post' action='/app/timetable/publishing/submit'><input type='hidden' name='profile_id' value='{pid}'><button type='submit' class='pub-btn'>Confirm and Submit for approval</button></form>"""
        elif status == "pending_approval":
            action_html = "<button type='button' class='pub-btn' data-open='pub-action-dialog' " + ("disabled" if not readiness or not readiness["ready"] else "") + ">Approve & Publish</button>"
            action_submit_html = f"""<form method='post' action='/app/timetable/publishing/publish'><input type='hidden' name='profile_id' value='{pid}'><button class='pub-btn' {'disabled' if not readiness or not readiness['ready'] else ''}>Confirm & Publish</button></form>"""
        elif status in ("published","archived"):
            action_html = "<button type='button' class='pub-btn' data-open='pub-action-dialog'>Create editable revision</button>"
            action_submit_html = f"""<form method='post' action='/app/timetable/publishing/revision'><input type='hidden' name='profile_id' value='{pid}'><button class='pub-btn'>Create revision</button></form>"""
        version_rows = "".join(
            f"<tr><td>{esc(v['label'])}</td><td>{esc(v['profile_name'])}</td><td>R{int(v['revision_no'] or 1)}</td><td>{esc(v['created_at'])}</td><td>{esc(v['created_by'])}</td></tr>"
            for v in versions
        ) or "<tr><td colspan='5' class='pub-muted'>No published versions yet.</td></tr>"
        version_options = "".join(
            f"<option value='{int(v['id'])}'>{esc(v['label'])} · {esc(v['profile_name'])} · {esc(v['created_at'])}</option>"
            for v in versions
        )
        compare_html = ""
        if len(versions) >= 2:
            compare_error_html = f"<div class='pub-alert error'>{esc(compare_error)}</div>" if compare_error else ""
            comparison_html = (
                f"<div class='pub-compare-result'><b>{len(comparison['added']) + len(comparison.get('advanced_added', []))} sessions added</b><b>{len(comparison['removed']) + len(comparison.get('advanced_removed', []))} sessions removed</b><b>{comparison['unchanged'] + comparison.get('advanced_unchanged', 0)} unchanged</b></div>"
                if comparison else ""
            )
            compare_html = f"""<section class='pub-card'><span class='pub-kicker'>VERSION COMPARISON</span><h3>Compare published versions</h3><form method='get' action='/app/timetable/publishing' class='pub-compare'><input type='hidden' name='profile_id' value='{pid}'><label>First version<select name='compare_first'>{version_options}</select></label><label>Second version<select name='compare_second'>{version_options}</select></label><button class='pub-btn secondary'>Compare</button></form>{compare_error_html}{comparison_html}</section>"""
        profile_modal = f"""
        <dialog class='pub-dialog' id='pub-profile-dialog'><div class='pub-dialog-head'><div><span class='pub-kicker'>TIMETABLE WORKSPACE</span><h3>Select timetable profile</h3></div><button type='button' class='pub-close' data-close='pub-profile-dialog' aria-label='Close'>×</button></div>
        <form method='get' action='/app/timetable/publishing' class='pub-form'><label>Academic year, term and profile<select name='profile_id'>{profile_options}</select></label><button class='pub-btn'>Open profile</button></form></dialog>
        """
        compare_modal = f"""
        <dialog class='pub-dialog' id='pub-compare-dialog'><div class='pub-dialog-head'><div><span class='pub-kicker'>VERSION REVIEW</span><h3>Compare published versions</h3></div><button type='button' class='pub-close' data-close='pub-compare-dialog' aria-label='Close'>×</button></div>
        <form method='get' action='/app/timetable/publishing' class='pub-form pub-compare'><input type='hidden' name='profile_id' value='{pid}'><label>First version<select name='compare_first'>{version_options}</select></label><label>Second version<select name='compare_second'>{version_options}</select></label><button class='pub-btn'>Compare versions</button></form>{compare_error_html if len(versions)>=2 else ''}{comparison_html if len(versions)>=2 else ''}
        </dialog>
        """
        action_modal = f"""
        <dialog class='pub-dialog' id='pub-action-dialog'><div class='pub-dialog-head'><div><span class='pub-kicker'>WORKFLOW ACTION</span><h3>{'Confirm and Submit for approval' if status=='draft' else 'Approve and Publish' if status=='pending_approval' else 'Create a new revision' if status in ('published','archived') else 'No action available'}</h3></div><button type='button' class='pub-close' data-close='pub-action-dialog' aria-label='Close'>×</button></div>
        <p class='pub-dialog-copy'>{'Confirm to submit this timetable for approval. The draft will be locked against further editing until a new revision is created.' if status=='draft' else 'Publishing makes this revision the official timetable and archives the previously published revision for the same academic year and term.' if status=='pending_approval' else 'A new editable draft will be copied from this version. The published snapshot remains unchanged.' if status in ('published','archived') else 'Choose a timetable profile to continue.'}</p>
        {("<ul class='pub-errors'>" + error_list + "</ul>") if status == "draft" and errors else ""}
        <div class='pub-actions'><button type='button' class='pub-btn secondary' data-close='pub-action-dialog'>Cancel</button>{action_submit_html or "<span class='pub-muted'>This profile has no available workflow action.</span>"}</div>
        </dialog>
        <script>
        (function(){{
          const openers=document.querySelectorAll('[data-open]');
          openers.forEach(button=>button.addEventListener('click',()=>document.getElementById(button.dataset.open)?.showModal()));
          document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>document.getElementById(button.dataset.close)?.close()));
          document.querySelectorAll('.pub-dialog').forEach(dialog=>dialog.addEventListener('click',event=>{{if(event.target===dialog)dialog.close();}}));
          if(new URLSearchParams(window.location.search).has('compare_first'))document.getElementById('pub-compare-dialog')?.showModal();
        }})();
        </script>
        """
        body = f"""
        <style>
        .pub-wrap{{max-width:1160px;margin:auto;padding:18px;color:#173d2b}}.pub-hero{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin:0 0 16px}}.pub-hero h2{{font-size:24px;margin:3px 0 5px}}.pub-hero p{{font-size:12px;color:#64748b;margin:0}}.pub-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}.pub-actions{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}.pub-actions form{{margin:0}}.pub-btn{{display:inline-flex;align-items:center;justify-content:center;padding:10px 14px;border:0;border-radius:9px;background:#17633b;color:white;text-decoration:none;font-size:12px;font-weight:800;cursor:pointer}}.pub-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8}}.pub-btn:disabled{{opacity:.45;cursor:not-allowed}}.pub-card{{background:white;border:1px solid #e1ebe3;border-radius:15px;padding:17px;margin-bottom:15px;box-shadow:0 3px 12px #173d2b08}}.pub-card h3{{font-size:17px;margin:4px 0 8px}}.pub-card-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}.pub-state{{font-size:10px;font-weight:900;padding:6px 10px;border-radius:20px;background:#edf2ee;color:#47634e}}.pub-state.good{{background:#eaf5ec;color:#17633b}}.pub-state.bad{{background:#fff1f0;color:#a12828}}.pub-profile-line{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:12px}}.pub-profile-line span{{font-size:11px;color:#647b69}}.pub-metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}}.pub-metrics span{{background:#f4f8f4;padding:12px;border-radius:9px;color:#64748b;font-size:10px}}.pub-metrics b{{display:block;font-size:22px;color:#173d2b}}.pub-errors{{margin:10px 0;padding:12px 14px 12px 32px;background:#fff5f4;color:#9f2929;border-radius:9px;font-size:11px;line-height:1.8}}.pub-ok{{font-size:12px;color:#17633b;background:#f1f8f2;padding:12px;border-radius:9px}}.pub-alert{{padding:11px 14px;border-radius:9px;margin-bottom:12px;font-size:12px;font-weight:700}}.pub-alert.success{{background:#eaf5ec;color:#17633b}}.pub-alert.error{{background:#fff1f0;color:#a12828}}.pub-table-scroll{{overflow:auto}}.pub-card table{{width:100%;border-collapse:collapse;min-width:580px}}.pub-card th,.pub-card td{{padding:11px;border-bottom:1px solid #edf2ed;text-align:left;font-size:11px}}.pub-card th{{background:#f0f6f1;color:#315b3e}}.pub-muted{{text-align:center;color:#94a3a0;padding:18px;font-size:11px}}.pub-dialog{{width:min(560px,calc(100% - 28px));max-height:85vh;overflow:auto;border:1px solid #dce9df;border-radius:17px;padding:19px;background:#fff;color:#173d2b;box-shadow:0 20px 70px #102c1b40}}.pub-dialog::backdrop{{background:#102c1b70;backdrop-filter:blur(2px)}}.pub-dialog-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:15px}}.pub-dialog h3{{font-size:18px;margin:4px 0}}.pub-close{{border:0;background:#eff5f0;color:#315b3e;border-radius:9px;width:34px;height:34px;font-size:22px;cursor:pointer}}.pub-form{{display:grid;gap:13px}}.pub-form label{{display:grid;gap:6px;font-size:11px;font-weight:800;color:#385b43}}.pub-form select{{width:100%;min-width:0;padding:11px;border:1px solid #dce7de;border-radius:9px;background:#fff;color:#173d2b}}.pub-dialog-copy{{font-size:12px;line-height:1.6;color:#647b69;margin:0 0 16px}}.pub-compare-result{{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}}.pub-compare-result b{{background:#f1f7f2;padding:10px 12px;border-radius:8px;font-size:11px}}.pub-empty{{padding:30px;text-align:center;background:white;border-radius:14px}}@media(max-width:650px){{.pub-wrap{{padding:12px}}.pub-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.pub-hero h2{{font-size:22px}}.pub-dialog{{padding:15px}}}}
        </style>
        <div class='pub-wrap'>
          <div class='pub-hero'><div><span class='pub-kicker'>DAVISCHOOL · TIMETABLE CONTROL</span><h2>Review & Publish</h2><p>Check timetable quality, approve the final schedule and maintain its version history.</p></div><div class='pub-actions'><button type='button' class='pub-btn secondary' data-open='pub-profile-dialog'>Select profile</button>{action_html or "<span class='pub-muted'>No workflow action is available for this profile.</span>"}</div></div>
          {notice}
          <section class='pub-card'><div class='pub-card-head'><div><span class='pub-kicker'>ACTIVE WORKSPACE</span><h3>{esc(selected['name'])}</h3><p>{esc(selected['academic_year'])} · {esc(selected['term'])} · {esc(str(selected['profile_type'] or 'main').replace('_',' ').title())} · Revision {int(selected['revision_no'] or 1)}</p></div><span class='pub-state {'good' if status=='published' else 'bad' if status=='pending_approval' else ''}'>{esc(status.replace('_',' ').upper())}</span></div><div class='pub-profile-line'><span>Current profile selected</span><button type='button' class='pub-btn secondary' data-open='pub-compare-dialog' {'disabled' if len(versions)<2 else ''}>Compare versions</button></div></section>
          {readiness_html}
          <section class='pub-card'><div class='pub-card-head'><div><span class='pub-kicker'>VERSION CONTROL</span><h3>Published timetable history</h3></div><span class='pub-state'>{len(versions)} saved version{'s' if len(versions)!=1 else ''}</span></div><div class='pub-table-scroll'><table><tr><th>Version</th><th>Profile</th><th>Revision</th><th>Published at</th><th>Published by</th></tr>{version_rows}</table></div></section>
        </div>{profile_modal}{compare_modal}{action_modal}
        """
        return module_page(request,"Publishing & Versions","timetable",body)

    @app.post("/app/timetable/publishing/submit")
    def timetable_submit_for_approval(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/",303)
        con = get_db()
        try:
            submit_for_approval(con,int(school["id"]),profile_id,request.session.get("email",""))
            return redirect_publishing(profile_id,"Timetable submitted for approval. Editing is now locked.")
        except TimetableSetupError as exc:
            try:
                con.rollback()
            except Exception:
                pass
            return redirect_publishing(profile_id,str(exc),True)
        except Exception:
            try:
                con.rollback()
            except Exception:
                pass
            logging.exception("Timetable submission for approval failed (profile_id=%s, school_id=%s)", profile_id, int(school["id"]))
            return redirect_publishing(
                profile_id,
                "Submission failed while saving the approval request. The error has been recorded; please try again or contact support.",
                True,
            )
        finally:
            con.close()

    # Compatibility endpoint for clients that post either workflow action to
    # the workspace URL. Resolve the action from the persisted profile state:
    # drafts are submitted for approval; pending profiles are approved and published.
    # This prevents a stale/wrapped form from re-submitting an already-pending draft.
    @app.post("/app/timetable/publishing")
    def timetable_publishing_submit_compat(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        con = get_db()
        try:
            profile = con.execute(
                "SELECT status FROM ds_timetable_profiles WHERE id=? AND school_id=?",
                (profile_id, int(school["id"])),
            ).fetchone()
            status = str(profile["status"] or "draft").strip().lower() if profile else ""
        finally:
            con.close()
        if status == "pending_approval":
            return timetable_approve_and_publish(request, profile_id)
        return timetable_submit_for_approval(request, profile_id)

    @app.post("/app/timetable/publishing/publish")
    def timetable_approve_and_publish(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/",303)
        con = get_db()
        try:
            result = publish_timetable(con,int(school["id"]),profile_id,request.session.get("email",""))
            return redirect_publishing(profile_id,"Timetable published successfully as version " + str(result["version_no"]) + ".")
        except TimetableSetupError as exc:
            return redirect_publishing(profile_id,str(exc),True)
        finally:
            con.close()

    @app.post("/app/timetable/publishing/revision")
    def timetable_create_revision(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/",303)
        con = get_db()
        try:
            revision_id = create_revision(con,int(school["id"]),profile_id,request.session.get("email",""))
            return RedirectResponse("/app/timetable/builder?profile_id="+str(revision_id),303)
        except TimetableSetupError as exc:
            return redirect_publishing(profile_id,str(exc),True)
        finally:
            con.close()
