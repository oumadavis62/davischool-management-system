from datetime import datetime
import math
from html import escape
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.new_ui import _db, _require_permission, _school_page, _school_session

router = APIRouter()

def _inventory_page(request, title, body):
    shared = """
<style>
.inv-workspace{--inv-forest:#174b32;--inv-green:#26734a;--inv-line:#dce9de;color:#233b2d;width:100%;max-width:none!important;padding-bottom:28px}
.inv-workspace:before{content:"";display:block;height:5px;margin:-2px 0 16px;border-radius:99px;background:linear-gradient(90deg,#174b32,#39845a 48%,#b8d8bd);box-shadow:0 2px 8px #174b321c}
.inv-workspace .page-heading{position:relative;overflow:hidden;isolation:isolate;display:flex;justify-content:space-between;align-items:center;gap:14px;padding:22px 24px 21px;margin:0 0 17px;border:1px solid #dce9de;border-radius:19px;background:linear-gradient(115deg,#f5faf5 0%,#fff 58%,#edf6ee 100%);box-shadow:0 8px 24px #214c2d0b}
.inv-workspace .page-heading h1{font-size:clamp(25px,3vw,33px);font-weight:800;letter-spacing:-.8px;line-height:1.15;color:#174b32;margin:7px 0 8px}
.inv-workspace .page-heading>div>div:last-child{color:#718278;font-size:12px;line-height:1.55}
.inv-workspace .lib-eyebrow{display:inline-flex;align-items:center;gap:7px;color:#397653;font-size:10px;font-weight:800;letter-spacing:1.7px}
.inv-workspace .lib-eyebrow:before{content:"";width:7px;height:7px;border-radius:2px;background:#4c9665;box-shadow:0 0 0 4px #e2f0e4}
.inv-workspace .stats{grid-template-columns:repeat(auto-fit,minmax(175px,1fr))!important;gap:13px!important;margin:0 0 17px!important}
.inv-workspace .stats>div{position:relative;overflow:hidden;min-height:100px;padding:17px 18px 15px 20px!important;border:1px solid #e0ebe1!important;border-radius:16px!important;background:linear-gradient(145deg,#fff,#f8fbf8)!important;box-shadow:0 5px 17px #183d2609!important}
.inv-workspace .stats>div:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,#367c50,#a6c9a9)}
.inv-workspace .stats span{color:#718176!important;font-size:11px!important;font-weight:750}
.inv-workspace .stats strong{color:#1e5b3a!important;font-size:27px!important;letter-spacing:-.6px}
.inv-workspace .panel{padding:18px!important;margin:0 0 14px!important;border:1px solid #e1ebe2!important;border-radius:17px!important;background:#fff!important;box-shadow:0 6px 22px #193d2609!important}
.inv-workspace .panel h2{margin:0 0 14px;color:#214d34;font-size:15px;font-weight:800}
.inv-workspace .scroll{max-width:100%;border:1px solid #e5ede6;border-radius:13px;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}
.inv-workspace table{border-collapse:separate!important;border-spacing:0!important;width:100%;min-width:760px}
.inv-workspace th{padding:13px 14px!important;background:linear-gradient(180deg,#f2f8f2,#eaf3eb)!important;color:#42634c!important;font-size:10px!important;font-weight:800;letter-spacing:.7px;text-transform:uppercase;white-space:nowrap}
.inv-workspace td{padding:12px 14px!important;border-bottom:1px solid #edf2ed!important;color:#3c5143;font-size:12px!important;vertical-align:middle}
.inv-workspace tbody tr:nth-child(even){background:#fbfdfb}
.inv-workspace tbody tr:hover{background:#f0f7f1}
.inv-workspace small{color:#718278!important;font-size:11px!important;line-height:1.45}
.inv-workspace label{color:#3d5946;font-size:11px!important;font-weight:750;line-height:1.35}
.inv-workspace input,.inv-workspace select,.inv-workspace textarea{min-height:42px!important;padding:10px 11px!important;border:1px solid #dce7de!important;border-radius:10px!important;background:#fcfefc!important;color:#294534}
.inv-workspace input:focus,.inv-workspace select:focus,.inv-workspace textarea:focus{outline:0;border-color:#78a985!important;box-shadow:0 0 0 3px #e4f1e6}
.inv-workspace .btn{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:9px 15px;border:1px solid #1f5b3b;border-radius:10px;background:linear-gradient(135deg,#205f3e,#317b4d);color:#fff!important;font-size:12px;font-weight:800;box-shadow:none;transition:all .16s ease}
.inv-workspace .btn:hover{filter:brightness(1.04);transform:translateY(-1px);box-shadow:0 5px 12px #205f3e20}
.inv-workspace .btn.btn-light{border-color:#dce8de;background:#f4f8f4;color:#3f6249!important}
.inv-workspace .inv-filter-trigger{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:9px 15px;border:1px solid #cfe0d1;border-radius:11px;background:#fff;color:#245b39;font-size:12px;font-weight:800;box-shadow:0 3px 10px #214c2d0b}
.inv-workspace .inv-filter-trigger:before{content:"";width:7px;height:7px;border-radius:50%;background:#4b9562;box-shadow:0 0 0 4px #e7f2e8}
.inv-filter-dialog{width:min(760px,calc(100% - 18px));max-height:88vh;overflow:auto;border:1px solid #dce8de;border-radius:21px;padding:0;background:#fff;box-shadow:0 28px 90px #102d1c55}
.inv-filter-dialog::backdrop,.inv-form-dialog::backdrop{background:#0d1f1385;backdrop-filter:blur(3px)}
.inv-filter-dialog .inv-dialog-head{position:sticky;top:0;z-index:2;display:flex;justify-content:space-between;align-items:center;padding:17px 20px;background:linear-gradient(110deg,#f0f7f1,#fff);border-bottom:1px solid #e4ede5}
.inv-filter-dialog .inv-dialog-head strong{font-size:16px;color:#1d5033}
.inv-filter-dialog .inv-dialog-head button{width:36px;height:36px;border:0;border-radius:50%;background:#e5efe6;color:#315b3e;font-size:22px}
.inv-filter-dialog .inv-dialog-content{padding:20px}
.inv-filter-dialog form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px;align-items:end}
.inv-filter-dialog form label{display:grid;grid-template-columns:1fr;gap:7px;min-width:0}
.inv-filter-dialog form button,.inv-filter-dialog form a{min-height:42px}
.inv-filter-dialog form a.inv-clear{display:inline-flex;align-items:center;justify-content:center;padding:10px 16px;border:1px solid #b9d4bf;border-radius:10px;background:#f0f7f1;color:#174b32!important;font-size:12px;font-weight:850;text-decoration:none!important;text-align:center}
.inv-form-dialog{width:min(760px,calc(100% - 18px));max-height:90vh;overflow:auto;border:1px solid #dce8de;border-radius:20px;padding:22px;background:#fff;box-shadow:0 28px 90px #102d1c55}
.inv-form-dialog h2{color:#1d5033;font-size:20px}
.inv-form-dialog .fields,.inv-form-dialog .form-grid,.inv-form-dialog .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}
.inv-form-dialog .actions{display:flex;justify-content:flex-end;gap:10px;margin-top:16px}
@media(max-width:700px){.inv-workspace .page-heading{align-items:flex-start;flex-direction:column;padding:18px 16px;border-radius:16px}.inv-workspace .page-heading>.btn,.inv-workspace .page-heading>a.btn{width:100%}.inv-workspace .stats{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}.inv-workspace .stats>div{min-height:88px;padding:13px 12px 12px 15px!important}.inv-workspace .stats strong{font-size:23px!important}.inv-workspace .panel{padding:12px!important;border-radius:14px!important}.inv-workspace .scroll{border-radius:10px}.inv-workspace table{min-width:760px}.inv-filter-dialog{border-radius:17px}.inv-filter-dialog .inv-dialog-content{padding:15px}.inv-filter-dialog form,.inv-form-dialog .fields,.inv-form-dialog .form-grid,.inv-form-dialog .grid{grid-template-columns:1fr}.inv-form-dialog{padding:17px;border-radius:17px}}
@media(prefers-reduced-motion:reduce){.inv-workspace *,.inv-filter-dialog *{transition:none!important;scroll-behavior:auto!important}}
@media print{.inv-filter-trigger,.inv-filter-dialog,.no-print{display:none!important}}
</style>
<script>
(function(){function setup(){document.querySelectorAll('.inventory-page,.inv-movements,.inv-req,.inv-report').forEach(function(page){page.classList.add('inv-workspace');var heading=page.querySelector('.page-heading');if(!heading)return;var form=page.querySelector('form[method="get"]');if(form&&!form.dataset.popupReady){form.dataset.popupReady='1';var dialog=document.createElement('dialog');dialog.className='inv-filter-dialog';var head=document.createElement('div');head.className='inv-dialog-head';head.innerHTML='<strong>Filter this page</strong><button type="button" aria-label="Close filters">×</button>';head.querySelector('button').addEventListener('click',function(){dialog.close()});var content=document.createElement('div');content.className='inv-dialog-content';form.parentNode.insertBefore(dialog,form);content.appendChild(form);dialog.appendChild(head);dialog.appendChild(content);page.appendChild(dialog);form.querySelectorAll('a.btn-light').forEach(function(a){a.classList.add('inv-clear');if(/^(Clear|Clear filters)$/i.test(a.textContent.trim()))a.textContent='Clear filters'});var trigger=document.createElement('button');trigger.type='button';trigger.className='inv-filter-trigger';trigger.textContent='Filters';trigger.addEventListener('click',function(){dialog.showModal()});heading.appendChild(trigger);dialog.addEventListener('click',function(e){if(e.target===dialog)dialog.close()})}})}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);else setup()})(); 
</script>
"""
    return _school_page(request, title, body + shared)


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
        return _inventory_page(request, "Inventory Register", body)
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
        return _inventory_page(request, "Stock Receipts & Issues", body)
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
        counts = cur.execute("SELECT COUNT(*) total, SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END) pending, SUM(CASE WHEN status='Approved' THEN 1 ELSE 0 END) approved, SUM(CASE WHEN status='Rejected' THEN 1 ELSE 0 END) rejected, SUM(CASE WHEN status='Issued' THEN 1 ELSE 0 END) issued FROM inventory_requisitions WHERE school_id=?",(sid,)).fetchone()
        opts = "".join(f"<option value='{int(x['id'])}'>{escape(str(x['item_code'] or ''))} — {escape(str(x['item_name'] or ''))} (balance {float(x['quantity'] or 0):g})</option>" for x in items)
        trs = ""
        for x in rows:
            action = ""
            if x["status"] == "Pending":
                action = f"""<form method="post" action="/app/inventory/requisitions/review"><input type="hidden" name="requisition_id" value="{int(x['id'])}"><input type="hidden" name="decision" value="Approved"><input name="decision_notes" placeholder="Approval note"><button class="btn">Approve</button></form><form method="post" action="/app/inventory/requisitions/review"><input type="hidden" name="requisition_id" value="{int(x['id'])}"><input type="hidden" name="decision" value="Rejected"><input name="decision_notes" placeholder="Reason required"><button class="btn btn-light">Reject</button></form>"""
            elif x["status"] == "Approved":
                action = f"""<form method="post" action="/app/inventory/requisitions/issue"><input type="hidden" name="requisition_id" value="{int(x['id'])}"><input name="issue_reference" placeholder="Issue voucher"><button class="btn">Issue stock</button></form>"""
            trs += f"<tr><td>REQ-{int(x['id']):05d}<small>{escape(str(x['requested_date'] or ''))}</small></td><td>{escape(str(x['item_name'] or ''))}<small>{escape(str(x['item_code'] or ''))}</small></td><td>{float(x['quantity'] or 0):g} {escape(str(x['unit'] or ''))}</td><td>{escape(str(x['purpose'] or ''))}</td><td>{escape(str(x['requested_by'] or ''))}</td><td>{escape(str(x['status'] or ''))}<small>{escape(str(x['decision_notes'] or ''))}</small><small>Reviewed by {escape(str(x['reviewed_by'] or '—'))} · {escape(str(x['reviewed_at'] or ''))}</small></td><td>{action}</td></tr>"
        trs = trs or "<tr><td colspan='7'>No requisitions found.</td></tr>"
        body = f"""
<div class="page inv-req"><style>
.inv-req{{width:100%;max-width:none}}.inv-req .stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}}.inv-req .stats>div,.inv-req .panel{{background:#fff;border:1px solid #e3ebe5;border-radius:14px;padding:15px}}.inv-req .stats span,.inv-req small{{display:block;color:#718078;font-size:12px}}.inv-req .stats strong{{font-size:24px;color:#174b35}}.inv-req .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.inv-req label{{display:grid;gap:6px;font-size:12px}}.inv-req input,.inv-req select,.inv-req textarea{{width:100%;min-height:39px;padding:8px;border:1px solid #dce6df;border-radius:9px;background:#fff}}.inv-req .wide{{grid-column:1/-1}}.inv-req .scroll{{overflow:auto;width:100%}}.inv-req table{{width:100%;min-width:1050px;border-collapse:collapse}}.inv-req th,.inv-req td{{padding:10px;border-bottom:1px solid #edf1ee;text-align:left;font-size:13px;vertical-align:top}}.inv-req th{{background:#f7faf8}}.inv-req form{{margin:0 0 5px}}@media(max-width:700px){{.inv-req .stats,.inv-req .grid{{grid-template-columns:1fr}}.inv-req .wide{{grid-column:auto}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">INVENTORY &amp; STORES / STOCK CONTROL</div><h1>Stock Requisitions &amp; Approvals</h1><div>Submit stock requests, approve or reject them, and issue approved quantities with an auditable ledger.</div></div><a class="btn btn-light" href="/app/inventory/transactions">Stock Receipts &amp; Issues</a></div>
<div class="stats"><div><span>Total requests</span><strong>{int(counts['total'] or 0)}</strong></div><div><span>Pending review</span><strong>{int(counts['pending'] or 0)}</strong></div><div><span>Approved</span><strong>{int(counts['approved'] or 0)}</strong></div><div><span>Rejected</span><strong>{int(counts['rejected'] or 0)}</strong></div><div><span>Issued</span><strong>{int(counts['issued'] or 0)}</strong></div></div>
<section class="panel"><h2>New stock requisition</h2><form method="post" action="/app/inventory/requisitions/create" class="grid"><label class="wide">Item *<select name="item_id" required><option value="">Select item</option>{opts}</select></label><label>Quantity *<input type="number" name="quantity" min="0.01" step="0.01" required></label><label>Requested by<input name="requested_by" value="{escape(str(request.session.get('name') or request.session.get('email') or ''),quote=True)}" readonly></label><label class="wide">Purpose *<textarea name="purpose" required maxlength="1000"></textarea></label><div class="wide"><button class="btn">Submit request</button></div></form></section>
<section class="panel" style="margin-top:16px"><form method="get" class="grid"><label>Search<input name="q" value="{escape(q,quote=True)}" placeholder="Item, requester or purpose"></label><label>Status<select name="status"><option value="All">All</option><option value="Pending" {'selected' if status=='Pending' else ''}>Pending</option><option value="Approved" {'selected' if status=='Approved' else ''}>Approved</option><option value="Rejected" {'selected' if status=='Rejected' else ''}>Rejected</option><option value="Issued" {'selected' if status=='Issued' else ''}>Issued</option></select></label><div class="wide"><button class="btn">Filter</button> <a class="btn btn-light" href="/app/inventory/requisitions">Clear</a></div></form><div class="scroll"><table><thead><tr><th>Request</th><th>Item</th><th>Quantity</th><th>Purpose</th><th>Requester</th><th>Status / decision</th><th>Actions</th></tr></thead><tbody>{trs}</tbody></table></div></section></div>
"""
        return _inventory_page(request, "Stock Requisitions & Approvals", body)
    finally:
        con.close()


