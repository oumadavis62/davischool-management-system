from datetime import datetime
from html import escape
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.new_ui import _db, _require_permission, _school_page, _school_session

router = APIRouter()

def _guard(request, permission="inventory.view"):
    sid = _school_session(request)
    if not sid:
        return None, RedirectResponse("/", 303)
    if not _require_permission(request, sid, permission):
        return None, HTMLResponse("You do not have permission to access Inventory & Stores.", 403)
    return sid, None

def _schema(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS inventory_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        item_code TEXT NOT NULL, item_name TEXT NOT NULL, category TEXT DEFAULT '',
        unit TEXT DEFAULT 'Piece', quantity REAL NOT NULL DEFAULT 0,
        reorder_level REAL NOT NULL DEFAULT 0, storage_location TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Active', description TEXT DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(school_id,item_code))""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_items_school_name ON inventory_items(school_id,item_name)")

@router.get("/app/inventory/items", response_class=HTMLResponse)
def inventory_register(request: Request, q: str = "", category: str = "", status: str = "Active"):
    sid, err = _guard(request)
    if err: return err
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        con.commit()
        where, params = ["school_id=?"], [sid]
        if q.strip():
            term = "%" + q.strip() + "%"
            where.append("(item_code LIKE ? OR item_name LIKE ? OR category LIKE ? OR storage_location LIKE ?)")
            params.extend([term] * 4)
        if category.strip():
            where.append("category=?")
            params.append(category.strip())
        if status in ("Active", "Inactive"):
            where.append("status=?")
            params.append(status)
        rows = cur.execute("SELECT * FROM inventory_items WHERE " + " AND ".join(where) + " ORDER BY item_name", tuple(params)).fetchall()
        cats = cur.execute("SELECT DISTINCT category FROM inventory_items WHERE school_id=? AND category<>'' ORDER BY category", (sid,)).fetchall()
        totals = cur.execute("SELECT COUNT(*) total,COALESCE(SUM(quantity),0) units,SUM(CASE WHEN quantity<=reorder_level THEN 1 ELSE 0 END) low FROM inventory_items WHERE school_id=? AND status='Active'", (sid,)).fetchone()
        trs = "".join(
            f"<tr><td><b>{escape(str(x['item_name'] or ''))}</b><small>{escape(str(x['item_code'] or ''))}</small></td><td>{escape(str(x['category'] or '—'))}</td><td>{escape(str(x['unit'] or ''))}</td><td>{float(x['quantity'] or 0):g}</td><td>{float(x['reorder_level'] or 0):g}</td><td>{escape(str(x['storage_location'] or '—'))}</td><td>{escape(str(x['status'] or 'Active'))}</td><td><button class='btn btn-light' type='button' onclick='editInv(this)' data-id='{int(x['id'])}' data-code='{escape(str(x['item_code'] or ''),quote=True)}' data-name='{escape(str(x['item_name'] or ''),quote=True)}' data-category='{escape(str(x['category'] or ''),quote=True)}' data-unit='{escape(str(x['unit'] or 'Piece'),quote=True)}' data-qty='{float(x['quantity'] or 0):g}' data-reorder='{float(x['reorder_level'] or 0):g}' data-location='{escape(str(x['storage_location'] or ''),quote=True)}' data-status='{escape(str(x['status'] or 'Active'),quote=True)}' data-description='{escape(str(x['description'] or ''),quote=True)}'>Edit</button></td></tr>" for x in rows
        ) or "<tr><td colspan='8'>No inventory items recorded yet.</td></tr>"
        options = "".join(f"<option value='{escape(str(x['category'] or ''),quote=True)}'>{escape(str(x['category'] or ''))}</option>" for x in cats)
        body = f"""
<div class="page inventory-page"><style>
.inventory-page .stats{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0}}
.inventory-page .stats>div,.inventory-page .panel{{background:#fff;border:1px solid #e3ebe5;border-radius:14px;padding:16px}}
.inventory-page .stats span,.inventory-page small{{display:block;color:#718078;font-size:12px}}.inventory-page .stats strong{{font-size:25px;color:#174b35}}
.inventory-page .toolbar{{display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:15px}}.inventory-page label{{display:grid;gap:6px;flex:1;min-width:145px;font-size:12px}}
.inventory-page input,.inventory-page select,.inventory-page textarea{{width:100%;min-height:40px;padding:8px;border:1px solid #dce6df;border-radius:9px;background:#fff}}
.inventory-page .scroll{{overflow:auto;width:100%}}.inventory-page table{{width:100%;min-width:850px;border-collapse:collapse}}.inventory-page th,.inventory-page td{{padding:11px 10px;text-align:left;border-bottom:1px solid #edf1ee;font-size:13px}}
.inventory-page th{{background:#f7faf8;color:#607267}}.inventory-page dialog{{width:min(720px,94vw);border:0;border-radius:16px;padding:22px}}
.inventory-page .fields{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.inventory-page .actions{{display:flex;justify-content:flex-end;gap:10px;margin-top:16px}}
@media(max-width:650px){{.inventory-page .stats,.inventory-page .fields{{grid-template-columns:1fr}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">INVENTORY &amp; STORES / STOCK CONTROL</div><h1>Inventory Register</h1><div>Register supplies and equipment, track stock levels and identify items due for replenishment.</div></div><button class="btn" type="button" onclick="openInv()">Add Inventory Item</button></div>
<div class="stats"><div><span>Active items</span><strong>{int(totals['total'] or 0)}</strong></div><div><span>Total stock units</span><strong>{float(totals['units'] or 0):g}</strong></div><div><span>At / below reorder level</span><strong>{int(totals['low'] or 0)}</strong></div></div>
<section class="panel"><form method="get" class="toolbar"><label>Search<input name="q" value="{escape(q,quote=True)}" placeholder="Code, name, category or location"></label><label>Category<select name="category"><option value="">All categories</option>{options}</select></label><label>Status<select name="status"><option value="Active" {'selected' if status=='Active' else ''}>Active</option><option value="Inactive" {'selected' if status=='Inactive' else ''}>Inactive</option><option value="All" {'selected' if status=='All' else ''}>All</option></select></label><button class="btn">Filter</button><a class="btn btn-light" href="/app/inventory/items">Clear</a></form>
<div class="scroll"><table><thead><tr><th>Item / Code</th><th>Category</th><th>Unit</th><th>Quantity</th><th>Reorder level</th><th>Location</th><th>Status</th><th>Action</th></tr></thead><tbody>{trs}</tbody></table></div></section></div>
<dialog id="invDialog"><form method="post" action="/app/inventory/items/save" id="invForm"><h2 id="invTitle">Add inventory item</h2><input type="hidden" name="item_id" id="ivId" value="0"><div class="fields">
<label>Item code *<input name="item_code" id="ivCode" required maxlength="50"></label><label>Item name *<input name="item_name" id="ivName" required maxlength="160"></label>
<label>Category<input name="category" id="ivCategory" maxlength="100"></label><label>Unit<select name="unit" id="ivUnit"><option>Piece</option><option>Pack</option><option>Box</option><option>Ream</option><option>Kg</option><option>Litre</option><option>Metre</option><option>Set</option><option>Pair</option><option>Other</option></select></label>
<label>Quantity<input type="number" min="0" step="0.01" name="quantity" id="ivQty" value="0"></label><label>Reorder level<input type="number" min="0" step="0.01" name="reorder_level" id="ivReorder" value="0"></label>
<label>Storage location<input name="storage_location" id="ivLocation"></label><label>Status<select name="status" id="ivStatus"><option>Active</option><option>Inactive</option></select></label>
<label style="grid-column:1/-1">Description<textarea name="description" id="ivDescription" rows="2"></textarea></label></div>
<div class="actions"><button class="btn btn-light" type="button" onclick="document.getElementById('invDialog').close()">Cancel</button><button class="btn">Save item</button></div></form></dialog>
<script>
function openInv(){{document.getElementById('invForm').reset();document.getElementById('ivId').value='0';document.getElementById('invTitle').textContent='Add inventory item';document.getElementById('invDialog').showModal();}}
function editInv(b){{let d=b.dataset;[['ivId','id'],['ivCode','code'],['ivName','name'],['ivCategory','category'],['ivUnit','unit'],['ivQty','qty'],['ivReorder','reorder'],['ivLocation','location'],['ivStatus','status'],['ivDescription','description']].forEach(x=>document.getElementById(x[0]).value=d[x[1]]);document.getElementById('invTitle').textContent='Edit inventory item';document.getElementById('invDialog').showModal();}}
</script>
"""
        return _school_page(request, "Inventory Register", body)
    finally:
        con.close()

@router.post("/app/inventory/items/save")
def inventory_save(request: Request, item_id: int = Form(0), item_code: str = Form(...), item_name: str = Form(...), category: str = Form(""), unit: str = Form("Piece"), quantity: float = Form(0), reorder_level: float = Form(0), storage_location: str = Form(""), status: str = Form("Active"), description: str = Form("")):
    sid, err = _guard(request, "inventory.manage")
    if err: return err
    code, name = item_code.strip(), item_name.strip()
    if not code or not name or quantity < 0 or reorder_level < 0:
        return HTMLResponse("Enter an item code and name, and non-negative stock values.", 400)
    if unit not in {"Piece","Pack","Box","Ream","Kg","Litre","Metre","Set","Pair","Other"}: unit = "Piece"
    if status not in ("Active","Inactive"): status = "Active"
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        now = datetime.utcnow().isoformat()
        if item_id:
            cur.execute("UPDATE inventory_items SET item_code=?,item_name=?,category=?,unit=?,quantity=?,reorder_level=?,storage_location=?,status=?,description=?,updated_at=? WHERE id=? AND school_id=?", (code,name,category.strip(),unit,quantity,reorder_level,storage_location.strip(),status,description.strip(),now,item_id,sid))
            if cur.rowcount == 0: return HTMLResponse("Inventory item not found.",404)
        else:
            cur.execute("INSERT INTO inventory_items (school_id,item_code,item_name,category,unit,quantity,reorder_level,storage_location,status,description,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (sid,code,name,category.strip(),unit,quantity,reorder_level,storage_location.strip(),status,description.strip(),now,now))
        con.commit()
    except Exception as exc:
        con.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return HTMLResponse("That item code is already used in this school's inventory.",409)
        raise
    finally:
        con.close()
    return RedirectResponse("/app/inventory/items",303)


def _transaction_schema(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS inventory_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL, transaction_type TEXT NOT NULL,
        quantity REAL NOT NULL, balance_after REAL NOT NULL,
        reference_no TEXT DEFAULT '', movement_date TEXT NOT NULL,
        notes TEXT DEFAULT '', recorded_by TEXT DEFAULT '',
        created_at TEXT NOT NULL)""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_tx_school_date ON inventory_transactions(school_id,movement_date)")


@router.get("/app/inventory/transactions", response_class=HTMLResponse)
def inventory_transactions(request: Request, q: str = "", movement: str = "All"):
    sid, err = _guard(request)
    if err: return err
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        _transaction_schema(cur)
        con.commit()
        items = cur.execute("SELECT id,item_code,item_name,unit,quantity FROM inventory_items WHERE school_id=? AND status='Active' ORDER BY item_name", (sid,)).fetchall()
        where, params = ["t.school_id=?"], [sid]
        if q.strip():
            term = "%" + q.strip() + "%"
            where.append("(i.item_name LIKE ? OR i.item_code LIKE ? OR t.reference_no LIKE ?)")
            params.extend([term, term, term])
        if movement in ("Receive", "Issue", "Adjustment In", "Adjustment Out"):
            where.append("t.transaction_type=?")
            params.append(movement)
        rows = cur.execute("SELECT t.*,i.item_name,i.item_code,i.unit FROM inventory_transactions t JOIN inventory_items i ON i.id=t.item_id WHERE " + " AND ".join(where) + " ORDER BY t.id DESC LIMIT 300", tuple(params)).fetchall()
        totals = cur.execute("SELECT COALESCE(SUM(CASE WHEN transaction_type='Receive' OR transaction_type='Adjustment In' THEN quantity ELSE 0 END),0) received,COALESCE(SUM(CASE WHEN transaction_type='Issue' OR transaction_type='Adjustment Out' THEN quantity ELSE 0 END),0) issued,COUNT(*) entries FROM inventory_transactions WHERE school_id=?", (sid,)).fetchone()
        item_options = "".join(f"<option value='{int(x['id'])}'>{escape(str(x['item_code'] or ''))} — {escape(str(x['item_name'] or ''))} (balance: {float(x['quantity'] or 0):g} {escape(str(x['unit'] or ''))})</option>" for x in items)
        table_rows = "".join(f"<tr><td>{escape(str(x['movement_date'] or ''))}</td><td><b>{escape(str(x['item_name'] or ''))}</b><small>{escape(str(x['item_code'] or ''))}</small></td><td>{escape(str(x['transaction_type'] or ''))}</td><td>{float(x['quantity'] or 0):g} {escape(str(x['unit'] or ''))}</td><td>{float(x['balance_after'] or 0):g}</td><td>{escape(str(x['reference_no'] or '—'))}</td><td>{escape(str(x['recorded_by'] or ''))}</td></tr>" for x in rows) or "<tr><td colspan='7'>No stock movements recorded yet.</td></tr>"
        body = f"""
<div class="page inv-movements"><style>
.inv-movements .stats{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0}}
.inv-movements .stats>div,.inv-movements .panel{{background:#fff;border:1px solid #e3ebe5;border-radius:14px;padding:15px}}
.inv-movements .stats span,.inv-movements small{{display:block;color:#718078;font-size:12px}}.inv-movements .stats strong{{font-size:24px;color:#174b35}}
.inv-movements .toolbar{{display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:14px}}.inv-movements label{{display:grid;gap:6px;flex:1;min-width:145px;font-size:12px}}
.inv-movements input,.inv-movements select,.inv-movements textarea{{width:100%;min-height:40px;padding:8px;border:1px solid #dce6df;border-radius:9px;background:#fff}}
.inv-movements .scroll{{overflow:auto;width:100%}}.inv-movements table{{width:100%;min-width:850px;border-collapse:collapse}}.inv-movements th,.inv-movements td{{padding:10px;border-bottom:1px solid #edf1ee;text-align:left;font-size:13px}}.inv-movements th{{background:#f7faf8;color:#607267}}
.inv-movements .form-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.inv-movements .form-grid .wide{{grid-column:1/-1}}
@media(max-width:650px){{.inv-movements .stats,.inv-movements .form-grid{{grid-template-columns:1fr}}.inv-movements .form-grid .wide{{grid-column:auto}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">INVENTORY &amp; STORES / STOCK CONTROL</div><h1>Stock Receipts &amp; Issues</h1><div>Record incoming supplies, issued stock and authorised quantity adjustments. Every movement updates the item balance and is retained in the ledger.</div></div><a class="btn btn-light" href="/app/inventory/items">Inventory Register</a></div>
<div class="stats"><div><span>Movement entries</span><strong>{int(totals['entries'] or 0)}</strong></div><div><span>Total received</span><strong>{float(totals['received'] or 0):g}</strong></div><div><span>Total issued</span><strong>{float(totals['issued'] or 0):g}</strong></div></div>
<section class="panel"><h2>Record stock movement</h2><form method="post" action="/app/inventory/transactions/save" class="form-grid">
<label class="wide">Inventory item *<select name="item_id" required><option value="">Select an active inventory item</option>{item_options}</select></label>
<label>Movement type *<select name="transaction_type" required><option>Receive</option><option>Issue</option><option>Adjustment In</option><option>Adjustment Out</option></select></label>
<label>Quantity *<input type="number" name="quantity" min="0.01" step="0.01" required></label>
<label>Movement date *<input type="date" name="movement_date" value="{datetime.utcnow().strftime('%Y-%m-%d')}" required></label>
<label>Reference / voucher number<input name="reference_no" maxlength="100" placeholder="GRN, issue voucher or reference"></label>
<label class="wide">Notes / purpose<textarea name="notes" rows="2" maxlength="1000"></textarea></label>
<div class="wide" style="display:flex;justify-content:flex-end"><button class="btn">Save stock movement</button></div></form></section>
<section class="panel" style="margin-top:16px"><form method="get" class="toolbar"><label>Search<input name="q" value="{escape(q,quote=True)}" placeholder="Item, code or reference"></label><label>Movement<select name="movement"><option value="All">All movements</option><option value="Receive" {'selected' if movement=='Receive' else ''}>Receive</option><option value="Issue" {'selected' if movement=='Issue' else ''}>Issue</option><option value="Adjustment In" {'selected' if movement=='Adjustment In' else ''}>Adjustment In</option><option value="Adjustment Out" {'selected' if movement=='Adjustment Out' else ''}>Adjustment Out</option></select></label><button class="btn">Filter</button><a class="btn btn-light" href="/app/inventory/transactions">Clear</a></form>
<div class="scroll"><table><thead><tr><th>Date</th><th>Item / Code</th><th>Movement</th><th>Quantity</th><th>Balance after</th><th>Reference</th><th>Recorded by</th></tr></thead><tbody>{table_rows}</tbody></table></div><small>Showing the latest 300 stock movements for this school.</small></section></div>
"""
        return _school_page(request, "Stock Receipts & Issues", body)
    finally:
        con.close()


@router.post("/app/inventory/transactions/save")
def inventory_transaction_save(request: Request, item_id: int = Form(...), transaction_type: str = Form(...), quantity: float = Form(...), movement_date: str = Form(...), reference_no: str = Form(""), notes: str = Form("")):
    sid, err = _guard(request, "inventory.manage")
    if err: return err
    if transaction_type not in ("Receive", "Issue", "Adjustment In", "Adjustment Out") or quantity <= 0:
        return HTMLResponse("Choose a valid movement type and enter a quantity greater than zero.", 400)
    try:
        datetime.strptime(movement_date, "%Y-%m-%d")
    except Exception:
        return HTMLResponse("Enter a valid movement date.", 400)
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        _transaction_schema(cur)
        item = cur.execute("SELECT id,quantity FROM inventory_items WHERE id=? AND school_id=? AND status='Active'", (item_id, sid)).fetchone()
        if not item:
            return HTMLResponse("The selected active inventory item was not found.", 404)
        old_balance = float(item["quantity"] or 0)
        delta = quantity if transaction_type in ("Receive", "Adjustment In") else -quantity
        new_balance = old_balance + delta
        if new_balance < 0:
            return HTMLResponse("This issue would make the stock balance negative. Check the available quantity.", 400)
        now = datetime.utcnow().isoformat()
        cur.execute("UPDATE inventory_items SET quantity=?,updated_at=? WHERE id=? AND school_id=?", (new_balance, now, item_id, sid))
        cur.execute("INSERT INTO inventory_transactions (school_id,item_id,transaction_type,quantity,balance_after,reference_no,movement_date,notes,recorded_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (sid,item_id,transaction_type,quantity,new_balance,reference_no.strip(),movement_date,notes.strip(),str(request.session.get("name") or request.session.get("email") or ""),now))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/inventory/transactions", 303)


def _requisition_schema(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS inventory_requisitions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
      item_id INTEGER NOT NULL, quantity REAL NOT NULL, purpose TEXT NOT NULL,
      requested_by TEXT DEFAULT '', requested_date TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Pending', reviewed_by TEXT DEFAULT '',
      reviewed_at TEXT DEFAULT '', decision_notes TEXT DEFAULT '',
      issued_at TEXT DEFAULT '', issue_reference TEXT DEFAULT '', created_at TEXT NOT NULL)""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_req_school_status ON inventory_requisitions(school_id,status,requested_date)")


@router.get("/app/inventory/requisitions", response_class=HTMLResponse)
def inventory_requisitions(request: Request, status: str = "All", q: str = ""):
    sid, err = _guard(request)
    if err: return err
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        _requisition_schema(cur)
        _transaction_schema(cur)
        con.commit()
        items = cur.execute("SELECT id,item_code,item_name,unit,quantity FROM inventory_items WHERE school_id=? AND status='Active' ORDER BY item_name",(sid,)).fetchall()
        where, params = ["r.school_id=?"], [sid]
        if status in ("Pending","Approved","Rejected","Issued"):
            where.append("r.status=?"); params.append(status)
        if q.strip():
            term = "%" + q.strip() + "%"
            where.append("(i.item_name LIKE ? OR i.item_code LIKE ? OR r.purpose LIKE ? OR r.requested_by LIKE ?)")
            params.extend([term]*4)
        rows = cur.execute("SELECT r.*,i.item_name,i.item_code,i.unit FROM inventory_requisitions r JOIN inventory_items i ON i.id=r.item_id AND i.school_id=r.school_id WHERE "+" AND ".join(where)+" ORDER BY r.id DESC LIMIT 500",tuple(params)).fetchall()
        counts = cur.execute("SELECT COUNT(*) total, SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END) pending, SUM(CASE WHEN status='Approved' THEN 1 ELSE 0 END) approved, SUM(CASE WHEN status='Issued' THEN 1 ELSE 0 END) issued FROM inventory_requisitions WHERE school_id=?",(sid,)).fetchone()
        opts = "".join(f"<option value='{int(x['id'])}'>{escape(str(x['item_code'] or ''))} — {escape(str(x['item_name'] or ''))} (balance {float(x['quantity'] or 0):g})</option>" for x in items)
        trs = ""
        for x in rows:
            action = ""
            if x["status"] == "Pending":
                action = f"""<form method="post" action="/app/inventory/requisitions/review"><input type="hidden" name="requisition_id" value="{int(x['id'])}"><input type="hidden" name="decision" value="Approved"><input name="decision_notes" placeholder="Approval note"><button class="btn">Approve</button></form><form method="post" action="/app/inventory/requisitions/review"><input type="hidden" name="requisition_id" value="{int(x['id'])}"><input type="hidden" name="decision" value="Rejected"><input name="decision_notes" placeholder="Reason required"><button class="btn btn-light">Reject</button></form>"""
            elif x["status"] == "Approved":
                action = f"""<form method="post" action="/app/inventory/requisitions/issue"><input type="hidden" name="requisition_id" value="{int(x['id'])}"><input name="issue_reference" placeholder="Issue voucher"><button class="btn">Issue stock</button></form>"""
            trs += f"<tr><td>REQ-{int(x['id']):05d}<small>{escape(str(x['requested_date'] or ''))}</small></td><td>{escape(str(x['item_name'] or ''))}<small>{escape(str(x['item_code'] or ''))}</small></td><td>{float(x['quantity'] or 0):g} {escape(str(x['unit'] or ''))}</td><td>{escape(str(x['purpose'] or ''))}</td><td>{escape(str(x['requested_by'] or ''))}</td><td>{escape(str(x['status'] or ''))}<small>{escape(str(x['decision_notes'] or ''))}</small></td><td>{action}</td></tr>"
        trs = trs or "<tr><td colspan='7'>No requisitions found.</td></tr>"
        body = f"""
<div class="page inv-req"><style>
.inv-req .stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}}.inv-req .stats>div,.inv-req .panel{{background:#fff;border:1px solid #e3ebe5;border-radius:14px;padding:15px}}.inv-req .stats span,.inv-req small{{display:block;color:#718078;font-size:12px}}.inv-req .stats strong{{font-size:24px;color:#174b35}}.inv-req .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.inv-req label{{display:grid;gap:6px;font-size:12px}}.inv-req input,.inv-req select,.inv-req textarea{{width:100%;min-height:39px;padding:8px;border:1px solid #dce6df;border-radius:9px;background:#fff}}.inv-req .wide{{grid-column:1/-1}}.inv-req .scroll{{overflow:auto;width:100%}}.inv-req table{{width:100%;min-width:1050px;border-collapse:collapse}}.inv-req th,.inv-req td{{padding:10px;border-bottom:1px solid #edf1ee;text-align:left;font-size:13px;vertical-align:top}}.inv-req th{{background:#f7faf8}}.inv-req form{{margin:0 0 5px}}@media(max-width:700px){{.inv-req .stats,.inv-req .grid{{grid-template-columns:1fr}}.inv-req .wide{{grid-column:auto}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">INVENTORY &amp; STORES / STOCK CONTROL</div><h1>Stock Requisitions &amp; Approvals</h1><div>Submit stock requests, approve or reject them, and issue approved quantities with an auditable ledger.</div></div><a class="btn btn-light" href="/app/inventory/transactions">Stock Receipts &amp; Issues</a></div>
<div class="stats"><div><span>Total requests</span><strong>{int(counts['total'] or 0)}</strong></div><div><span>Pending review</span><strong>{int(counts['pending'] or 0)}</strong></div><div><span>Approved</span><strong>{int(counts['approved'] or 0)}</strong></div><div><span>Issued</span><strong>{int(counts['issued'] or 0)}</strong></div></div>
<section class="panel"><h2>New stock requisition</h2><form method="post" action="/app/inventory/requisitions/create" class="grid"><label class="wide">Item *<select name="item_id" required><option value="">Select item</option>{opts}</select></label><label>Quantity *<input type="number" name="quantity" min="0.01" step="0.01" required></label><label>Requested by<input name="requested_by" value="{escape(str(request.session.get('name') or request.session.get('email') or ''),quote=True)}"></label><label class="wide">Purpose *<textarea name="purpose" required maxlength="1000"></textarea></label><div class="wide"><button class="btn">Submit request</button></div></form></section>
<section class="panel" style="margin-top:16px"><form method="get" class="grid"><label>Search<input name="q" value="{escape(q,quote=True)}" placeholder="Item, requester or purpose"></label><label>Status<select name="status"><option value="All">All</option><option value="Pending" {'selected' if status=='Pending' else ''}>Pending</option><option value="Approved" {'selected' if status=='Approved' else ''}>Approved</option><option value="Rejected" {'selected' if status=='Rejected' else ''}>Rejected</option><option value="Issued" {'selected' if status=='Issued' else ''}>Issued</option></select></label><div class="wide"><button class="btn">Filter</button> <a class="btn btn-light" href="/app/inventory/requisitions">Clear</a></div></form><div class="scroll"><table><thead><tr><th>Request</th><th>Item</th><th>Quantity</th><th>Purpose</th><th>Requester</th><th>Status / decision</th><th>Actions</th></tr></thead><tbody>{trs}</tbody></table></div></section></div>
"""
        return _school_page(request, "Stock Requisitions & Approvals", body)
    finally:
        con.close()


@router.post("/app/inventory/requisitions/create")
def inventory_requisition_create(request: Request, item_id: int = Form(...), quantity: float = Form(...), purpose: str = Form(...), requested_by: str = Form("")):
    sid, err = _guard(request, "inventory.manage")
    if err: return err
    if quantity <= 0 or not purpose.strip(): return HTMLResponse("Enter a positive quantity and purpose.",400)
    con = _db()
    try:
        cur = con.cursor(); _schema(cur); _requisition_schema(cur)
        item = cur.execute("SELECT id FROM inventory_items WHERE id=? AND school_id=? AND status='Active'",(item_id,sid)).fetchone()
        if not item: return HTMLResponse("Active inventory item not found.",404)
        now = datetime.utcnow().isoformat()
        cur.execute("INSERT INTO inventory_requisitions (school_id,item_id,quantity,purpose,requested_by,requested_date,status,created_at) VALUES (?,?,?,?,?,?,?,?)",(sid,item_id,quantity,purpose.strip(),requested_by.strip() or str(request.session.get("name") or request.session.get("email") or ""),now[:10],"Pending",now))
        con.commit()
    except Exception: con.rollback(); raise
    finally: con.close()
    return RedirectResponse("/app/inventory/requisitions",303)


@router.post("/app/inventory/requisitions/review")
def inventory_requisition_review(request: Request, requisition_id: int = Form(...), decision: str = Form(...), decision_notes: str = Form("")):
    sid, err = _guard(request, "inventory.manage")
    if err: return err
    if decision not in ("Approved","Rejected") or (decision=="Rejected" and not decision_notes.strip()): return HTMLResponse("Choose a valid decision; a rejection reason is required.",400)
    con = _db()
    try:
        cur=con.cursor(); _requisition_schema(cur)
        now=datetime.utcnow().isoformat()
        cur.execute("UPDATE inventory_requisitions SET status=?,reviewed_by=?,reviewed_at=?,decision_notes=? WHERE id=? AND school_id=? AND status='Pending'",(decision,str(request.session.get("name") or request.session.get("email") or ""),now,decision_notes.strip(),requisition_id,sid))
        if cur.rowcount != 1: con.rollback(); return HTMLResponse("Request not pending or already reviewed. Refresh the page.",409)
        con.commit()
    except Exception: con.rollback(); raise
    finally: con.close()
    return RedirectResponse("/app/inventory/requisitions",303)


@router.post("/app/inventory/requisitions/issue")
def inventory_requisition_issue(request: Request, requisition_id: int = Form(...), issue_reference: str = Form("")):
    sid, err = _guard(request, "inventory.manage")
    if err: return err
    con = _db()
    try:
        cur=con.cursor(); _schema(cur); _requisition_schema(cur); _transaction_schema(cur)
        req=cur.execute("SELECT r.*,i.quantity AS balance,i.status AS item_status FROM inventory_requisitions r JOIN inventory_items i ON i.id=r.item_id AND i.school_id=r.school_id WHERE r.id=? AND r.school_id=? AND r.status='Approved'",(requisition_id,sid)).fetchone()
        if not req: return HTMLResponse("Only an approved request can be issued.",409)
        qty=float(req["quantity"] or 0); balance=float(req["balance"] or 0)
        if req["item_status"]!="Active" or qty<=0 or balance<qty: return HTMLResponse("Item inactive or insufficient stock. No stock was issued.",400)
        now=datetime.utcnow().isoformat(); new_balance=balance-qty
        cur.execute("UPDATE inventory_items SET quantity=?,updated_at=? WHERE id=? AND school_id=?",(new_balance,now,req["item_id"],sid))
        cur.execute("INSERT INTO inventory_transactions (school_id,item_id,transaction_type,quantity,balance_after,reference_no,movement_date,notes,recorded_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(sid,req["item_id"],"Issue",qty,new_balance,issue_reference.strip() or ("REQ-%05d" % requisition_id),now[:10],"Issued against approved requisition REQ-%05d: %s" % (requisition_id,req["purpose"]),str(request.session.get("name") or request.session.get("email") or ""),now))
        cur.execute("UPDATE inventory_requisitions SET status='Issued',issued_at=?,issue_reference=? WHERE id=? AND school_id=? AND status='Approved'",(now,issue_reference.strip(),requisition_id,sid))
        if cur.rowcount != 1: con.rollback(); return HTMLResponse("Request changed; no stock was issued. Refresh and retry.",409)
        con.commit()
    except Exception: con.rollback(); raise
    finally: con.close()
    return RedirectResponse("/app/inventory/requisitions",303)


def _requisition_schema(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS inventory_requisitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        requisition_no TEXT NOT NULL,
        requested_by TEXT NOT NULL,
        requested_date TEXT NOT NULL,
        required_date TEXT NOT NULL,
        department TEXT DEFAULT '',
        purpose TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        decision_note TEXT DEFAULT '',
        reviewed_by TEXT DEFAULT '',
        reviewed_at TEXT DEFAULT '',
        issued_by TEXT DEFAULT '',
        issued_at TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(school_id,requisition_no)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS inventory_requisition_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        requisition_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        quantity REAL NOT NULL,
        created_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_req_school_status ON inventory_requisitions(school_id,status,id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_req_lines_lookup ON inventory_requisition_lines(school_id,requisition_id,item_id)")


@router.get("/app/inventory/requisitions", response_class=HTMLResponse)
def inventory_requisitions(request: Request, q: str = "", status: str = "All"):
    sid, err = _guard(request)
    if err:
        return err
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        _transaction_schema(cur)
        _requisition_schema(cur)
        con.commit()
        items = cur.execute(
            "SELECT id,item_code,item_name,unit,quantity FROM inventory_items WHERE school_id=? AND status='Active' ORDER BY item_name",
            (sid,)
        ).fetchall()
        totals = cur.execute(
            """SELECT COUNT(*) total,
               COALESCE(SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END),0) pending,
               COALESCE(SUM(CASE WHEN status='Approved' THEN 1 ELSE 0 END),0) approved,
               COALESCE(SUM(CASE WHEN status='Rejected' THEN 1 ELSE 0 END),0) rejected
               FROM inventory_requisitions WHERE school_id=?""",
            (sid,)
        ).fetchone()
        where = ["school_id=?"]
        params = [sid]
        if status in ("Pending", "Approved", "Rejected"):
            where.append("status=?")
            params.append(status)
        if q.strip():
            term = "%" + q.strip() + "%"
            where.append("(requisition_no LIKE ? OR requested_by LIKE ? OR department LIKE ? OR purpose LIKE ?)")
            params.extend([term, term, term, term])
        rows = cur.execute(
            "SELECT * FROM inventory_requisitions WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT 200",
            tuple(params)
        ).fetchall()
        item_options = "".join(
            f"<option value='{int(x['id'])}'>{escape(str(x['item_code'] or ''))} — {escape(str(x['item_name'] or ''))} (available: {float(x['quantity'] or 0):g} {escape(str(x['unit'] or ''))})</option>"
            for x in items
        )
        cards = []
        for row in rows:
            rid = int(row["id"])
            lines = cur.execute(
                """SELECT l.quantity,i.item_name,i.item_code,i.unit
                   FROM inventory_requisition_lines l
                   LEFT JOIN inventory_items i ON i.id=l.item_id AND i.school_id=l.school_id
                   WHERE l.school_id=? AND l.requisition_id=? ORDER BY l.id""",
                (sid, rid)
            ).fetchall()
            line_html = "".join(
                f"<li><b>{escape(str(line['item_name'] or 'Unavailable item'))}</b> <small>({escape(str(line['item_code'] or ''))})</small> — {float(line['quantity'] or 0):g} {escape(str(line['unit'] or ''))}</li>"
                for line in lines
            ) or "<li>No requisition lines were found.</li>"
            req_no = escape(str(row["requisition_no"] or ""))
            req_status = str(row["status"] or "Pending")
            status_class = "pending" if req_status == "Pending" else ("approved" if req_status == "Approved" else "rejected")
            note = str(row["decision_note"] or "").strip()
            decision_html = f"<div class='decision-note'><b>Decision note:</b> {escape(note)}<small>Reviewed by {escape(str(row['reviewed_by'] or ''))} · {escape(str(row['reviewed_at'] or ''))}</small></div>" if note or row["reviewed_by"] else ""
            if req_status == "Pending":
                action_html = f"""
<form method="post" action="/app/inventory/requisitions/decision" class="decision-form">
<input type="hidden" name="requisition_id" value="{rid}">
<label>Decision note<textarea name="decision_note" rows="2" maxlength="1000" placeholder="Reason, clarification or approval note"></textarea></label>
<div class="req-actions"><button class="btn" name="decision" value="Approved">Approve</button><button class="btn btn-light" name="decision" value="Rejected">Reject</button></div>
</form>"""
            elif req_status == "Approved" and not str(row["issued_at"] or "").strip():
                action_html = f"""
<form method="post" action="/app/inventory/requisitions/issue" class="req-issue-form">
<input type="hidden" name="requisition_id" value="{rid}">
<button class="btn">Issue approved stock</button>
<span>Stock is deducted only when this action is confirmed.</span>
</form>"""
            elif str(row["issued_at"] or "").strip():
                action_html = f"<div class='issued-note'>Issued by {escape(str(row['issued_by'] or ''))} · {escape(str(row['issued_at'] or ''))}</div>"
            else:
                action_html = ""
            cards.append(f"""
<article class="req-card">
<div class="req-card-head"><div><b>{req_no}</b><small>Requested by {escape(str(row['requested_by'] or ''))}</small></div><span class="req-status {status_class}">{escape(req_status)}{ " · Issued" if str(row["issued_at"] or "").strip() else ""}</span></div>
<div class="req-meta"><span>Requested: {escape(str(row['requested_date'] or ''))}</span><span>Required: {escape(str(row['required_date'] or ''))}</span><span>Department: {escape(str(row['department'] or '—'))}</span></div>
<ul class="req-items">{line_html}</ul>
<p class="req-purpose">{escape(str(row['purpose'] or ''))}</p>
{decision_html}
{action_html}
</article>""")
        cards_html = "".join(cards) or "<div class='empty-state'>No stock requisitions match this view.</div>"
        body = f"""
<div class="page inv-req-page"><style>
.inv-req-page{{width:100%;max-width:none}}
.inv-req-page .stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}}
.inv-req-page .stats>div,.inv-req-page .panel,.inv-req-page .req-card{{background:#fff;border:1px solid #e3ebe5;border-radius:14px;padding:16px;min-width:0}}
.inv-req-page .stats span,.inv-req-page small{{display:block;color:#718078;font-size:12px}}
.inv-req-page .stats strong{{font-size:24px;color:#174b35}}
.inv-req-page .panel{{margin-bottom:16px}}
.inv-req-page label{{display:grid;gap:6px;font-size:12px;color:#42564a}}
.inv-req-page input,.inv-req-page select,.inv-req-page textarea{{width:100%;min-height:40px;padding:9px;border:1px solid #dce6df;border-radius:9px;background:#fff;font:inherit}}
.inv-req-page textarea{{resize:vertical}}
.inv-req-page .req-form-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}
.inv-req-page .wide{{grid-column:1/-1}}
.inv-req-page .req-lines{{display:grid;gap:9px}}
.inv-req-page .req-line{{display:grid;grid-template-columns:minmax(0,2fr) minmax(110px,1fr) auto;gap:9px;align-items:end}}
.inv-req-page .req-line .remove-line{{min-height:40px}}
.inv-req-page .form-actions,.inv-req-page .req-actions{{display:flex;gap:9px;justify-content:flex-end;flex-wrap:wrap;align-items:center}}
.inv-req-page .req-toolbar{{display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:14px}}
.inv-req-page .req-toolbar label{{flex:1;min-width:170px}}
.inv-req-page .req-list{{display:grid;gap:12px}}
.inv-req-page .req-card-head{{display:flex;justify-content:space-between;gap:12px;align-items:start}}
.inv-req-page .req-card-head small{{margin-top:4px}}
.inv-req-page .req-status{{display:inline-flex;border-radius:99px;padding:6px 10px;font-size:12px;font-weight:700;white-space:nowrap}}
.inv-req-page .pending{{background:#fff4d8;color:#805a08}}.inv-req-page .approved{{background:#e3f4e9;color:#17623b}}.inv-req-page .rejected{{background:#fde9e7;color:#9a332b}}
.inv-req-page .req-meta{{display:flex;gap:16px;flex-wrap:wrap;color:#607267;font-size:12px;margin:12px 0}}
.inv-req-page .req-items{{margin:0;padding:12px 12px 12px 30px;background:#f7faf8;border-radius:10px;font-size:13px}}
.inv-req-page .req-items li+li{{margin-top:5px}}
.inv-req-page .req-purpose{{font-size:13px;white-space:pre-wrap}}
.inv-req-page .decision-form{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:end;border-top:1px solid #edf1ee;padding-top:12px;margin-top:12px}}
.inv-req-page .decision-note,.inv-req-page .issued-note{{border-top:1px solid #edf1ee;padding-top:10px;margin-top:10px;font-size:12px;color:#4c6154}}
.inv-req-page .req-issue-form{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-top:1px solid #edf1ee;padding-top:12px;margin-top:12px}}
.inv-req-page .req-issue-form span{{font-size:12px;color:#718078}}
.inv-req-page .empty-state{{padding:28px;text-align:center;background:#fff;border:1px dashed #cddbd1;border-radius:12px;color:#718078}}
@media(max-width:760px){{.inv-req-page .stats{{grid-template-columns:repeat(2,minmax(0,1fr))}}.inv-req-page .req-form-grid{{grid-template-columns:1fr}}.inv-req-page .wide{{grid-column:auto}}.inv-req-page .decision-form{{grid-template-columns:1fr}}}}
@media(max-width:520px){{.inv-req-page .stats{{grid-template-columns:1fr 1fr}}.inv-req-page .req-line{{grid-template-columns:1fr 110px}}.inv-req-page .req-line .remove-line{{grid-column:1/-1}}.inv-req-page .req-card-head{{align-items:start;flex-direction:column}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">INVENTORY &amp; STORES / STOCK CONTROL</div><h1>Stock Requisitions &amp; Approvals</h1><div>Capture departmental stock requests, review decisions and issue stock only after approval.</div></div><a class="btn btn-light" href="/app/inventory/transactions">Stock Receipts &amp; Issues</a></div>
<div class="stats"><div><span>Total requisitions</span><strong>{int(totals['total'] or 0)}</strong></div><div><span>Awaiting review</span><strong>{int(totals['pending'] or 0)}</strong></div><div><span>Approved</span><strong>{int(totals['approved'] or 0)}</strong></div><div><span>Rejected</span><strong>{int(totals['rejected'] or 0)}</strong></div></div>
<section class="panel"><h2>New stock requisition</h2><form method="post" action="/app/inventory/requisitions/save" class="req-form-grid">
<label>Required by date *<input type="date" name="required_date" min="{datetime.utcnow().strftime('%Y-%m-%d')}" value="{datetime.utcnow().strftime('%Y-%m-%d')}" required></label>
<label>Department / requesting section<input name="department" maxlength="120" placeholder="e.g. Science Department"></label>
<label>Requested by<input value="{escape(str(request.session.get('name') or request.session.get('email') or ''))}" disabled></label>
<div class="wide"><label>Requested items *</label><div class="req-lines" id="reqLines"><div class="req-line"><select name="item_ids" required><option value="">Select an active stock item</option>{item_options}</select><input type="number" name="quantities" min="0.01" step="0.01" placeholder="Quantity" required><button type="button" class="btn btn-light remove-line" onclick="removeReqLine(this)">Remove</button></div></div><div style="margin-top:9px"><button type="button" class="btn btn-light" onclick="addReqLine()">Add another item</button></div></div>
<label class="wide">Purpose / justification *<textarea name="purpose" rows="3" maxlength="2000" required placeholder="Explain why the items are needed and how they will be used."></textarea></label>
<div class="wide form-actions"><button class="btn">Submit requisition</button></div></form></section>
<section class="panel"><form method="get" class="req-toolbar"><label>Search<input name="q" value="{escape(q,quote=True)}" placeholder="Requisition number, requester, department or purpose"></label><label>Status<select name="status"><option value="All">All statuses</option><option value="Pending" {'selected' if status=='Pending' else ''}>Pending</option><option value="Approved" {'selected' if status=='Approved' else ''}>Approved</option><option value="Rejected" {'selected' if status=='Rejected' else ''}>Rejected</option></select></label><button class="btn">Filter</button><a class="btn btn-light" href="/app/inventory/requisitions">Clear</a></form><div class="req-list">{cards_html}</div><small>Showing the latest 200 requisitions for this school.</small></section></div>
<script>
function addReqLine(){{const first=document.querySelector('#reqLines .req-line');const row=first.cloneNode(true);row.querySelector('select').value='';row.querySelector('input').value='';document.getElementById('reqLines').appendChild(row);}}
function removeReqLine(button){{const rows=document.querySelectorAll('#reqLines .req-line');if(rows.length>1)button.closest('.req-line').remove();}}
</script>
"""
        return _school_page(request, "Stock Requisitions & Approvals", body)
    finally:
        con.close()


@router.post("/app/inventory/requisitions/save")
def inventory_requisition_save(
    request: Request,
    item_ids: list[int] = Form(...),
    quantities: list[float] = Form(...),
    required_date: str = Form(...),
    department: str = Form(""),
    purpose: str = Form(...)
):
    sid, err = _guard(request, "inventory.manage")
    if err:
        return err
    if not item_ids or len(item_ids) != len(quantities) or len(set(item_ids)) != len(item_ids):
        return HTMLResponse("Select at least one stock item, with one quantity per item. Do not repeat the same item.", 400)
    if any(float(qty) <= 0 for qty in quantities):
        return HTMLResponse("Every requested quantity must be greater than zero.", 400)
    try:
        datetime.strptime(required_date, "%Y-%m-%d")
    except Exception:
        return HTMLResponse("Enter a valid required-by date.", 400)
    if not purpose.strip():
        return HTMLResponse("Enter the purpose of this requisition.", 400)
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        _requisition_schema(cur)
        for item_id in item_ids:
            item = cur.execute(
                "SELECT id FROM inventory_items WHERE id=? AND school_id=? AND status='Active'",
                (int(item_id), sid)
            ).fetchone()
            if not item:
                return HTMLResponse("One or more selected items are not active inventory items in this school.", 400)
        now = datetime.utcnow().isoformat()
        requester = str(request.session.get("name") or request.session.get("email") or "School user")
        requested_date = datetime.utcnow().strftime("%Y-%m-%d")
        cur.execute(
            """INSERT INTO inventory_requisitions
               (school_id,requisition_no,requested_by,requested_date,required_date,department,purpose,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sid, "PENDING", requester, requested_date, required_date, department.strip(), purpose.strip(), "Pending", now, now)
        )
        requisition_id = int(cur.lastrowid or 0)
        if not requisition_id:
            raise RuntimeError("Could not allocate the requisition reference.")
        requisition_no = "REQ-" + datetime.utcnow().strftime("%Y%m%d") + "-" + str(requisition_id).zfill(6)
        cur.execute(
            "UPDATE inventory_requisitions SET requisition_no=? WHERE id=? AND school_id=?",
            (requisition_no, requisition_id, sid)
        )
        for item_id, qty in zip(item_ids, quantities):
            cur.execute(
                """INSERT INTO inventory_requisition_lines
                   (school_id,requisition_id,item_id,quantity,created_at) VALUES (?,?,?,?,?)""",
                (sid, requisition_id, int(item_id), float(qty), now)
            )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/inventory/requisitions", 303)


@router.post("/app/inventory/requisitions/decision")
def inventory_requisition_decision(
    request: Request,
    requisition_id: int = Form(...),
    decision: str = Form(...),
    decision_note: str = Form("")
):
    sid, err = _guard(request, "inventory.manage")
    if err:
        return err
    if decision not in ("Approved", "Rejected"):
        return HTMLResponse("Choose Approve or Reject.", 400)
    if decision == "Rejected" and not decision_note.strip():
        return HTMLResponse("A reason is required when rejecting a requisition.", 400)
    con = _db()
    try:
        cur = con.cursor()
        _requisition_schema(cur)
        row = cur.execute(
            "SELECT id,status FROM inventory_requisitions WHERE id=? AND school_id=?",
            (requisition_id, sid)
        ).fetchone()
        if not row:
            return HTMLResponse("Requisition not found for this school.", 404)
        if str(row["status"] or "") != "Pending":
            return HTMLResponse("Only pending requisitions can be reviewed.", 409)
        now = datetime.utcnow().isoformat()
        reviewer = str(request.session.get("name") or request.session.get("email") or "School reviewer")
        cur.execute(
            """UPDATE inventory_requisitions
               SET status=?,decision_note=?,reviewed_by=?,reviewed_at=?,updated_at=?
               WHERE id=? AND school_id=? AND status='Pending'""",
            (decision, decision_note.strip(), reviewer, now, now, requisition_id, sid)
        )
        if cur.rowcount != 1:
            con.rollback()
            return HTMLResponse("This requisition has already been reviewed. Refresh and try again.", 409)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/inventory/requisitions", 303)


@router.post("/app/inventory/requisitions/issue")
def inventory_requisition_issue(request: Request, requisition_id: int = Form(...)):
    sid, err = _guard(request, "inventory.manage")
    if err:
        return err
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        _transaction_schema(cur)
        _requisition_schema(cur)
        req = cur.execute(
            """SELECT id,requisition_no,status,issued_at FROM inventory_requisitions
               WHERE id=? AND school_id=?""",
            (requisition_id, sid)
        ).fetchone()
        if not req:
            return HTMLResponse("Requisition not found for this school.", 404)
        if str(req["status"] or "") != "Approved":
            return HTMLResponse("Stock can only be issued against an approved requisition.", 409)
        if str(req["issued_at"] or "").strip():
            return HTMLResponse("This requisition has already been issued.", 409)
        lines = cur.execute(
            "SELECT item_id,quantity FROM inventory_requisition_lines WHERE requisition_id=? AND school_id=? ORDER BY id",
            (requisition_id, sid)
        ).fetchall()
        if not lines:
            return HTMLResponse("This requisition has no stock lines to issue.", 409)
        now = datetime.utcnow().isoformat()
        issuer = str(request.session.get("name") or request.session.get("email") or "Stock officer")
        for line in lines:
            item_id = int(line["item_id"])
            qty = float(line["quantity"] or 0)
            if qty <= 0:
                con.rollback()
                return HTMLResponse("A requisition line has an invalid quantity. No stock was issued.", 409)
            item = cur.execute(
                """SELECT id,item_code,item_name,quantity FROM inventory_items
                   WHERE id=? AND school_id=? AND status='Active'""",
                (item_id, sid)
            ).fetchone()
            if not item:
                con.rollback()
                return HTMLResponse("A requested item is no longer active in this school. No stock was issued.", 409)
            old_balance = float(item["quantity"] or 0)
            new_balance = old_balance - qty
            if new_balance < 0:
                con.rollback()
                return HTMLResponse(
                    "Insufficient stock for " + str(item["item_name"] or item["item_code"] or "an item") + ". No stock was issued.",
                    409
                )
            cur.execute(
                """UPDATE inventory_items SET quantity=?,updated_at=?
                   WHERE id=? AND school_id=? AND quantity=?""",
                (new_balance, now, item_id, sid, old_balance)
            )
            if cur.rowcount != 1:
                con.rollback()
                return HTMLResponse("Stock changed during issue processing. Refresh and retry; no stock was issued.", 409)
            cur.execute(
                """INSERT INTO inventory_transactions
                   (school_id,item_id,transaction_type,quantity,balance_after,reference_no,movement_date,notes,recorded_by,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sid, item_id, "Issue", qty, new_balance, str(req["requisition_no"] or ""), datetime.utcnow().strftime("%Y-%m-%d"),
                 "Issued against approved requisition " + str(req["requisition_no"] or ""), issuer, now)
            )
        cur.execute(
            """UPDATE inventory_requisitions SET issued_by=?,issued_at=?,updated_at=?
               WHERE id=? AND school_id=? AND status='Approved' AND (issued_at='' OR issued_at IS NULL)""",
            (issuer, now, now, requisition_id, sid)
        )
        if cur.rowcount != 1:
            con.rollback()
            return HTMLResponse("This requisition has already been issued. No stock was deducted.", 409)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/inventory/requisitions", 303)
