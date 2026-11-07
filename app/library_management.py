from datetime import datetime
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.new_ui import _audit, _db, _require_permission, _school_page, _school_session

router = APIRouter()


def _library_guard(request, permission="library.view"):
    sid = _school_session(request)
    if not sid:
        return None, RedirectResponse("/", 303)
    if not _require_permission(request, sid, permission):
        return None, HTMLResponse("You do not have permission to access the library workspace.", 403)
    return sid, None


def _library_page(request, title, body):
    shared = """
<style>
.library-page{max-width:none!important;width:100%;padding-bottom:28px;color:#243b2d}
.library-page .lib-heading{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:8px 2px 17px;margin-bottom:8px;border-bottom:1px solid #e3ece4}
.library-page .lib-heading h1{font-size:clamp(23px,3vw,30px);font-weight:800;color:#214d34;margin:5px 0}
.library-page .lib-eyebrow{font-size:10px;letter-spacing:1.5px;font-weight:800;color:#528263}
.library-page .lib-muted{color:#78877c;font-size:12px;line-height:1.5}
.library-page .lib-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:17px 0}
.library-page .lib-kpis>div{background:linear-gradient(145deg,#fff,#f8fbf8);border:1px solid #e1ebe2;border-radius:14px;padding:15px 17px;box-shadow:0 3px 12px #1d4b2b0b}
.library-page .lib-kpis span{display:block;color:#718176;font-size:11px;font-weight:650}
.library-page .lib-kpis strong{display:block;color:#245b39;font-size:25px;margin-top:7px;font-weight:800}
.library-page .card.lib-table-card,.library-page .card.lib-filter-card{background:#fff;border:1px solid #e4ece5;border-radius:15px;box-shadow:0 4px 18px #1840250b;padding:16px;margin:0 0 14px}
.library-page .lib-table-card>.page-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 12px}
.library-page .lib-table-card h2{font-size:15px;font-weight:800;color:#2c5038;margin:0}
.library-page .lib-table-scroll{overflow:auto;max-width:100%;width:100%;border:1px solid #e8eee9;border-radius:10px;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}
.library-page .lib-table-scroll table{border-collapse:separate;border-spacing:0;width:100%;min-width:720px}
.library-page .lib-table-scroll th{background:#f0f6f0;color:#496451;font-size:10px;text-transform:uppercase;letter-spacing:.55px;font-weight:800;padding:12px 13px;white-space:nowrap;border-bottom:1px solid #dfe9e0}
.library-page .lib-table-scroll td{padding:11px 13px;border-bottom:1px solid #edf1ed;color:#405448;font-size:12px;vertical-align:middle}
.library-page .lib-table-scroll tbody tr:last-child td{border-bottom:0}
.library-page .lib-table-scroll tbody tr:hover{background:#f8fbf8}
.library-page .lib-status{display:inline-flex;padding:4px 9px;border-radius:30px;background:#e8f4e9;color:#28613d;font-size:10px;font-weight:800;white-space:nowrap}
.library-page .lib-inactive{background:#f1f2ef;color:#6e766f}
.library-page .lib-empty{text-align:center!important;padding:32px 16px!important;color:#879389!important}
.library-page .lib-edit{border:1px solid #d6e5d8;background:#f3f8f3;color:#28613e;border-radius:8px;padding:7px 11px;font-size:11px;font-weight:800;cursor:pointer}
.library-page .btn{border-radius:9px;font-weight:750;box-shadow:none}
.library-page .lib-filter-trigger{border:1px solid #d5e4d7;background:#f2f8f2;color:#285a3a;padding:9px 13px;border-radius:9px;font-size:12px;font-weight:800;cursor:pointer}
.lib-filter-dialog{width:min(760px,calc(100% - 24px));max-height:85vh;overflow:auto;border:1px solid #dce8de;border-radius:17px;padding:0;box-shadow:0 24px 80px #0f281a47}
.lib-filter-dialog::backdrop,.lib-dialog::backdrop{background:#0d1f1385;backdrop-filter:blur(3px)}
.lib-filter-dialog .lib-filter-dialog-head{position:sticky;top:0;background:#f5faf5;border-bottom:1px solid #e1ebe2;padding:15px 18px;display:flex;justify-content:space-between;align-items:center}
.lib-filter-dialog .lib-filter-dialog-head strong{font-size:15px;color:#28543a}
.lib-filter-dialog .lib-filter-dialog-head button{border:0;border-radius:50%;width:31px;height:31px;background:#e5efe6;color:#315b3e;font-size:21px;cursor:pointer}
.lib-filter-dialog .lib-filter-dialog-content{padding:17px}
.lib-filter-dialog .lib-filter-dialog-content .lib-filter-card{display:block!important;margin:0!important;padding:0!important;border:0!important;box-shadow:none!important;background:transparent!important}
.lib-filter-dialog .lib-filter-dialog-content form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;align-items:end}
.lib-filter-dialog .lib-filter-dialog-content form label{min-width:0;display:flex;flex-direction:column;gap:6px;font-size:11px;font-weight:750;color:#40594a}
.lib-filter-dialog .field,.lib-dialog .field{width:100%;border:1px solid #dce6dd;border-radius:8px;padding:10px 11px;background:#fff;min-height:39px}
.lib-dialog{max-width:calc(100% - 24px);max-height:88vh;overflow:auto;border:1px solid #dce8de;border-radius:17px}
.lib-dialog .lib-dialog-head h2{color:#28543a;font-size:19px}
@media(max-width:700px){.library-page .lib-heading{align-items:flex-start;flex-direction:column}.library-page .lib-kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.library-page .lib-kpis>div{padding:12px}.library-page .lib-kpis strong{font-size:22px}.library-page .card.lib-table-card{padding:11px}.library-page .lib-table-scroll table{min-width:680px}.lib-filter-dialog .lib-filter-dialog-content form{grid-template-columns:1fr}.lib-filter-dialog .lib-filter-dialog-content form>*{grid-column:1!important}}
@media print{.lib-filter-trigger,.lib-filter-dialog,.library-page .lib-heading button{display:none!important}}
</style>
<script>
(function(){function setup(){document.querySelectorAll('.library-page').forEach(function(page){var panel=page.querySelector('.lib-filter-card');if(!panel||panel.dataset.popupReady==='1')return;var heading=page.querySelector('.lib-heading');if(!heading)return;panel.dataset.popupReady='1';var dialog=document.createElement('dialog');dialog.className='lib-filter-dialog';var head=document.createElement('div');head.className='lib-filter-dialog-head';head.innerHTML='<strong>Filter this page</strong><button type="button" aria-label="Close filters">×</button>';head.querySelector('button').addEventListener('click',function(){dialog.close()});var content=document.createElement('div');content.className='lib-filter-dialog-content';content.appendChild(panel);dialog.appendChild(head);dialog.appendChild(content);page.appendChild(dialog);var trigger=document.createElement('button');trigger.type='button';trigger.className='lib-filter-trigger';trigger.innerHTML='&#9881; Filters';trigger.addEventListener('click',function(){dialog.showModal()});heading.appendChild(trigger);dialog.addEventListener('click',function(e){if(e.target===dialog)dialog.close()})})}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);else setup()})();
</script>
"""
    return _school_page(request, title, body + shared)