@router.post("/app/inventory/requisitions/create")
def inventory_requisition_create(request: Request, item_id: int = Form(...), quantity: float = Form(...), purpose: str = Form(...), requested_by: str = Form("")):
    sid, err = _guard(request, "inventory.manage")
    if err: return err
    if not math.isfinite(quantity) or quantity <= 0 or not purpose.strip(): return HTMLResponse("Enter a finite positive quantity and purpose.",400)
    con = _db()
    try:
        cur = con.cursor(); _schema(cur); _requisition_schema(cur)
        item = cur.execute("SELECT id FROM inventory_items WHERE id=? AND school_id=? AND status='Active'",(item_id,sid)).fetchone()
        if not item: return HTMLResponse("Active inventory item not found.",404)
        now = datetime.utcnow().isoformat()
        cur.execute("INSERT INTO inventory_requisitions (school_id,item_id,quantity,purpose,requested_by,requested_date,status,created_at) VALUES (?,?,?,?,?,?,?,?)",(sid,item_id,quantity,purpose.strip(),str(request.session.get("name") or request.session.get("email") or "School user"),now[:10],"Pending",now))
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
        if req["item_status"]!="Active" or not math.isfinite(qty) or qty<=0 or not math.isfinite(balance) or balance<qty:
            return HTMLResponse("Item inactive or insufficient stock. No stock was issued.",400)
        now=datetime.utcnow().isoformat(); new_balance=balance-qty
        cur.execute(
            "UPDATE inventory_items SET quantity=?,updated_at=? WHERE id=? AND school_id=? AND status='Active' AND quantity=? AND quantity>=?",
            (new_balance,now,req["item_id"],sid,balance,qty)
        )
        if cur.rowcount != 1:
            con.rollback()
            return HTMLResponse("Stock changed during issue processing. Refresh and retry; no stock was issued.",409)
        cur.execute("INSERT INTO inventory_transactions (school_id,item_id,transaction_type,quantity,balance_after,reference_no,movement_date,notes,recorded_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(sid,req["item_id"],"Issue",qty,new_balance,issue_reference.strip() or ("REQ-%05d" % requisition_id),now[:10],"Issued against approved requisition REQ-%05d: %s" % (requisition_id,req["purpose"]),str(request.session.get("name") or request.session.get("email") or ""),now))
        cur.execute("UPDATE inventory_requisitions SET status='Issued',issued_at=?,issue_reference=? WHERE id=? AND school_id=? AND status='Approved'",(now,issue_reference.strip(),requisition_id,sid))
        if cur.rowcount != 1: con.rollback(); return HTMLResponse("Request changed; no stock was issued. Refresh and retry.",409)
        con.commit()
    except Exception: con.rollback(); raise
    finally: con.close()
    return RedirectResponse("/app/inventory/requisitions",303)


@router.get("/app/inventory/reports", response_class=HTMLResponse)
def inventory_reports(request: Request, start_date: str = "", end_date: str = "", category: str = ""):
    sid, err = _guard(request)
    if err: return err
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        _transaction_schema(cur)
        con.commit()
        items = cur.execute("SELECT * FROM inventory_items WHERE school_id=? AND status='Active' ORDER BY category,item_name",(sid,)).fetchall()
        selected_category = category.strip()
        categories = sorted({str(x["category"] or "Uncategorised") for x in items})
        stock_rows = [x for x in items if not selected_category or str(x["category"] or "Uncategorised")==selected_category]
        low_rows = [x for x in stock_rows if float(x["quantity"] or 0) <= float(x["reorder_level"] or 0)]
        where, params = ["t.school_id=?"], [sid]
        if start_date: where.append("t.movement_date>=?"); params.append(start_date)
        if end_date: where.append("t.movement_date<=?"); params.append(end_date)
        if selected_category: where.append("i.category=?"); params.append("" if selected_category=="Uncategorised" else selected_category)
        movements = cur.execute("SELECT t.*,i.item_code,i.item_name,i.category,i.unit FROM inventory_transactions t JOIN inventory_items i ON i.id=t.item_id AND i.school_id=t.school_id WHERE "+" AND ".join(where)+" ORDER BY t.movement_date DESC,t.id DESC LIMIT 1000",tuple(params)).fetchall()
        received=sum(float(x["quantity"] or 0) for x in movements if str(x["transaction_type"]).lower() in ("receive","adjustment in"))
        issued=sum(float(x["quantity"] or 0) for x in movements if str(x["transaction_type"]).lower() in ("issue","adjustment out"))
        total_qty=sum(float(x["quantity"] or 0) for x in stock_rows)
        cats={}
        for x in stock_rows:
            k=str(x["category"] or "Uncategorised"); cats[k]=cats.get(k,0)+1
        cat_html="".join("<tr><td>"+escape(k)+"</td><td>"+str(v)+"</td></tr>" for k,v in sorted(cats.items())) or "<tr><td colspan='2'>No categories.</td></tr>"
        low_html="".join("<tr><td>"+escape(str(x["item_code"]))+"</td><td>"+escape(str(x["item_name"]))+"</td><td>"+escape(str(x["category"] or "Uncategorised"))+"</td><td>"+format(float(x["quantity"] or 0),".2f")+"</td><td>"+format(float(x["reorder_level"] or 0),".2f")+"</td></tr>" for x in low_rows) or "<tr><td colspan='5'>No items at or below reorder level.</td></tr>"
        move_html="".join("<tr><td>"+escape(str(x["movement_date"] or ""))+"</td><td>"+escape(str(x["item_code"] or ""))+" — "+escape(str(x["item_name"] or ""))+"</td><td>"+escape(str(x["transaction_type"] or ""))+"</td><td>"+format(float(x["quantity"] or 0),".2f")+" "+escape(str(x["unit"] or ""))+"</td><td>"+format(float(x["balance_after"] or 0),".2f")+"</td><td>"+escape(str(x["reference_no"] or ""))+"</td></tr>" for x in movements) or "<tr><td colspan='6'>No movements found.</td></tr>"
        cat_options="<option value=''>All categories</option>"+"".join("<option value='"+escape(c,quote=True)+"'"+(" selected" if c==selected_category else "")+">"+escape(c)+"</option>" for c in categories)
        body=f"""
<div class="page inv-report"><style>
.inv-report .stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}}.inv-report .stats>div,.inv-report .panel{{background:#fff;border:1px solid #e3ebe5;border-radius:14px;padding:15px}}.inv-report .stats span,.inv-report small{{display:block;color:#718078;font-size:12px}}.inv-report .stats strong{{font-size:24px;color:#174b35}}.inv-report .filters{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) auto;gap:10px;align-items:end}}.inv-report label{{display:grid;gap:6px;font-size:12px}}.inv-report input,.inv-report select{{width:100%;min-height:39px;padding:8px;border:1px solid #dce6df;border-radius:9px;background:#fff}}.inv-report .scroll{{overflow:auto;width:100%;margin-top:10px}}.inv-report table{{width:100%;min-width:680px;border-collapse:collapse}}.inv-report th,.inv-report td{{padding:10px;border-bottom:1px solid #edf1ee;text-align:left;font-size:13px}}.inv-report th{{background:#f7faf8}}@media(max-width:700px){{.inv-report .stats{{grid-template-columns:repeat(2,minmax(0,1fr))}}.inv-report .filters{{grid-template-columns:1fr}}}}@media print{{.inv-report .no-print{{display:none!important}}.inv-report .panel{{break-inside:avoid}}}}
</style>
<div class="page-heading"><div><div class="lib-eyebrow">INVENTORY &amp; STORES / REPORTING</div><h1>Stock Reports</h1><div>Stock balances, reorder alerts, category coverage and movement history.</div></div><button class="btn no-print" onclick="window.print()">Print Report</button></div>
<section class="panel no-print"><form method="get" class="filters"><label>From date<input type="date" name="start_date" value="{escape(start_date,quote=True)}"></label><label>To date<input type="date" name="end_date" value="{escape(end_date,quote=True)}"></label><label>Category<select name="category">{cat_options}</select></label><button class="btn">Apply Filters</button></form></section>
<div class="stats"><div><span>Active stock items</span><strong>{len(stock_rows)}</strong></div><div><span>Total units in stock</span><strong>{total_qty:,.2f}</strong></div><div><span>Reorder alerts</span><strong>{len(low_rows)}</strong></div><div><span>Movement entries</span><strong>{len(movements)}</strong></div></div>
<section class="panel"><h2>Movement summary</h2><div>Received / adjustment in: <b>{received:,.2f}</b> &nbsp; | &nbsp; Issued / adjustment out: <b>{issued:,.2f}</b></div><small>Latest 1,000 matching movements.</small></section>
<section class="panel" style="margin-top:14px"><h2>Low-stock and reorder alerts</h2><div class="scroll"><table><thead><tr><th>Item code</th><th>Item</th><th>Category</th><th>Balance</th><th>Reorder level</th></tr></thead><tbody>{low_html}</tbody></table></div></section>
<section class="panel" style="margin-top:14px"><h2>Stock by category</h2><div class="scroll"><table><thead><tr><th>Category</th><th>Active items</th></tr></thead><tbody>{cat_html}</tbody></table></div></section>
<section class="panel" style="margin-top:14px"><h2>Stock movement ledger</h2><div class="scroll"><table><thead><tr><th>Date</th><th>Item</th><th>Movement</th><th>Quantity</th><th>Balance after</th><th>Reference</th></tr></thead><tbody>{move_html}</tbody></table></div></section></div>
"""
        return _inventory_page(request, "Stock Reports", body)
    finally:
        con.close()
