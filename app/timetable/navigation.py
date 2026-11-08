"""Shared navigation and presentation for the Smart Timetable workspace."""
from html import escape
from urllib.parse import urlencode

def timetable_workspace(request, body):
    path = str(request.url.path or "")
    params = request.query_params
    profile_id = str(params.get("profile_id", "") or "")
    try:
        pid = str(int(profile_id)) if profile_id else ""
    except (TypeError, ValueError):
        pid = ""
    tab = str(params.get("tab", "setup") or "setup").lower()
    if path == "/app/timetable":
        active = "overview"
    elif path == "/app/timetable/setup":
        active = tab if tab in ("setup", "requirements", "availability") else "setup"
    elif path.startswith("/app/timetable/constraints"):
        active = "constraints"
    elif path.startswith("/app/timetable/automatic"):
        active = "automatic"
    elif path.startswith("/app/timetable/builder"):
        active = "builder"
    elif path.startswith("/app/timetable/views"):
        active = "views"
    elif path.startswith("/app/timetable/publishing"):
        active = "publishing"
    else:
        active = "overview"
    items = [
        ("overview", "Overview", "/app/timetable"),
        ("setup", "Timetable setup", "/app/timetable/setup"),
        ("requirements", "Teaching requirements", "/app/timetable/setup?tab=requirements"),
        ("availability", "Availability", "/app/timetable/setup?tab=availability"),
        ("constraints", "Constraints", "/app/timetable/constraints"),
        ("automatic", "Auto generate", "/app/timetable/automatic"),
        ("builder", "Manual builder", "/app/timetable/builder"),
        ("views", "Timetable views", "/app/timetable/views"),
        ("publishing", "Review & publish", "/app/timetable/publishing"),
    ]
    links = []
    for key, label, url in items:
        if pid and key != "overview":
            separator = "&" if "?" in url else "?"
            url += separator + "profile_id=" + pid
        links.append(
            "<a class='tt-work-tab" + (" is-active" if key == active else "") +
            "' href='" + escape(url, quote=True) + "' " +
            ("aria-current='page' " if key == active else "") +
            "><span>" + label + "</span><i></i></a>"
        )
    setup_script = ""
    if path == "/app/timetable/setup":
        setup_script = """
        <script>
        (function(){
          const nav=document.querySelector('.tt-workspace-nav'); if(!nav)return;
          const selected=nav.getAttribute('data-setup-tab')||'setup';
          const sections=[...document.querySelectorAll('.tt-wrap .tt-section')];
          sections.forEach(section=>{
            const heading=(section.querySelector('h3')?.textContent||'').toLowerCase();
            let group='setup';
            if(heading.includes('availability')) group='availability';
            if(heading.includes('requirement')||heading.includes('workload')) group='requirements';
            section.hidden=group!==selected;
          });
          const intro=document.querySelector('.tt-workflow-intro');
          if(intro){
            const copy={
              setup:['TIMETABLE FOUNDATION','Configure the school week, periods, breaks, calendar and learning spaces.'],
              requirements:['TEACHING REQUIREMENTS','Define subject loads and class workload limits for the timetable engine.'],
              availability:['STAFF & SUBJECT AVAILABILITY','Set preferred, fallback and unavailable teaching periods with the school-wide registers.']
            }[selected]||[];
            if(copy.length){intro.querySelector('b').textContent=copy[0];intro.querySelector('p').textContent=copy[1];}
          }
        })();
        </script>"""
    shell = """
    <style>
    .tt-workspace-nav{max-width:1500px;margin:0 auto 16px;padding:12px 13px 0;background:#fff;border:1px solid #dce9df;border-radius:17px;box-shadow:0 7px 22px rgba(36,83,52,.045)}
    .tt-workspace-nav .tt-workspace-top{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:2px 5px 11px}
    .tt-workspace-nav .tt-workspace-top b{font-size:12px;letter-spacing:.04em;color:#24563a}
    .tt-workspace-nav .tt-workspace-top small{font-size:10px;color:#819187}
    .tt-workspace-tabs{display:flex;gap:5px;overflow-x:auto;scrollbar-width:thin;padding:0 2px 9px;overscroll-behavior-x:contain}
    .tt-work-tab{position:relative;display:inline-flex;align-items:center;justify-content:center;min-height:39px;padding:0 13px;border-radius:10px 10px 7px 7px;color:#62766a!important;text-decoration:none!important;font-size:11px;font-weight:750;white-space:nowrap;transition:background .16s,color .16s}
    .tt-work-tab:hover{background:#f0f7f1;color:#245f3d!important}
    .tt-work-tab.is-active{background:#eaf5ec;color:#17633b!important}
    .tt-work-tab.is-active i{position:absolute;left:13px;right:13px;bottom:0;height:3px;border-radius:4px;background:#2b8050}
    .tt-workflow-intro{display:flex;align-items:center;gap:12px;margin:0 0 13px;padding:13px 16px;border:1px solid #dceade;border-radius:13px;background:linear-gradient(110deg,#f7fbf7,#edf6ef)}
    .tt-workflow-intro>span{width:34px;height:34px;display:grid;place-items:center;flex:none;border-radius:11px;background:#e0f0e3;color:#267347;font-size:17px}
    .tt-workflow-intro b{display:block;font-size:10px;letter-spacing:.11em;color:#398052}
    .tt-workflow-intro p{margin:4px 0 0;font-size:11px;line-height:1.45;color:#718276}
    .tt-wrap .tt-section[hidden]{display:none!important}
    @media(max-width:600px){.tt-workspace-nav{margin-bottom:11px;padding:10px 8px 0;border-radius:13px}.tt-workspace-nav .tt-workspace-top{padding:2px 5px 9px}.tt-workspace-nav .tt-workspace-top small{display:none}.tt-work-tab{padding:0 11px;min-height:37px}.tt-workflow-intro{padding:11px 12px}}
    </style>
    """
    nav_html = (
        shell +
        "<nav class='tt-workspace-nav' data-setup-tab='" + escape(active) + "' aria-label='Smart Timetable workflow'>" +
        "<div class='tt-workspace-top'><b>SMART TIMETABLE WORKSPACE</b><small>Move through each stage without leaving the module</small></div>" +
        "<div class='tt-workspace-tabs'>" + "".join(links) + "</div></nav>"
    )
    if path == "/app/timetable/setup":
        nav_html += "<div class='tt-workflow-intro'><span>▦</span><div><b>WORKFLOW</b><p>Configure the timetable foundation before setting requirements and availability.</p></div></div>"
    return nav_html + body + setup_script
