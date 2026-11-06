from datetime import datetime
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.new_ui import _audit, _db, _require_permission, _school_page, _school_session

router = APIRouter()


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
<dialog id="transportVehicleDialog" class="tr-dialog"><form method="post" action="/app/transport/vehicles/save" id="transportVehicleForm">
  <h2 id="transportVehicleTitle">Add vehicle</h2><input type="hidden" name="vehicle_id" id="trVehicleId" value="0">
  <div class="tr-form">
    <label>Registration number *<input name="registration_no" id="trReg" required maxlength="40"></label>
    <label>Make / Model<input name="make_model" id="trModel" maxlength="100"></label>
    <label>Vehicle type<select name="vehicle_type" id="trType"><option>Bus</option><option>Minibus</option><option>Van</option><option>Car</option><option>Other</option></select></label>
    <label>Seating capacity<input type="number" min="0" max="300" name="capacity" id="trCapacity" value="0"></label>
    <label>Driver name<input name="driver_name" id="trDriver" maxlength="140"></label>
    <label>Driver phone<input name="driver_phone" id="trPhone" maxlength="40"></label>
    <label>Insurance expiry<input type="date" name="insurance_expiry" id="trInsurance"></label>
    <label>Inspection expiry<input type="date" name="inspection_expiry" id="trInspection"></label>
    <label>Status<select name="status" id="trStatus"><option>Active</option><option>Maintenance</option><option>Inactive</option></select></label>
    <label>Notes<textarea name="notes" id="trNotes" rows="2"></textarea></label>
  </div>
  <div class="tr-actions"><button class="btn btn-light" type="button" onclick="document.getElementById('transportVehicleDialog').close()">Cancel</button><button class="btn" type="submit">Save Vehicle</button></div>
