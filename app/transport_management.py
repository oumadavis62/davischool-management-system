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
