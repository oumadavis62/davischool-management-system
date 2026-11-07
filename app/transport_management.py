from datetime import datetime
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.new_ui import _audit, _db, _require_permission, _school_page, _school_session

router = APIRouter()

def _transport_page(request, title, body):
    shared = """
<style>
.transport-page.inv-workspace{--inv-forest:#174b32;--inv-green:#26734a;color:#233b2d;width:100%;max-width:none!important;padding-bottom:28px}
.transport-page.inv-workspace:before{content:"";display:block;height:5px;margin:-2px 0 16px;border-radius:99px;background:linear-gradient(90deg,#174b32,#39845a 48%,#b8d8bd);box-shadow:0 2px 8px #174b321c}
.transport-page.inv-workspace .page-heading{position:relative;overflow:hidden;isolation:isolate;display:flex;justify-content:space-between;align-items:center;gap:14px;padding:22px 24px 21px;margin:0 0 17px;border:1px solid #dce9de;border-radius:19px;background:linear-gradient(115deg,#f5faf5 0%,#fff 58%,#edf6ee 100%);box-shadow:0 8px 24px #214c2d0b}
.transport-page.inv-workspace .page-heading h1{font-size:clamp(25px,3vw,33px);font-weight:800;letter-spacing:-.8px;line-height:1.15;color:#174b32;margin:7px 0 8px}
.transport-page.inv-workspace .page-heading>div>div:last-child{color:#718278;font-size:12px;line-height:1.55}
.transport-page.inv-workspace .lib-eyebrow{display:inline-flex;align-items:center;gap:7px;color:#397653;font-size:10px;font-weight:800;letter-spacing:1.7px}
.transport-page.inv-workspace .lib-eyebrow:before{content:"";width:7px;height:7px;border-radius:2px;background:#4c9665;box-shadow:0 0 0 4px #e2f0e4}
.transport-page.inv-workspace .tr-kpis{grid-template-columns:repeat(auto-fit,minmax(175px,1fr))!important;gap:13px!important;margin:0 0 17px!important}
.transport-page.inv-workspace .tr-kpis>div{position:relative;overflow:hidden;min-height:100px;padding:17px 18px 15px 20px!important;border:1px solid #e0ebe1!important;border-radius:16px!important;background:linear-gradient(145deg,#fff,#f8fbf8)!important;box-shadow:0 5px 17px #183d2609!important}
.transport-page.inv-workspace .tr-kpis>div:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,#367c50,#a6c9a9)}
.transport-page.inv-workspace .tr-kpis span{color:#718176!important;font-size:11px!important;font-weight:750}
.transport-page.inv-workspace .tr-kpis strong{color:#1e5b3a!important;font-size:27px!important;letter-spacing:-.6px}
.transport-page.inv-workspace .tr-panel{padding:18px!important;margin:0 0 14px!important;border:1px solid #e1ebe2!important;border-radius:17px!important;background:#fff!important;box-shadow:0 6px 22px #193d2609!important}
.transport-page.inv-workspace .tr-scroll{max-width:100%;border:1px solid #e5ede6;border-radius:13px;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}
.transport-page.inv-workspace table{border-collapse:separate!important;border-spacing:0!important;width:100%;min-width:760px}
.transport-page.inv-workspace th{padding:13px 14px!important;background:linear-gradient(180deg,#f2f8f2,#eaf3eb)!important;color:#42634c!important;font-size:10px!important;font-weight:800;letter-spacing:.7px;text-transform:uppercase;white-space:nowrap}
.transport-page.inv-workspace td{padding:12px 14px!important;border-bottom:1px solid #edf2ed!important;color:#3c5143;font-size:12px!important;vertical-align:middle}
.transport-page.inv-workspace tbody tr:nth-child(even){background:#fbfdfb}
.transport-page.inv-workspace tbody tr:hover{background:#f0f7f1}
.transport-page.inv-workspace .tr-muted,.transport-page.inv-workspace small{color:#718278!important}
.transport-page.inv-workspace label{color:#3d5946;font-size:11px!important;font-weight:750;line-height:1.35}
.transport-page.inv-workspace input,.transport-page.inv-workspace select,.transport-page.inv-workspace textarea{min-height:42px!important;padding:10px 11px!important;border:1px solid #dce7de!important;border-radius:10px!important;background:#fcfefc!important;color:#294534}
.transport-page.inv-workspace input:focus,.transport-page.inv-workspace select:focus,.transport-page.inv-workspace textarea:focus{outline:0;border-color:#78a985!important;box-shadow:0 0 0 3px #e4f1e6}
.transport-page.inv-workspace .btn{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:9px 15px;border:1px solid #1f5b3b;border-radius:10px;background:linear-gradient(135deg,#205f3e,#317b4d);color:#fff!important;font-size:12px;font-weight:800;box-shadow:none;transition:all .16s ease}
.transport-page.inv-workspace .btn:hover{filter:brightness(1.04);transform:translateY(-1px);box-shadow:0 5px 12px #205f3e20}
.transport-page.inv-workspace .btn.btn-light{border-color:#dce8de;background:#f4f8f4;color:#3f6249!important}
.transport-page.inv-workspace .tr-dialog,.transport-page.inv-workspace dialog.tr-dialog{width:min(760px,calc(100% - 18px));max-height:90vh;overflow:auto;border:1px solid #dce8de;border-radius:20px;padding:22px;background:#fff;box-shadow:0 28px 90px #102d1c55}
dialog.tr-dialog{width:min(760px,calc(100% - 18px));max-height:90vh;overflow:auto;border:1px solid #dce8de;border-radius:20px;padding:22px;background:#fff;box-shadow:0 28px 90px #102d1c55}dialog.tr-dialog h2{margin:0 0 15px;color:#1d5033;font-size:20px}
.transport-page.inv-workspace dialog::backdrop{background:#0d1f1385;backdrop-filter:blur(3px)}
.transport-page.inv-workspace .tr-dialog h2{margin:0 0 15px;color:#1d5033;font-size:20px}
.transport-page.inv-workspace .tr-form{gap:13px}
.transport-page.inv-workspace .tr-form label{display:grid;gap:7px}
.transport-page.inv-workspace .tr-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:16px}
.transport-page.inv-workspace .tr-filter-trigger{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:9px 15px;border:1px solid #cfe0d1;border-radius:11px;background:#fff;color:#245b39;font-size:12px;font-weight:800;box-shadow:0 3px 10px #214c2d0b}
.transport-page.inv-workspace .tr-filter-trigger:before{content:"";width:7px;height:7px;border-radius:50%;background:#4b9562;box-shadow:0 0 0 4px #e7f2e8}
.transport-filter-dialog{width:min(760px,calc(100% - 18px));max-height:88vh;overflow:auto;border:1px solid #dce8de;border-radius:21px;padding:0;background:#fff;box-shadow:0 28px 90px #102d1c55}
.transport-filter-dialog::backdrop{background:#0d1f1385;backdrop-filter:blur(3px)}
.transport-filter-dialog .tr-dialog-head{position:sticky;top:0;z-index:2;display:flex;justify-content:space-between;align-items:center;padding:17px 20px;background:linear-gradient(110deg,#f0f7f1,#fff);border-bottom:1px solid #e4ede5}
.transport-filter-dialog .tr-dialog-head strong{font-size:16px;color:#1d5033}
.transport-filter-dialog .tr-dialog-head button{width:36px;height:36px;border:0;border-radius:50%;background:#e5efe6;color:#315b3e;font-size:22px}
.transport-filter-dialog .tr-dialog-content{padding:20px}
.transport-filter-dialog form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px;align-items:end}
.transport-filter-dialog form label{display:grid;grid-template-columns:1fr;gap:7px;min-width:0}
.transport-filter-dialog form button,.transport-filter-dialog form a{min-height:42px}
.transport-filter-dialog form a.tr-clear{display:inline-flex;align-items:center;justify-content:center;padding:10px 16px;border:1px solid #b9d4bf;border-radius:10px;background:#f0f7f1;color:#174b32!important;font-size:12px;font-weight:850;text-decoration:none!important;text-align:center}
@media(max-width:700px){.transport-page.inv-workspace .page-heading{align-items:flex-start;flex-direction:column;padding:18px 16px;border-radius:16px}.transport-page.inv-workspace .page-heading>.btn,.transport-page.inv-workspace .page-heading>a.btn{width:100%}.transport-page.inv-workspace .tr-kpis{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}.transport-page.inv-workspace .tr-kpis>div{min-height:88px;padding:13px 12px 12px 15px!important}.transport-page.inv-workspace .tr-kpis strong{font-size:23px!important}.transport-page.inv-workspace .tr-panel{padding:12px!important;border-radius:14px!important}.transport-page.inv-workspace .tr-scroll{border-radius:10px}.transport-page.inv-workspace table{min-width:760px}.transport-page.inv-workspace .tr-dialog{padding:17px;border-radius:17px}.transport-page.inv-workspace .tr-form{grid-template-columns:1fr!important}.transport-filter-dialog{border-radius:17px}.transport-filter-dialog .tr-dialog-content{padding:15px}.transport-filter-dialog form{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){.transport-page.inv-workspace *,.transport-filter-dialog *{transition:none!important;scroll-behavior:auto!important}}
@media print{.transport-page.inv-workspace .tr-toolbar,.transport-page.inv-workspace .tr-filter-trigger,.transport-filter-dialog,.transport-page.inv-workspace .no-print{display:none!important}.transport-page.inv-workspace .tr-panel{break-inside:avoid;box-shadow:none}}
</style>
<script>
(function(){function setup(){document.querySelectorAll('.transport-page').forEach(function(page){page.classList.add('inv-workspace');var heading=page.querySelector('.page-heading');if(!heading)return;
var filter=page.querySelector('form[method="get"]');if(filter&&!filter.dataset.popupReady){filter.dataset.popupReady='1';var dialog=document.createElement('dialog');dialog.className='transport-filter-dialog';var head=document.createElement('div');head.className='tr-dialog-head';head.innerHTML='<strong>Filter this page</strong><button type="button" aria-label="Close filters">×</button>';head.querySelector('button').addEventListener('click',function(){dialog.close()});var content=document.createElement('div');content.className='tr-dialog-content';filter.parentNode.insertBefore(dialog,filter);content.appendChild(filter);dialog.appendChild(head);dialog.appendChild(content);page.appendChild(dialog);filter.querySelectorAll('a.btn-light').forEach(function(a){a.classList.add('tr-clear');if(/^(Clear|Clear filters)$/i.test(a.textContent.trim()))a.textContent='Clear filters'});var trigger=document.createElement('button');trigger.type='button';trigger.className='tr-filter-trigger';trigger.textContent='Filters';trigger.addEventListener('click',function(){dialog.showModal()});heading.appendChild(trigger);dialog.addEventListener('click',function(e){if(e.target===dialog)dialog.close()})}
var stopForm=page.querySelector('form[action="/app/transport/routes/stops/save"]');if(stopForm&&!stopForm.dataset.popupReady){stopForm.dataset.popupReady='1';var stopDialog=document.createElement('dialog');stopDialog.className='tr-dialog';var stopTitle=document.createElement('h2');stopTitle.textContent='Add route stop';stopDialog.appendChild(stopTitle);stopForm.parentNode.insertBefore(stopDialog,stopForm);stopDialog.appendChild(stopForm);page.appendChild(stopDialog);var stopTrigger=document.createElement('button');stopTrigger.type='button';stopTrigger.className='btn';stopTrigger.textContent='Add Stop';var section=stopForm.closest('section.tr-panel');var sectionHead=section&&section.querySelector('.page-heading');if(sectionHead)sectionHead.appendChild(stopTrigger);else if(section)section.insertBefore(stopTrigger,section.firstChild);stopTrigger.addEventListener('click',function(){stopDialog.showModal()})}
})}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);else setup()})();
</script>
"""
    dialog_close_support = """<style>
.ds-modal-close{position:absolute!important;top:12px!important;right:12px!important;z-index:5;display:inline-flex!important;align-items:center!important;justify-content:center!important;width:36px!important;height:36px!important;min-width:36px!important;min-height:36px!important;padding:0!important;border:1px solid #cfe0d2!important;border-radius:50%!important;background:#eaf4ec!important;color:#205a38!important;font:700 24px/1 Arial,sans-serif!important;cursor:pointer!important;box-shadow:0 2px 8px #163b2418!important}
.ds-modal-close:hover{background:#d9ecdd!important;transform:scale(1.04)}
dialog:has(.ds-modal-close){position:relative}
dialog:has(.ds-modal-close)>*:first-child{padding-right:42px}
@media(max-width:560px){.ds-modal-close{top:10px!important;right:10px!important;width:34px!important;height:34px!important}}
</style><script>
(function(){
 function addClose(dialog){
  if(!dialog||dialog.dataset.dsCloseReady==='1')return;
  dialog.dataset.dsCloseReady='1';
  var existing=dialog.querySelector('button[aria-label*="close" i],button[title*="close" i],.lib-close,.inv-dialog-head button,.ps-dialog-close,.fac-dialog-close,.health-dialog-close,.tr-dialog-close,.ds-modal-close');
  if(existing){existing.classList.add('ds-modal-close');if(!existing.getAttribute('aria-label'))existing.setAttribute('aria-label','Close dialog');if(!existing.getAttribute('title'))existing.setAttribute('title','Close');return;}
  var close=document.createElement('button');close.type='button';close.className='ds-modal-close';close.textContent='×';close.setAttribute('aria-label','Close dialog');close.title='Close';close.addEventListener('click',function(){dialog.close()});
  dialog.insertBefore(close,dialog.firstChild);
 }
 function scan(root){(root||document).querySelectorAll('dialog').forEach(addClose)}
 function init(){scan(document);new MutationObserver(function(records){records.forEach(function(record){record.addedNodes.forEach(function(node){if(node.nodeType===1){if(node.matches&&node.matches('dialog'))addClose(node);scan(node)}})})}).observe(document.body,{childList:true,subtree:true});document.addEventListener('click',function(e){var d=e.target.closest&&e.target.closest('dialog');if(d&&e.target===d)d.close()});}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
</script>"""
    return _school_page(request, title, body + shared + dialog_close_support)



