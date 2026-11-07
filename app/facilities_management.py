from datetime import datetime, date
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.new_ui import _audit, _db, _school_page, _school_session

router = APIRouter()


def _guard(request):
    sid = _school_session(request)
    if not sid:
        return None, RedirectResponse("/", 303)
    if str(request.session.get("role", "")).strip().lower() not in ("school_admin", "registrar"):
        return None, HTMLResponse("Facilities and assets records are restricted to school administrators and registrars.", 403)
    return sid, None


def _schema(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS school_facilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        facility_code TEXT NOT NULL, facility_name TEXT NOT NULL, facility_type TEXT DEFAULT '',
        location TEXT DEFAULT '', capacity INTEGER NOT NULL DEFAULT 0,
        condition_status TEXT NOT NULL DEFAULT 'Good', operational_status TEXT NOT NULL DEFAULT 'Active',
        notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(school_id, facility_code))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS facility_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        room_code TEXT NOT NULL, room_name TEXT NOT NULL, building TEXT DEFAULT '',
        room_type TEXT DEFAULT 'Classroom', capacity INTEGER NOT NULL DEFAULT 0,
        usage_status TEXT NOT NULL DEFAULT 'Available', notes TEXT DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(school_id, room_code))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS facility_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        asset_code TEXT NOT NULL, asset_name TEXT NOT NULL, category TEXT DEFAULT '',
        room_id INTEGER, location TEXT DEFAULT '', condition_status TEXT NOT NULL DEFAULT 'Good',
        asset_status TEXT NOT NULL DEFAULT 'In Use', acquired_on TEXT DEFAULT '',
        purchase_value REAL NOT NULL DEFAULT 0, assigned_to TEXT DEFAULT '', notes TEXT DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(school_id, asset_code))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS facility_maintenance (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        request_no TEXT NOT NULL, facility_id INTEGER, room_id INTEGER, asset_id INTEGER,
        request_date TEXT NOT NULL, reported_by TEXT DEFAULT '', issue TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'Normal', status TEXT NOT NULL DEFAULT 'Open',
        assigned_to TEXT DEFAULT '', scheduled_date TEXT DEFAULT '', completed_date TEXT DEFAULT '',
        action_taken TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(school_id, request_no))""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_facilities_school_status ON school_facilities(school_id, operational_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_facility_rooms_school ON facility_rooms(school_id, usage_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_facility_assets_school ON facility_assets(school_id, asset_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_facility_maintenance_school ON facility_maintenance(school_id, status, request_date)")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _layout(request, title, eyebrow, description, body):
    styles = """<style>
.fac-page{width:100%;max-width:none;display:grid;gap:16px;color:#26372d}
.fac-page .fac-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.fac-page h1{margin:0;color:#174b2b}.fac-page h2{margin:0 0 12px;color:#245638;font-size:17px}
.fac-page p{margin:5px 0 0;color:#718078;font-size:13px;line-height:1.5}
.fac-page .fac-card,.fac-page .fac-kpis>div{background:#fff;border:1px solid #dce9de;border-radius:14px;padding:16px;min-width:0}
.fac-page .fac-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.fac-page .fac-kpis small{display:block;color:#718078;font-size:12px}
.fac-page .fac-kpis strong{display:block;color:#174b35;font-size:24px;margin-top:5px}
.fac-page .fac-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.fac-page label{display:grid;gap:6px;font-size:12px;font-weight:700;color:#52645a;min-width:0}
.fac-page input,.fac-page select,.fac-page textarea{width:100%;min-height:40px;padding:9px;border:1px solid #dce6df;border-radius:9px;background:#fff;color:#26372d;font:inherit}
.fac-page textarea{min-height:70px}.fac-page .wide{grid-column:1/-1}
.fac-page .fac-actions{display:flex;gap:9px;justify-content:flex-end;align-items:center;flex-wrap:wrap;margin-top:12px}
.fac-page .fac-btn{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:9px;background:#176b3a;color:#fff;padding:10px 14px;font-weight:800;font-size:12px;text-decoration:none;cursor:pointer}
.fac-page .fac-btn.light{background:#edf5ef;color:#245638}
.fac-page .fac-toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:12px}
.fac-page .fac-toolbar label{flex:1;min-width:160px}
.fac-page .fac-scroll{width:100%;overflow:auto}
.fac-page table{width:100%;min-width:760px;border-collapse:collapse}
.fac-page th,.fac-page td{padding:10px;text-align:left;vertical-align:top;border-bottom:1px solid #edf1ee;font-size:12px}
.fac-page th{background:#f5f9f6;color:#607267;white-space:nowrap}
.fac-page td small{display:block;color:#718078;margin-top:3px}
.fac-page .fac-pill{display:inline-block;padding:4px 8px;border-radius:20px;background:#edf5ef;color:#245638;font-size:11px;font-weight:800}
.fac-page .fac-empty{text-align:center;padding:26px;color:#718078}
@media(max-width:760px){.fac-page .fac-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.fac-page .fac-form{grid-template-columns:1fr}.fac-page .wide{grid-column:auto}.fac-page .fac-card{padding:12px}}

.fac-page{--fac-forest:#174b32;gap:17px!important;padding-bottom:28px!important}
.fac-page:before{content:"";display:block;height:5px;margin:-2px 0 0;border-radius:99px;background:linear-gradient(90deg,#174b32,#39845a 48%,#b8d8bd);box-shadow:0 2px 8px #174b321c}
.fac-page .fac-head{align-items:center;padding:22px 24px;border:1px solid #dce9de;border-radius:19px;background:linear-gradient(115deg,#f5faf5,#fff 58%,#edf6ee);box-shadow:0 8px 24px #214c2d0b}
.fac-page .fac-head h1{font-size:clamp(25px,3vw,33px);font-weight:800;letter-spacing:-.8px;color:#174b32}
.fac-page .fac-head p{color:#718278;font-size:12px}
.fac-page .fac-kpis{gap:13px!important}
.fac-page .fac-kpis>div{position:relative;overflow:hidden;min-height:96px;padding:17px 18px 15px 20px!important;border:1px solid #e0ebe1!important;border-radius:16px!important;background:linear-gradient(145deg,#fff,#f8fbf8)!important;box-shadow:0 5px 17px #183d2609!important}
.fac-page .fac-kpis>div:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,#367c50,#a6c9a9)}
.fac-page .fac-kpis small{font-size:11px;font-weight:750}.fac-page .fac-kpis strong{color:#1e5b3a;font-size:27px;letter-spacing:-.6px}
.fac-page .fac-card{padding:18px!important;border:1px solid #e1ebe2!important;border-radius:17px!important;box-shadow:0 6px 22px #193d2609!important}
.fac-page .fac-card h2{font-size:15px;font-weight:800;color:#214d34}
.fac-page .fac-scroll{border:1px solid #e5ede6;border-radius:13px;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}
.fac-page table{border-collapse:separate;border-spacing:0}
.fac-page th{padding:13px 14px;background:linear-gradient(180deg,#f2f8f2,#eaf3eb);color:#42634c;font-size:10px;font-weight:800;letter-spacing:.7px;text-transform:uppercase}
.fac-page td{padding:12px 14px;color:#3c5143}
.fac-page tbody tr:nth-child(even){background:#fbfdfb}.fac-page tbody tr:hover{background:#f0f7f1}
.fac-page label{color:#3d5946;font-weight:750}
.fac-page input,.fac-page select,.fac-page textarea{min-height:42px;padding:10px 11px;border:1px solid #dce7de;border-radius:10px;background:#fcfefc}
.fac-page input:focus,.fac-page select:focus,.fac-page textarea:focus{outline:0;border-color:#78a985;box-shadow:0 0 0 3px #e4f1e6}
.fac-page .fac-btn{min-height:40px;padding:9px 15px;border:1px solid #1f5b3b;border-radius:10px;background:linear-gradient(135deg,#205f3e,#317b4d);font-weight:800;transition:all .16s ease}
.fac-page .fac-btn:hover{filter:brightness(1.04);transform:translateY(-1px);box-shadow:0 5px 12px #205f3e20}
.fac-page .fac-btn.light{border:1px solid #b9d4bf;background:#f0f7f1;color:#174b32}
.fac-page .fac-filter-trigger{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:9px 15px;border:1px solid #cfe0d1;border-radius:11px;background:#fff;color:#245b39;font-size:12px;font-weight:800}
.fac-page .fac-filter-trigger:before{content:"";width:7px;height:7px;border-radius:50%;background:#4b9562;box-shadow:0 0 0 4px #e7f2e8}
.fac-filter-dialog,.fac-form-dialog{width:min(760px,calc(100% - 18px));max-height:90vh;overflow:auto;border:1px solid #dce8de;border-radius:21px;padding:0;background:#fff;box-shadow:0 28px 90px #102d1c55}
.fac-filter-dialog::backdrop,.fac-form-dialog::backdrop{background:#0d1f1385;backdrop-filter:blur(3px)}
.fac-filter-dialog .fac-dialog-head{position:sticky;top:0;z-index:2;display:flex;justify-content:space-between;align-items:center;padding:17px 20px;background:linear-gradient(110deg,#f0f7f1,#fff);border-bottom:1px solid #e4ede5}
.fac-filter-dialog .fac-dialog-head strong,.fac-form-dialog h2{font-size:16px;color:#1d5033}
.fac-filter-dialog .fac-dialog-head button{width:36px;height:36px;border:0;border-radius:50%;background:#e5efe6;color:#315b3e;font-size:22px}
.fac-filter-dialog .fac-dialog-content{padding:20px}
.fac-filter-dialog form{display:flex;flex-wrap:wrap;gap:12px;align-items:end}
.fac-filter-dialog form label{flex:1;min-width:150px;display:grid;gap:7px}
.fac-filter-dialog form .fac-btn.light{display:inline-flex;align-items:center;justify-content:center;min-height:42px;text-decoration:none}
.fac-form-dialog{padding:22px}.fac-form-dialog h2{margin:0 0 16px;font-size:20px}
.fac-form-dialog form{display:grid;gap:12px}.fac-form-dialog .fac-form{grid-template-columns:repeat(2,minmax(0,1fr))}
@media(max-width:700px){.fac-page .fac-head{align-items:flex-start;flex-direction:column;padding:18px 16px}.fac-page .fac-head>.fac-btn{width:100%}.fac-page .fac-kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.fac-page .fac-kpis>div{min-height:86px;padding:13px 12px 12px 15px!important}.fac-page .fac-kpis strong{font-size:23px}.fac-page .fac-card{padding:12px!important}.fac-page .fac-scroll{border-radius:10px}.fac-page table{min-width:760px}.fac-filter-dialog{border-radius:17px}.fac-filter-dialog .fac-dialog-content{padding:15px}.fac-form-dialog{padding:17px;border-radius:17px}.fac-form-dialog .fac-form{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){.fac-page *,.fac-filter-dialog *,.fac-form-dialog *{transition:none!important;scroll-behavior:auto!important}}
@media print{.fac-page .fac-filter-trigger,.fac-filter-dialog,.fac-form-dialog,.fac-page .no-print{display:none!important}.fac-page .fac-card{break-inside:avoid;box-shadow:none}}
</style>
<script>
(function(){function setup(){document.querySelectorAll('.fac-page').forEach(function(page){var head=page.querySelector('.fac-head');if(!head)return;
var filter=page.querySelector('form[method="get"]');if(filter&&!filter.dataset.popupReady){filter.dataset.popupReady='1';var dialog=document.createElement('dialog');dialog.className='fac-filter-dialog';var bar=document.createElement('div');bar.className='fac-dialog-head';bar.innerHTML='<strong>Filter this page</strong><button type="button" aria-label="Close filters">×</button>';bar.querySelector('button').addEventListener('click',function(){dialog.close()});var content=document.createElement('div');content.className='fac-dialog-content';filter.parentNode.insertBefore(dialog,filter);content.appendChild(filter);dialog.appendChild(bar);dialog.appendChild(content);page.appendChild(dialog);filter.querySelectorAll('a.fac-btn.light').forEach(function(a){if(/^(Clear|Clear filters)$/i.test(a.textContent.trim()))a.textContent='Clear filters'});var trigger=document.createElement('button');trigger.type='button';trigger.className='fac-filter-trigger';trigger.textContent='Filters';trigger.addEventListener('click',function(){dialog.showModal()});head.appendChild(trigger);dialog.addEventListener('click',function(e){if(e.target===dialog)dialog.close()})}
var entry=page.querySelector('.fac-card form.fac-form');if(entry&&!entry.dataset.popupReady){entry.dataset.popupReady='1';var card=entry.closest('.fac-card');var h=card&&card.querySelector('h2');var title=h?h.textContent.trim():'Add facility or asset record';var modal=document.createElement('dialog');modal.className='fac-form-dialog';var mh=document.createElement('h2');mh.textContent=title;modal.appendChild(mh);entry.parentNode.insertBefore(modal,entry);modal.appendChild(entry);page.appendChild(modal);var add=document.createElement('button');add.type='button';add.className='fac-btn';add.textContent=title;add.addEventListener('click',function(){modal.showModal()});head.appendChild(add)}
})}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);else setup()})();
</script>"""
</style>"""
    return _school_page(request, title, "<div class='page fac-page'><div class='fac-head'><div><div class='lib-eyebrow'>" + escape(eyebrow) + "</div><h1>" + escape(title) + "</h1><p>" + escape(description) + "</p></div></div>" + body + "</div>" + styles)


def _count(cur, table, sid, where=""):
    sql = "SELECT COUNT(*) n FROM " + table + " WHERE school_id=?" + where
    row = cur.execute(sql, (sid,)).fetchone()
    return int(row["n"] or 0)


@router.get("/app/facilities/register", response_class=HTMLResponse)
def facilities_register(request: Request, q: str = "", status: str = "All"):
    sid, denied = _guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        where, params = ["school_id=?"], [sid]
        if q.strip():
            term = "%" + q.strip() + "%"
            where.append("(facility_code LIKE ? OR facility_name LIKE ? OR facility_type LIKE ? OR location LIKE ?)")
            params.extend([term] * 4)
        if status in ("Active", "Inactive", "Under Repair"):
            where.append("operational_status=?")
            params.append(status)
        rows = cur.execute("SELECT * FROM school_facilities WHERE " + " AND ".join(where) + " ORDER BY facility_name", tuple(params)).fetchall()
        total = _count(cur, "school_facilities", sid)
        active = _count(cur, "school_facilities", sid, " AND operational_status='Active'")
        repair = _count(cur, "school_facilities", sid, " AND operational_status='Under Repair'")
        con.commit()
    finally:
        con.close()
    trs = "".join("<tr><td><b>" + escape(str(r["facility_name"] or "")) + "</b><small>" + escape(str(r["facility_code"] or "")) + "</small></td><td>" + escape(str(r["facility_type"] or "—")) + "</td><td>" + escape(str(r["location"] or "—")) + "</td><td>" + str(int(r["capacity"] or 0)) + "</td><td>" + escape(str(r["condition_status"] or "")) + "</td><td><span class='fac-pill'>" + escape(str(r["operational_status"] or "")) + "</span></td></tr>" for r in rows) or "<tr><td colspan='6' class='fac-empty'>No facilities recorded yet.</td></tr>"
    body = """<div class='fac-kpis'><div><small>Registered facilities</small><strong>""" + str(total) + """</strong></div><div><small>Active facilities</small><strong>""" + str(active) + """</strong></div><div><small>Under repair</small><strong>""" + str(repair) + """</strong></div><div><small>Displayed records</small><strong>""" + str(len(rows)) + """</strong></div></div>
<section class='fac-card'><h2>Register a facility</h2><form method='post' action='/app/facilities/register/save' class='fac-form'>
<label>Facility code *<input name='facility_code' required maxlength='40'></label><label>Facility name *<input name='facility_name' required maxlength='160'></label>
<label>Facility type<input name='facility_type' placeholder='Laboratory, library, office, dining hall'></label><label>Location / building<input name='location' maxlength='160'></label>
<label>Capacity<input type='number' name='capacity' min='0' max='100000' value='0'></label><label>Condition<select name='condition_status'><option>Good</option><option>Fair</option><option>Needs Repair</option><option>Unsafe</option></select></label>
<label>Operational status<select name='operational_status'><option>Active</option><option>Under Repair</option><option>Inactive</option></select></label><label class='wide'>Notes<textarea name='notes' maxlength='2000'></textarea></label>
<div class='wide fac-actions'><button class='fac-btn'>Save facility</button></div></form></section>
<section class='fac-card'><form method='get' class='fac-toolbar'><label>Search facilities<input name='q' value='""" + escape(q, quote=True) + """' placeholder='Code, name, type or location'></label><label>Status<select name='status'><option>All</option><option """ + ("selected" if status == "Active" else "") + """>Active</option><option """ + ("selected" if status == "Under Repair" else "") + """>Under Repair</option><option """ + ("selected" if status == "Inactive" else "") + """>Inactive</option></select></label><button class='fac-btn'>Filter</button><a class='fac-btn light' href='/app/facilities/register'>Clear</a></form><div class='fac-scroll'><table><thead><tr><th>Facility / Code</th><th>Type</th><th>Location</th><th>Capacity</th><th>Condition</th><th>Status</th></tr></thead><tbody>""" + trs + """</tbody></table></div></section>"""
    return _layout(request, "Facilities Register", "FACILITIES & ASSETS / FACILITIES", "Maintain a central register of school buildings, facilities, locations, capacities and operational condition.", body)


@router.post("/app/facilities/register/save")
def facility_save(request: Request, facility_code: str = Form(...), facility_name: str = Form(...), facility_type: str = Form(""), location: str = Form(""), capacity: int = Form(0), condition_status: str = Form("Good"), operational_status: str = Form("Active"), notes: str = Form("")):
    sid, denied = _guard(request)
    if denied:
        return denied
    if condition_status not in ("Good", "Fair", "Needs Repair", "Unsafe"):
        condition_status = "Good"
    if operational_status not in ("Active", "Under Repair", "Inactive"):
        operational_status = "Active"
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        now = _now()
        cur.execute("INSERT INTO school_facilities (school_id,facility_code,facility_name,facility_type,location,capacity,condition_status,operational_status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (sid, facility_code.strip()[:40], facility_name.strip()[:160], facility_type.strip()[:100], location.strip()[:160], max(0, capacity), condition_status, operational_status, notes.strip()[:2000], now, now))
        _audit(cur, sid, request, "FACILITY_CREATE", "Registered facility " + facility_code.strip()[:40])
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/facilities/register", 303)


@router.get("/app/facilities/rooms", response_class=HTMLResponse)
def facility_rooms(request: Request, q: str = ""):
    sid, denied = _guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        rows = cur.execute("SELECT * FROM facility_rooms WHERE school_id=? AND (?='' OR room_code LIKE ? OR room_name LIKE ? OR building LIKE ?) ORDER BY building,room_name", (sid, q.strip(), "%" + q.strip() + "%", "%" + q.strip() + "%", "%" + q.strip() + "%")).fetchall()
        total = _count(cur, "facility_rooms", sid)
        available = _count(cur, "facility_rooms", sid, " AND usage_status='Available'")
        con.commit()
    finally:
        con.close()
    trs = "".join("<tr><td><b>" + escape(str(r["room_name"] or "")) + "</b><small>" + escape(str(r["room_code"] or "")) + "</small></td><td>" + escape(str(r["building"] or "—")) + "</td><td>" + escape(str(r["room_type"] or "")) + "</td><td>" + str(int(r["capacity"] or 0)) + "</td><td><span class='fac-pill'>" + escape(str(r["usage_status"] or "")) + "</span></td></tr>" for r in rows) or "<tr><td colspan='5' class='fac-empty'>No rooms or spaces registered yet.</td></tr>"
    body = """<div class='fac-kpis'><div><small>Rooms / spaces</small><strong>""" + str(total) + """</strong></div><div><small>Available</small><strong>""" + str(available) + """</strong></div></div>
<section class='fac-card'><h2>Add classroom or room</h2><form method='post' action='/app/facilities/rooms/save' class='fac-form'>
<label>Room code *<input name='room_code' required maxlength='40'></label><label>Room name *<input name='room_name' required maxlength='140'></label>
<label>Building / block<input name='building' maxlength='120'></label><label>Room type<select name='room_type'><option>Classroom</option><option>Laboratory</option><option>Library</option><option>Office</option><option>Store</option><option>Hall</option><option>Staff Room</option><option>Other</option></select></label>
<label>Capacity<input type='number' name='capacity' min='0' max='10000' value='0'></label><label>Usage status<select name='usage_status'><option>Available</option><option>Allocated</option><option>Closed</option><option>Under Repair</option></select></label>
<label class='wide'>Notes<textarea name='notes' maxlength='1500'></textarea></label><div class='wide fac-actions'><button class='fac-btn'>Save room</button></div></form></section>
<section class='fac-card'><form method='get' class='fac-toolbar'><label>Search rooms<input name='q' value='""" + escape(q, quote=True) + """' placeholder='Room code, name or building'></label><button class='fac-btn'>Search</button></form><div class='fac-scroll'><table><thead><tr><th>Room / Code</th><th>Building</th><th>Type</th><th>Capacity</th><th>Usage</th></tr></thead><tbody>""" + trs + """</tbody></table></div></section>"""
    return _layout(request, "Classrooms & Room Allocation", "FACILITIES & ASSETS / SPACE MANAGEMENT", "Register classrooms and shared spaces, track capacity and record their current use.", body)


@router.post("/app/facilities/rooms/save")
def facility_room_save(request: Request, room_code: str = Form(...), room_name: str = Form(...), building: str = Form(""), room_type: str = Form("Classroom"), capacity: int = Form(0), usage_status: str = Form("Available"), notes: str = Form("")):
    sid, denied = _guard(request)
    if denied:
        return denied
    if usage_status not in ("Available", "Allocated", "Closed", "Under Repair"):
        usage_status = "Available"
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        now = _now()
        cur.execute("INSERT INTO facility_rooms (school_id,room_code,room_name,building,room_type,capacity,usage_status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (sid, room_code.strip()[:40], room_name.strip()[:140], building.strip()[:120], room_type.strip()[:80], max(0, capacity), usage_status, notes.strip()[:1500], now, now))
        _audit(cur, sid, request, "FACILITY_ROOM_CREATE", "Registered room " + room_code.strip()[:40])
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/facilities/rooms", 303)


@router.get("/app/facilities/assets", response_class=HTMLResponse)
def facility_assets(request: Request, q: str = ""):
    sid, denied = _guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        rooms = cur.execute("SELECT id,room_code,room_name FROM facility_rooms WHERE school_id=? ORDER BY room_name", (sid,)).fetchall()
        rows = cur.execute("SELECT a.*,r.room_name,r.room_code FROM facility_assets a LEFT JOIN facility_rooms r ON r.id=a.room_id AND r.school_id=a.school_id WHERE a.school_id=? AND (?='' OR a.asset_code LIKE ? OR a.asset_name LIKE ? OR a.category LIKE ?) ORDER BY a.asset_name", (sid, q.strip(), "%" + q.strip() + "%", "%" + q.strip() + "%", "%" + q.strip() + "%")).fetchall()
        total = _count(cur, "facility_assets", sid)
        in_use = _count(cur, "facility_assets", sid, " AND asset_status='In Use'")
        repair = _count(cur, "facility_assets", sid, " AND asset_status='Under Repair'")
        con.commit()
    finally:
        con.close()
    room_opts = "<option value=''>Not assigned to a room</option>" + "".join("<option value='" + str(int(r["id"])) + "'>" + escape(str(r["room_code"] or "")) + " — " + escape(str(r["room_name"] or "")) + "</option>" for r in rooms)
    trs = "".join("<tr><td><b>" + escape(str(r["asset_name"] or "")) + "</b><small>" + escape(str(r["asset_code"] or "")) + "</small></td><td>" + escape(str(r["category"] or "—")) + "</td><td>" + escape(str(r["room_name"] or r["location"] or "—")) + "</td><td>" + escape(str(r["condition_status"] or "")) + "</td><td><span class='fac-pill'>" + escape(str(r["asset_status"] or "")) + "</span></td><td>" + escape(str(r["assigned_to"] or "—")) + "</td></tr>" for r in rows) or "<tr><td colspan='6' class='fac-empty'>No equipment or furniture recorded yet.</td></tr>"
    body = """<div class='fac-kpis'><div><small>Registered assets</small><strong>""" + str(total) + """</strong></div><div><small>In use</small><strong>""" + str(in_use) + """</strong></div><div><small>Under repair</small><strong>""" + str(repair) + """</strong></div></div>
<section class='fac-card'><h2>Register furniture or equipment</h2><form method='post' action='/app/facilities/assets/save' class='fac-form'>
<label>Asset code *<input name='asset_code' required maxlength='50'></label><label>Asset name *<input name='asset_name' required maxlength='160'></label>
<label>Category<input name='category' placeholder='Furniture, ICT, laboratory, sports'></label><label>Room<select name='room_id'>""" + room_opts + """</select></label>
<label>Other location<input name='location' maxlength='160'></label><label>Condition<select name='condition_status'><option>Good</option><option>Fair</option><option>Needs Repair</option><option>Unserviceable</option></select></label>
<label>Asset status<select name='asset_status'><option>In Use</option><option>In Store</option><option>Under Repair</option><option>Disposed</option></select></label><label>Acquired on<input type='date' name='acquired_on'></label>
<label>Purchase value<input type='number' name='purchase_value' min='0' step='0.01' value='0'></label><label>Assigned to<input name='assigned_to' maxlength='140'></label>
<label class='wide'>Notes<textarea name='notes' maxlength='1500'></textarea></label><div class='wide fac-actions'><button class='fac-btn'>Save asset</button></div></form></section>
<section class='fac-card'><form method='get' class='fac-toolbar'><label>Search assets<input name='q' value='""" + escape(q, quote=True) + """' placeholder='Asset code, name or category'></label><button class='fac-btn'>Search</button></form><div class='fac-scroll'><table><thead><tr><th>Asset / Code</th><th>Category</th><th>Location</th><th>Condition</th><th>Status</th><th>Assigned to</th></tr></thead><tbody>""" + trs + """</tbody></table></div></section>"""
    return _layout(request, "Furniture & Equipment Register", "FACILITIES & ASSETS / ASSET CONTROL", "Track school furniture, equipment, location, condition, custody and acquisition details.", body)


@router.post("/app/facilities/assets/save")
def facility_asset_save(request: Request, asset_code: str = Form(...), asset_name: str = Form(...), category: str = Form(""), room_id: int = Form(0), location: str = Form(""), condition_status: str = Form("Good"), asset_status: str = Form("In Use"), acquired_on: str = Form(""), purchase_value: float = Form(0), assigned_to: str = Form(""), notes: str = Form("")):
    sid, denied = _guard(request)
    if denied:
        return denied
    if condition_status not in ("Good", "Fair", "Needs Repair", "Unserviceable"):
        condition_status = "Good"
    if asset_status not in ("In Use", "In Store", "Under Repair", "Disposed"):
        asset_status = "In Use"
    if acquired_on:
        try:
            date.fromisoformat(acquired_on)
        except ValueError:
            return HTMLResponse("Enter a valid acquisition date.", 400)
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        room_value = None
        if room_id:
            room = cur.execute("SELECT id FROM facility_rooms WHERE id=? AND school_id=?", (room_id, sid)).fetchone()
            if not room:
                return HTMLResponse("Selected room was not found in this school.", 404)
            room_value = room_id
        now = _now()
        cur.execute("INSERT INTO facility_assets (school_id,asset_code,asset_name,category,room_id,location,condition_status,asset_status,acquired_on,purchase_value,assigned_to,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid, asset_code.strip()[:50], asset_name.strip()[:160], category.strip()[:100], room_value, location.strip()[:160], condition_status, asset_status, acquired_on, max(0, purchase_value), assigned_to.strip()[:140], notes.strip()[:1500], now, now))
        _audit(cur, sid, request, "FACILITY_ASSET_CREATE", "Registered asset " + asset_code.strip()[:50])
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/facilities/assets", 303)


@router.get("/app/facilities/maintenance", response_class=HTMLResponse)
def facility_maintenance(request: Request, status: str = "Open"):
    sid, denied = _guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        facilities = cur.execute("SELECT id,facility_name FROM school_facilities WHERE school_id=? ORDER BY facility_name", (sid,)).fetchall()
        rooms = cur.execute("SELECT id,room_name,room_code FROM facility_rooms WHERE school_id=? ORDER BY room_name", (sid,)).fetchall()
        assets = cur.execute("SELECT id,asset_name,asset_code FROM facility_assets WHERE school_id=? ORDER BY asset_name", (sid,)).fetchall()
        where, params = ["m.school_id=?"], [sid]
        if status in ("Open", "In Progress", "Completed", "Cancelled"):
            where.append("m.status=?")
            params.append(status)
        rows = cur.execute("SELECT m.*,f.facility_name,r.room_name,a.asset_name FROM facility_maintenance m LEFT JOIN school_facilities f ON f.id=m.facility_id AND f.school_id=m.school_id LEFT JOIN facility_rooms r ON r.id=m.room_id AND r.school_id=m.school_id LEFT JOIN facility_assets a ON a.id=m.asset_id AND a.school_id=m.school_id WHERE " + " AND ".join(where) + " ORDER BY CASE m.priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 ELSE 2 END,m.request_date DESC,m.id DESC", tuple(params)).fetchall()
        total = _count(cur, "facility_maintenance", sid)
        open_count = _count(cur, "facility_maintenance", sid, " AND status='Open'")
        progress = _count(cur, "facility_maintenance", sid, " AND status='In Progress'")
        con.commit()
    finally:
        con.close()
    def options(rows, label):
        return "<option value='0'>No " + label + " selected</option>" + "".join("<option value='" + str(int(x["id"])) + "'>" + escape(str(x[label] or "")) + "</option>" for x in rows)
    trs = ""
    for r in rows:
        target = r["facility_name"] or r["room_name"] or r["asset_name"] or "General"
        trs += "<tr><td><b>" + escape(str(r["request_no"] or "")) + "</b><small>" + escape(str(r["request_date"] or "")) + "</small></td><td>" + escape(str(target)) + "</td><td>" + escape(str(r["issue"] or "")) + "</td><td>" + escape(str(r["priority"] or "")) + "</td><td><span class='fac-pill'>" + escape(str(r["status"] or "")) + "</span></td><td>" + escape(str(r["assigned_to"] or "—")) + "</td><td><form method='post' action='/app/facilities/maintenance/" + str(int(r["id"])) + "/status' class='fac-actions'><select name='status'><option" + (" selected" if r["status"] == "Open" else "") + ">Open</option><option" + (" selected" if r["status"] == "In Progress" else "") + ">In Progress</option><option" + (" selected" if r["status"] == "Completed" else "") + ">Completed</option><option" + (" selected" if r["status"] == "Cancelled" else "") + ">Cancelled</option></select><button class='fac-btn'>Update</button></form></td></tr>"
    if not trs:
        trs = "<tr><td colspan='7' class='fac-empty'>No maintenance requests match this filter.</td></tr>"
    facility_opts = options(facilities, "facility_name")
    room_opts = "<option value='0'>No room selected</option>" + "".join("<option value='" + str(int(x["id"])) + "'>" + escape(str(x["room_code"] or "")) + " — " + escape(str(x["room_name"] or "")) + "</option>" for x in rooms)
    asset_opts = "<option value='0'>No asset selected</option>" + "".join("<option value='" + str(int(x["id"])) + "'>" + escape(str(x["asset_code"] or "")) + " — " + escape(str(x["asset_name"] or "")) + "</option>" for x in assets)
    body = """<div class='fac-kpis'><div><small>All requests</small><strong>""" + str(total) + """</strong></div><div><small>Open</small><strong>""" + str(open_count) + """</strong></div><div><small>In progress</small><strong>""" + str(progress) + """</strong></div></div>
<section class='fac-card'><h2>Log maintenance request</h2><form method='post' action='/app/facilities/maintenance/save' class='fac-form'>
<label>Request number *<input name='request_no' required maxlength='40' placeholder='e.g. MNT-001'></label><label>Request date *<input type='date' name='request_date' value='""" + date.today().isoformat() + """' required></label>
<label>Facility<select name='facility_id'>""" + facility_opts + """</select></label><label>Room / space<select name='room_id'>""" + room_opts + """</select></label><label>Asset / equipment<select name='asset_id'>""" + asset_opts + """</select></label><label>Reported by<input name='reported_by' maxlength='140'></label>
<label>Priority<select name='priority'><option>Normal</option><option>High</option><option>Urgent</option><option>Low</option></select></label><label>Assigned to<input name='assigned_to' maxlength='140'></label>
<label class='wide'>Problem / work required *<textarea name='issue' required maxlength='2000'></textarea></label><label>Scheduled date<input type='date' name='scheduled_date'></label><div class='wide fac-actions'><button class='fac-btn'>Create request</button></div></form></section>
<section class='fac-card'><form method='get' class='fac-toolbar'><label>Request status<select name='status'><option>Open</option><option """ + ("selected" if status == "In Progress" else "") + """>In Progress</option><option """ + ("selected" if status == "Completed" else "") + """>Completed</option><option """ + ("selected" if status == "Cancelled" else "") + """>Cancelled</option><option """ + ("selected" if status == "All" else "") + """>All</option></select></label><button class='fac-btn'>Filter</button><a class='fac-btn light' href='/app/facilities/maintenance'>Clear</a></form><div class='fac-scroll'><table><thead><tr><th>Request</th><th>Target</th><th>Issue</th><th>Priority</th><th>Status</th><th>Assigned to</th><th>Update status</th></tr></thead><tbody>""" + trs + """</tbody></table></div></section>"""
    return _layout(request, "Maintenance Requests & Work Orders", "FACILITIES & ASSETS / MAINTENANCE", "Log repair needs, assign responsibility, set priority and track work orders through completion.", body)


@router.post("/app/facilities/maintenance/save")
def maintenance_save(request: Request, request_no: str = Form(...), request_date: str = Form(...), facility_id: int = Form(0), room_id: int = Form(0), asset_id: int = Form(0), reported_by: str = Form(""), priority: str = Form("Normal"), assigned_to: str = Form(""), issue: str = Form(...), scheduled_date: str = Form("")):
    sid, denied = _guard(request)
    if denied:
        return denied
    try:
        date.fromisoformat(request_date)
        if scheduled_date:
            date.fromisoformat(scheduled_date)
    except ValueError:
        return HTMLResponse("Enter valid request and scheduled dates.", 400)
    if priority not in ("Low", "Normal", "High", "Urgent"):
        priority = "Normal"
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        for table, value in (("school_facilities", facility_id), ("facility_rooms", room_id), ("facility_assets", asset_id)):
            if value and not cur.execute("SELECT id FROM " + table + " WHERE id=? AND school_id=?", (value, sid)).fetchone():
                return HTMLResponse("Selected facility, room or asset does not belong to this school.", 404)
        now = _now()
        cur.execute("INSERT INTO facility_maintenance (school_id,request_no,facility_id,room_id,asset_id,request_date,reported_by,issue,priority,status,assigned_to,scheduled_date,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,'Open',?,?,?,?)", (sid, request_no.strip()[:40], facility_id or None, room_id or None, asset_id or None, request_date, reported_by.strip()[:140], issue.strip()[:2000], priority, assigned_to.strip()[:140], scheduled_date, now, now))
        _audit(cur, sid, request, "FACILITY_MAINTENANCE_CREATE", "Created maintenance request " + request_no.strip()[:40])
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/facilities/maintenance", 303)


@router.post("/app/facilities/maintenance/{request_id}/status")
def maintenance_status(request: Request, request_id: int, status: str = Form(...)):
    sid, denied = _guard(request)
    if denied:
        return denied
    if status not in ("Open", "In Progress", "Completed", "Cancelled"):
        return HTMLResponse("Invalid maintenance status.", 400)
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        row = cur.execute("SELECT id FROM facility_maintenance WHERE id=? AND school_id=?", (request_id, sid)).fetchone()
        if not row:
            return HTMLResponse("Maintenance request not found.", 404)
        now = _now()
        completed = date.today().isoformat() if status == "Completed" else ""
        cur.execute("UPDATE facility_maintenance SET status=?,completed_date=?,updated_at=? WHERE id=? AND school_id=?", (status, completed, now, request_id, sid))
        _audit(cur, sid, request, "FACILITY_MAINTENANCE_STATUS", "Updated maintenance request %s to %s" % (request_id, status))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/facilities/maintenance?status=All", 303)


@router.get("/app/facilities/history", response_class=HTMLResponse)
def maintenance_history(request: Request, q: str = ""):
    sid, denied = _guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        term = "%" + q.strip() + "%"
        rows = cur.execute("SELECT m.*,f.facility_name,r.room_name,a.asset_name FROM facility_maintenance m LEFT JOIN school_facilities f ON f.id=m.facility_id AND f.school_id=m.school_id LEFT JOIN facility_rooms r ON r.id=m.room_id AND r.school_id=m.school_id LEFT JOIN facility_assets a ON a.id=m.asset_id AND a.school_id=m.school_id WHERE m.school_id=? AND (?='' OR m.request_no LIKE ? OR m.issue LIKE ? OR m.action_taken LIKE ?) ORDER BY CASE WHEN m.status='Completed' THEN 0 ELSE 1 END,m.completed_date DESC,m.request_date DESC", (sid, q.strip(), term, term, term)).fetchall()
        completed = _count(cur, "facility_maintenance", sid, " AND status='Completed'")
        con.commit()
    finally:
        con.close()
    trs = "".join("<tr><td><b>" + escape(str(r["request_no"] or "")) + "</b><small>Raised: " + escape(str(r["request_date"] or "")) + "</small></td><td>" + escape(str(r["facility_name"] or r["room_name"] or r["asset_name"] or "General")) + "</td><td>" + escape(str(r["issue"] or "")) + "</td><td>" + escape(str(r["action_taken"] or "—")) + "</td><td>" + escape(str(r["completed_date"] or "—")) + "</td><td><span class='fac-pill'>" + escape(str(r["status"] or "")) + "</span></td></tr>" for r in rows) or "<tr><td colspan='6' class='fac-empty'>No maintenance history recorded.</td></tr>"
    body = """<div class='fac-kpis'><div><small>Completed work orders</small><strong>""" + str(completed) + """</strong></div><div><small>History records</small><strong>""" + str(len(rows)) + """</strong></div></div><section class='fac-card'><form method='get' class='fac-toolbar'><label>Search work history<input name='q' value='""" + escape(q, quote=True) + """' placeholder='Request number, issue or work performed'></label><button class='fac-btn'>Search</button><a class='fac-btn light' href='/app/facilities/history'>Clear</a></form><div class='fac-scroll'><table><thead><tr><th>Request</th><th>Facility / Asset</th><th>Issue</th><th>Work performed</th><th>Completed</th><th>Status</th></tr></thead><tbody>""" + trs + """</tbody></table></div></section>"""
    return _layout(request, "Repairs & Maintenance History", "FACILITIES & ASSETS / SERVICE HISTORY", "Review work orders, repair outcomes and completion dates for school facilities and equipment.", body)


@router.get("/app/facilities/reports", response_class=HTMLResponse)
def facilities_reports(request: Request):
    sid, denied = _guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        facilities = _count(cur, "school_facilities", sid)
        rooms = _count(cur, "facility_rooms", sid)
        assets = _count(cur, "facility_assets", sid)
        active_assets = _count(cur, "facility_assets", sid, " AND asset_status='In Use'")
        repair_assets = _count(cur, "facility_assets", sid, " AND asset_status='Under Repair'")
        open_jobs = _count(cur, "facility_maintenance", sid, " AND status IN ('Open','In Progress')")
        completed = _count(cur, "facility_maintenance", sid, " AND status='Completed'")
        value_row = cur.execute("SELECT COALESCE(SUM(purchase_value),0) total_value FROM facility_assets WHERE school_id=? AND asset_status<>'Disposed'", (sid,)).fetchone()
        condition_rows = cur.execute("SELECT condition_status,COUNT(*) total FROM facility_assets WHERE school_id=? GROUP BY condition_status ORDER BY condition_status", (sid,)).fetchall()
        con.commit()
    finally:
        con.close()
    conditions = "".join("<tr><td>" + escape(str(r["condition_status"] or "Not specified")) + "</td><td>" + str(int(r["total"] or 0)) + "</td></tr>" for r in condition_rows) or "<tr><td colspan='2' class='fac-empty'>No asset condition data yet.</td></tr>"
    body = """<div class='fac-kpis'><div><small>Facilities</small><strong>""" + str(facilities) + """</strong></div><div><small>Rooms / spaces</small><strong>""" + str(rooms) + """</strong></div><div><small>Assets recorded</small><strong>""" + str(assets) + """</strong></div><div><small>Assets in use</small><strong>""" + str(active_assets) + """</strong></div><div><small>Assets under repair</small><strong>""" + str(repair_assets) + """</strong></div><div><small>Open work orders</small><strong>""" + str(open_jobs) + """</strong></div><div><small>Completed work orders</small><strong>""" + str(completed) + """</strong></div><div><small>Recorded asset value</small><strong>""" + format(float(value_row["total_value"] or 0), ",.2f") + """</strong></div></div>
<section class='fac-card'><h2>Asset condition summary</h2><div class='fac-scroll'><table><thead><tr><th>Condition</th><th>Number of assets</th></tr></thead><tbody>""" + conditions + """</tbody></table></div></section>
<section class='fac-card'><h2>Management overview</h2><p>Use the Facilities Register, Room Allocation, Asset Register and Maintenance Work Orders to keep the figures above current. Asset value is the recorded acquisition value excluding disposed assets.</p></section>"""
    return _layout(request, "Facilities & Assets Reports", "FACILITIES & ASSETS / REPORTING", "Monitor facilities, room capacity records, asset condition and maintenance workload across the school.", body)
