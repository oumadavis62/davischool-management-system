"""Shared presentation for the Smart Timetable pages.

The dashboard sidebar handles page-level navigation. Every configuration
section on the setup page is presented as an in-page horizontal tab.
"""
from html import escape


def timetable_workspace(request, body):
    path = str(request.url.path or "")
    if path != "/app/timetable/setup":
        return body

    requested = str(request.query_params.get("tab", "setup") or "setup").lower()
    requested_section = str(request.query_params.get("section", "") or "").lower()
    marker = ("<span class='tt-workspace-state' data-requested-tab='" + escape(requested, quote=True) +
              "' data-requested-section='" + escape(requested_section, quote=True) + "' hidden></span>")
    intro = """
      <div class='tt-workflow-intro'><span>▦</span><div>
        <b>TIMETABLE CONFIGURATION</b>
        <p>Choose a section below to configure each part of your school's timetable.</p>
      </div></div>
      <style>
        .tt-workflow-intro{display:flex;align-items:center;gap:12px;margin:0 0 13px;padding:13px 16px;border:1px solid #dceade;border-radius:13px;background:linear-gradient(110deg,#f7fbf7,#edf6ef)}
        .tt-workflow-intro>span{width:34px;height:34px;display:grid;place-items:center;flex:none;border-radius:11px;background:#e0f0e3;color:#267347;font-size:17px}
        .tt-workflow-intro b{display:block;font-size:10px;letter-spacing:.11em;color:#398052}
        .tt-workflow-intro p{margin:4px 0 0;font-size:11px;line-height:1.45;color:#718276}
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
          if(requested==='availability') return /teacher availability/i.test(label);
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
        activate(initial);
      }
      if(document.readyState==='loading'){
        document.addEventListener('DOMContentLoaded',initTimetableSetupTabs,{once:true});
      }else{
        initTimetableSetupTabs();
      }
      </script>
    """
    return marker + intro + body
