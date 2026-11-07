from datetime import datetime
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
        return None, HTMLResponse("Parent and student services are restricted to school administrators and registrars.", 403)
    return sid, None


def _schema(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS parent_service_notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        title TEXT NOT NULL, audience TEXT NOT NULL DEFAULT 'All Parents',
        message TEXT NOT NULL, publish_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Published',
        created_by TEXT DEFAULT '', created_at TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS parent_service_meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        parent_name TEXT NOT NULL, phone TEXT DEFAULT '', student_id INTEGER,
        meeting_date TEXT NOT NULL, meeting_time TEXT DEFAULT '', purpose TEXT NOT NULL,
        assigned_to TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Scheduled',
        notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS parent_service_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL,
        request_no TEXT NOT NULL, student_id INTEGER, requester_name TEXT NOT NULL,
        requester_phone TEXT DEFAULT '', category TEXT NOT NULL, subject TEXT NOT NULL,
        details TEXT DEFAULT '', priority TEXT NOT NULL DEFAULT 'Normal',
        status TEXT NOT NULL DEFAULT 'Open', assigned_to TEXT DEFAULT '',
        resolution TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(school_id,request_no))""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_parent_notice_school ON parent_service_notices(school_id,publish_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_parent_meetings_school ON parent_service_meetings(school_id,meeting_date,status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_parent_requests_school ON parent_service_requests(school_id,status,created_at)")
    cur.execute("""CREATE TABLE IF NOT EXISTS parent_student_links (
        school_id INTEGER NOT NULL, user_id INTEGER NOT NULL, student_id INTEGER NOT NULL,
        created_at TEXT, PRIMARY KEY (school_id,user_id,student_id))""")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _students(cur, sid):
    return cur.execute("""SELECT s.id,s.name,s.admission_no,s.parent_name,s.parent_phone,
        c.name class_name,c.stream FROM students s
        LEFT JOIN classes c ON c.id=s.class_id AND c.school_id=s.school_id
        WHERE s.school_id=? AND lower(coalesce(s.status,'active')) NOT IN ('inactive','transferred','graduated','left')
        ORDER BY s.name""", (sid,)).fetchall()


def _options(rows):
    return "<option value=''>Select learner (optional)</option>" + "".join(
        "<option value='" + str(int(r["id"])) + "'>" + escape(str(r["admission_no"] or "No admission")) +
        " — " + escape(str(r["name"] or "")) + (" · " + escape(str(r["class_name"] or "")) if r["class_name"] else "") + "</option>"
        for r in rows)


def _page(request, title, description, body):
    css = """<style>
.ps-page{width:100%;max-width:none;display:grid;gap:16px;color:#26372d}
.ps-page h1{margin:0;color:#174b2b}.ps-page h2{margin:0 0 12px;color:#245638;font-size:17px}
.ps-page p{margin:5px 0 0;color:#718078;font-size:13px;line-height:1.5}
.ps-card,.ps-kpis>div{background:#fff;border:1px solid #dce9de;border-radius:14px;padding:16px;min-width:0}
.ps-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.ps-kpis small{display:block;color:#718078;font-size:12px}.ps-kpis strong{display:block;color:#174b35;font-size:24px;margin-top:5px}
.ps-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.ps-page label{display:grid;gap:6px;font-size:12px;font-weight:700;color:#52645a;min-width:0}
.ps-page input,.ps-page select,.ps-page textarea{width:100%;min-height:40px;padding:9px;border:1px solid #dce6df;border-radius:9px;background:#fff;color:#26372d;font:inherit}
.ps-page textarea{min-height:76px}.ps-page .wide{grid-column:1/-1}
.ps-actions{display:flex;gap:9px;justify-content:flex-end;flex-wrap:wrap;margin-top:10px}
.ps-btn{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:9px;background:#176b3a;color:#fff;padding:10px 14px;font-weight:800;font-size:12px;text-decoration:none;cursor:pointer}
.ps-btn.light{background:#edf5ef;color:#245638}
.ps-table-wrap{width:100%;overflow:auto}.ps-page table{width:100%;min-width:720px;border-collapse:collapse}
.ps-page th,.ps-page td{padding:10px;text-align:left;vertical-align:top;border-bottom:1px solid #edf1ee;font-size:12px}
.ps-page th{background:#f5f9f6;color:#607267;white-space:nowrap}.ps-page td small{display:block;color:#718078;margin-top:3px}
.ps-pill{display:inline-block;padding:4px 8px;border-radius:20px;background:#edf5ef;color:#245638;font-size:11px;font-weight:800}
.ps-toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:12px}.ps-toolbar label{flex:1;min-width:160px}
.ps-page>div:first-child{padding:22px 24px;border:1px solid #cfe2d2;border-radius:18px;background:linear-gradient(125deg,#e5f2e7 0%,#f5faf5 55%,#d9ebdc 100%);box-shadow:0 8px 24px #1d57300b}
.ps-page>div:first-child h1{font-size:clamp(22px,3vw,30px);letter-spacing:-.4px}
.ps-card,.ps-kpis>div{box-shadow:0 5px 18px #214b2e0a;transition:box-shadow .18s,border-color .18s,transform .18s}
.ps-card:hover,.ps-kpis>div:hover{border-color:#b8d4be;box-shadow:0 9px 24px #214b2e12}
.ps-btn{background:linear-gradient(135deg,#247847,#145b34);box-shadow:0 3px 8px #176b3a20;transition:transform .16s,filter .16s}
.ps-btn:hover{filter:brightness(1.08);transform:translateY(-1px)}
.ps-btn.light{background:#edf5ef;box-shadow:none;border:1px solid #d7e8da}
.ps-page table{border-collapse:separate;border-spacing:0}
.ps-page thead th{position:sticky;top:0;background:#edf5ef;border-bottom:1px solid #d9e7dc}
.ps-page tbody tr:hover td{background:#f8fbf8}
.ps-page input:focus,.ps-page select:focus,.ps-page textarea:focus{outline:2px solid #8fbd9a;outline-offset:1px;border-color:#57966b}
.ps-dialog{width:min(760px,calc(100vw - 28px));max-height:86vh;overflow:auto;border:1px solid #cfe0d2;border-radius:18px;padding:22px;background:linear-gradient(145deg,#f1f8f2,#fff 45%);color:#26372d;box-shadow:0 24px 80px #102b1c40}
.ps-dialog::backdrop{background:#14271c80;backdrop-filter:blur(3px)}
.ps-dialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}
.ps-dialog-head h2{margin:0;color:#245638;font-size:18px}
.ps-dialog-close{border:0;border-radius:9px;background:#e6f1e8;color:#245638;padding:8px 12px;font-weight:800;cursor:pointer}
.ps-dialog .ps-actions{position:sticky;bottom:-22px;padding:12px 0 2px;background:linear-gradient(0deg,#f1f8f2 75%,transparent)}
.ps-filter-trigger{margin:0 0 12px}
@media(max-width:760px){.ps-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.ps-form{grid-template-columns:1fr}.ps-page .wide{grid-column:auto}.ps-card{padding:12px}.ps-dialog{padding:16px}.ps-page>div:first-child{padding:17px}}
@media(prefers-reduced-motion:reduce){.ps-card,.ps-kpis>div,.ps-btn{transition:none}}
@media print{.ps-btn,.ps-toolbar,.ps-dialog{display:none!important}.ps-card{box-shadow:none;break-inside:avoid}.ps-table-wrap{overflow:visible}.ps-page table{min-width:0}}
</style>
<script>
(function(){
 function init(){
  document.querySelectorAll('.ps-page .ps-card').forEach(function(card){
   var form=card.querySelector(':scope > form.ps-form');
   if(form){
    var heading=card.querySelector('h2'),label=heading?heading.textContent.trim():'Open form';
    var trigger=document.createElement('button');trigger.type='button';trigger.className='ps-btn ps-entry-trigger';trigger.textContent=label;
    var dialog=document.createElement('dialog');dialog.className='ps-dialog';
    var head=document.createElement('div');head.className='ps-dialog-head';
    var title=document.createElement('h2');title.textContent=label;
    var close=document.createElement('button');close.type='button';close.className='ps-dialog-close';close.textContent='Close';close.addEventListener('click',function(){dialog.close()});
    head.append(title,close);dialog.append(head,form);card.insertBefore(trigger,form);card.insertBefore(dialog,form);
    trigger.addEventListener('click',function(){dialog.showModal()});
    dialog.addEventListener('click',function(e){if(e.target===dialog)dialog.close()});
   }
   var filter=card.querySelector(':scope > form.ps-toolbar');
   if(filter){
    var trigger=document.createElement('button');trigger.type='button';trigger.className='ps-btn light ps-filter-trigger';trigger.textContent='Open filters';
    var dialog=document.createElement('dialog');dialog.className='ps-dialog';
    var head=document.createElement('div');head.className='ps-dialog-head';
    var title=document.createElement('h2');title.textContent='Search & filters';
    var close=document.createElement('button');close.type='button';close.className='ps-dialog-close';close.textContent='Close';close.addEventListener('click',function(){dialog.close()});
    head.append(title,close);dialog.append(head,filter);card.insertBefore(trigger,filter);card.insertBefore(dialog,filter);
    trigger.addEventListener('click',function(){dialog.showModal()});
   }
  });
  document.querySelectorAll('.ps-page .ps-table-wrap').forEach(function(w){w.setAttribute('tabindex','0');w.setAttribute('aria-label','Scrollable data table')});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
</script>"""
    html = "<div class='page ps-page'><div><h1>" + escape(title) + "</h1><p>" + escape(description) + "</p></div>" + body + "</div>" + css
\n    dialog_close_support = """<style>
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
</script>"""    return _school_page(request, title, html + dialog_close_support)


def _count(cur, table, sid):
    return int(cur.execute("SELECT COUNT(*) n FROM " + table + " WHERE school_id=?", (sid,)).fetchone()["n"] or 0)


@router.get("/app/parent-services/guardians", response_class=HTMLResponse)
def parent_guardians(request: Request, q: str = ""):
    sid, denied = _guard(request)
    if denied:
        return denied
    con = _db()
    try:
        cur = con.cursor()
        _schema(cur)
        # Student Manager remains the single source of truth. Build this
        # directory from enrolled learners instead of asking staff to register
        # the same parent a second time.
        learner_rows = _students(cur, sid)
        con.commit()
    finally:
        con.close()

    groups = {}
    for learner in learner_rows:
        parent_name = str(learner["parent_name"] or "").strip()
        parent_phone = str(learner["parent_phone"] or "").strip()
        if not parent_name and not parent_phone:
            continue
        digits = "".join(ch for ch in parent_phone if ch.isdigit())
        # A phone number is the strongest available matching key. If absent,
        # fall back to a case/spacing-normalised parent name.
        key = ("phone", digits) if digits else ("name", " ".join(parent_name.casefold().split()))
        group = groups.setdefault(key, {"names": [], "phones": [], "learners": []})
        if parent_name and parent_name not in group["names"]:
            group["names"].append(parent_name)
        if parent_phone and parent_phone not in group["phones"]:
            group["phones"].append(parent_phone)
        group["learners"].append(learner)

    term = q.strip().casefold()
    directory = []
    for group in groups.values():
        names = group["names"]
        phones = group["phones"]
        learners = group["learners"]
        display_name = names[0] if names else "Parent / Guardian"
        display_phone = phones[0] if phones else "No phone recorded"
        learner_names = ", ".join(str(row["name"] or "") for row in learners)
        searchable = " ".join([
            " ".join(names), " ".join(phones),
            " ".join(str(row["name"] or "") for row in learners),
            " ".join(str(row["admission_no"] or "") for row in learners)
        ]).casefold()
        if term and term not in searchable:
            continue
        directory.append({
            "name": display_name,
            "other_names": names[1:],
            "phone": display_phone,
            "other_phones": phones[1:],
            "children": len(learners),
            "learner_names": learner_names
        })
    directory.sort(key=lambda item: item["name"].casefold())
    learner_count = len(learner_rows)
    parent_count = len(groups)
    trs = "".join(
        "<tr><td><b>" + escape(item["name"]) + "</b>" +
        ("<small>Also recorded as: " + escape(", ".join(item["other_names"])) + "</small>" if item["other_names"] else "") +
        "<small>" + escape(item["phone"]) + "</small>" +
        ("<small>Other phone formats: " + escape(", ".join(item["other_phones"])) + "</small>" if item["other_phones"] else "") +
        "</td><td>" + str(item["children"]) + "</td><td>" + escape(item["learner_names"]) + "</td></tr>"
        for item in directory
    ) or "<tr><td colspan='3'>No parent contacts match this search.</td></tr>"
    body = (
        "<div class='ps-kpis'><div><small>Unique parent contacts</small><strong>" + str(parent_count) +
        "</strong></div><div><small>Active learners</small><strong>" + str(learner_count) +
        "</strong></div><div><small>Displayed contacts</small><strong>" + str(len(directory)) +
        "</strong></div><div><small>Source</small><strong style='font-size:15px'>Student register</strong></div></div>"
        "<section class='ps-card'><h2>Parent / Guardian Directory</h2>"
        "<p>This directory is automatically populated from parent details entered in Students Manager, Admissions and Enrolment. "
        "There is no second parent-registration step. Updating a learner's parent name or phone in Students Manager updates this directory. "
        "Learners sharing the same phone number are grouped together; where no phone is recorded, matching parent names are grouped.</p>"
        "<form method='get' class='ps-toolbar'><label>Search parent or learner<input name='q' value='" +
        escape(q, quote=True) + "' placeholder='Name, phone or admission number'></label>"
        "<button class='ps-btn'>Search</button><a class='ps-btn light' href='/app/parent-services/guardians'>Clear</a></form>"
        "<div class='ps-table-wrap'><table><thead><tr><th>Parent / Guardian</th><th>Linked learners</th><th>Learners</th></tr></thead><tbody>" +
        trs + "</tbody></table></div></section>"
    )
    return _page(request, "Parent & Guardian Register",
                 "An automatically maintained directory of parent and guardian contacts captured in the student register.", body)


@router.get("/app/parent-services/linking", response_class=HTMLResponse)
def parent_linking(request: Request):
    sid, denied = _guard(request)
    if denied: return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur)
        students=_students(cur,sid)
        users=cur.execute("SELECT id,full_name,username,email FROM users WHERE school_id=? AND role='parent' ORDER BY full_name",(sid,)).fetchall()
        rows=cur.execute("""SELECT l.user_id,l.student_id,u.full_name,u.username,s.name student_name,s.admission_no
            FROM parent_student_links l JOIN users u ON u.id=l.user_id AND u.school_id=l.school_id
            JOIN students s ON s.id=l.student_id AND s.school_id=l.school_id
            WHERE l.school_id=? ORDER BY u.full_name,s.name""",(sid,)).fetchall()
        con.commit()
    finally:con.close()
    user_opts="<option value=''>Select existing parent account</option>"+"".join("<option value='"+str(int(u["id"]))+"'>"+escape(str(u["full_name"] or "Parent"))+" — "+escape(str(u["username"] or u["email"] or ""))+"</option>" for u in users)
    trs="".join("<tr><td>"+escape(str(r["full_name"] or "Parent"))+"<small>"+escape(str(r["username"] or ""))+"</small></td><td>"+escape(str(r["student_name"] or ""))+"</td><td>"+escape(str(r["admission_no"] or ""))+"</td><td><form method='post' action='/app/parent-services/linking/remove'><input type='hidden' name='user_id' value='"+str(int(r["user_id"]))+"'><input type='hidden' name='student_id' value='"+str(int(r["student_id"]))+"'><button class='ps-btn light'>Unlink</button></form></td></tr>" for r in rows) or "<tr><td colspan='4'>No explicit parent–learner links have been recorded.</td></tr>"
    body="<section class='ps-card'><h2>Link an existing parent account to a learner</h2><p>This uses existing parent portal accounts. It does not create passwords or expose credentials.</p><form method='post' action='/app/parent-services/linking/save' class='ps-form'><label>Parent account *<select name='user_id' required>"+user_opts+"</select></label><label>Learner *<select name='student_id' required>"+_options(students)+"</select></label><div class='wide ps-actions'><button class='ps-btn'>Save parent–learner link</button></div></form></section><section class='ps-card'><h2>Current parent–learner links</h2><div class='ps-table-wrap'><table><thead><tr><th>Parent account</th><th>Learner</th><th>Admission no.</th><th>Action</th></tr></thead><tbody>"+trs+"</tbody></table></div></section>"
    return _page(request,"Parent–Student Linking","Connect existing parent portal accounts to one or more learners, including siblings.",body)


@router.post("/app/parent-services/linking/save")
def parent_link_save(request:Request,user_id:int=Form(...),student_id:int=Form(...)):
    sid,denied=_guard(request)
    if denied:return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur)
        if not cur.execute("SELECT id FROM users WHERE id=? AND school_id=? AND role='parent'",(user_id,sid)).fetchone():return HTMLResponse("Parent account not found in this school.",404)
        if not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone():return HTMLResponse("Learner not found in this school.",404)
        exists=cur.execute("SELECT user_id FROM parent_student_links WHERE school_id=? AND user_id=? AND student_id=?",(sid,user_id,student_id)).fetchone()
        if not exists:cur.execute("INSERT INTO parent_student_links(school_id,user_id,student_id,created_at) VALUES(?,?,?,?)",(sid,user_id,student_id,_now()))
        _audit(cur,sid,request,"PARENT_STUDENT_LINK","Linked parent account "+str(user_id)+" to learner "+str(student_id));con.commit()
    except Exception as exc:
        con.rollback();print("PARENT LINK SAVE ERROR:",repr(exc),flush=True);return HTMLResponse("The parent link could not be saved. Please verify the selected records.",500)
    finally:con.close()
    return RedirectResponse("/app/parent-services/linking",303)