def _transport_guard(request, permission="transport.view"):
    sid = _school_session(request)
    if not sid:
        return None, RedirectResponse("/", 303)
    if not _require_permission(request, sid, permission):
        return None, HTMLResponse("You do not have permission to access Transport Management.", 403)
    return sid, None


def _ensure_transport_vehicles(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS transport_vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        registration_no TEXT NOT NULL,
        make_model TEXT DEFAULT '',
        vehicle_type TEXT DEFAULT 'Bus',
        capacity INTEGER NOT NULL DEFAULT 0,
        driver_name TEXT DEFAULT '',
        driver_phone TEXT DEFAULT '',
        insurance_expiry TEXT DEFAULT '',
        inspection_expiry TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Active',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(school_id, registration_no)
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transport_vehicles_school_status ON transport_vehicles(school_id, status)")


@router.get("/app/transport/vehicles", response_class=HTMLResponse)
def transport_vehicle_register(request: Request, q: str = "", status: str = "Active"):
    sid, error = _transport_guard(request)
    if error:
        return error
    con = _db()
    cur = con.cursor()
    _ensure_transport_vehicles(cur)
    con.commit()
    where = ["school_id=?"]
    params = [sid]
    if q.strip():
        term = "%" + q.strip() + "%"
        where.append("(registration_no LIKE ? OR make_model LIKE ? OR driver_name LIKE ? OR driver_phone LIKE ?)")
        params.extend([term] * 4)
    if status in ("Active", "Maintenance", "Inactive"):
        where.append("status=?")
        params.append(status)
    rows = cur.execute(
        "SELECT * FROM transport_vehicles WHERE " + " AND ".join(where) + " ORDER BY registration_no",
        tuple(params),
    ).fetchall()
    totals = cur.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END) AS active, "
        "SUM(CASE WHEN status='Maintenance' THEN 1 ELSE 0 END) AS maintenance "
        "FROM transport_vehicles WHERE school_id=?",
        (sid,),
    ).fetchone()
    rows_html = "".join(
        f"<tr><td><b>{escape(str(x['registration_no'] or ''))}</b><div class='tr-muted'>{escape(str(x['make_model'] or ''))}</div></td>"
        f"<td>{escape(str(x['vehicle_type'] or ''))}</td><td>{int(x['capacity'] or 0)}</td>"
        f"<td>{escape(str(x['driver_name'] or '—'))}<div class='tr-muted'>{escape(str(x['driver_phone'] or ''))}</div></td>"
        f"<td>{escape(str(x['insurance_expiry'] or '—'))}</td><td>{escape(str(x['inspection_expiry'] or '—'))}</td>"
        f"<td><span class='tr-status'>{escape(str(x['status'] or 'Active'))}</span></td>"
        f"<td><button class='btn btn-light' type='button' onclick='editTransportVehicle(this)' "
        f"data-id='{int(x['id'])}' data-reg='{escape(str(x['registration_no'] or ''), quote=True)}' "
        f"data-model='{escape(str(x['make_model'] or ''), quote=True)}' data-type='{escape(str(x['vehicle_type'] or 'Bus'), quote=True)}' "
        f"data-capacity='{int(x['capacity'] or 0)}' data-driver='{escape(str(x['driver_name'] or ''), quote=True)}' "
        f"data-phone='{escape(str(x['driver_phone'] or ''), quote=True)}' data-insurance='{escape(str(x['insurance_expiry'] or ''), quote=True)}' "
        f"data-inspection='{escape(str(x['inspection_expiry'] or ''), quote=True)}' data-status='{escape(str(x['status'] or 'Active'), quote=True)}' "
        f"data-notes='{escape(str(x['notes'] or ''), quote=True)}'>Edit</button></td></tr>"
        for x in rows
    )
    if not rows_html:
        rows_html = "<tr><td colspan='8' class='tr-empty'>No vehicles found. Add the school's first vehicle to begin the register.</td></tr>"
    body = f"""
<div class="page transport-page">
<style>
.transport-page .tr-kpis{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0}}
.transport-page .tr-kpis>div,.transport-page .tr-panel{{background:#fff;border:1px solid #e3ebe5;border-radius:15px;padding:17px}}
.transport-page .tr-kpis span,.transport-page .tr-muted{{display:block;color:#718078;font-size:12px}}
.transport-page .tr-kpis strong{{display:block;font-size:25px;color:#174b35;margin-top:5px}}
.transport-page .tr-toolbar{{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:16px}}
.transport-page label{{display:grid;gap:6px;font-size:12px;color:#53665b;flex:1;min-width:160px}}
.transport-page .tr-toolbar input,.transport-page .tr-toolbar select{{width:100%;min-height:40px;padding:8px 10px;border:1px solid #dce6df;border-radius:9px;background:#fff}}
.transport-page .tr-scroll{{overflow:auto;width:100%}}
.transport-page table{{width:100%;min-width:900px;border-collapse:collapse}}
.transport-page th,.transport-page td{{padding:12px 10px;text-align:left;border-bottom:1px solid #edf1ee;font-size:13px}}
.transport-page th{{color:#607267;background:#f7faf8;font-weight:650}}
.transport-page .tr-status{{display:inline-block;padding:5px 9px;border-radius:20px;background:#e9f4ed;color:#286344;font-size:11px}}
.transport-page .tr-empty{{text-align:center;padding:32px;color:#7b8981}}
.transport-page .tr-dialog{{width:min(760px,94vw);border:0;border-radius:18px;padding:22px;box-shadow:0 20px 70px #10251b44}}
.transport-page .tr-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}
.transport-page .tr-form input,.transport-page .tr-form select,.transport-page .tr-form textarea{{width:100%;min-height:40px;padding:9px;border:1px solid #dce6df;border-radius:9px}}
.transport-page .tr-actions{{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}}
@media(max-width:650px){{.transport-page .tr-kpis{{grid-template-columns:1fr}}.transport-page .tr-form{{grid-template-columns:1fr}}}}
/* Premium sage treatment for route and learner-allocation dialogs */
.tr-allocation-dialog,.tr-route-dialog{{box-sizing:border-box;isolation:isolate;max-height: min(90vh,900px)!important;overflow-x:hidden!important;overflow-y:auto!important;padding:0!important;border:1px solid #b9d2bb!important;border-radius:28px!important;background:linear-gradient(145deg,#f7fbf5 0%,#eaf4e8 48%,#f9fcf7 100%)!important;box-shadow:0 34px 100px #173d285c,0 8px 24px #173d281c!important;scrollbar-width:thin;scrollbar-color:#a9c9ac #edf5eb}}
.tr-allocation-dialog{{width:min(850px,calc(100% - 24px))!important}}
.tr-route-dialog{{width:min(810px,calc(100% - 24px))!important}}
.tr-allocation-dialog::backdrop,.tr-route-dialog::backdrop{{background:rgba(13,35,23,.68);backdrop-filter:blur(7px)}}
.tr-allocation-dialog form,.tr-route-dialog form{{padding:0!important;background:transparent!important}}
.tr-allocation-dialog .tr-allocation-head,.tr-route-dialog .tr-route-head{{position:relative;overflow:hidden;padding:34px 38px 30px;background:radial-gradient(circle at 88% 8%,#ffffffb8 0,transparent 25%),radial-gradient(circle at 4% 110%,#a8cda955 0,transparent 38%),linear-gradient(125deg,#bcd8bd 0%,#d7e9d4 48%,#edf6e9 100%);border-bottom:1px solid #b8d2b9}}
.tr-allocation-dialog .tr-allocation-head:after,.tr-route-dialog .tr-route-head:after{{content:"";position:absolute;right:68px;top:-64px;width:190px;height:190px;border:1px solid #ffffff70;border-radius:50%;box-shadow:0 0 0 22px #ffffff20,0 0 0 46px #ffffff12;pointer-events:none}}
.tr-allocation-dialog .tr-allocation-eyebrow,.tr-route-dialog .tr-route-eyebrow{{position:relative;z-index:1;display:inline-flex;align-items:center;margin:0 0 14px;padding:7px 12px;border:1px solid #a9c8ac;border-radius:999px;background:#ffffffb8;color:#2f6540;font-size:9px;font-weight:900;letter-spacing:1.35px}}
.tr-allocation-dialog .tr-allocation-head h2,.tr-route-dialog .tr-route-head h2{{position:relative;z-index:1;margin:0 58px 8px 0!important;color:#17482f!important;font-size:27px!important;line-height:1.15!important;font-weight:900!important;letter-spacing:-.55px}}
.tr-allocation-dialog .tr-allocation-head p,.tr-route-dialog .tr-route-head p{{position:relative;z-index:1;max-width:570px;margin:0;color:#46664d;font-size:12px;line-height:1.7}}
.tr-allocation-dialog .tr-allocation-close,.tr-route-dialog .tr-route-close{{position:absolute;z-index:3;top:20px;right:22px;display:grid;place-items:center;width:42px;height:42px;padding:0;border:1px solid #a8c5aa;border-radius:14px;background:#ffffffd9;color:#245638;font-size:25px;line-height:1;cursor:pointer;box-shadow:0 4px 12px #214b2b16;transition:transform .18s ease,background .18s ease,box-shadow .18s ease}}
.tr-allocation-dialog .tr-allocation-close:hover,.tr-route-dialog .tr-route-close:hover{{transform:rotate(90deg);background:#fff;box-shadow:0 7px 18px #214b2b25}}
.tr-allocation-dialog .tr-allocation-section,.tr-route-dialog .tr-route-section{{position:relative;margin:18px 25px 0;padding:21px 23px 23px;border:1px solid #d1e2d0;border-radius:19px;background:linear-gradient(135deg,#ffffffed 0%,#f5faf3 100%);box-shadow:0 7px 20px #234e2d0a, inset 0 1px #fff;}}
.tr-allocation-dialog .tr-allocation-section:before,.tr-route-dialog .tr-route-section:before{{content:"";position:absolute;left:0;top:18px;bottom:18px;width:3px;border-radius:0 4px 4px 0;background:linear-gradient(#8fbd94,#c8dfc8)}}
.tr-allocation-dialog .tr-allocation-section h3,.tr-route-dialog .tr-route-section h3{{display:flex;align-items:center;gap:11px;margin:0 0 18px;padding:0 0 13px;border-bottom:1px solid #e5eee3;color:#2b5939;font-size:11px;font-weight:900;letter-spacing:.75px;text-transform:uppercase}}
.tr-allocation-dialog .tr-allocation-section h3 span,.tr-route-dialog .tr-route-section h3 span{{display:grid;flex:0 0 32px;place-items:center;width:32px;height:32px;border:1px solid #b9d5b9;border-radius:11px;background:linear-gradient(145deg,#e5f2e2,#c5dfc3);color:#28603a;font-size:11px;box-shadow:0 3px 8px #285a3512}}
.tr-allocation-dialog .tr-form,.tr-route-dialog .tr-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 18px}}
.tr-allocation-dialog .tr-form label,.tr-route-dialog .tr-form label{{display:grid;align-content:start;gap:8px;min-width:0;color:#3a5d43;font-size:10px;font-weight:900;letter-spacing:.25px}}
.tr-allocation-dialog .tr-form input,.tr-allocation-dialog .tr-form select,.tr-allocation-dialog .tr-form textarea,.tr-route-dialog .tr-form input,.tr-route-dialog .tr-form select,.tr-route-dialog .tr-form textarea{{box-sizing:border-box;width:100%;min-width:0;min-height:47px;padding:11px 13px;border:1px solid #d2e1d1;border-radius:12px;outline:none;background:linear-gradient(180deg,#fff 0%,#f9fcf8 100%);color:#294b34;font-family:inherit;font-size:13px;font-weight:550;box-shadow:inset 0 1px 2px #244b2d08;transition:border-color .18s ease,box-shadow .18s ease,background .18s ease}}
.tr-allocation-dialog .tr-form input::placeholder,.tr-route-dialog .tr-form input::placeholder,.tr-allocation-dialog .tr-form textarea::placeholder,.tr-route-dialog .tr-form textarea::placeholder{{color:#9aa99b;font-weight:450}}
.tr-allocation-dialog .tr-form input:focus,.tr-allocation-dialog .tr-form select:focus,.tr-allocation-dialog .tr-form textarea:focus,.tr-route-dialog .tr-form input:focus,.tr-route-dialog .tr-form select:focus,.tr-route-dialog .tr-form textarea:focus{{border-color:#78a981;background:#fff;box-shadow:0 0 0 3px #8fbd9430,0 3px 10px #244b2d0a}}
.tr-route-dialog .tr-form textarea{{min-height:88px;resize:vertical}}
.tr-allocation-dialog .tr-check-options{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
.tr-allocation-dialog .tr-check-options label{{display:flex;align-items:center;gap:11px;min-width:0;padding:15px 16px;border:1px solid #d2e3d0;border-radius:14px;background:linear-gradient(135deg,#fff,#f2f8f0);color:#365b40;font-size:12px;font-weight:850;box-shadow:0 4px 12px #244b2d08;transition:border-color .18s ease,transform .18s ease,background .18s ease}}
.tr-allocation-dialog .tr-check-options label:has(input:checked){{border-color:#9bc49d;background:linear-gradient(135deg,#f1f8ef,#e3f1e1);color:#245a35}}
.tr-allocation-dialog .tr-check-options label:hover{{transform:translateY(-1px);border-color:#9fc4a1}}
.tr-allocation-dialog .tr-check-options input{{width:18px;height:18px;min-height:18px;margin:0;accent-color:#34794b}}
.tr-allocation-dialog .tr-actions,.tr-route-dialog .tr-actions{{position:sticky;z-index:4;bottom:0;display:flex;justify-content:flex-end;gap:11px;padding:17px 26px 20px;margin:20px 0 0;border-top:1px solid #cbdccb;background:linear-gradient(110deg,#e4f0e1f5,#f8fbf6f7 55%,#dcebd9f5);backdrop-filter:blur(12px)}}
.tr-allocation-dialog .tr-actions .btn,.tr-route-dialog .tr-actions .btn{{min-width:150px;min-height:46px;padding:0 20px;border:1px solid #286c40!important;border-radius:12px!important;background:linear-gradient(135deg,#347c4b,#205d37)!important;color:#fff!important;font-size:12px;font-weight:900;letter-spacing:.2px;box-shadow:0 6px 14px #28683b25;transition:transform .18s ease,box-shadow .18s ease}}
.tr-allocation-dialog .tr-actions .btn:hover,.tr-route-dialog .tr-actions .btn:hover{{transform:translateY(-2px);box-shadow:0 9px 19px #28683b35}}
.tr-allocation-dialog .tr-actions .btn-light,.tr-route-dialog .tr-actions .btn-light{{border:1px solid #c7d9c6!important;background:#ffffffd9!important;color:#426149!important;box-shadow:none!important}}
.tr-allocation-dialog .tr-actions .btn-light:hover,.tr-route-dialog .tr-actions .btn-light:hover{{background:#fff!important;border-color:#9fbea1!important}}
@media(max-width:650px){{.tr-allocation-dialog,.tr-route-dialog{{width:calc(100% - 14px)!important;max-height:94vh!important;border-radius:20px!important}}.tr-allocation-dialog .tr-allocation-head,.tr-route-dialog .tr-route-head{{padding:25px 20px 22px}}.tr-allocation-dialog .tr-allocation-head h2,.tr-route-dialog .tr-route-head h2{{font-size:23px!important}}.tr-allocation-dialog .tr-allocation-close,.tr-route-dialog .tr-route-close{{top:14px;right:14px;width:37px;height:37px}}.tr-allocation-dialog .tr-allocation-section,.tr-route-dialog .tr-route-section{{margin:12px 11px 0;padding:16px 15px 17px;border-radius:15px}}.tr-allocation-dialog .tr-form,.tr-route-dialog .tr-form,.tr-allocation-dialog .tr-check-options{{grid-template-columns:1fr!important}}.tr-allocation-dialog .tr-actions,.tr-route-dialog .tr-actions{{padding:13px 11px 15px;gap:8px}}.tr-allocation-dialog .tr-actions .btn,.tr-route-dialog .tr-actions .btn{{flex:1;min-width:0;padding:0 10px}}
 
/* Record transport event — premium sage popup */
.tr-event-dialog{{box-sizing:border-box;isolation:isolate;width:min(820px,calc(100% - 24px))!important;max-height:min(90vh,900px)!important;overflow-x:hidden!important;overflow-y:auto!important;padding:0!important;border:1px solid #b9d2bb!important;border-radius:28px!important;background:linear-gradient(145deg,#f7fbf5 0%,#eaf4e8 48%,#f9fcf7 100%)!important;box-shadow:0 34px 100px #173d285c,0 8px 24px #173d281c!important;scrollbar-width:thin;scrollbar-color:#a9c9ac #edf5eb}}
.tr-event-dialog::backdrop{{background:rgba(13,35,23,.68);backdrop-filter:blur(7px)}}
.tr-event-dialog form{{padding:0!important;background:transparent!important}}
.tr-event-dialog .tr-event-head{{position:relative;overflow:hidden;padding:34px 38px 30px;background:radial-gradient(circle at 88% 8%,#ffffffb8 0,transparent 25%),radial-gradient(circle at 4% 110%,#a8cda955 0,transparent 38%),linear-gradient(125deg,#bcd8bd 0%,#d7e9d4 48%,#edf6e9 100%);border-bottom:1px solid #b8d2b9}}
.tr-event-dialog .tr-event-head:after{{content:"";position:absolute;right:68px;top:-64px;width:190px;height:190px;border:1px solid #ffffff70;border-radius:50%;box-shadow:0 0 0 22px #ffffff20,0 0 0 46px #ffffff12;pointer-events:none}}
.tr-event-dialog .tr-event-eyebrow{{position:relative;z-index:1;display:inline-flex;align-items:center;margin:0 0 14px;padding:7px 12px;border:1px solid #a9c8ac;border-radius:999px;background:#ffffffb8;color:#2f6540;font-size:9px;font-weight:900;letter-spacing:1.35px}}
.tr-event-dialog .tr-event-head h2{{position:relative;z-index:1;margin:0 58px 8px 0!important;color:#17482f!important;font-size:27px!important;line-height:1.15!important;font-weight:900!important;letter-spacing:-.55px}}
.tr-event-dialog .tr-event-head p{{position:relative;z-index:1;max-width:570px;margin:0;color:#46664d;font-size:12px;line-height:1.7}}
.tr-event-dialog .tr-event-close{{position:absolute;z-index:3;top:20px;right:22px;display:grid;place-items:center;width:42px;height:42px;padding:0;border:1px solid #a8c5aa;border-radius:14px;background:#ffffffd9;color:#245638;font-size:25px;line-height:1;cursor:pointer;box-shadow:0 4px 12px #214b2b16;transition:transform .18s ease,background .18s ease,box-shadow .18s ease}}
.tr-event-dialog .tr-event-close:hover{{transform:rotate(90deg);background:#fff;box-shadow:0 7px 18px #214b2b25}}
.tr-event-dialog .tr-event-section{{position:relative;margin:18px 25px 0;padding:21px 23px 23px;border:1px solid #d1e2d0;border-radius:19px;background:linear-gradient(135deg,#ffffffed 0%,#f5faf3 100%);box-shadow:0 7px 20px #234e2d0a,inset 0 1px #fff}}
.tr-event-dialog .tr-event-section:before{{content:"";position:absolute;left:0;top:18px;bottom:18px;width:3px;border-radius:0 4px 4px 0;background:linear-gradient(#8fbd94,#c8dfc8)}}
.tr-event-dialog .tr-event-section h3{{display:flex;align-items:center;gap:11px;margin:0 0 18px;padding:0 0 13px;border-bottom:1px solid #e5eee3;color:#2b5939;font-size:11px;font-weight:900;letter-spacing:.75px;text-transform:uppercase}}
.tr-event-dialog .tr-event-section h3 span{{display:grid;flex:0 0 32px;place-items:center;width:32px;height:32px;border:1px solid #b9d5b9;border-radius:11px;background:linear-gradient(145deg,#e5f2e2,#c5dfc3);color:#28603a;font-size:11px;box-shadow:0 3px 8px #285a3512}}
.tr-event-dialog .tr-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 18px}}
.tr-event-dialog .tr-form label{{display:grid;align-content:start;gap:8px;min-width:0;color:#3a5d43;font-size:10px;font-weight:900;letter-spacing:.25px}}
.tr-event-dialog .tr-form input,.tr-event-dialog .tr-form select,.tr-event-dialog .tr-form textarea{{box-sizing:border-box;width:100%;min-width:0;min-height:47px;padding:11px 13px;border:1px solid #d2e1d1;border-radius:12px;outline:none;background:linear-gradient(180deg,#fff,#f9fcf8);color:#294b34;font-family:inherit;font-size:13px;font-weight:550;box-shadow:inset 0 1px 2px #244b2d08;transition:border-color .18s ease,box-shadow .18s ease,background .18s ease}}
.tr-event-dialog .tr-form input::placeholder{{color:#9aa99b;font-weight:450}}
.tr-event-dialog .tr-form input:focus,.tr-event-dialog .tr-form select:focus,.tr-event-dialog .tr-form textarea:focus{{border-color:#78a981;background:#fff;box-shadow:0 0 0 3px #8fbd9430,0 3px 10px #244b2d0a}}
.tr-event-dialog .tr-event-actions{{position:sticky;z-index:4;bottom:0;display:flex;justify-content:flex-end;gap:11px;padding:17px 26px 20px;margin:20px 0 0;border-top:1px solid #cbdccb;background:linear-gradient(110deg,#e4f0e1f5,#f8fbf6f7 55%,#dcebd9f5);backdrop-filter:blur(12px)}}
.tr-event-dialog .tr-event-actions .btn{{min-width:155px;min-height:46px;padding:0 20px;border:1px solid #286c40!important;border-radius:12px!important;background:linear-gradient(135deg,#347c4b,#205d37)!important;color:#fff!important;font-size:12px;font-weight:900;letter-spacing:.2px;box-shadow:0 6px 14px #28683b25;transition:transform .18s ease,box-shadow .18s ease}}
.tr-event-dialog .tr-event-actions .btn:hover{{transform:translateY(-2px);box-shadow:0 9px 19px #28683b35}}
.tr-event-dialog .tr-event-actions .btn-light{{border:1px solid #c7d9c6!important;background:#ffffffd9!important;color:#426149!important;box-shadow:none!important}}
.tr-event-dialog .tr-event-actions .btn-light:hover{{background:#fff!important;border-color:#9fbea1!important}}
@media(max-width:650px){{.tr-event-dialog{{width:calc(100% - 14px)!important;max-height:94vh!important;border-radius:20px!important}}.tr-event-dialog .tr-event-head{{padding:25px 20px 22px}}.tr-event-dialog .tr-event-head h2{{font-size:23px!important}}.tr-event-dialog .tr-event-close{{top:14px;right:14px;width:37px;height:37px}}.tr-event-dialog .tr-event-section{{margin:12px 11px 0;padding:16px 15px 17px;border-radius:15px}}.tr-event-dialog .tr-form{{grid-template-columns:1fr!important}}.tr-event-dialog .tr-event-actions{{padding:13px 11px 15px;gap:8px}}.tr-event-dialog .tr-event-actions .btn{{flex:1;min-width:0;padding:0 10px}}
 
.tr-vehicle-dialog{{width:min(780px,calc(100% - 20px))!important;max-height:92vh!important;overflow:auto!important;padding:0!important;border:1px solid #cbdccb!important;border-radius:25px!important;background:linear-gradient(145deg,#eff7ee 0%,#e3f0e2 48%,#f8fbf6 100%)!important;box-shadow:0 28px 90px #173d2852!important;scrollbar-width:thin;scrollbar-color:#a8c4aa #edf4ec}}
.tr-vehicle-dialog::backdrop{{background:rgba(18,39,27,.62);backdrop-filter:blur(5px)}}
.tr-vehicle-dialog form{{padding:0!important;background:transparent!important}}
.tr-vehicle-dialog .tr-vehicle-head{{position:relative;padding:29px 35px 25px;background:radial-gradient(ellipse at 90% 0%,rgba(255,255,255,.58),transparent 43%),linear-gradient(125deg,#c9e0c9,#dcebd9 48%,#eef6eb);border-bottom:1px solid #c8ddc9}}
.tr-vehicle-dialog .tr-vehicle-eyebrow{{display:inline-flex;margin-bottom:12px;padding:7px 12px;border:1px solid #b7d0b9;border-radius:999px;background:#ffffffb8;color:#356847;font-size:9px;font-weight:900;letter-spacing:1.3px}}
.tr-vehicle-dialog .tr-vehicle-head h2{{margin:0 52px 7px 0!important;color:#174b32!important;font-size:25px!important;font-weight:900!important;letter-spacing:-.7px}}
.tr-vehicle-dialog .tr-vehicle-head p{{margin:0;color:#4f6d56;font-size:12px;line-height:1.6}}
.tr-vehicle-dialog .tr-vehicle-close{{position:absolute;top:18px;right:20px;display:grid;place-items:center;width:39px;height:39px;border:1px solid #b6cfb8;border-radius:13px;background:#ffffffd9;color:#245638;font-size:24px;line-height:1;cursor:pointer;box-shadow:0 4px 12px #244e2d16}}
.tr-vehicle-dialog .tr-vehicle-section{{margin:16px 23px 0;padding:18px 20px 20px;border:1px solid #b7cfb8cc;border-radius:17px;background:linear-gradient(135deg,#ffffffdf,#edf6ebdf);box-shadow:0 5px 15px #234e2d0b}}
.tr-vehicle-dialog .tr-vehicle-section h3{{display:flex;align-items:center;gap:10px;margin:0 0 16px;padding-bottom:11px;border-bottom:1px solid #e1ece0;color:#28583a;font-size:11px;font-weight:900;letter-spacing:.6px;text-transform:uppercase}}
.tr-vehicle-dialog .tr-vehicle-section h3 span{{display:grid;place-items:center;width:29px;height:29px;border-radius:10px;background:linear-gradient(145deg,#d9ebd7,#bcd8bc);color:#285b39;font-size:11px}}
.tr-vehicle-dialog .tr-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 17px;padding:0 0 2px}}
.tr-vehicle-dialog .tr-form label{{display:grid;align-content:start;gap:7px;min-width:0;color:#35583d;font-size:11px;font-weight:850}}
.tr-vehicle-dialog .tr-form input,.tr-vehicle-dialog .tr-form select,.tr-vehicle-dialog .tr-form textarea{{box-sizing:border-box;width:100%;min-height:44px;padding:10px 12px;border:1px solid #d0e0d0;border-radius:11px;background:linear-gradient(180deg,#fff,#f9fcf8);color:#294534;font-size:13px;box-shadow:0 2px 5px #21482a09}}
.tr-vehicle-dialog .tr-form textarea{{min-height:76px;resize:vertical}}
.tr-vehicle-dialog .tr-form input:focus,.tr-vehicle-dialog .tr-form select:focus,.tr-vehicle-dialog .tr-form textarea:focus{{outline:0;border-color:#72a77b;box-shadow:0 0 0 3px #6fa3772e}}
.tr-vehicle-dialog .tr-actions{{position:sticky;bottom:0;padding:15px 24px 18px;margin:16px 0 0;border-top:1px solid #cbdccb;background:linear-gradient(110deg,#e1eee0,#f4f8f1 55%,#dcebd9);backdrop-filter:blur(12px)}}
.tr-vehicle-dialog .tr-actions .btn{{min-width:140px;min-height:44px;border-radius:11px;font-weight:850}}
.tr-vehicle-dialog .tr-actions .btn-light{{background:#ffffffd1!important;color:#3c6047!important;border:1px solid #c8dcc9!important}}
@media(max-width:650px){{.tr-vehicle-dialog{{max-height:95vh!important;border-radius:19px!important}}.tr-vehicle-dialog .tr-vehicle-head{{padding:24px 20px 21px}}.tr-vehicle-dialog .tr-vehicle-head h2{{font-size:22px!important}}.tr-vehicle-dialog .tr-vehicle-close{{top:14px;right:14px;width:35px;height:35px}}.tr-vehicle-dialog .tr-vehicle-section{{margin:12px 12px 0;padding:15px}}.tr-vehicle-dialog .tr-form{{grid-template-columns:1fr!important}}.tr-vehicle-dialog .tr-actions{{padding:13px 13px 16px}}.tr-vehicle-dialog .tr-actions .btn{{flex:1;min-width:0}}}}
</style>
  <div class="page-heading">
    <div><div class="lib-eyebrow">TRANSPORT MANAGEMENT / FLEET</div><h1>Vehicle Register</h1>
    <div class="tr-muted">Register school vehicles, seating capacity, assigned drivers and compliance dates.</div></div>
    <button class="btn" type="button" onclick="openTransportVehicle()">Add Vehicle</button>
  </div>
  <div class="tr-kpis">
    <div><span>Registered vehicles</span><strong>{int(totals['total'] or 0)}</strong></div>
    <div><span>Active vehicles</span><strong>{int(totals['active'] or 0)}</strong></div>
    <div><span>Under maintenance</span><strong>{int(totals['maintenance'] or 0)}</strong></div>
  </div>
  <section class="tr-panel">
    <form method="get" class="tr-toolbar">
      <label>Search fleet<input name="q" value="{escape(q, quote=True)}" placeholder="Registration, model, driver or phone"></label>
      <label>Status<select name="status"><option value="Active" {'selected' if status == 'Active' else ''}>Active</option><option value="Maintenance" {'selected' if status == 'Maintenance' else ''}>Maintenance</option><option value="Inactive" {'selected' if status == 'Inactive' else ''}>Inactive</option><option value="All" {'selected' if status == 'All' else ''}>All</option></select></label>
      <button class="btn" type="submit">Apply</button><a class="btn btn-light" href="/app/transport/vehicles">Clear</a>
    </form>
    <div class="tr-scroll"><table><thead><tr><th>Registration / Model</th><th>Type</th><th>Capacity</th><th>Assigned driver</th><th>Insurance expiry</th><th>Inspection expiry</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows_html}</tbody></table></div>
  </section>
</div>
<dialog id="transportVehicleDialog" class="tr-dialog tr-vehicle-dialog"><form method="post" action="/app/transport/vehicles/save" id="transportVehicleForm">
<div class="tr-vehicle-head"><span class="tr-vehicle-eyebrow">TRANSPORT MANAGEMENT · FLEET SETUP</span><button class="tr-vehicle-close" type="button" aria-label="Close vehicle dialog" onclick="document.getElementById('transportVehicleDialog').close()">×</button><h2 id="transportVehicleTitle">Add vehicle</h2><p>Capture the vehicle identity, assigned driver and compliance details for the school fleet.</p></div>
<input type="hidden" name="vehicle_id" id="trVehicleId" value="0">
<section class="tr-vehicle-section"><h3><span>01</span> Vehicle identification</h3><div class="tr-form">
<label>Registration number *<input name="registration_no" id="trReg" required maxlength="40" placeholder="e.g. KDA 123A"></label>
<label>Make / Model<input name="make_model" id="trModel" maxlength="100" placeholder="e.g. Toyota Coaster"></label>
<label>Vehicle type<select name="vehicle_type" id="trType"><option>Bus</option><option>Minibus</option><option>Van</option><option>Car</option><option>Other</option></select></label>
<label>Seating capacity<input type="number" min="0" max="300" name="capacity" id="trCapacity" value="0" placeholder="Number of seats"></label>
</div></section>
<section class="tr-vehicle-section"><h3><span>02</span> Driver assignment</h3><div class="tr-form">
<label>Driver name<input name="driver_name" id="trDriver" maxlength="140" placeholder="Full name of assigned driver"></label>
<label>Driver phone<input name="driver_phone" id="trPhone" maxlength="40" placeholder="Contact number"></label>
</div></section>
<section class="tr-vehicle-section"><h3><span>03</span> Compliance &amp; status</h3><div class="tr-form">
<label>Insurance expiry<input type="date" name="insurance_expiry" id="trInsurance"></label>
<label>Inspection expiry<input type="date" name="inspection_expiry" id="trInspection"></label>
<label>Status<select name="status" id="trStatus"><option>Active</option><option>Maintenance</option><option>Inactive</option></select></label>
</div></section>
<section class="tr-vehicle-section"><h3><span>04</span> Additional information</h3><div class="tr-form">
<label style="grid-column:1/-1">Notes<textarea name="notes" id="trNotes" rows="2" placeholder="Optional vehicle details or maintenance notes"></textarea></label>
</div></section>
<div class="tr-actions"><button class="btn btn-light" type="button" onclick="document.getElementById('transportVehicleDialog').close()">Cancel</button><button class="btn" type="submit">Save Vehicle</button></div>
</form></dialog>
<script>
function openTransportVehicle(){{document.getElementById('transportVehicleForm').reset();document.getElementById('trVehicleId').value='0';document.getElementById('trCapacity').value='0';document.getElementById('transportVehicleTitle').textContent='Add vehicle';document.getElementById('transportVehicleDialog').showModal();}}
function editTransportVehicle(b){{const f=document.getElementById('transportVehicleForm');f.reset();const m={{vehicle_id:'id',registration_no:'reg',make_model:'model',vehicle_type:'type',capacity:'capacity',driver_name:'driver',driver_phone:'phone',insurance_expiry:'insurance',inspection_expiry:'inspection',status:'status',notes:'notes'}};Object.keys(m).forEach(k=>{{const el=f.elements[k];if(el)el.value=b.dataset[m[k]]||'';}});document.getElementById('transportVehicleTitle').textContent='Edit vehicle';document.getElementById('transportVehicleDialog').showModal();}}
</script>
"""
    try:
        return _transport_page(request, "Vehicle Register", body)
    finally:
        con.close()


