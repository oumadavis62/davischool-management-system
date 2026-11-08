"""Shared presentation for the Smart Timetable pages.

The dashboard sidebar handles page-level navigation. The setup workspace uses
in-page horizontal tabs for its individual configuration sections.
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

    if path == "/app/timetable/setup":
        marker = "<span class='tt-workspace-state' data-setup-tab='" + escape(active, quote=True) + "' hidden></span>"
        intro = (
            "<div class='tt-workflow-intro'><span>▦</span><div>"
            "<b>WORKFLOW</b><p>Configure the timetable foundation before setting requirements and availability.</p>"
            "</div></div>"
            """<style>
            .tt-workflow-intro{display:flex;align-items:center;gap:12px;margin:0 0 13px;padding:13px 16px;border:1px solid #dceade;border-radius:13px;background:linear-gradient(110deg,#f7fbf7,#edf6ef)}
            .tt-workflow-intro>span{width:34px;height:34px;display:grid;place-items:center;flex:none;border-radius:11px;background:#e0f0e3;color:#267347;font-size:17px}
            .tt-workflow-intro b{display:block;font-size:10px;letter-spacing:.11em;color:#398052}
            .tt-workflow-intro p{margin:4px 0 0;font-size:11px;line-height:1.45;color:#718276}
            .tt-wrap .tt-section[hidden]{display:none!important}
            .tt-setup-tabs{display:flex;gap:7px;overflow-x:auto;overscroll-behavior-x:contain;padding:7px;margin:0 0 16px;border:1px solid #d9e8dc;border-radius:15px;background:#f8fcf8;scrollbar-width:thin}
            .tt-setup-tabs button{flex:0 0 auto;min-height:42px;padding:10px 15px;border:1px solid transparent;border-radius:10px;background:transparent;color:#52705b;font-size:12px;font-weight:800;white-space:nowrap;cursor:pointer;transition:background .15s,color .15s,box-shadow .15s}
            .tt-setup-tabs button:hover{background:#eaf4ec;color:#245d39}
            .tt-setup-tabs button[aria-selected="true"]{background:#2e7548;color:#fff;box-shadow:0 4px 11px rgba(36,103,61,.18)}
            .tt-wrap .tt-section.tt-tab-active{display:block}
            .tt-wrap .tt-section .tt-section-content{display:block!important}
            .tt-wrap .tt-section .tt-section-toggle{display:none!important}
            @media(max-width:600px){.tt-setup-tabs{margin-left:-4px;margin-right:-4px;border-radius:12px}.tt-setup-tabs button{min-height:40px;padding:9px 12px;font-size:11px}}
            </style>"""
            """<script>
            (function(){
              const root=document.querySelector('.tt-wrap'); if(!root)return;
              const state=document.querySelector('.tt-workspace-state');
              const selected=state?.getAttribute('data-setup-tab')||'setup';
              const all=[...root.querySelectorAll('.tt-section')];
              const groups=all.map(section=>{
                const heading=(section.querySelector('h3')?.textContent||'').toLowerCase();
                let group='setup';
                if(heading.includes('availability')) group='availability';
                if(heading.includes('requirement')||heading.includes('workload')) group='requirements';
                return {section,group};
              });
              const visible=groups.filter(item=>item.group===selected);
              groups.forEach(item=>item.section.hidden=item.group!==selected);
              const intro=document.querySelector('.tt-workflow-intro');
              if(intro){
                const copy={
                  setup:['TIMETABLE FOUNDATION','Configure the school week, periods, breaks, calendar and learning spaces.'],
                  requirements:['TEACHING REQUIREMENTS','Define subject loads and class workload limits for the timetable engine.'],
                  availability:['STAFF & SUBJECT AVAILABILITY','Set preferred, fallback and unavailable teaching periods with the school-wide registers.']
                }[selected]||[];
                if(copy.length){intro.querySelector('b').textContent=copy[0];intro.querySelector('p').textContent=copy[1];}
              }
              let nav=document.querySelector('.tt-setup-tabs');
              if(!nav){nav=document.createElement('nav');nav.className='tt-setup-tabs';nav.setAttribute('aria-label','Timetable setup sections');}
              function buildTabs(){
                const currentRoot=document.querySelector('.tt-wrap'); if(!currentRoot)return;
                const sections=[...currentRoot.querySelectorAll('.tt-section')].filter(section=>!section.hidden);
                if(!sections.length){nav.hidden=true;return;}
                nav.hidden=false;
                const previous=nav.querySelector('button[aria-selected="true"]')?.dataset.section;
                nav.replaceChildren();
                sections.forEach((section,index)=>{
                  const heading=section.querySelector('h3');
                  const label=(heading?.textContent||'Section '+(index+1)).trim();
                  const button=document.createElement('button');button.type='button';button.textContent=label;
                  button.dataset.section=String(index);button.setAttribute('role','tab');
                  button.setAttribute('aria-selected',String(index===Math.min(Number(previous)||0,sections.length-1)));
                  button.addEventListener('click',()=>activate(index));
                  nav.append(button);
                });
                const first=currentRoot.querySelector('.tt-section');
                if(first&&nav.parentNode!==first.parentNode) first.parentNode.insertBefore(nav,first);
                activate(Math.min(Number(previous)||0,sections.length-1));
              }
              function activate(index){
                const currentRoot=document.querySelector('.tt-wrap');if(!currentRoot)return;
                const sections=[...currentRoot.querySelectorAll('.tt-section')].filter(section=>!section.hidden);
                sections.forEach((section,i)=>{
                  section.classList.toggle('tt-tab-active',i===index);
                  section.hidden=i!==index;
                });
                [...nav.querySelectorAll('button')].forEach((button,i)=>button.setAttribute('aria-selected',String(i===index)));
              }
              buildTabs();
              if(!window.__ttSetupTabsObserver){
                window.__ttSetupTabsObserver=new MutationObserver(()=>{if(!window.__ttSetupTabsQueued){window.__ttSetupTabsQueued=true;requestAnimationFrame(()=>{window.__ttSetupTabsQueued=false;buildTabs();});}});
                window.__ttSetupTabsObserver.observe(root,{childList:true,subtree:true});
              }
            })();
            </script>"""
        )
        return marker + intro + body
    return body