@router.post("/app/parent-services/linking/remove")
def parent_link_remove(request:Request,user_id:int=Form(...),student_id:int=Form(...)):
    sid,denied=_guard(request)
    if denied:return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur)
        cur.execute("DELETE FROM parent_student_links WHERE school_id=? AND user_id=? AND student_id=?",(sid,user_id,student_id))
        _audit(cur,sid,request,"PARENT_STUDENT_UNLINK","Unlinked parent account "+str(user_id)+" from learner "+str(student_id));con.commit()
    finally:con.close()
    return RedirectResponse("/app/parent-services/linking",303)


@router.get("/app/parent-services/access", response_class=HTMLResponse)
def parent_access(request:Request):
    sid,denied=_guard(request)
    if denied:return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur)
        rows=cur.execute("""SELECT u.id,u.full_name,u.username,u.email,COUNT(l.student_id) children
            FROM users u LEFT JOIN parent_student_links l ON l.user_id=u.id AND l.school_id=u.school_id
            WHERE u.school_id=? AND u.role='parent' GROUP BY u.id,u.full_name,u.username,u.email ORDER BY u.full_name""",(sid,)).fetchall()
        con.commit()
    finally:con.close()
    trs="".join("<tr><td><b>"+escape(str(r["full_name"] or "Parent"))+"</b></td><td>"+escape(str(r["username"] or r["email"] or ""))+"</td><td>"+str(int(r["children"] or 0))+"</td><td><span class='ps-pill'>Existing account</span></td></tr>" for r in rows) or "<tr><td colspan='4'>No parent portal accounts found. Parent accounts are created through the existing student admission workflow when a phone number is provided.</td></tr>"
    body="<section class='ps-card'><h2>Parent Portal Accounts</h2><p>Review parent accounts and the number of learners explicitly linked to each account. Password reset and sign-in remain governed by the existing account security workflow.</p><div class='ps-table-wrap'><table><thead><tr><th>Parent</th><th>Username / Contact</th><th>Linked learners</th><th>Account</th></tr></thead><tbody>"+trs+"</tbody></table></div></section>"
    return _page(request,"Parent Portal Access","Monitor existing parent portal accounts without duplicating login or credential-management logic.",body)


