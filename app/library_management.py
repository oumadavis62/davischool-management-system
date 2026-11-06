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
        "SELECT * FROM library_books WHERE " + " AND ".join(filters) + " ORDER BY title COLLATE NOCASE, author COLLATE NOCASE",
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
    return _school_page(request, "Book Catalogue", body)


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
        return _school_page(request, "Book Register", body)
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