@router.post("/app/transport/vehicles/save")
def save_transport_vehicle(
    request: Request,
    vehicle_id: int = Form(0),
    registration_no: str = Form(""),
    make_model: str = Form(""),
    vehicle_type: str = Form("Bus"),
    capacity: int = Form(0),
    driver_name: str = Form(""),
    driver_phone: str = Form(""),
    insurance_expiry: str = Form(""),
    inspection_expiry: str = Form(""),
    status: str = Form("Active"),
    notes: str = Form(""),
):
    sid, error = _transport_guard(request, "transport.manage")
    if error:
        return error
    registration_no = registration_no.strip().upper()
    if not registration_no:
        return HTMLResponse("Registration number is required.", 400)
    if capacity < 0 or capacity > 300:
        return HTMLResponse("Enter a valid seating capacity.", 400)
    if vehicle_type not in ("Bus", "Minibus", "Van", "Car", "Other"):
        return HTMLResponse("Invalid vehicle type.", 400)
    if status not in ("Active", "Maintenance", "Inactive"):
        return HTMLResponse("Invalid vehicle status.", 400)
    now = datetime.utcnow().isoformat(timespec="seconds")
    con = _db()
    cur = con.cursor()
    try:
        _ensure_transport_vehicles(cur)
        values = (registration_no, make_model.strip(), vehicle_type, capacity, driver_name.strip(),
                  driver_phone.strip(), insurance_expiry.strip(), inspection_expiry.strip(), status,
                  notes.strip(), now)
        if vehicle_id:
            cur.execute(
                "UPDATE transport_vehicles SET registration_no=?,make_model=?,vehicle_type=?,capacity=?,driver_name=?,driver_phone=?,insurance_expiry=?,inspection_expiry=?,status=?,notes=?,updated_at=? WHERE id=? AND school_id=?",
                values + (vehicle_id, sid),
            )
            if cur.rowcount == 0:
                con.rollback()
                return HTMLResponse("Vehicle record was not found.", 404)
            event = "TRANSPORT_VEHICLE_UPDATED"
        else:
            cur.execute(
                "INSERT INTO transport_vehicles (school_id,registration_no,make_model,vehicle_type,capacity,driver_name,driver_phone,insurance_expiry,inspection_expiry,status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid,) + values[:-1] + (now, now),
            )
            event = "TRANSPORT_VEHICLE_REGISTERED"
        con.commit()
        _audit(sid, event, f"Vehicle {registration_no}")
    except Exception as exc:
        con.rollback()
        message = str(exc).lower()
        if "unique" in message or "duplicate" in message:
            return HTMLResponse("A vehicle with that registration number is already registered.", 409)
        print(f"DAVISCHOOL TRANSPORT VEHICLE SAVE ERROR: {exc!r}", flush=True)
        return HTMLResponse("Vehicle could not be saved. Please try again.", 500)
    finally:
        con.close()
    return RedirectResponse("/app/transport/vehicles", 303)