@router.get("/app/parent-services/notices", response_class=HTMLResponse)
def parent_notices(request:Request):
    sid,denied=_guard(request)
    if denied:return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur)
        rows=cur.execute("SELECT * FROM parent_service_notices WHERE school_id=? ORDER BY publish_date DESC,id DESC",(sid,)).fetchall()
        con.commit()
    finally:con.close()
    trs="".join("<tr><td><b>"+escape(str(r["title"]))+"</b><small>"+escape(str(r["publish_date"]))+"</small></td><td>"+escape(str(r["audience"]))+"</td><td>"+escape(str(r["message"]))+"</td><td><span class='ps-pill'>"+escape(str(r["status"]))+"</span></td></tr>" for r in rows) or "<tr><td colspan='4'>No notices have been published.</td></tr>"
    body="<section class='ps-card'><h2>Create parent communication / notice</h2><form method='post' action='/app/parent-services/notices/save' class='ps-form'><label>Notice title *<input name='title' required maxlength='180'></label><label>Audience<select name='audience'><option>All Parents</option><option>Parents of a Class</option><option>Parents of Selected Learners</option></select></label><label>Publish date *<input type='date' name='publish_date' required value='"+datetime.now().strftime("%Y-%m-%d")+"'></label><label>Status<select name='status'><option>Published</option><option>Draft</option></select></label><label class='wide'>Message *<textarea name='message' required maxlength='5000'></textarea></label><div class='wide ps-actions'><button class='ps-btn'>Save notice</button></div></form></section><section class='ps-card'><h2>Notices register</h2><div class='ps-table-wrap'><table><thead><tr><th>Notice</th><th>Audience</th><th>Message</th><th>Status</th></tr></thead><tbody>"+trs+"</tbody></table></div></section>"
    return _page(request,"Parent Communication & Notices","Prepare and maintain school notices for parent communication. Publishing here records the notice; external SMS/email delivery is not implied.",body)


