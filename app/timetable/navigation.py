"""Shared presentation for the Smart Timetable pages.

Navigation is provided by the dashboard's Timetable Management sidebar group;
this wrapper deliberately does not render a second, horizontal navigation bar.
"""
from html import escape


def timetable_workspace(request, body):
    path = str(request.url.path or "")
    params = request.query_params
    tab = str(params.get("tab", "setup") or "setup").lower()
    if path == "/app/timetable/setup":
        active = tab if tab in ("setup", "requirements", "availability") else "setup"
    else:
        active = "setup"

    setup_script = ""
    if path == "/app/timetable/setup":
        setup_script = """
        <script>
        (function(){
          const state=document.querySelector('.tt-workspace-state'); if(!state)return;
          const selected=state.getAttribute('data-setup-tab')||'setup';
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
    if path == "/app/timetable/setup":
        marker = "<span class='tt-workspace-state' data-setup-tab='" + escape(active, quote=True) + "' hidden></span>"
        intro = (
            "<div class='tt-workflow-intro'><span>▦</span><div>"
            "<b>WORKFLOW</b><p>Configure the timetable foundation before setting requirements and availability.</p>"
            "</div></div>"
            "<style>.tt-workflow-intro{display:flex;align-items:center;gap:12px;margin:0 0 13px;padding:13px 16px;border:1px solid #dceade;border-radius:13px;background:linear-gradient(110deg,#f7fbf7,#edf6ef)}"
            ".tt-workflow-intro>span{width:34px;height:34px;display:grid;place-items:center;flex:none;border-radius:11px;background:#e0f0e3;color:#267347;font-size:17px}"
            ".tt-workflow-intro b{display:block;font-size:10px;letter-spacing:.11em;color:#398052}"
            ".tt-workflow-intro p{margin:4px 0 0;font-size:11px;line-height:1.45;color:#718276}"
            ".tt-wrap .tt-section[hidden]{display:none!important}</style>"
        )
        return marker + intro + body + setup_script
    return body