def _ensure_transport_routes(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS transport_routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        route_name TEXT NOT NULL,
        route_code TEXT NOT NULL,
        direction TEXT NOT NULL DEFAULT 'Both',
        start_point TEXT DEFAULT '',
        end_point TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Active',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(school_id, route_code)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS transport_route_stops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        route_id INTEGER NOT NULL,
        stop_name TEXT NOT NULL,
        stop_order INTEGER NOT NULL DEFAULT 1,
        pickup_time TEXT DEFAULT '',
        dropoff_time TEXT DEFAULT '',
        fare NUMERIC NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'Active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(school_id, route_id, stop_order)
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transport_routes_school_status ON transport_routes(school_id,status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transport_stops_route_order ON transport_route_stops(school_id,route_id,stop_order)")


@router.get("/app/transport/routes", response_class=HTMLResponse)
def transport_routes_register(request: Request, q: str = "", status: str = "Active", route_id: int = 0):
    sid, error = _transport_guard(request)
    if error:
        return error
    con = _db()
    cur = con.cursor()
    _ensure_transport_routes(cur)
    con.commit()
    clauses = ["r.school_id=?"]
    params = [sid]
    if q.strip():
        term = "%" + q.strip() + "%"
        clauses.append("(r.route_name LIKE ? OR r.route_code LIKE ? OR r.start_point LIKE ? OR r.end_point LIKE ?)")
        params.extend([term] * 4)
    if status in ("Active", "Inactive"):
        clauses.append("r.status=?")
        params.append(status)
    routes = cur.execute(
        "SELECT r.*, (SELECT COUNT(*) FROM transport_route_stops s WHERE s.school_id=r.school_id AND s.route_id=r.id) AS stop_count "
        "FROM transport_routes r WHERE " + " AND ".join(clauses) + " ORDER BY r.route_name",
        tuple(params),
    ).fetchall()
    totals = cur.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END) AS active FROM transport_routes WHERE school_id=?",
        (sid,),
    ).fetchone()
    stop_total = cur.execute("SELECT COUNT(*) AS total FROM transport_route_stops WHERE school_id=?", (sid,)).fetchone()
    selected_route = cur.execute(
        "SELECT * FROM transport_routes WHERE id=? AND school_id=?", (route_id, sid)
    ).fetchone() if route_id else None
    stop_rows = cur.execute(
        "SELECT * FROM transport_route_stops WHERE school_id=? AND route_id=? ORDER BY stop_order,id",
        (sid, route_id),
    ).fetchall() if selected_route else []
    route_rows = "".join(
        f"<tr><td><b>{escape(str(r['route_name'] or ''))}</b><div class='tr-muted'>{escape(str(r['route_code'] or ''))}</div></td>"
        f"<td>{escape(str(r['direction'] or 'Both'))}</td><td>{escape(str(r['start_point'] or '—'))} → {escape(str(r['end_point'] or '—'))}</td>"
        f"<td>{int(r['stop_count'] or 0)}</td><td><span class='tr-status'>{escape(str(r['status'] or 'Active'))}</span></td>"
        f"<td><a class='btn btn-light' href='/app/transport/routes?route_id={int(r['id'])}'>Manage stops</a> "
        f"<button class='btn btn-light' type='button' onclick='editTransportRoute(this)' data-id='{int(r['id'])}' "
        f"data-name='{escape(str(r['route_name'] or ''), quote=True)}' data-code='{escape(str(r['route_code'] or ''), quote=True)}' "
        f"data-direction='{escape(str(r['direction'] or 'Both'), quote=True)}' data-start='{escape(str(r['start_point'] or ''), quote=True)}' "
        f"data-end='{escape(str(r['end_point'] or ''), quote=True)}' data-status='{escape(str(r['status'] or 'Active'), quote=True)}' "
        f"data-notes='{escape(str(r['notes'] or ''), quote=True)}'>Edit</button></td></tr>"
        for r in routes
    ) or "<tr><td colspan='6' class='tr-empty'>No routes found. Add the first school transport route.</td></tr>"
    stop_table = "".join(
        f"<tr><td>{int(s['stop_order'] or 0)}</td><td><b>{escape(str(s['stop_name'] or ''))}</b></td>"
        f"<td>{escape(str(s['pickup_time'] or '—'))}</td><td>{escape(str(s['dropoff_time'] or '—'))}</td>"
        f"<td>{float(s['fare'] or 0):.2f}</td><td>{escape(str(s['status'] or 'Active'))}</td></tr>"
        for s in stop_rows
    ) or "<tr><td colspan='6' class='tr-empty'>No stops have been added to this route.</td></tr>"
    selected_panel = ""
    if selected_route:
        selected_panel = f"""
<section class="tr-panel" style="margin-top:18px">
 <div class="page-heading"><div><h2>{escape(str(selected_route['route_name']))} — Stops</h2><div class="tr-muted">Ordered pickup and drop-off points for this route.</div></div></div>
 <form method="post" action="/app/transport/routes/stops/save" class="tr-toolbar">
  <input type="hidden" name="route_id" value="{int(selected_route['id'])}">
  <label>Stop name *<input name="stop_name" required maxlength="140"></label>
  <label>Stop order *<input name="stop_order" type="number" min="1" max="300" value="{len(stop_rows)+1}" required></label>
  <label>Pickup time<input name="pickup_time" type="time"></label>
  <label>Drop-off time<input name="dropoff_time" type="time"></label>
  <label>Fare<input name="fare" type="number" min="0" step="0.01" value="0"></label>
  <button class="btn" type="submit">Add stop</button>
 </form>
 <div class="tr-scroll"><table style="min-width:650px"><thead><tr><th>Order</th><th>Stop</th><th>Pickup</th><th>Drop-off</th><th>Fare</th><th>Status</th></tr></thead><tbody>{stop_table}</tbody></table></div>
</section>"""
    body = f"""
<div class="page transport-page">
<style>
.transport-page .tr-kpis{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0}}
.transport-page .tr-kpis>div,.transport-page .tr-panel{{background:#fff;border:1px solid #e3ebe5;border-radius:15px;padding:17px}}
.transport-page .tr-kpis span,.transport-page .tr-muted{{display:block;color:#718078;font-size:12px}}
.transport-page .tr-kpis strong{{display:block;font-size:25px;color:#174b35;margin-top:5px}}
.transport-page .tr-toolbar{{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:16px}}
.transport-page label{{display:grid;gap:6px;font-size:12px;color:#53665b;flex:1;min-width:130px}}
.transport-page input,.transport-page select{{width:100%;min-height:40px;padding:8px 10px;border:1px solid #dce6df;border-radius:9px;background:#fff}}
.transport-page .tr-scroll{{overflow:auto;width:100%}}
.transport-page table{{width:100%;min-width:760px;border-collapse:collapse}}
.transport-page th,.transport-page td{{padding:12px 10px;text-align:left;border-bottom:1px solid #edf1ee;font-size:13px}}
.transport-page th{{color:#607267;background:#f7faf8;font-weight:650}}
.transport-page .tr-status{{display:inline-block;padding:5px 9px;border-radius:20px;background:#e9f4ed;color:#286344;font-size:11px}}
.transport-page .tr-empty{{text-align:center;padding:28px;color:#7b8981}}
.transport-page .tr-dialog{{width:min(680px,94vw);border:0;border-radius:18px;padding:22px;box-shadow:0 20px 70px #10251b44}}
.transport-page .tr-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}
.transport-page .tr-actions{{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}}
@media(max-width:650px){{.transport-page .tr-kpis{{grid-template-columns:1fr}}.transport-page .tr-form{{grid-template-columns:1fr}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">TRANSPORT MANAGEMENT / ROUTING</div><h1>Routes &amp; Stops</h1><div class="tr-muted">Define school transport routes and arrange pickup and drop-off points in travel order.</div></div><button class="btn" type="button" onclick="openTransportRoute()">Add Route</button></div>
<div class="tr-kpis"><div><span>Registered routes</span><strong>{int(totals['total'] or 0)}</strong></div><div><span>Active routes</span><strong>{int(totals['active'] or 0)}</strong></div><div><span>Registered stops</span><strong>{int(stop_total['total'] or 0)}</strong></div></div>
<section class="tr-panel">
<form method="get" class="tr-toolbar"><label>Search routes<input name="q" value="{escape(q, quote=True)}" placeholder="Route, code or terminal point"></label><label>Status<select name="status"><option value="Active" {'selected' if status=='Active' else ''}>Active</option><option value="Inactive" {'selected' if status=='Inactive' else ''}>Inactive</option><option value="All" {'selected' if status=='All' else ''}>All</option></select></label><button class="btn" type="submit">Apply</button><a class="btn btn-light" href="/app/transport/routes">Clear</a></form>
<div class="tr-scroll"><table><thead><tr><th>Route / Code</th><th>Direction</th><th>Start → End</th><th>Stops</th><th>Status</th><th>Actions</th></tr></thead><tbody>{route_rows}</tbody></table></div>
</section>
{selected_panel}
<dialog id="transportRouteDialog" class="tr-dialog tr-route-dialog"><form method="post" action="/app/transport/routes/save" id="transportRouteForm">
 <div class="tr-route-head"><span class="tr-route-eyebrow">TRANSPORT MANAGEMENT · ROUTE SETUP</span><button class="tr-route-close" type="button" aria-label="Close route dialog" title="Close" onclick="document.getElementById('transportRouteDialog').close()">×</button><h2 id="transportRouteTitle">Add route</h2><p>Set the route identity, travel direction and terminal points for school transport.</p></div>
 <input type="hidden" name="route_id" value="0">
 <section class="tr-route-section"><h3><span>01</span> Route identification</h3><div class="tr-form"><label>Route name *<input name="route_name" required maxlength="140" placeholder="e.g. Mabale – Town Centre"></label><label>Route code *<input name="route_code" required maxlength="40" placeholder="e.g. RT-001"></label></div></section>
 <section class="tr-route-section"><h3><span>02</span> Direction &amp; terminals</h3><div class="tr-form"><label>Direction<select name="direction"><option>Both</option><option>Pickup</option><option>Drop-off</option></select></label><label>Starting point<input name="start_point" maxlength="140" placeholder="Starting terminal or pickup point"></label><label style="grid-column:1/-1">End point<input name="end_point" maxlength="140" placeholder="Final destination or drop-off point"></label></div></section>
 <section class="tr-route-section"><h3><span>03</span> Route status &amp; notes</h3><div class="tr-form"><label>Status<select name="status"><option>Active</option><option>Inactive</option></select></label><label style="grid-column:1/-1">Notes<textarea name="notes" rows="2" maxlength="500" placeholder="Optional route instructions or details"></textarea></label></div></section>
 <div class="tr-actions"><button class="btn btn-light" type="button" onclick="document.getElementById('transportRouteDialog').close()">Cancel</button><button class="btn" type="submit">Save Route</button></div>
 </form></dialog>
</div>
<script>
function openTransportRoute(){{const f=document.getElementById('transportRouteForm');f.reset();f.elements.route_id.value='0';document.getElementById('transportRouteTitle').textContent='Add route';document.getElementById('transportRouteDialog').showModal();}}
function editTransportRoute(b){{const f=document.getElementById('transportRouteForm');f.elements.route_id.value=b.dataset.id;f.elements.route_name.value=b.dataset.name;f.elements.route_code.value=b.dataset.code;f.elements.direction.value=b.dataset.direction;f.elements.start_point.value=b.dataset.start;f.elements.end_point.value=b.dataset.end;f.elements.status.value=b.dataset.status;f.elements.notes.value=b.dataset.notes;document.getElementById('transportRouteTitle').textContent='Edit route';document.getElementById('transportRouteDialog').showModal();}}
</script>
"""
    try:
        return _transport_page(request, "Routes & Stops", body)
    finally:
        con.close()