@router.post("/app/parent-services/notices/save")
def parent_notice_save(request:Request,title:str=Form(...),audience:str=Form("All Parents"),message:str=Form(...),publish_date:str=Form(...),status:str=Form("Published")):
    sid,denied=_guard(request)
    if denied:return denied
    if audience not in ("All Parents","Parents of a Class","Parents of Selected Learners"):audience="All Parents"
    if status not in ("Published","Draft"):status="Draft"
    con=_db()
    try:
        cur=con.cursor();_schema(cur)
        cur.execute("INSERT INTO parent_service_notices(school_id,title,audience,message,publish_date,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",(sid,title.strip()[:180],audience,message.strip()[:5000],publish_date,status,str(request.session.get("email") or ""),_now()))
        _audit(cur,sid,request,"PARENT_NOTICE_CREATE","Saved parent notice: "+title.strip()[:180]);con.commit()
    except Exception as exc:
        con.rollback();print("PARENT NOTICE SAVE ERROR:",repr(exc),flush=True);return HTMLResponse("The notice could not be saved.",500)
    finally:con.close()
    return RedirectResponse("/app/parent-services/notices",303)


@router.get("/app/parent-services/meetings", response_class=HTMLResponse)
def parent_meetings(request:Request):
    sid,denied=_guard(request)
    if denied:return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur);students=_students(cur,sid)
        rows=cur.execute("""SELECT m.*,s.name student_name FROM parent_service_meetings m
            LEFT JOIN students s ON s.id=m.student_id AND s.school_id=m.school_id
            WHERE m.school_id=? ORDER BY m.meeting_date DESC,m.meeting_time DESC""",(sid,)).fetchall();con.commit()
    finally:con.close()
    trs="".join("<tr><td><b>"+escape(str(r["parent_name"]))+"</b><small>"+escape(str(r["phone"] or ""))+"</small></td><td>"+escape(str(r["student_name"] or "—"))+"</td><td>"+escape(str(r["meeting_date"]))+" "+escape(str(r["meeting_time"] or ""))+"</td><td>"+escape(str(r["purpose"]))+"</td><td><span class='ps-pill'>"+escape(str(r["status"]))+"</span></td></tr>" for r in rows) or "<tr><td colspan='5'>No parent meetings have been scheduled.</td></tr>"
    body="<section class='ps-card'><h2>Schedule a parent meeting</h2><form method='post' action='/app/parent-services/meetings/save' class='ps-form'><label>Parent / guardian name *<input name='parent_name' required maxlength='160'></label><label>Contact phone<input name='phone' maxlength='40'></label><label>Learner<select name='student_id'>"+_options(students)+"</select></label><label>Meeting date *<input type='date' name='meeting_date' required></label><label>Meeting time<input type='time' name='meeting_time'></label><label>Assigned staff<input name='assigned_to' maxlength='160'></label><label class='wide'>Purpose *<textarea name='purpose' required maxlength='2000'></textarea></label><div class='wide ps-actions'><button class='ps-btn'>Schedule meeting</button></div></form></section><section class='ps-card'><h2>Meetings & appointments</h2><div class='ps-table-wrap'><table><thead><tr><th>Parent</th><th>Learner</th><th>Date / time</th><th>Purpose</th><th>Status</th></tr></thead><tbody>"+trs+"</tbody></table></div></section>"
    return _page(request,"Parent Meetings & Appointments","Schedule and track parent consultations, academic conferences and follow-up appointments.",body)