def _ensure_book_catalogue(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS library_books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        author TEXT DEFAULT '',
        isbn TEXT DEFAULT '',
        category TEXT DEFAULT '',
        publisher TEXT DEFAULT '',
        publication_year INTEGER,
        shelf_location TEXT DEFAULT '',
        total_copies INTEGER NOT NULL DEFAULT 1,
        available_copies INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'Active',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(school_id, isbn)
    )""")


@router.get("/app/library/catalogue", response_class=HTMLResponse)
def library_book_catalogue(
    request: Request,
    q: str = "",
    category: str = "",
    status: str = "Active",
):
    sid, error = _library_guard(request)
    if error:
        return error
    con = _db()
    cur = con.cursor()
    _ensure_book_catalogue(cur)
    con.commit()
    filters = ["school_id=?"]
    params = [sid]
    if q.strip():
        term = "%" + q.strip() + "%"
        filters.append("(title LIKE ? OR author LIKE ? OR isbn LIKE ? OR publisher LIKE ? OR shelf_location LIKE ?)")
        params.extend([term] * 5)
    if category.strip():
        filters.append("category=?")
        params.append(category.strip())
    if status in ("Active", "Archived"):
        filters.append("status=?")
        params.append(status)
    rows = cur.execute(
        "SELECT * FROM library_books WHERE " + " AND ".join(filters) + " ORDER BY LOWER(title), LOWER(author)",
        tuple(params),
    ).fetchall()
    categories = cur.execute(
        "SELECT DISTINCT category FROM library_books WHERE school_id=? AND COALESCE(category,'')<>'' ORDER BY category",
        (sid,),
    ).fetchall()
    total_titles = cur.execute("SELECT COUNT(*) AS n FROM library_books WHERE school_id=?", (sid,)).fetchone()["n"]
    total_copies = cur.execute("SELECT COALESCE(SUM(total_copies),0) AS n FROM library_books WHERE school_id=? AND status='Active'", (sid,)).fetchone()["n"]
    available = cur.execute("SELECT COALESCE(SUM(available_copies),0) AS n FROM library_books WHERE school_id=? AND status='Active'", (sid,)).fetchone()["n"]
    category_options = "<option value=''>All categories</option>" + "".join(
        f"<option value='{escape(str(x['category']), quote=True)}' {'selected' if category == str(x['category']) else ''}>{escape(str(x['category']))}</option>"
        for x in categories
    )
    rows_html = "".join(
        f"<tr><td><b>{escape(str(x['title'] or ''))}</b><div class='lib-muted'>{escape(str(x['publisher'] or ''))}</div></td>"
        f"<td>{escape(str(x['author'] or '—'))}</td><td>{escape(str(x['isbn'] or '—'))}</td>"
        f"<td>{escape(str(x['category'] or '—'))}</td><td>{escape(str(x['shelf_location'] or '—'))}</td>"
        f"<td class='lib-num'>{int(x['total_copies'] or 0)}</td><td class='lib-num'>{int(x['available_copies'] or 0)}</td>"
        f"<td><span class='lib-status {'lib-inactive' if x['status'] != 'Active' else ''}'>{escape(str(x['status'] or 'Active'))}</span></td>"
        f"<td><button class='lib-edit' type='button' onclick='editLibraryBook(this)' "
        f"data-id='{int(x['id'])}' data-title='{escape(str(x['title'] or ''), quote=True)}' "
        f"data-author='{escape(str(x['author'] or ''), quote=True)}' data-isbn='{escape(str(x['isbn'] or ''), quote=True)}' "
        f"data-category='{escape(str(x['category'] or ''), quote=True)}' data-publisher='{escape(str(x['publisher'] or ''), quote=True)}' "
        f"data-year='{escape(str(x['publication_year'] or ''), quote=True)}' data-shelf='{escape(str(x['shelf_location'] or ''), quote=True)}' "
        f"data-total='{int(x['total_copies'] or 0)}' data-available='{int(x['available_copies'] or 0)}' "
        f"data-status='{escape(str(x['status'] or 'Active'), quote=True)}' data-notes='{escape(str(x['notes'] or ''), quote=True)}'>Edit</button></td></tr>"
        for x in rows
    )
    if not rows_html:
        rows_html = "<tr><td colspan='9' class='lib-empty'>No books match these filters. Add a title to start the catalogue.</td></tr>"
    body = f"""
<div class="page library-page">
  <div class="page-heading lib-heading">
    <div><div class="lib-eyebrow">LIBRARY MANAGER / COLLECTION</div><h1>Book Catalogue</h1>
      <div class="lib-muted">Maintain the school's book collection, copy counts and shelf locations.</div></div>
    <button class="btn" type="button" onclick="openLibraryBook()">Add Book</button>
  </div>
  <div class="lib-kpis">
    <div><span>Book titles</span><strong>{int(total_titles or 0)}</strong></div>
    <div><span>Total copies</span><strong>{int(total_copies or 0)}</strong></div>
    <div><span>Available copies</span><strong>{int(available or 0)}</strong></div>
  </div>
  <section class="card lib-filter-card"><form method="get" class="lib-filters">
    <label>Search catalogue<input class="field" name="q" value="{escape(q, quote=True)}" placeholder="Title, author, ISBN, publisher or shelf"></label>
    <label>Category<select class="field" name="category">{category_options}</select></label>
    <label>Status<select class="field" name="status"><option value="Active" {'selected' if status == 'Active' else ''}>Active</option><option value="Archived" {'selected' if status == 'Archived' else ''}>Archived</option><option value="All" {'selected' if status == 'All' else ''}>All</option></select></label>
    <button class="btn">Apply Filters</button><a class="btn btn-light" href="/app/library/catalogue">Clear</a>
  </form></section>
  <section class="card lib-table-card"><div class="page-heading"><h2>Collection register</h2><span class="lib-muted">{len(rows)} title(s) shown</span></div>
    <div class="lib-table-scroll"><table><thead><tr><th>Book title / Publisher</th><th>Author</th><th>ISBN</th><th>Category</th><th>Shelf</th><th>Total</th><th>Available</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows_html}</tbody></table></div>
  </section>
</div>
<dialog id="libraryBookDialog" class="lib-dialog"><form method="post" action="/app/library/catalogue/save" id="libraryBookForm">
  <div class="lib-dialog-head"><div><div class="lib-eyebrow">LIBRARY COLLECTION</div><h2 id="libraryBookDialogTitle">Add book</h2></div><button type="button" class="lib-close" onclick="document.getElementById('libraryBookDialog').close()">×</button></div>
  <input type="hidden" name="book_id" id="libBookId" value="0">
  <div class="lib-form-grid">
    <label>Book title *<input class="field" name="title" id="libTitle" required maxlength="240"></label>
    <label>Author<input class="field" name="author" id="libAuthor" maxlength="180"></label>
    <label>ISBN / Accession number<input class="field" name="isbn" id="libIsbn" maxlength="80"></label>
    <label>Category<input class="field" name="category" id="libCategory" maxlength="100" placeholder="e.g. Mathematics"></label>
    <label>Publisher<input class="field" name="publisher" id="libPublisher" maxlength="180"></label>
    <label>Publication year<input class="field" type="number" name="publication_year" id="libYear" min="1000" max="2100"></label>
    <label>Shelf / Location<input class="field" name="shelf_location" id="libShelf" maxlength="100"></label>
    <label>Total copies<input class="field" type="number" name="total_copies" id="libTotal" min="0" value="1" required></label>
    <label>Available copies<input class="field" type="number" name="available_copies" id="libAvailable" min="0" value="1" required></label>
    <label>Status<select class="field" name="status" id="libStatus"><option>Active</option><option>Archived</option></select></label>
    <label class="lib-notes">Notes<textarea class="field" name="notes" id="libNotes" rows="2"></textarea></label>
  </div>
  <div class="lib-dialog-actions"><button type="button" class="btn btn-light" onclick="document.getElementById('libraryBookDialog').close()">Cancel</button><button class="btn" type="submit">Save Book</button></div>
