"""Shared presentation for the Smart Timetable pages.

The dashboard sidebar handles page-level navigation. Every configuration
section on the setup page is presented as an in-page horizontal tab.
"""
from html import escape


def timetable_workspace(request, body):
    path = str(request.url.path or "")
    profile_id = str(request.query_params.get("profile_id", "") or "")
    profile_qs = ("?profile_id=" + escape(profile_id, quote=True)) if profile_id.isdigit() and int(profile_id) > 0 else ""
    links = [
        ("/app/timetable", "Overview", "overview"),
        ("/app/timetable/setup", "Configure", "setup"),
        ("/app/timetable/setup?tab=requirements", "Requirements", "requirements"),
        ("/app/timetable/builder", "Manual Builder", "builder"),
        ("/app/timetable/automatic", "Generate", "automatic"),
        ("/app/timetable/room-allocation", "Room Allocation", "room-allocation"),
        ("/app/timetable/views", "Views", "views"),
        ("/app/timetable/publishing", "Publish", "publishing"),
    ]
    active = {
        "/app/timetable": "overview",
        "/app/timetable/setup": "requirements" if str(request.query_params.get("tab", "")) == "requirements" else "setup",
        "/app/timetable/builder": "builder",
        "/app/timetable/automatic": "automatic",
        "/app/timetable/room-allocation": "room-allocation",
        "/app/timetable/views": "views",
        "/app/timetable/publishing": "publishing",
    }.get(path, "")
    nav_items = []
    for href, label, key in links:
        if "?" in href:
            href = href + ("&" if profile_qs else "") + profile_qs.lstrip("?")
        else:
            href += profile_qs
        selected = " aria-current='page'" if active == key else ""
        nav_items.append(f"<a href='{href}'{selected}>{label}</a>")
    global_nav = (
        "<nav class='tt-global-tabs' aria-label='Smart Timetable sections'>"
        + "".join(nav_items) + "</nav>"
        + "<style>"
        ".tt-global-tabs{display:flex;align-items:center;gap:6px;overflow-x:auto;overscroll-behavior-x:contain;padding:7px;margin:0 0 16px;border:1px solid #dce9de;border-radius:13px;background:#f7fbf7;scrollbar-width:thin}"
        ".tt-global-tabs a{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;min-height:39px;padding:9px 13px;border-radius:9px;color:#52705b;text-decoration:none;font-size:11px;font-weight:800;white-space:nowrap}"
        ".tt-global-tabs a:hover{background:#e8f3e9;color:#245d39}"
        ".tt-global-tabs a[aria-current='page']{background:#2e7548;color:#fff;box-shadow:0 3px 9px rgba(36,103,61,.16)}"
        "@media(max-width:600px){.tt-global-tabs{margin-left:-3px;margin-right:-3px}.tt-global-tabs a{min-height:38px;padding:8px 11px;font-size:10px}}"
        "</style>"
    )
    if path != "/app/timetable/setup":
        return global_nav + body

    requested = str(request.query_params.get("tab", "setup") or "setup").lower()
    requested_section = str(request.query_params.get("section", "") or "").lower()
    marker = ("<span class='tt-workspace-state' data-requested-tab='" + escape(requested, quote=True) +
              "' data-requested-section='" + escape(requested_section, quote=True) + "' hidden></span>")
    intro = """
      <header class='tt-workflow-intro'>
        <div><span>SMART TIMETABLE · CONFIGURATION</span><h1>Configure Timetable</h1>
        <p>Set up the timetable structure, availability and teaching requirements.</p></div>
      </header>
      <style>
        .tt-workflow-intro{margin:0 0 14px;padding:8px 2px 12px;border-bottom:1px solid #e1ebe2}
        .tt-workflow-intro>div{display:grid;gap:4px}
        .tt-workflow-intro span{font-size:9px;letter-spacing:.13em;font-weight:850;color:#398052}
        .tt-workflow-intro h1{margin:0;color:#204a34;font-size:clamp(21px,2.5vw,28px);letter-spacing:-.55px}
        .tt-workflow-intro p{margin:0;color:#718276;font-size:11px;line-height:1.5}
        .tt-wrap .tt-section[hidden]{display:none!important}
        .tt-setup-tabs{display:flex;gap:7px;overflow-x:auto;overscroll-behavior-x:contain;padding:7px;margin:0 0 16px;border:1px solid #d9e8dc;border-radius:15px;background:#f8fcf8;scrollbar-width:thin}
        .tt-setup-tabs button{flex:0 0 auto;min-height:42px;padding:10px 15px;border:1px solid transparent;border-radius:10px;background:transparent;color:#52705b;font-size:12px;font-weight:800;white-space:nowrap;cursor:pointer;transition:background .15s,color .15s,box-shadow .15s}
        .tt-setup-tabs button:hover{background:#eaf4ec;color:#245d39}
        .tt-setup-tabs button[aria-selected="true"]{background:#2e7548;color:#fff;box-shadow:0 4px 11px rgba(36,103,61,.18)}
        .tt-wrap .tt-section .tt-section-content{display:block!important}
        .tt-wrap .tt-section .tt-section-toggle{display:none!important}
        @media(max-width:600px){.tt-setup-tabs{margin-left:-4px;margin-right:-4px;border-radius:12px}.tt-setup-tabs button{min-height:40px;padding:9px 12px;font-size:11px}}
      </style>
      <script>
      function initTimetableSetupTabs(){
        const root=document.querySelector('.tt-wrap');
        if(!root)return;
        const sections=[...root.querySelectorAll('.tt-section')];
        if(!sections.length)return;
        const state=document.querySelector('.tt-workspace-state');
        const requested=state?.getAttribute('data-requested-tab')||'setup';
        const requestedSection=state?.getAttribute('data-requested-section')||'';
        const nav=document.createElement('nav');
        nav.className='tt-setup-tabs';
        nav.setAttribute('role','tablist');
        nav.setAttribute('aria-label','Timetable setup sections');
        const allLabels=sections.map((section,index)=>{
          const heading=section.querySelector('h3,h2,h4');
          return (heading?.textContent||('Section '+(index+1))).trim();
        });
        // Teaching Requirements is one landing workspace with exactly two tabs:
        // Tracking and Subject Requirements. Never expose a separate requirements-only page.
        const keep = allLabels.map(label=>{
          if(requested==='requirements') return /track class lesson allocations|subject requirements/i.test(label);
          // Availability is a section inside the Configure workspace. Keep every
          // Configure section in the tab strip so users can still navigate away;
          // the availability workspace itself is selected below.
          if(requested==='availability') return true;
          if(requested==='setup') return !/teacher availability|subject availability|requirement|workload|allocation/i.test(label);
          return true;
        });
        const visibleSections=sections.filter((section,index)=>keep[index]);
        const visibleLabels=allLabels.filter((label,index)=>keep[index]);
        sections.forEach((section,index)=>{ if(!keep[index]) section.hidden=true; });
        if(!visibleSections.length)return;
        const sectionsForTabs=visibleSections;
        const labels=visibleLabels;
        let initial=0;
        if(requested==='requirements'){
          const wanted=requestedSection==='tracking'
            ? /track class lesson allocations/i
            : /subject requirements/i;
          const match=labels.findIndex(label=>wanted.test(label));
          initial=match>=0?match:Math.max(0,labels.findIndex(label=>/subject requirements/i.test(label)));
        }else if(requested==='availability'){
          const match=labels.findIndex(label=>/staff and subject availability|teacher availability/i.test(label));
          initial=match>=0?match:0;
        }
        function activate(index){
          sectionsForTabs.forEach((section,i)=>{
            section.hidden=i!==index;
            section.classList.toggle('tt-tab-active',i===index);
          });
          [...nav.querySelectorAll('button')].forEach((button,i)=>{
            button.setAttribute('aria-selected',String(i===index));
            button.tabIndex=i===index?0:-1;
          });
        }
        sectionsForTabs.forEach((section,index)=>{
          const button=document.createElement('button');
          button.type='button';
          button.textContent=labels[index];
          button.setAttribute('role','tab');
          button.setAttribute('aria-selected','false');
          button.tabIndex=-1;
          button.addEventListener('click',()=>activate(index));
          button.addEventListener('keydown',event=>{
            if(event.key==='ArrowRight'||event.key==='ArrowLeft'){
              event.preventDefault();
              const next=(index+(event.key==='ArrowRight'?1:-1)+sectionsForTabs.length)%sectionsForTabs.length;
              nav.querySelectorAll('button')[next]?.focus();
              activate(next);
            }
          });
          nav.append(button);
        });
        sectionsForTabs[0].parentNode.insertBefore(nav,sectionsForTabs[0]);
        // Keep the existing profile switcher and save feedback, but place them
        // below the section tabs so the Configure page opens directly on its tabs.
        const wrap=sectionsForTabs[0].parentNode;
        const profilePicker=wrap.querySelector(':scope > .tt-select');
        const alerts=[...wrap.querySelectorAll(':scope > .tt-alert')];
        if(profilePicker) nav.insertAdjacentElement('afterend',profilePicker);
        let anchor=profilePicker||nav;
        alerts.forEach(alert=>{anchor.insertAdjacentElement('afterend',alert);anchor=alert;});
        activate(initial);
      }
      if(document.readyState==='loading'){
        document.addEventListener('DOMContentLoaded',initTimetableSetupTabs,{once:true});
      }else{
        initTimetableSetupTabs();
      }
      </script>
    """
    return global_nav + marker + intro + body