@router.post("/app/transport/routes/save")
def save_transport_route(
    request: Request,
    route_id: int = Form(0),
    route_name: str = Form(""),
    route_code: str = Form(""),
    direction: str = Form("Both"),
    start_point: str = Form(""),
    end_point: str = Form(""),
    status: str = Form("Active"),
    notes: str = Form(""),
):
    sid, error = _transport_guard(request, "transport.manage")
    if error:
        return error
    route_name, route_code = route_name.strip(), route_code.strip().upper()
    if not route_name or not route_code:
        return HTMLResponse("Route name and route code are required.", 400)
    if direction not in ("Both", "Pickup", "Drop-off") or status not in ("Active", "Inactive"):
        return HTMLResponse("Invalid route direction or status.", 400)
    now = datetime.utcnow().isoformat(timespec="seconds")
    con = _db()
    cur = con.cursor()
    try:
        _ensure_transport_routes(cur)
        vals = (route_name, route_code, direction, start_point.strip(), end_point.strip(), status, notes.strip(), now)
        if route_id:
            cur.execute(
                "UPDATE transport_routes SET route_name=?,route_code=?,direction=?,start_point=?,end_point=?,status=?,notes=?,updated_at=? WHERE id=? AND school_id=?",
                vals + (route_id, sid),
            )
            if cur.rowcount == 0:
                con.rollback()
                return HTMLResponse("Route was not found.", 404)
            event = "TRANSPORT_ROUTE_UPDATED"
        else:
            cur.execute(
                "INSERT INTO transport_routes (school_id,route_name,route_code,direction,start_point,end_point,status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid,) + vals[:-1] + (now, now),
            )
            event = "TRANSPORT_ROUTE_CREATED"
        con.commit()
        _audit(sid, event, f"Route {route_code}")
    except Exception as exc:
        con.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return HTMLResponse("That route code is already in use.", 409)
        print(f"DAVISCHOOL TRANSPORT ROUTE SAVE ERROR: {exc!r}", flush=True)
        return HTMLResponse("Route could not be saved. Please try again.", 500)
    finally:
        con.close()
    return RedirectResponse("/app/transport/routes", 303)


@router.post("/app/transport/routes/stops/save")
def save_transport_route_stop(
    request: Request,
    route_id: int = Form(...),
    stop_name: str = Form(""),
    stop_order: int = Form(1),
    pickup_time: str = Form(""),
    dropoff_time: str = Form(""),
    fare: float = Form(0),
):
    sid, error = _transport_guard(request, "transport.manage")
    if error:
        return error
    stop_name = stop_name.strip()
    if not stop_name or stop_order < 1 or stop_order > 300 or fare < 0:
        return HTMLResponse("Enter a stop name, valid order and non-negative fare.", 400)
    con = _db()
    cur = con.cursor()
    try:
        _ensure_transport_routes(cur)
        route = cur.execute("SELECT id FROM transport_routes WHERE id=? AND school_id=?", (route_id, sid)).fetchone()
        if not route:
            return HTMLResponse("Route was not found.", 404)
        now = datetime.utcnow().isoformat(timespec="seconds")
        cur.execute(
            "INSERT INTO transport_route_stops (school_id,route_id,stop_name,stop_order,pickup_time,dropoff_time,fare,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'Active',?,?)",
            (sid, route_id, stop_name, stop_order, pickup_time.strip(), dropoff_time.strip(), fare, now, now),
        )
        con.commit()
        _audit(sid, "TRANSPORT_ROUTE_STOP_ADDED", f"{stop_name} on route {route_id}")
    except Exception as exc:
        con.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return HTMLResponse("That stop order is already used on this route.", 409)
        print(f"DAVISCHOOL TRANSPORT STOP SAVE ERROR: {exc!r}", flush=True)
        return HTMLResponse("Stop could not be saved. Please try again.", 500)
    finally:
        con.close()
    return RedirectResponse(f"/app/transport/routes?route_id={route_id}", 303)