</form></dialog>
<script>
function openLibraryBook(){{document.getElementById('libraryBookForm').reset();document.getElementById('libBookId').value='0';document.getElementById('libTotal').value='1';document.getElementById('libAvailable').value='1';document.getElementById('libraryBookDialogTitle').textContent='Add book';document.getElementById('libraryBookDialog').showModal();}}
function editLibraryBook(button){{const d=button.dataset;const fields={{id:'libBookId',title:'libTitle',author:'libAuthor',isbn:'libIsbn',category:'libCategory',publisher:'libPublisher',year:'libYear',shelf:'libShelf',total:'libTotal',available:'libAvailable',status:'libStatus',notes:'libNotes'}};Object.keys(fields).forEach(k=>{{const el=document.getElementById(fields[k]);if(el)el.value=d[k]||'';}});document.getElementById('libraryBookDialogTitle').textContent='Edit book';document.getElementById('libraryBookDialog').showModal();}}
document.getElementById('libraryBookForm').addEventListener('submit',function(e){{const total=Number(document.getElementById('libTotal').value),available=Number(document.getElementById('libAvailable').value);if(available>total){{e.preventDefault();alert('Available copies cannot exceed total copies.');}}}});
</script>
<style>
.library-page{{max-width:none;width:100%}}.lib-heading{{align-items:center}}.lib-eyebrow{{font-size:11px;letter-spacing:1.3px;font-weight:800;color:#397653}}.lib-muted{{color:#718176;font-size:12px}}.lib-kpis{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:16px 0}}.lib-kpis>div{{background:#fff;border:1px solid #e2ebe3;border-radius:14px;padding:16px 18px;box-shadow:0 3px 12px #1c4a2b0a}}.lib-kpis span{{display:block;color:#718176;font-size:12px}}.lib-kpis strong{{display:block;color:#205d3b;font-size:25px;margin-top:5px}}.lib-filter-card{{margin-bottom:14px}}.lib-filters{{display:grid;grid-template-columns:minmax(220px,2fr) repeat(2,minmax(140px,1fr)) auto auto;gap:12px;align-items:end}}.lib-filters label,.lib-form-grid label{{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:700;color:#40594a}}.lib-table-scroll{{overflow:auto;width:100%}}.lib-table-scroll table{{width:100%;min-width:1050px;border-collapse:collapse}}.lib-table-scroll th,.lib-table-scroll td{{padding:11px 12px;border-bottom:1px solid #e8eee9;text-align:left;font-size:12px}}.lib-table-scroll th{{background:#f3f8f3;color:#476251;white-space:nowrap}}.lib-num{{text-align:center!important;font-weight:700}}.lib-status{{display:inline-block;padding:4px 8px;border-radius:20px;background:#e9f5ec;color:#276640;font-size:11px;font-weight:800}}.lib-inactive{{background:#f1f1f1;color:#68716b}}.lib-edit{{border:1px solid #d7e5da;background:#f5faf5;color:#286342;border-radius:8px;padding:6px 10px;font-weight:700;cursor:pointer}}.lib-empty{{text-align:center!important;padding:30px!important;color:#748278}}.lib-dialog{{width:min(760px,calc(100% - 24px));border:0;border-radius:18px;padding:0;box-shadow:0 20px 70px #12271a44}}.lib-dialog::backdrop{{background:#10201780;backdrop-filter:blur(3px)}}.lib-dialog form{{padding:22px}}.lib-dialog-head{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px}}.lib-dialog-head h2{{margin:4px 0}}.lib-close{{border:0;background:#edf4ee;border-radius:50%;width:34px;height:34px;font-size:22px;cursor:pointer}}.lib-form-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}}.lib-notes{{grid-column:1/-1}}.lib-dialog-actions{{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}}.lib-dialog .field{{width:100%}}@media(max-width:720px){{.lib-kpis{{grid-template-columns:1fr}}.lib-filters{{grid-template-columns:1fr 1fr}}.lib-filters label:first-child{{grid-column:1/-1}}.lib-form-grid{{grid-template-columns:1fr}}.lib-notes{{grid-column:auto}}}}
</style>
"""
    con.close()
    return _library_page(request, "Book Catalogue", body)


@router.post("/app/library/catalogue/save")
async def library_book_save(
    request: Request,
    book_id: int = Form(0),
    title: str = Form(...),
    author: str = Form(""),
    isbn: str = Form(""),
    category: str = Form(""),
    publisher: str = Form(""),
    publication_year: str = Form(""),
    shelf_location: str = Form(""),
    total_copies: int = Form(1),
    available_copies: int = Form(1),
    status: str = Form("Active"),
    notes: str = Form(""),
):
    sid, error = _library_guard(request, "library.edit")
    if error:
        return error
    title = title.strip()
    if not title:
        return HTMLResponse("Book title is required.", 400)
    total_copies = max(0, int(total_copies))
    available_copies = max(0, int(available_copies))
    if available_copies > total_copies:
        return HTMLResponse("Available copies cannot exceed total copies.", 400)
    year = int(publication_year) if publication_year.isdigit() and 1000 <= int(publication_year) <= 2100 else None
    state = "Archived" if status == "Archived" else "Active"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    con = _db()
    cur = con.cursor()
    _ensure_book_catalogue(cur)
    try:
        if book_id:
            cur.execute(
                """UPDATE library_books SET title=?,author=?,isbn=?,category=?,publisher=?,
                   publication_year=?,shelf_location=?,total_copies=?,available_copies=?,
                   status=?,notes=?,updated_at=? WHERE id=? AND school_id=?""",
                (title, author.strip(), isbn.strip(), category.strip(), publisher.strip(), year,
                 shelf_location.strip(), total_copies, available_copies, state, notes.strip(), now, book_id, sid),
            )
            if cur.rowcount == 0:
                con.rollback()
                return HTMLResponse("The selected book could not be found.", 404)
            action = "LIBRARY_BOOK_UPDATED"
        else:
            cur.execute(
                """INSERT INTO library_books(school_id,title,author,isbn,category,publisher,
                   publication_year,shelf_location,total_copies,available_copies,status,notes,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, title, author.strip(), isbn.strip(), category.strip(), publisher.strip(), year,
                 shelf_location.strip(), total_copies, available_copies, state, notes.strip(), now, now),
            )
            action = "LIBRARY_BOOK_ADDED"
        _audit(cur, sid, request, action, f"{title} ({isbn.strip() or 'no ISBN'})")
        con.commit()
    except Exception as exc:
        con.rollback()
        if "unique" in str(exc).lower():
            return HTMLResponse("That ISBN / accession number is already used by another book in this school.", 409)
        raise
    finally:
        con.close()
    return RedirectResponse("/app/library/catalogue", 303)


def _ensure_book_copies(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS library_book_copies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        book_id INTEGER NOT NULL,
        accession_no TEXT NOT NULL,
        condition TEXT NOT NULL DEFAULT 'Good',
        copy_status TEXT NOT NULL DEFAULT 'Available',
        acquisition_date TEXT DEFAULT '',
        purchase_cost REAL NOT NULL DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(school_id, accession_no)
    )""")


@router.get("/app/library/register", response_class=HTMLResponse)
def library_book_register(request: Request, q: str = "", status: str = ""):
    sid, error = _library_guard(request)
    if error:
        return error
    con = _db()
    try:
        cur = con.cursor()
        _ensure_book_catalogue(cur)
        _ensure_book_copies(cur)
        con.commit()
        books = cur.execute(
            "SELECT id,title FROM library_books WHERE school_id=? AND status='Active' ORDER BY LOWER(title)",
            (sid,),
        ).fetchall()
        filters = ["c.school_id=?"]
        params = [sid]
        if q.strip():
            term = "%" + q.strip() + "%"
            filters.append("(b.title LIKE ? OR c.accession_no LIKE ? OR c.notes LIKE ?)")
            params.extend([term, term, term])
        if status in ("Available", "Issued", "Damaged", "Lost", "Withdrawn"):
            filters.append("c.copy_status=?")
            params.append(status)
        rows = cur.execute(
            "SELECT c.*,b.title FROM library_book_copies c JOIN library_books b ON b.id=c.book_id AND b.school_id=c.school_id WHERE "
            + " AND ".join(filters) + " ORDER BY LOWER(b.title),LOWER(c.accession_no)",
            tuple(params),
        ).fetchall()
        total = cur.execute("SELECT COUNT(*) AS n FROM library_book_copies WHERE school_id=?", (sid,)).fetchone()["n"]
        available = cur.execute("SELECT COUNT(*) AS n FROM library_book_copies WHERE school_id=? AND copy_status='Available'", (sid,)).fetchone()["n"]
        options = "".join(
            f"<option value='{int(b['id'])}'>{escape(str(b['title']), quote=True)}</option>" for b in books
        ) or "<option value=''>Add a title in Book Catalogue first</option>"
        table = "".join(
            f"<tr><td><b>{escape(str(r['accession_no']))}</b></td><td>{escape(str(r['title']))}</td>"
            f"<td>{escape(str(r['condition']))}</td><td><span class='lib-status'>{escape(str(r['copy_status']))}</span></td>"
            f"<td>{escape(str(r['acquisition_date'] or '—'))}</td><td>{float(r['purchase_cost'] or 0):,.2f}</td>"
            f"<td>{escape(str(r['notes'] or '—'))}</td></tr>" for r in rows
        ) or "<tr><td colspan='7' class='lib-empty'>No physical copies are registered for these filters.</td></tr>"
        body = f"""
<div class="page library-page">
 <div class="page-heading lib-heading"><div><div class="lib-eyebrow">LIBRARY MANAGER / COLLECTION</div><h1>Book Register</h1><div class="lib-muted">Register each physical copy separately and track its accession number, condition and status.</div></div><button class="btn" type="button" onclick="document.getElementById('copyDialog').showModal()">Register Copy</button></div>
 <div class="lib-kpis"><div><span>Registered copies</span><strong>{int(total or 0)}</strong></div><div><span>Available copies</span><strong>{int(available or 0)}</strong></div><div><span>Catalogue titles</span><strong>{len(books)}</strong></div></div>
 <section class="card lib-filter-card"><form method="get" class="lib-filters" style="grid-template-columns:2fr 1fr auto auto"><label>Search<input class="field" name="q" value="{escape(q, quote=True)}" placeholder="Title, accession number or notes"></label><label>Copy status<select class="field" name="status"><option value="">All statuses</option>{''.join(f"<option {'selected' if status == s else ''}>{s}</option>" for s in ('Available','Issued','Damaged','Lost','Withdrawn'))}</select></label><button class="btn">Apply</button><a class="btn btn-light" href="/app/library/register">Clear</a></form></section>
 <section class="card lib-table-card"><div class="page-heading"><h2>Individual copy register</h2><span class="lib-muted">{len(rows)} copy/copies shown</span></div><div class="lib-table-scroll"><table style="min-width:900px"><thead><tr><th>Accession no.</th><th>Book title</th><th>Condition</th><th>Status</th><th>Acquired</th><th>Cost</th><th>Notes</th></tr></thead><tbody>{table}</tbody></table></div></section>
</div>
<dialog id="copyDialog" class="lib-dialog"><form method="post" action="/app/library/register/save"><div class="lib-dialog-head"><div><div class="lib-eyebrow">PHYSICAL COPY</div><h2>Register book copy</h2></div><button type="button" class="lib-close" onclick="document.getElementById('copyDialog').close()">×</button></div>
<div class="lib-form-grid"><label>Catalogue title *<select class="field" name="book_id" required>{options}</select></label><label>Accession number *<input class="field" name="accession_no" required maxlength="80"></label><label>Condition<select class="field" name="condition"><option>New</option><option selected>Good</option><option>Fair</option><option>Poor</option></select></label><label>Status<select class="field" name="copy_status"><option>Available</option><option>Damaged</option><option>Lost</option><option>Withdrawn</option></select></label><label>Acquisition date<input class="field" type="date" name="acquisition_date"></label><label>Purchase cost<input class="field" type="number" min="0" step="0.01" name="purchase_cost" value="0"></label><label class="lib-notes">Notes<textarea class="field" name="notes" rows="2"></textarea></label></div>
<div class="lib-dialog-actions"><button type="button" class="btn btn-light" onclick="document.getElementById('copyDialog').close()">Cancel</button><button class="btn" type="submit" {'disabled' if not books else ''}>Save Copy</button></div></form></dialog>
"""
        con.close()
        return _library_page(request, "Book Register", body)
    except Exception:
        con.close()
        raise


@router.post("/app/library/register/save")
async def library_book_copy_save(
    request: Request,
    book_id: int = Form(...),
    accession_no: str = Form(...),
    condition: str = Form("Good"),
    copy_status: str = Form("Available"),
    acquisition_date: str = Form(""),
    purchase_cost: float = Form(0),
    notes: str = Form(""),
):
    sid, error = _library_guard(request, "library.edit")
    if error:
        return error
    accession_no = accession_no.strip()
    if not accession_no:
        return HTMLResponse("Accession number is required.", 400)
    condition = condition if condition in ("New", "Good", "Fair", "Poor") else "Good"
    copy_status = copy_status if copy_status in ("Available", "Damaged", "Lost", "Withdrawn") else "Available"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    con = _db()
    try:
        cur = con.cursor()
        _ensure_book_catalogue(cur)
        _ensure_book_copies(cur)
        exists = cur.execute("SELECT id FROM library_books WHERE id=? AND school_id=?", (book_id, sid)).fetchone()
        if not exists:
            return HTMLResponse("Select a valid catalogue title.", 400)
        cur.execute(
            """INSERT INTO library_book_copies(school_id,book_id,accession_no,condition,copy_status,
               acquisition_date,purchase_cost,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (sid, book_id, accession_no, condition, copy_status, acquisition_date.strip(),
             max(0, purchase_cost), notes.strip(), now, now),
        )
        _audit(cur, sid, request, "LIBRARY_COPY_REGISTERED", f"{accession_no} / book {book_id}")
        con.commit()
    except Exception as exc:
        con.rollback()
        if "unique" in str(exc).lower():
            return HTMLResponse("That accession number is already registered in this school.", 409)
        raise
    finally:
        con.close()
    return RedirectResponse("/app/library/register", 303)



def _ensure_library_issues(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS library_book_issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        copy_id INTEGER NOT NULL,
        book_id INTEGER NOT NULL,
        borrower_type TEXT NOT NULL,
        borrower_name TEXT NOT NULL,
        borrower_ref TEXT DEFAULT '',
        issue_date TEXT NOT NULL,
        due_date TEXT NOT NULL,
        issued_by TEXT DEFAULT '',
        issue_status TEXT NOT NULL DEFAULT 'Issued',
        returned_at TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")


@router.get("/app/library/issues", response_class=HTMLResponse)
def library_issue_books(request: Request, q: str = "", borrower_type: str = "", status: str = "Issued"):
    sid, error = _library_guard(request)
    if error:
        return error
    con = _db()
    try:
        cur = con.cursor()
        _ensure_book_catalogue(cur)
        _ensure_book_copies(cur)
        _ensure_library_issues(cur)
        con.commit()
        available_copies = cur.execute(
            """SELECT c.id,c.accession_no,b.title FROM library_book_copies c
               JOIN library_books b ON b.id=c.book_id AND b.school_id=c.school_id
               WHERE c.school_id=? AND c.copy_status='Available' AND b.status='Active'
               ORDER BY LOWER(b.title),LOWER(c.accession_no)""",
            (sid,),
        ).fetchall()
        filters = ["i.school_id=?"]
        params = [sid]
        if q.strip():
            term = "%" + q.strip() + "%"
            filters.append("(b.title LIKE ? OR c.accession_no LIKE ? OR i.borrower_name LIKE ? OR i.borrower_ref LIKE ?)")
            params.extend([term] * 4)
        if borrower_type in ("Student", "Staff"):
            filters.append("i.borrower_type=?")
            params.append(borrower_type)
        if status in ("Issued", "Returned", "All"):
            if status != "All":
                filters.append("i.issue_status=?")
                params.append(status)
        else:
            filters.append("i.issue_status='Issued'")
            status = "Issued"
        rows = cur.execute(
            """SELECT i.*,b.title,c.accession_no FROM library_book_issues i
               JOIN library_books b ON b.id=i.book_id AND b.school_id=i.school_id
               JOIN library_book_copies c ON c.id=i.copy_id AND c.school_id=i.school_id
               WHERE """ + " AND ".join(filters) + " ORDER BY i.issue_date DESC,i.id DESC",
            tuple(params),
        ).fetchall()
        outstanding = cur.execute(
            "SELECT COUNT(*) AS n FROM library_book_issues WHERE school_id=? AND issue_status='Issued'",
            (sid,),
        ).fetchone()["n"]
        overdue = cur.execute(
            "SELECT COUNT(*) AS n FROM library_book_issues WHERE school_id=? AND issue_status='Issued' AND due_date<?",
            (sid, datetime.now().date().isoformat()),
        ).fetchone()["n"]
        copy_options = "".join(
            f"<option value='{int(c['id'])}'>{escape(str(c['title']))} — {escape(str(c['accession_no']))}</option>"
            for c in available_copies
        ) or "<option value=''>No available copies — register a copy or process a return first</option>"
        table = "".join(
            f"<tr><td><b>{escape(str(r['title']))}</b><div class='lib-muted'>{escape(str(r['accession_no']))}</div></td>"
            f"<td>{escape(str(r['borrower_name']))}<div class='lib-muted'>{escape(str(r['borrower_type']))} · {escape(str(r['borrower_ref'] or 'No ID recorded'))}</div></td>"
            f"<td>{escape(str(r['issue_date']))}</td><td>{escape(str(r['due_date']))}</td>"
            f"<td><span class='lib-status {'lib-inactive' if r['issue_status'] == 'Returned' else ''}'>{escape(str(r['issue_status']))}</span></td></tr>"
            for r in rows
        ) or "<tr><td colspan='5' class='lib-empty'>No book issues match these filters.</td></tr>"
        body = f"""
<div class="page library-page">
 <div class="page-heading lib-heading"><div><div class="lib-eyebrow">LIBRARY MANAGER / CIRCULATION</div><h1>Issue Books</h1><div class="lib-muted">Issue available physical copies to learners and staff, with a clear due date and borrower record.</div></div><button class="btn" type="button" onclick="document.getElementById('issueDialog').showModal()" {'disabled' if not available_copies else ''}>Issue a Book</button></div>
 <div class="lib-kpis"><div><span>Books currently issued</span><strong>{int(outstanding or 0)}</strong></div><div><span>Overdue issues</span><strong>{int(overdue or 0)}</strong></div><div><span>Copies available to issue</span><strong>{len(available_copies)}</strong></div></div>
 <section class="card lib-filter-card"><form method="get" class="lib-filters" style="grid-template-columns:2fr 1fr 1fr auto auto"><label>Search issues<input class="field" name="q" value="{escape(q, quote=True)}" placeholder="Book, accession number, borrower or ID"></label><label>Borrower type<select class="field" name="borrower_type"><option value="">All borrowers</option><option value="Student" {'selected' if borrower_type == 'Student' else ''}>Student</option><option value="Staff" {'selected' if borrower_type == 'Staff' else ''}>Staff</option></select></label><label>Issue status<select class="field" name="status"><option value="Issued" {'selected' if status == 'Issued' else ''}>Issued</option><option value="Returned" {'selected' if status == 'Returned' else ''}>Returned</option><option value="All" {'selected' if status == 'All' else ''}>All</option></select></label><button class="btn">Apply</button><a class="btn btn-light" href="/app/library/issues">Clear</a></form></section>
 <section class="card lib-table-card"><div class="page-heading"><h2>Issue register</h2><span class="lib-muted">{len(rows)} record(s) shown</span></div><div class="lib-table-scroll"><table style="min-width:850px"><thead><tr><th>Book / Accession</th><th>Borrower</th><th>Issue date</th><th>Due date</th><th>Status</th></tr></thead><tbody>{table}</tbody></table></div></section>
</div>
<dialog id="issueDialog" class="lib-dialog"><form method="post" action="/app/library/issues/save"><div class="lib-dialog-head"><div><div class="lib-eyebrow">LIBRARY CIRCULATION</div><h2>Issue a book</h2></div><button type="button" class="lib-close" onclick="document.getElementById('issueDialog').close()">×</button></div>
<div class="lib-form-grid"><label>Available book copy *<select class="field" name="copy_id" required>{copy_options}</select></label><label>Borrower type *<select class="field" name="borrower_type" required><option>Student</option><option>Staff</option></select></label><label>Borrower full name *<input class="field" name="borrower_name" required maxlength="180"></label><label>Admission / Staff number<input class="field" name="borrower_ref" maxlength="80"></label><label>Issue date *<input class="field" type="date" name="issue_date" value="{datetime.now().date().isoformat()}" required></label><label>Due date *<input class="field" type="date" name="due_date" min="{datetime.now().date().isoformat()}" required></label><label class="lib-notes">Notes<textarea class="field" name="notes" rows="2"></textarea></label></div>
<div class="lib-dialog-actions"><button type="button" class="btn btn-light" onclick="document.getElementById('issueDialog').close()">Cancel</button><button class="btn" type="submit" {'disabled' if not available_copies else ''}>Confirm Issue</button></div></form></dialog>
"""
        return _library_page(request, "Issue Books", body)
    finally:
        con.close()


@router.post("/app/library/issues/save")
async def library_issue_save(
    request: Request,
    copy_id: int = Form(...),
    borrower_type: str = Form(...),
    borrower_name: str = Form(...),
    borrower_ref: str = Form(""),
    issue_date: str = Form(...),
    due_date: str = Form(...),
    notes: str = Form(""),
):
    sid, error = _library_guard(request, "library.edit")
    if error:
        return error
    borrower_type = borrower_type if borrower_type in ("Student", "Staff") else ""
    borrower_name = borrower_name.strip()
    try:
        from datetime import date
        issue_day = date.fromisoformat(issue_date)
        due_day = date.fromisoformat(due_date)
    except (TypeError, ValueError):
        return HTMLResponse("Enter valid issue and due dates.", 400)
    if not borrower_type or not borrower_name:
        return HTMLResponse("Select a borrower type and enter the borrower's full name.", 400)
    if due_day < issue_day:
        return HTMLResponse("The due date cannot be earlier than the issue date.", 400)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    con = _db()
    try:
        cur = con.cursor()
        _ensure_book_catalogue(cur)
        _ensure_book_copies(cur)
        _ensure_library_issues(cur)
        copy = cur.execute(
            """SELECT c.id,c.book_id,c.copy_status,c.accession_no,b.title FROM library_book_copies c
               JOIN library_books b ON b.id=c.book_id AND b.school_id=c.school_id
               WHERE c.id=? AND c.school_id=? AND b.status='Active'""",
            (copy_id, sid),
        ).fetchone()
        if not copy:
            return HTMLResponse("The selected book copy was not found in this school's register.", 404)
        if copy["copy_status"] != "Available":
            return HTMLResponse("This copy is no longer available. Refresh the page and select another copy.", 409)
        cur.execute(
            """INSERT INTO library_book_issues(school_id,copy_id,book_id,borrower_type,borrower_name,
               borrower_ref,issue_date,due_date,issued_by,issue_status,returned_at,notes,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,'Issued','',?,?,?)""",
            (sid, copy_id, copy["book_id"], borrower_type, borrower_name, borrower_ref.strip(),
             issue_day.isoformat(), due_day.isoformat(), str(getattr(request.state, "user", "") or ""),
             notes.strip(), now, now),
        )
        cur.execute(
            "UPDATE library_book_copies SET copy_status='Issued',updated_at=? WHERE id=? AND school_id=? AND copy_status='Available'",
            (now, copy_id, sid),
        )
        if cur.rowcount == 0:
            con.rollback()
            return HTMLResponse("This copy has just been issued by another user. Refresh and try again.", 409)
        _audit(cur, sid, request, "LIBRARY_BOOK_ISSUED", f"{copy['title']} / {copy['accession_no']} to {borrower_name}")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/library/issues", 303)


@router.get("/app/library/returns", response_class=HTMLResponse)
def library_book_returns(request: Request, q: str = ""):
    sid, error = _library_guard(request)
    if error:
        return error
    con = _db()
    try:
        cur = con.cursor()
        _ensure_book_catalogue(cur)
        _ensure_book_copies(cur)
        _ensure_library_issues(cur)
        con.commit()
        filters = ["i.school_id=?", "i.issue_status='Issued'"]
        params = [sid]
        if q.strip():
            term = "%" + q.strip() + "%"
            filters.append("(b.title LIKE ? OR c.accession_no LIKE ? OR i.borrower_name LIKE ? OR i.borrower_ref LIKE ?)")
            params.extend([term] * 4)
        rows = cur.execute(
            """SELECT i.id,i.borrower_name,i.borrower_type,i.borrower_ref,i.issue_date,i.due_date,
                      b.title,c.accession_no
               FROM library_book_issues i
               JOIN library_books b ON b.id=i.book_id AND b.school_id=i.school_id
               JOIN library_book_copies c ON c.id=i.copy_id AND c.school_id=i.school_id
               WHERE """ + " AND ".join(filters) + " ORDER BY i.due_date,i.issue_date",
            tuple(params),
        ).fetchall()
        today = datetime.now().date().isoformat()
        overdue_count = sum(1 for row in rows if str(row["due_date"]) < today)
        table = "".join(
            f"<tr><td><b>{escape(str(row['title']))}</b><div class='lib-muted'>{escape(str(row['accession_no']))}</div></td>"
            f"<td>{escape(str(row['borrower_name']))}<div class='lib-muted'>{escape(str(row['borrower_type']))} · {escape(str(row['borrower_ref'] or 'No ID recorded'))}</div></td>"
            f"<td>{escape(str(row['issue_date']))}</td><td>{escape(str(row['due_date']))}</td>"
            f"<td><span class='lib-status {'lib-inactive' if str(row['due_date']) < today else ''}'>{'Overdue' if str(row['due_date']) < today else 'On loan'}</span></td>"
            f"<td><button class='btn btn-light' type='button' onclick=\"document.getElementById('return-{int(row['id'])}').showModal()\">Record return</button></td></tr>"
            for row in rows
        ) or "<tr><td colspan='6' class='lib-empty'>There are no books currently awaiting return.</td></tr>"
        dialogs = "".join(
            f"""<dialog id="return-{int(row['id'])}" class="lib-dialog"><form method="post" action="/app/library/returns/process">
<input type="hidden" name="issue_id" value="{int(row['id'])}">
<div class="lib-dialog-head"><div><div class="lib-eyebrow">BOOK RETURN</div><h2>Record returned copy</h2><div class="lib-muted">{escape(str(row['title']))} · {escape(str(row['accession_no']))}</div></div><button type="button" class="lib-close" onclick="this.closest('dialog').close()">×</button></div>
<div class="lib-form-grid"><label>Return date *<input class="field" type="date" name="return_date" value="{today}" required></label>
<label>Returned condition *<select class="field" name="return_condition"><option>Good</option><option>Fair</option><option>Poor</option><option>Damaged</option></select></label>
<label class="lib-notes">Return notes<textarea class="field" name="return_notes" rows="2" placeholder="Optional notes about the returned copy"></textarea></label></div>
<div class="lib-dialog-actions"><button type="button" class="btn btn-light" onclick="this.closest('dialog').close()">Cancel</button><button class="btn" type="submit">Confirm return</button></div></form></dialog>"""
            for row in rows
        )
        body = f"""
<div class="page library-page">
 <div class="page-heading lib-heading"><div><div class="lib-eyebrow">LIBRARY MANAGER / CIRCULATION</div><h1>Book Returns</h1><div class="lib-muted">Receive borrowed books, record their returned condition and release copies back into circulation.</div></div></div>
 <div class="lib-kpis"><div><span>Books awaiting return</span><strong>{len(rows)}</strong></div><div><span>Overdue returns</span><strong>{overdue_count}</strong></div><div><span>Returned condition tracked</span><strong>Yes</strong></div></div>
 <section class="card lib-filter-card"><form method="get" class="lib-filters" style="grid-template-columns:2fr auto auto"><label>Find an issued book<input class="field" name="q" value="{escape(q, quote=True)}" placeholder="Title, accession number, borrower or ID"></label><button class="btn">Search</button><a class="btn btn-light" href="/app/library/returns">Clear</a></form></section>
 <section class="card lib-table-card"><div class="page-heading"><h2>Outstanding loans</h2><span class="lib-muted">{len(rows)} book(s) awaiting return</span></div><div class="lib-table-scroll"><table style="min-width:950px"><thead><tr><th>Book / Accession</th><th>Borrower</th><th>Issued</th><th>Due date</th><th>Loan status</th><th>Action</th></tr></thead><tbody>{table}</tbody></table></div></section>
</div>
{dialogs}
"""
        return _library_page(request, "Book Returns", body)
    finally:
        con.close()


@router.post("/app/library/returns/process")
async def library_book_return_process(
    request: Request,
    issue_id: int = Form(...),
    return_date: str = Form(...),
    return_condition: str = Form("Good"),
    return_notes: str = Form(""),
):
    sid, error = _library_guard(request, "library.edit")
    if error:
        return error
    try:
        from datetime import date
        returned_day = date.fromisoformat(return_date)
    except (TypeError, ValueError):
        return HTMLResponse("Enter a valid return date.", 400)
    if returned_day > datetime.now().date():
        return HTMLResponse("The return date cannot be in the future.", 400)
    return_condition = return_condition if return_condition in ("Good", "Fair", "Poor", "Damaged") else "Good"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    new_copy_status = "Damaged" if return_condition == "Damaged" else "Available"
    con = _db()
    try:
        cur = con.cursor()
        _ensure_book_catalogue(cur)
        _ensure_book_copies(cur)
        _ensure_library_issues(cur)
        issue = cur.execute(
            """SELECT i.id,i.copy_id,i.book_id,i.issue_status,b.title,c.accession_no
               FROM library_book_issues i
               JOIN library_books b ON b.id=i.book_id AND b.school_id=i.school_id
               JOIN library_book_copies c ON c.id=i.copy_id AND c.school_id=i.school_id
               WHERE i.id=? AND i.school_id=?""",
            (issue_id, sid),
        ).fetchone()
        if not issue:
            return HTMLResponse("The selected issue record was not found in this school's library.", 404)
        if issue["issue_status"] != "Issued":
            return HTMLResponse("This book has already been returned.", 409)
        cur.execute(
            """UPDATE library_book_issues SET issue_status='Returned',returned_at=?,updated_at=?,
               notes=CASE WHEN COALESCE(notes,'')='' THEN ? ELSE notes || ' | Return: ' || ? END
               WHERE id=? AND school_id=? AND issue_status='Issued'""",
            (returned_day.isoformat(), now, return_notes.strip(), return_notes.strip(), issue_id, sid),
        )
        if cur.rowcount == 0:
            con.rollback()
            return HTMLResponse("This loan was already processed. Refresh the page.", 409)
        cur.execute(
            """UPDATE library_book_copies SET copy_status=?,condition=?,updated_at=?
               WHERE id=? AND school_id=?""",
            (new_copy_status, return_condition, now, issue["copy_id"], sid),
        )
        _audit(cur, sid, request, "LIBRARY_BOOK_RETURNED",
               f"{issue['title']} / {issue['accession_no']} returned; condition {return_condition}")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/library/returns", 303)


@router.get("/app/library/overdue", response_class=HTMLResponse)
def library_overdue_books(request: Request, q: str = "", borrower_type: str = ""):
    sid, error = _library_guard(request)
    if error:
        return error
    con = _db()
    try:
        cur = con.cursor()
        _ensure_book_catalogue(cur)
        _ensure_book_copies(cur)
        _ensure_library_issues(cur)
        con.commit()
        today = datetime.now().date()
        today_text = today.isoformat()
        filters = ["i.school_id=?", "i.issue_status='Issued'", "i.due_date<?"]
        params = [sid, today_text]
        if borrower_type in ("Student", "Staff"):
            filters.append("i.borrower_type=?")
            params.append(borrower_type)
        else:
            borrower_type = ""
        if q.strip():
            term = "%" + q.strip() + "%"
            filters.append("(b.title LIKE ? OR c.accession_no LIKE ? OR i.borrower_name LIKE ? OR i.borrower_ref LIKE ?)")
            params.extend([term] * 4)
        rows = cur.execute(
            """SELECT i.id,i.borrower_name,i.borrower_type,i.borrower_ref,i.issue_date,i.due_date,
                      b.title,c.accession_no
               FROM library_book_issues i
               JOIN library_books b ON b.id=i.book_id AND b.school_id=i.school_id
               JOIN library_book_copies c ON c.id=i.copy_id AND c.school_id=i.school_id
               WHERE """ + " AND ".join(filters) + " ORDER BY i.due_date,i.borrower_name",
            tuple(params),
        ).fetchall()
        def days_late(value):
            try:
                from datetime import date
                return max(0, (today - date.fromisoformat(str(value)[:10])).days)
            except (TypeError, ValueError):
                return 0
        table = "".join(
            f"<tr><td><b>{escape(str(row['title']))}</b><div class='lib-muted'>{escape(str(row['accession_no']))}</div></td>"
            f"<td>{escape(str(row['borrower_name']))}<div class='lib-muted'>{escape(str(row['borrower_type']))} · {escape(str(row['borrower_ref'] or 'No ID recorded'))}</div></td>"
            f"<td>{escape(str(row['issue_date']))}</td><td>{escape(str(row['due_date']))}</td>"
            f"<td><span class='lib-status lib-inactive'>{days_late(row['due_date'])} day(s) overdue</span></td></tr>"
            for row in rows
        ) or "<tr><td colspan='5' class='lib-empty'>No overdue books. All issued books are within their due dates.</td></tr>"
        student_count = sum(1 for row in rows if row["borrower_type"] == "Student")
        staff_count = sum(1 for row in rows if row["borrower_type"] == "Staff")
        body = f"""
<div class="page library-page">
 <div class="page-heading lib-heading"><div><div class="lib-eyebrow">LIBRARY MANAGER / CIRCULATION</div><h1>Overdue Books</h1><div class="lib-muted">Track borrowed books that have passed their due dates and identify borrowers who need a return follow-up.</div></div><a class="btn btn-light" href="/app/library/returns">Manage returns</a></div>
 <div class="lib-kpis"><div><span>Overdue books</span><strong>{len(rows)}</strong></div><div><span>Student borrowers</span><strong>{student_count}</strong></div><div><span>Staff borrowers</span><strong>{staff_count}</strong></div></div>
 <section class="card lib-filter-card"><form method="get" class="lib-filters" style="grid-template-columns:2fr 1fr auto auto"><label>Search overdue loans<input class="field" name="q" value="{escape(q, quote=True)}" placeholder="Book, accession number, borrower or ID"></label><label>Borrower type<select class="field" name="borrower_type"><option value="">All borrowers</option><option value="Student" {'selected' if borrower_type == 'Student' else ''}>Student</option><option value="Staff" {'selected' if borrower_type == 'Staff' else ''}>Staff</option></select></label><button class="btn">Apply</button><a class="btn btn-light" href="/app/library/overdue">Clear</a></form></section>
 <section class="card lib-table-card"><div class="page-heading"><h2>Overdue loan register</h2><span class="lib-muted">{len(rows)} overdue record(s)</span></div><div class="lib-table-scroll"><table style="min-width:900px"><thead><tr><th>Book / Accession</th><th>Borrower</th><th>Issue date</th><th>Due date</th><th>Overdue duration</th></tr></thead><tbody>{table}</tbody></table></div></section>
</div>
"""
        return _library_page(request, "Overdue Books", body)
    finally:
        con.close()


def _ensure_library_members(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS library_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        member_type TEXT NOT NULL DEFAULT 'Student',
        full_name TEXT NOT NULL,
        member_ref TEXT DEFAULT '',
        class_department TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        member_status TEXT NOT NULL DEFAULT 'Active',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_library_members_school ON library_members(school_id, member_type, member_status)")


@router.get("/app/library/members", response_class=HTMLResponse)
def library_members(request: Request, q: str = "", member_type: str = "", status: str = "Active"):
    sid, error = _library_guard(request)
    if error:
        return error
    con = _db()
    try:
        cur = con.cursor()
        _ensure_library_members(cur)
        con.commit()
        filters = ["school_id=?"]
        params = [sid]
        if member_type in ("Student", "Staff"):
            filters.append("member_type=?")
            params.append(member_type)
        else:
            member_type = ""
        if status in ("Active", "Inactive"):
            filters.append("member_status=?")
            params.append(status)
        else:
            status = "All"
        if q.strip():
            term = "%" + q.strip() + "%"
            filters.append("(full_name LIKE ? OR member_ref LIKE ? OR class_department LIKE ? OR phone LIKE ?)")
            params.extend([term] * 4)
        rows = cur.execute(
            "SELECT * FROM library_members WHERE " + " AND ".join(filters) + " ORDER BY full_name",
            tuple(params),
        ).fetchall()
        total = cur.execute("SELECT COUNT(*) AS n FROM library_members WHERE school_id=?", (sid,)).fetchone()["n"]
        active = cur.execute("SELECT COUNT(*) AS n FROM library_members WHERE school_id=? AND member_status='Active'", (sid,)).fetchone()["n"]
        students = cur.execute("SELECT COUNT(*) AS n FROM library_members WHERE school_id=? AND member_type='Student' AND member_status='Active'", (sid,)).fetchone()["n"]
        table = "".join(
            f"<tr><td><b>{escape(str(x['full_name']))}</b><div class='lib-muted'>{escape(str(x['member_ref'] or 'No reference'))}</div></td>"
            f"<td>{escape(str(x['member_type']))}</td><td>{escape(str(x['class_department'] or '—'))}</td>"
            f"<td>{escape(str(x['phone'] or '—'))}</td><td>{escape(str(x['email'] or '—'))}</td>"
            f"<td><span class='lib-status {'lib-inactive' if x['member_status'] != 'Active' else ''}'>{escape(str(x['member_status']))}</span></td></tr>"
            for x in rows
        ) or "<tr><td colspan='6' class='lib-empty'>No library members match these filters. Add a student or staff member to begin.</td></tr>"
        body = f"""
<div class="page library-page">
 <div class="page-heading lib-heading"><div><div class="lib-eyebrow">LIBRARY MANAGER / MEMBERSHIP</div><h1>Library Members</h1><div class="lib-muted">Maintain the school's library membership register for students and staff.</div></div><button class="btn" type="button" onclick="document.getElementById('libraryMemberDialog').showModal()">Add Member</button></div>
 <div class="lib-kpis"><div><span>Registered members</span><strong>{int(total or 0)}</strong></div><div><span>Active members</span><strong>{int(active or 0)}</strong></div><div><span>Active student members</span><strong>{int(students or 0)}</strong></div></div>
 <section class="card lib-filter-card"><form method="get" class="lib-filters" style="grid-template-columns:2fr 1fr 1fr auto auto">
 <label>Search members<input class="field" name="q" value="{escape(q, quote=True)}" placeholder="Name, admission/staff number, class or phone"></label>
 <label>Member type<select class="field" name="member_type"><option value="">All types</option><option value="Student" {'selected' if member_type == 'Student' else ''}>Student</option><option value="Staff" {'selected' if member_type == 'Staff' else ''}>Staff</option></select></label>
 <label>Status<select class="field" name="status"><option value="Active" {'selected' if status == 'Active' else ''}>Active</option><option value="Inactive" {'selected' if status == 'Inactive' else ''}>Inactive</option><option value="All" {'selected' if status == 'All' else ''}>All</option></select></label>
 <button class="btn">Apply</button><a class="btn btn-light" href="/app/library/members">Clear</a></form></section>
 <section class="card lib-table-card"><div class="page-heading"><h2>Membership register</h2><span class="lib-muted">{len(rows)} member(s) shown</span></div><div class="lib-table-scroll"><table style="min-width:850px"><thead><tr><th>Member / Reference</th><th>Type</th><th>Class / Department</th><th>Phone</th><th>Email</th><th>Status</th></tr></thead><tbody>{table}</tbody></table></div></section>
</div>
<dialog id="libraryMemberDialog" class="lib-dialog"><form method="post" action="/app/library/members/save">
 <div class="lib-dialog-head"><div><div class="lib-eyebrow">LIBRARY MEMBERSHIP</div><h2>Register library member</h2></div><button type="button" class="lib-close" onclick="this.closest('dialog').close()">×</button></div>
 <div class="lib-form-grid"><label>Member type *<select class="field" name="member_type" required><option>Student</option><option>Staff</option></select></label>
 <label>Full name *<input class="field" name="full_name" maxlength="180" required></label>
 <label>Admission / Staff number<input class="field" name="member_ref" maxlength="80"></label>
 <label>Class / Department<input class="field" name="class_department" maxlength="120"></label>
 <label>Phone<input class="field" name="phone" maxlength="50"></label><label>Email<input class="field" type="email" name="email" maxlength="180"></label>
 <label>Status<select class="field" name="member_status"><option>Active</option><option>Inactive</option></select></label>
 <label class="lib-notes">Notes<textarea class="field" name="notes" rows="2"></textarea></label></div>
 <div class="lib-dialog-actions"><button type="button" class="btn btn-light" onclick="this.closest('dialog').close()">Cancel</button><button class="btn" type="submit">Save Member</button></div>
</form></dialog>
"""
        return _library_page(request, "Library Members", body)
    finally:
        con.close()


@router.post("/app/library/members/save")
async def library_member_save(
    request: Request,
    member_type: str = Form(...),
    full_name: str = Form(...),
    member_ref: str = Form(""),
    class_department: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    member_status: str = Form("Active"),
    notes: str = Form(""),
):
    sid, error = _library_guard(request, "library.edit")
    if error:
        return error
    member_type = member_type if member_type in ("Student", "Staff") else ""
    full_name = full_name.strip()
    member_ref = member_ref.strip()
    member_status = member_status if member_status in ("Active", "Inactive") else "Active"
    if not member_type or not full_name:
        return HTMLResponse("Select a valid member type and enter the member's full name.", 400)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    con = _db()
    try:
        cur = con.cursor()
        _ensure_library_members(cur)
        if member_ref:
            existing = cur.execute(
                "SELECT id FROM library_members WHERE school_id=? AND member_type=? AND member_ref=?",
                (sid, member_type, member_ref),
            ).fetchone()
            if existing:
                return HTMLResponse("That admission/staff number is already registered as a library member.", 409)
        cur.execute(
            """INSERT INTO library_members(school_id,member_type,full_name,member_ref,class_department,
               phone,email,member_status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, member_type, full_name, member_ref, class_department.strip(), phone.strip(),
             email.strip(), member_status, notes.strip(), now, now),
        )
        _audit(cur, sid, request, "LIBRARY_MEMBER_REGISTERED", f"{member_type}: {full_name} ({member_ref or 'no reference'})")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return RedirectResponse("/app/library/members", 303)


@router.get("/app/library/reports", response_class=HTMLResponse)
def library_reports(request: Request, date_from: str = "", date_to: str = ""):
    sid, error = _library_guard(request)
    if error:
        return error
    today = datetime.now().date()
    date_from = date_from or today.replace(day=1).isoformat()
    date_to = date_to or today.isoformat()
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
        if start > end:
            raise ValueError("Invalid date range")
    except (TypeError, ValueError):
        return HTMLResponse("Enter a valid reporting date range.", 400)
    con = _db()
    try:
        cur = con.cursor()
        _ensure_book_catalogue(cur)
        _ensure_book_copies(cur)
        _ensure_library_issues(cur)
        _ensure_library_members(cur)
        con.commit()

        def metric(sql, params=(sid,)):
            result = cur.execute(sql, params).fetchone()
            return int(result["n"] or 0)

        titles = metric("SELECT COUNT(*) n FROM library_books WHERE school_id=? AND status='Active'")
        copies = metric("SELECT COUNT(*) n FROM library_book_copies WHERE school_id=?")
        available = metric("SELECT COUNT(*) n FROM library_book_copies WHERE school_id=? AND copy_status='Available'")
        issued_copies = metric("SELECT COUNT(*) n FROM library_book_copies WHERE school_id=? AND copy_status='Issued'")
        damaged = metric("SELECT COUNT(*) n FROM library_book_copies WHERE school_id=? AND copy_status='Damaged'")
        lost = metric("SELECT COUNT(*) n FROM library_book_copies WHERE school_id=? AND copy_status='Lost'")
        outstanding = metric("SELECT COUNT(*) n FROM library_book_issues WHERE school_id=? AND issue_status='Issued'")
        overdue = metric("SELECT COUNT(*) n FROM library_book_issues WHERE school_id=? AND issue_status='Issued' AND due_date<?", (sid, today.isoformat()))
        issued_period = metric("SELECT COUNT(*) n FROM library_book_issues WHERE school_id=? AND issue_date BETWEEN ? AND ?", (sid, date_from, date_to))
        returned_period = metric("SELECT COUNT(*) n FROM library_book_issues WHERE school_id=? AND issue_status='Returned' AND substr(returned_at,1,10) BETWEEN ? AND ?", (sid, date_from, date_to))
        members = metric("SELECT COUNT(*) n FROM library_members WHERE school_id=? AND member_status='Active'")
        student_members = metric("SELECT COUNT(*) n FROM library_members WHERE school_id=? AND member_status='Active' AND member_type='Student'")
        staff_members = metric("SELECT COUNT(*) n FROM library_members WHERE school_id=? AND member_status='Active' AND member_type='Staff'")

        categories = cur.execute(
            """SELECT COALESCE(NULLIF(TRIM(b.category),''),'Uncategorised') category,
                      COUNT(DISTINCT b.id) titles, COUNT(c.id) copies,
                      SUM(CASE WHEN c.copy_status='Available' THEN 1 ELSE 0 END) available
               FROM library_books b LEFT JOIN library_book_copies c
                 ON c.book_id=b.id AND c.school_id=b.school_id
               WHERE b.school_id=? AND b.status='Active'
               GROUP BY COALESCE(NULLIF(TRIM(b.category),''),'Uncategorised')
               ORDER BY category""", (sid,)
        ).fetchall()
        category_rows = "".join(
            f"<tr><td>{escape(str(x['category']))}</td><td class='lib-num'>{int(x['titles'] or 0)}</td><td class='lib-num'>{int(x['copies'] or 0)}</td><td class='lib-num'>{int(x['available'] or 0)}</td></tr>"
            for x in categories
        ) or "<tr><td colspan='4' class='lib-empty'>No catalogue categories recorded.</td></tr>"

        activity = cur.execute(
            """SELECT i.borrower_name,i.borrower_type,i.issue_date,i.due_date,i.issue_status,
                      b.title,c.accession_no
               FROM library_book_issues i
               JOIN library_books b ON b.id=i.book_id AND b.school_id=i.school_id
               JOIN library_book_copies c ON c.id=i.copy_id AND c.school_id=i.school_id
               WHERE i.school_id=? AND i.issue_date BETWEEN ? AND ?
               ORDER BY i.issue_date DESC,i.id DESC LIMIT 30""",
            (sid, date_from, date_to),
        ).fetchall()
        activity_rows = "".join(
            f"<tr><td>{escape(str(x['issue_date']))}</td><td><b>{escape(str(x['title']))}</b><div class='lib-muted'>{escape(str(x['accession_no']))}</div></td>"
            f"<td>{escape(str(x['borrower_name']))}<div class='lib-muted'>{escape(str(x['borrower_type']))}</div></td>"
            f"<td>{escape(str(x['due_date']))}</td><td>{escape(str(x['issue_status']))}</td></tr>"
            for x in activity
        ) or "<tr><td colspan='5' class='lib-empty'>No circulation activity in this date range.</td></tr>"

        body = f"""
<div class="page library-page">
 <div class="page-heading lib-heading"><div><div class="lib-eyebrow">LIBRARY MANAGER / ANALYTICS</div><h1>Library Reports</h1><div class="lib-muted">Collection, circulation and membership overview.</div></div><button class="btn" type="button" onclick="window.print()">Print Report</button></div>
 <section class="card lib-filter-card"><form method="get" class="lib-filters" style="grid-template-columns:1fr 1fr auto auto">
  <label>From date<input class="field" type="date" name="date_from" value="{escape(date_from, quote=True)}" required></label>
  <label>To date<input class="field" type="date" name="date_to" value="{escape(date_to, quote=True)}" required></label>
  <button class="btn">Generate</button><a class="btn btn-light" href="/app/library/reports">This month</a>
 </form><div class="lib-muted" style="margin-top:8px">Circulation period: {escape(date_from)} to {escape(date_to)}</div></section>
 <div class="lib-kpis">
  <div><span>Active catalogue titles</span><strong>{titles}</strong></div><div><span>Physical copies</span><strong>{copies}</strong></div><div><span>Available copies</span><strong>{available}</strong></div><div><span>Currently on loan</span><strong>{outstanding}</strong></div>
  <div><span>Overdue loans</span><strong>{overdue}</strong></div><div><span>Issued in period</span><strong>{issued_period}</strong></div><div><span>Returned in period</span><strong>{returned_period}</strong></div><div><span>Active members</span><strong>{members}</strong></div>
 </div>
 <section class="card lib-table-card"><div class="page-heading"><h2>Collection by category</h2></div><div class="lib-table-scroll"><table><thead><tr><th>Category</th><th>Titles</th><th>Copies</th><th>Available</th></tr></thead><tbody>{category_rows}</tbody></table></div></section>
 <section class="card lib-table-card"><div class="page-heading"><h2>Copy status</h2></div><div class="lib-kpis"><div><span>Available</span><strong>{available}</strong></div><div><span>Issued</span><strong>{issued_copies}</strong></div><div><span>Damaged</span><strong>{damaged}</strong></div><div><span>Lost</span><strong>{lost}</strong></div></div></section>
 <section class="card lib-table-card"><div class="page-heading"><h2>Active membership</h2></div><div class="lib-kpis"><div><span>Total active</span><strong>{members}</strong></div><div><span>Students</span><strong>{student_members}</strong></div><div><span>Staff</span><strong>{staff_members}</strong></div></div></section>
 <section class="card lib-table-card"><div class="page-heading"><h2>Circulation activity</h2><span class="lib-muted">Latest 30 issues in the selected period</span></div><div class="lib-table-scroll"><table style="min-width:850px"><thead><tr><th>Issue date</th><th>Book / Accession</th><th>Borrower</th><th>Due date</th><th>Status</th></tr></thead><tbody>{activity_rows}</tbody></table></div></section>
</div>
<style>@media print{{.nav,.sidebar,.lib-filter-card,.lib-heading button{{display:none!important}}.page{{width:100%!important;max-width:none!important;margin:0!important}}.card{{break-inside:avoid;box-shadow:none!important}}body{{background:#fff!important}}}}</style>
"""
        return _library_page(request, "Library Reports", body)
    finally:
        con.close()
