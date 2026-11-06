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
