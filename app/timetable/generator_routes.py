"""Automatic timetable generator workspace."""
from __future__ import annotations

from html import escape
import json
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

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
    def timetable_automatic_page(request: Request, profile_id: int = 0, run_id: int = 0, job_id: int = 0, message: str = "", error: int = 0):
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
        # Capture the tab identity for the generator's fetch-based actions.
        # These actions bypass HTML form submission events, so the global
        # submit listener cannot append ds_tab for them.
        tab_id = str(request.scope.get("davischool_tab_id") or "").strip()
        if not (16 <= len(tab_id) <= 64 and all(ch.isalnum() or ch in "_-" for ch in tab_id)):
            tab_id = ""

        job_progress_html = ""
        if job_id:
            job_progress_html = f"<section class='ag-result' id='tt-job-progress'><span class='ag-kicker'>BACKGROUND GENERATION · JOB #{int(job_id)}</span><h3 id='tt-job-title'>Checking generation status…</h3><p id='tt-job-message'>The timetable is being generated in the background. You can safely leave this page.</p><div id='tt-job-stage' class='ag-state'>QUEUED</div></section>"
        generator_script = """<script>
        const ttTabSessionId = TT_TAB_SESSION_ID || new URL(window.location.href).searchParams.get('ds_tab') || '';
        function ttBindTabSession(form) {
            // This inline submit hook runs synchronously, even if the deferred
            // global tab-session controller has not loaded yet. Without it a
            // fast click on a freshly opened page can POST before ds_tab is
            // attached, selecting the empty legacy session cookie.
            let id = '';
            try { id = sessionStorage.getItem('davischool_tab_id') || ''; } catch (_) {}
            if (!/^[A-Za-z0-9_-]{16,64}$/.test(id)) id = TT_TAB_SESSION_ID || '';
            if (!/^[A-Za-z0-9_-]{16,64}$/.test(id)) {
                id = (window.crypto && crypto.randomUUID)
                    ? crypto.randomUUID().replace(/-/g, '')
                    : Date.now().toString(36) + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
                try { sessionStorage.setItem('davischool_tab_id', id); } catch (_) {}
            }
            const field = form.querySelector('input[name="ds_tab"]') || document.createElement('input');
            field.type = 'hidden';
            field.name = 'ds_tab';
            field.value = id;
            if (!field.parentNode) form.appendChild(field);
            const actionUrl = new URL(form.action, window.location.origin);
            actionUrl.searchParams.set('ds_tab', id);
            form.action = actionUrl.pathname + actionUrl.search + actionUrl.hash;
            return true;
        }
        async function ttRunGenerator(button, action, profileId, mode) {
            if (button.dataset.busy === '1') return;
            const payload = new URLSearchParams({profile_id: String(profileId)});
            const target = new URL(action, window.location.origin);
            if (ttTabSessionId) {
                target.searchParams.set('ds_tab', ttTabSessionId);
                payload.set('ds_tab', ttTabSessionId);
            }
            if (mode === 'dated') {
                const start = document.getElementById('tt-start-date');
                const end = document.getElementById('tt-end-date');
                if (!start || !end || !start.value || !end.value) {
                    alert('Choose both the start and end dates before generating.');
                    return;
                }
                if (end.value < start.value) {
                    alert('The end date must be on or after the start date.');
                    return;
                }
                const span = (Date.parse(end.value + 'T00:00:00Z') - Date.parse(start.value + 'T00:00:00Z')) / 86400000;
                if (span > 365) {
                    alert('Generate no more than 366 calendar days at a time.');
                    return;
                }
                payload.set('start_date', start.value);
                payload.set('end_date', end.value);
            }
            const prompts = {
                complete: 'Generate a complete timetable using the current setup? Existing manual lessons will be preserved.',
                advanced: 'Generate normalized sessions, including combined classes and teaching teams?',
                dated: 'Generate dated sessions for every active requirement in this date range?'
            };
            if (!confirm(prompts[mode] || 'Start timetable generation?')) return;
            const original = button.textContent;
            button.dataset.busy = '1';
            button.disabled = true;
            button.textContent = 'Generating timetable…';
            try {
                const response = await fetch(target.toString(), {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
                    body: payload.toString(),
                    redirect: 'follow'
                });
                if (!response.ok) {
                    const detail = (await response.text()).slice(0, 500);
                    throw new Error('Server returned HTTP ' + response.status + (detail ? ': ' + detail : ''));
                }
                if (response.redirected && response.url) window.location.assign(response.url);
                else window.location.reload();
            } catch (error) {
                button.disabled = false;
                button.dataset.busy = '';
                button.textContent = original;
                alert('Timetable generation request failed: ' + (error && error.message ? error.message : error));
            }
        }
        </script>"""
        generator_script = generator_script.replace("TT_TAB_SESSION_ID", json.dumps(tab_id))
        if job_id:
            generator_script += f"""<script>
            (function () {{
                const jobId = {int(job_id)};
                const title = document.getElementById('tt-job-title');
                const message = document.getElementById('tt-job-message');
                const stage = document.getElementById('tt-job-stage');
                let attempts = 0;
                async function refreshJob() {{
                    try {{
                        const response = await fetch('/app/timetable/generation-jobs/' + jobId, {{credentials:'same-origin', cache:'no-store'}});
                        if (!response.ok) throw new Error('Could not read job status');
                        const job = await response.json();
                        title.textContent = job.status === 'completed' ? 'Timetable generated' : job.status === 'failed' ? 'Generation needs attention' : 'Generating timetable…';
                        message.textContent = job.message || 'The solver is working. You can safely leave this page.';
                        stage.textContent = String(job.stage || job.status || 'queued').toUpperCase();
                        stage.className = 'ag-state ' + (job.status === 'completed' ? 'good' : job.status === 'failed' ? 'bad' : '');
                        if (job.status === 'completed' && job.result_run_id) {{
                            window.location.replace('/app/timetable/automatic?profile_id={pid}&run_id=' + encodeURIComponent(job.result_run_id));
                            return;
                        }}
                        if (job.status === 'completed' || job.status === 'failed') return;
                    }} catch (err) {{
                        message.textContent = 'Status temporarily unavailable. The background job remains queued or running; refreshing this page is safe.';
                    }}
                    attempts += 1;
                    if (attempts < 1200) window.setTimeout(refreshJob, 3000);
                }}
                refreshJob();
            }})();
            </script>"""
        read_only = str(selected['status']) != 'draft'
        advanced_action = (
            f"""<button type='button' class='ag-btn secondary' onclick="ttRunGenerator(this,'/app/timetable/automatic/generate-advanced',{pid},'advanced')">Generate weekly instructional sessions ({int(advanced_instructional_requirements)})</button>"""
            if advanced_instructional_requirements and not read_only else ""
        )
        date_range_action = (
            f"""<div class='ag-date-form'>
                <label>From <input id='tt-start-date' type='date' required value='{esc(selected['academic_start_date'] or '')}'
                    min='{esc(selected['academic_start_date'] or '')}' max='{esc(selected['academic_end_date'] or '')}'></label>
                <label>To <input id='tt-end-date' type='date' required value='{esc(selected['academic_end_date'] or selected['academic_start_date'] or '')}'
                    min='{esc(selected['academic_start_date'] or '')}' max='{esc(selected['academic_end_date'] or '')}'></label>
                <button type='button' class='ag-btn' onclick="ttRunGenerator(this,'/app/timetable/automatic/generate-dated',{pid},'dated')">Generate dated timetable</button>
                <p>Uses each actual date's day template, remedial/activity slots, rotation week, teacher availability and shared resource-conflict checks. Maximum range: 366 days.</p>
                </div>"""
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
        # Bind the generation form to the already-authenticated browser tab on
        # the server. Do not rely on the deferred tab-session JavaScript to add
        # ds_tab at submit time: mobile browsers can submit before that handler
        # has run, which selects the legacy/empty session and redirects to "/".
        generate_action = "/app/timetable/automatic/generate"
        if tab_id:
            generate_action += "?ds_tab=" + quote(tab_id)
        tab_field = f"<input type='hidden' name='ds_tab' value='{esc(tab_id)}'>" if tab_id else ""
        def render_run_row(r):
            try:
                row_summary = json.loads(r["result_summary_json"] or "{}")
            except Exception:
                row_summary = {}
            summary_attr = esc(json.dumps(row_summary, ensure_ascii=False))
            row_status = str(r["status"] or "unknown")
            active_run = row_status.lower() in ("queued", "running", "processing")
            return (
                f"<tr><td>#{int(r['id'])}</td><td>{esc(r['created_at'])}</td>"
                f"<td><span class='ag-state {'good' if row_status.lower()=='completed' else 'bad'}'>{esc(row_status)}</span></td>"
                f"<td>{esc(r['engine_version'])}</td>"
                f"<td><button type='button' class='ag-view-result' data-run-id='{int(r['id'])}' data-run-status='{esc(row_status)}' data-run-created='{esc(r['created_at'])}' data-run-engine='{esc(r['engine_version'])}' data-run-summary='{summary_attr}'>View result</button></td>"
                f"""<td><form method="post" action="/app/timetable/automatic/generation-report/delete" class="ag-delete-form" onsubmit="return confirm('Delete generation report run #{int(r['id'])}? This removes only the audit report. Existing timetable lessons will remain unchanged.');">"""
                f"<input type='hidden' name='profile_id' value='{pid}'><input type='hidden' name='run_id' value='{int(r['id'])}'>{tab_field}<button type='submit' class='ag-delete-btn' {'disabled' if active_run else ''}>Delete</button></form></td></tr>"
            )
        run_rows = "".join(render_run_row(r) for r in runs) or "<tr><td colspan='6' class='ag-muted'>No generation runs yet.</td></tr>"
        ready = bool(days and periods and (requirements or advanced_instructional_requirements) and not read_only)
        action_html = (
            f"""<form method='post' action='{esc(generate_action)}' class='ag-generate-form' onsubmit="return ttBindTabSession(this) && confirm('Generate a complete timetable using the current setup? Existing manual lessons will be preserved.');"><input type='hidden' name='profile_id' value='{pid}'>{tab_field}<button type='submit' class='ag-btn' {'disabled' if not tab_id else ''}>⚡ Generate complete timetable</button></form>"""
            if ready else
            (f"""<div class='ag-warning'>This profile is {esc(selected['status']).replace('_',' ')} and is read-only. Create a new draft revision before generating or changing its timetable.</div><a class='ag-btn secondary' href='/app/timetable/publishing?profile_id={pid}'>Create Revision</a>""" if read_only else
             f"""<div class='ag-warning'>Complete the setup requirements first: add instructional days, teaching periods and a weekly requirement for every current class-subject-teacher allocation.</div><a class='ag-btn secondary' href='/app/timetable/setup?profile_id={pid}'>Complete Setup</a>""")
        )
        audit_modal = """
        <div id='ag-result-modal' class='ag-modal' aria-hidden='true' role='dialog' aria-modal='true'>
          <div class='ag-modal-backdrop' data-close-modal='1'></div>
          <section class='ag-modal-panel'><button type='button' class='ag-modal-close' aria-label='Close' data-close-modal='1'>×</button>
          <span class='ag-kicker'>AUDITABLE GENERATION REPORT</span><h3 id='ag-modal-title'>Generation result</h3>
          <div id='ag-modal-meta' class='ag-modal-meta'></div><p id='ag-modal-message'></p>
          <div id='ag-modal-metrics' class='ag-metrics'></div><div id='ag-modal-details' class='ag-modal-details'></div>
          <div class='ag-modal-footer'><button type='button' class='ag-btn secondary' data-close-modal='1'>Close</button></div></section></div>
        <style>
        .ag-view-result{padding:7px 11px;border:1px solid #d5e8d8;border-radius:8px;background:#edf6ef;color:#17633b;font-size:11px;font-weight:850;cursor:pointer}.ag-view-result:hover{background:#17633b;color:#fff}
        .ag-modal{display:none;position:fixed;inset:0;z-index:10050;align-items:center;justify-content:center;padding:16px}.ag-modal.open{display:flex}.ag-modal-backdrop{position:absolute;inset:0;background:#10271bcc;backdrop-filter:blur(3px)}
        .ag-modal-panel{position:relative;z-index:1;width:min(620px,100%);max-height:85vh;overflow:auto;padding:24px;background:#fff;border:1px solid #dceade;border-radius:18px;box-shadow:0 24px 80px #071b1280;color:#173d2b}
        .ag-modal-panel h3{font-size:21px;margin:7px 38px 8px 0}.ag-modal-panel p{font-size:13px;line-height:1.65;color:#64786a}.ag-modal-close{position:absolute;right:14px;top:12px;width:34px;height:34px;border:0;border-radius:50%;background:#edf6ef;color:#17633b;font-size:24px;cursor:pointer}
        .ag-modal-meta{display:flex;gap:8px;flex-wrap:wrap;color:#64786a;font-size:11px}.ag-modal-meta span{padding:6px 9px;background:#f4f8f4;border-radius:8px}.ag-modal-details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}
        .ag-modal-detail{padding:10px 12px;border:1px solid #edf2ed;border-radius:9px;min-width:0}.ag-modal-detail b{display:block;font-size:10px;color:#64786a;margin-bottom:4px}.ag-modal-detail span{font-size:13px;font-weight:800;color:#173d2b;overflow-wrap:anywhere}.ag-modal-footer{display:flex;justify-content:flex-end;margin-top:18px}
        @media(max-width:480px){.ag-modal{padding:9px}.ag-modal-panel{padding:19px 15px;max-height:88vh}.ag-modal-details{grid-template-columns:1fr}}
        </style>
        <script>
        (function(){const modal=document.getElementById('ag-result-modal');if(!modal)return;
        const close=()=>{modal.classList.remove('open');modal.setAttribute('aria-hidden','true');document.body.style.overflow='';};
        document.addEventListener('click',event=>{const trigger=event.target.closest('.ag-view-result');if(trigger){let data={};try{data=JSON.parse(trigger.dataset.runSummary||'{}')}catch(_e){}
        document.getElementById('ag-modal-title').textContent='Generation run #'+trigger.dataset.runId;
        const meta=document.getElementById('ag-modal-meta');meta.replaceChildren();[trigger.dataset.runStatus,trigger.dataset.runCreated,trigger.dataset.runEngine].forEach(v=>{const s=document.createElement('span');s.textContent=v||'—';meta.append(s)});
        document.getElementById('ag-modal-message').textContent=data.message||'No result details were saved for this run.';
        const metrics=document.getElementById('ag-modal-metrics');metrics.replaceChildren();[['Generated lessons',data.generated_lessons],['Manual lessons kept',data.manual_lessons_kept],['Quality score',data.quality_score],['Search steps',data.search_nodes]].forEach(([label,value])=>{const item=document.createElement('span'),n=document.createElement('b');n.textContent=value??'—';item.append(n,document.createTextNode(label));metrics.append(item)});
        const details=document.getElementById('ag-modal-details');details.replaceChildren();Object.entries(data).filter(([k])=>!['message','generated_lessons','manual_lessons_kept','quality_score','search_nodes'].includes(k)).slice(0,20).forEach(([k,v])=>{const d=document.createElement('div'),l=document.createElement('b'),x=document.createElement('span');d.className='ag-modal-detail';l.textContent=k.replace(/_/g,' ');x.textContent=typeof v==='object'?JSON.stringify(v):String(v??'—');d.append(l,x);details.append(d)});
        modal.classList.add('open');modal.setAttribute('aria-hidden','false');document.body.style.overflow='hidden';modal.querySelector('.ag-modal-close').focus();return}
        if(event.target.closest('[data-close-modal]'))close()});
        document.addEventListener('keydown',e=>{if(e.key==='Escape'&&modal.classList.contains('open'))close()})})();
        </script>
        """
        body = f"""
        <style>.ag-wrap{{max-width:1180px;margin:auto;padding:clamp(14px,2.5vw,28px);color:#173d2b}}.ag-hero{{position:relative;overflow:hidden;display:flex;align-items:center;gap:18px;margin-bottom:18px;padding:25px 26px;border:1px solid #dceade;border-radius:20px;background:linear-gradient(115deg,#f4faf4 0%,#fff 68%,#e9f5eb 100%)}}.ag-hero:after{{content:' ';position:absolute;width:210px;height:210px;right:-70px;top:-105px;border:28px solid #dceede;border-radius:50%;opacity:.65}}.ag-hero-copy{{position:relative;z-index:1;max-width:760px}}.ag-hero h2{{font-size:clamp(23px,3vw,32px);letter-spacing:-.035em;margin:7px 0 8px;color:#143b29}}.ag-hero p{{font-size:13px;line-height:1.65;color:#617568;margin:0;max-width:680px}}.ag-kicker{{font-size:10px;font-weight:900;letter-spacing:.14em;color:#43845a}}.ag-select{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 16px;padding:12px 15px;background:#fff;border:1px solid #e1ebe3;border-radius:13px}}.ag-select label{{font-size:11px;font-weight:900;color:#52685a}}.ag-select select{{min-width:min(360px,100%);max-width:100%;padding:10px 36px 10px 12px;border:1px solid #dce7de;border-radius:9px;background:#fbfdfb;color:#173d2b;font-size:12px}}.ag-card,.ag-result,.ag-history{{background:white;border:1px solid #e1ebe3;border-radius:17px;padding:clamp(15px,2vw,22px);margin-bottom:16px;box-shadow:0 5px 20px #173d2b0a}}.ag-card h3,.ag-result h3{{font-size:19px;margin:5px 0;color:#173d2b}}.ag-card p,.ag-result p{{font-size:12px;color:#64786a;line-height:1.65}}.ag-checks{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:18px 0}}.ag-check{{position:relative;background:#f6faf6;border:1px solid #e5eee6;border-radius:12px;padding:14px 13px}}.ag-check b{{display:block;font-size:25px;line-height:1.2;color:#17633b}}.ag-check span{{display:block;margin-top:5px;font-size:10px;color:#64786a}}.ag-btn{{display:inline-flex;align-items:center;justify-content:center;padding:12px 17px;border:0;border-radius:10px;background:#17633b;color:white;text-decoration:none;font-size:12px;font-weight:850;cursor:pointer;box-shadow:0 4px 10px #17633b20}}.ag-btn:disabled{{opacity:.6;cursor:wait}}.ag-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8;box-shadow:none}}.ag-generate-form{{margin-top:5px}}.ag-warning{{padding:13px 15px;background:#fff7e8;color:#8b5b14;border:1px solid #f5e5c6;border-radius:10px;font-size:12px;line-height:1.55;margin:14px 0}}.ag-alert{{padding:11px 14px;border-radius:10px;margin-bottom:12px;font-size:12px;font-weight:700}}.ag-alert.success{{background:#eaf5ec;color:#17633b}}.ag-alert.error{{background:#fff1f0;color:#a12828}}.ag-result-head{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}}.ag-state{{display:inline-flex;font-size:10px;font-weight:900;padding:6px 10px;border-radius:20px}}.ag-state.good{{background:#eaf5ec;color:#17633b}}.ag-state.bad{{background:#fff1f0;color:#a12828}}.ag-metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:14px}}.ag-metrics span{{background:#f5f8f5;padding:13px;border-radius:10px;color:#64786a;font-size:10px}}.ag-metrics b{{display:block;font-size:22px;color:#173d2b}}.ag-history h3{{font-size:19px;margin:5px 0 14px}}.ag-history table{{width:100%;border-collapse:collapse;min-width:500px}}.ag-history th,.ag-history td{{padding:12px;border-bottom:1px solid #edf2ed;text-align:left;font-size:11px}}.ag-history th{{background:#f5f9f5;color:#315b3e;font-weight:900}}.ag-history a{{color:#17633b;font-weight:800;text-decoration:none}}.ag-delete-form{{margin:0}}.ag-delete-btn{{padding:7px 11px;border:1px solid #f0d3d0;border-radius:8px;background:#fff5f4;color:#a12828;font-size:11px;font-weight:850;cursor:pointer}}.ag-delete-btn:hover{{background:#a12828;color:#fff}}.ag-delete-btn:disabled{{opacity:.4;cursor:not-allowed}}.ag-table-scroll{{overflow:auto;border:1px solid #edf2ed;border-radius:10px}}.ag-muted{{text-align:center;color:#94a3a0;padding:18px}}.ag-empty{{padding:30px;background:white;border-radius:14px;text-align:center}}.ag-date-form{{display:flex;gap:10px;align-items:end;flex-wrap:wrap;border-top:1px solid #e7eee8;margin-top:14px;padding-top:14px}}.ag-date-form label{{display:grid;gap:5px;font-size:11px;font-weight:800}}.ag-date-form input{{padding:9px;border:1px solid #dce7de;border-radius:8px;background:#fff}}.ag-date-form p{{flex-basis:100%;margin:0}}@media(max-width:760px){{.ag-checks{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ag-hero{{padding:20px 17px}}.ag-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:420px){{.ag-checks{{gap:7px}}.ag-check{{padding:11px}}.ag-check b{{font-size:22px}}.ag-select select{{min-width:100%}}}}</style>
        <div class='ag-wrap'><header class='ag-hero'><div class='ag-hero-copy'><span class='ag-kicker'>DAVISCHOOL · SMART TIMETABLING</span><h2>Smart Timetable Generator</h2><p>Build a clash-checked timetable from your approved teaching requirements, teacher allocations, school week and available rooms. Manual lessons remain protected.</p></div></header>{notice}{selector}
        {audit_modal}<section class='ag-card'><span class='ag-kicker'>GENERATION READINESS</span><h3>{esc(selected['name'])}</h3><p>{esc(selected['academic_year'])} · {esc(selected['term'])}. The generator preserves manual lessons and replaces an earlier automatic timetable only after it finds a complete solution.</p><div class='ag-checks'><div class='ag-check'><b>{int(requirements)}</b><span>Lesson requirements</span></div><div class='ag-check'><b>{int(allocations_count)}</b><span>Current allocations</span></div></div>
        {action_html}
                </section>{job_progress_html}{result_html}<section class='ag-history'><span class='ag-kicker'>AUDITABLE GENERATION HISTORY</span><h3>Previous runs</h3><div class='ag-table-scroll'><table><tr><th>Run</th><th>Created</th><th>Status</th><th>Engine</th><th>Result</th><th>Actions</th></tr>{run_rows}</table></div></section></div>{generator_script}
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

    # Accept both the canonical action URL and the legacy page URL used by
    # already-rendered clients/forms. The page itself remains GET-only.
    @app.post("/app/timetable/automatic")
    @app.post("/app/timetable/automatic/generate")
    def run_automatic_generation(request: Request, profile_id: int = Form(...)):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        from app.timetable.generation_jobs import enqueue_generation_job
        try:
            job_id = enqueue_generation_job(
                get_db, int(school["id"]), int(profile_id), request.session.get("email", "")
            )
        except Exception:
            import logging
            logging.getLogger("davischool.timetable.generator").exception(
                "Could not enqueue automatic timetable generation (school_id=%s profile_id=%s)",
                int(school["id"]), int(profile_id),
            )
            return redirect_generator(profile_id, message="The generation job could not be queued because the database is busy. Your existing timetable has not been changed. Please retry.", error=True)
        return RedirectResponse(
            f"/app/timetable/automatic?profile_id={int(profile_id)}&job_id={job_id}", 303
        )

    @app.post("/app/timetable/automatic/generation-report/delete")
    def delete_generation_report(request: Request, profile_id: int = Form(...), run_id: int = Form(...), ds_tab: str = Form("")):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        school_id = int(school["id"])
        tab_id = str(ds_tab or "").strip()
        if not (16 <= len(tab_id) <= 64 and all(ch.isalnum() or ch in "_-" for ch in tab_id)):
            tab_id = ""
        def report_redirect(message, error=False):
            response = redirect_generator(profile_id, message=message, error=error)
            location = response.headers.get("location", "/app/timetable/automatic")
            if tab_id:
                location += ("&" if "?" in location else "?") + "ds_tab=" + quote(tab_id)
            return RedirectResponse(location, 303)
        con = get_db()
        try:
            cur = con.cursor()
            run = cur.execute(
                """SELECT id,status FROM ds_timetable_generation_runs
                   WHERE id=? AND school_id=? AND profile_id=?""",
                (int(run_id), school_id, int(profile_id)),
            ).fetchone()
            if not run:
                return report_redirect("That generation report was not found.", error=True)
            if str(run["status"] or "").lower() in ("queued", "running", "processing"):
                return report_redirect("An active generation run cannot be deleted.", error=True)
            cur.execute(
                """DELETE FROM ds_timetable_generation_runs
                   WHERE id=? AND school_id=? AND profile_id=?""",
                (int(run_id), school_id, int(profile_id)),
            )
            con.commit()
            return report_redirect(f"Generation report run #{int(run_id)} deleted. Existing timetable lessons were not changed.")
        except Exception:
            con.rollback()
            import logging
            logging.getLogger("davischool.timetable.generator").exception(
                "Could not delete generation report (school_id=%s profile_id=%s run_id=%s)",
                school_id, int(profile_id), int(run_id),
            )
            return report_redirect("The generation report could not be deleted. No timetable lessons were changed.", error=True)
        finally:
            con.close()

    @app.get("/app/timetable/generation-jobs/{job_id}")
    def timetable_generation_job_status(request: Request, job_id: int):
        school = school_for(request)
        if not school:
            return JSONResponse({"error": "Not authorised"}, status_code=401)
        from app.timetable.generation_jobs import get_generation_job
        job = get_generation_job(get_db, int(school["id"]), int(job_id))
        if not job:
            return JSONResponse({"error": "Generation job not found"}, status_code=404)
        return JSONResponse(job)