</form></dialog>
<script>
function openTransportVehicle(){{document.getElementById('transportVehicleForm').reset();document.getElementById('trVehicleId').value='0';document.getElementById('trCapacity').value='0';document.getElementById('transportVehicleTitle').textContent='Add vehicle';document.getElementById('transportVehicleDialog').showModal();}}
function editTransportVehicle(b){{const f=document.getElementById('transportVehicleForm');f.reset();const m={{vehicle_id:'id',registration_no:'reg',make_model:'model',vehicle_type:'type',capacity:'capacity',driver_name:'driver',driver_phone:'phone',insurance_expiry:'insurance',inspection_expiry:'inspection',status:'status',notes:'notes'}};Object.keys(m).forEach(k=>{{const el=f.elements[k];if(el)el.value=b.dataset[m[k]]||'';}});document.getElementById('transportVehicleTitle').textContent='Edit vehicle';document.getElementById('transportVehicleDialog').showModal();}}
</script>
"""
    try:
        return _school_page(request, "Vehicle Register", body)
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
</div>
<dialog id="transportRouteDialog" class="tr-dialog"><form method="post" action="/app/transport/routes/save" id="transportRouteForm"><h2 id="transportRouteTitle">Add route</h2><input type="hidden" name="route_id" value="0"><div class="tr-form">
<label>Route name *<input name="route_name" required maxlength="140"></label><label>Route code *<input name="route_code" required maxlength="40"></label>
<label>Direction<select name="direction"><option>Both</option><option>Pickup</option><option>Drop-off</option></select></label><label>Status<select name="status"><option>Active</option><option>Inactive</option></select></label>
<label>Starting point<input name="start_point" maxlength="140"></label><label>End point<input name="end_point" maxlength="140"></label>
<label style="grid-column:1/-1">Notes<input name="notes" maxlength="500"></label></div>
<div class="tr-actions"><button class="btn btn-light" type="button" onclick="document.getElementById('transportRouteDialog').close()">Cancel</button><button class="btn" type="submit">Save route</button></div></form></dialog>
<script>
function openTransportRoute(){{const f=document.getElementById('transportRouteForm');f.reset();f.elements.route_id.value='0';document.getElementById('transportRouteTitle').textContent='Add route';document.getElementById('transportRouteDialog').showModal();}}
function editTransportRoute(b){{const f=document.getElementById('transportRouteForm');f.elements.route_id.value=b.dataset.id;f.elements.route_name.value=b.dataset.name;f.elements.route_code.value=b.dataset.code;f.elements.direction.value=b.dataset.direction;f.elements.start_point.value=b.dataset.start;f.elements.end_point.value=b.dataset.end;f.elements.status.value=b.dataset.status;f.elements.notes.value=b.dataset.notes;document.getElementById('transportRouteTitle').textContent='Edit route';document.getElementById('transportRouteDialog').showModal();}}
</script>
"""
    try:
        return _school_page(request, "Routes & Stops", body)
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
</section></div>
<dialog id="transportAllocationDialog" class="tr-dialog"><form method="post" action="/app/transport/allocations/save" id="transportAllocationForm">
<h2 id="transportAllocationTitle">Allocate learner</h2><input type="hidden" name="allocation_id" value="0">
<div class="tr-form">
<label>Learner *<select name="student_id" required><option value="">Select learner</option>{student_options}</select></label>
<label>Route *<select name="route_id" id="trAllocRoute" required><option value="">Select route</option>{route_options}</select></label>
<label>Pickup / drop-off stop *<select name="stop_id" id="trAllocStop" required><option value="">Select stop</option>{stop_options}</select></label>
<label>Vehicle<select name="vehicle_id"><option value="0">Not assigned</option>{''.join(vehicle_options.split('>',1)[1:]) if False else ''}</select></label>
<label>Effective from *<input type="date" name="effective_from" required></label>
<label>Effective to<input type="date" name="effective_to"></label>
<label>Status<select name="status"><option>Active</option><option>Inactive</option></select></label>
<label>Notes<input name="notes" maxlength="500"></label>
</div>
<div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:14px"><label style="display:flex;align-items:center;gap:8px"><input type="checkbox" name="pickup_required" value="1" checked style="width:auto;min-height:0">Pickup required</label><label style="display:flex;align-items:center;gap:8px"><input type="checkbox" name="dropoff_required" value="1" checked style="width:auto;min-height:0">Drop-off required</label></div>
<div class="tr-actions"><button class="btn btn-light" type="button" onclick="document.getElementById('transportAllocationDialog').close()">Cancel</button><button class="btn" type="submit">Save Allocation</button></div>
</form></dialog>
<script>
const trAllocStops=Array.from(document.getElementById('trAllocStop').options).map(o=>({{value:o.value,route:o.dataset.route||''}}));
function filterTransportStops(){{const route=document.getElementById('trAllocRoute').value;const sel=document.getElementById('trAllocStop');Array.from(sel.options).forEach(o=>{{if(!o.value){{o.hidden=false;return;}}o.hidden=!!route&&o.dataset.route!==route;}});if(sel.selectedOptions[0]&&sel.selectedOptions[0].hidden)sel.value='';}}
document.getElementById('trAllocRoute').addEventListener('change',filterTransportStops);
function openTransportAllocation(){{const f=document.getElementById('transportAllocationForm');f.reset();f.elements.allocation_id.value='0';document.getElementById('transportAllocationTitle').textContent='Allocate learner';filterTransportStops();document.getElementById('transportAllocationDialog').showModal();}}
function editTransportAllocation(b){{const f=document.getElementById('transportAllocationForm');f.reset();f.elements.allocation_id.value=b.dataset.id;f.elements.student_id.value=b.dataset.student;f.elements.route_id.value=b.dataset.route;filterTransportStops();f.elements.stop_id.value=b.dataset.stop;f.elements.vehicle_id.value=b.dataset.vehicle;f.elements.effective_from.value=b.dataset.from;f.elements.effective_to.value=b.dataset.to;f.elements.status.value=b.dataset.status;f.elements.notes.value=b.dataset.notes;f.elements.pickup_required.checked=b.dataset.pickup==='1';f.elements.dropoff_required.checked=b.dataset.dropoff==='1';document.getElementById('transportAllocationTitle').textContent='Edit allocation';document.getElementById('transportAllocationDialog').showModal();}}
</script>
"""
        return _school_page(request, "Student Transport Allocation", body)
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
