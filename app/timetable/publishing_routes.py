"""Publishing, approval and timetable version management workspace."""
from __future__ import annotations

from html import escape
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
        return RedirectResponse("/school/timetable/publishing" + (("?" + "&".join(parts)) if parts else ""), 303)

    @app.get("/school/timetable/publishing", response_class=HTMLResponse)
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
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==pid else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])} ({esc(p['status'])})</option>"
            for p in profiles
        )
        selector = f"<form method='get' action='/school/timetable/publishing' class='pub-select'><label>Timetable profile</label><select name='profile_id' onchange='this.form.submit()'>{profile_options}</select></form>" if profiles else ""
        if not selected:
            body = "<div class='pub-empty'><h2>No timetable profile found</h2><p>Create and configure a timetable profile first.</p><a class='pub-btn' href='/school/timetable/setup'>Open Timetable Setup</a></div>"
            return module_page(request,"Publishing & Versions","timetable",body)

        status = str(selected["status"] or "draft")
        errors = readiness["errors"] if readiness else []
        error_list = "".join("<li>"+esc(item)+"</li>" for item in errors)
        error_html = ("<ul class='pub-errors'>" + error_list + "</ul>") if errors else "<p class='pub-ok'>All weekly requirements and scheduling constraints are satisfied.</p>"
        readiness_html = (
            f"""<section class='pub-card'><div class='pub-card-head'><div><span class='pub-kicker'>PUBLISHING READINESS</span><h3>{'Ready to submit' if readiness['ready'] else 'Action required before publishing'}</h3></div><span class='pub-state {'good' if readiness['ready'] else 'bad'}'>{'READY' if readiness['ready'] else 'NOT READY'}</span></div><div class='pub-metrics'><span><b>{int(readiness['scheduled_lessons'])}</b>Scheduled lessons</span><span><b>{int(readiness['required_lessons'])}</b>Required lessons</span><span><b>{int(readiness['requirements'])}</b>Lesson requirements</span></div>{error_html}</section>"""
            if readiness else ""
        )
        action_html = ""
        if status == "draft":
            action_html = (
                f"<form method='post' action='/school/timetable/publishing/submit' onsubmit='return confirm("Submit this timetable for approval? Editing will be locked until a revision is created.")'><input type='hidden' name='profile_id' value='{pid}'><button class='pub-btn' {'disabled' if not readiness or not readiness['ready'] else ''}>Submit for approval</button></form>"
            )
        elif status == "pending_approval":
            action_html = (
                f"<form method='post' action='/school/timetable/publishing/publish' onsubmit='return confirm("Approve and publish this timetable? The previously published revision will be archived.")'><input type='hidden' name='profile_id' value='{pid}'><button class='pub-btn' {'disabled' if not readiness or not readiness['ready'] else ''}>Approve & Publish</button></form>"
            )
        elif status in ("published","archived"):
            action_html = (
                f"<form method='post' action='/school/timetable/publishing/revision' onsubmit='return confirm("Create an editable draft revision from this published timetable?")'><input type='hidden' name='profile_id' value='{pid}'><button class='pub-btn'>＋ Create new revision</button></form>"
            )
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
                f"<div class='pub-compare-result'><b>{len(comparison['added'])} lessons added</b><b>{len(comparison['removed'])} lessons removed</b><b>{comparison['unchanged']} unchanged</b></div>"
                if comparison else ""
            )
            compare_html = f"""<section class='pub-card'><span class='pub-kicker'>VERSION COMPARISON</span><h3>Compare published versions</h3><form method='get' action='/school/timetable/publishing' class='pub-compare'><input type='hidden' name='profile_id' value='{pid}'><label>First version<select name='compare_first'>{version_options}</select></label><label>Second version<select name='compare_second'>{version_options}</select></label><button class='pub-btn secondary'>Compare</button></form>{compare_error_html}{comparison_html}</section>"""
        body = f"""
        <style>
        .pub-wrap{{max-width:1250px;margin:auto;padding:20px;color:#173d2b}}.pub-hero{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}}.pub-hero h2{{font-size:25px;margin:3px 0 5px}}.pub-hero p{{font-size:12px;color:#64748b;margin:0}}.pub-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}.pub-actions{{display:flex;gap:8px;flex-wrap:wrap}}.pub-btn{{display:inline-flex;align-items:center;justify-content:center;padding:10px 14px;border:0;border-radius:9px;background:#17633b;color:white;text-decoration:none;font-size:12px;font-weight:800;cursor:pointer}}.pub-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8}}.pub-btn:disabled{{opacity:.45;cursor:not-allowed}}.pub-select{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}}.pub-select label{{font-size:12px;font-weight:800}}.pub-select select,.pub-compare select{{padding:10px;border:1px solid #dce7de;border-radius:9px;background:white;min-width:260px}}.pub-card{{background:white;border:1px solid #e1ebe3;border-radius:15px;padding:17px;margin-bottom:15px;box-shadow:0 3px 12px #173d2b08}}.pub-card h3{{font-size:17px;margin:4px 0 12px}}.pub-card-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}.pub-state{{font-size:10px;font-weight:900;padding:6px 10px;border-radius:20px}}.pub-state.good{{background:#eaf5ec;color:#17633b}}.pub-state.bad{{background:#fff1f0;color:#a12828}}.pub-metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}}.pub-metrics span{{background:#f4f8f4;padding:12px;border-radius:9px;color:#64748b;font-size:10px}}.pub-metrics b{{display:block;font-size:22px;color:#173d2b}}.pub-errors{{margin:10px 0;padding:12px 14px 12px 32px;background:#fff5f4;color:#9f2929;border-radius:9px;font-size:11px;line-height:1.8}}.pub-ok{{font-size:12px;color:#17633b}}.pub-alert{{padding:11px 14px;border-radius:9px;margin-bottom:12px;font-size:12px;font-weight:700}}.pub-alert.success{{background:#eaf5ec;color:#17633b}}.pub-alert.error{{background:#fff1f0;color:#a12828}}.pub-compare{{display:flex;align-items:end;gap:10px;flex-wrap:wrap}}.pub-compare label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800}}.pub-compare-result{{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}}.pub-compare-result b{{background:#f4f8f4;padding:10px 12px;border-radius:8px;font-size:11px}}.pub-table-scroll{{overflow:auto}}.pub-card table{{width:100%;border-collapse:collapse;min-width:580px}}.pub-card th,.pub-card td{{padding:11px;border-bottom:1px solid #edf2ed;text-align:left;font-size:11px}}.pub-card th{{background:#f0f6f1;color:#315b3e}}.pub-muted{{text-align:center;color:#94a3a0;padding:18px}}.pub-empty{{padding:30px;text-align:center;background:white;border-radius:14px}}@media(max-width:650px){{.pub-wrap{{padding:12px}}.pub-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.pub-hero h2{{font-size:22px}}}}
        </style>
        <div class='pub-wrap'><div class='pub-hero'><div><span class='pub-kicker'>DAVISCHOOL · APPROVAL & VERSION CONTROL</span><h2>Publishing & Versions</h2><p>Validate, approve, publish and preserve immutable timetable revisions.</p></div><div class='pub-actions'><a class='pub-btn secondary' href='/school/timetable/builder?profile_id={pid}'>Master Builder</a><a class='pub-btn secondary' href='/school/timetable/views?profile_id={pid}'>Timetable Views</a><a class='pub-btn secondary' href='/school/timetable/export/pdf?profile_id={pid}'>Export PDF</a><a class='pub-btn secondary' href='/school/timetable/export/xlsx?profile_id={pid}'>Export Excel</a></div></div>{notice}{selector}
        <section class='pub-card'><div class='pub-card-head'><div><span class='pub-kicker'>SELECTED PROFILE</span><h3>{esc(selected['name'])}</h3><p>{esc(selected['academic_year'])} · {esc(selected['term'])} · Revision {int(selected['revision_no'] or 1)}</p></div><span class='pub-state {'good' if status=='published' else 'bad' if status=='pending_approval' else ''}'>{esc(status.replace('_',' ').upper())}</span></div><div class='pub-actions'>{action_html}</div></section>{readiness_html}{compare_html}
        <section class='pub-card'><span class='pub-kicker'>IMMUTABLE HISTORY</span><h3>Published timetable versions</h3><div class='pub-table-scroll'><table><tr><th>Version</th><th>Profile</th><th>Revision</th><th>Published at</th><th>Published by</th></tr>{version_rows}</table></div></section></div>
        """
        return module_page(request,"Publishing & Versions","timetable",body)

    @app.post("/school/timetable/publishing/submit")
    def timetable_submit_for_approval(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/",303)
        con = get_db()
        try:
            submit_for_approval(con,int(school["id"]),profile_id,request.session.get("email",""))
            return redirect_publishing(profile_id,"Timetable submitted for approval. Editing is now locked.")
        except TimetableSetupError as exc:
            return redirect_publishing(profile_id,str(exc),True)
        finally:
            con.close()

    @app.post("/school/timetable/publishing/publish")
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

    @app.post("/school/timetable/publishing/revision")
    def timetable_create_revision(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school: return RedirectResponse("/",303)
        con = get_db()
        try:
            revision_id = create_revision(con,int(school["id"]),profile_id,request.session.get("email",""))
            return RedirectResponse("/school/timetable/builder?profile_id="+str(revision_id),303)
        except TimetableSetupError as exc:
            return redirect_publishing(profile_id,str(exc),True)
        finally:
            con.close()