@router.post("/app/parent-services/meetings/save")
def parent_meeting_save(request:Request,parent_name:str=Form(...),phone:str=Form(""),student_id:str=Form(""),meeting_date:str=Form(...),meeting_time:str=Form(""),purpose:str=Form(...),assigned_to:str=Form("")):
    sid,denied=_guard(request)
    if denied:return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur);student=int(student_id) if student_id.isdigit() else None
        if student and not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student,sid)).fetchone():return HTMLResponse("Learner not found in this school.",404)
        now=_now()
        cur.execute("INSERT INTO parent_service_meetings(school_id,parent_name,phone,student_id,meeting_date,meeting_time,purpose,assigned_to,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(sid,parent_name.strip()[:160],phone.strip()[:40],student,meeting_date,meeting_time,purpose.strip()[:2000],assigned_to.strip()[:160],"Scheduled",now,now))
        _audit(cur,sid,request,"PARENT_MEETING_CREATE","Scheduled parent meeting for "+parent_name.strip()[:160]);con.commit()
    except Exception as exc:
        con.rollback();print("PARENT MEETING SAVE ERROR:",repr(exc),flush=True);return HTMLResponse("The meeting could not be saved.",500)
    finally:con.close()
    return RedirectResponse("/app/parent-services/meetings",303)


@router.get("/app/parent-services/requests", response_class=HTMLResponse)
def parent_requests(request:Request):
    sid,denied=_guard(request)
    if denied:return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur);students=_students(cur,sid)
        rows=cur.execute("""SELECT r.*,s.name student_name FROM parent_service_requests r
            LEFT JOIN students s ON s.id=r.student_id AND s.school_id=r.school_id
            WHERE r.school_id=? ORDER BY r.created_at DESC""",(sid,)).fetchall()
        total=_count(cur,"parent_service_requests",sid);opened=int(cur.execute("SELECT COUNT(*) n FROM parent_service_requests WHERE school_id=? AND status IN ('Open','In Progress')",(sid,)).fetchone()["n"] or 0);con.commit()
    finally:con.close()
    trs="".join("<tr><td><b>"+escape(str(r["request_no"]))+"</b><small>"+escape(str(r["created_at"]))+"</small></td><td>"+escape(str(r["requester_name"]))+"<small>"+escape(str(r["requester_phone"] or ""))+"</small></td><td>"+escape(str(r["student_name"] or "—"))+"</td><td>"+escape(str(r["category"]))+" — "+escape(str(r["subject"]))+"</td><td>"+escape(str(r["priority"]))+"</td><td><span class='ps-pill'>"+escape(str(r["status"]))+"</span></td></tr>" for r in rows) or "<tr><td colspan='6'>No service requests have been recorded.</td></tr>"
    body="<div class='ps-kpis'><div><small>Total requests</small><strong>"+str(total)+"</strong></div><div><small>Open / in progress</small><strong>"+str(opened)+"</strong></div><div><small>Closed</small><strong>"+str(total-opened)+"</strong></div><div><small>Displayed</small><strong>"+str(len(rows))+"</strong></div></div><section class='ps-card'><h2>Record a parent / student service request</h2><form method='post' action='/app/parent-services/requests/save' class='ps-form'><label>Requester name *<input name='requester_name' required maxlength='160'></label><label>Phone<input name='requester_phone' maxlength='40'></label><label>Learner<select name='student_id'>"+_options(students)+"</select></label><label>Category<select name='category'><option>General Enquiry</option><option>Academic Support</option><option>Admission / Records</option><option>Student Welfare</option><option>Transport</option><option>Fees / Finance</option><option>Other</option></select></label><label>Subject *<input name='subject' required maxlength='180'></label><label>Priority<select name='priority'><option>Normal</option><option>High</option><option>Urgent</option></select></label><label class='wide'>Request details<textarea name='details' maxlength='3000'></textarea></label><div class='wide ps-actions'><button class='ps-btn'>Save service request</button></div></form></section><section class='ps-card'><h2>Request tracker</h2><div class='ps-table-wrap'><table><thead><tr><th>Request</th><th>Requester</th><th>Learner</th><th>Category / subject</th><th>Priority</th><th>Status</th></tr></thead><tbody>"+trs+"</tbody></table></div></section>"
    return _page(request,"Student Service Requests","Register and track parent or learner enquiries, requests and follow-up actions.",body)