def _ensure_transport_allocations(cur):
    _ensure_transport_vehicles(cur)
    _ensure_transport_routes(cur)
    cur.execute("""CREATE TABLE IF NOT EXISTS transport_student_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        route_id INTEGER NOT NULL,
        stop_id INTEGER NOT NULL,
        vehicle_id INTEGER,
        effective_from TEXT NOT NULL,
        effective_to TEXT DEFAULT '',
        pickup_required INTEGER NOT NULL DEFAULT 1,
        dropoff_required INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'Active',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transport_alloc_school_status ON transport_student_allocations(school_id,status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transport_alloc_student ON transport_student_allocations(school_id,student_id)")


@router.get("/app/transport/allocations", response_class=HTMLResponse)
def transport_student_allocations(request: Request, q: str = "", status: str = "Active"):
    sid, error = _transport_guard(request)
    if error:
        return error
    con = _db()
    cur = con.cursor()
    try:
        _ensure_transport_allocations(cur)
        con.commit()
        students = cur.execute(
            "SELECT s.id,s.admission_no,s.name,s.status,c.name AS class_name,c.stream "
            "FROM students s LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id "
            "WHERE s.school_id=? AND COALESCE(s.status,'Active') NOT IN ('Graduated','Inactive','Transferred') "
            "ORDER BY s.name LIMIT 600", (sid,)
        ).fetchall()
        routes = cur.execute(
            "SELECT id,route_name,route_code FROM transport_routes WHERE school_id=? AND status='Active' ORDER BY route_name",
            (sid,)
        ).fetchall()
        stops = cur.execute(
            "SELECT s.id,s.route_id,s.stop_name,s.stop_order,r.route_name FROM transport_route_stops s "
            "JOIN transport_routes r ON r.id=s.route_id AND r.school_id=s.school_id "
            "WHERE s.school_id=? AND s.status='Active' AND r.status='Active' ORDER BY r.route_name,s.stop_order",
            (sid,)
        ).fetchall()
        vehicles = cur.execute(
            "SELECT id,registration_no,capacity FROM transport_vehicles WHERE school_id=? AND status='Active' ORDER BY registration_no",
            (sid,)
        ).fetchall()
        clauses = ["a.school_id=?"]
        params = [sid]
        if status in ("Active", "Inactive"):
            clauses.append("a.status=?")
            params.append(status)
        if q.strip():
            term = "%" + q.strip() + "%"
            clauses.append("(s.name LIKE ? OR s.admission_no LIKE ? OR r.route_name LIKE ? OR v.registration_no LIKE ? OR st.stop_name LIKE ?)")
            params.extend([term] * 5)
        rows = cur.execute(
            "SELECT a.*,s.name AS student_name,s.admission_no,c.name AS class_name,c.stream,"
            "r.route_name,st.stop_name,v.registration_no "
            "FROM transport_student_allocations a JOIN students s ON s.id=a.student_id AND s.school_id=a.school_id "
            "LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id "
            "JOIN transport_routes r ON r.id=a.route_id AND r.school_id=a.school_id "
            "JOIN transport_route_stops st ON st.id=a.stop_id AND st.school_id=a.school_id AND st.route_id=a.route_id "
            "LEFT JOIN transport_vehicles v ON v.id=a.vehicle_id AND v.school_id=a.school_id "
            "WHERE " + " AND ".join(clauses) + " ORDER BY a.status,a.updated_at DESC LIMIT 1000",
            tuple(params)
        ).fetchall()
        totals = cur.execute(
            "SELECT COUNT(*) AS total,SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END) AS active "
            "FROM transport_student_allocations WHERE school_id=?", (sid,)
        ).fetchone()
        active_students = cur.execute(
            "SELECT COUNT(*) AS total FROM students WHERE school_id=? AND COALESCE(status,'Active') NOT IN ('Graduated','Inactive','Transferred')",
            (sid,)
        ).fetchone()
        student_options = "".join(
            f"<option value='{int(s['id'])}'>{escape(str(s['admission_no'] or '—'))} · {escape(str(s['name'] or ''))} · {escape(str(s['class_name'] or 'Unassigned'))} {escape(str(s['stream'] or ''))}</option>"
            for s in students
        ) or "<option value=''>No eligible learners found</option>"
        route_options = "".join(
            f"<option value='{int(r['id'])}'>{escape(str(r['route_name']))} ({escape(str(r['route_code']))})</option>" for r in routes
        ) or "<option value=''>No active routes</option>"
        stop_options = "".join(
            f"<option value='{int(s['id'])}' data-route='{int(s['route_id'])}'>{escape(str(s['route_name']))} · {int(s['stop_order'])}. {escape(str(s['stop_name']))}</option>" for s in stops
        ) or "<option value=''>No active stops</option>"
        vehicle_options = "<option value=''>Not assigned</option>" + "".join(
            f"<option value='{int(v['id'])}'>{escape(str(v['registration_no']))} · capacity {int(v['capacity'] or 0)}</option>" for v in vehicles
        )
        table_rows = "".join(
            f"<tr><td><b>{escape(str(a['student_name'] or ''))}</b><div class='tr-muted'>{escape(str(a['admission_no'] or ''))} · {escape(str(a['class_name'] or 'Unassigned'))} {escape(str(a['stream'] or ''))}</div></td>"
            f"<td>{escape(str(a['route_name'] or ''))}<div class='tr-muted'>{escape(str(a['stop_name'] or ''))}</div></td>"
            f"<td>{escape(str(a['registration_no'] or 'Not assigned'))}</td><td>{escape(str(a['effective_from'] or ''))}</td>"
            f"<td>{escape(str(a['effective_to'] or '—'))}</td><td><span class='tr-status'>{escape(str(a['status']))}</span></td>"
            f"<td><button class='btn btn-light' type='button' onclick='editTransportAllocation(this)' data-id='{int(a['id'])}' data-student='{int(a['student_id'])}' data-route='{int(a['route_id'])}' data-stop='{int(a['stop_id'])}' data-vehicle='{int(a['vehicle_id'] or 0)}' data-from='{escape(str(a['effective_from'] or ''),quote=True)}' data-to='{escape(str(a['effective_to'] or ''),quote=True)}' data-pickup='{int(a['pickup_required'] or 0)}' data-dropoff='{int(a['dropoff_required'] or 0)}' data-status='{escape(str(a['status']),quote=True)}' data-notes='{escape(str(a['notes'] or ''),quote=True)}'>Edit</button></td></tr>"
            for a in rows
        ) or "<tr><td colspan='7' class='tr-empty'>No transport allocations match this view.</td></tr>"
        body = f"""
<div class="page transport-page">
<style>
.transport-page .tr-kpis{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0}}
.transport-page .tr-kpis>div,.transport-page .tr-panel{{background:#fff;border:1px solid #e3ebe5;border-radius:15px;padding:17px}}
.transport-page .tr-kpis span,.transport-page .tr-muted{{display:block;color:#718078;font-size:12px}}
.transport-page .tr-kpis strong{{display:block;font-size:25px;color:#174b35;margin-top:5px}}
.transport-page .tr-toolbar{{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:16px}}
.transport-page label{{display:grid;gap:6px;font-size:12px;color:#53665b;flex:1;min-width:150px}}
.transport-page input,.transport-page select,.transport-page textarea{{width:100%;min-height:40px;padding:8px 10px;border:1px solid #dce6df;border-radius:9px;background:#fff}}
.transport-page .tr-scroll{{overflow:auto;width:100%}}.transport-page table{{width:100%;min-width:900px;border-collapse:collapse}}
.transport-page th,.transport-page td{{padding:12px 10px;text-align:left;border-bottom:1px solid #edf1ee;font-size:13px}}
.transport-page th{{color:#607267;background:#f7faf8;font-weight:650}}
.transport-page .tr-status{{display:inline-block;padding:5px 9px;border-radius:20px;background:#e9f4ed;color:#286344;font-size:11px}}
.transport-page .tr-empty{{text-align:center;padding:30px;color:#7b8981}}
.transport-page .tr-dialog{{width:min(760px,94vw);border:0;border-radius:18px;padding:22px;box-shadow:0 20px 70px #10251b44}}
.transport-page .tr-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}
.transport-page .tr-actions{{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}}
@media(max-width:650px){{.transport-page .tr-kpis{{grid-template-columns:1fr}}.transport-page .tr-form{{grid-template-columns:1fr}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">TRANSPORT MANAGEMENT / LEARNERS</div><h1>Student Transport Allocation</h1><div class="tr-muted">Assign eligible learners to active routes, pickup stops and school vehicles, with effective dates.</div></div><button class="btn" type="button" onclick="openTransportAllocation()">Allocate Learner</button></div>
<div class="tr-kpis"><div><span>Eligible learners</span><strong>{int(active_students['total'] or 0)}</strong></div><div><span>Active allocations</span><strong>{int(totals['active'] or 0)}</strong></div><div><span>Total allocation records</span><strong>{int(totals['total'] or 0)}</strong></div></div>
<section class="tr-panel">
<form method="get" class="tr-toolbar"><label>Search allocations<input name="q" value="{escape(q,quote=True)}" placeholder="Learner, admission no., route, stop or vehicle"></label><label>Status<select name="status"><option value="Active" {'selected' if status=='Active' else ''}>Active</option><option value="Inactive" {'selected' if status=='Inactive' else ''}>Inactive</option><option value="All" {'selected' if status=='All' else ''}>All</option></select></label><button class="btn" type="submit">Apply</button><a class="btn btn-light" href="/app/transport/allocations">Clear</a></form>
<div class="tr-scroll"><table><thead><tr><th>Learner</th><th>Route / Stop</th><th>Vehicle</th><th>Effective from</th><th>Effective to</th><th>Status</th><th>Action</th></tr></thead><tbody>{table_rows}</tbody></table></div>
</section>
<dialog id="transportAllocationDialog" class="tr-dialog tr-allocation-dialog"><form method="post" action="/app/transport/allocations/save" id="transportAllocationForm">
<div class="tr-allocation-head"><span class="tr-allocation-eyebrow">TRANSPORT MANAGEMENT · LEARNER SETUP</span><button class="tr-allocation-close" type="button" aria-label="Close allocation dialog" title="Close" onclick="document.getElementById('transportAllocationDialog').close()">×</button><h2 id="transportAllocationTitle">Allocate learner</h2><p>Choose the learner, assign an active route and stop, and set the transport service period.</p></div>
<input type="hidden" name="allocation_id" value="0">
<section class="tr-allocation-section"><h3><span>01</span> Learner &amp; route assignment</h3><div class="tr-form">
<label>Learner *<select name="student_id" required><option value="">Select learner</option>{student_options}</select></label>
<label>Route *<select name="route_id" id="trAllocRoute" required><option value="">Select route</option>{route_options}</select></label>
<label>Pickup / drop-off stop *<select name="stop_id" id="trAllocStop" required><option value="">Select stop</option>{stop_options}</select></label>
<label>Vehicle<select name="vehicle_id">{vehicle_options}</select></label>
</div></section>
<section class="tr-allocation-section"><h3><span>02</span> Allocation period &amp; status</h3><div class="tr-form">
<label>Effective from *<input type="date" name="effective_from" required></label>
<label>Effective to<input type="date" name="effective_to"></label>
<label>Status<select name="status"><option>Active</option><option>Inactive</option></select></label>
</div></section>
<section class="tr-allocation-section"><h3><span>03</span> Pickup &amp; drop-off preferences</h3><div class="tr-check-options">
<label><input type="checkbox" name="pickup_required" value="1" checked> Pickup required</label>
<label><input type="checkbox" name="dropoff_required" value="1" checked> Drop-off required</label>
</div></section>
<section class="tr-allocation-section"><h3><span>04</span> Additional information</h3><div class="tr-form">
<label style="grid-column:1/-1">Notes<input name="notes" maxlength="500" placeholder="Optional learner transport instructions"></label>
</div></section>
<div class="tr-actions"><button class="btn btn-light" type="button" onclick="document.getElementById('transportAllocationDialog').close()">Cancel</button><button class="btn" type="submit">Save Allocation</button></div>
</form></dialog>
</div>
<script>
const trAllocStops=Array.from(document.getElementById('trAllocStop').options).map(o=>({{value:o.value,route:o.dataset.route||''}}));
function filterTransportStops(){{const route=document.getElementById('trAllocRoute').value;const sel=document.getElementById('trAllocStop');Array.from(sel.options).forEach(o=>{{if(!o.value){{o.hidden=false;return;}}o.hidden=!!route&&o.dataset.route!==route;}});if(sel.selectedOptions[0]&&sel.selectedOptions[0].hidden)sel.value='';}}
document.getElementById('trAllocRoute').addEventListener('change',filterTransportStops);
function openTransportAllocation(){{const f=document.getElementById('transportAllocationForm');f.reset();f.elements.allocation_id.value='0';document.getElementById('transportAllocationTitle').textContent='Allocate learner';filterTransportStops();document.getElementById('transportAllocationDialog').showModal();}}
function editTransportAllocation(b){{const f=document.getElementById('transportAllocationForm');f.reset();f.elements.allocation_id.value=b.dataset.id;f.elements.student_id.value=b.dataset.student;f.elements.route_id.value=b.dataset.route;filterTransportStops();f.elements.stop_id.value=b.dataset.stop;f.elements.vehicle_id.value=b.dataset.vehicle;f.elements.effective_from.value=b.dataset.from;f.elements.effective_to.value=b.dataset.to;f.elements.status.value=b.dataset.status;f.elements.notes.value=b.dataset.notes;f.elements.pickup_required.checked=b.dataset.pickup==='1';f.elements.dropoff_required.checked=b.dataset.dropoff==='1';document.getElementById('transportAllocationTitle').textContent='Edit allocation';document.getElementById('transportAllocationDialog').showModal();}}
</script>
"""
        return _transport_page(request, "Student Transport Allocation", body)
    finally:
        con.close()


@router.post("/app/transport/allocations/save")
def save_transport_allocation(
    request: Request,
    allocation_id: int = Form(0),
    student_id: int = Form(...),
    route_id: int = Form(...),
    stop_id: int = Form(...),
    vehicle_id: int = Form(0),
    effective_from: str = Form(""),
    effective_to: str = Form(""),
    pickup_required: str = Form(""),
    dropoff_required: str = Form(""),
    status: str = Form("Active"),
    notes: str = Form(""),
):
    sid, error = _transport_guard(request, "transport.manage")
    if error:
        return error
    if status not in ("Active", "Inactive") or not effective_from.strip():
        return HTMLResponse("Select a valid status and effective start date.", 400)
    if effective_to.strip() and effective_to.strip() < effective_from.strip():
        return HTMLResponse("Effective-to date cannot be earlier than effective-from date.", 400)
    con = _db()
    cur = con.cursor()
    try:
        _ensure_transport_allocations(cur)
        learner = cur.execute(
            "SELECT id FROM students WHERE id=? AND school_id=? AND COALESCE(status,'Active') NOT IN ('Graduated','Inactive','Transferred')",
            (student_id, sid)
        ).fetchone()
        route = cur.execute("SELECT id FROM transport_routes WHERE id=? AND school_id=? AND status='Active'", (route_id, sid)).fetchone()
        stop = cur.execute(
            "SELECT id FROM transport_route_stops WHERE id=? AND route_id=? AND school_id=? AND status='Active'",
            (stop_id, route_id, sid)
        ).fetchone()
        vehicle = cur.execute("SELECT id,capacity FROM transport_vehicles WHERE id=? AND school_id=? AND status='Active'", (vehicle_id, sid)).fetchone() if vehicle_id else None
        if not learner or not route or not stop or (vehicle_id and not vehicle):
            return HTMLResponse("Select a current learner and valid active route, stop and vehicle from this school.", 400)
        if vehicle and int(vehicle["capacity"] or 0) > 0:
            occupied = cur.execute(
                "SELECT COUNT(*) AS n FROM transport_student_allocations WHERE school_id=? AND vehicle_id=? AND status='Active' AND id<>?",
                (sid, vehicle_id, allocation_id)
            ).fetchone()
            if int(occupied["n"] or 0) >= int(vehicle["capacity"]):
                return HTMLResponse("The selected vehicle has reached its registered seating capacity.", 409)
        if status == "Active":
            duplicate = cur.execute(
                "SELECT id FROM transport_student_allocations WHERE school_id=? AND student_id=? AND status='Active' AND id<>? LIMIT 1",
                (sid, student_id, allocation_id)
            ).fetchone()
            if duplicate:
                return HTMLResponse("This learner already has an active transport allocation. Edit the existing record or deactivate it first.", 409)
        now = datetime.utcnow().isoformat(timespec="seconds")
        vals = (student_id, route_id, stop_id, vehicle_id or None, effective_from.strip(), effective_to.strip(),
                1 if pickup_required else 0, 1 if dropoff_required else 0, status, notes.strip(), now)
        if allocation_id:
            cur.execute(
                "UPDATE transport_student_allocations SET student_id=?,route_id=?,stop_id=?,vehicle_id=?,effective_from=?,effective_to=?,pickup_required=?,dropoff_required=?,status=?,notes=?,updated_at=? WHERE id=? AND school_id=?",
                vals + (allocation_id, sid)
            )
            if cur.rowcount == 0:
                con.rollback()
                return HTMLResponse("Allocation record was not found.", 404)
            event = "TRANSPORT_STUDENT_ALLOCATION_UPDATED"
        else:
            cur.execute(
                "INSERT INTO transport_student_allocations (school_id,student_id,route_id,stop_id,vehicle_id,effective_from,effective_to,pickup_required,dropoff_required,status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid,) + vals[:-1] + (now, now)
            )
            event = "TRANSPORT_STUDENT_ALLOCATED"
        con.commit()
        _audit(sid, event, f"Student {student_id} on route {route_id}")
    except Exception as exc:
        con.rollback()
        print(f"DAVISCHOOL TRANSPORT ALLOCATION SAVE ERROR: {exc!r}", flush=True)
        return HTMLResponse("Transport allocation could not be saved. Please check the learner and route details.", 500)
    finally:
        con.close()
    return RedirectResponse("/app/transport/allocations", 303)


def _ensure_transport_trip_logs(cur):
    _ensure_transport_allocations(cur)
    cur.execute("""CREATE TABLE IF NOT EXISTS transport_trip_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        trip_date TEXT NOT NULL,
        trip_period TEXT NOT NULL DEFAULT 'Morning',
        route_id INTEGER,
        vehicle_id INTEGER,
        student_id INTEGER,
        event_type TEXT NOT NULL,
        event_time TEXT DEFAULT '',
        details TEXT DEFAULT '',
        recorded_by TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transport_trip_logs_school_date ON transport_trip_logs(school_id,trip_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transport_trip_logs_school_event ON transport_trip_logs(school_id,event_type)")


@router.get("/app/transport/trip-logs", response_class=HTMLResponse)
def transport_trip_logs(request: Request, q: str = "", date_from: str = "", date_to: str = "", event_type: str = "All"):
    sid, error = _transport_guard(request)
    if error:
        return error
    con = _db()
    cur = con.cursor()
    try:
        _ensure_transport_trip_logs(cur)
        con.commit()
        allocations = cur.execute(
            "SELECT a.student_id,s.name,s.admission_no,c.name AS class_name,c.stream,a.route_id "
            "FROM transport_student_allocations a JOIN students s ON s.id=a.student_id AND s.school_id=a.school_id "
            "LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id "
            "WHERE a.school_id=? AND a.status='Active' ORDER BY s.name LIMIT 800", (sid,)
        ).fetchall()
        routes = cur.execute("SELECT id,route_name FROM transport_routes WHERE school_id=? AND status='Active' ORDER BY route_name", (sid,)).fetchall()
        vehicles = cur.execute("SELECT id,registration_no FROM transport_vehicles WHERE school_id=? AND status='Active' ORDER BY registration_no", (sid,)).fetchall()
        clauses = ["l.school_id=?"]
        params = [sid]
        if date_from.strip():
            clauses.append("l.trip_date>=?")
            params.append(date_from.strip())
        if date_to.strip():
            clauses.append("l.trip_date<=?")
            params.append(date_to.strip())
        valid_events = ("Boarded", "Dropped off", "Missed pickup", "Absent", "Trip departed", "Trip arrived", "Incident")
        if event_type in valid_events:
            clauses.append("l.event_type=?")
            params.append(event_type)
        if q.strip():
            term = "%" + q.strip() + "%"
            clauses.append("(s.name LIKE ? OR s.admission_no LIKE ? OR r.route_name LIKE ? OR v.registration_no LIKE ? OR l.details LIKE ?)")
            params.extend([term] * 5)
        logs = cur.execute(
            "SELECT l.*,s.name AS student_name,s.admission_no,r.route_name,v.registration_no "
            "FROM transport_trip_logs l LEFT JOIN students s ON s.id=l.student_id AND s.school_id=l.school_id "
            "LEFT JOIN transport_routes r ON r.id=l.route_id AND r.school_id=l.school_id "
            "LEFT JOIN transport_vehicles v ON v.id=l.vehicle_id AND v.school_id=l.school_id "
            "WHERE " + " AND ".join(clauses) + " ORDER BY l.trip_date DESC,l.event_time DESC,l.id DESC LIMIT 1000",
            tuple(params)
        ).fetchall()
        summary = cur.execute(
            "SELECT COUNT(*) AS total,SUM(CASE WHEN event_type='Boarded' THEN 1 ELSE 0 END) AS boarded,"
            "SUM(CASE WHEN event_type='Dropped off' THEN 1 ELSE 0 END) AS dropped,"
            "SUM(CASE WHEN event_type='Missed pickup' THEN 1 ELSE 0 END) AS missed,"
            "SUM(CASE WHEN event_type='Incident' THEN 1 ELSE 0 END) AS incidents "
            "FROM transport_trip_logs WHERE school_id=? AND trip_date=?", (sid, datetime.utcnow().date().isoformat())
        ).fetchone()
        learner_options = "<option value=''>Trip-level / no individual learner</option>" + "".join(
            f"<option value='{int(a['student_id'])}' data-route='{int(a['route_id'])}'>{escape(str(a['admission_no'] or '—'))} · {escape(str(a['name'] or ''))} · {escape(str(a['class_name'] or 'Unassigned'))} {escape(str(a['stream'] or ''))}</option>"
            for a in allocations
        )
        route_options = "<option value=''>Not specified</option>" + "".join(
            f"<option value='{int(r['id'])}'>{escape(str(r['route_name']))}</option>" for r in routes
        )
        vehicle_options = "<option value=''>Not specified</option>" + "".join(
            f"<option value='{int(v['id'])}'>{escape(str(v['registration_no']))}</option>" for v in vehicles
        )
        rows_html = "".join(
            f"<tr><td>{escape(str(l['trip_date'] or ''))}<div class='tr-muted'>{escape(str(l['trip_period'] or ''))} · {escape(str(l['event_time'] or 'Time not recorded'))}</div></td>"
            f"<td><b>{escape(str(l['event_type'] or ''))}</b><div class='tr-muted'>{escape(str(l['details'] or ''))}</div></td>"
            f"<td>{escape(str(l['student_name'] or 'Trip-level record'))}<div class='tr-muted'>{escape(str(l['admission_no'] or ''))}</div></td>"
            f"<td>{escape(str(l['route_name'] or '—'))}</td><td>{escape(str(l['registration_no'] or '—'))}</td>"
            f"<td>{escape(str(l['recorded_by'] or '—'))}</td></tr>" for l in logs
        ) or "<tr><td colspan='6' class='tr-empty'>No trip or attendance records match these filters.</td></tr>"
        body = f"""
<div class="page transport-page">
<style>
.transport-page .tr-kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}}
.transport-page .tr-kpis>div,.transport-page .tr-panel{{background:#fff;border:1px solid #e3ebe5;border-radius:15px;padding:16px}}
.transport-page .tr-kpis span,.transport-page .tr-muted{{display:block;color:#718078;font-size:12px}}
.transport-page .tr-kpis strong{{display:block;font-size:24px;color:#174b35;margin-top:5px}}
.transport-page .tr-toolbar{{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:16px}}
.transport-page label{{display:grid;gap:6px;font-size:12px;color:#53665b;flex:1;min-width:145px}}
.transport-page input,.transport-page select,.transport-page textarea{{width:100%;min-height:40px;padding:8px 10px;border:1px solid #dce6df;border-radius:9px;background:#fff}}
.transport-page .tr-scroll{{overflow:auto;width:100%}}.transport-page table{{width:100%;min-width:900px;border-collapse:collapse}}
.transport-page th,.transport-page td{{padding:12px 10px;text-align:left;border-bottom:1px solid #edf1ee;font-size:13px}}
.transport-page th{{color:#607267;background:#f7faf8;font-weight:650}}.transport-page .tr-empty{{text-align:center;padding:30px;color:#7b8981}}
.transport-page .tr-dialog{{width:min(760px,94vw);border:0;border-radius:18px;padding:22px;box-shadow:0 20px 70px #10251b44}}
.transport-page .tr-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}
.transport-page .tr-actions{{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}}
@media(max-width:700px){{.transport-page .tr-kpis{{grid-template-columns:repeat(2,minmax(0,1fr))}}.transport-page .tr-form{{grid-template-columns:1fr}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">TRANSPORT MANAGEMENT / DAILY OPERATIONS</div><h1>Transport Attendance & Trip Logs</h1><div class="tr-muted">Record learner boarding, drop-offs, missed pickups, trip movements and incidents.</div></div><button class="btn" type="button" onclick="document.getElementById('transportTripDialog').showModal()">Record Trip Event</button></div>
<div class="tr-kpis"><div><span>Today's records</span><strong>{int(summary['total'] or 0)}</strong></div><div><span>Learners boarded</span><strong>{int(summary['boarded'] or 0)}</strong></div><div><span>Dropped off</span><strong>{int(summary['dropped'] or 0)}</strong></div><div><span>Missed pickups / incidents</span><strong>{int(summary['missed'] or 0)+int(summary['incidents'] or 0)}</strong></div></div>
<section class="tr-panel">
<form method="get" class="tr-toolbar"><label>Search<input name="q" value="{escape(q,quote=True)}" placeholder="Learner, admission no., route, vehicle or details"></label><label>From<input type="date" name="date_from" value="{escape(date_from,quote=True)}"></label><label>To<input type="date" name="date_to" value="{escape(date_to,quote=True)}"></label><label>Event<select name="event_type"><option value="All">All events</option>{''.join(f"<option {'selected' if event_type==e else ''}>{e}</option>" for e in valid_events)}</select></label><button class="btn" type="submit">Apply</button><a class="btn btn-light" href="/app/transport/trip-logs">Clear</a></form>
<div class="tr-scroll"><table><thead><tr><th>Date / Period</th><th>Event / Details</th><th>Learner</th><th>Route</th><th>Vehicle</th><th>Recorded by</th></tr></thead><tbody>{rows_html}</tbody></table></div>
</section></div>
<dialog id="transportTripDialog" class="tr-dialog tr-event-dialog"><form method="post" action="/app/transport/trip-logs/save">
<div class="tr-event-head"><span class="tr-event-eyebrow">TRANSPORT MANAGEMENT · DAILY OPERATIONS</span><button class="tr-event-close" type="button" aria-label="Close transport event dialog" title="Close" onclick="document.getElementById('transportTripDialog').close()">×</button><h2>Record transport event</h2><p>Capture learner movements, trip activity and incidents with accurate date, time and route details.</p></div>
<section class="tr-event-section"><h3><span>01</span> Event details</h3><div class="tr-form">
<label>Event type *<select name="event_type" required>{''.join(f'<option>{e}</option>' for e in valid_events)}</select></label>
<label>Trip period<select name="trip_period"><option>Morning</option><option>Afternoon</option><option>Other</option></select></label>
<label>Trip date *<input type="date" name="trip_date" value="{datetime.utcnow().date().isoformat()}" required></label>
<label>Event time<input type="time" name="event_time"></label>
</div></section>
<section class="tr-event-section"><h3><span>02</span> Learner &amp; journey</h3><div class="tr-form">
<label>Learner<select name="student_id">{learner_options}</select></label>
<label>Route<select name="route_id">{route_options}</select></label>
<label>Vehicle<select name="vehicle_id">{vehicle_options}</select></label>
</div></section>
<section class="tr-event-section"><h3><span>03</span> Notes &amp; incident details</h3><div class="tr-form">
<label style="grid-column:1/-1">Details / incident notes<input name="details" maxlength="1000" placeholder="Describe the event, incident or any important transport notes"></label>
</div></section>
<div class="tr-event-actions"><button class="btn btn-light" type="button" onclick="document.getElementById('transportTripDialog').close()">Cancel</button><button class="btn" type="submit">Save Event Record</button></div>
</form></dialog>
</div>
"""
        return _transport_page(request, "Transport Attendance & Trip Logs", body)
    finally:
        con.close()


@router.post("/app/transport/trip-logs/save")
def save_transport_trip_log(
    request: Request,
    trip_date: str = Form(""),
    trip_period: str = Form("Morning"),
    event_type: str = Form(""),
    event_time: str = Form(""),
    student_id: int = Form(0),
    route_id: int = Form(0),
    vehicle_id: int = Form(0),
    details: str = Form(""),
):
    sid, error = _transport_guard(request, "transport.manage")
    if error:
        return error
    allowed_events = ("Boarded", "Dropped off", "Missed pickup", "Absent", "Trip departed", "Trip arrived", "Incident")
    if event_type not in allowed_events or trip_period not in ("Morning", "Afternoon", "Other") or len(details) > 1000:
        return HTMLResponse("Please provide a valid trip event and details.", 400)
    try:
        datetime.strptime(trip_date, "%Y-%m-%d")
        if event_time:
            datetime.strptime(event_time, "%H:%M")
    except ValueError:
        return HTMLResponse("Enter a valid trip date and time.", 400)
    con = _db()
    cur = con.cursor()
    try:
        _ensure_transport_trip_logs(cur)
        route = cur.execute("SELECT id FROM transport_routes WHERE id=? AND school_id=? AND status='Active'", (route_id, sid)).fetchone() if route_id else None
        vehicle = cur.execute("SELECT id FROM transport_vehicles WHERE id=? AND school_id=? AND status='Active'", (vehicle_id, sid)).fetchone() if vehicle_id else None
        allocation = cur.execute(
            "SELECT a.student_id,a.route_id FROM transport_student_allocations a JOIN students s ON s.id=a.student_id AND s.school_id=a.school_id "
            "WHERE a.school_id=? AND a.student_id=? AND a.status='Active' AND (a.effective_to='' OR a.effective_to>=?) LIMIT 1",
            (sid, student_id, trip_date)
        ).fetchone() if student_id else None
        if (route_id and not route) or (vehicle_id and not vehicle):
            return HTMLResponse("Select an active route and vehicle belonging to this school.", 400)
        if student_id and not allocation:
            return HTMLResponse("The selected learner has no active transport allocation.", 400)
        if student_id and route_id and int(allocation["route_id"]) != route_id:
            return HTMLResponse("The selected learner is not allocated to this route.", 400)
        actor = ""
        try:
            actor = str(_school_session(request) or "")
        except Exception:
            actor = ""
        now = datetime.utcnow().isoformat(timespec="seconds")
        cur.execute(
            "INSERT INTO transport_trip_logs (school_id,trip_date,trip_period,route_id,vehicle_id,student_id,event_type,event_time,details,recorded_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sid, trip_date, trip_period, route_id or None, vehicle_id or None, student_id or None, event_type, event_time, details.strip(), actor, now)
        )
        con.commit()
        _audit(sid, "TRANSPORT_TRIP_EVENT_RECORDED", f"{event_type} on {trip_date}")
    except Exception as exc:
        con.rollback()
        print(f"DAVISCHOOL TRANSPORT TRIP LOG SAVE ERROR: {exc!r}", flush=True)
        return HTMLResponse("Transport event could not be saved. Please verify the selected records.", 500)
    finally:
        con.close()
    return RedirectResponse("/app/transport/trip-logs", 303)



@router.get("/app/transport/reports", response_class=HTMLResponse)
def transport_reports(request: Request, date_from: str = "", date_to: str = ""):
    sid, error = _transport_guard(request)
    if error:
        return error
    con = _db()
    cur = con.cursor()
    try:
        _ensure_transport_trip_logs(cur)
        con.commit()
        event_where = ["school_id=?"]
        event_params = [sid]
        if date_from.strip():
            event_where.append("trip_date>=?")
            event_params.append(date_from.strip())
        if date_to.strip():
            event_where.append("trip_date<=?")
            event_params.append(date_to.strip())
        event_sql = " AND ".join(event_where)
        fleet = cur.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END) AS active, "
            "SUM(CASE WHEN status='Maintenance' THEN 1 ELSE 0 END) AS maintenance FROM transport_vehicles WHERE school_id=?",
            (sid,)
        ).fetchone()
        route_totals = cur.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END) AS active FROM transport_routes WHERE school_id=?",
            (sid,)
        ).fetchone()
        allocation_total = cur.execute(
            "SELECT COUNT(*) AS total FROM transport_student_allocations WHERE school_id=? AND status='Active'",
            (sid,)
        ).fetchone()
        activity = cur.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN event_type='Boarded' THEN 1 ELSE 0 END) AS boarded, "
            "SUM(CASE WHEN event_type='Dropped off' THEN 1 ELSE 0 END) AS dropped, "
            "SUM(CASE WHEN event_type='Missed pickup' THEN 1 ELSE 0 END) AS missed, "
            "SUM(CASE WHEN event_type='Absent' THEN 1 ELSE 0 END) AS absent, "
            "SUM(CASE WHEN event_type='Incident' THEN 1 ELSE 0 END) AS incidents, "
            "SUM(CASE WHEN event_type='Trip departed' THEN 1 ELSE 0 END) AS departed, "
            "SUM(CASE WHEN event_type='Trip arrived' THEN 1 ELSE 0 END) AS arrived "
            "FROM transport_trip_logs WHERE " + event_sql, tuple(event_params)
        ).fetchone()
        by_event = cur.execute(
            "SELECT event_type,COUNT(*) AS total FROM transport_trip_logs WHERE " + event_sql +
            " GROUP BY event_type ORDER BY total DESC,event_type", tuple(event_params)
        ).fetchall()
        by_route = cur.execute(
            "SELECT r.route_name,r.route_code,COUNT(DISTINCT a.student_id) AS learners,"
            "COUNT(DISTINCT s.id) AS stops,COUNT(DISTINCT l.id) AS events "
            "FROM transport_routes r "
            "LEFT JOIN transport_student_allocations a ON a.school_id=r.school_id AND a.route_id=r.id AND a.status='Active' "
            "LEFT JOIN transport_route_stops s ON s.school_id=r.school_id AND s.route_id=r.id AND s.status='Active' "
            "LEFT JOIN transport_trip_logs l ON l.school_id=r.school_id AND l.route_id=r.id "
            + ("AND l.trip_date>=? " if date_from.strip() else "") +
            ("AND l.trip_date<=? " if date_to.strip() else "") +
            "WHERE r.school_id=? GROUP BY r.id,r.route_name,r.route_code ORDER BY learners DESC,r.route_name",
            tuple(([date_from.strip()] if date_from.strip() else []) + ([date_to.strip()] if date_to.strip() else []) + [sid])
        ).fetchall()
        by_vehicle = cur.execute(
            "SELECT v.registration_no,v.make_model,v.capacity,v.status,COUNT(DISTINCT a.student_id) AS learners,"
            "COUNT(DISTINCT l.id) AS events "
            "FROM transport_vehicles v "
            "LEFT JOIN transport_student_allocations a ON a.school_id=v.school_id AND a.vehicle_id=v.id AND a.status='Active' "
            "LEFT JOIN transport_trip_logs l ON l.school_id=v.school_id AND l.vehicle_id=v.id "
            + ("AND l.trip_date>=? " if date_from.strip() else "") +
            ("AND l.trip_date<=? " if date_to.strip() else "") +
            "WHERE v.school_id=? GROUP BY v.id,v.registration_no,v.make_model,v.capacity,v.status "
            "ORDER BY events DESC,learners DESC,v.registration_no",
            tuple(([date_from.strip()] if date_from.strip() else []) + ([date_to.strip()] if date_to.strip() else []) + [sid])
        ).fetchall()
        recent = cur.execute(
            "SELECT l.trip_date,l.trip_period,l.event_type,l.event_time,l.details,"
            "s.name AS student_name,s.admission_no,r.route_name,v.registration_no "
            "FROM transport_trip_logs l "
            "LEFT JOIN students s ON s.id=l.student_id AND s.school_id=l.school_id "
            "LEFT JOIN transport_routes r ON r.id=l.route_id AND r.school_id=l.school_id "
            "LEFT JOIN transport_vehicles v ON v.id=l.vehicle_id AND v.school_id=l.school_id "
            "WHERE " + event_sql + " ORDER BY l.trip_date DESC,l.event_time DESC,l.id DESC LIMIT 50",
            tuple(event_params)
        ).fetchall()
        event_rows = "".join(
            f"<tr><td>{escape(str(x['event_type'] or ''))}</td><td>{int(x['total'] or 0)}</td></tr>" for x in by_event
        ) or "<tr><td colspan='2' class='tr-empty'>No trip events in this period.</td></tr>"
        route_rows = "".join(
            f"<tr><td><b>{escape(str(x['route_name'] or ''))}</b><div class='tr-muted'>{escape(str(x['route_code'] or ''))}</div></td>"
            f"<td>{int(x['learners'] or 0)}</td><td>{int(x['stops'] or 0)}</td><td>{int(x['events'] or 0)}</td></tr>" for x in by_route
        ) or "<tr><td colspan='4' class='tr-empty'>No routes registered.</td></tr>"
        vehicle_rows = "".join(
            f"<tr><td><b>{escape(str(x['registration_no'] or ''))}</b><div class='tr-muted'>{escape(str(x['make_model'] or ''))}</div></td>"
            f"<td>{escape(str(x['status'] or ''))}</td><td>{int(x['capacity'] or 0)}</td>"
            f"<td>{int(x['learners'] or 0)}</td><td>{int(x['events'] or 0)}</td></tr>" for x in by_vehicle
        ) or "<tr><td colspan='5' class='tr-empty'>No vehicles registered.</td></tr>"
        recent_rows = "".join(
            f"<tr><td>{escape(str(x['trip_date'] or ''))}<div class='tr-muted'>{escape(str(x['trip_period'] or ''))} · {escape(str(x['event_time'] or ''))}</div></td>"
            f"<td><b>{escape(str(x['event_type'] or ''))}</b><div class='tr-muted'>{escape(str(x['details'] or ''))}</div></td>"
            f"<td>{escape(str(x['student_name'] or 'Trip-level record'))}<div class='tr-muted'>{escape(str(x['admission_no'] or ''))}</div></td>"
            f"<td>{escape(str(x['route_name'] or '—'))}</td><td>{escape(str(x['registration_no'] or '—'))}</td></tr>" for x in recent
        ) or "<tr><td colspan='5' class='tr-empty'>No trip records in this period.</td></tr>"
        start_label = escape(date_from or "All dates", quote=True)
        end_label = escape(date_to or "To date", quote=True)
        body = f"""
<div class="page transport-page">
<style>
.transport-page .tr-kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}}
.transport-page .tr-kpis>div,.transport-page .tr-panel{{background:#fff;border:1px solid #e3ebe5;border-radius:15px;padding:16px;margin-bottom:16px}}
.transport-page .tr-kpis span,.transport-page .tr-muted{{display:block;color:#718078;font-size:12px}}
.transport-page .tr-kpis strong{{display:block;font-size:24px;color:#174b35;margin-top:5px}}
.transport-page .tr-toolbar{{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:16px}}
.transport-page label{{display:grid;gap:6px;font-size:12px;color:#53665b;flex:1;min-width:150px}}
.transport-page input{{width:100%;min-height:40px;padding:8px 10px;border:1px solid #dce6df;border-radius:9px;background:#fff}}
.transport-page .tr-scroll{{overflow:auto;width:100%}}.transport-page table{{width:100%;min-width:620px;border-collapse:collapse}}
.transport-page th,.transport-page td{{padding:11px 10px;text-align:left;border-bottom:1px solid #edf1ee;font-size:13px}}
.transport-page th{{color:#607267;background:#f7faf8;font-weight:650}}.transport-page .tr-empty{{text-align:center;padding:25px;color:#7b8981}}
.transport-page .tr-report-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:760px){{.transport-page .tr-kpis{{grid-template-columns:repeat(2,minmax(0,1fr))}}.transport-page .tr-report-grid{{grid-template-columns:1fr}}}}
@media print{{.transport-page .tr-toolbar,.transport-page .no-print{{display:none!important}}.transport-page .tr-panel{{break-inside:avoid;box-shadow:none}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">TRANSPORT MANAGEMENT / ANALYTICS</div><h1>Transport Reports</h1><div class="tr-muted">Fleet, route allocation and trip activity summary.</div></div><button class="btn no-print" type="button" onclick="window.print()">Print / Save PDF</button></div>
<section class="tr-panel no-print"><form method="get" class="tr-toolbar">
<label>Activity from<input type="date" name="date_from" value="{start_label}"></label>
<label>Activity to<input type="date" name="date_to" value="{end_label}"></label>
<button class="btn" type="submit">Apply filters</button><a class="btn btn-light" href="/app/transport/reports">Clear</a>
</form></section>
<div class="tr-kpis">
<div><span>Registered vehicles</span><strong>{int(fleet['total'] or 0)}</strong></div>
<div><span>Active vehicles</span><strong>{int(fleet['active'] or 0)}</strong></div>
<div><span>Active routes</span><strong>{int(route_totals['active'] or 0)}</strong></div>
<div><span>Active learner allocations</span><strong>{int(allocation_total['total'] or 0)}</strong></div>
<div><span>Trip / attendance events</span><strong>{int(activity['total'] or 0)}</strong></div>
<div><span>Learners boarded</span><strong>{int(activity['boarded'] or 0)}</strong></div>
<div><span>Dropped off</span><strong>{int(activity['dropped'] or 0)}</strong></div>
<div><span>Missed pickups / incidents</span><strong>{int(activity['missed'] or 0)+int(activity['incidents'] or 0)}</strong></div>
</div>
<div class="tr-report-grid">
<section class="tr-panel"><h2>Trip activity by event</h2><div class="tr-muted">Filtered period: {start_label} — {end_label}</div><div class="tr-scroll"><table><thead><tr><th>Event type</th><th>Records</th></tr></thead><tbody>{event_rows}</tbody></table></div></section>
<section class="tr-panel"><h2>Route utilisation</h2><div class="tr-muted">Current active learner allocations and activity in the selected period.</div><div class="tr-scroll"><table><thead><tr><th>Route</th><th>Learners</th><th>Stops</th><th>Events</th></tr></thead><tbody>{route_rows}</tbody></table></div></section>
</div>
<section class="tr-panel"><h2>Vehicle utilisation</h2><div class="tr-muted">Current allocations and recorded trip events by vehicle.</div><div class="tr-scroll"><table><thead><tr><th>Vehicle</th><th>Status</th><th>Capacity</th><th>Learners</th><th>Events</th></tr></thead><tbody>{vehicle_rows}</tbody></table></div></section>
<section class="tr-panel"><h2>Recent transport activity</h2><div class="tr-muted">Up to 50 latest records within the selected period.</div><div class="tr-scroll"><table><thead><tr><th>Date / Period</th><th>Event / Details</th><th>Learner</th><th>Route</th><th>Vehicle</th></tr></thead><tbody>{recent_rows}</tbody></table></div></section>
</div>
"""
        return _transport_page(request, "Transport Reports", body)
    finally:
        con.close()