@router.post("/app/parent-services/requests/save")
def parent_request_save(request:Request,requester_name:str=Form(...),requester_phone:str=Form(""),student_id:str=Form(""),category:str=Form("General Enquiry"),subject:str=Form(...),priority:str=Form("Normal"),details:str=Form("")):
    sid,denied=_guard(request)
    if denied:return denied
    if priority not in ("Normal","High","Urgent"):priority="Normal"
    con=_db()
    try:
        cur=con.cursor();_schema(cur);student=int(student_id) if student_id.isdigit() else None
        if student and not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student,sid)).fetchone():return HTMLResponse("Learner not found in this school.",404)
        now=_now();request_no="PSR-"+datetime.now().strftime("%y%m%d%H%M%S%f")
        cur.execute("INSERT INTO parent_service_requests(school_id,request_no,student_id,requester_name,requester_phone,category,subject,details,priority,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(sid,request_no,student,requester_name.strip()[:160],requester_phone.strip()[:40],category.strip()[:80],subject.strip()[:180],details.strip()[:3000],priority,"Open",now,now))
        _audit(cur,sid,request,"PARENT_SERVICE_REQUEST","Recorded "+request_no);con.commit()
    except Exception as exc:
        con.rollback();print("PARENT SERVICE REQUEST ERROR:",repr(exc),flush=True);return HTMLResponse("The service request could not be saved.",500)
    finally:con.close()
    return RedirectResponse("/app/parent-services/requests",303)


@router.get("/app/parent-services/reports", response_class=HTMLResponse)
def parent_service_reports(request:Request):
    sid,denied=_guard(request)
    if denied:return denied
    con=_db()
    try:
        cur=con.cursor();_schema(cur)
        contacts=int(cur.execute("""SELECT COUNT(*) n FROM (SELECT parent_name,parent_phone FROM students WHERE school_id=? AND (COALESCE(parent_name,'')<>'' OR COALESCE(parent_phone,'')<>'') GROUP BY parent_name,parent_phone) x""",(sid,)).fetchone()["n"] or 0)
        linked=int(cur.execute("SELECT COUNT(*) n FROM parent_student_links WHERE school_id=?",(sid,)).fetchone()["n"] or 0)
        accounts=int(cur.execute("SELECT COUNT(*) n FROM users WHERE school_id=? AND role='parent'",(sid,)).fetchone()["n"] or 0)
        notices=_count(cur,"parent_service_notices",sid);meetings=_count(cur,"parent_service_meetings",sid);requests=_count(cur,"parent_service_requests",sid)
        open_requests=int(cur.execute("SELECT COUNT(*) n FROM parent_service_requests WHERE school_id=? AND status IN ('Open','In Progress')",(sid,)).fetchone()["n"] or 0)
        con.commit()
    finally:con.close()
    body="<div class='ps-kpis'><div><small>Unique contacts</small><strong>"+str(contacts)+"</strong></div><div><small>Parent accounts</small><strong>"+str(accounts)+"</strong></div><div><small>Explicit learner links</small><strong>"+str(linked)+"</strong></div><div><small>Open requests</small><strong>"+str(open_requests)+"</strong></div></div><section class='ps-card'><h2>Parent & Student Services Summary</h2><div class='ps-table-wrap'><table><thead><tr><th>Measure</th><th>Recorded</th></tr></thead><tbody><tr><td>Parent / guardian contact groups</td><td>"+str(contacts)+"</td></tr><tr><td>Parent portal accounts</td><td>"+str(accounts)+"</td></tr><tr><td>Parent–learner links</td><td>"+str(linked)+"</td></tr><tr><td>Notices / communications</td><td>"+str(notices)+"</td></tr><tr><td>Parent meetings scheduled</td><td>"+str(meetings)+"</td></tr><tr><td>Total service requests</td><td>"+str(requests)+"</td></tr><tr><td>Open / in-progress requests</td><td>"+str(open_requests)+"</td></tr></tbody></table></div><div class='ps-actions'><button class='ps-btn' onclick='window.print()'>Print report</button></div></section>"
    return _page(request,"Parent & Student Services Reports","A school-scoped overview of parent contacts, portal access, links, notices, meetings and service requests.",body)
