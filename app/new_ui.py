from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from html import escape
import base64
import re
from urllib.parse import quote
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

router = APIRouter()

def _pdf_route_error(request, route_name, exc):
    import traceback
    print("DAVISCHOOL PDF ROUTE ERROR: %s %s %s" % (route_name, request.method, request.url.path), flush=True)
    print("DAVISCHOOL PDF ROUTE EXCEPTION: %r" % (exc,), flush=True)
    print(traceback.format_exc(), flush=True)
    detail = f"{type(exc).__name__}: {str(exc) or 'no exception message'}"
    safe_detail = escape(detail)[:800]
    return HTMLResponse(
        "DaviSchool PDF generation failed.<br><br><b>Technical detail:</b> " + safe_detail +
        "<br><br>Please send this exact technical detail to the developer so the failing database/query can be fixed.",
        status_code=500,
    )

# Standard selection lists used across school data-entry screens. These keep
# entry consistent while still allowing the database to store plain text.
TERM_OPTIONS = ("Term 1", "Term 2", "Term 3")
YEAR_OPTIONS = tuple(str(y) for y in range(datetime.now(ZoneInfo("Africa/Nairobi")).year, datetime.now(ZoneInfo("Africa/Nairobi")).year + 5))

def _parse_assessment_ids(exam_ids="", exam_id=""):
    """Safely normalize one or more assessment IDs without changing existing routes."""
    raw = exam_ids or exam_id or ""
    out = []
    for value in str(raw).split(","):
        try:
            value = int(value.strip())
            if value > 0 and value not in out:
                out.append(value)
        except (TypeError, ValueError):
            continue
    return out


def _average_selected_assessments(cur, school_id, student_id, exam_ids, term="", year=""):
    """Return subject-level averages for selected assessments.
    
    This calculation layer is deliberately isolated from the existing screens.
    Missing marks are ignored, while available assessment marks are averaged.
    """
    ids = _parse_assessment_ids(",".join(str(x) for x in (exam_ids or [])))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    sql = (
        "SELECT subject_id, marks FROM marks "
        "WHERE school_id=? AND student_id=? AND exam_id IN (" + placeholders + ")"
    )
    params = [school_id, student_id] + ids
    if term:
        sql += " AND term=?"
        params.append(term)
    if year:
        sql += " AND year=?"
        params.append(year)
    rows = cur.execute(sql, params).fetchall()
    buckets = {}
    for row in rows:
        if row["marks"] is None or str(row["marks"]).strip() == "":
            continue
        try:
            buckets.setdefault(int(row["subject_id"]), []).append(float(row["marks"]))
        except (TypeError, ValueError):
            continue
    return {subject_id: sum(values) / len(values) for subject_id, values in buckets.items() if values}


@router.get("/", response_class=HTMLResponse)
def davischool_login_page(request: Request):
    if request.session.get("email"):
        return RedirectResponse("/app", status_code=303)
    error = "<div class='err'>This school account is suspended. Please contact the DaviSchool administrator.</div>" if request.query_params.get("suspended") else ("<div class='err'>Invalid username or password.</div>" if request.query_params.get("error") else "")
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>DaviSchool Login</title><style>body{{margin:0;background:#eef5fb;font-family:Arial,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}}.box{{width:min(430px,92vw);background:white;border:1px solid #d8e3f0;border-top:4px solid #2E8B57;border-radius:18px;padding:32px;box-shadow:0 18px 50px #176B3A20}}.logo{{font-size:25px;font-weight:900;color:#176B3A;margin-bottom:5px}}.sub{{color:#64748b;margin-bottom:25px}}label{{display:block;font-size:13px;font-weight:800;color:#334155;margin:14px 0 7px}}input{{width:100%;box-sizing:border-box;padding:13px;border:1px solid #dbe2ea;border-radius:10px;font-size:15px}}button{{width:100%;margin-top:20px;padding:14px;border:0;border-radius:10px;background:#176B3A;color:white;font-weight:900;font-size:15px;cursor:pointer}}.err{{background:#fff1f2;border:1px solid #fda4af;color:#9f1239;padding:11px;border-radius:10px;margin-bottom:14px}}</style></head><body><div class='box'><div class='logo'>🏫 DaviSchool Management System</div><div class='sub'>Secure school management platform</div>{error}<form method='post' action='/login'><label>Username / Email</label><input name='email' type='text' autocomplete='username' required placeholder='Enter username or email'><label>Password</label><input name='password' type='password' autocomplete='current-password' required placeholder='Enter password'><button type='submit'>Sign In</button></form></div></body></html>""")

@router.post("/login")
def davischool_login(request: Request, email: str = Form(...), password: str = Form(...)):
    from app.main import verify_password
    con = _db()
    try:
        _ensure_user_account_columns(con.cursor(), con)
        login_value = email.strip().lower()
        user = con.execute("SELECT * FROM users WHERE lower(email)=? OR lower(username)=? LIMIT 1", (login_value, login_value)).fetchone()
    finally:
        con.close()
    if not user:
        return RedirectResponse("/?error=1", status_code=303)
    ok, legacy = verify_password(password, user["password"] or "")
    # Generated teacher accounts keep the initial password in temporary_password.
    # Accept that credential as a safe fallback and immediately replace the
    # stored password with the normal hash, so teacher login works even if the
    # account was created before the password hash was finalized.
    if not ok and user["role"] == "teacher":
        temporary_password = str(user["temporary_password"] or "") if "temporary_password" in user.keys() else ""
        if temporary_password and password == temporary_password:
            ok = True
            legacy = True
    if not ok:
        return RedirectResponse("/?error=1", status_code=303)
    if user["role"] == "school_admin":
        con = _db()
        try:
            school = con.execute("SELECT status FROM schools WHERE id=?", (user["school_id"],)).fetchone()
        finally:
            con.close()
        status = str(school["status"] or "active").strip().lower() if school else "suspended"
        if status not in ("active", "enabled"):
            return RedirectResponse("/?suspended=1", status_code=303)
    request.session["email"] = user["email"]
    request.session["role"] = user["role"]
    request.session["school_id"] = user["school_id"]
    request.session["teacher_id"] = user["teacher_id"] if "teacher_id" in user.keys() and user["teacher_id"] else None
    if user["role"] == "teacher" and not request.session.get("teacher_id") and user["school_id"]:
        con = _db()
        try:
            teacher_row = con.execute("SELECT id FROM teachers WHERE school_id=? AND lower(email)=lower(?) LIMIT 1", (user["school_id"], user["email"])).fetchone()
            if teacher_row:
                request.session["teacher_id"] = teacher_row["id"]
                try:
                    con.execute("UPDATE users SET teacher_id=? WHERE id=? AND school_id=?", (teacher_row["id"], user["id"], user["school_id"]))
                    con.commit()
                except Exception:
                    pass
        finally:
            con.close()
    request.session["name"] = user["full_name"] or user["email"]
    if legacy:
        from app.main import hash_password
        con = _db()
        con.execute("UPDATE users SET password=? WHERE id=?", (hash_password(password), user["id"]))
        con.commit(); con.close()
    return RedirectResponse("/app", status_code=303)

@router.get("/logout")
def davischool_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)

def _db():
    from app.main import get_db
    return get_db()

def _ensure_user_account_columns(cur, con=None):
    """Ensure generated-account columns exist on both SQLite and PostgreSQL."""
    cur.execute("SELECT * FROM users LIMIT 0")
    columns = {str(col.name if hasattr(col, "name") else col[0]).lower() for col in (cur.description or [])}
    changed = False
    for column, definition in (("username", "TEXT"), ("teacher_id", "INTEGER"), ("student_id", "INTEGER"), ("temporary_password", "TEXT")):
        if column not in columns:
            cur.execute("ALTER TABLE users ADD COLUMN %s %s" % (column, definition))
            columns.add(column)
            changed = True
    if changed and con is not None:
        con.commit()

def _pdf_response(pdf_bytes, filename):
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "davischool.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})


def _pdf_build(story, pagesize, title):
    from io import BytesIO
    from reportlab.platypus import SimpleDocTemplate, PageBreak
    from reportlab.lib.units import mm
    buffer = BytesIO()
    generated_at = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S EAT")

    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        footer = "DaviSchool Management System  ·  Generated: %s  ·  Page %d" % (
            generated_at, canvas.getPageNumber()
        )
        canvas.setFillColorRGB(0.04, 0.24, 0.57)
        canvas.drawCentredString(pagesize[0] / 2, 6 * mm, footer)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title=title,
        author="DaviSchool Management System",
    )
    try:
        doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
        return buffer.getvalue()
    except Exception as exc:
        print("DAVISCHOOL PDF STORY FALLBACK:", repr(exc), flush=True)

    # Emergency fallback: build a plain PDF without Platypus so a malformed
    # flowable, font, or table cannot turn the download into HTTP 500.
    try:
        from reportlab.pdfgen import canvas
        fallback_buffer = BytesIO()
        c = canvas.Canvas(fallback_buffer, pagesize=pagesize)
        c.setTitle(str(title))
        c.setAuthor("DaviSchool Management System")
        y = pagesize[1] - 18 * mm

        def ascii_text(value):
            return str(value).encode("ascii", "replace").decode("ascii")

        c.setFont("Helvetica-Bold", 13)
        c.drawString(12 * mm, y, ascii_text(title))
        y -= 9 * mm
        c.setFont("Helvetica", 7.5)

        try:
            for item in story:
                lines = []
                if hasattr(item, "getPlainText"):
                    lines = [item.getPlainText()]
                elif hasattr(item, "_cellvalues"):
                    for row in item._cellvalues:
                        vals = []
                        for cell in row:
                            if hasattr(cell, "getPlainText"):
                                vals.append(cell.getPlainText())
                            else:
                                vals.append(str(cell))
                        lines.append(" | ".join(vals))
                for line in lines:
                    text_line = re.sub(r"\s+", " ", str(line)).strip()
                    if not text_line:
                        continue
                    text_line = ascii_text(text_line)
                    for start_at in range(0, len(text_line), 115):
                        if y < 18 * mm:
                            c.setFont("Helvetica", 7)
                            c.drawCentredString(
                                pagesize[0] / 2,
                                7 * mm,
                                "DaviSchool Management System - Generated: %s - Page %d"
                                % (generated_at, c.getPageNumber()),
                            )
                            c.showPage()
                            y = pagesize[1] - 18 * mm
                            c.setFont("Helvetica", 7.5)
                        c.drawString(12 * mm, y, text_line[start_at:start_at + 115])
                        y -= 4.5 * mm
        except Exception as fallback_story_exc:
            print("DAVISCHOOL PDF TEXT FALLBACK:", repr(fallback_story_exc), flush=True)

        c.setFont("Helvetica", 7)
        c.drawCentredString(
            pagesize[0] / 2,
            7 * mm,
            "DaviSchool Management System - Generated: %s - Page %d"
            % (generated_at, c.getPageNumber()),
        )
        c.save()
        return fallback_buffer.getvalue()
    except Exception as fallback_exc:
        print("DAVISCHOOL PDF MINIMAL FALLBACK:", repr(fallback_exc), flush=True)
        # Last-resort PDF: no story parsing, no Unicode, no tables.
        from reportlab.pdfgen import canvas
        minimal_buffer = BytesIO()
        c = canvas.Canvas(minimal_buffer, pagesize=pagesize)
        c.setTitle("DaviSchool Management System")
        c.setFont("Helvetica-Bold", 12)
        c.drawString(12 * mm, pagesize[1] - 18 * mm, "DaviSchool Management System")
        c.setFont("Helvetica", 9)
        c.drawString(12 * mm, pagesize[1] - 28 * mm, "PDF generated successfully.")
        c.setFont("Helvetica", 7)
        c.drawCentredString(
            pagesize[0] / 2,
            7 * mm,
            "DaviSchool Management System - Generated: %s - Page %d"
            % (generated_at, c.getPageNumber()),
        )
        c.save()
        return minimal_buffer.getvalue()


def _pdf_styles():
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("DaviTitle", parent=styles["Title"], fontSize=15, leading=18, alignment=TA_CENTER, spaceAfter=5, textColor="#176B3A"),
        "subtitle": ParagraphStyle("DaviSubtitle", parent=styles["Normal"], fontSize=8, leading=10, alignment=TA_CENTER, spaceAfter=8, textColor="#176B3A"),
        "normal": ParagraphStyle("DaviNormal", parent=styles["Normal"], fontSize=8, leading=10),
        "report_student_name": ParagraphStyle("DaviReportStudentName", parent=styles["Normal"], fontSize=12, leading=14, spaceAfter=2, fontName="Helvetica-Bold"),
        "small": ParagraphStyle("DaviSmall", parent=styles["Normal"], fontSize=7, leading=9),
        "table": ParagraphStyle("DaviTable", parent=styles["Normal"], fontSize=6.5, leading=8),
        "table_head": ParagraphStyle("DaviTableHead", parent=styles["Normal"], fontSize=6.5, leading=8, alignment=TA_CENTER),
    }


def _pdf_school_header(school_row, styles, title, subtitle=""):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm
    from io import BytesIO
    name = str(school_row["name"] or "DaviSchool") if school_row else "DaviSchool"
    address_lines = []
    right_contact_lines = []
    if school_row:
        if "postal_address" in school_row.keys() and school_row["postal_address"]:
            address_lines.append("P.O. Box " + str(school_row["postal_address"]))
        if "postal_code" in school_row.keys() and school_row["postal_code"]:
            address_lines.append("Postal Code " + str(school_row["postal_code"]))
        if "phone" in school_row.keys() and school_row["phone"]:
            right_contact_lines.append("Phone: " + str(school_row["phone"]))
        if "email" in school_row.keys() and school_row["email"]:
            right_contact_lines.append("Email: " + str(school_row["email"]))
    logo_flowable = Paragraph("SCHOOL", styles["title"])
    logo_data = str(school_row["logo_data"] or "") if school_row and "logo_data" in school_row.keys() else ""
    if logo_data:
        try:
            from reportlab.platypus import Image
            raw = logo_data.split(",", 1)[1] if "," in logo_data and logo_data.split(",", 1)[0].startswith("data:") else logo_data
            logo_flowable = Image(BytesIO(base64.b64decode(raw)), width=22*mm, height=18*mm)
        except Exception:
            pass
    text = [Paragraph(escape(name).upper(), styles["title"])]
    text.extend(Paragraph(escape(line), styles["small"]) for line in address_lines)
    if subtitle:
        text.append(Paragraph(escape(subtitle), styles["small"]))
    right = [Paragraph(escape(line), styles["small"]) for line in right_contact_lines] or [Paragraph("", styles["small"])]
    table = Table([[logo_flowable, text, right]], colWidths=[30*mm, None, 52*mm])
    table.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LINEBELOW",(0,0),(-1,-1),1.8,colors.HexColor("#176B3A")),
        ("LINEABOVE",(0,0),(-1,-1),1.0,colors.HexColor("#2E8B57")),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),4),
        ("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))
    return [table, Spacer(1, 5), Paragraph(escape(title), styles["subtitle"])]

def _shell(title, name, role, body, school_id=None):
    # Sidebar visibility follows the same permission vocabulary enforced by
    # protected routes. Super Admin remains on platform-level navigation.
    if role == "super_admin":
        nav = [
            ("/app","⌂","Platform Overview",None),
            ("/schools/manage","🏫","Manage Schools",None),
            ("/super/global-control/dashboard","🌍","Global Control",None),
            ("/account/change-password","🔑","My Account",None),
        ]
    else:
        nav = [
            ("/app","⌂","Overview",None),
            ("/app/students","🎓","Students","students.view"),
            ("/app/staff","👩‍🏫","Staff & Teachers","staff.view"),
            ("/app/classes","🏫","Classes","classes.view"),
            ("/app/subjects","📚","Subjects","subjects.view"),
            ("/app/exams","🧪","Examinations","exams.view"),
            ("/app/academics","📝","Academics","marks.view"),
            ("/app/academics/allocations","👩‍🏫","Teacher Allocations","staff.edit"),
            ("/app/academics/assessments","📋","SBA / CBA","marks.edit"),
            ("/app/academics/analysis","📊","Academic Analysis","reports.view"),
            ("/app/report-cards","📄","Report Cards","reports.view"),
            ("/app/attendance","✓","Attendance","attendance.view"),
            ("/app/timetable","🗓","Timetable","timetable.view"),
            ("/app/finance","💰","Fees & Finance","fees.view"),
            ("/app/accounting","📚","Accounting","finance.view"),
            ("/app/announcements","📢","Announcements","communications.view"),
            ("/app/users","👤","Users","users.manage"),
            ("/app/roles","🔐","Roles & Permissions","settings.manage"),
            ("/app/school-settings","⚙","School Settings","settings.view"),
            ("/app/audit","🛡","Audit Trail","audit.view"),
        ]
        if role == "school_admin":
            nav.insert(7, ("/app/academics/marks-corrections","🔓","Marks Corrections",None))
        if role != "school_admin" and school_id:
            con = _db()
            try:
                cur = con.cursor()
                nav = [item for item in nav if item[3] is None or _permission_enabled(cur, int(school_id), role, item[3])]
            finally:
                con.close()
    # Teachers open directly on the Overview workspace with the dashboard/sidebar
    # locked out of sight. School Admin and Super Admin navigation is unchanged.
    teacher_locked = (role == "teacher")
    if teacher_locked:
        links = ""
    else:
        links = "".join(f"<a href='{u}' class='nav'><span>{i}</span>{escape(l)}</a>" for u,i,l,_ in nav)
    initials="".join(x[0] for x in (name or "DaviSchool").split()[:2]).upper()
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{escape(title)} · DaviSchool</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,Arial,sans-serif;background:#eef5fb;color:#172033;--navy:#176B3A;--navy-dark:#0F4D2A;--gold:#2E8B57;--ink:#172033;--line:#d8e3f0}}
.app{{display:flex;min-height:100vh}}.teacher-portal .side{{display:none}}.teacher-portal .main{{margin-left:0}}.side{{width:250px;background:var(--navy-dark);color:#dbeafe;padding:18px 12px;position:fixed;inset:0 auto 0 0;overflow:auto}}
.brand{{font-size:20px;font-weight:900;color:white;padding:8px 12px 24px}}.brand small{{display:block;font-size:10px;color:#bfdbfe;margin-top:4px;letter-spacing:1px}}
.nav{{display:flex;gap:11px;align-items:center;color:#dbeafe;text-decoration:none;padding:10px 12px;border-radius:10px;font-size:13px;margin:3px 0;border-left:3px solid transparent}}.nav:hover{{background:rgba(46,139,87,.16);color:white;border-left-color:var(--gold)}}
.main{{margin-left:250px;flex:1;min-width:0;transition:margin-left .2s ease}}.sidebar-toggle{{border:1px solid #cbd5e1;background:#fff;color:var(--navy);border-radius:9px;padding:7px 10px;font-size:16px;cursor:pointer;line-height:1}}.sidebar-toggle:hover{{background:#f8fafc}}.sidebar-hidden .side{{transform:translateX(-100%)}}.sidebar-hidden .main{{margin-left:0}}.top{{height:68px;background:white;border-bottom:3px solid var(--gold);display:flex;align-items:center;justify-content:space-between;padding:0 28px;position:sticky;top:0;z-index:1000}}
.avatar{{width:36px;height:36px;border-radius:50%;background:var(--navy);color:white;display:flex;align-items:center;justify-content:center;font-weight:800}}
.page{{padding:28px;max-width:1500px;margin:auto}}.btn,.btnlink{{background:var(--navy)!important;color:#fff!important;border-color:var(--navy)!important}}.btn:hover,.btnlink:hover{{background:var(--navy-dark)!important}}h1{{font-size:25px;margin:0 0 6px}}.muted{{color:#64748b;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin:22px 0}}.card{{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px;box-shadow:0 2px 8px #00000005}}.kpi{{font-size:28px;font-weight:900;margin-top:10px}}.label{{font-size:11px;color:#64748b;text-transform:uppercase;font-weight:800}}
.section{{margin-top:18px}}.section h2{{font-size:16px;margin:0 0 12px}}.actions{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;position:relative;z-index:1}}.action{{display:block;position:relative;z-index:2;background:white;border:1px solid #e5e7eb;border-radius:14px;padding:15px;text-decoration:none;color:#172033;font-weight:800;font-size:13px;cursor:pointer;pointer-events:auto}}.action span{{font-size:21px;display:block;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden}}th,td{{padding:12px;border-bottom:1px solid #eef2f7;text-align:left;font-size:12px}}th{{background:#f8fafc;color:#64748b;font-size:10px;text-transform:uppercase}}
@media(max-width:900px){{.side{{width:72px}}.brand{{font-size:0}}.brand:before{{content:'DS';font-size:18px}}.nav{{justify-content:center;font-size:0}}.nav span{{font-size:17px}}.main{{margin-left:72px}}.grid,.actions{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:600px){{.page{{padding:16px}}.grid,.actions{{grid-template-columns:1fr 1fr}}.top{{padding:0 16px}}}}
</style></head><body class='{{"sidebar-hidden" if teacher_locked else ""}}'><div class='app{" teacher-portal" if teacher_locked else ""}'><aside class='side'><div class='brand'>DaviSchool<small>MANAGEMENT PLATFORM</small></div>{links}{"" if teacher_locked else "<div style='padding:14px 12px;color:#94a3b8;font-size:10px;line-height:1.4'>Selection-based data entry is enabled throughout the school workspace.</div><a href='/logout' class='nav' style='margin-top:18px'>↪ Logout</a>"}</aside>
<main class='main'><header class='top'><div style='display:flex;align-items:center;gap:10px'>{"" if teacher_locked else "<button type='button' class='sidebar-toggle' id='sidebarToggle' aria-label='Hide sidebar' title='Hide sidebar' onclick='toggleSidebar()'>☰</button>"}<div><strong>{escape(title)}</strong><div class='muted'>{escape(role.replace("_"," ").title())}</div></div></div><div style='display:flex;gap:10px;align-items:center'><span class='muted'>{escape(name)}</span><div class='avatar'>{escape(initials)}</div></div></header>{body}<script>(function(){{try{{if(!{str(teacher_locked).lower()} && localStorage.getItem('davischool_sidebar_hidden')==='1')document.body.classList.add('sidebar-hidden');}}catch(e){{}}}})();function toggleSidebar(){{var hidden=document.body.classList.toggle('sidebar-hidden');var b=document.getElementById('sidebarToggle');if(b){{b.setAttribute('aria-label',hidden?'Show sidebar':'Hide sidebar');b.setAttribute('title',hidden?'Show sidebar':'Hide sidebar');}}try{{localStorage.setItem('davischool_sidebar_hidden',hidden?'1':'0');}}catch(e){{}}}}</script><script>(function(){{let lastPing=0;let lastActivity=Date.now();const PING_EVERY=60000;const ACTIVE_WINDOW=120000;function markActivity(){{lastActivity=Date.now();ping(true);}}function ping(force){{const now=Date.now();if(!force && now-lastActivity>ACTIVE_WINDOW)return;if(now-lastPing<60000)return;lastPing=now;try{{fetch('/app/session-keepalive',{{method:'GET',credentials:'same-origin',cache:'no-store'}}).catch(function(){{}});}}catch(e){{}}}}['click','dblclick','mousedown','pointerdown','touchstart','touchmove','keydown','input','change','scroll','wheel'].forEach(function(ev){{document.addEventListener(ev,markActivity,{{passive:true}});}});setInterval(function(){{if(Date.now()-lastActivity<=ACTIVE_WINDOW)ping(false);}},PING_EVERY);}})();</script><script>(function(){{
// Collapse repeated visits to the same school workspace when using the phone Back button.
// This applies to Students, Staff/Teachers, Teacher Allocations, Academics,
// Analysis, Report Cards, Attendance, Timetable and the other school modules.
// A Back action may skip repeated entries of the same workspace, but it still
// stops normally when the user reaches a different sidebar workspace or Overview.
(function(){{
  try{{
    var currentPath=window.location.pathname;
    var key='davischool_workspace_path';
    sessionStorage.setItem(key,currentPath);
    window.addEventListener('popstate',function(){{
      var nowPath=window.location.pathname;
      var lastPath=sessionStorage.getItem(key)||'';
      if(nowPath===lastPath && nowPath.indexOf('/app')===0){{
        window.setTimeout(function(){{window.history.go(-1);}},0);
        return;
      }}
      sessionStorage.setItem(key,nowPath);
    }});
  }}catch(e){{}}
}})();
// Keep routine school data-entry saves from filling the phone/browser Back stack.
// A successful POST is followed by a normal page load, but replace that entry
// so repeated saves on the same workspace do not require dozens of Back presses.
document.addEventListener('submit',function(event){{
  var form=event.target;
  if(!form || String(form.method||'get').toLowerCase()!=='post')return;
  var submitter=event.submitter;
  // A submit button may override the form action/method with formaction/formmethod.
  // This is required for Marks: School Admin uses the same form for Save Marks
  // and Submit & Lock Marks, so the lock button must reach /marks/finalize rather
  // than being intercepted and sent to /marks/save.
  var action=(submitter && (submitter.getAttribute('formaction') || submitter.formAction)) || form.getAttribute('action') || window.location.href;
  var method=(submitter && (submitter.getAttribute('formmethod') || submitter.formMethod)) || form.getAttribute('method') || 'get';
  try{{
    var url=new URL(action,window.location.href);
    if(url.origin!==window.location.origin)return;
    var path=url.pathname.toLowerCase();
    // Preserve normal browser navigation for downloads/print/PDF actions.
    if(path==='/app/academics/marks/save' || path==='/app/academics/marks/save-draft' || path==='/app/academics/marks/delete' || path==='/app/academics/marks/finalize' || path==='/app/academics/marks-corrections/lock' || path==='/app/academics/marks/unfinalize' || path==='/app/academics/marks-corrections/approve' || path==='/app/academics/marks-corrections/reject' || path==='/app/academics/marks-corrections/clear' || path==='/app/users' || path==='/app/users/add' || path==='/app/exams' || path==='/app/exams/add' || path==='/app/report-card-settings' || path==='/app/classes/class-teacher' || path==='/app/academics/allocations/add' || path.indexOf('/app/academics/allocations/delete/')===0 || path.indexOf('/app/academics/allocations/edit/')===0 || path.indexOf('/app/subjects/delete/')===0 || path.indexOf('/app/exams/delete/')===0 || path.indexOf('/app/exams/edit/')===0 || path.indexOf('/app/classes/delete/')===0 || path.indexOf('/app/classes/edit/')===0 ||
       path==='/app/subjects/add')return;
    if(path.indexOf('/pdf')===0 || path.indexOf('/print')===0 || path.indexOf('/download')===0 || path.indexOf('/export')===0 || form.target==='_blank' || form.hasAttribute('download'))return;
    event.preventDefault();
    var data=new FormData(form);
    if(submitter && submitter.name && !data.has(submitter.name))data.append(submitter.name,submitter.value||'');
    fetch(url.toString(),{{method:String(method).toUpperCase(),body:data,credentials:'same-origin',redirect:'follow',headers:{{'X-DaviSchool-History':'replace'}}}})
      .then(function(response){{
        if(!response.ok){{window.location.href=response.url||url.toString();return;}}
        window.location.replace(response.url||url.toString());
      }})
      .catch(function(){{window.location.href=url.toString();}});
  }}catch(e){{}}
}},true);
}})();</script></main></div></body></html>"""
@router.get("/app/session-keepalive")
def session_keepalive(request: Request):
    """Refresh an active authenticated session when the user is interacting with the workspace."""
    if "email" not in request.session:
        return JSONResponse({"authenticated": False}, status_code=401)
    request.session["_last_activity"] = datetime.now().timestamp()
    return JSONResponse({"authenticated": True})

def _school_session(request):
    role = str(request.session.get("role", ""))
    if "email" not in request.session or role not in ("school_admin", "teacher"):
        return None
    sid = int(request.session.get("school_id") or 0)
    if not sid:
        return None
    con = _db()
    try:
        school = con.execute("SELECT status FROM schools WHERE id=?", (sid,)).fetchone()
    finally:
        con.close()
    status = str(school["status"] or "active").strip().lower() if school else "suspended"
    if status not in ("active", "enabled"):
        request.session.clear()
        return None
    return sid

def _audit(cur, school_id, request, action, details):
    ts=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO system_audit(school_id,user_email,action,details,timestamp) VALUES(?,?,?,?,?)",
                (school_id,request.session.get("email",""),action,details,ts))

def _permission_enabled(cur, school_id, role, permission):
    # No custom rule means preserve the existing role behavior.
    row=cur.execute("SELECT enabled FROM roles_permissions WHERE school_id=? AND role=? AND permission=? ORDER BY id DESC LIMIT 1",
                    (school_id,role,permission)).fetchone()
    return True if row is None else bool(int(row["enabled"] or 0))

def _require_permission(request, school_id, permission):
    """Enforce the School Admin configured permission for every school role."""
    role=str(request.session.get("role",""))
    if role=="school_admin":
        return True
    con=_db()
    try:
        return _permission_enabled(con.cursor(),school_id,role,permission)
    finally:
        con.close()

def _teacher_class_authorized(cur, request, school_id, class_id, subject_id=None):
    """Restrict teacher academic actions to their allocated class/subject."""
    if str(request.session.get("role","")) != "teacher":
        return True
    teacher_id = request.session.get("teacher_id")
    if not teacher_id:
        return False
    if subject_id:
        return bool(cur.execute(
            "SELECT 1 FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND class_id=? AND subject_id=? LIMIT 1",
            (school_id, teacher_id, class_id, subject_id)
        ).fetchone())
    return bool(cur.execute(
        "SELECT 1 FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND class_id=? LIMIT 1",
        (school_id, teacher_id, class_id)
    ).fetchone())

def _school_page(request, title, body):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    return HTMLResponse(_shell(title,request.session.get("name","DaviSchool"),request.session.get("role",""),body,sid))

@router.get("/app/class-teacher", response_class=HTMLResponse)
def class_teacher_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if str(request.session.get("role",""))!="teacher":
        return RedirectResponse("/app")
    con=_db();cur=con.cursor()
    if not _require_permission(request,sid,"class_teacher.view"):
        con.close()
        return HTMLResponse("Class Teacher access has been disabled by the School Admin.",403)
    teacher_id=int(request.session.get("teacher_id") or 0)
    _ensure_class_teacher_assignments_table(cur)
    assignment=cur.execute("""SELECT a.class_id,c.name class_name,c.level,c.stream
        FROM class_teacher_assignments a JOIN classes c ON c.id=a.class_id
        WHERE a.school_id=? AND a.teacher_id=? LIMIT 1""",(sid,teacher_id)).fetchone()
    if not assignment:
        con.close()
        body="""<div class='page'><h1>🏫 My Class</h1><div class='card section'><h2>No class assigned</h2><div class='muted'>The School Admin has not linked your account to a class as Class Teacher yet.</div></div></div>"""
        return _school_page(request,"My Class",body)
    cid=int(assignment["class_id"])
    students=cur.execute("""SELECT s.id,s.admission_no,s.name,s.gender,s.parent_phone,s.status
        FROM students s WHERE s.school_id=? AND s.class_id=? ORDER BY s.name""",(sid,cid)).fetchall()
    edit_enabled=_require_permission(request,sid,"class_teacher.edit")
    con.close()
    rows="".join(
        f"<tr><td>{escape(str(s['admission_no'] or ''))}</td><td><b>{escape(str(s['name'] or ''))}</b></td><td>{escape(str(s['gender'] or ''))}</td><td>{escape(str(s['parent_phone'] or ''))}</td><td>{escape(str(s['status'] or 'Active'))}</td><td><a class='action' href='/app/students/history/{int(s['id'])}'>📋 History</a></td></tr>"
        for s in students
    )
    controls=f"""<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:12px'>
<a class='action' href='/app/academics/marks?class_id={cid}'>📝 Class Marks</a>
<a class='action' href='/app/report-cards?class_id={cid}'>📄 Report Cards</a>
</div>""" if edit_enabled else """<div class='muted' style='margin-top:12px'>Editing controls are restricted by the School Admin. You currently have view-only class access.</div>"""
    body=f"""<div class='page'><h1>🏫 My Class</h1><div class='muted'>Class Teacher workspace. Access is limited to the class assigned to your teacher profile.</div>
<div class='grid'><div class='card'><div class='label'>Class</div><div class='kpi'>{escape(str(assignment['class_name'] or ''))}{(' · '+escape(str(assignment['stream'] or ''))) if assignment['stream'] else ''}</div></div><div class='card'><div class='label'>Level</div><div class='kpi'>{escape(str(assignment['level'] or ''))}</div></div><div class='card'><div class='label'>Students</div><div class='kpi'>{len(students)}</div></div></div>
<div class='card section'><h2>Class controls</h2>{controls}</div>
<div class='card section'><h2>Students in my class ({len(students)})</h2><div style='overflow-x:auto'><table><thead><tr><th>Admission No.</th><th>Name</th><th>Gender</th><th>Parent Phone</th><th>Status</th><th>Details</th></tr></thead><tbody>{rows or "<tr><td colspan='6'>No students are currently assigned to this class.</td></tr>"}</tbody></table></div></div>"""
    return _school_page(request,"My Class",body)

@router.get("/app/students", response_class=HTMLResponse)
def students_page(request: Request):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    if not _require_permission(request, sid, "students.view"):
        return HTMLResponse("You do not have permission to view students.", 403)
    con=_db(); cur=con.cursor(); _ensure_student_history_table(cur)
    students=cur.execute("""SELECT s.*,c.name class_name,c.stream class_stream
        FROM students s LEFT JOIN classes c ON c.id=s.class_id
        WHERE s.school_id=? ORDER BY s.id DESC""",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    con.close()
    rows="".join(f"""<tr><td>{escape(str(s['admission_no'] or ''))}</td><td><b>{escape(str(s['name'] or ''))}</b></td>
      <td>{escape(str(s['class_name'] or 'Unassigned'))} {escape(str(s['class_stream'] or ''))}</td><td>{escape(str(s['gender'] or ''))}</td>
      <td>{escape(str(s['parent_phone'] or ''))}</td><td>{escape(str(s['status'] if 'status' in s.keys() and s['status'] else 'Active'))}</td>
      <td><a class='action' href='/app/students/edit/{s["id"]}'>Edit</a> <a class='action' href='/app/students/history/{s["id"]}'>History</a></td></tr>""" for s in students)
    opts="".join(f"<option value='{c['id']}'>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    body=f"""<div class='page'><h1>Students</h1><div class='muted'>Student register, admissions, transfers and academic-history management.</div>
<div class='card section'><h2>Add student</h2><form method='post' action='/app/students/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<input name='admission_no' required placeholder='Admission number' class='field'><input name='name' required placeholder='Full name' class='field'><select name='class_id' class='field'><option value=''>Class</option>{opts}</select>
<select name='gender' class='field'><option value=''>Gender</option><option>Male</option><option>Female</option><option>Other</option></select><input name='parent_phone' placeholder='Parent phone' class='field'><input name='assessment_no' placeholder='Assessment number' class='field'>
<button class='btn'>Save Student</button></form></div>
<div class='card section'><div style='display:flex;justify-content:space-between'><h2>Student register ({len(students)})</h2><a class='action' href='/app/students'>Refresh</a></div>
<table><thead><tr><th>Admission</th><th>Name</th><th>Class</th><th>Gender</th><th>Parent phone</th><th>Status</th><th>Action</th></tr></thead>
<tbody>{rows or '<tr><td colspan=7>No students yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}</style>"""
    return _school_page(request,"Students",body)

@router.post("/app/students/add")
def students_add(request: Request, admission_no:str=Form(...), name:str=Form(...), class_id:str=Form(""), gender:str=Form(""), parent_phone:str=Form(""), assessment_no:str=Form("")):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/",303)
    if not _require_permission(request, sid, "students.create"):
        return HTMLResponse("You do not have permission to create students.", 403)
    con=_db(); cur=con.cursor(); _ensure_student_history_table(cur)
    admission=admission_no.strip()
    if cur.execute("SELECT id FROM students WHERE school_id=? AND lower(admission_no)=lower(?)",(sid,admission)).fetchone():
        con.close(); return HTMLResponse("Admission number already exists. <a href='/app/students'>Back</a>",400)
    cid=int(class_id) if class_id.isdigit() else None
    class_stream = ""
    if cid:
        class_row = cur.execute("SELECT id,stream FROM classes WHERE id=? AND school_id=?",(cid,sid)).fetchone()
        if not class_row:
            cid=None
        else:
            class_stream = str(class_row["stream"] or "").strip()
    cur.execute("INSERT INTO students(school_id,admission_no,assessment_no,name,class_id,gender,parent_phone,stream,status) VALUES(?,?,?,?,?,?,?,?,?)",(sid,admission,assessment_no.strip(),name.strip(),cid,gender.strip(),parent_phone.strip(),class_stream,"active"))
    student_id=cur.lastrowid
    _audit(cur,sid,request,"STUDENT_CREATE",f"Created student {name.strip()} ({admission})")
    con.commit(); con.close(); return RedirectResponse("/app/students",303)

@router.get("/app/students/edit/{student_id}",response_class=HTMLResponse)
def student_edit_page(request: Request,student_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "students.edit"):
        return HTMLResponse("You do not have permission to edit students.", 403)
    con=_db();cur=con.cursor()
    st=cur.execute("SELECT * FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    con.close()
    if not st:return HTMLResponse("Student not found.",404)
    opts="".join(f"<option value='{c['id']}' {'selected' if st['class_id'] and int(st['class_id'])==int(c['id']) else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    body=f"""<div class='page'><h1>Edit Student</h1><div class='card section'><form method='post' style='display:grid;grid-template-columns:repeat(2,1fr);gap:10px'>
<label>Admission number<input name='admission_no' value='{escape(str(st['admission_no'] or ''))}' required class='field'></label>
<label>Full name<input name='name' value='{escape(str(st['name'] or ''))}' required class='field'></label>
<label>Assessment number<input name='assessment_no' value='{escape(str(st['assessment_no'] or ''))}' class='field'></label>
<label>Class<select name='class_id' class='field'><option value=''>Unassigned</option>{opts}</select></label>
<label>Gender<select name='gender' class='field'><option>{escape(str(st['gender'] or ''))}</option><option>Male</option><option>Female</option><option>Other</option></select></label>
<label>Parent phone<input name='parent_phone' value='{escape(str(st['parent_phone'] or ''))}' class='field'></label>
<label>Status<select name='status' class='field'><option value='active'>Active</option><option value='inactive'>Inactive</option><option value='graduated'>Graduated</option><option value='transferred'>Transferred</option></select></label>
<div><button class='btn'>Save Changes</button> <a class='action' href='/app/students'>Cancel</a></div></form></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;margin-top:5px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Edit Student",body)

@router.post("/app/students/edit/{student_id}")
def student_edit(request: Request,student_id:int,admission_no:str=Form(...),name:str=Form(...),assessment_no:str=Form(""),class_id:str=Form(""),gender:str=Form(""),parent_phone:str=Form(""),status:str=Form("active")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "students.edit"):
        return HTMLResponse("You do not have permission to edit students.", 403)
    con=_db();cur=con.cursor();_ensure_student_history_table(cur)
    st=cur.execute("SELECT * FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone()
    if not st:con.close();return HTMLResponse("Student not found.",404)
    admission=admission_no.strip()
    dup=cur.execute("SELECT id FROM students WHERE school_id=? AND lower(admission_no)=lower(?) AND id<>?",(sid,admission,student_id)).fetchone()
    if dup:con.close();return HTMLResponse("Admission number already exists.",400)
    cid=int(class_id) if class_id.isdigit() else None
    class_stream = ""
    if cid:
        class_row = cur.execute("SELECT id,stream FROM classes WHERE id=? AND school_id=?",(cid,sid)).fetchone()
        if not class_row:
            con.close();return HTMLResponse("Invalid class.",400)
        class_stream = str(class_row["stream"] or "").strip()
    old_class=st["class_id"];new_status=status.strip().lower() if status.strip().lower() in ("active","inactive","graduated","transferred") else "active"
    cur.execute("UPDATE students SET admission_no=?,assessment_no=?,name=?,class_id=?,gender=?,parent_phone=?,stream=?,status=? WHERE id=? AND school_id=?",(admission,assessment_no.strip(),name.strip(),cid,gender.strip(),parent_phone.strip(),class_stream,new_status,student_id,sid))
    if (old_class or None)!=(cid or None):
        now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO student_class_history(school_id,student_id,from_class_id,to_class_id,changed_at,changed_by,reason) VALUES(?,?,?,?,?,?,?)",(sid,student_id,old_class,cid,now,request.session.get("email",""),"Student class/stream transfer"))
        _audit(cur,sid,request,"STUDENT_TRANSFER",f"Transferred {name.strip()} from class {old_class or 'Unassigned'} to {cid or 'Unassigned'}")
    _audit(cur,sid,request,"STUDENT_UPDATE",f"Updated student {name.strip()} ({admission})")
    con.commit();con.close();return RedirectResponse("/app/students",303)

@router.get("/app/students/history/{student_id}",response_class=HTMLResponse)
def student_history(request: Request,student_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "students.view"):
        return HTMLResponse("You do not have permission to view student history.", 403)
    con=_db();cur=con.cursor();_ensure_student_history_table(cur)
    st=cur.execute("SELECT * FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone()
    hist=cur.execute("""SELECT h.*,f.name from_class,t.name to_class
        FROM student_class_history h LEFT JOIN classes f ON f.id=h.from_class_id LEFT JOIN classes t ON t.id=h.to_class_id
        WHERE h.student_id=? AND h.school_id=? ORDER BY h.id DESC""",(student_id,sid)).fetchall()
    con.close()
    if not st:return HTMLResponse("Student not found.",404)
    rows="".join(f"<tr><td>{escape(str(h['changed_at'] or ''))}</td><td>{escape(str(h['from_class'] or 'Unassigned'))}</td><td>{escape(str(h['to_class'] or 'Unassigned'))}</td><td>{escape(str(h['changed_by'] or ''))}</td><td>{escape(str(h['reason'] or ''))}</td></tr>" for h in hist)
    body=f"""<div class='page'><h1>Student History</h1><div class='card section'><h2>{escape(str(st['name']))}</h2><div class='muted'>Admission: {escape(str(st['admission_no'] or ''))}</div><table><thead><tr><th>Date</th><th>From Class</th><th>To Class</th><th>Changed By</th><th>Reason</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No class transfer history recorded yet.</td></tr>'}</tbody></table></div></div>"""
    return _school_page(request,"Student History",body)

@router.get("/app/staff", response_class=HTMLResponse)
def staff_page(request: Request):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    if not _require_permission(request, sid, "staff.view"):
        return HTMLResponse("You do not have permission to view staff records.", 403)
    con=_db(); cur=con.cursor()
    staff=cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    con.close()
    def val(t,key,default=""):
        try: return str(t[key] if t[key] is not None else default)
        except Exception: return default
    rows="".join(f"""<tr><td><b>{escape(val(t,'name'))}</b><div class='muted'>{escape(val(t,'tsc_no'))}</div></td><td>{escape(val(t,'role'))}</td><td>{escape(val(t,'email'))}</td><td>{escape(val(t,'phone'))}</td><td>{escape(val(t,'employment_type'))}</td><td><span class='status'>{escape(val(t,'status','active').replace('_',' ').title())}</span></td><td><a class='action' href='/app/staff/edit/{t["id"]}'>Edit</a> <a class='action' href='/app/academics/allocations?teacher_id={t["id"]}'>Teaching</a></td></tr>""" for t in staff)
    body=f"""<div class='page'><h1>Staff & Teachers</h1><div class='muted'>Staff directory, employment status, teacher profiles and academic responsibilities.</div>
<div class='card section'><h2>Add staff member</h2><form method='post' action='/app/staff/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<input name='name' required placeholder='Full name' class='field'><input name='email' type='email' placeholder='Email' class='field'><input name='phone' placeholder='Phone' class='field'><input name='tsc_no' placeholder='TSC number' class='field'><input name='id_no' placeholder='ID number' class='field'>
<select name='role' class='field'><option>Teacher</option><option>Deputy Teacher</option><option>Head of Department</option><option>Head Teacher</option><option>Principal</option><option>Bursar</option><option>Secretary</option><option>Support Staff</option></select>
<select name='gender' class='field'><option value=''>Gender</option><option>Male</option><option>Female</option><option>Other</option></select><select name='employment_type' class='field'><option>Permanent</option><option>Contract</option><option>Part-time</option></select>
<select name='status' class='field'><option value='active'>Active</option><option value='inactive'>Inactive</option><option value='on_leave'>On Leave</option><option value='left'>Left School</option></select>
<input name='department' placeholder='Department / responsibility' class='field'><button class='btn'>Save Staff</button></form></div>
<div class='card section'><div style='display:flex;justify-content:space-between;align-items:center'><h2>Staff register ({len(staff)})</h2><a class='action' href='/app/academics/allocations'>Teacher Allocation</a></div>
<table><thead><tr><th>Name / TSC</th><th>Role</th><th>Email</th><th>Phone</th><th>Employment</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows or '<tr><td colspan=7>No staff yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}.status{{display:inline-block;padding:5px 9px;border-radius:999px;background:#eef2ff;font-size:11px;font-weight:800}}</style>"""
    return _school_page(request,"Staff & Teachers",body)

@router.post("/app/staff/add")
def staff_add(request: Request,name:str=Form(...),email:str=Form(""),phone:str=Form(""),tsc_no:str=Form(""),id_no:str=Form(""),role:str=Form("Teacher"),gender:str=Form(""),employment_type:str=Form("Permanent"),status:str=Form("active"),department:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "staff.create"):
        return HTMLResponse("You do not have permission to add staff.", 403)
    allowed_status=("active","inactive","on_leave","left")
    new_status=status.strip().lower() if status.strip().lower() in allowed_status else "active"
    con=_db();cur=con.cursor(); email_v=email.strip(); tsc_v=tsc_no.strip(); id_v=id_no.strip()
    if email_v and cur.execute("SELECT id FROM teachers WHERE school_id=? AND lower(email)=lower(?)",(sid,email_v)).fetchone():
        con.close(); return HTMLResponse("A staff member with that email already exists. <a href='/app/staff'>Back</a>",400)
    if tsc_v and cur.execute("SELECT id FROM teachers WHERE school_id=? AND lower(tsc_no)=lower(?)",(sid,tsc_v)).fetchone():
        con.close(); return HTMLResponse("That TSC number already exists. <a href='/app/staff'>Back</a>",400)
    if id_v and cur.execute("SELECT id FROM teachers WHERE school_id=? AND lower(id_no)=lower(?)",(sid,id_v)).fetchone():
        con.close(); return HTMLResponse("That ID number already exists. <a href='/app/staff'>Back</a>",400)
    cur.execute("INSERT INTO teachers(school_id,name,email,phone,tsc_no,gender,id_no,role,employment_type,status,department) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(sid,name.strip(),email_v,phone.strip(),tsc_v,gender.strip(),id_v,role.strip(),employment_type.strip(),new_status,department.strip()))
    _audit(cur,sid,request,"STAFF_CREATE",f"Created staff member {name.strip()}")
    con.commit();con.close();return RedirectResponse("/app/staff",303)

@router.get("/app/staff/edit/{teacher_id}",response_class=HTMLResponse)
def staff_edit_page(request: Request,teacher_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "staff.edit"):
        return HTMLResponse("You do not have permission to edit staff records.", 403)
    con=_db();cur=con.cursor(); t=cur.execute("SELECT * FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone(); con.close()
    if not t:return HTMLResponse("Staff member not found.",404)
    def val(key,default=""):
        try:return str(t[key] if t[key] is not None else default)
        except Exception:return default
    status=val("status","active")
    body=f"""<div class='page'><h1>Edit Staff / Teacher</h1><div class='card section'><form method='post' style='display:grid;grid-template-columns:repeat(2,1fr);gap:10px'>
<label>Full name<input name='name' value='{escape(val("name"))}' required class='field'></label><label>Email<input name='email' type='email' value='{escape(val("email"))}' class='field'></label>
<label>Phone<input name='phone' value='{escape(val("phone"))}' class='field'></label><label>TSC number<input name='tsc_no' value='{escape(val("tsc_no"))}' class='field'></label>
<label>ID number<input name='id_no' value='{escape(val("id_no"))}' class='field'></label><label>Role<select name='role' class='field'><option>{escape(val("role","Teacher"))}</option><option>Teacher</option><option>Deputy Teacher</option><option>Head of Department</option><option>Head Teacher</option><option>Principal</option><option>Bursar</option><option>Secretary</option><option>Support Staff</option></select></label>
<label>Gender<select name='gender' class='field'><option>{escape(val("gender"))}</option><option>Male</option><option>Female</option><option>Other</option></select></label><label>Employment type<select name='employment_type' class='field'><option>{escape(val("employment_type","Permanent"))}</option><option>Permanent</option><option>Contract</option><option>Part-time</option></select></label>
<label>Status<select name='status' class='field'><option value='active' {'selected' if status=='active' else ''}>Active</option><option value='inactive' {'selected' if status=='inactive' else ''}>Inactive</option><option value='on_leave' {'selected' if status=='on_leave' else ''}>On Leave</option><option value='left' {'selected' if status=='left' else ''}>Left School</option></select></label>
<label>Department / responsibility<input name='department' value='{escape(val("department"))}' class='field'></label><div><button class='btn'>Save Changes</button> <a class='action' href='/app/staff'>Cancel</a></div></form></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;margin-top:5px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Edit Staff / Teacher",body)

@router.post("/app/staff/edit/{teacher_id}")
def staff_edit(request: Request,teacher_id:int,name:str=Form(...),email:str=Form(""),phone:str=Form(""),tsc_no:str=Form(""),id_no:str=Form(""),role:str=Form("Teacher"),gender:str=Form(""),employment_type:str=Form("Permanent"),status:str=Form("active"),department:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "staff.edit"):
        return HTMLResponse("You do not have permission to edit staff records.", 403)
    allowed_status=("active","inactive","on_leave","left"); new_status=status.strip().lower() if status.strip().lower() in allowed_status else "active"
    con=_db();cur=con.cursor(); t=cur.execute("SELECT * FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone()
    if not t:con.close();return HTMLResponse("Staff member not found.",404)
    email_v=email.strip();tsc_v=tsc_no.strip();id_v=id_no.strip()
    if email_v and cur.execute("SELECT id FROM teachers WHERE school_id=? AND lower(email)=lower(?) AND id<>?",(sid,email_v,teacher_id)).fetchone():
        con.close();return HTMLResponse("A staff member with that email already exists.",400)
    if tsc_v and cur.execute("SELECT id FROM teachers WHERE school_id=? AND lower(tsc_no)=lower(?) AND id<>?",(sid,tsc_v,teacher_id)).fetchone():
        con.close();return HTMLResponse("That TSC number already exists.",400)
    if id_v and cur.execute("SELECT id FROM teachers WHERE school_id=? AND lower(id_no)=lower(?) AND id<>?",(sid,id_v,teacher_id)).fetchone():
        con.close();return HTMLResponse("That ID number already exists.",400)
    cur.execute("UPDATE teachers SET name=?,email=?,phone=?,tsc_no=?,gender=?,id_no=?,role=?,employment_type=?,status=?,department=? WHERE id=? AND school_id=?",(name.strip(),email_v,phone.strip(),tsc_v,gender.strip(),id_v,role.strip(),employment_type.strip(),new_status,department.strip(),teacher_id,sid))
    _audit(cur,sid,request,"STAFF_UPDATE",f"Updated staff member {name.strip()} ({teacher_id})")
    con.commit();con.close();return RedirectResponse("/app/staff",303)

@router.get("/app/academics", response_class=HTMLResponse)
def academics_page(request: Request, exam_id: str = "", class_id: str = "", subject_id: str = "", term: str = "", year: str = ""):
    sid = _school_session(request)
    if not sid: return RedirectResponse("/")
    if not _require_permission(request, sid, "marks.view"):
        return HTMLResponse("You do not have permission to view academic records.", 403)
    con = _db(); cur = con.cursor()
    role = str(request.session.get("role",""))
    allocations = []
    if role == "teacher":
        teacher_id = int(request.session.get("teacher_id") or 0)
        if teacher_id:
            allocations = cur.execute("""SELECT DISTINCT class_id,subject_id
                FROM teacher_allocations
                WHERE school_id=? AND teacher_id=?
                ORDER BY class_id,subject_id""",(sid,teacher_id)).fetchall()
            class_ids = sorted({int(a["class_id"]) for a in allocations if a["class_id"] is not None})
            subject_ids = sorted({int(a["subject_id"]) for a in allocations if a["subject_id"] is not None})
            if class_ids:
                ph = ",".join("?" for _ in class_ids)
                classes = cur.execute("SELECT * FROM classes WHERE school_id=? AND id IN ("+ph+") ORDER BY name,stream",[sid]+class_ids).fetchall()
            else:
                classes = []
            if subject_ids:
                ph = ",".join("?" for _ in subject_ids)
                subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? AND id IN ("+ph+") ORDER BY name",[sid]+subject_ids).fetchall()
            else:
                subjects = []
        else:
            classes = []
            subjects = []
    else:
        classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
        subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    terms = cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    stat = cur.execute("SELECT COUNT(*) entries,COALESCE(AVG(marks),0) avg_mark FROM marks WHERE school_id=?",(sid,)).fetchone()
    eid = int(exam_id) if exam_id.isdigit() else 0
    cid = int(class_id) if class_id.isdigit() else 0
    subid = int(subject_id) if subject_id.isdigit() else 0
    params=[sid]; query="SELECT COUNT(*) entries,COALESCE(AVG(marks),0) avg_mark,COALESCE(MAX(marks),0) high,COALESCE(MIN(marks),0) low FROM marks WHERE school_id=?"
    if eid: query+=" AND exam_id=?"; params.append(eid)
    if cid: query+=" AND class_id=?"; params.append(cid)
    if subid: query+=" AND subject_id=?"; params.append(subid)
    if term: query+=" AND term=?"; params.append(term.strip())
    if year: query+=" AND year=?"; params.append(year.strip())
    selected=cur.execute(query,params).fetchone(); con.close()
    eopts="".join("<option value='%s' %s>%s</option>"%(e["id"],"selected" if int(e["id"])==eid else "",escape(str(e["name"]))) for e in exams)
    # For teachers these lists are already restricted above to their allocation IDs.
    # Build the dropdowns from those restricted rows only; never render the school's
    # full class/subject catalogue into a teacher's Marks Entry form.
    if role=="teacher":
        allowed_class_ids={int(a["class_id"]) for a in allocations if a["class_id"] is not None}
        allowed_subject_ids={int(a["subject_id"]) for a in allocations if a["subject_id"] is not None}
        teacher_classes=[x for x in classes if int(x["id"]) in allowed_class_ids]
        teacher_subjects=[x for x in subjects if int(x["id"]) in allowed_subject_ids]
        copts="".join("<option value='%s' %s>%s %s</option>"%(c["id"],"selected" if int(c["id"])==cid else "",escape(str(c["name"])),escape(str(c["stream"] or ""))) for c in teacher_classes)
        sopts="".join("<option value='%s' %s>%s</option>"%(s["id"],"selected" if int(s["id"])==subid else "",escape(str(s["name"]))) for s in teacher_subjects)
    else:
        copts="".join("<option value='%s' %s>%s %s</option>"%(c["id"],"selected" if int(c["id"])==cid else "",escape(str(c["name"])),escape(str(c["stream"] or ""))) for c in classes)
        sopts="".join("<option value='%s' %s>%s</option>"%(s["id"],"selected" if int(s["id"])==subid else "",escape(str(s["name"]))) for s in subjects)
    topts="".join("<option %s>%s</option>"%("selected" if x==term else "",x) for x in TERM_OPTIONS)
    yopts="".join("<option value='%s' %s>%s</option>"%(y,"selected" if y==year else "",y) for y in YEAR_OPTIONS)
    actions=[("/app/academics/marks","📝","Marks Entry","Enter and update learner marks"),("/app/academics/marksheets","📋","Class Marksheets","View class marks"),("/app/academics/subject-analysis","📊","Subject Analysis","Analyse subjects"),("/app/academics/student-analysis","👤","Student Analysis","Analyse a learner"),("/app/academics/class-analysis","🏫","Class Analysis","Analyse a class"),("/app/academics/assessments","🧪","SBA / CBA","Continuous assessment"),("/app/academics/grading","🎯","Grade & Points","Set subject grading rules"),("/app/academics/allocations","👩‍🏫","Teacher Allocation","Assign teachers"),("/app/report-cards","📄","Report Cards","Generate reports"),("/app/report-card-settings","📅","Report Card Dates","Set opening & closing dates"),("/app/exams","⚙","Examinations","Manage examinations"),("/app/subjects","📚","Subjects","Manage subjects"),("/app/classes","🏷","Classes & Streams","Manage classes")]
    # Preserve the current isolated browser-tab session when opening an Academic Manager tile.
    # The explicit query parameter prevents the tile navigation from falling back to the
    # generic login session even if the browser-side tab script has not run yet.
    current_ds_tab=str(request.query_params.get("ds_tab") or request.scope.get("davischool_tab_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", current_ds_tab):
        current_ds_tab=""
    action_html="".join("<a class='action' href='%s%s' onclick='window.location.href=this.href; return false;'><span>%s</span>%s<small>%s</small></a>"%(x[0],("?ds_tab="+quote(current_ds_tab,safe="")) if current_ds_tab else "",x[1],x[2],x[3]) for x in actions)
    body="<div class='page'><h1>Academic Management</h1><div class='muted'>Select options below to work with marks, assessments, analysis and reports.</div><div class='grid'><div class='card'><div class='label'>Subjects</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Exams</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Classes</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Marks Average</div><div class='kpi'>%.1f%%</div></div></div>"%(len(subjects),len(exams),len(classes),float(stat["avg_mark"] or 0))
    body+="<div class='card section'><h2>Academic Selection</h2><form method='get' action='/app/academics' class='academic-select'><select name='year' class='field' onchange='this.form.submit()'><option value=''>All Years</option>"+yopts+"</select><select name='term' class='field' onchange='this.form.submit()'><option value=''>All Terms</option>"+topts+"</select><select name='exam_id' class='field' onchange='this.form.submit()'><option value=''>All Exams</option>"+eopts+"</select><select name='class_id' class='field' onchange='this.form.submit()'><option value=''>All Classes</option>"+copts+"</select><select name='subject_id' class='field' onchange='this.form.submit()'><option value=''>All Subjects</option>"+sopts+"</select></form></div><div class='section'><div class='actions'>"+action_html+"</div></div>"
    body+="<div class='card section'><h2>Selected Academic Results</h2><div class='grid' style='margin:0'><div class='card'><div class='label'>Entries</div><div class='kpi'>%d</div></div><div class='card'><div class='label'><b>Average</b></div><div class='kpi'>%.1f%%</div></div><div class='card'><div class='label'>Highest</div><div class='kpi'>%.1f</div></div><div class='card'><div class='label'>Lowest</div><div class='kpi'>%.1f</div></div></div></div></div><style>.deletebtn,[data-action='delete-mark'],button[formaction='/app/academics/marks/delete']{display:none!important}.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff;cursor:pointer}.academic-select{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.action small{display:block;color:#64748b;margin-top:5px}@media(max-width:900px){.academic-select{grid-template-columns:1fr 1fr}}</style>"%(int(selected["entries"] or 0),float(selected["avg_mark"] or 0),float(selected["high"] or 0),float(selected["low"] or 0))
    return _school_page(request,"Academic Management",body)


def _student_result(cur, school_id, student_id, exam_id, grading_rules=None, overall_rules=None):
    """Single source of truth for a student's academic totals."""
    rows=cur.execute("""SELECT sub.id subject_id,sub.name,m.marks
        FROM marks m JOIN subjects sub ON sub.id=m.subject_id
        WHERE m.school_id=? AND m.student_id=? AND m.exam_id=?
        ORDER BY sub.name""",(school_id,student_id,exam_id)).fetchall()
    total=0.0
    points=0.0
    graded=0
    details=[]
    for r in rows:
        if r["marks"] is None or str(r["marks"])=="":
            continue
        mark=float(r["marks"])
        grade,pt=_subject_grade_points(cur,school_id,int(r["subject_id"]),mark,grading_rules)
        total += mark
        points += float(pt or 0)
        graded += 1
        details.append((r,mark,grade,float(pt or 0)))
    average=(total/graded) if graded else 0.0
    overall=_overall_grade(cur,school_id,average,overall_rules) if graded else "—"
    return {"rows":rows,"details":details,"total":total,"points":points,
            "count":graded,"average":average,"overall_grade":overall}

def _student_result_for_assessments(cur, school_id, student_id, exam_ids, grading_rules=None, overall_rules=None):
    """Safe multi-assessment result engine; existing single-assessment engine remains unchanged."""
    ids = _parse_assessment_ids(",".join(str(x) for x in (exam_ids or [])))
    if not ids:
        return {"rows": [], "details": [], "exam_marks": {}, "total": 0.0, "points": 0.0,
                "count": 0, "average": 0.0, "overall_grade": "—"}
    placeholders = ",".join("?" for _ in ids)
    rows = cur.execute(
        "SELECT sub.id subject_id,sub.name,m.exam_id,m.marks FROM marks m "
        "JOIN subjects sub ON sub.id=m.subject_id "
        "WHERE m.school_id=? AND m.student_id=? AND m.exam_id IN (" + placeholders + ") "
        "ORDER BY sub.name,m.exam_id",
        [school_id, student_id] + ids
    ).fetchall()
    buckets = {}
    for row in rows:
        if row["marks"] is None or str(row["marks"]).strip() == "":
            continue
        try:
            subject_id = int(row["subject_id"])
            exam_value = int(row["exam_id"])
            buckets.setdefault(subject_id, {})[exam_value] = float(row["marks"])
        except (TypeError, ValueError):
            continue
    details = []
    exam_marks = {}
    total = points = 0.0
    for subject_id, by_exam in buckets.items():
        values = list(by_exam.values())
        average = sum(values) / len(values)
        source = next(r for r in rows if int(r["subject_id"]) == subject_id)
        grade, pt = _subject_grade_points(cur, school_id, subject_id, average, grading_rules)
        details.append((source, average, grade, float(pt or 0)))
        exam_marks[subject_id] = {exam_id: by_exam[exam_id] for exam_id in ids if exam_id in by_exam}
        total += average
        points += float(pt or 0)
    count = len(details)
    average = total / count if count else 0.0
    overall = _overall_grade(cur, school_id, average, overall_rules) if count else "—"
    return {"rows": rows, "details": details, "exam_marks": exam_marks,
            "total": total, "points": points, "count": count,
            "average": average, "overall_grade": overall}


def _ensure_overall_grading_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS overall_grading_rules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        min_total REAL,
        max_total REAL,
        grade TEXT,
        class_teacher_comment TEXT,
        principal_comment TEXT
    )""")
    for col, definition in [("class_teacher_comment","TEXT"),("principal_comment","TEXT")]:
        try:
            cur.execute("SAVEPOINT davischool_overall_comment_column")
            cur.execute("ALTER TABLE overall_grading_rules ADD COLUMN %s %s" % (col, definition))
            cur.execute("RELEASE SAVEPOINT davischool_overall_comment_column")
        except Exception:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT davischool_overall_comment_column")
                cur.execute("RELEASE SAVEPOINT davischool_overall_comment_column")
            except Exception:
                pass

def _ensure_class_teacher_assignments_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS class_teacher_assignments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        assigned_at TEXT,
        UNIQUE(school_id,class_id)
    )""")

def _report_signatories(cur, school_id, class_id):
    # Assignment storage is optional for compatibility with older databases.
    # If the assignment table cannot be created/read on a legacy database,
    # fall back to the teacher role instead of breaking report-card generation.
    class_teacher = None
    try:
        _ensure_class_teacher_assignments_table(cur)
        class_teacher = cur.execute(
            """SELECT t.id,t.name,t.role FROM class_teacher_assignments a
               JOIN teachers t ON t.id=a.teacher_id
               WHERE a.school_id=? AND a.class_id=? AND t.school_id=?
                 AND COALESCE(t.status,'active')='active' LIMIT 1""",
            (school_id, class_id, school_id)
        ).fetchone()
    except Exception as exc:
        print("DAVISCHOOL CLASS TEACHER ASSIGNMENT FALLBACK:", repr(exc), flush=True)
        try:
            cur.connection.rollback()
        except Exception:
            pass
    if not class_teacher:
        try:
            class_teacher = cur.execute(
                """SELECT id,name,role FROM teachers WHERE school_id=?
                   AND lower(COALESCE(role,'')) IN ('class teacher','class_teacher')
                   AND COALESCE(status,'active')='active' ORDER BY id DESC LIMIT 1""",
                (school_id,)
            ).fetchone()
        except Exception as exc:
            print("DAVISCHOOL TEACHER STATUS FALLBACK:", repr(exc), flush=True)
            try: cur.connection.rollback()
            except Exception: pass
            try:
                class_teacher = cur.execute(
                    """SELECT id,name,role FROM teachers WHERE school_id=?
                       AND lower(COALESCE(role,'')) IN ('class teacher','class_teacher')
                       ORDER BY id DESC LIMIT 1""",
                    (school_id,)
                ).fetchone()
            except Exception:
                class_teacher = None
    # The Principal shown on report cards is the school administrator.
    # This keeps the report card synchronized with the school admin account
    # instead of requiring a separate Principal teacher profile.
    principal = cur.execute(
        """SELECT id,full_name,email FROM users
           WHERE school_id=? AND role='school_admin'
             AND TRIM(COALESCE(full_name,''))<>''
           ORDER BY id DESC LIMIT 1""",
        (school_id,)
    ).fetchone()
    if principal:
        principal_name = str(principal["full_name"] or "").strip()
    else:
        # Compatibility fallback for older schools whose admin account has
        # no full_name yet: use the most recent school-admin email.
        principal = cur.execute(
            """SELECT id,full_name,email FROM users
               WHERE school_id=? AND role='school_admin'
               ORDER BY id DESC LIMIT 1""",
            (school_id,)
        ).fetchone()
        principal_name = str((principal["full_name"] if principal else "") or (principal["email"] if principal else "")).strip()
    return (str(class_teacher["name"] or "") if class_teacher else "",
            principal_name)

def _load_overall_grading_rules(cur, school_id):
    try:
        _ensure_overall_grading_table(cur)
        return cur.execute(
            "SELECT min_total,max_total,grade FROM overall_grading_rules WHERE school_id=? ORDER BY min_total DESC,id DESC",
            (school_id,)
        ).fetchall()
    except Exception as exc:
        print("DAVISCHOOL OVERALL RULES LOAD FALLBACK:", repr(exc), flush=True)
        try:
            cur.connection.rollback()
        except Exception:
            try:
                cur._connection.rollback()
            except Exception:
                pass
        return []

def _overall_grade(cur, school_id, average_percentage, overall_rules=None):
    """Return the school's configured overall grade only.
    Never silently substitute the subject/default grading scale for an overall grade.
    """
    try:
        rules = overall_rules
        if rules is None:
            _ensure_overall_grading_table(cur)
            rules = cur.execute(
                "SELECT min_total,max_total,grade FROM overall_grading_rules "
                "WHERE school_id=? ORDER BY min_total DESC,id DESC",
                (school_id,)
            ).fetchall()
        valid_rules = []
        for rule in (rules or []):
            try:
                valid_rules.append((float(rule["min_total"]), float(rule["max_total"]), str(rule["grade"])))
            except (TypeError, ValueError, KeyError):
                continue
        if not valid_rules:
            return "—"
        average = float(average_percentage)
        # First honor an explicitly configured range.
        for minimum, maximum, grade in sorted(valid_rules, key=lambda x: (x[0], x[1]), reverse=True):
            if minimum <= average <= maximum:
                return grade
        # If the school entered whole-number boundaries (e.g. 70-79 and 80-100),
        # decimal averages such as 79.5 can fall into the tiny gap between bands.
        # In that case use the configured band's lower boundary rather than
        # reverting to the unrelated default D/E grading scale.
        lower_rules = [r for r in valid_rules if r[0] <= average]
        if lower_rules:
            return max(lower_rules, key=lambda x: x[0])[2]
        # Below the lowest configured band: use the school's lowest configured grade
        # rather than inventing a grade from the default scale.
        return min(valid_rules, key=lambda x: x[0])[2]
    except Exception as exc:
        print("DAVISCHOOL OVERALL GRADING ERROR:", repr(exc), flush=True)
        return "—"

@router.get("/app/academics/overall-grading", response_class=HTMLResponse)
def overall_grading(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can manage overall grading.", 403)
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view overall grading.", 403)
    con=_db();cur=con.cursor()
    try:
        _ensure_overall_grading_table(cur)
        rules=cur.execute("SELECT * FROM overall_grading_rules WHERE school_id=? ORDER BY min_total DESC,max_total DESC",(sid,)).fetchall()
    except Exception as exc:
        print("DAVISCHOOL OVERALL GRADING PAGE FALLBACK:", repr(exc), flush=True)
        rules=[]
    con.close()
    rows="".join("<tr><td>%.1f</td><td>%.1f</td><td><b>%s</b></td><td><form method='post' action='/app/academics/overall-grading/delete/%s' style='display:inline'><button class='btnlink' type='submit' onclick='return confirm(\"Delete this overall grading rule?\")'>Delete</button></form></td></tr>"%(float(r["min_total"]),float(r["max_total"]),escape(str(r["grade"])),r["id"]) for r in rules)
    body=("<div class='page'><h1>Overall Grade & Position Settings</h1>"
      "<div class='muted'>Set the average-percentage bands your school uses for the final overall grade. The overall grade is based on the learner's average percentage across entered subjects. Position is calculated automatically from total marks within the selected class and stream.</div>"
      "<div class='card section'><h2>Add overall grade band</h2><form method='post' action='/app/academics/overall-grading/add' style='display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px'>"
      "<input name='min_total' type='number' min='0' max='100' step='0.01' required placeholder='Minimum average %' class='field'>"
      "<input name='max_total' type='number' min='0' max='100' step='0.01' required placeholder='Maximum average %' class='field'>"
      "<input name='grade' required placeholder='Overall grade e.g. A' class='field'><button class='btn'>Save</button></form></div>"
      "<div class='card section'><h2>Report Card Comments by Overall Grade</h2><div class='muted'>Set the class teacher and principal comment that will automatically appear on report cards for each overall grade.</div>"
      "<table><thead><tr><th>Grade</th><th>Class Teacher Comment</th><th>Principal Comment</th><th>Action</th></tr></thead><tbody>"
      + "".join("<tr><td><b>%s</b></td><td colspan='2'><form method='post' action='/app/report-cards/overall-grade-comments'><input type='hidden' name='rule_id' value='%s'><input name='class_teacher_comment' value='%s' class='field' placeholder='Class teacher comment'><input name='principal_comment' value='%s' class='field' style='margin-top:6px' placeholder='Principal comment'><button class='btn' style='margin-top:6px'>Save Comments</button></form></td><td></td></tr>" %
          (escape(str(r["grade"])),r["id"],escape(str(r["class_teacher_comment"] or "")),escape(str(r["principal_comment"] or ""))) for r in rules)
      + ("<tr><td colspan='4'>No overall grading bands configured yet.</td></tr>" if not rules else "")
      + "</tbody></table></div>"
      + "<div class='card section'><table><thead><tr><th>Minimum Average %</th><th>Maximum Average %</th><th>Overall Grade</th><th>Action</th></tr></thead><tbody>"+(rows or "<tr><td colspan='4'>No overall grading bands configured.</td></tr>")+"</tbody></table></div>"
      "<div class='card section'><b>Overall grade:</b> Based on average percentage. <b>Position:</b> ranked automatically by total marks, highest total first; equal totals receive the same position.</div>"
      "<style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;box-sizing:border-box}.marks-table{width:100%%;table-layout:fixed;border-collapse:collapse}.marks-table th,.marks-table td{vertical-align:middle;text-align:left;padding:8px 7px;box-sizing:border-box}.marks-table th{white-space:nowrap}.marks-table .col-admission{width:12%%}.marks-table .col-student{width:22%%}.marks-table .col-mark{width:12%%}.marks-table .col-grade{width:10%%}.marks-table .col-points{width:10%%}.marks-table .col-comment{width:34%%}.marks-table td:nth-child(1),.marks-table td:nth-child(2),.marks-table td:nth-child(4),.marks-table td:nth-child(5){white-space:nowrap}.markcell,.gradecell,.pointcell,.commentcell{height:1px}.markinput{width:100%%;max-width:110px;padding:8px;border:1px solid #dbe2ea;border-radius:8px;box-sizing:border-box}.commentinput{display:block;flex:0 1 210px;width:210px;max-width:210px;min-width:0;box-sizing:border-box}.comment-wrap{display:flex;align-items:center;gap:6px;min-width:0}.editbtn{flex:0 0 auto;padding:6px 8px;border:0;border-radius:7px;background:#111827;color:#fff;font-weight:800;cursor:pointer;white-space:nowrap}.btn{padding:8px 11px;border:0;border-radius:8px;background:#111827;color:#fff;font-weight:800;cursor:pointer;margin-right:5px}</style></div>")
    return _school_page(request,"Overall Grade & Position Settings",body)

@router.post("/app/academics/overall-grading/add")
def overall_grading_add(request: Request,min_total:float=Form(...),max_total:float=Form(...),grade:str=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can edit overall grading.", 403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit overall grading.", 403)
    if min_total<0 or max_total>100 or max_total<min_total or not grade.strip():
        return HTMLResponse("Invalid average-percentage range or grade. <a href='/app/academics/overall-grading'>Back</a>",400)
    con=_db();cur=con.cursor();_ensure_overall_grading_table(cur)
    overlap=cur.execute(
        """SELECT id FROM overall_grading_rules
           WHERE school_id=? AND min_total<=? AND max_total>=? LIMIT 1""",
        (sid,max_total,min_total)
    ).fetchone()
    if overlap:
        con.close()
        return HTMLResponse("That overall grading range overlaps an existing range. <a href='/app/academics/overall-grading'>Back</a>",400)
    cur.execute("INSERT INTO overall_grading_rules(school_id,min_total,max_total,grade) VALUES(?,?,?,?)",(sid,min_total,max_total,grade.strip()))
    _audit(cur,sid,request,"OVERALL_GRADING_RULE_CREATE","Configured overall grade %s for %.1f-%.1f%% average"%(grade.strip(),min_total,max_total))
    con.commit();con.close()
    return RedirectResponse("/app/academics/overall-grading",303)

@router.post("/app/academics/overall-grading/delete/{rule_id}")
def overall_grading_delete(request: Request,rule_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can edit overall grading.", 403)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to edit overall grading.", 403)
    con=_db();cur=con.cursor();_ensure_overall_grading_table(cur)
    cur.execute("DELETE FROM overall_grading_rules WHERE id=? AND school_id=?",(rule_id,sid))
    con.commit();con.close()
    return RedirectResponse("/app/academics/overall-grading",303)



# MarkSheet-only subject order. Subjects not listed here remain after the
# requested curriculum subjects, preserving their existing alphabetical order.
def _parse_exam_ids(exam_ids="", exam_id=""):
    raw = exam_ids or exam_id or ""
    out = []
    for part in str(raw).split(","):
        try:
            value = int(part.strip())
            if value > 0 and value not in out:
                out.append(value)
        except (TypeError, ValueError):
            pass
    return out

def _aggregate_marks_for_students(cur, sid, student_ids, exam_ids, term="", year=""):
    """Safely aggregate marks for MarkSheet display without allowing an optional
    filter-column/schema mismatch to prevent the entire MarkSheet from loading."""
    if not student_ids or not exam_ids:
        return {}
    sp = ",".join("?" for _ in student_ids)
    ep = ",".join("?" for _ in exam_ids)
    base_q = "SELECT student_id,subject_id,marks FROM marks WHERE school_id=? AND student_id IN ("+sp+") AND exam_id IN ("+ep+")"
    base_params = [sid] + list(student_ids) + list(exam_ids)

    rows = None
    try:
        q = base_q
        params = list(base_params)
        if term:
            q += " AND term=?"; params.append(term)
        if year:
            q += " AND year=?"; params.append(year)
        rows = cur.execute(q, params).fetchall()
    except Exception as exc:
        print("DAVISCHOOL MARKSHEET AGGREGATE FILTER FALLBACK:", repr(exc), flush=True)
        try:
            rows = cur.execute(base_q, base_params).fetchall()
        except Exception as fallback_exc:
            print("DAVISCHOOL MARKSHEET AGGREGATE QUERY FAILED:", repr(fallback_exc), flush=True)
            return {}

    buckets = {}
    for r in rows:
        if r["marks"] is None or str(r["marks"]).strip()=="":
            continue
        try:
            buckets.setdefault((int(r["student_id"]),int(r["subject_id"])), []).append(float(r["marks"]))
        except (TypeError, ValueError, KeyError):
            continue
    return {k: sum(v)/len(v) for k,v in buckets.items() if v}

MARKSHEET_SUBJECT_ORDER = (
    "English",
    "Kiswahili",
    "Mathematics",
    "Integrated Science",
    "Agriculture",
    "Creative Arts and Sports",
    "Social Studies",
    "Christian Religious Education",
    "Pre-technical Studies",
)

def _subject_marksheet_label(subject):
    """Return the subject initial/code for MarkSheet headings, with a safe name fallback."""
    try:
        initial = str(subject["initial"] or "").strip()
    except Exception:
        initial = ""
    label = initial or str(subject["name"] or "").strip()
    # Pre-technical Studies is displayed as PRET on both electronic and blank MarkSheets.
    if label.upper() == "PRE" or "pre-technical" in str(subject["name"] or "").strip().lower():
        return "PRET"
    return label

def _marksheet_subject_order(subjects):
    # Fixed MarkSheet curriculum order. Only the MarkSheet display order is
    # changed; database subject records and marks remain untouched.
    def normalize(value):
        value = str(value or "").strip().casefold()
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())

    def subject_position(value):
        name = normalize(value)
        tokens = set(name.split())

        if "english" in tokens:
            return 1
        if "kiswahili" in tokens:
            return 2
        if "mathematics" in tokens or "math" in tokens:
            return 3
        # Treat all Integrated Science/Science naming variants as the
        # Science slot. Agriculture-related names are excluded so a subject
        # such as Agriculture Science cannot accidentally take this position.
        if "science" in tokens and "agriculture" not in tokens:
            return 4
        if "agriculture" in tokens:
            return 5
        if "creative" in tokens and "arts" in tokens and "sport" in tokens:
            return 6
        if "social" in tokens and "studies" in tokens:
            return 7
        # Accept both the full stored name and the common CRE abbreviation.
        if (
            name == "cre"
            or "christian religious education" in name
            or ("christian" in tokens and "religious" in tokens and "education" in tokens)
        ):
            return 8
        if "pre" in tokens and "technical" in tokens:
            return 9

        # Subjects outside the requested curriculum remain after the nine
        # specified subjects, preserving their original relative order.
        return 100

    return sorted(
        list(subjects),
        key=lambda subject: (
            subject_position(subject["name"]),
            0 if subject_position(subject["name"]) < 100 else 1,
            normalize(subject["name"]) if subject_position(subject["name"]) == 100 else "",
        ),
    )

@router.get("/app/academics/marksheets", response_class=HTMLResponse)
def class_marksheets(request: Request, exam_id: str = "", exam_ids: str = "", class_id: str = "", term: str = "", year: str = "", stream: str = "", page: int = 1, subject_ids: str = "", subject_metrics: str = "", overall_metrics: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view marksheets.", 403)
    con = _db()
    cur = con.cursor()
    try: grading_rules = _load_grading_rules(cur, sid)
    except Exception as exc:
        print("DAVISCHOOL MARKSHEET GRADING RULES FALLBACK:", repr(exc), flush=True); grading_rules=[]
    try: overall_rules = _load_overall_grading_rules(cur, sid)
    except Exception as exc:
        print("DAVISCHOOL MARKSHEET OVERALL RULES FALLBACK:", repr(exc), flush=True); overall_rules=[]
    # Grading-table compatibility helpers can rollback PostgreSQL transactions.
    # Start the actual MarkSheet read/render work on a completely fresh
    # connection so no aborted transaction or invalid cursor can leak into it.
    try:
        con.close()
    except Exception:
        pass
    con = _db()
    cur = con.cursor()
    try:
        exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (sid,)).fetchall()
        classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
        try:
            overall_rules = _load_overall_grading_rules(cur, sid)
        except Exception as exc:
            print("DAVISCHOOL MARKSHEET PDF OVERALL RULES ERROR:", repr(exc), flush=True)
            overall_rules = []
        subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
        subjects = _marksheet_subject_order(subjects)
        # Keep the full exam subject count before any display-only subject
        # filtering. Full-exam eligibility must always use the complete exam.
        full_exam_subject_count = len(subjects)
        selected_subject_ids = []
        for raw_id in str(subject_ids or "").split(","):
            try:
                if raw_id.strip():
                    selected_subject_ids.append(int(raw_id.strip()))
            except ValueError:
                pass
        if selected_subject_ids:
            selected_set = set(selected_subject_ids)
            subjects = [s for s in subjects if int(s["id"]) in selected_set]
        subject_metric_map = {}
        for part in str(subject_metrics or "").split(","):
            if ":" not in part:
                continue
            raw_id, raw_metrics = part.split(":", 1)
            try:
                subject_metric_map[int(raw_id)] = [m for m in raw_metrics.split(".") if m in ("mks", "grade", "pts")]
            except (TypeError, ValueError):
                pass
        for subject in subjects:
            subject_metric_map.setdefault(int(subject["id"]), ["mks", "grade", "pts"])
        overall_metric_list = [m for m in str(overall_metrics or "").split(",") if m in ("mks", "pts", "avg", "grade", "pos")]
        if not overall_metric_list:
            overall_metric_list = ["mks", "pts", "avg", "grade", "pos"]
    except Exception as exc:
        print("DAVISCHOOL MARKSHEET ACADEMIC LOOKUP FAILED:", repr(exc), flush=True)
        try:
            con.rollback()
        except Exception:
            pass
        try:
            cur = con.cursor()
        except Exception:
            con.close()
            con = _db()
            cur = con.cursor()
        exams = []
        classes = []
        subjects = []
    selected_exam_ids = _parse_exam_ids(exam_ids, exam_id)
    if not selected_exam_ids and exams: selected_exam_ids=[int(exams[0]["id"])]
    eid = selected_exam_ids[0] if selected_exam_ids else 0
    class_stream_by_id = {int(c["id"]): str(c["stream"] or "") for c in classes}

    # A class can be printed either as one stream or as a combined grade.
    # Combined mode uses class_id=grade:<class name>, e.g. grade:Grade 9.
    combined_mode = class_id.startswith("grade:")
    combined_grade = class_id[6:] if combined_mode else ""
    def _grade_group_key(row):
        name = str(row["name"] or "").strip()
        stream_value = str(row["stream"] or "").strip()
        if stream_value:
            return name
        match = re.match(r"^(.*?\d)\s*[A-Za-z]$", name)
        return match.group(1).strip() if match else name
    selected_class_ids = []
    if combined_mode:
        selected_class_ids = [
            int(c["id"]) for c in classes
            if _grade_group_key(c).strip().lower() == combined_grade.strip().lower()
        ]
        stream = ""
        cid = selected_class_ids[0] if selected_class_ids else 0
    else:
        cid = int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
        selected_class_ids = [cid] if cid else []

    try:
        class_row = cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?", (cid, sid)).fetchone() if cid else None
        er = cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?", (eid, sid)).fetchone() if eid else None
    except Exception as exc:
        print("DAVISCHOOL MARKSHEET CONTEXT LOOKUP FAILED:", repr(exc), flush=True)
        try:
            con.close()
        except Exception:
            pass
        con = _db()
        cur = con.cursor()
        class_row = cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?", (cid, sid)).fetchone() if cid else None
        er = cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?", (eid, sid)).fetchone() if eid else None
    if er:
        if not term:
            term = str(er["term"] or "")
        if not year:
            year = str(er["year"] or "")
    if selected_class_ids:
        class_marks_placeholders = ",".join("?" for _ in selected_class_ids)
        student_query = "SELECT * FROM students WHERE school_id=? AND class_id IN (" + class_marks_placeholders + ")"
        student_params = [sid] + selected_class_ids
    else:
        student_query = "SELECT * FROM students WHERE school_id=? AND class_id=?"
        student_params = [sid, cid]
    if stream and not combined_mode:
        student_query += " AND stream=?"
        student_params.append(stream)
    student_query += " ORDER BY name"
    try:
        students = cur.execute(student_query, student_params).fetchall() if cid else []
    except Exception as exc:
        print("DAVISCHOOL MARKSHEET STUDENT QUERY FAILED:", repr(exc), flush=True)
        try:
            con.rollback()
        except Exception:
            pass
        try:
            cur = con.cursor()
        except Exception:
            con.close()
            con = _db()
            cur = con.cursor()
        students = []
    mark_rows = []
    if eid and students:
        # Filter marks by the actual students selected above. This is important
        # when a stream is selected: subject means/distributions must not include
        # marks from the other streams in the same grade.
        student_ids_for_marks = [int(st["id"]) for st in students]
        student_marks_placeholders = ",".join("?" for _ in student_ids_for_marks)
        mark_query = "SELECT student_id,subject_id,marks FROM marks WHERE school_id=? AND exam_id=? AND student_id IN (" + student_marks_placeholders + ")"
        mark_params = [sid, eid] + student_ids_for_marks
        if term:
            mark_query += " AND term=?"
            mark_params.append(term)
        if year:
            mark_query += " AND year=?"
            mark_params.append(year)
        try:
            mark_rows = cur.execute(mark_query, mark_params).fetchall()
        except Exception as exc:
            # Older production databases may temporarily lack one of the
            # optional filtering columns. Never let that prevent the
            # marksheet from loading the students and their marks.
            print("DAVISCHOOL MARKSHEET MARK QUERY FALLBACK:", repr(exc), flush=True)
            try:
                con.rollback()
            except Exception:
                pass
            try:
                cur = con.cursor()
            except Exception:
                con.close()
                con = _db()
                cur = con.cursor()
            try:
                fallback_rows = cur.execute(
                    "SELECT student_id,subject_id,marks FROM marks WHERE school_id=? AND exam_id=?",
                    (sid, eid)
                ).fetchall()
                allowed_students = {int(st["id"]) for st in students}
                mark_rows = [r for r in fallback_rows if int(r["student_id"]) in allowed_students]
            except Exception as fallback_exc:
                print("DAVISCHOOL MARKSHEET MARK FALLBACK FAILED:", repr(fallback_exc), flush=True)
                mark_rows = []
    marks = _aggregate_marks_for_students(cur, sid, [int(st["id"]) for st in students], selected_exam_ids, term, year)
    # Stream choices must belong to the currently selected class/grade.
    # Keeping this scoped prevents a stream from another class from producing
    # an invalid/empty MarkSheet request.
    if combined_mode:
        streams = sorted(set(
            str(c["stream"] or "") for c in classes
            if int(c["id"]) in set(selected_class_ids) and str(c["stream"] or "")
        ))
    elif cid:
        streams = sorted(set(
            str(st["stream"] or "") for st in classes
            if int(st["id"]) == cid and str(st["stream"] or "")
        ))
        # Some installations store the stream on the student rather than the
        # class record. Fall back to the selected class's students.
        if not streams:
            try:
                stream_rows = cur.execute(
                    "SELECT DISTINCT stream FROM students WHERE school_id=? AND class_id=? AND stream IS NOT NULL AND stream<>? ORDER BY stream",
                    (sid, cid, "")
                ).fetchall()
                streams = sorted(set(str(row["stream"] or "") for row in stream_rows if str(row["stream"] or "").strip()))
            except Exception as exc:
                print("DAVISCHOOL MARKSHEET STREAM LOOKUP FALLBACK:", repr(exc), flush=True)
                streams = []
    else:
        streams = []

    eopts = "".join("<option value='%s' %s>%s</option>" % (e["id"], "selected" if int(e["id"]) in selected_exam_ids else "", escape(str(e["name"]))) for e in exams)
    # Offer a combined option for every grade/class name represented by
    # multiple stream records, while retaining each individual stream.
    grade_groups = {}
    for c in classes:
        grade_key = _grade_group_key(c)
        if grade_key:
            grade_groups.setdefault(grade_key.lower(), {"name": grade_key, "ids": []})
            grade_groups[grade_key.lower()]["ids"].append(int(c["id"]))
    combined_options = []
    for group in sorted(grade_groups.values(), key=lambda x: x["name"].lower()):
        if len(group["ids"]) >= 2:
            selected = combined_mode and group["name"].strip().lower() == combined_grade.strip().lower()
            combined_options.append(
                "<option value='grade:%s' %s>%s — All Streams</option>" % (
                    escape(group["name"]),
                    "selected" if selected else "",
                    escape(group["name"])
                )
            )
    copts = "".join(combined_options) + "".join("<option value='%s' %s>%s %s</option>" % (
        c["id"], "selected" if (not combined_mode and int(c["id"]) == cid) else "",
        escape(str(c["name"])), escape(str(c["stream"] or ""))
    ) for c in classes)
    stropts = "".join("<option value='%s' %s>%s</option>" % (
        escape(x), "selected" if x == stream else "", escape(x)
    ) for x in streams)
    topts = "".join("<option %s>%s</option>" % (
        "selected" if x == term else "", x
    ) for x in TERM_OPTIONS)
    yopts = "".join("<option value='%s' %s>%s</option>" % (
        y, "selected" if y == year else "", y
    ) for y in YEAR_OPTIONS)

    header_cells = ""
    sub_header_cells = ""
    subject_colgroup = ""
    metric_labels = {"mks": "MKS", "grade": "GRD", "pts": "PTS"}
    metric_classes = {"mks": "mks-col", "grade": "grade-col", "pts": "points-col"}
    for subject in subjects:
        metrics = subject_metric_map.get(int(subject["id"]), ["mks", "grade", "pts"])
        header_cells += "<th colspan='%d' class='subjecthead'>%s</th>" % (len(metrics), escape(_subject_marksheet_label(subject)))
        for metric in metrics:
            sub_header_cells += "<th class='%s-head'>%s</th>" % (metric, metric_labels[metric])
            subject_colgroup += "<col class='%s'>" % metric_classes[metric]

    # Calculate subject means from the marks query itself (one pass only).
    # This avoids an extra student x subject loop and keeps the MarkSheet fast.
    mean_totals={}
    mean_counts={}
    for row in mark_rows:
        try:
            value=row["marks"]
            if value is None or str(value).strip()=="":
                continue
            subject_id=int(row["subject_id"])
            mean_totals[subject_id]=mean_totals.get(subject_id,0.0)+float(value)
            mean_counts[subject_id]=mean_counts.get(subject_id,0)+1
        except (TypeError,ValueError,KeyError):
            continue
    subject_means=[]
    for subject in subjects:
        subject_id=int(subject["id"])
        count_mean=mean_counts.get(subject_id,0)
        mean=(mean_totals.get(subject_id,0.0)/count_mean) if count_mean else None
        subject_means.append((subject,mean,count_mean))

    # Rank subjects against one another using their mean mark. Ties share a position.
    subject_mean_sorted = sorted(
        [x for x in subject_means if x[1] is not None],
        key=lambda x: (-float(x[1]), str(x[0]["name"]).lower())
    )
    subject_positions = {}
    last_mean = None
    last_subject_position = 0
    for idx, item in enumerate(subject_mean_sorted, 1):
        mean_value = float(item[1])
        if last_mean is None or mean_value != last_mean:
            last_subject_position = idx
            last_mean = mean_value
        subject_positions[int(item[0]["id"])] = last_subject_position

    computed=[]
    for student in students:
        total=0.0
        total_points=0.0
        count=0
        cells=""
        for subject in subjects:
            value=marks.get((int(student["id"]),int(subject["id"])))
            metrics = subject_metric_map.get(int(subject["id"]), ["mks", "grade", "pts"])
            if value is None:
                cells += "".join("<td>—</td>" for _ in metrics)
            else:
                try:
                    grade,points,_=_subject_grade_details(cur,sid,int(subject["id"]),value,grading_rules)
                except Exception as exc:
                    print("DAVISCHOOL MARKSHEET GRADE FALLBACK:", repr(exc), flush=True)
                    grade,points=_default_grade_points(float(value))
                    _ = ""
                total+=float(value or 0)
                total_points+=float(points or 0)
                count+=1
                metric_html = {
                    "mks": "<td class='mks-cell'>%.1f</td>" % float(value),
                    "grade": "<td class='grade-cell'><b>%s</b></td>" % escape(str(grade)),
                    "pts": "<td class='points-cell'>%.1f</td>" % float(points),
                }
                cells += "".join(metric_html[m] for m in metrics)
        computed.append((student,total,total_points,count,cells))
    computed.sort(key=lambda x:x[1],reverse=True)
    page_size=30
    total_students=len(computed)
    total_pages=max(1,(total_students+page_size-1)//page_size)
    page=max(1,min(int(page or 1),total_pages))
    page_students=set(id(x) for x in computed[(page-1)*page_size:page*page_size])

    rows=""
    all_rows=""
    last_total=None
    last_position=0
    for index,item in enumerate(computed,1):
        student,total,total_points,count,cells=item
        if last_total is None or total != last_total:
            last_position=index
            last_total=total
        try:
            average=(total/count) if count else 0
            overall_grade=_overall_grade(cur,sid,average,overall_rules) if count else "—"
        except Exception as exc:
            print("DAVISCHOOL MARKSHEET OVERALL GRADE FALLBACK:", repr(exc), flush=True)
            overall_grade=_default_grade_points(average)[0] if count else "—"
        average=(total/count) if count else 0
        student_stream = str(student["stream"] or "").strip() or class_stream_by_id.get(int(student["class_id"] or 0), "")
        stream_cell = "<td class='stream-cell'><b>%s</b></td>" % escape(student_stream) if combined_mode else ""
        overall_cells = "".join({
            "mks": "<td class='overall-marks-col'><b>%.1f</b></td>" % total,
            "pts": "<td class='overall-points-col'><b>%.1f</b></td>" % total_points,
            "avg": "<td class='overall-avg-col'><b>%.1f%%</b></td>" % average,
            "grade": "<td class='overall-grade-col'><b>%s</b></td>" % escape(str(overall_grade)),
            "pos": "<td class='overall-pos-col'><b>%d</b></td>" % last_position,
        }[m] for m in overall_metric_list)
        row_html = (
            "<tr><td class='adm-no-cell'>%s</td><td class='name-cell'><b>%s</b></td>%s%s%s</tr>"
            % (
                escape(str(student["admission_no"] or "")),
                escape(str(student["name"] or "")),
                stream_cell,
                cells,
                overall_cells,
            )
        )
        all_rows += row_html
        if id(item) in page_students:
            rows += row_html

    try:
        school_row = cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    except Exception as exc:
        print("DAVISCHOOL MARKSHEET SCHOOL LOOKUP FAILED:", repr(exc), flush=True)
        try:
            con.close()
        except Exception:
            pass
        con = _db()
        cur = con.cursor()
        school_row = cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    school_name = escape(str(school_row["name"])) if school_row else "DaviSchool"
    school_email = escape(str(school_row["email"] or "")) if school_row else ""
    school_phone = escape(str(school_row["phone"] or "")) if school_row else ""
    school_postal = escape("P.O. Box %s" % str(school_row["postal_address"] or "")) if school_row and "postal_address" in school_row.keys() and school_row["postal_address"] else ""
    school_postal_code = escape(str(school_row["postal_code"] or "")) if school_row and "postal_code" in school_row.keys() else ""
    school_logo = str(school_row["logo_data"] or "") if school_row and "logo_data" in school_row.keys() else ""
    doc_contact_lines = "".join("<div>%s</div>" % x for x in [school_postal, school_postal_code] if x)
    doc_right_lines = "".join("<div>%s</div>" % x for x in [("☎ "+school_phone) if school_phone else "", ("✉ "+school_email) if school_email else ""] if x)
    doc_brand = "<div class='doc-header'><div class='doc-logo'>%s</div><div class='doc-school-block'><div class='doc-school'>%s</div><div class='doc-contact'>%s</div></div><div class='doc-right'>%s</div></div>" % (("<img src='%s' alt='School logo'>" % escape(school_logo)) if school_logo else "🏫",school_name,doc_contact_lines,doc_right_lines)
    if combined_mode and combined_grade:
        class_title = escape(str(combined_grade)) + " — ALL STREAMS"
    elif class_row:
        class_title = escape(str(class_row["name"]))
        selected_stream = str(stream or class_row["stream"] or "").strip()
        class_title += " — STREAM: " + escape(selected_stream) if selected_stream else " — ALL STREAMS"
    else:
        class_title = "Select a class"
    exam_name = escape(" + ".join(str(e["name"]) for e in exams if int(e["id"]) in selected_exam_ids)) if selected_exam_ids else "Select examinations"
    stream_col_html = "<th rowspan='2'>STREAM</th>" if combined_mode else ""
    stream_colgroup_html = "<col class='stream-col'>" if combined_mode else ""
    colspan = (3 if combined_mode else 2) + sum(len(subject_metric_map.get(int(s["id"]), ["mks", "grade", "pts"])) for s in subjects) + len(overall_metric_list)
    selected_class_param = quote(str(class_id), safe='') if class_id else quote(str(cid), safe='')
    marksheet_tab_id = str(request.query_params.get("ds_tab") or request.scope.get("davischool_tab_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", marksheet_tab_id):
        marksheet_tab_id = ""
    marksheet_tab_q = ("&ds_tab=" + quote(marksheet_tab_id, safe="")) if marksheet_tab_id else ""
    pdf_marksheet_url = f"<a class='btnlink' href='/app/academics/marksheets/pdf?exam_id={eid}&class_id={selected_class_param}&term={quote(str(term or ''), safe='')}&year={quote(str(year or ''), safe='')}&stream={quote(str(stream or ''), safe='')}&subject_ids={quote(','.join(str(x) for x in selected_subject_ids), safe='')}&subject_metrics={quote(subject_metrics or '', safe='')}&overall_metrics={quote(','.join(overall_metric_list), safe='')}{marksheet_tab_q}'>⬇️ Download PDF</a>"
    marksheet_page_query = (
        f"exam_id={quote(str(eid), safe='')}"
        f"&class_id={selected_class_param}"
        f"&term={quote(str(term or ''), safe='')}"
        f"&year={quote(str(year or ''), safe='')}"
        f"&stream={quote(str(stream or ''), safe='')}"
        f"&subject_ids={quote(','.join(str(x) for x in selected_subject_ids), safe='')}"
        f"&subject_metrics={quote(subject_metrics or '', safe='')}"
        f"&overall_metrics={quote(','.join(overall_metric_list), safe='')}"
    )
    prev_page = max(1, page - 1)
    next_page = min(total_pages, page + 1)
    prev_disabled = "opacity:.45;pointer-events:none" if page <= 1 else ""
    next_disabled = "opacity:.45;pointer-events:none" if page >= total_pages else ""
    marksheet_pagination = (
        "<div class='marksheet-pagination no-print'>"
        f"<a class='btnlink' style='{prev_disabled}' href='/app/academics/marksheets?page={prev_page}&{marksheet_page_query}{marksheet_tab_q}'>← Previous</a>"
        f"<span class='marksheet-page-info'>Page {page} of {total_pages} · {total_students} students</span>"
        f"<a class='btnlink' style='{next_disabled}' href='/app/academics/marksheets?page={next_page}&{marksheet_page_query}{marksheet_tab_q}'>Next →</a>"
        "</div>"
    )

    print_script = '''<script>
function printDocument(){
  var doc=document.querySelector('.marksheet-card');
  if(!doc){window.print();return;}
  var allRows=document.getElementById('marksheet-all-rows');
  var printDoc=doc.cloneNode(true);
  if(allRows){
    var printBody=printDoc.querySelector('.marksheet tbody');
    if(printBody){printBody.innerHTML=allRows.innerHTML;}
  }
  printDoc.querySelectorAll('.marksheet-pagination').forEach(function(el){el.remove();});
  var w=window.open('', '_blank', 'width=1200,height=800');
  if(!w){window.print();return;}
  var generatedAt=new Intl.DateTimeFormat('en-KE',{
    timeZone:'Africa/Nairobi',year:'numeric',month:'2-digit',day:'2-digit',
    hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false
  }).format(new Date())+' EAT';
  var css='*{box-sizing:border-box}body{margin:0;background:#fff;color:#172033;font-family:Arial,sans-serif}.marksheet-card{display:block!important;width:100%!important;margin:0!important;padding:0!important;border:0!important;box-shadow:none!important}.no-print{display:none!important}.doc-header{display:flex;align-items:flex-start;gap:14px;border-top:2px solid #2E8B57;border-bottom:3px solid #176B3A;padding:8px 4px 10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center;flex:0 0 86px}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school-block{flex:1;min-width:0}.doc-school{font-size:20px;line-height:1.15;font-weight:900;text-transform:uppercase;color:#176B3A}.doc-contact{font-size:10px;color:#334155;margin-top:5px;line-height:1.55}.doc-contact div{display:block;margin:1px 0}.doc-right{font-size:10px;color:#176B3A;line-height:1.65;text-align:left;min-width:155px}.doc-right div{display:block;margin:1px 0}.marksheet-school{display:none!important}.marksheet-meta{font-size:14px;font-weight:800;padding:8px 4px;border-top:1px solid #176B3A;border-bottom:1px solid #176B3A}.marksheet{border-collapse:collapse;width:max-content;min-width:100%;font-family:Arial,sans-serif;table-layout:auto}.marksheet th,.marksheet td{border:1.25px solid #176B3A;padding:5px 6px;text-align:center;font-size:10px;white-space:nowrap}.marksheet th{background:#fff!important;color:#000!important;font-weight:900}.marksheet thead tr:nth-child(2) th{background:#fff!important;color:#000!important;font-weight:900}.marksheet tbody td{border-top:1px solid #176B3A;border-bottom:1px solid #176B3A}.marksheet .adm-no-col{width:58px;min-width:58px;max-width:58px}.marksheet .name-col{width:170px;min-width:170px;max-width:170px}.marksheet .stream-col,.marksheet .stream-cell{width:55px;min-width:55px;max-width:55px}.marksheet .mks-col,.marksheet .points-col{width:48px;min-width:48px;max-width:48px}.marksheet .grade-col{width:44px;min-width:44px;max-width:44px}.marksheet .overall-marks-col{width:58px;min-width:58px;max-width:58px}.marksheet .overall-points-col{width:58px;min-width:58px;max-width:58px}.marksheet .overall-avg-col{width:64px;min-width:64px;max-width:64px}.marksheet .overall-grade-col{width:52px;min-width:52px;max-width:52px}.marksheet .overall-pos-col{width:58px;min-width:58px;max-width:58px}.marksheet .subjecthead{font-size:11px;color:#fff;text-transform:uppercase}.marksheet .name-head,.marksheet .name-cell{text-align:left;min-width:170px;width:170px;max-width:170px}.marksheet td b{font-weight:800}.subject-mean-summary{page-break-before:always;break-before:page;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;width:100%;min-width:0;max-width:100%;min-height:245mm;margin:0;padding:18mm 10mm 10mm;background:#fff;box-sizing:border-box;overflow:visible}.subject-mean-title{font-size:20px;font-weight:900;text-align:center;text-transform:uppercase;margin:0 0 14px;padding:0 0 8px;width:100%;max-width:820px;border-bottom:2px solid #111}.subject-mean-grid{width:100%;min-width:0;max-width:100%;display:block;overflow:visible;box-sizing:border-box}.subject-analysis-wrap{display:block;width:100%;min-width:0;max-width:100%;margin:0 auto;overflow:visible;box-sizing:border-box}.distribution-scroll{display:block;width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x;overscroll-behavior-x:contain;padding-bottom:8px;box-sizing:border-box;scrollbar-gutter:stable}.distribution-scroll:focus{outline:2px solid #94a3b8;outline-offset:2px}.distribution-title{font-size:10px;font-weight:900;text-align:center;text-transform:uppercase;margin:3px 0}.grade-distribution{border-collapse:collapse;width:max-content;min-width:760px;table-layout:fixed;margin:0}.grade-distribution th,.grade-distribution td{border:1px solid #111!important;padding:3px 4px;text-align:center;font-size:8.5px;line-height:1.1;box-sizing:border-box}.grade-distribution th{font-weight:900;background:#fff;color:#000}.subject-distribution th:first-child,.subject-distribution td:first-child{width:10%;text-align:left;padding-left:3px;font-weight:900}.subject-distribution th:nth-last-child(3),.subject-distribution td:nth-last-child(3){width:10%}.subject-distribution th:nth-last-child(2),.subject-distribution td:nth-last-child(2){width:10%}.subject-distribution th:nth-last-child(1),.subject-distribution td:nth-last-child(1){width:10%}.overall-distribution th:nth-last-child(2),.overall-distribution td:nth-last-child(2){width:12%}.overall-distribution th:nth-last-child(1),.overall-distribution td:nth-last-child(1){width:15%}.print-footer{position:fixed;left:0;right:0;bottom:0;text-align:center;border-top:2px solid #2E8B57;padding-top:4px;font-size:8px;color:#176B3A;background:#fff}@page{size:A4 landscape;margin:8mm 8mm 12mm}';
  var footer='<div class="print-footer"><i>DaviSchool Management System</i> · Generated: '+generatedAt+'</div>';
  var previewBar='<div class="marksheet-preview-bar no-print"><div><b>🖨️ MarkSheet Print Preview</b><span>Review the complete MarkSheet before printing.</span></div><div><button type="button" onclick="window.print()">🖨️ Print MarkSheet</button><button type="button" onclick="window.close()">✕ Close Preview</button></div></div>';
  var previewCss='.marksheet-preview-bar{position:sticky;top:0;z-index:9999;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 16px;margin:0 0 14px;background:#172033;color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.15);font-family:Arial,sans-serif}.marksheet-preview-bar span{display:block;font-size:12px;font-weight:400;margin-top:3px;opacity:.85}.marksheet-preview-bar button{border:0;border-radius:8px;padding:10px 14px;margin-left:7px;font-weight:800;cursor:pointer;background:#fff;color:#172033}.marksheet-preview-bar button:first-child{background:#176B3A;color:#fff}@media print{.marksheet-preview-bar{display:none!important}}';
  var html='<!doctype html><html><head><meta charset="utf-8"><title>MarkSheet Print Preview</title><style>'+css+previewCss+'</style></head><body>'+previewBar+printDoc.outerHTML+footer+'</body></html>';
  w.document.open();w.document.write(html);w.document.close();w.focus();
}
</script>'''
    subject_mean_rows = sorted(
        subject_means,
        key=lambda item: (
            subject_positions.get(int(item[0]["id"]), 9999),
            str(item[0]["name"]).casefold(),
        ),
    )
    subject_summary_values = {
        int(subject["id"]): (mean, count, subject_positions.get(int(subject["id"]), "—"))
        for subject, mean, count in subject_mean_rows
    }

    # Compact on-screen/print-preview grade distributions. They deliberately
    # use horizontal grade columns so the entire analysis fits one landscape page.
    grade_order = ["A", "B", "C", "D", "E"]
    overall_grade_counts = {}
    subject_grade_counts = {int(s["id"]): {} for s in subjects}
    for student, total, total_points, count, cells in computed:
        if count:
            average = total / count
            try:
                og = str(_overall_grade(cur, sid, average, overall_rules) or "").strip()
            except Exception:
                og = str(_default_grade_points(average)[0] or "").strip()
            if og and og != "—":
                overall_grade_counts[og] = overall_grade_counts.get(og, 0) + 1
        for subject in subjects:
            value = marks.get((int(student["id"]), int(subject["id"])))
            if value is None:
                continue
            try:
                sg, _, _ = _subject_grade_details(cur, sid, int(subject["id"]), value, grading_rules)
            except Exception:
                sg, _ = _default_grade_points(float(value))
            sg = str(sg or "").strip()
            if sg and sg != "—":
                bucket = subject_grade_counts[int(subject["id"])]
                bucket[sg] = bucket.get(sg, 0) + 1

    all_grades = set(overall_grade_counts.keys())
    for counts in subject_grade_counts.values():
        all_grades.update(counts.keys())
    distribution_grades = [g for g in grade_order if g in all_grades]
    distribution_grades += sorted(g for g in all_grades if g not in grade_order)

    # computed rows are tuples: (student, total, total_points, count, cells).
    # Keep this summary based on the actual selected students; do not treat the
    # tuple as a mapping (which previously caused the grade-selection request
    # to return HTTP 500).
    # Class Mean is based on actual student total marks, not an average of
    # student averages. Include every student who sat at least one exam
    # subject; exclude only students with no recorded exam mark at all.
    # This also applies when classes/streams are combined.
    # computed rows are tuples: (student, total, total_points, count, cells).
    mean_eligible_students = [
        item for item in computed if int(item[3] or 0) > 0
    ]
    overall_entries = len(mean_eligible_students)
    # Mean of eligible students' TOTAL MARKS. Partial exam attempts are included.
    overall_class_mean = (
        sum(float(item[1] or 0) for item in mean_eligible_students)
        / len(mean_eligible_students)
        if mean_eligible_students else None
    )
    # Identify the exact class/stream scope automatically so the overall
    # distribution label always tells the user which distribution is shown.
    # class_title already resolves to e.g. "Grade 8 — STREAM: A" or
    # "Grade 8 — ALL STREAMS", depending on the current MarkSheet filters.
    overall_distribution_label = "OVERALL GRADE DISTRIBUTION — " + str(class_title)
    overall_distribution_html = ""
    if distribution_grades:
        overall_distribution_html = (
            "<div class='marksheet-scroll distribution-scroll'><div class='distribution-title'>" + overall_distribution_label + "</div>"
            "<table class='grade-distribution overall-distribution'><thead><tr>" +
            "".join("<th>%s</th>" % escape(g) for g in distribution_grades) +
            "<th>Entries</th><th>Class Mean</th></tr></thead><tbody><tr>" +
            "".join("<td>%d</td>" % overall_grade_counts.get(g, 0) for g in distribution_grades) +
            "<td>%d</td><td>%s</td>" % (overall_entries, ("%.2f" % overall_class_mean) if overall_class_mean is not None else "—") +
            "</tr></tbody></table></div>"
        )

    subject_distribution_html = ""
    if distribution_grades and subjects:
        subject_distribution_html = (
            "<div class='marksheet-scroll distribution-scroll'><div class='distribution-title'>PER-SUBJECT GRADE DISTRIBUTION</div>"
            "<table class='grade-distribution subject-distribution'><thead><tr><th>Subject</th>" +
            "".join("<th>%s</th>" % escape(g) for g in distribution_grades) +
            "<th>Entries</th><th>Mean</th><th>Position</th></tr></thead><tbody>" +
            "".join(
                "<tr><td>%s</td>%s<td>%d</td><td>%s</td><td>%s</td></tr>" % (
                    escape(_subject_marksheet_label(subject)),
                    "".join(
                        "<td>%d</td>" % subject_grade_counts[int(subject["id"])].get(g, 0)
                        for g in distribution_grades
                    ),
                    int(subject_summary_values.get(int(subject["id"]), (None, 0, "—"))[1] or 0),
                    ("%.2f" % subject_summary_values[int(subject["id"])][0]) if subject_summary_values.get(int(subject["id"]), (None,))[0] is not None else "—",
                    str(subject_summary_values.get(int(subject["id"]), (None, 0, "—"))[2]),
                )
                for subject in subjects
            ) +
            "</tbody></table></div>"
        )

    subject_mean_html = (
        "<div class='subject-analysis-wrap'>" +
        overall_distribution_html +
        subject_distribution_html +
        "</div>"
    )
    rows_html = rows or "<tr><td colspan='%d'>No students or marks found.</td></tr>" % colspan
    all_rows_html = all_rows or "<tr><td colspan='%d'>No students or marks found.</td></tr>" % colspan
    body = (
        "<div class='page'><h1>Class Marksheets</h1>"
        "<div class='muted'>A print-ready marksheet. Select one or more assessments; when multiple assessments are selected, each subject shows their average.</div>"
        "<div class='card section no-print'><form method='get' action='/app/academics/marksheets?ds_tab=" + quote(marksheet_tab_id, safe='') + "' class='marksheet-select'><input type='hidden' name='ds_tab' value='" + escape(marksheet_tab_id) + "'>"
        "<select name='class_id' class='field' onchange='this.form.submit()'><option value=''>Select Class</option>" + copts + "</select>"
        "<select name='stream' class='field' onchange='this.form.submit()'><option value=''>All Streams</option>" + stropts + "</select>"
        "<select name='term' class='field' onchange='this.form.submit()'><option value=''>All Terms</option>" + topts + "</select>"
        "<select name='year' class='field' onchange='this.form.submit()'><option value=''>All Years</option>" + yopts + "</select>"
        "<select name='exam_id' class='field' onchange='this.form.submit()'><option value=''>Select Exam</option>" + eopts + "</select>"
        "<input type='hidden' name='subject_ids' id='selectedSubjectIds' value='" + escape(','.join(str(x) for x in selected_subject_ids)) + "'>"
        "<input type='hidden' name='subject_metrics' id='selectedSubjectMetrics' value='" + escape(subject_metrics or '') + "'>"
        "<input type='hidden' name='overall_metrics' id='selectedOverallMetrics' value='" + escape(','.join(overall_metric_list)) + "'>"
        "<button type='button' class='btn' onclick='printDocument()'>Print Marksheet</button>" + pdf_marksheet_url +
        "<div class='subject-picker'><div class='subject-picker-title'>Subjects to display on MarkSheet</div><div class='subject-picker-grid'>" +
        "".join("<label><input type='checkbox' class='subject-choice' value='%s' %s> %s</label>" % (s["id"], "checked" if (not selected_subject_ids or int(s["id"]) in set(selected_subject_ids)) else "", escape(str(s["name"]))) for s in _marksheet_subject_order(cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall())) +
        "</div><div class='subject-picker-actions'><button type='button' class='btnlink' onclick='document.querySelectorAll(\".subject-choice\").forEach(function(x){x.checked=true})'>Select all</button><button type='button' class='btnlink' onclick='document.querySelectorAll(\".subject-choice\").forEach(function(x){x.checked=false})'>Clear</button></div></div>" +
        "<div class='subject-metric-picker'><div class='subject-picker-title'>Display for each selected subject</div><div class='subject-metric-grid'>" +
        "".join("<div><b>%s:</b> %s</div>" % (escape(str(s["name"])), "".join("<label class='metric-label'><input type='checkbox' class='metric-choice' data-subject='%s' value='%s' %s> %s</label>" % (s["id"],m,"checked" if m in subject_metric_map.get(int(s["id"]),["mks","grade","pts"]) else "",{"mks":"MKS","grade":"GRD","pts":"PTS"}[m]) for m in ("mks","grade","pts"))) for s in subjects) +
        "</div></div><div class='subject-metric-picker'><div class='subject-picker-title'>Display under OVERALL</div><div class='subject-metric-grid'>" +
        "".join("<label class='metric-label'><input type='checkbox' class='overall-choice' value='%s' %s> %s</label>" % (m, "checked" if m in overall_metric_list else "", {"mks":"MKS","pts":"PTS","avg":"AVG %","grade":"GRD","pos":"POS"}[m]) for m in ("mks","pts","avg","grade","pos")) +
        "</div><div style='margin-top:12px'><button type='submit' class='btn' onclick='var a=[];document.querySelectorAll(\".subject-choice:checked\").forEach(function(x){a.push(x.value)});var sm=[];document.querySelectorAll(\".metric-choice:checked\").forEach(function(x){var id=x.dataset.subject;var f=sm.find(function(y){return y.id===id});if(!f){f={id:id,m:[]};sm.push(f)}f.m.push(x.value)});var om=[];document.querySelectorAll(\".overall-choice:checked\").forEach(function(x){om.push(x.value)});document.getElementById(\"selectedSubjectIds\").value=a.join(\",\");document.getElementById(\"selectedSubjectMetrics\").value=sm.map(function(x){return x.id+\":\"+x.m.join(\".\")}).join(\",\");document.getElementById(\"selectedOverallMetrics\").value=om.join(\",\")'>Apply Display</button></div></div>" +
        "</form><div class='marksheet-action-links'><a class='btnlink' href='/app/academics/marks?ds_tab=" + quote(marksheet_tab_id, safe='') + "'>Enter / Edit Marks</a><a class='btnlink' href='/app/academics/blank-marksheet?ds_tab=" + quote(marksheet_tab_id, safe='') + "'>🖨 Blank MarkSheet</a><a class='btnlink' href='/app/academics/grading?ds_tab=" + quote(marksheet_tab_id, safe='') + "'>Set Subject Grade & Points</a><a class='btnlink' href='/app/academics/overall-grading?ds_tab=" + quote(marksheet_tab_id, safe='') + "'>Set Overall Grade</a></div></div>" +
        "<div id='marksheet-all-rows' style='display:none'><table><tbody>" + all_rows_html + "</tbody></table></div>" +
        "<div class='card section marksheet-card'>" + doc_brand +
        "<div class='marksheet-title'>STUDENT MARKSHEET</div>"
        "<div class='marksheet-meta'>CLASS: " + class_title + " &nbsp;&nbsp; EXAM: " + exam_name +
        " &nbsp;&nbsp; TERM: " + escape(term or "All") + " &nbsp;&nbsp; YEAR: " + escape(year or "All") + "</div>"
        "<div class='marksheet-scroll' tabindex='0'><table class='marksheet'><colgroup>"
        "<col class='adm-no-col'><col class='name-col'>" + stream_colgroup_html + subject_colgroup +
        "" + "".join("<col class='overall-%s-col'>" % m for m in overall_metric_list) + ""
        "</colgroup><thead><tr><th rowspan='2' class='adm-no-head'>ADM NO.</th><th rowspan='2' class='name-head'>NAME</th>" +
        stream_col_html + header_cells + "<th colspan='" + str(len(overall_metric_list)) + "'>OVERALL</th></tr><tr>" + sub_header_cells +
        "".join("<th class='overall-%s-col'>%s</th>" % (m, {"mks":"MKS","pts":"PTS","avg":"AVG %","grade":"GRD","pos":"POS"}[m]) for m in overall_metric_list) + "</tr></thead><tbody>" +
        rows_html + "</tbody></table>" + marksheet_pagination + "</div><div class='subject-mean-summary'><div class='subject-mean-title'>GRADE DISTRIBUTION ANALYSIS</div>" +
        "<div class='subject-mean-grid'>" + subject_mean_html + "</div></div></div></div>" +
        print_script +
        "<style>"
        ".field{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}"
        ".marksheet-select{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}.subject-picker{grid-column:1/-1;border:1px solid #dbe2ea;border-radius:10px;padding:10px;background:#f8fafc}.subject-picker-title{font-weight:900;margin-bottom:8px}.subject-picker-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:7px 12px}.subject-picker-grid label{font-weight:600}.subject-picker-actions{margin-top:8px}.subject-metric-picker{grid-column:1/-1;border:1px solid #dbe2ea;border-radius:10px;padding:10px;background:#fff}.subject-metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:7px 14px}.metric-label{margin-left:6px;font-weight:600}.btn,.btnlink{padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}.btnlink{background:#fff;color:#172033;margin:0}.marksheet-action-links{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px;margin-top:10px}.marksheet-action-links .btnlink{display:inline-flex;align-items:center;justify-content:center;white-space:normal;line-height:1.25;text-align:center;min-height:42px}"
        ".marksheet-card{background:#fff;min-width:0;overflow:visible}.marksheet-scroll{display:block;width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;overscroll-behavior-x:contain;padding-bottom:8px;scrollbar-gutter:stable}.marksheet-scroll:focus{outline:2px solid #94a3b8;outline-offset:2px}.marksheet{width:max-content;min-width:100%}.marksheet-pagination{display:flex;align-items:center;justify-content:center;gap:16px;padding:10px 0}.marksheet-pagination .btnlink:disabled{opacity:.45;cursor:not-allowed}.marksheet thead tr:first-child th{background:#fff;color:#000;font-weight:900}.marksheet thead tr:nth-child(2) th{background:#fff;color:#000;font-weight:900}.marksheet th:nth-child(1),.marksheet td:nth-child(1){position:sticky;left:0;background:#fff;z-index:10}.marksheet th:nth-child(2),.marksheet td:nth-child(2){position:sticky;left:78px;background:#fff;z-index:10}.marksheet thead tr:first-child th:nth-child(1),.marksheet thead tr:first-child th:nth-child(2),.marksheet thead tr:nth-child(2) th:nth-child(1),.marksheet thead tr:nth-child(2) th:nth-child(2){z-index:13}.doc-header{display:flex;align-items:flex-start;gap:14px;border-top:2px solid #2E8B57;border-bottom:3px solid #176B3A;padding:8px 4px 10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center;flex:0 0 86px}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school-block{flex:1;min-width:0}.doc-school{font-size:20px;line-height:1.15;font-weight:900;text-transform:uppercase;color:#176B3A}.doc-contact{font-size:10px;color:#334155;margin-top:5px;line-height:1.55}.doc-contact div{display:block;margin:1px 0}.doc-right{font-size:10px;color:#176B3A;line-height:1.65;text-align:left;min-width:155px;padding-top:2px}.doc-right div{display:block;margin:1px 0}.marksheet-title{text-align:center;font-size:24px;font-weight:900;color:#176B3A;padding:5px 4px 6px}.marksheet-school{display:none!important}.marksheet-meta{font-size:14px;font-weight:800;padding:8px 4px;border-top:1px solid #111;border-bottom:1px solid #111}.marksheet{border-collapse:collapse;width:max-content;min-width:0;font-family:Arial,sans-serif;table-layout:fixed}.marksheet th,.marksheet td{border:1.25px solid #111;padding:6px 8px;text-align:center;font-size:12px;white-space:nowrap;box-sizing:border-box}.marksheet th{background:#fff;color:#000;text-transform:none;font-weight:900}.marksheet thead tr:nth-child(2) th{background:#fff;color:#000;font-weight:900}.marksheet tbody td{border-top:1px solid #111;border-bottom:1px solid #111}.marksheet .adm-no-col{width:58px;min-width:58px;max-width:58px}.marksheet .name-col{width:170px;min-width:170px;max-width:170px}.marksheet .stream-col,.marksheet .stream-cell{width:55px;min-width:55px;max-width:55px}.marksheet .mks-col,.marksheet .points-col{width:48px;min-width:48px;max-width:48px}.marksheet .grade-col{width:44px;min-width:44px;max-width:44px}.marksheet .overall-marks-col{width:58px;min-width:58px;max-width:58px}.marksheet .overall-points-col{width:58px;min-width:58px;max-width:58px}.marksheet .overall-avg-col{width:64px;min-width:64px;max-width:64px}.marksheet .overall-grade-col{width:52px;min-width:52px;max-width:52px}.marksheet .overall-pos-col{width:58px;min-width:58px;max-width:58px}.marksheet .mks-cell,.marksheet .points-cell{vertical-align:middle;width:58px;min-width:58px;max-width:58px}.marksheet .grade-cell{vertical-align:middle;width:50px;min-width:50px;max-width:50px}.marksheet .subjecthead{font-size:13px;color:#000;font-weight:900;text-transform:uppercase;white-space:nowrap;overflow:hidden;max-width:166px} .marksheet .overall-marks-col{min-width:82px}.marksheet .overall-points-col{min-width:82px}.marksheet .overall-avg-col{min-width:92px}.marksheet .overall-grade-col{min-width:68px}.marksheet .overall-pos-col{min-width:58px}.marksheet .name-head,.marksheet .name-cell{text-align:left;min-width:170px;width:170px;max-width:170px}.marksheet td b{font-weight:800}.subject-mean-summary{margin-top:12px;border:1px solid #111827;padding:9px;background:#fff}.subject-mean-title{font-size:12px;font-weight:900;text-align:center;border-bottom:1px solid #111827;padding-bottom:5px;margin-bottom:7px}.subject-mean-grid{display:block;width:100%;min-width:0;max-width:100%;overflow:visible;box-sizing:border-box}.subject-summary{border-collapse:collapse;width:100%;table-layout:fixed}.subject-summary th,.subject-summary td{border:1px solid #111;padding:10px 18px;text-align:center;line-height:1.35}.subject-summary th{font-weight:900;background:#fff;color:#000}.subject-summary th:nth-child(1),.subject-summary td:nth-child(1){width:48%;text-align:left;padding-left:18px}.subject-summary th:nth-child(2),.subject-summary td:nth-child(2){width:17%}.subject-summary th:nth-child(3),.subject-summary td:nth-child(3){width:17%}.subject-summary th:nth-child(4),.subject-summary td:nth-child(4){width:18%;padding-right:18px}.subject-mean-summary{page-break-before:always;break-before:page;margin-top:18px;padding-top:18px}.subject-mean-item{border:1px solid #cbd5e1;padding:6px;text-align:center}.subject-mean-item span{display:block;font-size:10px;font-weight:800;text-transform:uppercase}.subject-mean-item b{display:block;font-size:14px;margin:2px 0}.subject-mean-item small{font-size:8px;color:#64748b}.subject-mean-empty{font-size:10px;color:#64748b;text-align:center;padding:5px}"
        "@media(max-width:900px){.marksheet-select{grid-template-columns:1fr 1fr}}"
        "@media print{body{background:#fff}.marksheet-pagination{display:none!important}.marksheet tbody tr{display:table-row!important}.side,.top,.no-print,.page>h1,.page>.muted{display:none!important}.main{margin-left:0!important;padding:0!important}.page{padding:0!important;margin:0!important;max-width:none!important}.marksheet-card{display:block!important;border:0!important;box-shadow:none!important;margin:0!important;padding:0!important;width:100%!important}.marksheet-card .doc-header{margin-top:0}.marksheet-title{font-size:20px}.marksheet-school{font-size:20px}.marksheet th,.marksheet td{padding:4px 5px;font-size:10px}}"
        "</style></div>"
    )
    con.close()
    return _school_page(request, "Class Marksheets", body)



@router.get("/app/academics/marksheets/pdf")
def class_marksheets_pdf(
    request: Request,
    exam_id: str = "",
    exam_ids: str = "",
    class_id: str = "",
    term: str = "",
    year: str = "",
    stream: str = "",
    subject_ids: str = "",
    subject_metrics: str = "",
    overall_metrics: str = "",
):
    """Download the currently selected MarkSheet as a real PDF file."""
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to download marksheets.", 403)

    con = _db()
    try:
        cur = con.cursor()
        exams = cur.execute(
            "SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (sid,)
        ).fetchall()
        classes = cur.execute(
            "SELECT * FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)
        ).fetchall()
        subjects = _marksheet_subject_order(
            cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
        )

        selected_exam_ids = _parse_exam_ids(exam_ids, exam_id)
        if not selected_exam_ids and exams:
            selected_exam_ids = [int(exams[0]["id"])]
        if not selected_exam_ids:
            return HTMLResponse("No examination is available for this MarkSheet.", 400)

        combined_mode = str(class_id).startswith("grade:")
        combined_grade = str(class_id)[6:] if combined_mode else ""

        def _grade_group_key_pdf(row):
            name = str(row["name"] or "").strip()
            stream_value = str(row["stream"] or "").strip()
            if stream_value:
                return name
            match = re.match(r"^(.*?\d)\s*[A-Za-z]$", name)
            return match.group(1).strip() if match else name

        if combined_mode:
            selected_class_ids = [
                int(c["id"]) for c in classes
                if _grade_group_key_pdf(c).strip().lower() == combined_grade.strip().lower()
            ]
        else:
            cid = int(class_id) if str(class_id).isdigit() else (int(classes[0]["id"]) if classes else 0)
            selected_class_ids = [cid] if cid else []

        if not selected_class_ids:
            return HTMLResponse("Please select a class or combined grade before downloading.", 400)

        exam_rows = [
            e for e in exams if int(e["id"]) in set(selected_exam_ids)
        ]
        if not exam_rows:
            return HTMLResponse("The selected examination could not be found.", 404)

        first_exam = exam_rows[0]
        if not term:
            term = str(first_exam["term"] or "")
        if not year:
            year = str(first_exam["year"] or "")

        placeholders = ",".join("?" for _ in selected_class_ids)
        student_sql = (
            "SELECT * FROM students WHERE school_id=? AND class_id IN (" +
            placeholders + ")"
        )
        student_params = [sid] + selected_class_ids
        if stream and not combined_mode:
            student_sql += " AND stream=?"
            student_params.append(stream)
        student_sql += " ORDER BY name"
        students = cur.execute(student_sql, student_params).fetchall()

        # Preserve the complete exam subject set for Class Mean eligibility.
        # Display-only subject filtering must not make a partially completed exam
        # look like a full exam.
        full_exam_subject_count = len(subjects)

        selected_ids = []
        for raw_id in str(subject_ids or "").split(","):
            try:
                if raw_id.strip():
                    selected_ids.append(int(raw_id.strip()))
            except (TypeError, ValueError):
                pass
        if selected_ids:
            selected_set = set(selected_ids)
            subjects = [s for s in subjects if int(s["id"]) in selected_set]

        subject_metric_map = {}
        for part in str(subject_metrics or "").split(","):
            if ":" not in part:
                continue
            raw_id, raw_metrics = part.split(":", 1)
            try:
                subject_metric_map[int(raw_id)] = [
                    m for m in raw_metrics.split(".")
                    if m in ("mks", "grade", "pts")
                ]
            except (TypeError, ValueError):
                pass
        for subject in subjects:
            subject_metric_map.setdefault(int(subject["id"]), ["mks", "grade", "pts"])

        overall_metric_list = [
            m for m in str(overall_metrics or "").split(",")
            if m in ("mks", "pts", "avg", "grade", "pos")
        ]
        if not overall_metric_list:
            overall_metric_list = ["mks", "pts", "avg", "grade", "pos"]

        marks = _aggregate_marks_for_students(
            cur, sid, [int(st["id"]) for st in students],
            selected_exam_ids, term, year
        )
        grading_rules = _load_grading_rules(cur, sid)
        overall_rules = _load_overall_grading_rules(cur, sid)

        computed = []
        subject_totals = {int(s["id"]): 0.0 for s in subjects}
        subject_counts = {int(s["id"]): 0 for s in subjects}

        for student in students:
            total = 0.0
            total_points = 0.0
            count = 0
            values = {}
            for subject in subjects:
                value = marks.get((int(student["id"]), int(subject["id"])))
                if value is None:
                    values[int(subject["id"])] = None
                    continue
                try:
                    value = float(value)
                    grade, points, _ = _subject_grade_details(
                        cur, sid, int(subject["id"]), value, grading_rules
                    )
                except Exception:
                    value = float(value)
                    grade, points = _default_grade_points(value)
                values[int(subject["id"])] = (value, grade, float(points or 0))
                subject_totals[int(subject["id"])] += value
                subject_counts[int(subject["id"])] += 1
                total += value
                total_points += float(points or 0)
                count += 1
            average = (total / count) if count else 0.0
            overall_grade = _overall_grade(cur, sid, average, overall_rules) if count else "—"
            computed.append({
                "student": student,
                "values": values,
                "total": total,
                "points": total_points,
                "count": count,
                "average": average,
                "grade": overall_grade,
            })

        computed.sort(key=lambda item: (-item["total"], str(item["student"]["name"] or "").casefold()))
        last_total = None
        position = 0
        for index, item in enumerate(computed, 1):
            if last_total is None or item["total"] != last_total:
                position = index
                last_total = item["total"]
            item["position"] = position

        school_row = cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
        if combined_mode:
            class_title = (combined_grade + " — ALL STREAMS").strip()
        else:
            selected_class = next(
                (c for c in classes if int(c["id"]) == selected_class_ids[0]), None
            )
            class_title = str(selected_class["name"] or "") if selected_class else "Class"
            selected_stream = str(stream or (selected_class["stream"] or "")).strip() if selected_class else str(stream or "")
            if selected_stream:
                class_title += " — STREAM: " + selected_stream
            else:
                class_title += " — ALL STREAMS"

        exam_title = " + ".join(str(e["name"] or "") for e in exam_rows)
        styles = _pdf_styles()
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm

        story = []
        story.extend(_pdf_school_header(
            school_row,
            styles,
            "STUDENT MARKSHEET",
            "Class: %s   |   Examination: %s   |   Term: %s   |   Year: %s"
            % (class_title, exam_title, term or "All", year or "All"),
        ))

        header = ["ADM NO.", "STUDENT NAME"]
        for subject in subjects:
            label = _subject_marksheet_label(subject)
            for metric in subject_metric_map[int(subject["id"])]:
                header.append("%s %s" % (label, {"mks": "MKS", "grade": "GRD", "pts": "PTS"}[metric]))
        for metric in overall_metric_list:
            header.append("OVERALL " + {"mks": "MKS", "pts": "PTS", "avg": "AVG %", "grade": "GRD", "pos": "POS"}[metric])

        table_rows = [[Paragraph(escape(str(x)), styles["table_head"]) for x in header]]
        for item in computed:
            student = item["student"]
            row = [
                Paragraph(escape(str(student["admission_no"] or "")), styles["table"]),
                Paragraph(escape(str(student["name"] or "")), styles["table"]),
            ]
            for subject in subjects:
                value = item["values"].get(int(subject["id"]))
                for metric in subject_metric_map[int(subject["id"])]:
                    if value is None:
                        text_value = "—"
                    elif metric == "mks":
                        text_value = "%.1f" % value[0]
                    elif metric == "grade":
                        text_value = str(value[1])
                    else:
                        text_value = "%.1f" % value[2]
                    row.append(Paragraph(escape(text_value), styles["table"]))
            for metric in overall_metric_list:
                if metric == "mks":
                    text_value = "%.1f" % item["total"]
                elif metric == "pts":
                    text_value = "%.1f" % item["points"]
                elif metric == "avg":
                    text_value = "%.1f%%" % item["average"]
                elif metric == "grade":
                    text_value = str(item["grade"])
                else:
                    text_value = str(item["position"])
                row.append(Paragraph(escape(text_value), styles["table"]))
            table_rows.append(row)

        col_count = max(1, len(header))
        col_widths = [17 * mm, 34 * mm] + [9.5 * mm] * (col_count - 2)
        if col_count > 15:
            col_widths = [15 * mm, 29 * mm] + [7.5 * mm] * (col_count - 2)

        table = Table(table_rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.white),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (1, 1), (1, -1), "LEFT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(table)

        # Keep the complete analysis together on one dedicated A4-landscape page.
        # This prevents Subject Means / grade distributions from being split across pages.
        story.append(PageBreak())
        # The per-subject distribution table now carries the exact Entries, Mean,
        # and Position values that were previously shown in the separate Subject Means table.
        subject_mean_values = []
        for subject in subjects:
            sid_subject = int(subject["id"])
            count = subject_counts[sid_subject]
            mean = subject_totals[sid_subject] / count if count else None
            subject_mean_values.append((subject, mean, count))
        ranked_subjects = sorted(
            [x for x in subject_mean_values if x[1] is not None],
            key=lambda x: (-float(x[1]), str(x[0]["name"]).casefold())
        )
        subject_positions = {}
        last_mean = None
        last_pos = 0
        for idx, item in enumerate(ranked_subjects, 1):
            if last_mean is None or float(item[1]) != float(last_mean):
                last_pos = idx
                last_mean = float(item[1])
            subject_positions[int(item[0]["id"])] = last_pos

        # Overall grade distribution: grades across columns, counts directly below.
        grade_order = ["A", "B", "C", "D", "E"]
        grade_counts = {}
        for item in computed:
            grade = str(item.get("grade") or "").strip()
            if grade and grade != "—":
                grade_counts[grade] = grade_counts.get(grade, 0) + 1
        ordered_grades = [g for g in grade_order if g in grade_counts]
        ordered_grades += sorted(g for g in grade_counts if g not in grade_order)

        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("OVERALL GRADE DISTRIBUTION", styles["subtitle"]))
        if ordered_grades:
            overall_entries_pdf = sum(1 for item in computed if int(item.get("count", 0) or 0) > 0)
            # PDF Class Mean must use eligible students' actual total marks,
            # matching the MarkSheet HTML calculation. Partial exam attempts count;
            # only students with no recorded exam mark are excluded.
            mean_eligible_students_pdf = [
                item for item in computed
                if int(item.get("count", 0) or 0) > 0
            ]
            overall_class_mean_pdf = (
                sum(float(item.get("total", 0) or 0) for item in mean_eligible_students_pdf)
                / len(mean_eligible_students_pdf)
                if mean_eligible_students_pdf else None
            )
            overall_rows = [
                [Paragraph(escape(g), styles["table_head"]) for g in ordered_grades]
                + [Paragraph("Entries", styles["table_head"]), Paragraph("Class Mean", styles["table_head"])],
                [Paragraph(str(grade_counts[g]), styles["table"]) for g in ordered_grades]
                + [Paragraph(str(overall_entries_pdf), styles["table"]),
                   Paragraph(("%.2f" % overall_class_mean_pdf) if overall_class_mean_pdf is not None else "—", styles["table"])],
            ]
            grade_col_width = max(22 * mm, min(34 * mm, 150 * mm / len(ordered_grades)))
            overall_table = Table(
                overall_rows,
                colWidths=[grade_col_width] * len(ordered_grades) + [22 * mm, 28 * mm],
                hAlign="CENTER",
            )
            overall_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(overall_table)

        # Per-subject grade distribution: one compact row per subject.
        subject_grade_counts = {}
        for subject in subjects:
            sid_subject = int(subject["id"])
            counts = {}
            for item in computed:
                value = item["values"].get(sid_subject)
                if value is None:
                    continue
                grade = str(value[1] or "").strip()
                if grade and grade != "—":
                    counts[grade] = counts.get(grade, 0) + 1
            subject_grade_counts[sid_subject] = counts

        all_subject_grades = set()
        for counts in subject_grade_counts.values():
            all_subject_grades.update(counts.keys())
        subject_grades = [g for g in grade_order if g in all_subject_grades]
        subject_grades += sorted(g for g in all_subject_grades if g not in grade_order)

        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("PER-SUBJECT GRADE DISTRIBUTION", styles["subtitle"]))
        if subject_grades:
            distribution_rows = [[
                Paragraph("Subject", styles["table_head"])
            ] + [
                Paragraph(escape(g), styles["table_head"]) for g in subject_grades
            ] + [
                Paragraph("Entries", styles["table_head"]),
                Paragraph("Mean", styles["table_head"]),
                Paragraph("Position", styles["table_head"]),
            ]]
            for subject in subjects:
                sid_subject = int(subject["id"])
                counts = subject_grade_counts[sid_subject]
                mean = subject_totals[sid_subject] / subject_counts[sid_subject] if subject_counts[sid_subject] else None
                distribution_rows.append([
                    Paragraph(escape(_subject_marksheet_label(subject)), styles["table"])
                ] + [
                    Paragraph(str(counts.get(g, 0)), styles["table"])
                    for g in subject_grades
                ] + [
                    Paragraph(str(subject_counts[sid_subject]), styles["table"]),
                    Paragraph(("%.2f" % mean) if mean is not None else "—", styles["table"]),
                    Paragraph(str(subject_positions.get(sid_subject, "—")), styles["table"]),
                ])
            dist_col_widths = [20 * mm] + [
                max(12 * mm, min(20 * mm, 88 * mm / len(subject_grades)))
                for _ in subject_grades
            ] + [20 * mm, 22 * mm, 22 * mm]
            distribution_table = Table(
                distribution_rows,
                colWidths=dist_col_widths,
                repeatRows=1,
                hAlign="CENTER",
            )
            distribution_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ALIGN", (0, 1), (0, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ]))
            story.append(distribution_table)

        filename = "MarkSheet_%s_%s.pdf" % (
            re.sub(r"[^A-Za-z0-9]+", "_", class_title).strip("_") or "Class",
            re.sub(r"[^A-Za-z0-9]+", "_", exam_title).strip("_") or "Exam",
        )
        pdf = _pdf_build(story, landscape(A4), "DaviSchool MarkSheet")
        return _pdf_response(pdf, filename)
    except Exception as exc:
        print("DAVISCHOOL MARKSHEET PDF ROUTE ERROR:", repr(exc), flush=True)
        try:
            con.rollback()
        except Exception:
            pass
        return _pdf_route_error(request, "marksheets/pdf", exc)
    finally:
        try:
            con.close()
        except Exception:
            pass

@router.get("/app/academics/blank-marksheet", response_class=HTMLResponse)
def blank_marksheet(request: Request, exam_id: str = "", class_id: str = "", stream: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to generate blank marksheets.", 403)
    con = _db()
    try:
        cur = con.cursor()
        exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC", (sid,)).fetchall()
        classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)).fetchall()
        subjects = _marksheet_subject_order(cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall())
        eid = int(exam_id) if str(exam_id).isdigit() else (int(exams[0]["id"]) if exams else 0)
        selected_exam = cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?", (eid, sid)).fetchone() if eid else None
        cid = int(class_id) if str(class_id).isdigit() else (int(classes[0]["id"]) if classes else 0)
        selected_class = cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?", (cid, sid)).fetchone() if cid else None
        students = []
        if cid:
            sql = "SELECT * FROM students WHERE school_id=? AND class_id=?"
            params = [sid, cid]
            if stream:
                sql += " AND stream=?"
                params.append(stream)
            sql += " ORDER BY name"
            students = cur.execute(sql, params).fetchall()
        school = cur.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
        con.close()
        eopts = "".join("<option value='%s' %s>%s</option>" % (e["id"], "selected" if int(e["id"]) == eid else "", escape(str(e["name"]))) for e in exams)
        copts = "".join("<option value='%s' %s>%s %s</option>" % (c["id"], "selected" if int(c["id"]) == cid else "", escape(str(c["name"])), escape(str(c["stream"] or ""))) for c in classes)
        streams = sorted(set(str(c["stream"] or "") for c in classes if str(c["stream"] or "")))
        stropts = "".join("<option value='%s' %s>%s</option>" % (escape(x), "selected" if x == stream else "", escape(x)) for x in streams)
        subject_headers = "".join("<th>%s<br><span class='blank-sub'>MKS</span></th>" % escape(_subject_marksheet_label(sub)) for sub in subjects)
        student_rows = "".join("<tr><td>%s</td><td class='student-name'>%s</td>%s<td></td></tr>" % (escape(str(st["admission_no"] or "")), escape(str(st["name"] or "")), "".join("<td class='blank-cell'></td>" for _ in subjects)) for st in students)
        if not students:
            student_rows = "<tr><td colspan='%d'>No students found for the selected class/stream.</td></tr>" % (len(subjects) + 3)
        school_name = escape(str(school["name"] or "DaviSchool")) if school else "DaviSchool"
        school_logo = str(school["logo_data"] or "") if school and "logo_data" in school.keys() else ""
        school_email = escape(str(school["email"] or "")) if school and "email" in school.keys() else ""
        school_phone = escape(str(school["phone"] or "")) if school and "phone" in school.keys() else ""
        school_postal = escape("P.O. Box " + str(school["postal_address"])) if school and "postal_address" in school.keys() and school["postal_address"] else ""
        school_postal_code = escape(str(school["postal_code"])) if school and "postal_code" in school.keys() and school["postal_code"] else ""
        contacts = []
        if school:
            for key in ("email", "phone", "postal_address", "postal_code"):
                if key in school.keys() and school[key]:
                    value = str(school[key])
                    if key == "postal_address": value = "P.O. Box " + value
                    contacts.append(value)
        class_title = escape(str(selected_class["name"] or "")) if selected_class else "Class"
        stream_title = escape(stream or (str(selected_class["stream"] or "") if selected_class else ""))
        exam_title = escape(str(selected_exam["name"] or "")) if selected_exam else "Examination"
        body = f"""<div class='page'><h1>Blank MarkSheet</h1><div class='muted'>Print a clean sheet for handwritten marks entry. Only registered student details and column headers are populated.</div>
<div class='card no-print' style='margin-top:14px'><form method='get' action='/app/academics/blank-marksheet' class='blank-controls'>
<div><label>Examination</label><select name='exam_id' class='field'>{eopts}</select></div>
<div><label>Class</label><select name='class_id' class='field'>{copts}</select></div>
<div><label>Stream</label><select name='stream' class='field'><option value=''>All / selected class</option>{stropts}</select></div>
<div style='align-self:end'><button class='btn' type='submit'>Prepare Blank Sheet</button> <input type='hidden' name='ds_tab' value='{escape(tab_id)}'><button class='btn' type='submit'>Load Students</button></div>
</form></div>
<div class='card blank-marksheet-card'><div class='blank-doc-head'><div class='blank-brand-left'><div class='blank-doc-logo'>{("<img src='%s' alt='School logo'>" % escape(school_logo)) if school_logo else "🏫"}</div><div><div class='blank-school'>{school_name}</div><div class='blank-contact'>{("".join("<div>%s</div>" % x for x in [school_postal, school_postal_code] if x))}</div></div></div><div class='blank-doc-right'>{("".join("<div>%s</div>" % x for x in [("☎ "+school_phone) if school_phone else "", ("✉ "+school_email) if school_email else ""] if x))}</div><div class='blank-title'>BLANK MARKS ENTRY SHEET</div></div>
<div class='blank-meta'><b>CLASS:</b> {class_title} &nbsp;&nbsp; <b>STREAM:</b> {stream_title or "All"} &nbsp;&nbsp; <b>EXAM:</b> {exam_title}</div>
<div class='blank-scroll'><table class='blank-marksheet'><thead><tr><th>ADM NO.</th><th>STUDENT NAME</th>{subject_headers}<th>OVERALL</th></tr></thead><tbody>{student_rows}</tbody></table></div>
<div class='blank-note'>Handwritten entry sheet — enter marks clearly, then submit the completed sheet for electronic entry into DaviSchool.</div></div></div>
<style>
.blank-controls{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.blank-controls label{{display:block;font-size:12px;font-weight:800;margin-bottom:5px}}.blank-controls .field{{width:100%;padding:10px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}
.blank-marksheet-card{{background:#fff;overflow:hidden}}.blank-doc-head{{display:flex;align-items:flex-start;gap:14px;border-top:2px solid #2E8B57;border-bottom:3px solid #176B3A;padding:8px 4px 10px}}.blank-brand-left{{display:flex;align-items:flex-start;gap:12px;flex:1;min-width:0}}.blank-doc-logo{{width:86px;height:70px;display:flex;align-items:center;justify-content:center;flex:0 0 86px}}.blank-doc-logo img{{max-width:82px;max-height:66px;object-fit:contain}}.blank-school{{font-size:20px;line-height:1.15;font-weight:900;text-transform:uppercase;color:#176B3A}}.blank-contact{{font-size:10px;color:#334155;margin-top:5px;line-height:1.55}}.blank-contact div{{display:block;margin:1px 0}}.blank-doc-right{{font-size:10px;color:#176B3A;line-height:1.65;min-width:155px}}.blank-doc-right div{{display:block;margin:1px 0}}.blank-title{{font-size:16px;font-weight:900;text-align:right;color:#176B3A}}.blank-meta{{font-size:11px;font-weight:800;padding:8px 4px;border-bottom:1px solid #111827}}.blank-scroll{{overflow-x:auto;padding-bottom:8px}}.blank-marksheet{{border-collapse:collapse;width:max-content;min-width:100%;font-family:Arial,sans-serif}}.blank-marksheet th,.blank-marksheet td{{border:1px solid #111;padding:7px 8px;text-align:center;font-size:10px;white-space:nowrap;height:28px}}.blank-marksheet th{{background:#fff;color:#000;font-weight:900}}.blank-marksheet th:first-child,.blank-marksheet td:first-child{{width:58px;min-width:58px}}.blank-marksheet th:nth-child(2),.blank-marksheet td:nth-child(2){{width:125px;min-width:125px;max-width:125px;text-align:left}}.blank-marksheet th:not(:first-child):not(:nth-child(2)){{min-width:52px;width:52px}}.blank-marksheet .blank-sub{{font-size:8px}}.blank-marksheet .blank-cell{{height:30px;min-width:72px}}.blank-note{{font-size:9px;color:#64748b;margin-top:8px}}
@media(max-width:900px){{.blank-controls{{grid-template-columns:1fr 1fr}}}}
@media print{{@page{{size:A4 landscape;margin:8mm}}body{{background:#fff;color:#172033}}.side,.top,.no-print,.page>h1,.page>.muted{{display:none!important}}.main{{margin-left:0!important;padding:0!important}}.page{{padding:0!important;margin:0!important;max-width:none!important}}.blank-marksheet-card{{border:0!important;box-shadow:none!important;margin:0!important;padding:0!important}}.blank-scroll{{overflow:visible!important}}.blank-marksheet{{width:100%!important}}.blank-marksheet th,.blank-marksheet td{{font-size:8px;padding:5px;border-color:#176B3A}}.blank-marksheet th{{background:#fff;color:#000;font-weight:900}}.blank-school{{font-size:16px}}.blank-title{{font-size:13px}}}}
</style>"""
        return _school_page(request, "Blank MarkSheet", body)
    except Exception as exc:
        try: con.close()
        except Exception: pass
        return HTMLResponse("Unable to generate the blank marksheet: " + escape(str(exc)), 500)

@router.get("/app/finance", response_class=HTMLResponse)
def finance_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not (_require_permission(request, sid, "fees.view") or _require_permission(request, sid, "finance.view")):
        return HTMLResponse("You do not have permission to view fees or finance.", 403)
    con=_db();cur=con.cursor()
    fee=cur.execute("SELECT COALESCE(SUM(amount),0) expected,COALESCE(SUM(paid),0) paid FROM fees WHERE school_id=?",(sid,)).fetchone()
    exp=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM expenses WHERE school_id=?",(sid,)).fetchone()["v"]
    payments=cur.execute("SELECT fp.*,s.name student_name FROM fee_payments fp LEFT JOIN students s ON s.id=fp.student_id WHERE fp.school_id=? ORDER BY fp.id DESC LIMIT 50",(sid,)).fetchall();con.close()
    rows="".join(f"<tr><td>{escape(str(p['student_name'] or ''))}</td><td>KES {float(p['amount'] or 0):,.2f}</td><td>{escape(str(p['date'] or ''))}</td><td>{escape(str(p['reference'] or ''))}</td></tr>" for p in payments)
    body=f"""<div class='page'><h1>Finance & Fees</h1><div class='muted'>Fee register, collections, expenses and financial control.</div><div class='grid'><div class='card'><div class='label'>Fees charged</div><div class='kpi'>KES {float(fee['expected'] or 0):,.0f}</div></div><div class='card'><div class='label'>Collected</div><div class='kpi'>KES {float(fee['paid'] or 0):,.0f}</div></div><div class='card'><div class='label'>Outstanding</div><div class='kpi'>KES {float(fee['expected'] or 0)-float(fee['paid'] or 0):,.0f}</div></div><div class='card'><div class='label'>Expenses</div><div class='kpi'>KES {float(exp or 0):,.0f}</div></div></div><div class='section'><div class='actions'><a class='action' href='/app/finance'><span>💳</span>Finance Workspace</a><a class='action' href='/app/accounting'><span>📚</span>Accounting</a><a class='action' href='/app/accounting'><span>⚖</span>Trial Balance</a><a class='action' href='/app/finance/fees'><span>📒</span>Fee Register</a></div></div><div class='card section'><h2>Recent fee payments</h2><table><thead><tr><th>Student</th><th>Amount</th><th>Date</th><th>Receipt</th></tr></thead><tbody>{rows or '<tr><td colspan=4>No payments yet.</td></tr>'}</tbody></table></div></div>"""
    return _school_page(request,"Finance & Fees",body)


@router.get("/app/school-settings", response_class=HTMLResponse)
def school_settings_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "settings.view"):
        return HTMLResponse("You do not have permission to view school settings.", 403)
    con=_db();cur=con.cursor()
    school=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
    con.close()
    if not school:return RedirectResponse("/app")
    def val(key):
        return escape(str(school[key] or ""))
    logo=str(school["logo_data"] or "") if "logo_data" in school.keys() else ""
    logo_preview=f"<img src='{escape(logo)}' alt='School logo' style='max-width:140px;max-height:100px;object-fit:contain;border:1px solid #dbe2ea;border-radius:10px;padding:6px;background:white'>" if logo else "<div style='width:140px;height:100px;border:1px dashed #cbd5e1;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:12px'>No logo uploaded</div>"
    body=f"""<div class='page'><h1>School Settings</h1><div class='muted'>Manage the registered profile, contact details and document identity for this school.</div><div class='card section'><h2>School Profile</h2><form method='post' action='/app/school-settings' enctype='multipart/form-data' style='display:grid;grid-template-columns:repeat(2,1fr);gap:12px'>
<label>School Name<input name='school_name' required value='{val("name")}' class='field'></label>
<label>School Email<input name='school_email' type='email' required value='{val("email")}' class='field'></label>
<label>Location<input name='location' required value='{val("location")}' class='field'></label>
<label>Phone<input name='phone' required value='{val("phone")}' class='field'></label>
<label>Postal Address<input name='postal_address' placeholder='P.O. Box 123' value='{val("postal_address")}' class='field'></label>
<label>Postal Code<input name='postal_code' placeholder='00100' value='{val("postal_code")}' class='field'></label>
<label>Principal / Administrator<input name='principal' required value='{val("principal")}' class='field'></label>
<label>School Type<select name='school_type' class='field'><option {'selected' if school["school_type"]=="Primary" else ''}>Primary</option><option {'selected' if school["school_type"]=="Secondary" else ''}>Secondary</option><option {'selected' if school["school_type"]=="Primary & Junior Secondary" else ''}>Primary & Junior Secondary</option></select></label>
<div style='grid-column:1/-1'><div style='font-size:12px;font-weight:800;color:#475569;margin-bottom:7px'>School Logo</div>{logo_preview}<input name='school_logo' type='file' accept='image/png,image/jpeg,image/webp,image/gif' class='field' style='margin-top:8px'><div class='muted' style='margin-top:5px'>Upload PNG, JPG, WEBP or GIF. The logo will appear on school printouts, including report cards and marksheets.</div></div>
<div style='grid-column:1/-1'><button class='btn'>Save School Settings</button></div></form></div></div>
<style>label{{display:block;font-size:12px;font-weight:800;color:#475569}}.field{{width:100%;margin-top:6px;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:white}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}</style>"""
    return _school_page(request,"School Settings",body)

@router.post("/app/school-settings")
async def school_settings_save(request: Request, school_name:str=Form(...), school_email:str=Form(...), location:str=Form(...), phone:str=Form(...), principal:str=Form(...), school_type:str=Form(...), postal_address:str=Form(""), postal_code:str=Form(""), school_logo:UploadFile|None=File(None)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "settings.edit"):
        return HTMLResponse("You do not have permission to edit school settings.", 403)
    allowed={"Primary","Secondary","Primary & Junior Secondary"}
    if school_type not in allowed:return HTMLResponse("Invalid school type. <a href='/app/school-settings'>Back</a>",400)
    logo_data=None
    if school_logo and school_logo.filename:
        raw=await school_logo.read()
        if len(raw)>2*1024*1024:return HTMLResponse("School logo is too large. Maximum size is 2 MB. <a href='/app/school-settings'>Back</a>",400)
        content_type=(school_logo.content_type or "").lower()
        allowed_types={"image/png","image/jpeg","image/webp","image/gif"}
        if content_type not in allowed_types:return HTMLResponse("Invalid logo format. Use PNG, JPG, WEBP or GIF. <a href='/app/school-settings'>Back</a>",400)
        logo_data=f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
    con=_db();cur=con.cursor()
    if logo_data:
        cur.execute("UPDATE schools SET name=?,email=?,location=?,phone=?,principal=?,school_type=?,postal_address=?,postal_code=?,logo_data=? WHERE id=?",(school_name.strip(),school_email.strip(),location.strip(),phone.strip(),principal.strip(),school_type,postal_address.strip(),postal_code.strip(),logo_data,sid))
    else:
        cur.execute("UPDATE schools SET name=?,email=?,location=?,phone=?,principal=?,school_type=?,postal_address=?,postal_code=? WHERE id=?",(school_name.strip(),school_email.strip(),location.strip(),phone.strip(),principal.strip(),school_type,postal_address.strip(),postal_code.strip(),sid))
    _audit(cur,sid,request,"SCHOOL_PROFILE_UPDATE",f"Updated school profile and document identity for {school_name.strip()}")
    con.commit();con.close()
    return RedirectResponse("/app/school-settings?saved=1",303)

@router.get("/app/portals", response_class=HTMLResponse)
def portals_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    body="""<div class='page'><h1>School Portals</h1><div class='muted'>Portal access and school-facing services.</div>
<div class='actions section'>
<div class='action'><span>👨‍🎓</span>Student Portal<small style='display:block;color:#64748b;margin-top:5px'>Student-facing access can be connected to this school workspace.</small></div>
<div class='action'><span>👨‍👩‍👧</span>Parent Portal<small style='display:block;color:#64748b;margin-top:5px'>Parent-facing access can be connected to this school workspace.</small></div>
<div class='action'><span>👩‍🏫</span>Teacher Portal<small style='display:block;color:#64748b;margin-top:5px'>Teacher-facing access can be connected to this school workspace.</small></div>
</div>
<div class='card section'><h2>Portal Access</h2><div class='muted'>Use User Management to create and assign school accounts, then use the appropriate role to control portal access.</div><div style='margin-top:12px'><a class='action' href='/app/users'>👤 Open User Management</a> <a class='action' href='/app/roles'>🔐 Open Roles & Permissions</a></div></div></div>"""
    return _school_page(request,"School Portals",body)

@router.get("/app", response_class=HTMLResponse)
def app_home(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")
    role=request.session.get("role","")
    name=request.session.get("name","DaviSchool")
    con=_db(); cur=con.cursor()
    if role=="super_admin":
        schools=cur.execute("SELECT COUNT(*) c FROM schools").fetchone()["c"]
        users=cur.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        platform_users=cur.execute("SELECT full_name,email,role FROM users ORDER BY id").fetchall()
        students=cur.execute("SELECT COUNT(*) c FROM students").fetchone()["c"]
        revenue=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM fee_payments").fetchone()["v"]
        recent=cur.execute("SELECT name,location FROM schools ORDER BY id DESC LIMIT 8").fetchall()
        con.close()
        rows="".join(f"<tr><td>{escape(r['name'])}</td><td>{escape(r['location'] or '')}</td><td>Active</td></tr>" for r in recent)
        body=f"""<div class='page'><h1>Platform Overview</h1><div class='muted'>One control centre for every DaviSchool institution.</div>
<div class='grid'><div class='card'><div class='label'>Schools</div><div class='kpi'>{schools}</div></div><div class='card'><div class='label'>Users</div><div class='kpi'>{users}</div></div><div class='card'><div class='label'>Students</div><div class='kpi'>{students}</div></div><div class='card'><div class='label'>Fees received</div><div class='kpi'>KES {revenue:,.0f}</div></div></div>
<div class='section'><h2>🩺 Platform Health</h2>
<div class='card' style='margin-bottom:12px;background:#f0fdf4;border-color:#bbf7d0'>
  <div style='font-size:16px;font-weight:900;color:#166534'>🟢 Platform operating normally</div>
  <div class='muted' style='margin-top:6px'>DaviSchool is connected to its production data store and the platform overview is responding normally. School, user and student records are available to the platform.</div>
</div>
<div class='actions'>
  <div class='action'><span>🗄️</span>Database Health<small style='display:block;color:#64748b;margin-top:5px'>🟢 Connected</small></div>
  <div class='action'><span>🏫</span>School Services<small style='display:block;color:#64748b;margin-top:5px'>🟢 {schools} schools registered</small></div>
  <div class='action'><span>👥</span>User Access<small style='display:block;color:#64748b;margin-top:5px'>🟢 {users} users registered</small>
    <div style='margin-top:10px;text-align:left;border-top:1px solid #e2e8f0;padding-top:8px'>
      {''.join(f"<div style='padding:6px 0;border-bottom:1px solid #f1f5f9'><b>👤 {escape(str(u['full_name'] or 'User'))}</b><br><span style='font-size:12px;color:#64748b'>📧 {escape(str(u['email'] or ''))} · 🔐 {escape(str(u['role'] or ''))}</span></div>" for u in platform_users)}
    </div>
  </div>
  <div class='action'><span>🎓</span>Student Records<small style='display:block;color:#64748b;margin-top:5px'>🟢 {students} students recorded</small></div>
</div>
</div>
<div class='section'><h2>Institutions</h2><table><thead><tr><th>School</th><th>Location</th><th>Status</th></tr></thead><tbody>{rows or '<tr><td colspan=3>No schools yet</td></tr>'}</tbody></table></div></div>"""
    else:
        school_id=request.session.get("school_id",0)
        school=cur.execute("SELECT * FROM schools WHERE id=?",(school_id,)).fetchone()
        school_name=school["name"] if school else "School"
        if role=="teacher":
            body=f"""<div class='page'><h1>{escape(school_name)}</h1><div class='muted'>Teacher workspace</div>
<div class='grid' style='grid-template-columns:repeat(5,1fr)'>
<div class='card'><div class='label'>Students</div><div class='kpi'>🎓</div></div>
<div class='card'><div class='label'>Classes</div><div class='kpi'>🏫</div></div>
<a class='card' href='/app/academics/marks' style='text-decoration:none;color:inherit;cursor:pointer'><div class='label'>Record Marks</div><div class='kpi'>📝</div></a>
<div class='card'><div class='label'>Attendance</div><div class='kpi'>✓</div></div>
<div class='card'><div class='label'>Analysis</div><div class='kpi'>📊</div></div>
</div></div>"""
        else:
            s=cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?",(school_id,)).fetchone()["c"]
            t=cur.execute("SELECT COUNT(*) c FROM teachers WHERE school_id=?",(school_id,)).fetchone()["c"]
            c=cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?",(school_id,)).fetchone()["c"]
            fees=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM fee_payments WHERE school_id=?",(school_id,)).fetchone()["v"]
            body=f"""<div class='page'><h1>{escape(school_name)}</h1><div class='muted'>Your complete school operating centre.</div>
<div class='grid'><div class='card'><div class='label'>Students</div><div class='kpi'>{s}</div></div><div class='card'><div class='label'>Staff</div><div class='kpi'>{t}</div></div><div class='card'><div class='label'>Classes</div><div class='kpi'>{c}</div></div><div class='card'><div class='label'>Fees received</div><div class='kpi'>KES {fees:,.0f}</div></div></div>
<div class='section'><h2>Daily operations</h2><div class='actions'><div class='action'><span>🎓</span>Students</div><div class='action'><span>📝</span>Record Marks</div><div class='action'><span>✓</span>Attendance</div><div class='action'><span>💰</span>Finance</div><div class='action'><span>📄</span>Report Cards</div><div class='action'><span>📊</span>Analysis</div><div class='action'><span>📚</span>Accounting</div><div class='action'><span>👤</span>Users</div></div></div>
<div class='section'><h2>Administration</h2><div class='actions'><div class='action'><span>⚙</span>School Settings</div><div class='action'><span>🎓</span>Promotion / Transfer</div><div class='action'><span>🔐</span>Roles</div><div class='action'><span>🛡</span>Audit Trail</div><div class='action'><span>🌐</span>Portals</div></div></div></div></div>"""
    con.close()
    return HTMLResponse(_shell("DaviSchool",name,role,body))


def _grade(mark, out_of=100):
    try:
        p=(float(mark)/float(out_of))*100
    except Exception:
        p=0
    if p>=80: return "A"
    if p>=75: return "A-"
    if p>=70: return "B+"
    if p>=65: return "B"
    if p>=60: return "B-"
    if p>=55: return "C+"
    if p>=50: return "C"
    if p>=45: return "C-"
    if p>=40: return "D+"
    if p>=30: return "D"
    return "E"


def _ensure_student_history_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS student_class_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        from_class_id INTEGER,
        to_class_id INTEGER,
        changed_at TEXT,
        changed_by TEXT,
        reason TEXT
    )""")

def _ensure_report_card_fields(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS report_card_settings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        opening_date TEXT,
        closing_date TEXT,
        UNIQUE(school_id,exam_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS subject_performance_comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        comment TEXT,
        updated_at TEXT,
        UNIQUE(school_id,student_id,exam_id,subject_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS class_teacher_comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        comment TEXT,
        updated_at TEXT,
        UNIQUE(school_id,student_id,exam_id)
    )""")
    # Older production databases may already have these tables with only part
    # of the current schema. Upgrade them additively without destructive changes.
    for table, columns in (
        ("subject_performance_comments", [
            ("school_id","INTEGER"),("student_id","INTEGER"),("exam_id","INTEGER"),
            ("subject_id","INTEGER"),("comment","TEXT"),("updated_at","TEXT")
        ]),
        ("class_teacher_comments", [
            ("school_id","INTEGER"),("student_id","INTEGER"),("exam_id","INTEGER"),
            ("comment","TEXT"),("updated_at","TEXT")
        ]),
        ("report_card_settings", [
            ("school_id","INTEGER"),("exam_id","INTEGER"),
            ("opening_date","TEXT"),("closing_date","TEXT")
        ]),
    ):
        for col, definition in columns:
            try:
                cur.execute("SAVEPOINT davischool_report_field_column")
                cur.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, definition))
                cur.execute("RELEASE SAVEPOINT davischool_report_field_column")
            except Exception as exc:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT davischool_report_field_column")
                    cur.execute("RELEASE SAVEPOINT davischool_report_field_column")
                except Exception:
                    try:
                        cur.connection.rollback()
                    except Exception:
                        pass
                msg=str(exc).lower()
                if "already exists" not in msg and "duplicate column" not in msg:
                    print("DAVISCHOOL REPORT FIELD SCHEMA WARNING:",repr(exc),flush=True)

def _ensure_academic_locks_table(cur):
    """Ensure the lock table exists and safely upgrade legacy schemas.
    
    Existing production tables are upgraded additively only.  Each ALTER is
    isolated in a savepoint so a PostgreSQL "column already exists" error
    cannot abort the transaction used by marks finalization.
    """
    # Keep this DDL portable across Render PostgreSQL and local SQLite.
    # Do not add/alter the existing primary-key column: production databases may
    # already contain academic_locks with a legacy id definition.
    cur.execute("""CREATE TABLE IF NOT EXISTS academic_locks(
        school_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'finalized',
        finalized_by TEXT,
        finalized_at TEXT
    )""")
    for col, definition in [
        ("school_id","INTEGER"),
        ("exam_id","INTEGER"),
        ("class_id","INTEGER"),
        ("subject_id","INTEGER"),
        ("status","TEXT"),
        ("finalized_by","TEXT"),
        ("finalized_at","TEXT"),
    ]:
        try:
            cur.execute("SAVEPOINT davischool_academic_lock_column")
            cur.execute("ALTER TABLE academic_locks ADD COLUMN %s %s" % (col, definition))
            cur.execute("RELEASE SAVEPOINT davischool_academic_lock_column")
        except Exception as exc:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT davischool_academic_lock_column")
                cur.execute("RELEASE SAVEPOINT davischool_academic_lock_column")
            except Exception:
                # If the driver does not support savepoints, leave the
                # connection usable by rolling back the failed DDL.
                try:
                    cur.connection.rollback()
                except Exception:
                    pass
            # An existing column is expected; only unexpected schema errors
            # are useful in the Render log.
            msg=str(exc).lower()
            if "already exists" not in msg and "duplicate column" not in msg:
                print("DAVISCHOOL ACADEMIC LOCK SCHEMA WARNING:",repr(exc),flush=True)

def _academic_lock(cur, school_id, exam_id, class_id, subject_id):
    _ensure_academic_locks_table(cur)
    return cur.execute(
        "SELECT * FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=? LIMIT 1",
        (school_id, exam_id, class_id, subject_id)
    ).fetchone()

def _ensure_marks_correction_requests_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS marks_correction_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        teacher_id INTEGER,
        requested_by TEXT,
        requested_at TEXT,
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        reviewed_by TEXT,
        reviewed_at TEXT,
        review_note TEXT
    )""")

def _pending_marks_correction(cur, school_id, exam_id, class_id, subject_id, teacher_id=None):
    _ensure_marks_correction_requests_table(cur)
    params=[school_id,exam_id,class_id,subject_id]
    q="SELECT * FROM marks_correction_requests WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=? AND status='pending'"
    if teacher_id:
        q += " AND teacher_id=?"
        params.append(teacher_id)
    q += " ORDER BY id DESC LIMIT 1"
    return cur.execute(q,params).fetchone()

def _ensure_grading_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS subject_grading_rules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        subject_id INTEGER,
        min_mark REAL,
        max_mark REAL,
        grade TEXT,
        points REAL,
        performance_comment TEXT
    )""")
    # Additive compatibility for older production databases.
    # Use a savepoint for each ALTER so PostgreSQL does not leave the whole
    # request transaction aborted when the column already exists.
    for col, definition in [
        ("school_id","INTEGER"),
        ("subject_id","INTEGER"),
        ("min_mark","REAL"),
        ("max_mark","REAL"),
        ("grade","TEXT"),
        ("points","REAL"),
        ("performance_comment","TEXT"),
    ]:
        try:
            cur.execute("SAVEPOINT davischool_grading_column")
            cur.execute("ALTER TABLE subject_grading_rules ADD COLUMN %s %s" % (col, definition))
            cur.execute("RELEASE SAVEPOINT davischool_grading_column")
        except Exception:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT davischool_grading_column")
                cur.execute("RELEASE SAVEPOINT davischool_grading_column")
            except Exception:
                try:
                    cur.connection.rollback()
                except Exception:
                    try:
                        cur._connection.rollback()
                    except Exception:
                        pass

def _default_grade_points(mark):
    grade = _grade(mark)
    points = {
        "A": 12, "A-": 11, "B+": 10, "B": 9, "B-": 8,
        "C+": 7, "C": 6, "C-": 5, "D+": 4, "D": 3, "E": 1
    }.get(grade, 0)
    return grade, points

def _load_grading_rules(cur, school_id):
    """Load subject grading rules once per page instead of recreating/querying the table for every mark."""
    try:
        _ensure_grading_table(cur)
        rows = cur.execute(
            "SELECT subject_id,min_mark,max_mark,grade,points,performance_comment FROM subject_grading_rules WHERE school_id=? ORDER BY subject_id,min_mark DESC,id DESC",
            (school_id,)
        ).fetchall()
    except Exception as exc:
        print("DAVISCHOOL GRADING RULES LOAD FALLBACK:", repr(exc), flush=True)
        try:
            cur.connection.rollback()
        except Exception:
            try:
                cur._connection.rollback()
            except Exception:
                pass
        return {}
    rules = {}
    for row in rows:
        try:
            rules.setdefault(int(row["subject_id"]), []).append(row)
        except Exception:
            continue
    return rules

def _subject_grade_details(cur, school_id, subject_id, mark, grading_rules=None, out_of=100):
    try:
        value = float(mark)
    except Exception:
        return "—", 0, ""
    try:
        maximum = float(out_of or 100)
        percentage = (value / maximum) * 100 if maximum > 0 else value
    except Exception:
        percentage = value
    if grading_rules is not None:
        for rule in grading_rules.get(int(subject_id), []):
            try:
                low=float(rule["min_mark"]); high=float(rule["max_mark"])
                # Grading rules are normally entered on a 0-100 scale. Also
                # accept raw-mark ranges for compatibility with existing
                # configurations, so marks such as 40/50 correctly match 80-100.
                if low <= value <= high or low <= percentage <= high:
                    return str(rule["grade"]), float(rule["points"] or 0), str(rule["performance_comment"] or "")
            except Exception:
                continue
        # A subject with configured grading rules must never silently fall back
        # to the automatic A-E scale. If the mark is outside the configured
        # ranges, surface an ungraded state so the school can correct the rule.
        return "—", 0, ""
    try:
        _ensure_grading_table(cur)
        rule = cur.execute("""SELECT grade,points,performance_comment FROM subject_grading_rules
            WHERE school_id=? AND subject_id=? AND ? BETWEEN min_mark AND max_mark
            ORDER BY min_mark DESC, id DESC LIMIT 1""",(school_id, subject_id, value)).fetchone()
        if rule:
            return str(rule["grade"]), float(rule["points"] or 0), str(rule["performance_comment"] or "")
        # If this subject has custom rules but none matched, do not substitute
        # the global automatic grading scale.
        any_rule = cur.execute(
            "SELECT id FROM subject_grading_rules WHERE school_id=? AND subject_id=? LIMIT 1",
            (school_id, subject_id)
        ).fetchone()
        if any_rule:
            return "—", 0, ""
    except Exception as exc:
        print("DAVISCHOOL SUBJECT GRADING FALLBACK:", repr(exc), flush=True)
    grade, points = _default_grade_points(value)
    return grade, points, ""

def _subject_grade_points(cur, school_id, subject_id, mark, grading_rules=None):
    grade, points, _ = _subject_grade_details(cur, school_id, subject_id, mark, grading_rules)
    return grade, points

@router.get("/app/academics/grading", response_class=HTMLResponse)
def grading_setup(request: Request, subject_id: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/")
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can manage subject grading.", 403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to manage subject grading.", 403)
    # Keep schema compatibility/migration work isolated from the reads below.
    # Older PostgreSQL databases may need additive columns, and a failed DDL
    # attempt must never leave the grading page using an aborted transaction.
    con = _db()
    cur = con.cursor()
    try:
        _ensure_grading_table(cur)
        con.commit()
    except Exception as exc:
        print("DAVISCHOOL GRADING PAGE TABLE FALLBACK:", repr(exc), flush=True)
        try:
            con.rollback()
        except Exception:
            pass
    finally:
        try:
            con.close()
        except Exception:
            pass

    con = _db()
    cur = con.cursor()
    try:
        subjects = cur.execute(
            "SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)
        ).fetchall()
        subid = int(subject_id) if subject_id.isdigit() else 0
        if subid and not cur.execute(
            "SELECT id FROM subjects WHERE id=? AND school_id=?", (subid, sid)
        ).fetchone():
            subid = 0
        try:
            rules = cur.execute(
            """SELECT * FROM subject_grading_rules
               WHERE school_id=? AND subject_id=?
               ORDER BY min_mark DESC, max_mark DESC""",
            (sid, subid)
            ).fetchall() if subid else []
        except Exception as exc:
            print("DAVISCHOOL GRADING PAGE RULES FALLBACK:", repr(exc), flush=True)
            rules = []
    except Exception as exc:
        print("DAVISCHOOL GRADING PAGE READ FAILED:", repr(exc), flush=True)
        try:
            con.rollback()
        except Exception:
            pass
        subjects = []
        subid = int(subject_id) if subject_id.isdigit() else 0
        rules = []
    finally:
        try:
            con.close()
        except Exception:
            pass

    sopts = "".join(
        "<option value='%s' %s>%s</option>" % (
            s["id"],
            "selected" if int(s["id"]) == subid else "",
            escape(str(s["name"]))
        ) for s in subjects
    )
    rule_rows = "".join(
        "<tr><td>%.1f</td><td>%.1f</td><td><b>%s</b></td><td>%.1f</td><td>%s</td>"
        "<td style='white-space:nowrap'><a class='btnlink' href='/app/academics/grading/edit/%s?subject_id=%s'>✏️ Edit</a> "
        "<form method='post' action='/app/academics/grading/delete/%s?subject_id=%s' style='display:inline'><button class='btnlink' type='submit' onclick='return confirm(\"Delete this subject grading rule?\")'>Delete</button></form></td></tr>"
        % (float(r["min_mark"]), float(r["max_mark"]), escape(str(r["grade"])),
           float(r["points"] or 0), escape(str(r["performance_comment"] or "")), r["id"], subid, r["id"], subid)
        for r in rules
    )
    target_subject_options = "".join(
        "<label style='display:flex;align-items:center;gap:8px;padding:7px'><input class='grading-target' type='checkbox' name='target_subject_ids' value='%s'> %s</label>"
        % (s["id"], escape(str(s["name"])))
        for s in subjects if int(s["id"]) != subid
    )
    body = (
        "<div class='page'><h1>Subject Grading & Points</h1>"
        "<div class='muted'>Set the grade band and points for each subject. "
        "These rules are applied automatically when marks are entered and when class marksheets are generated.</div>"
        "<div class='card section'><form method='get' action='/app/academics/grading' "
        "style='display:grid;grid-template-columns:1fr auto;gap:10px'>"
        "<select name='subject_id' class='field' required><option value=''>Select subject</option>"
        + sopts +
        "</select><button class='btn'>Load Subject</button></form></div>"
        "<div class='card section'><h2>Add grading rule</h2>"
        "<form method='post' action='/app/academics/grading/add' "
        "style='display:grid;grid-template-columns:repeat(5,1fr);gap:10px'>"
        "<input type='hidden' name='subject_id' value='" + str(subid) + "'>"
        "<input name='min_mark' required type='number' min='0' max='100' step='0.01' placeholder='Minimum mark' class='field'>"
        "<input name='max_mark' required type='number' min='0' max='100' step='0.01' placeholder='Maximum mark' class='field'>"
        "<input name='grade' required placeholder='Grade e.g. A' class='field'>"
        "<input name='points' required type='number' min='0' step='0.01' placeholder='Points' class='field'>"
        "<div style='grid-column:1/-1'><textarea name='performance_comment' required rows='2' placeholder='Performance comment for this grade band' class='field'></textarea></div>"
        "<button class='btn'>Save Grade & Points</button></form></div>"
        "<div class='card section'><h2>Copy this grading scale to other subjects</h2>"
        "<div class='muted' style='margin-bottom:12px'>Copy all configured grade ranges, points and performance comments from the selected subject to one or more other subjects.</div>"
        "<form method='post' action='/app/academics/grading/copy' onsubmit='return confirmCopyGrading()'>"
        "<input type='hidden' name='source_subject_id' value='" + str(subid) + "'>"
        "<div style='display:grid;grid-template-columns:repeat(2,1fr);gap:8px;max-height:260px;overflow:auto;padding:8px;border:1px solid #e5e7eb;border-radius:9px'>"
        + target_subject_options +
        "</div>"
        "<label style='display:block;margin:12px 0;font-weight:700'><input type='checkbox' id='select-all-grading' onclick='document.querySelectorAll(\".grading-target\").forEach(function(x){x.checked=this.checked},this)'> Select all other subjects</label>"
        "<label style='display:block;margin:12px 0'><input type='checkbox' name='overwrite' value='1'> Replace existing grading scales on selected subjects</label>"
        "<button class='btn' type='submit'>📋 Copy Grading Scale</button></form></div>"
        "<div class='card section'><h2>Configured rules</h2>"
        "<table><thead><tr><th>Minimum</th><th>Maximum</th><th>Grade</th><th>Points</th><th>Performance Comment</th><th>Action</th></tr></thead>"
        "<tbody>" + (rule_rows or "<tr><td colspan='6'>No custom grading rules configured for this subject.</td></tr>") + "</tbody></table></div>"
        "<div class='card section'><b>Default fallback:</b> if a subject has no custom rule for a mark, DaviSchool uses the standard A–E scale and default points until you configure that subject.</div>"
        "</div><style>.field{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}.btn,.btnlink{padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}.btnlink{background:#fff;color:#172033}</style>"
    )
    return _school_page(request, "Subject Grading & Points", body)

@router.post("/app/academics/grading/add")
def grading_add(request: Request, subject_id: int = Form(...), min_mark: float = Form(...),
                max_mark: float = Form(...), grade: str = Form(...), points: float = Form(...), performance_comment: str = Form(...)):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can edit grading.", 403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit grading.", 403)
    if min_mark < 0 or max_mark > 100 or min_mark > max_mark or points < 0:
        return HTMLResponse("Invalid grading range. <a href='/app/academics/grading'>Back</a>", 400)
    if not grade.strip():
        return HTMLResponse("Grade is required. <a href='/app/academics/grading'>Back</a>", 400)
    if not performance_comment.strip():
        return HTMLResponse("Performance comment is required. <a href='/app/academics/grading'>Back</a>", 400)
    con = _db()
    cur = con.cursor()
    _ensure_grading_table(cur)
    if not cur.execute(
        "SELECT id FROM subjects WHERE id=? AND school_id=?", (subject_id, sid)
    ).fetchone():
        con.close()
        return HTMLResponse("Invalid subject. <a href='/app/academics/grading'>Back</a>", 400)
    overlap=cur.execute(
        """SELECT id FROM subject_grading_rules
           WHERE school_id=? AND subject_id=? AND min_mark<=? AND max_mark>=?
           LIMIT 1""",
        (sid,subject_id,max_mark,min_mark)
    ).fetchone()
    if overlap:
        con.close()
        return HTMLResponse("That grading range overlaps an existing range for this subject. <a href='/app/academics/grading'>Back</a>",400)
    cur.execute(
        """INSERT INTO subject_grading_rules
           (school_id,subject_id,min_mark,max_mark,grade,points,performance_comment)
           VALUES(?,?,?,?,?,?,?)""",
        (sid, subject_id, min_mark, max_mark, grade.strip(), points, performance_comment.strip())
    )
    _audit(cur, sid, request, "GRADING_RULE_CREATE",
           "Configured %s: %.1f-%.1f = %s / %.1f points" %
           (grade.strip(), min_mark, max_mark, grade.strip(), points))
    con.commit()
    con.close()
    return RedirectResponse("/app/academics/grading?subject_id=%s" % subject_id, 303)

@router.post("/app/academics/grading/copy")
async def grading_copy(request: Request):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can edit grading.", 403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to manage subject grading.", 403)
    form = await request.form()
    try:
        source_subject_id = int(str(form.get("source_subject_id") or "0"))
    except Exception:
        source_subject_id = 0
    target_ids = []
    for raw in form.getlist("target_subject_ids"):
        try:
            value = int(str(raw))
            if value > 0 and value not in target_ids:
                target_ids.append(value)
        except Exception:
            continue
    overwrite = str(form.get("overwrite") or "") == "1"
    if not source_subject_id or not target_ids:
        return HTMLResponse("Select a source subject and at least one target subject. <a href='/app/academics/grading'>Back</a>", 400)
    con = _db()
    cur = con.cursor()
    try:
        _ensure_grading_table(cur)
        source = cur.execute(
            "SELECT id,name FROM subjects WHERE id=? AND school_id=?",
            (source_subject_id, sid)
        ).fetchone()
        if not source:
            return HTMLResponse("Invalid source subject. <a href='/app/academics/grading'>Back</a>", 400)
        rules = cur.execute(
            """SELECT min_mark,max_mark,grade,points,performance_comment
               FROM subject_grading_rules
               WHERE school_id=? AND subject_id=?
               ORDER BY min_mark DESC,max_mark DESC,id DESC""",
            (sid, source_subject_id)
        ).fetchall()
        if not rules:
            return HTMLResponse("The selected subject has no grading rules to copy. Configure its grading scale first. <a href='/app/academics/grading?subject_id=%s'>Back</a>" % source_subject_id, 400)
        valid_targets = cur.execute(
            "SELECT id,name FROM subjects WHERE school_id=? AND id<>? ORDER BY name",
            (sid, source_subject_id)
        ).fetchall()
        valid_ids = {int(x["id"]) for x in valid_targets}
        target_ids = [x for x in target_ids if x in valid_ids]
        if not target_ids:
            return HTMLResponse("No valid target subjects were selected. <a href='/app/academics/grading?subject_id=%s'>Back</a>" % source_subject_id, 400)
        copied = 0
        skipped = 0
        for target_id in target_ids:
            existing = cur.execute(
                "SELECT id FROM subject_grading_rules WHERE school_id=? AND subject_id=? LIMIT 1",
                (sid, target_id)
            ).fetchone()
            if existing and not overwrite:
                skipped += 1
                continue
            cur.execute(
                "DELETE FROM subject_grading_rules WHERE school_id=? AND subject_id=?",
                (sid, target_id)
            )
            for rule in rules:
                cur.execute(
                    """INSERT INTO subject_grading_rules
                       (school_id,subject_id,min_mark,max_mark,grade,points,performance_comment)
                       VALUES(?,?,?,?,?,?,?)""",
                    (sid, target_id, rule["min_mark"], rule["max_mark"], rule["grade"],
                     rule["points"], rule["performance_comment"] or "")
                )
            copied += 1
        _audit(cur, sid, request, "GRADING_RULE_COPY",
               "Copied grading scale from subject %s to %s subject(s); skipped %s existing subject(s)" %
               (source_subject_id, copied, skipped))
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/app/academics/grading?subject_id=%s&copied=%s" % (source_subject_id, copied), 303)

@router.get("/app/academics/grading/edit/{rule_id}", response_class=HTMLResponse)
def grading_edit_page(request: Request, rule_id: int, subject_id: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can edit grading.", 403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit grading.", 403)
    con = _db()
    cur = con.cursor()
    try:
        _ensure_grading_table(cur)
        row = cur.execute(
            "SELECT * FROM subject_grading_rules WHERE id=? AND school_id=?",
            (rule_id, sid)
        ).fetchone()
        if not row:
            return HTMLResponse("Grading rule not found. <a href='/app/academics/grading'>Back</a>", 404)
        sid_for_form = int(row["subject_id"])
        subject = cur.execute(
            "SELECT id,name FROM subjects WHERE id=? AND school_id=?",
            (sid_for_form, sid)
        ).fetchone()
    finally:
        con.close()
    if not subject:
        return HTMLResponse("Subject not found. <a href='/app/academics/grading'>Back</a>", 404)
    body = (
        "<div class='page'><h1>Edit Grading Rule</h1>"
        "<div class='muted'>Update the minimum mark, maximum mark, grade, points, or performance comment for this subject.</div>"
        "<div class='card section'><div style='margin-bottom:12px;font-weight:800'>Subject: %s</div>"
        "<form method='post' action='/app/academics/grading/edit/%s' style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>"
        "<input type='hidden' name='subject_id' value='%s'>"
        "<input name='min_mark' required type='number' min='0' max='100' step='0.01' value='%s' placeholder='Minimum mark' class='field'>"
        "<input name='max_mark' required type='number' min='0' max='100' step='0.01' value='%s' placeholder='Maximum mark' class='field'>"
        "<input name='grade' required value='%s' placeholder='Grade e.g. A' class='field'>"
        "<input name='points' required type='number' min='0' step='0.01' value='%s' placeholder='Points' class='field'>"
        "<div style='grid-column:1/-1'><textarea name='performance_comment' required rows='3' placeholder='Performance comment for this grade band' class='field'>%s</textarea></div>"
        "<div style='grid-column:1/-1'><button class='btn' type='submit'>💾 Save Changes</button> "
        "<a class='btnlink' href='/app/academics/grading?subject_id=%s'>Cancel</a></div>"
        "</form></div></div>"
        "<style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}.btn,.btnlink{padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}.btnlink{background:#fff;color:#172033}</style></div>"
    ) % (
        escape(str(subject["name"])),
        rule_id,
        sid_for_form,
        escape(str(row["min_mark"])),
        escape(str(row["max_mark"])),
        escape(str(row["grade"] or "")),
        escape(str(row["points"] or 0)),
        escape(str(row["performance_comment"] or "")),
        sid_for_form
    )
    return _school_page(request, "Edit Grading Rule", body)

@router.post("/app/academics/grading/edit/{rule_id}")
def grading_edit(
    request: Request,
    rule_id: int,
    subject_id: int = Form(...),
    min_mark: float = Form(...),
    max_mark: float = Form(...),
    grade: str = Form(...),
    points: float = Form(...),
    performance_comment: str = Form(...)
):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can edit grading.", 403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit grading.", 403)
    grade_v = grade.strip()
    comment_v = performance_comment.strip()
    if min_mark < 0 or max_mark > 100 or min_mark > max_mark or points < 0:
        return HTMLResponse("Invalid grading range. <a href='/app/academics/grading?subject_id=%s'>Back</a>" % subject_id, 400)
    if not grade_v:
        return HTMLResponse("Grade is required. <a href='/app/academics/grading?subject_id=%s'>Back</a>" % subject_id, 400)
    if not comment_v:
        return HTMLResponse("Performance comment is required. <a href='/app/academics/grading?subject_id=%s'>Back</a>" % subject_id, 400)
    con = _db()
    cur = con.cursor()
    try:
        _ensure_grading_table(cur)
        row = cur.execute(
            "SELECT * FROM subject_grading_rules WHERE id=? AND school_id=?",
            (rule_id, sid)
        ).fetchone()
        if not row:
            con.close()
            return HTMLResponse("Grading rule not found. <a href='/app/academics/grading?subject_id=%s'>Back</a>" % subject_id, 404)
        if int(row["subject_id"]) != int(subject_id):
            con.close()
            return HTMLResponse("Invalid subject for this grading rule.", 400)
        subject = cur.execute(
            "SELECT id FROM subjects WHERE id=? AND school_id=?",
            (subject_id, sid)
        ).fetchone()
        if not subject:
            con.close()
            return HTMLResponse("Invalid subject. <a href='/app/academics/grading'>Back</a>", 400)
        overlap = cur.execute(
            """SELECT id FROM subject_grading_rules
               WHERE school_id=? AND subject_id=? AND id<>?
                 AND min_mark<=? AND max_mark>=?
               LIMIT 1""",
            (sid, subject_id, rule_id, max_mark, min_mark)
        ).fetchone()
        if overlap:
            con.close()
            return HTMLResponse(
                "That grading range overlaps another existing range for this subject. "
                "<a href='/app/academics/grading/edit/%s?subject_id=%s'>Back</a>" % (rule_id, subject_id),
                400
            )
        cur.execute(
            """UPDATE subject_grading_rules
               SET min_mark=?, max_mark=?, grade=?, points=?, performance_comment=?
               WHERE id=? AND school_id=? AND subject_id=?""",
            (min_mark, max_mark, grade_v, points, comment_v, rule_id, sid, subject_id)
        )
        _audit(
            cur, sid, request, "GRADING_RULE_EDIT",
            "Updated %s: %.1f-%.1f = %s / %.1f points" %
            (grade_v, min_mark, max_mark, grade_v, points)
        )
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/app/academics/grading?subject_id=%s" % subject_id, 303)

@router.post("/app/academics/grading/delete/{rule_id}")
def grading_delete(request: Request, rule_id: int, subject_id: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can edit grading.", 403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit grading.", 403)
    con = _db()
    cur = con.cursor()
    _ensure_grading_table(cur)
    row = cur.execute(
        "SELECT * FROM subject_grading_rules WHERE id=? AND school_id=?",
        (rule_id, sid)
    ).fetchone()
    if row:
        cur.execute("DELETE FROM subject_grading_rules WHERE id=? AND school_id=?", (rule_id, sid))
        _audit(cur, sid, request, "GRADING_RULE_DELETE",
               "Deleted grading rule %s" % rule_id)
    con.commit()
    con.close()
    return RedirectResponse("/app/academics/grading?subject_id=%s" % subject_id, 303)

def _ensure_teacher_mark_drafts_table(cur):
    """Create the private teacher draft store without touching published marks."""
    cur.execute("""CREATE TABLE IF NOT EXISTS teacher_mark_drafts (
        school_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        marks TEXT,
        comment TEXT,
        updated_at TEXT
    )""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_teacher_mark_draft
        ON teacher_mark_drafts(school_id,teacher_id,exam_id,class_id,subject_id,student_id)""")

def _ensure_marks_correction_requests_table(cur):
    """Create/upgrade the teacher mark-correction request store without deleting existing requests."""
    cur.execute("""CREATE TABLE IF NOT EXISTS marks_correction_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        teacher_id INTEGER,
        requested_by TEXT,
        requested_at TEXT,
        reason TEXT,
        status TEXT DEFAULT 'pending',
        reviewed_by TEXT,
        reviewed_at TEXT,
        review_note TEXT
    )""")
    # Older production databases may already have this table with a partial
    # schema. Add missing columns only; never recreate or delete the table.
    for col, definition in [
        ("school_id","INTEGER"),
        ("exam_id","INTEGER"),
        ("class_id","INTEGER"),
        ("subject_id","INTEGER"),
        ("teacher_id","INTEGER"),
        ("requested_by","TEXT"),
        ("requested_at","TEXT"),
        ("reason","TEXT"),
        ("status","TEXT DEFAULT 'pending'"),
        ("reviewed_by","TEXT"),
        ("reviewed_at","TEXT"),
        ("review_note","TEXT"),
    ]:
        try:
            cur.execute("SAVEPOINT davischool_correction_column")
            cur.execute("ALTER TABLE marks_correction_requests ADD COLUMN %s %s" % (col, definition))
            cur.execute("RELEASE SAVEPOINT davischool_correction_column")
        except Exception:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT davischool_correction_column")
                cur.execute("RELEASE SAVEPOINT davischool_correction_column")
            except Exception:
                pass
    try:
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_marks_correction_school
            ON marks_correction_requests(school_id,status,id)""")
    except Exception:
        pass

def _pending_marks_correction(cur, school_id, exam_id, class_id, subject_id, teacher_id):
    return cur.execute(
        """SELECT * FROM marks_correction_requests
           WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=?
             AND teacher_id=? AND status='pending'
           ORDER BY id DESC LIMIT 1""",
        (school_id, exam_id, class_id, subject_id, teacher_id)
    ).fetchone()

@router.get("/app/academics/marks", response_class=HTMLResponse)
def marks_page(request: Request, exam_id: str="", class_id: str="", subject_id: str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "marks.view"):
        return HTMLResponse("You do not have permission to view marks.", 403)
    con=_db();cur=con.cursor()
    try:
        exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        role=str(request.session.get("role",""))
        teacher_id=int(request.session.get("teacher_id") or 0) if role=="teacher" else 0
        if role=="teacher" and teacher_id:
            # Teachers must see only the classes/subjects actually allocated to
            # them. Keep the class+subject pairing together so the initial page
            # can never select a valid class with an unrelated subject.
            allocations=cur.execute("""SELECT DISTINCT class_id,subject_id
              FROM teacher_allocations
              WHERE school_id=? AND teacher_id=?
              ORDER BY class_id,subject_id""",(sid,teacher_id)).fetchall()
            class_ids=sorted({int(a["class_id"]) for a in allocations if a["class_id"] is not None})
            subject_ids=sorted({int(a["subject_id"]) for a in allocations if a["subject_id"] is not None})
            if class_ids:
                ph=",".join("?" for _ in class_ids)
                classes=cur.execute("SELECT * FROM classes WHERE school_id=? AND id IN ("+ph+") ORDER BY name,stream",[sid]+class_ids).fetchall()
            else:
                classes=[]
            if subject_ids:
                ph=",".join("?" for _ in subject_ids)
                subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? AND id IN ("+ph+") ORDER BY name",[sid]+subject_ids).fetchall()
            else:
                subjects=[]
        else:
            classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
            subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    except Exception as exc:
        print("DAVISCHOOL MARKS ACADEMIC LOOKUP FAILED:", repr(exc), flush=True)
        try: con.rollback()
        except Exception: pass
        con.close()
        return HTMLResponse("Academic data is still initializing. Please refresh this page in a few seconds.",503)
    selected_exam_ids=_parse_assessment_ids(exam_id)
    if not selected_exam_ids and exams:
        selected_exam_ids=[int(exams[0]["id"])]
    eid=selected_exam_ids[0] if selected_exam_ids else 0
    cid=int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
    subid=int(subject_id) if subject_id.isdigit() else (int(subjects[0]["id"]) if subjects else 0)
    # On the teacher landing page, choose the first allocated class/subject pair
    # rather than independently choosing the first class and first subject.
    if role=="teacher" and teacher_id:
        if allocations:
            first_pair=allocations[0]
            if not class_id and not subject_id:
                cid=int(first_pair["class_id"])
                subid=int(first_pair["subject_id"])
            elif not _teacher_class_authorized(cur, request, sid, cid, subid):
                cid=int(first_pair["class_id"])
                subid=int(first_pair["subject_id"])
    students=[]
    out_of=100.0
    subject_comments={}
    if eid and cid and subid and str(request.session.get("role","")) == "teacher" and not _teacher_class_authorized(cur, request, sid, cid, subid):
        con.close()
        return HTMLResponse("You are not allocated to this class and subject.", 403)
    if eid and cid and subid:
        # Load the learner list first. The fallback query deliberately reads
        # only student data, so a legacy marks schema can never prevent the
        # Marks Entry screen from opening.
        try:
            if role=="teacher":
                _ensure_teacher_mark_drafts_table(cur)
                students=cur.execute("""SELECT s.id,s.admission_no,s.name,
                    COALESCE(
                      (SELECT CAST(m2.marks AS TEXT) FROM marks m2
                       WHERE m2.student_id=s.id AND m2.exam_id=? AND m2.subject_id=?
                         AND m2.school_id=? AND (m2.class_id=? OR m2.class_id IS NULL)
                       ORDER BY m2.id DESC LIMIT 1),
                      (SELECT d2.marks FROM teacher_mark_drafts d2
                       WHERE d2.student_id=s.id AND d2.exam_id=? AND d2.subject_id=?
                         AND d2.class_id=? AND d2.school_id=? AND d2.teacher_id=?
                       ORDER BY d2.updated_at DESC LIMIT 1),
                      ''
                    ) marks
                  FROM students s
                  WHERE s.school_id=? AND s.class_id=? ORDER BY s.name""",
                  (eid,subid,sid,cid,eid,subid,cid,sid,teacher_id,sid,cid)).fetchall()
            else:
                students=cur.execute("""SELECT s.id,s.admission_no,s.name,
                    COALESCE((SELECT CAST(m2.marks AS TEXT)
                              FROM marks m2
                              WHERE m2.student_id=s.id AND m2.exam_id=? AND m2.subject_id=? AND m2.school_id=?
                              ORDER BY m2.id DESC LIMIT 1),'') marks
                  FROM students s
                  WHERE s.school_id=? AND s.class_id=? ORDER BY s.name""",(eid,subid,sid,sid,cid)).fetchall()
        except Exception as exc:
            print("DAVISCHOOL MARKS LOAD JOIN FALLBACK:", repr(exc), flush=True)
            try:
                con.rollback()
            except Exception:
                pass
            students=cur.execute("""SELECT id,admission_no,name,'' AS marks
              FROM students WHERE school_id=? AND class_id=? ORDER BY name""",(sid,cid)).fetchall()
        try:
            cfg=cur.execute("SELECT out_of FROM set_marks_config WHERE school_id=? AND exam_id=? AND subject_id=? ORDER BY id DESC LIMIT 1",(sid,eid,subid)).fetchone()
            out_of=float(cfg["out_of"] or 100) if cfg and cfg["out_of"] else 100.0
        except Exception as exc:
            print("DAVISCHOOL MARKS CONFIG FALLBACK:", repr(exc), flush=True)
            try:
                con.rollback()
            except Exception:
                pass
            out_of=100.0
        try:
            _ensure_report_card_fields(cur)
            student_ids = [int(strow["id"]) for strow in students]
            if student_ids:
                placeholders = ",".join(["?"] * len(student_ids))
                if role=="teacher":
                    _ensure_teacher_mark_drafts_table(cur)
                    comment_rows = cur.execute(
                        "SELECT student_id,comment FROM teacher_mark_drafts "
                        "WHERE school_id=? AND teacher_id=? AND exam_id=? AND class_id=? AND subject_id=? "
                        "AND student_id IN (" + placeholders + ")",
                        [sid, teacher_id, eid, cid, subid] + student_ids
                    ).fetchall()
                else:
                    comment_rows = cur.execute(
                        "SELECT student_id,comment FROM subject_performance_comments "
                        "WHERE school_id=? AND exam_id=? AND subject_id=? "
                        "AND student_id IN (" + placeholders + ")",
                        [sid, eid, subid] + student_ids
                    ).fetchall()
                subject_comments = {
                    int(row["student_id"]): (row["comment"] or "")
                    for row in comment_rows
                }
                # A blank mark means the learner did not have a mark for this
                # assessment. Never display a stale performance comment from
                # an earlier mark in that case; the field returns to its
                # normal empty/default state automatically.
                for strow in students:
                    if str(strow["marks"] or "").strip() == "":
                        subject_comments[int(strow["id"])] = ""
        except Exception as exc:
            print("DAVISCHOOL MARKS COMMENT READ FALLBACK:", repr(exc), flush=True)
            try:
                con.rollback()
            except Exception:
                pass
            subject_comments = {int(strow["id"]): "" for strow in students}
    grading_rules=[]
    if subid:
        try:
            _ensure_grading_table(cur)
            grading_rules=cur.execute("""SELECT * FROM subject_grading_rules
              WHERE school_id=? AND subject_id=? ORDER BY min_mark DESC,max_mark DESC""",(sid,subid)).fetchall()
        except Exception as exc:
            print("DAVISCHOOL GRADING RULES FALLBACK:", repr(exc), flush=True)
            try:
                con.rollback()
            except Exception:
                pass
            grading_rules=[]
    safe_rules=[]
    for r in grading_rules:
        try:
            safe_rules.append("[%s,%s,%r,%s,%r]"%(float(r["min_mark"]),float(r["max_mark"]),str(r["grade"] or "E"),float(r["points"] or 0),str(r["performance_comment"] or "")))
        except Exception:
            # Ignore an incomplete legacy grading row rather than breaking
            # the entire Marks Entry screen.
            continue
    js_rules="["+",".join(safe_rules)+"]"
    eopts="".join("<option value='%s' %s>%s (%s)</option>"%(e["id"],"selected" if int(e["id"])==eid else "",escape(str(e["name"])),escape(str(e["year"] or ""))) for e in exams)
    if role=="teacher":
        allowed_pairs={(int(a["class_id"]),int(a["subject_id"])) for a in allocations if a["class_id"] is not None and a["subject_id"] is not None}
        copts="".join("<option value='%s' %s>%s %s</option>"%(c["id"],"selected" if int(c["id"])==cid else "",escape(str(c["name"])),escape(str(c["stream"] or ""))) for c in classes if any(pair[0]==int(c["id"]) for pair in allowed_pairs))
        sopts="".join("<option value='%s' data-class-ids='%s' %s>%s</option>"%(s["id"],",".join(str(pair[0]) for pair in sorted(allowed_pairs) if pair[1]==int(s["id"])),"selected" if int(s["id"])==subid else "",escape(str(s["name"]))) for s in subjects if any(pair[1]==int(s["id"]) for pair in allowed_pairs))
    else:
        copts="".join("<option value='%s' %s>%s %s</option>"%(c["id"],"selected" if int(c["id"])==cid else "",escape(str(c["name"])),escape(str(c["stream"] or ""))) for c in classes)
        sopts="".join("<option value='%s' %s>%s</option>"%(s["id"],"selected" if int(s["id"])==subid else "",escape(str(s["name"]))) for s in subjects)
    locked = False
    if eid and cid and subid:
        try:
            _ensure_academic_locks_table(cur)
            locked = bool(_academic_lock(cur,sid,eid,cid,subid))
        except Exception as exc:
            # A legacy lock table must never make existing marks inaccessible.
            print("DAVISCHOOL MARKS LOCK FALLBACK:", repr(exc), flush=True)
            locked = False
    role = str(request.session.get("role",""))
    teacher_id = request.session.get("teacher_id") if role == "teacher" else None
    pending_correction = None
    if eid and cid and subid:
        try:
            pending_correction = _pending_marks_correction(cur, sid, eid, cid, subid, teacher_id if role == "teacher" else None)
        except Exception as exc:
            print("DAVISCHOOL MARKS CORRECTION READ FALLBACK:", repr(exc), flush=True)
            pending_correction = None
    rule_note="Custom grading: %s rule(s)"%len(grading_rules) if grading_rules else "Using default A-E grading until you configure this subject."
    grading_link="" if role=="teacher" else "<a href='/app/academics/grading?subject_id=%s' style='margin-left:10px;font-weight:800'>Set / Edit Grade & Points</a>"%subid
    # Teacher forms default to PRIVATE DRAFT saving. Submit & Lock explicitly
    # overrides the form action to publish and lock the marks. School Admin keeps
    # the normal published/main marks workflow unchanged.
    # Always derive the active tab from the middleware as a fallback. After
    # returning from Marks Corrections, a form submission must never fall back
    # to the legacy generic session cookie.
    tab_id = str(request.query_params.get("ds_tab") or request.scope.get("davischool_tab_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", tab_id):
        tab_id = ""
    tab_q = ("?ds_tab=" + quote(tab_id, safe="")) if tab_id else ""
    form_action = "/app/academics/marks/save-draft" + tab_q if role == "teacher" else "/app/academics/marks/save" + tab_q
    draft_action = ""
    lock_action = ""
    if locked:
        if role == "school_admin":
            mark_actions = "<form method='post' action='/app/academics/marks/unfinalize" + tab_q + "' style='display:inline'><input type='hidden' name='exam_id' value='%s'><input type='hidden' name='class_id' value='%s'><input type='hidden' name='subject_id' value='%s'><button class='btn' type='submit'>🔓 Reopen Marks</button></form> <a class='btnlink' href='/app/academics/marks-corrections'>Correction Requests</a>"%(eid,cid,subid)
        elif role == "teacher":
            # Once the School Admin finalizes these marks, the teacher side is
            # strictly read-only. Correction workflow is intentionally disabled
            # here and can be restored as a separate feature later.
            mark_actions = "<div class='muted' style='font-weight:800'>🔒 Marks are FINALIZED and LOCKED. No editing is available on the Teacher side.</div>"
        else:
            mark_actions = ""
    else:
        if role=="teacher":
            mark_actions = ""
            draft_action = "<button class='btn' type='submit' formaction='" + form_action + "' formmethod='post'>💾 Save Draft</button>" if students else ""
            lock_action = ""
        else:
            # School Admin uses the published/main marks workflow. This branch
            # is intentionally isolated from the teacher draft workflow.
            mark_actions = ("<button class='btn' type='submit' formaction='" + form_action + "' formmethod='post'>💾 Save Marks</button>") if students else ""
            # Submit & Lock has been removed from the School Admin Record Marks UI.
            # Keep the underlying finalize route untouched so existing data/state is preserved.
            lock_action = ""
            draft_action = ""
    # Keep correction/reopen forms outside the main marks form. Nested HTML forms are invalid and can cause the browser to submit the wrong action.
    form_actions = (draft_action if role == "teacher" else (mark_actions if not locked else ""))
    outside_actions = mark_actions if locked else ""
    rows=""
    for x in students:
        mark=x["marks"]
        if mark=="":
            grade,points="—","—"
        else:
            try:
                grade,points,default_comment=_subject_grade_details(cur,sid,subid,mark,{subid:grading_rules},out_of)
                if default_comment:
                    subject_comments[int(x["id"])]=default_comment
                else:
                    subject_comments[int(x["id"])]=""
            except Exception as exc:
                print("DAVISCHOOL MARKS GRADE FALLBACK:", repr(exc), flush=True)
                grade,points=_default_grade_points(float(mark))
        # Teacher marks remain editable while the assessment is open.
        # Only an actual finalized lock disables the mark field.
        mark_disabled = "disabled" if locked else ""
        edit_control=""
        rows+="<tr id='student-%s'><td>%s</td><td><b>%s</b></td><td class='markcell'><div class='markbox'><input id='mark-%s' name='mark_%s' value='%s' type='text' inputmode='decimal' pattern='[0-9]+(\\.[0-9])?' data-min='0' data-max='%s' class='markinput' %s>%s</div></td><td class='gradecell'>%s</td><td class='pointcell'>%s</td><td class='commentcell'><div class='comment-wrap'><input name='comment_%s' value='%s' class='field commentinput' placeholder='Performance comment' disabled></div></td></tr>"%(x["id"],escape(str(x["admission_no"] or "")),escape(str(x["name"] or "")),x["id"],x["id"],escape("" if mark=="" else "%.1f"%float(mark)),out_of,mark_disabled,edit_control,escape(str(grade)),points if points=="—" else "%.1f"%float(points),x["id"],escape(str(subject_comments.get(int(x["id"]), ""))))
    con.close()
    body=(
      "<div class='page'><h1>Marks Entry</h1><div class='muted'>Enter marks and DaviSchool will apply the subject's configured grade and point rules automatically.</div>"
      "<div class='card section'><form method='get' action='/app/academics/marks" + tab_q + "' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>"
      "<select name='exam_id' class='field'><option value=''>Select examination</option>"+eopts+"</select>"
      "<select name='class_id' class='field'><option value=''>Select class</option>"+copts+"</select>"
      "<select name='subject_id' class='field'><option value=''>Select subject</option>"+sopts+"</select>"
      "<input type='hidden' name='ds_tab' value='" + escape(tab_id) + "'><button class='btn' type='submit'>Load Students</button></form>"
      "<div class='card section marks-entry'><div style='margin-bottom:10px;padding:10px;background:{bg};border-radius:9px;font-weight:800'>{status}</div>"
      "<form id='marksEntryForm' method='post' action='{action}' data-save-action='{action}'>"
      "<input type='hidden' name='exam_id' value='{eid}'><input type='hidden' name='class_id' value='{cid}'><input type='hidden' name='subject_id' value='{subid}'>"
      "<div class='marks-table-scroll'><table class='marks-table'><colgroup><col class='col-admission'><col class='col-student'><col class='col-mark'><col class='col-grade'><col class='col-points'><col class='col-comment'></colgroup><thead><tr><th>Admission</th><th>Student</th><th>Mark / {out_of}</th><th>Grade</th><th>Points</th><th>Performance Comment</th></tr></thead><tbody>{rows}</tbody></table></div>{form_actions}</form><div style='margin-top:10px'>{outside_actions}</div></div></div>".format(
          bg=("#fee2e2" if locked else "#f0fdf4"),
          status=("🔒 Marks are FINALIZED and locked." if locked else "🟢 Marks are open for editing."),
          action=form_action,eid=eid,cid=cid,subid=subid,out_of=out_of,
          rows=rows or "<tr><td colspan='7'>Select an examination, class and subject, then load students.</td></tr>",
          form_actions=form_actions,outside_actions=outside_actions)+
      "<style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;box-sizing:border-box}.marks-table-scroll{width:100%%;max-width:100%%;overflow-x:auto;overflow-y:visible;-webkit-overflow-scrolling:touch;touch-action:auto;overscroll-behavior-x:contain;border:1px solid #e5e7eb;border-radius:10px}.marks-table{width:850px;min-width:850px;table-layout:fixed;border-collapse:collapse}.marks-table th,.marks-table td{vertical-align:middle;text-align:left;padding:8px 7px;box-sizing:border-box}.marks-table th{white-space:nowrap}.marks-table .col-admission{width:8%%}.marks-table .col-student{width:18%%}.marks-table .col-mark{width:11%%}.marks-table .col-grade{width:6%%}.marks-table .col-points{width:6%%}.marks-table .col-comment{width:49%%}.marks-table td:nth-child(1),.marks-table td:nth-child(2),.marks-table td:nth-child(4),.marks-table td:nth-child(5){white-space:nowrap}.markcell,.gradecell,.pointcell,.commentcell{height:1px}.marks-table th:last-child,.marks-table td:last-child{position:sticky;right:0;background:#fff;z-index:20;box-shadow:-4px 0 8px rgba(0,0,0,.10)}.marks-table th:last-child{z-index:21}.marks-table-scroll{position:relative;overflow-x:scroll;isolation:isolate}.markbox{position:relative;width:100%%;max-width:110px}.markinput{width:100%%;padding:8px;border:1px solid #dbe2ea;border-radius:8px;box-sizing:border-box}.commentinput{width:100%%;max-width:212px;min-width:0;box-sizing:border-box;height:32px;padding:6px 8px;font-size:12px}.btn,.editbtn{padding:8px 11px;border:0;border-radius:8px;background:#111827;color:#fff;font-weight:800;cursor:pointer;margin-right:5px}@media(max-width:700px){.marks-table-scroll{overflow-x:auto;overflow-y:visible;touch-action:auto;-webkit-overflow-scrolling:touch}.marks-table{width:850px;min-width:850px}.marks-table th,.marks-table td{padding:8px 10px}}</style>"
      "<script>(function(){var cs=document.querySelector('select[name=\\\"class_id\\\"]'),ss=document.querySelector('select[name=\\\"subject_id\\\"]');if(cs&&ss){function f(){var cid=cs.value,first=null;Array.prototype.forEach.call(ss.options,function(o){if(!o.value)return;var rawIds=o.getAttribute('data-class-ids');if(rawIds===null){o.hidden=false;if(!first)first=o.value;return;}var ids=rawIds.split(',');o.hidden=ids.indexOf(cid)<0;if(!o.hidden&&!first)first=o.value;});var cur=ss.options[ss.selectedIndex];if(cur&&cur.hidden&&first)ss.value=first;}cs.addEventListener('change',f);f();}})();var gradingRules=%s;document.querySelectorAll('.markinput').forEach(function(el){el.setAttribute('inputmode','decimal');el.setAttribute('pattern','[0-9]+(\\.[0-9])?');el.addEventListener('change',function(){if(el.value!==''&&!isNaN(parseFloat(el.value)))el.value=parseFloat(el.value).toFixed(1);});el.addEventListener('blur',function(){if(el.value!==''&&!isNaN(parseFloat(el.value)))el.value=parseFloat(el.value).toFixed(1);});el.addEventListener('input',function(){var row=el.closest('tr'),mark=parseFloat(el.value),commentCell=row.querySelector('.commentinput');if(isNaN(mark)){row.querySelector('.gradecell').textContent='—';row.querySelector('.pointcell').textContent='—';if(commentCell)commentCell.value='';return;}var grade='—',points='—',comment='';var pct=(mark/out_of)*100;for(var i=0;i<gradingRules.length;i++){if((mark>=gradingRules[i][0]&&mark<=gradingRules[i][1])||(pct>=gradingRules[i][0]&&pct<=gradingRules[i][1])){grade=gradingRules[i][2];points=gradingRules[i][3];comment=gradingRules[i][4]||'';break;}}if(gradingRules.length===0){if(mark>=80){grade='A';points=12}else if(mark>=75){grade='A-';points=11}else if(mark>=70){grade='B+';points=10}else if(mark>=65){grade='B';points=9}else if(mark>=60){grade='B-';points=8}else if(mark>=55){grade='C+';points=7}else if(mark>=50){grade='C';points=6}else if(mark>=45){grade='C-';points=5}else if(mark>=40){grade='D+';points=4}else if(mark>=30){grade='D';points=3}}row.querySelector('.gradecell').textContent=grade;row.querySelector('.pointcell').textContent=points;if(commentCell && !commentCell.dataset.manual)commentCell.value=comment;});});document.querySelectorAll('.commentinput').forEach(function(el){el.addEventListener('input',function(){el.dataset.manual='1';});});document.querySelectorAll('button,a,form').forEach(function(el){var t=(el.textContent||'').trim().toLowerCase(),h=(el.getAttribute('href')||'')+(el.getAttribute('action')||'')+(el.getAttribute('formaction')||'');if(t.includes('delete')||t.includes('🗑')||h.includes('/marks/delete')){var node=el.closest('form')||el;if(node&&node!==document.body)node.remove();}});document.querySelectorAll('.marks-entry button,.marks-entry a,.marks-entry form').forEach(function(el){var t=(el.textContent||'').trim().toLowerCase(),h=(el.getAttribute('href')||'')+(el.getAttribute('action')||'')+(el.getAttribute('formaction')||'');if(t.includes('delete')||t.includes('remove')||t.includes('🗑')||h.includes('/marks/delete')){var node=el.closest('form')||el;if(node&&node!==document.body)node.remove();}});</script>"%js_rules
    )
    return _school_page(request,"Marks Entry",body)

@router.post("/app/academics/marks/save-draft")
async def marks_save_draft(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "teacher":
        return HTMLResponse("Draft saving is available only to teachers.",403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to save marks.",403)
    con=_db();cur=con.cursor()
    try:
        _ensure_teacher_mark_drafts_table(cur)
        teacher_id=int(request.session.get("teacher_id") or 0)
        if not teacher_id or not _teacher_class_authorized(cur, request, sid, class_id, subject_id):
            con.close(); return HTMLResponse("You are not allocated to this class and subject.",403)
        valid=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
        if not valid:
            con.close(); return HTMLResponse("Invalid academic selection. <a href='/app/academics/marks'>Back</a>",400)
        if _academic_lock(cur,sid,exam_id,class_id,subject_id):
            con.close(); return HTMLResponse("These marks are already submitted and locked. <a href='/app/academics/marks'>Back</a>",403)
        form=await request.form()
        now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        students=cur.execute("SELECT id FROM students WHERE school_id=? AND class_id=?",(sid,class_id)).fetchall()
        cfg=cur.execute("SELECT out_of FROM set_marks_config WHERE school_id=? AND exam_id=? AND subject_id=? ORDER BY id DESC LIMIT 1",(sid,exam_id,subject_id)).fetchone()
        out_of=float(cfg["out_of"] or 100) if cfg and cfg["out_of"] else 100.0
        for st in students:
            student_id=int(st["id"])
            raw=form.get(f"mark_{student_id}")
            comment=str(form.get(f"comment_{student_id}") or "").strip()
            draft_key=(sid,teacher_id,exam_id,class_id,subject_id,student_id)
            existing_drafts=cur.execute(
                """SELECT 1 FROM teacher_mark_drafts
                   WHERE school_id=? AND teacher_id=? AND exam_id=? AND class_id=?
                     AND subject_id=? AND student_id=?""",
                draft_key
            ).fetchone()

            if raw is None or str(raw).strip()=="":
                # A blank saved by the teacher is also a blank in the shared
                # marks record, so the School Admin sees the same state.
                cur.execute(
                    """DELETE FROM marks
                       WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=? AND class_id=?""",
                    (sid,student_id,subject_id,exam_id,class_id)
                )
                if existing_drafts:
                    cur.execute(
                        """UPDATE teacher_mark_drafts SET marks='',comment='',updated_at=?
                           WHERE school_id=? AND teacher_id=? AND exam_id=? AND class_id=?
                             AND subject_id=? AND student_id=?""",
                        (now,)+draft_key
                    )
                else:
                    cur.execute(
                        """INSERT INTO teacher_mark_drafts
                           (school_id,teacher_id,exam_id,class_id,subject_id,student_id,marks,comment,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (sid,teacher_id,exam_id,class_id,subject_id,student_id,'','',now)
                    )
                try:
                    cur.execute(
                        """DELETE FROM subject_performance_comments
                           WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=?""",
                        (sid,student_id,exam_id,subject_id)
                    )
                except Exception:
                    pass
                continue

            try:
                mark=float(raw)
            except Exception:
                continue
            if mark<0 or mark>out_of:
                continue
            mark_value=int(mark) if mark.is_integer() else mark

            # Shared published marks record: both School Admin and Teacher
            # pages read this same value.
            exam=cur.execute("SELECT year,term FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
            old_rows=cur.execute(
                "SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=?",
                (sid,student_id,subject_id,exam_id)
            ).fetchall()
            if old_rows:
                for old in old_rows:
                    cur.execute(
                        "UPDATE marks SET marks=?,class_id=?,year=?,term=? WHERE id=? AND school_id=?",
                        (mark_value,class_id,exam["year"],exam["term"],old["id"],sid)
                    )
            else:
                cur.execute(
                    "INSERT INTO marks(school_id,student_id,subject_id,exam_id,class_id,marks,year,term) VALUES(?,?,?,?,?,?,?,?)",
                    (sid,student_id,subject_id,exam_id,class_id,mark_value,exam["year"],exam["term"])
                )

            # Keep the teacher draft mirror so the teacher can resume after
            # logging out, but it is no longer a separate source of truth.
            if existing_drafts:
                cur.execute(
                    """UPDATE teacher_mark_drafts SET marks=?,comment=?,updated_at=?
                       WHERE school_id=? AND teacher_id=? AND exam_id=? AND class_id=?
                         AND subject_id=? AND student_id=?""",
                    (str(mark_value),comment,now)+draft_key
                )
            else:
                cur.execute(
                    """INSERT INTO teacher_mark_drafts
                       (school_id,teacher_id,exam_id,class_id,subject_id,student_id,marks,comment,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (sid,teacher_id,exam_id,class_id,subject_id,student_id,str(mark_value),comment,now)
                )

            # Refresh the shared performance comment from the current grading
            # rule so both sides show the same comment.
            try:
                grading_rules=_load_grading_rules(cur,sid)
                _,_,shared_comment=_subject_grade_details(cur,sid,subject_id,mark,grading_rules,out_of)
            except Exception:
                shared_comment=""
            now_comment=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
            existing_comments=cur.execute(
                "SELECT id FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=?",
                (sid,student_id,exam_id,subject_id)
            ).fetchall()
            if existing_comments:
                for ec in existing_comments:
                    cur.execute(
                        "UPDATE subject_performance_comments SET comment=?,updated_at=? WHERE id=? AND school_id=?",
                        (shared_comment,now_comment,ec["id"],sid)
                    )
            else:
                cur.execute(
                    "INSERT INTO subject_performance_comments(school_id,student_id,exam_id,subject_id,comment,updated_at) VALUES(?,?,?,?,?,?)",
                    (sid,student_id,exam_id,subject_id,shared_comment,now_comment)
                )
        # Draft data must be saved even if the optional audit trail has a schema problem.
        # Keep an audit-table/schema failure from aborting the marks transaction.
        # PostgreSQL marks the whole transaction failed after a statement error,
        # so merely catching the exception is not enough; roll back to a savepoint.
        try:
            cur.execute("SAVEPOINT davischool_marks_draft_audit")
            try:
                _audit(cur,sid,request,"MARKS_DRAFT_SAVE",f"Saved private draft marks for exam {exam_id}, class {class_id}, subject {subject_id}")
                cur.execute("RELEASE SAVEPOINT davischool_marks_draft_audit")
            except Exception as audit_exc:
                print("DAVISCHOOL MARKS DRAFT AUDIT WARNING:",repr(audit_exc),flush=True)
                try: cur.execute("ROLLBACK TO SAVEPOINT davischool_marks_draft_audit")
                except Exception: pass
                try: cur.execute("RELEASE SAVEPOINT davischool_marks_draft_audit")
                except Exception: pass
        except Exception as audit_sp_exc:
            print("DAVISCHOOL MARKS DRAFT AUDIT SAVEPOINT WARNING:",repr(audit_sp_exc),flush=True)
        con.commit()
    except Exception as exc:
        try: con.rollback()
        except Exception: pass
        print("DAVISCHOOL MARKS DRAFT SAVE ERROR:",repr(exc),flush=True)
        return HTMLResponse("Save Draft failed: %s" % escape(str(exc)) , 500)
    finally:
        try: con.close()
        except Exception: pass
    tab_value=str(request.query_params.get("ds_tab") or "").strip()
    tab_suffix=("&ds_tab="+quote(tab_value,safe="")) if tab_value else ""
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}&saved_at={int(datetime.now(ZoneInfo('Africa/Nairobi')).timestamp())}"+tab_suffix,303,headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0"})

@router.post("/app/academics/marks/save")
async def marks_save(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit marks.", 403)
    form=await request.form()
    con=_db();cur=con.cursor()
    if not _teacher_class_authorized(cur, request, sid, class_id, subject_id):
        con.close()
        return HTMLResponse("You are not allocated to this class and subject.", 403)
    valid=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not valid: con.close(); return HTMLResponse("Invalid academic selection. <a href='/app/academics/marks'>Back</a>",400)
    if _academic_lock(cur,sid,exam_id,class_id,subject_id):
        con.close()
        return HTMLResponse("These marks are finalized and locked. <a href='/app/academics/marks'>Back</a>",403)
    exam=cur.execute("SELECT year,term FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
    cfg=cur.execute("SELECT out_of FROM set_marks_config WHERE school_id=? AND exam_id=? AND subject_id=? ORDER BY id DESC LIMIT 1",(sid,exam_id,subject_id)).fetchone()
    out_of=float(cfg["out_of"] or 100) if cfg and cfg["out_of"] else 100.0
    students=cur.execute("SELECT id FROM students WHERE school_id=? AND class_id=?",(sid,class_id)).fetchall()
    # Prepare the performance-comment table once per save request, not once per
    # student. Re-running schema checks inside the student loop makes Save Marks
    # increasingly slow as the class size grows.
    _ensure_report_card_fields(cur)
    try:
        grading_rules=_load_grading_rules(cur,sid)
    except Exception as exc:
        print("DAVISCHOOL MARKS SAVE GRADING FALLBACK:",repr(exc),flush=True)
        grading_rules={}
    for st in students:
        raw=form.get(f"mark_{st['id']}")
        if raw is None or str(raw).strip()=="":
            # Blank means the mark was intentionally cleared. Remove only the
            # published row for this exact school/student/exam/subject/class.
            cur.execute(
                """DELETE FROM marks
                   WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=? AND class_id=?""",
                (sid,st["id"],subject_id,exam_id,class_id)
            )
            # A blank mark also means there is no performance comment for this
            # student/subject/assessment. Otherwise the old comment remains in
            # subject_performance_comments and is shown again even though the
            # mark has been cleared.
            try:
                cur.execute(
                    """DELETE FROM subject_performance_comments
                       WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=?""",
                    (sid,st["id"],exam_id,subject_id)
                )
            except Exception as exc:
                print("DAVISCHOOL BLANK MARK COMMENT CLEAR WARNING:",repr(exc),flush=True)
            continue
        try: mark=float(raw); mark_int=int(mark) if mark.is_integer() else mark
        except Exception: continue
        if mark<0 or mark>out_of: continue
        old_rows=cur.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=?",(sid,st["id"],subject_id,exam_id)).fetchall()
        if old_rows:
            # Update all legacy duplicate rows so an older duplicate cannot
            # make a newly saved mark appear to revert on the next page load.
            for old in old_rows:
                cur.execute("UPDATE marks SET marks=?,class_id=?,year=?,term=? WHERE id=? AND school_id=?",(mark_int,class_id,exam["year"],exam["term"],old["id"],sid))
        else:
            cur.execute("INSERT INTO marks(school_id,student_id,subject_id,exam_id,class_id,marks,year,term) VALUES(?,?,?,?,?,?,?,?)",(sid,st["id"],subject_id,exam_id,class_id,mark_int,exam["year"],exam["term"]))
        # Performance comments are controlled by the subject grading rules.
        # Recalculate them on every mark save so changing a student's mark also
        # replaces any stale comment from the previous grade band.
        now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        try:
            _, _, comment = _subject_grade_details(cur,sid,subject_id,mark,grading_rules,out_of)
        except Exception as exc:
            print("DAVISCHOOL MARKS COMMENT DEFAULT FALLBACK:",repr(exc),flush=True)
            comment=""
        existing_comments=cur.execute(
            "SELECT id FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=?",
            (sid,st["id"],exam_id,subject_id)
        ).fetchall()
        if existing_comments:
            for existing_comment in existing_comments:
                cur.execute(
                    "UPDATE subject_performance_comments SET comment=?,updated_at=? WHERE id=? AND school_id=?",
                    (comment,now,existing_comment["id"],sid)
                )
        else:
            cur.execute(
                "INSERT INTO subject_performance_comments(school_id,student_id,exam_id,subject_id,comment,updated_at) VALUES(?,?,?,?,?,?)",
                (sid,st["id"],exam_id,subject_id,comment,now)
            )
    # Saving marks must not be rolled back by an optional audit-trail
    # schema problem. The marks themselves are the primary transaction.
    # Audit logging is optional and must never invalidate the actual marks save.
    # A caught PostgreSQL statement error otherwise leaves the transaction aborted.
    try:
        cur.execute("SAVEPOINT davischool_marks_audit")
        try:
            _audit(cur,sid,request,"MARKS_SAVE",f"Saved marks for exam {exam_id}, class {class_id}, subject {subject_id}")
            cur.execute("RELEASE SAVEPOINT davischool_marks_audit")
        except Exception as audit_exc:
            print("DAVISCHOOL MARKS SAVE AUDIT WARNING:",repr(audit_exc),flush=True)
            try: cur.execute("ROLLBACK TO SAVEPOINT davischool_marks_audit")
            except Exception: pass
            try: cur.execute("RELEASE SAVEPOINT davischool_marks_audit")
            except Exception: pass
    except Exception as audit_sp_exc:
        print("DAVISCHOOL MARKS SAVE AUDIT SAVEPOINT WARNING:",repr(audit_sp_exc),flush=True)
    try:
        con.commit()
    except Exception as save_exc:
        try: con.rollback()
        except Exception: pass
        print("DAVISCHOOL MARKS SAVE COMMIT ERROR:",repr(save_exc),flush=True)
        try: con.close()
        except Exception: pass
        return HTMLResponse("Save Marks failed: %s" % escape(str(save_exc)),500)
    con.close()
    # Render the locked marks page directly in this authenticated request.
    # This avoids a second protected request/redirect, which can otherwise
    # lose the tab-specific session cookie and send the admin to login.
    return marks_page(request, exam_id=str(exam_id), class_id=str(class_id), subject_id=str(subject_id))

# Marks deletion is intentionally disabled. Published and teacher draft marks must not be deletable from the Record Marks workflow.\n\n@router.post("/app/academics/marks/finalize")
async def finalize_marks(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:
        print("DAVISCHOOL FINALIZE AUTH FAILED: tab=%s cookies=%s session_keys=%s role=%r email_present=%s" % (
            request.scope.get("davischool_tab_id",""),
            sorted([k for k in request.cookies.keys() if k.startswith("davischool_session_")]),
            sorted(list(request.session.keys())),
            request.session.get("role"),
            bool(request.session.get("email"))
        ), flush=True)
        return RedirectResponse("/",303)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to finalize marks.",403)
    con=_db();cur=con.cursor();_ensure_academic_locks_table(cur)
    valid=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not valid:
        con.close(); return HTMLResponse("Invalid academic selection. <a href='/app/academics/marks'>Back</a>",400)
    if not _teacher_class_authorized(cur, request, sid, class_id, subject_id):
        con.close(); return HTMLResponse("You are not allocated to this class and subject.",403)
    existing_lock_row = _academic_lock(cur,sid,exam_id,class_id,subject_id)
    # Only an already-finalized record should block finalization. Legacy/unlocked
    # lock rows must be normalized to finalized below.
    if existing_lock_row and str(existing_lock_row["status"] or "").lower() == "finalized":
        con.close(); tab_value=str(request.query_params.get("ds_tab") or "").strip()
    return_params = []
    for pname, pvalue in (("exam_id",return_exam_id),("class_id",return_class_id),("subject_id",return_subject_id)):
        if str(pvalue or "").strip():
            return_params.append(pname+"="+quote(str(pvalue).strip(),safe=""))
    if tab_value:
        return_params.append("ds_tab="+quote(tab_value,safe=""))
    return RedirectResponse("/app/academics/marks" + (("?"+"&".join(return_params)) if return_params else ""),303)

    role=str(request.session.get("role",""))
    if role=="teacher":
        _ensure_teacher_mark_drafts_table(cur)
        teacher_id=int(request.session.get("teacher_id") or 0)
        form=await request.form()
        # Capture the current screen before publishing.
        now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        students=cur.execute("SELECT id FROM students WHERE school_id=? AND class_id=?",(sid,class_id)).fetchall()
        cfg=cur.execute("SELECT out_of FROM set_marks_config WHERE school_id=? AND exam_id=? AND subject_id=? ORDER BY id DESC LIMIT 1",(sid,exam_id,subject_id)).fetchone()
        out_of=float(cfg["out_of"] or 100) if cfg and cfg["out_of"] else 100.0
        exam=cur.execute("SELECT year,term FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
        for st in students:
            student_id=int(st["id"])
            raw=form.get(f"mark_{student_id}")
            comment=str(form.get(f"comment_{student_id}") or "").strip()
            if raw is None or str(raw).strip()=="":
                continue
            try: mark=float(raw)
            except Exception: continue
            if mark<0 or mark>out_of: continue
            mark_value=int(mark) if mark.is_integer() else mark
            old=cur.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=?",(sid,student_id,subject_id,exam_id)).fetchone()
            if old:
                cur.execute("UPDATE marks SET marks=?,class_id=?,year=?,term=? WHERE id=? AND school_id=?",(mark_value,class_id,exam["year"],exam["term"],old["id"],sid))
            else:
                cur.execute("INSERT INTO marks(school_id,student_id,subject_id,exam_id,class_id,marks,year,term) VALUES(?,?,?,?,?,?,?,?)",(sid,student_id,subject_id,exam_id,class_id,mark_value,exam["year"],exam["term"]))
            _ensure_report_card_fields(cur)
            try:
                grading_rules=_load_grading_rules(cur,sid)
                _,_,comment=_subject_grade_details(cur,sid,subject_id,mark,grading_rules,out_of)
            except Exception as exc:
                print("DAVISCHOOL FINALIZE COMMENT FALLBACK:",repr(exc),flush=True)
                comment=""
            existing_comments=cur.execute(
                "SELECT id FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=?",
                (sid,student_id,exam_id,subject_id)
            ).fetchall()
            if existing_comments:
                for existing_comment in existing_comments:
                    cur.execute(
                        "UPDATE subject_performance_comments SET comment=?,updated_at=? WHERE id=? AND school_id=?",
                        (comment,now,existing_comment["id"],sid)
                    )
            else:
                cur.execute(
                    "INSERT INTO subject_performance_comments(school_id,student_id,exam_id,subject_id,comment,updated_at) VALUES(?,?,?,?,?,?)",
                    (sid,student_id,exam_id,subject_id,comment,now)
                )
        cur.execute("DELETE FROM teacher_mark_drafts WHERE school_id=? AND teacher_id=? AND exam_id=? AND class_id=? AND subject_id=?",(sid,teacher_id,exam_id,class_id,subject_id))

    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    # The lock is the actual publication/submit operation. If a legacy database
    # already has a lock row for this exact selection, normalize that row to
    # finalized instead of creating a second lock record.
    existing_lock=cur.execute(
        "SELECT status FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=? LIMIT 1",
        (sid,exam_id,class_id,subject_id)
    ).fetchone()
    if existing_lock:
        cur.execute(
            "UPDATE academic_locks SET status=?,finalized_by=?,finalized_at=? WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=?",
            ("finalized",request.session.get("email",""),now,sid,exam_id,class_id,subject_id)
        )
    else:
        cur.execute(
            "INSERT INTO academic_locks(school_id,exam_id,class_id,subject_id,status,finalized_by,finalized_at) VALUES(?,?,?,?,?,?,?)",
            (sid,exam_id,class_id,subject_id,"finalized",request.session.get("email",""),now)
        )
    # Commit the actual lock independently of the optional audit trail.
    try:
        cur.execute("SAVEPOINT davischool_finalize_audit")
        try:
            _audit(cur,sid,request,"MARKS_FINALIZE",f"Finalized marks for exam {exam_id}, class {class_id}, subject {subject_id}")
            cur.execute("RELEASE SAVEPOINT davischool_finalize_audit")
        except Exception as audit_exc:
            print("DAVISCHOOL MARKS FINALIZE AUDIT WARNING:",repr(audit_exc),flush=True)
            try: cur.execute("ROLLBACK TO SAVEPOINT davischool_finalize_audit")
            except Exception: pass
            try: cur.execute("RELEASE SAVEPOINT davischool_finalize_audit")
            except Exception: pass
    except Exception as audit_sp_exc:
        print("DAVISCHOOL MARKS FINALIZE AUDIT SAVEPOINT WARNING:",repr(audit_sp_exc),flush=True)
    con.commit()
    # Verify the committed lock before redirecting. This makes a failed/legacy
    # lock write visible in the Render log instead of silently returning to the
    # editable marks screen.
    verified=cur.execute(
        "SELECT status FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=? AND status='finalized' LIMIT 1",
        (sid,exam_id,class_id,subject_id)
    ).fetchone()
    if not verified:
        print("DAVISCHOOL MARKS FINALIZE ERROR: lock was not persisted",flush=True)
        con.close()
        return HTMLResponse("Marks could not be locked. Please try Submit & Lock Marks again.",500)
    con.close()
    tab_value=str(request.query_params.get("ds_tab") or "").strip()
    tab_suffix=("&ds_tab="+quote(tab_value,safe="")) if tab_value else ""
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}"+tab_suffix,303)

@router.get("/app/academics/marks/request-correction", response_class=HTMLResponse)
def request_marks_correction_get(request: Request, exam_id:int=0, class_id:int=0, subject_id:int=0):
    """Gracefully handle clients that submit the correction action as GET instead of POST."""
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if str(request.session.get("role","")) != "teacher":
        return HTMLResponse("Only teachers can submit a correction request.", 403)
    if not exam_id or not class_id or not subject_id:
        return RedirectResponse("/app/academics/marks", 303)
    return HTMLResponse(
        "<div style='font-family:Arial,sans-serif;padding:30px'>"
        "<h2>Request Marks Correction</h2>"
        "<p>Please enter the reason for requesting correction.</p>"
        "<form method='post' action='/app/academics/marks/request-correction'>"
        f"<input type='hidden' name='exam_id' value='{exam_id}'>"
        f"<input type='hidden' name='class_id' value='{class_id}'>"
        f"<input type='hidden' name='subject_id' value='{subject_id}'>"
        "<textarea name='reason' required minlength='5' style='width:100%;max-width:500px;padding:10px' placeholder='Reason for correction'></textarea>"
        "<br><br><button type='submit'>Submit Correction Request</button>"
        "</form></div>"
    )

@router.post("/app/academics/marks/request-correction")
async def request_marks_correction(request: Request, exam_id:int=Form(0), class_id:int=Form(0), subject_id:int=Form(0), reason:str=Form("")):
    # Accept the academic IDs from the form body or from the action URL.
    # Some mobile browsers can omit hidden form controls during submission;
    # keeping the IDs in both places prevents a 422 from losing the request.
    try:
        exam_id = int(exam_id or request.query_params.get("exam_id") or 0)
        class_id = int(class_id or request.query_params.get("class_id") or 0)
        subject_id = int(subject_id or request.query_params.get("subject_id") or 0)
    except (TypeError, ValueError):
        exam_id, class_id, subject_id = 0, 0, 0
    if not reason:
        reason = str(request.query_params.get("reason") or "")
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "teacher":
        return HTMLResponse("Only teachers can submit a correction request.",403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to request mark corrections.",403)
    teacher_id=request.session.get("teacher_id")
    if not teacher_id:
        return HTMLResponse("Your teacher account is not linked to a teacher record. Please contact the school administrator.",403)
    reason=reason.strip()
    if len(reason)<5:
        return HTMLResponse("Please provide a clear reason for the correction.",400)
    con=_db();cur=con.cursor();_ensure_academic_locks_table(cur);_ensure_marks_correction_requests_table(cur)
    if not _teacher_class_authorized(cur,request,sid,class_id,subject_id):
        con.close();return HTMLResponse("You are not allocated to this class and subject.",403)
    valid=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not valid:
        con.close();return HTMLResponse("Invalid academic selection.",400)
    if not _academic_lock(cur,sid,exam_id,class_id,subject_id):
        con.close();return HTMLResponse("These marks are not locked, so you can correct them directly.",400)
    existing=_pending_marks_correction(cur,sid,exam_id,class_id,subject_id,int(teacher_id))
    if existing:
        con.close();return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    request_values=(sid,exam_id,class_id,subject_id,int(teacher_id),request.session.get("email",""),now,reason,"pending")
    # Some older PostgreSQL deployments have this table with an id column but
    # without a working BIGSERIAL default. Try the normal insert first; if that
    # legacy schema rejects it, generate the request id from the existing rows
    # inside a savepoint. Existing requests are never deleted or rewritten.
    try:
        cur.execute("SAVEPOINT davischool_correction_insert")
        cur.execute("INSERT INTO marks_correction_requests(school_id,exam_id,class_id,subject_id,teacher_id,requested_by,requested_at,reason,status) VALUES(?,?,?,?,?,?,?,?,?)",request_values)
        cur.execute("RELEASE SAVEPOINT davischool_correction_insert")
    except Exception as insert_exc:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT davischool_correction_insert")
            cur.execute("RELEASE SAVEPOINT davischool_correction_insert")
        except Exception:
            pass
        print("DAVISCHOOL MARKS CORRECTION INSERT RETRY:",repr(insert_exc),flush=True)
        next_id=cur.execute("SELECT COALESCE(MAX(id),0)+1 AS next_id FROM marks_correction_requests").fetchone()["next_id"]
        cur.execute("INSERT INTO marks_correction_requests(id,school_id,exam_id,class_id,subject_id,teacher_id,requested_by,requested_at,reason,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (int(next_id),)+request_values)
    # The correction request itself must never be lost because an optional audit
    # record has a legacy schema problem. Save the request first; audit failure
    # is only a warning and does not block the approval workflow.
    try:
        _audit(cur,sid,request,"MARKS_CORRECTION_REQUEST",f"Requested mark correction for exam {exam_id}, class {class_id}, subject {subject_id}: {reason}")
    except Exception as audit_exc:
        print("DAVISCHOOL MARKS CORRECTION AUDIT WARNING:",repr(audit_exc),flush=True)
    con.commit()
    tab_value=str(request.query_params.get("ds_tab") or "").strip()
    return_params = []
    if return_load:
        return_params.append("load=1")
    for pname, pvalue in (("exam_id",return_exam_id),("class_id",return_class_id),("subject_id",return_subject_id),("year",return_year),("term",return_term)):
        if str(pvalue or "").strip():
            return_params.append(pname+"="+quote(str(pvalue).strip(),safe=""))
    if tab_value:
        return_params.append("ds_tab="+quote(tab_value,safe=""))
    return RedirectResponse("/app/academics/marks-corrections" + (("?"+"&".join(return_params)) if return_params else ""),303)

@router.get("/app/academics/marks-corrections", response_class=HTMLResponse)
def marks_correction_requests(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can review mark correction requests.",403)

    con=_db();cur=con.cursor()
    _ensure_marks_correction_requests_table(cur)
    _ensure_academic_locks_table(cur)

    # Load filter choices from this school only. No marks are changed by this page.
    examinations=cur.execute(
        "SELECT id,name FROM exams WHERE school_id=? ORDER BY name,id",(sid,)
    ).fetchall()
    classes=cur.execute(
        "SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream,id",(sid,)
    ).fetchall()
    subjects=cur.execute(
        "SELECT id,name FROM subjects WHERE school_id=? ORDER BY name,id",(sid,)
    ).fetchall()
    filter_years=cur.execute(
        "SELECT DISTINCT year FROM marks WHERE school_id=? AND year IS NOT NULL AND TRIM(CAST(year AS TEXT))<>'' ORDER BY year DESC",(sid,)
    ).fetchall()
    filter_terms=cur.execute(
        "SELECT DISTINCT term FROM marks WHERE school_id=? AND term IS NOT NULL AND TRIM(CAST(term AS TEXT))<>'' ORDER BY term",(sid,)
    ).fetchall()

    # Nothing is displayed until the administrator selects filters and clicks Load.
    params=request.query_params
    load_requested=str(params.get("load","")).strip()=="1"
    exam_filter=str(params.get("exam_id","")).strip()
    class_filter=str(params.get("class_id","")).strip()
    subject_filter=str(params.get("subject_id","")).strip()
    year_filter=str(params.get("year","")).strip()
    term_filter=str(params.get("term","")).strip()

    saved_rows=[]
    if load_requested:
        where=[
            "m.school_id=?",
            "m.exam_id IS NOT NULL",
            "m.class_id IS NOT NULL",
            "m.subject_id IS NOT NULL",
            "m.marks IS NOT NULL"
        ]
        query_params=[sid]

        if exam_filter:
            try:
                where.append("m.exam_id=?")
                query_params.append(int(exam_filter))
            except (TypeError,ValueError):
                exam_filter=""
        if class_filter:
            try:
                where.append("m.class_id=?")
                query_params.append(int(class_filter))
            except (TypeError,ValueError):
                class_filter=""
        if subject_filter:
            try:
                where.append("m.subject_id=?")
                query_params.append(int(subject_filter))
            except (TypeError,ValueError):
                subject_filter=""
        if year_filter:
            where.append("CAST(m.year AS TEXT)=?")
            query_params.append(year_filter)
        if term_filter:
            where.append("CAST(m.term AS TEXT)=?")
            query_params.append(term_filter)

        saved_rows=cur.execute("""
            SELECT
                m.exam_id,m.class_id,m.subject_id,
                e.name exam_name,c.name class_name,c.stream,
                sub.name subject_name,
                COUNT(m.id) mark_count,
                AVG(m.marks) mark_mean,
                MAX(m.year) mark_year,MAX(m.term) mark_term
            FROM marks m
            LEFT JOIN exams e ON e.id=m.exam_id
            LEFT JOIN classes c ON c.id=m.class_id
            LEFT JOIN subjects sub ON sub.id=m.subject_id
            WHERE %s
            GROUP BY m.exam_id,m.class_id,m.subject_id,e.name,c.name,c.stream,sub.name
            ORDER BY COALESCE(e.name,''),COALESCE(c.name,''),COALESCE(c.stream,''),COALESCE(sub.name,'')
        """ % " AND ".join(where),query_params).fetchall()

    request_rows=cur.execute("""
        SELECT r.*,e.name exam_name,c.name class_name,c.stream,sub.name subject_name,t.name teacher_name
        FROM marks_correction_requests r
        LEFT JOIN exams e ON e.id=r.exam_id
        LEFT JOIN classes c ON c.id=r.class_id
        LEFT JOIN subjects sub ON sub.id=r.subject_id
        LEFT JOIN teachers t ON t.id=r.teacher_id
        WHERE r.school_id=?
        ORDER BY CASE WHEN r.status='pending' THEN 0 ELSE 1 END,r.id DESC
    """,(sid,)).fetchall()

    lock_map={}
    for row in saved_rows:
        lock_map[(int(row["exam_id"]),int(row["class_id"]),int(row["subject_id"]))] = _academic_lock(
            cur,sid,int(row["exam_id"]),int(row["class_id"]),int(row["subject_id"])
        )

    con.close()

    exam_options="".join(
        "<option value='%s' %s>%s</option>" % (
            x["id"],"selected" if str(x["id"])==exam_filter else "",
            escape(str(x["name"] or ""))
        ) for x in examinations
    )
    class_options="".join(
        "<option value='%s' %s>%s%s</option>" % (
            x["id"],"selected" if str(x["id"])==class_filter else "",
            escape(str(x["name"] or "")),
            (" — "+escape(str(x["stream"] or ""))) if x["stream"] else ""
        ) for x in classes
    )
    subject_options="".join(
        "<option value='%s' %s>%s</option>" % (
            x["id"],"selected" if str(x["id"])==subject_filter else "",
            escape(str(x["name"] or ""))
        ) for x in subjects
    )
    year_options="".join(
        "<option value='%s' %s>%s</option>" % (
            escape(str(x["year"] or "")),
            "selected" if str(x["year"] or "")==year_filter else "",
            escape(str(x["year"] or ""))
        ) for x in filter_years
    )
    term_options="".join(
        "<option value='%s' %s>%s</option>" % (
            escape(str(x["term"] or "")),
            "selected" if str(x["term"] or "")==term_filter else "",
            escape(str(x["term"] or ""))
        ) for x in filter_terms
    )

    # Preserve the browser tab's isolated session when Lock/Unlock is submitted.
    # Without ds_tab, the tab-aware session middleware can fall back to the wrong
    # session cookie and the action can appear to do nothing or return to login.
    correction_tab_id = str(request.query_params.get("ds_tab") or "").strip()
    tab_q = ("?ds_tab=" + quote(correction_tab_id, safe="")) if correction_tab_id else ""

    marks_rows=""
    for r in saved_rows:
        key=(int(r["exam_id"]),int(r["class_id"]),int(r["subject_id"]))
        locked_row=lock_map.get(key)
        locked=str(locked_row["status"] or "").lower()=="finalized" if locked_row else False
        status_html = "<span style='font-weight:900;color:#b91c1c'>🔒 Locked / Submitted</span>" if locked else "<span style='font-weight:900;color:#176B3A'>🟢 Saved / Unlocked</span>"
        if locked:
            action=(f"<form method='post' action='/app/academics/marks/unfinalize" + tab_q + "' style='display:inline'>"
                    f"<input type='hidden' name='exam_id' value='{key[0]}'><input type='hidden' name='class_id' value='{key[1]}'><input type='hidden' name='subject_id' value='{key[2]}'><input type='hidden' name='return_exam_id' value='{escape(str(exam_filter or ""))}'><input type='hidden' name='return_class_id' value='{escape(str(class_filter or ""))}'><input type='hidden' name='return_subject_id' value='{escape(str(subject_filter or ""))}'><input type='hidden' name='return_year' value='{escape(str(year_filter or ""))}'><input type='hidden' name='return_term' value='{escape(str(term_filter or ""))}'><input type='hidden' name='return_load' value='1'>"
                    f"<button class='unlock-btn' type='submit' onclick='if(confirm(&quot;Unlock these subject marks for editing?&quot;)){{this.form.submit();}} return false;'>🔓 Unlock</button></form>")
        else:
            action=(f"<form method='post' action='/app/academics/marks-corrections/lock" + tab_q + "' style='display:inline'>"
                    f"<input type='hidden' name='exam_id' value='{key[0]}'><input type='hidden' name='class_id' value='{key[1]}'><input type='hidden' name='subject_id' value='{key[2]}'><input type='hidden' name='return_exam_id' value='{escape(str(exam_filter or ""))}'><input type='hidden' name='return_class_id' value='{escape(str(class_filter or ""))}'><input type='hidden' name='return_subject_id' value='{escape(str(subject_filter or ""))}'><input type='hidden' name='return_year' value='{escape(str(year_filter or ""))}'><input type='hidden' name='return_term' value='{escape(str(term_filter or ""))}'><input type='hidden' name='return_load' value='1'>"
                    f"<button class='lock-btn' type='submit' onclick='if(confirm(&quot;Lock and submit these subject marks?&quot;)){{this.form.submit();}} return false;'>🔒 Lock</button></form>")
        marks_rows += (
            f"<tr><td>{escape(str(r['exam_name'] or ''))}</td>"
            f"<td>{escape(str(r['class_name'] or ''))}{(' · '+escape(str(r['stream'] or ''))) if r['stream'] else ''}</td>"
            f"<td><b>{escape(str(r['subject_name'] or ''))}</b></td>"
            f"<td>{escape(str(r['mark_term'] or ''))}</td><td>{escape(str(r['mark_year'] or ''))}</td>"
            f"<td>{int(r['mark_count'] or 0)}</td>"
            f"<td>{'—' if r['mark_mean'] is None else ('%.1f' % float(r['mark_mean']))}</td>"
            f"<td>{status_html}</td><td>{action}</td></tr>"
        )

    request_rows_html=""
    for r in request_rows:
        status=str(r["status"] or "").lower()
        action=""
        if status=="pending":
            action=(f"<form method='post' action='/app/academics/marks-corrections/approve' style='display:inline'>"
                    f"<input type='hidden' name='request_id' value='{r['id']}'>"
                    f"<button class='btn' type='submit' onclick='return confirm(&quot;Approve this correction request and reopen the marks?&quot;);'>🔓 Approve / Reopen</button></form> "
                    f"<form method='post' action='/app/academics/marks-corrections/reject' style='display:inline'>"
                    f"<input type='hidden' name='request_id' value='{r['id']}'>"
                    f"<button class='btnlink' type='submit' onclick='return confirm(&quot;Reject this correction request?&quot;);'>Reject</button></form>")
        request_rows_html += (
            f"<tr><td>{escape(str(r['requested_at'] or ''))}</td>"
            f"<td>{escape(str(r['teacher_name'] or r['requested_by'] or ''))}</td>"
            f"<td>{escape(str(r['exam_name'] or ''))}</td>"
            f"<td>{escape(str(r['class_name'] or ''))} {escape(str(r['stream'] or ''))}</td>"
            f"<td>{escape(str(r['subject_name'] or ''))}</td>"
            f"<td>{escape(str(r['reason'] or ''))}</td>"
            f"<td>{escape(status.title())}</td><td>{action}</td></tr>"
        )

    filter_summary = ""
    if load_requested:
        filter_summary = "<div class='muted' style='margin-top:10px'>Showing %d saved subject assessment(s) matching the selected filters.</div>" % len(saved_rows)

    body=f"""<div class='page'><h1>Marks Corrections</h1>
<div class='muted'>Select the examination, class, subject, year and term, then click <b>Load</b> to display the saved subject marks for that selection.</div>
<div class='card section'>
<h2>Load Saved & Submitted Subject Marks</h2>
<form method='get' action='/app/academics/marks-corrections' class='marks-filter-form'>
<div class='filter-grid'>
<label>Examination<select name='exam_id' class='field'><option value=''>All Examinations</option>{exam_options}</select></label>
<label>Class<select name='class_id' class='field'><option value=''>All Classes</option>{class_options}</select></label>
<label>Subject<select name='subject_id' class='field'><option value=''>All Subjects</option>{subject_options}</select></label>
<label>Year<select name='year' class='field'><option value=''>All Years</option>{year_options}</select></label>
<label>Term<select name='term' class='field'><option value=''>All Terms</option>{term_options}</select></label>
</div>
<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px'>
<button class='load-btn' type='submit' name='load' value='1'>🔎 Load</button>
<a class='clear-btn' href='/app/academics/marks-corrections'>Clear</a>
</div>
</form>
{filter_summary}
</div>
<div class='card section'><h2>Saved & Submitted Subject Marks</h2>
<div style='overflow-x:auto'>
<table><thead><tr><th>Examination</th><th>Class</th><th>Subject</th><th>Term</th><th>Year</th><th>Entries</th><th>Mean</th><th>Status</th><th>Action</th></tr></thead>
<tbody>{marks_rows or "<tr><td colspan='9'>No saved subject marks found for the selected filters.</td></tr>"}</tbody></table></div></div>
<div class='card section'><div style='display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap'><h2 style='margin:0'>Teacher Correction Requests</h2><form method='post' action='/app/academics/marks-corrections/clear?ds_tab={quote(str(request.query_params.get("ds_tab") or ""),safe="")}' style='display:inline' onsubmit='return confirm(&quot;Clear all teacher correction requests for this school? This will not change any marks or saved subject records.&quot;);'><input type='hidden' name='ds_tab' value='{escape(str(request.query_params.get("ds_tab") or ""))}'><button class='btnlink' type='submit' style='color:#b91c1c;border-color:#fecaca;font-weight:900'>🗑 Clear Requests</button></form></div>
<div class='muted' style='margin:10px 0'>Requests submitted by teachers remain available here for review.</div>
<div style='overflow-x:auto'>
<table><thead><tr><th>Requested</th><th>Teacher</th><th>Exam</th><th>Class</th><th>Subject</th><th>Reason</th><th>Status</th><th>Action</th></tr></thead>
<tbody>{request_rows_html or "<tr><td colspan='8'>No correction requests yet.</td></tr>"}</tbody></table></div></div>
</div>
<style>
.marks-filter-form{{margin-top:8px}}
.filter-grid{{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:10px}}
.filter-grid label{{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:800;color:#334155}}
.field{{width:100%;box-sizing:border-box;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff;font-size:14px}}
.load-btn,.clear-btn{{display:inline-flex;align-items:center;justify-content:center;padding:10px 16px;border-radius:9px;font-weight:900;text-decoration:none;cursor:pointer}}
.load-btn{{border:0;background:#176B3A;color:#fff}}
.clear-btn{{border:1px solid #dbe2ea;background:#fff;color:#172033}}
.btn,.btnlink,.lock-btn,.unlock-btn{{padding:8px 11px;border:0;border-radius:8px;background:#176B3A;color:#fff;font-weight:800;cursor:pointer;text-decoration:none;white-space:nowrap}}
.btnlink{{background:#fff;color:#172033;border:1px solid #dbe2ea}}
.unlock-btn{{background:#b45309}}
.lock-btn{{background:#176B3A}}
@media(max-width:900px){{.filter-grid{{grid-template-columns:repeat(2,minmax(150px,1fr))}}}}
@media(max-width:560px){{.filter-grid{{grid-template-columns:1fr}}}}
</style>"""
    return _school_page(request,"Marks Corrections",body)

@router.post("/app/academics/marks-corrections/approve")
def approve_marks_correction(request: Request, request_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can approve corrections.",403)
    con=_db();cur=con.cursor();_ensure_academic_locks_table(cur);_ensure_marks_correction_requests_table(cur)
    row=cur.execute("SELECT * FROM marks_correction_requests WHERE id=? AND school_id=? AND status='pending'",(request_id,sid)).fetchone()
    if not row:
        con.close();return HTMLResponse("Correction request not found or already reviewed.",404)
    lock=_academic_lock(cur,sid,row["exam_id"],row["class_id"],row["subject_id"])
    if lock:
        cur.execute("DELETE FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=?",(sid,row["exam_id"],row["class_id"],row["subject_id"]))
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE marks_correction_requests SET status='approved',reviewed_by=?,reviewed_at=?,review_note=? WHERE id=? AND school_id=?",(request.session.get("email",""),now,"Marks reopened for teacher correction.",request_id,sid))
    _audit(cur,sid,request,"MARKS_CORRECTION_APPROVE",f"Approved correction request {request_id}; reopened exam {row['exam_id']}, class {row['class_id']}, subject {row['subject_id']}")
    con.commit();con.close()
    return RedirectResponse("/app/academics/marks-corrections",303)

@router.post("/app/academics/marks-corrections/clear")
def clear_marks_correction_requests(request: Request, ds_tab: str = Form("")):
    """Clear teacher correction requests and return to the same isolated admin tab."""
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can clear correction requests.",403)

    # Prefer the tab id submitted by the form, but fall back to the query
    # parameter injected by the tab-session middleware. This prevents a clear
    # action from falling back to the generic login session.
    tab_value=str(ds_tab or request.query_params.get("ds_tab") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", tab_value):
        tab_value=""

    con=_db();cur=con.cursor()
    _ensure_marks_correction_requests_table(cur)
    try:
        count_row=cur.execute(
            "SELECT COUNT(*) AS n FROM marks_correction_requests WHERE school_id=?",
            (sid,),
        ).fetchone()
        cleared=int(count_row["n"] or 0) if count_row else 0
        if cleared:
            cur.execute(
                "DELETE FROM marks_correction_requests WHERE school_id=?",
                (sid,),
            )
            _audit(
                cur,sid,request,"MARKS_CORRECTION_CLEAR",
                f"Cleared {cleared} teacher correction request(s)",
            )
        con.commit()
    finally:
        con.close()

    tab_suffix=("&ds_tab="+quote(tab_value,safe="")) if tab_value else ""
    return RedirectResponse("/app/academics/marks-corrections"+tab_suffix,303)

@router.post("/app/academics/marks-corrections/reject")
def reject_marks_correction(request: Request, request_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can reject corrections.",403)
    con=_db();cur=con.cursor();_ensure_marks_correction_requests_table(cur)
    row=cur.execute("SELECT id FROM marks_correction_requests WHERE id=? AND school_id=? AND status='pending'",(request_id,sid)).fetchone()
    if not row:
        con.close();return HTMLResponse("Correction request not found or already reviewed.",404)
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE marks_correction_requests SET status='rejected',reviewed_by=?,reviewed_at=?,review_note=? WHERE id=? AND school_id=?",(request.session.get("email",""),now,"Correction request rejected.",request_id,sid))
    _audit(cur,sid,request,"MARKS_CORRECTION_REJECT",f"Rejected correction request {request_id}")
    con.commit();con.close()
    return RedirectResponse("/app/academics/marks-corrections",303)

@router.post("/app/academics/marks-corrections/lock")
def lock_marks_from_corrections(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...), return_exam_id:str=Form(""), return_class_id:str=Form(""), return_subject_id:str=Form(""), return_year:str=Form(""), return_term:str=Form(""), return_load:str=Form("1")):
    """School Admin-only lock action for the Marks Corrections page."""
    sid=_school_session(request)
    if not sid:
        return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can lock marks from the Marks Corrections page.",403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to lock marks.",403)

    con=_db();cur=con.cursor()
    try:
        _ensure_academic_locks_table(cur)

        valid = (
            cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
            and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
            and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
        )
        if not valid:
            con.close()
            return HTMLResponse("Invalid academic selection.",400)

        # Do not create a lock for a subject with no saved marks.
        has_marks=cur.execute(
            "SELECT 1 FROM marks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=? AND marks IS NOT NULL LIMIT 1",
            (sid,exam_id,class_id,subject_id)
        ).fetchone()
        if not has_marks:
            con.close()
            return HTMLResponse("No saved marks were found for this examination, class and subject.",400)

        now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        # Normalize any legacy/duplicate lock rows for this exact subject,
        # then write one authoritative finalized row. This prevents an older
        # unlocked row from being selected by the status lookup.
        cur.execute(
            "DELETE FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=?",
            (sid,exam_id,class_id,subject_id)
        )
        cur.execute(
            "INSERT INTO academic_locks(school_id,exam_id,class_id,subject_id,status,finalized_by,finalized_at) VALUES(?,?,?,?,?,?,?)",
            (sid,exam_id,class_id,subject_id,"finalized",request.session.get("email",""),now)
        )

        try:
            _audit(cur,sid,request,"MARKS_FINALIZE",f"Finalized marks from Marks Corrections for exam {exam_id}, class {class_id}, subject {subject_id}")
        except Exception as audit_exc:
            print("DAVISCHOOL CORRECTIONS LOCK AUDIT WARNING:",repr(audit_exc),flush=True)

        con.commit()

        verified=cur.execute(
            "SELECT 1 FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=? AND status='finalized' LIMIT 1",
            (sid,exam_id,class_id,subject_id)
        ).fetchone()
        if not verified:
            con.close()
            return HTMLResponse("Marks could not be locked.",500)
    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        print("DAVISCHOOL CORRECTIONS LOCK ERROR:",repr(exc),flush=True)
        con.close()
        return HTMLResponse("Marks could not be locked. Please try again.",500)

    tab_value=str(request.query_params.get("ds_tab") or "").strip()
    tab_suffix=("&ds_tab="+quote(tab_value,safe="")) if tab_value else ""
    con.close()
    return_params = []
    if return_load:
        return_params.append("load=1")
    for pname, pvalue in (("exam_id",return_exam_id),("class_id",return_class_id),("subject_id",return_subject_id),("year",return_year),("term",return_term)):
        if str(pvalue or "").strip():
            return_params.append(pname+"="+quote(str(pvalue).strip(),safe=""))
    if tab_value:
        return_params.append("ds_tab="+quote(tab_value,safe=""))
    return_url="/app/academics/marks-corrections" + (("?"+"&".join(return_params)) if return_params else "")
    return RedirectResponse(return_url,303)

@router.post("/app/academics/marks/unfinalize")
def unfinalize_marks(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...), return_exam_id:str=Form(""), return_class_id:str=Form(""), return_subject_id:str=Form(""), return_year:str=Form(""), return_term:str=Form(""), return_load:str=Form("1")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can directly reopen finalized marks.",403)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to unfinalize marks.", 403)
    con=_db();cur=con.cursor();_ensure_academic_locks_table(cur)
    row=_academic_lock(cur,sid,exam_id,class_id,subject_id)
    if row:
        cur.execute("DELETE FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id=?",(sid,exam_id,class_id,subject_id))
        _audit(cur,sid,request,"MARKS_UNFINALIZE",f"Reopened marks for exam {exam_id}, class {class_id}, subject {subject_id}")
    con.commit()
    tab_value=str(request.query_params.get("ds_tab") or "").strip()
    return_params = []
    if return_load:
        return_params.append("load=1")
    for pname, pvalue in (("exam_id",return_exam_id),("class_id",return_class_id),("subject_id",return_subject_id),("year",return_year),("term",return_term)):
        if str(pvalue or "").strip():
            return_params.append(pname+"="+quote(str(pvalue).strip(),safe=""))
    if tab_value:
        return_params.append("ds_tab="+quote(tab_value,safe=""))
    return RedirectResponse("/app/academics/marks-corrections" + (("?"+"&".join(return_params)) if return_params else ""),303)

def _ensure_teacher_allocations_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS teacher_allocations (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        UNIQUE(school_id,teacher_id,class_id,subject_id)
    )""")

@router.get("/app/academics/allocations", response_class=HTMLResponse)
def teacher_allocations_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request,sid,"staff.edit"):
        return HTMLResponse("You do not have permission to manage teacher allocations.",403)
    con=_db();cur=con.cursor();_ensure_teacher_allocations_table(cur)
    teachers=cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    subjects=cur.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    rows=cur.execute("""SELECT a.id,t.name teacher_name,c.name class_name,c.stream class_stream,s.name subject_name
                        FROM teacher_allocations a JOIN teachers t ON t.id=a.teacher_id
                        JOIN classes c ON c.id=a.class_id JOIN subjects s ON s.id=a.subject_id
                        WHERE a.school_id=? ORDER BY t.name,c.name,s.name""",(sid,)).fetchall()
    con.close()
    tops="".join("<option value='%s'>%s</option>"%(x["id"],escape(str(x["name"] or ""))) for x in teachers)
    cops="".join("<option value='%s'>%s%s</option>"%(x["id"],escape(str(x["name"] or "")),(" — "+escape(str(x["stream"]))) if x["stream"] else "") for x in classes)
    sops="".join("<option value='%s'>%s</option>"%(x["id"],escape(str(x["name"] or ""))) for x in subjects)
    current_ds_tab_q=("?" + "ds_tab=" + quote(request.query_params.get("ds_tab"),safe="")) if request.query_params.get("ds_tab") else ""
    trs="".join("<tr><td>%s</td><td>%s%s</td><td>%s</td><td><a class='btn edit' href='/app/academics/allocations/edit/%s'>Edit</a> <form method='post' action='/app/academics/allocations/delete/%s%s' style='display:inline' onsubmit=\"if(!confirm('Delete this teacher allocation?')) return false; this.submit(); return false;\"><button class='btn danger' type='submit' formaction='/app/academics/allocations/delete/%s%s' formmethod='post'>Delete</button></form></td></tr>"%(escape(str(x["teacher_name"])),escape(str(x["class_name"])),(" — "+escape(str(x["class_stream"]))) if x["class_stream"] else "",escape(str(x["subject_name"])),x["id"],x["id"],current_ds_tab_q,x["id"],current_ds_tab_q) for x in rows)
    body=f"""<div class='page'><h1>Teacher Allocations</h1><div class='muted'>Assign teachers to classes and subjects.</div>
<div class='card section'><div class='teacher-allocation-filter-scroll' tabindex='0'><form method='post' action='/app/academics/allocations/add{current_ds_tab_q}' class='teacher-allocation-filter-form'>
<select name='teacher_id' class='field' required><option value=''>Select Teacher</option>{tops}</select>
<select name='class_id' class='field' required><option value=''>Select Class / Stream</option>{cops}</select>
<select name='subject_id' class='field' required><option value=''>Select Subject</option>{sops}</select>
<button class='btn' type='submit' formaction='/app/academics/allocations/add{current_ds_tab_q}' formmethod='post'>Save Allocation</button></form></div></div>
<div class='card section'><h2>Current Allocations ({len(rows)})</h2><div class='marksheet-scroll teacher-allocation-scroll' tabindex='0'><table class='teacher-allocation-table'><thead><tr><th>Teacher</th><th>Class / Stream</th><th>Subject</th><th>Action</th></tr></thead><tbody>{trs or '<tr><td colspan=4>No allocations yet.</td></tr>'}</tbody></table></div></div>
<style>.teacher-allocation-scroll{{display:block;width:100%;min-width:0;max-width:100%;max-height:60vh;overflow-x:auto;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;overscroll-behavior:contain;padding-bottom:10px}}.teacher-allocation-scroll::-webkit-scrollbar{{width:10px;height:10px}}.teacher-allocation-scroll::-webkit-scrollbar-thumb{{border-radius:8px;background:#9ca3af}}.teacher-allocation-filter-scroll::-webkit-scrollbar{{height:10px}}.teacher-allocation-table{{width:max-content;min-width:900px}}.teacher-allocation-filter-scroll{{display:block;width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x;overscroll-behavior-x:contain;padding-bottom:8px}}.teacher-allocation-filter-form{{display:grid;grid-template-columns:260px 260px 260px auto;gap:10px;width:max-content;min-width:100%}}.teacher-allocation-filter-form .field{{min-width:0}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}.danger{{background:#b91c1c}}.edit{{background:#176B3A;margin-right:5px;padding:9px 12px}}</style></div>"""
    return _school_page(request,"Teacher Allocations",body)

@router.post("/app/academics/allocations/add")
def teacher_allocations_add(request: Request,teacher_id:int=Form(...),class_id:int=Form(...),subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request,sid,"staff.edit"):return HTMLResponse("You do not have permission to manage teacher allocations.",403)
    con=_db();cur=con.cursor();_ensure_teacher_allocations_table(cur)
    if not (cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()):
        con.close();return HTMLResponse("Invalid selection. <a href='/app/academics/allocations'>Back</a>",400)
    existing=cur.execute("SELECT id FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND class_id=? AND subject_id=? LIMIT 1",(sid,teacher_id,class_id,subject_id)).fetchone()
    if not existing:
        cur.execute("INSERT INTO teacher_allocations(school_id,teacher_id,class_id,subject_id) VALUES(?,?,?,?)",(sid,teacher_id,class_id,subject_id))
        _audit(cur,sid,request,"TEACHER_ALLOCATION","Teacher %s / Class %s / Subject %s"%(teacher_id,class_id,subject_id))
    con.commit();con.close()
    tab_value=str(request.query_params.get("ds_tab") or "").strip()
    return RedirectResponse("/app/academics/allocations" + (("?ds_tab="+quote(tab_value,safe="")) if tab_value else ""),303)

@router.get("/app/academics/allocations/edit/{allocation_id}", response_class=HTMLResponse)
def teacher_allocations_edit_page(request: Request, allocation_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request,sid,"staff.edit"):
        return HTMLResponse("You do not have permission to manage teacher allocations.",403)
    con=_db();cur=con.cursor();_ensure_teacher_allocations_table(cur)
    allocation=cur.execute("SELECT id,teacher_id,class_id,subject_id FROM teacher_allocations WHERE id=? AND school_id=?",(allocation_id,sid)).fetchone()
    teachers=cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    subjects=cur.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    con.close()
    if not allocation:return HTMLResponse("Teacher allocation not found. <a href='/app/academics/allocations'>Back</a>",404)
    tops="".join("<option value='%s' %s>%s</option>"%(x["id"],"selected" if int(x["id"])==int(allocation["teacher_id"]) else "",escape(str(x["name"] or ""))) for x in teachers)
    cops="".join("<option value='%s' %s>%s%s</option>"%(x["id"],"selected" if int(x["id"])==int(allocation["class_id"]) else "",escape(str(x["name"] or "")),(" — "+escape(str(x["stream"]))) if x["stream"] else "") for x in classes)
    sops="".join("<option value='%s' %s>%s</option>"%(x["id"],"selected" if int(x["id"])==int(allocation["subject_id"]) else "",escape(str(x["name"] or ""))) for x in subjects)
    body=f"""<div class='page'><h1>Edit Teacher Allocation</h1><div class='muted'>Update the teacher, class/stream or subject assigned to this allocation.</div>
<div class='card section'><div class='teacher-allocation-edit-filter-scroll' tabindex='0'><form method='post' action='/app/academics/allocations/edit/{allocation_id}' class='teacher-allocation-edit-filter-form'>
<select name='teacher_id' class='field' required><option value=''>Select Teacher</option>{tops}</select>
<select name='class_id' class='field' required><option value=''>Select Class / Stream</option>{cops}</select>
<select name='subject_id' class='field' required><option value=''>Select Subject</option>{sops}</select>
<button class='btn'>Save Changes</button><a class='btn secondary' href='/app/academics/allocations'>Cancel</a></form></div>
<style>.teacher-allocation-edit-filter-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x;overscroll-behavior-x:contain;padding-bottom:8px}}.teacher-allocation-edit-filter-form{{display:grid;grid-template-columns:260px 260px 260px auto auto;gap:10px;width:max-content;min-width:100%}}.teacher-allocation-edit-filter-form .field{{min-width:0}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{display:inline-block;padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer;white-space:nowrap}}.secondary{{background:#64748b}}</style></div>"""
    return _school_page(request,"Edit Teacher Allocation",body)

@router.post("/app/academics/allocations/edit/{allocation_id}")
def teacher_allocations_edit(request: Request, allocation_id:int, teacher_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request,sid,"staff.edit"):return HTMLResponse("You do not have permission to manage teacher allocations.",403)
    con=_db();cur=con.cursor();_ensure_teacher_allocations_table(cur)
    if not cur.execute("SELECT id FROM teacher_allocations WHERE id=? AND school_id=?",(allocation_id,sid)).fetchone():
        con.close();return HTMLResponse("Teacher allocation not found. <a href='/app/academics/allocations'>Back</a>",404)
    if not (cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()):
        con.close();return HTMLResponse("Invalid selection. <a href='/app/academics/allocations'>Back</a>",400)
    duplicate=cur.execute("SELECT id FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND class_id=? AND subject_id=? AND id<>?",(sid,teacher_id,class_id,subject_id,allocation_id)).fetchone()
    if duplicate:
        con.close();return HTMLResponse("That teacher allocation already exists. <a href='/app/academics/allocations'>Back</a>",400)
    cur.execute("UPDATE teacher_allocations SET teacher_id=?,class_id=?,subject_id=? WHERE id=? AND school_id=?",(teacher_id,class_id,subject_id,allocation_id,sid))
    _audit(cur,sid,request,"TEACHER_ALLOCATION_EDIT","Edited teacher allocation %s"%(allocation_id,))
    con.commit();con.close()
    return RedirectResponse("/app/academics/allocations",303)

@router.post("/app/academics/allocations/delete/{allocation_id}")
def teacher_allocations_delete(request: Request,allocation_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request,sid,"staff.edit"):return HTMLResponse("You do not have permission to manage teacher allocations.",403)
    con=_db();cur=con.cursor();_ensure_teacher_allocations_table(cur)
    allocation=cur.execute("SELECT id FROM teacher_allocations WHERE id=? AND school_id=?",(allocation_id,sid)).fetchone()
    if not allocation:
        con.close()
        return HTMLResponse("Teacher allocation not found. <a href='/app/academics/allocations'>Back</a>",404)
    try:
        cur.execute("DELETE FROM teacher_allocations WHERE id=? AND school_id=?",(allocation_id,sid))
        if not cur.rowcount:
            con.rollback();con.close()
            return HTMLResponse("Teacher allocation could not be deleted. <a href='/app/academics/allocations'>Back</a>",409)
        _audit(cur,sid,request,"TEACHER_ALLOCATION_DELETE","Deleted teacher allocation %s"%(allocation_id,))
        con.commit()
    except Exception as exc:
        try: con.rollback()
        except Exception: pass
        con.close()
        print("DAVISCHOOL TEACHER ALLOCATION DELETE FAILED:",repr(exc),flush=True)
        return HTMLResponse("Unable to delete this teacher allocation. <a href='/app/academics/allocations'>Back</a>",500)
    con.close()
    return RedirectResponse("/app/academics/allocations" + (("?ds_tab=" + quote(request.query_params.get("ds_tab"),safe="")) if request.query_params.get("ds_tab") else ""),303)

@router.get("/app/academics/analysis", response_class=HTMLResponse)
def new_analysis(request: Request, exam_id:str="", exam_ids:str="", class_id:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view academic analysis.", 403)
    con=_db();cur=con.cursor()
    try:
        _ensure_grading_table(cur)
    except Exception as exc:
        print("DAVISCHOOL ANALYSIS GRADING TABLE FALLBACK:", repr(exc), flush=True)
    try:
        _ensure_academic_locks_table(cur)
    except Exception as exc:
        print("DAVISCHOOL ANALYSIS LOCK TABLE FALLBACK:", repr(exc), flush=True)
    try:
        exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    except Exception as exc:
        print("DAVISCHOOL ANALYSIS CONTEXT FAILED:", repr(exc), flush=True)
        try: con.rollback()
        except Exception: pass
        exams=[]; classes=[]
    selected_exam_ids=_parse_assessment_ids(exam_ids, exam_id)
    if not selected_exam_ids and exams:
        selected_exam_ids=[int(exams[0]["id"])]
    eid=selected_exam_ids[0] if selected_exam_ids else 0
    cid=int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
    try: grading_rules = _load_grading_rules(cur, sid)
    except Exception as exc:
        print("DAVISCHOOL ANALYSIS GRADING RULES FALLBACK:", repr(exc), flush=True); grading_rules=[]
    try: overall_rules = _load_overall_grading_rules(cur, sid)
    except Exception as exc:
        print("DAVISCHOOL ANALYSIS OVERALL RULES FALLBACK:", repr(exc), flush=True); overall_rules=[]
    stats=[]; student_results=[]
    if eid:
        placeholders=",".join("?" for _ in selected_exam_ids)
        q="""SELECT sub.id subject_id,sub.name subject,COUNT(m.id) entries,COALESCE(AVG(m.marks),0) avg_mark,
          COALESCE(MAX(m.marks),0) high,COALESCE(MIN(m.marks),0) low
          FROM subjects sub LEFT JOIN marks m ON m.subject_id=sub.id AND m.exam_id IN (PLACEHOLDERS) AND m.school_id=?
          LEFT JOIN students sm ON sm.id=m.student_id AND sm.school_id=m.school_id"""
        q=q.replace("PLACEHOLDERS",placeholders)
        params=list(selected_exam_ids)+[sid]
        if cid:q+=" AND sm.class_id=?";params.append(cid)
        q+=" WHERE sub.school_id=? GROUP BY sub.id,sub.name ORDER BY sub.name";params.append(sid)
        try: stats=cur.execute(q,params).fetchall()
        except Exception as exc:
            print("DAVISCHOOL SUBJECT ANALYSIS QUERY FALLBACK:", repr(exc), flush=True)
            try: con.rollback()
            except Exception: pass
            stats=[]
        students=cur.execute("SELECT id,name,admission_no,class_id FROM students WHERE school_id=? "+("AND class_id=? " if cid else "")+"ORDER BY name",([sid,cid] if cid else [sid])).fetchall()
        for st in students:
            try:
                result=_student_result_for_assessments(cur,sid,int(st["id"]),selected_exam_ids,grading_rules,overall_rules)
            except Exception as exc:
                print("DAVISCHOOL ANALYSIS STUDENT RESULT FALLBACK:", repr(exc), flush=True)
                result={"details":[],"total":0.0,"points":0.0,"count":0,"average":0.0,"overall_grade":"—"}
            try:
                locks=cur.execute("""SELECT COUNT(*) c FROM academic_locks
                    WHERE school_id=? AND exam_id=? AND class_id=?""",(sid,eid,st["class_id"])).fetchone()["c"]
            except Exception as exc:
                print("DAVISCHOOL ANALYSIS LOCK COUNT FALLBACK:", repr(exc), flush=True)
                locks=0
            student_results.append((st,result,int(locks or 0)))
    con.close()
    eopts="".join(f"<option value='{e['id']}' {'selected' if int(e['id']) in selected_exam_ids else ''}>{escape(str(e['name']))}</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    rows="".join(f"<tr><td>{escape(str(x['subject']))}</td><td>{x['entries']}</td><td>{float(x['avg_mark'] or 0):.2f}</td><td>{x['high']}</td><td>{x['low']}</td></tr>" for x in stats)
    ranked=sorted(student_results,key=lambda z:(-float(z[1]["total"]),str(z[0]["name"])))
    rank_map={int(z[0]["id"]):i+1 for i,z in enumerate(ranked)}
    student_rows="".join(f"<tr><td>{escape(str(st['admission_no'] or ''))}</td><td>{escape(str(st['name']))}</td><td>{res['count']}</td><td>{res['total']:.1f}</td><td>{res['average']:.1f}%</td><td>{escape(str(res['overall_grade']))}</td><td>{rank_map.get(int(st['id']),'—')} / {len(ranked)}</td></tr>" for st,res,_ in student_results)
    body=f"""<div class='page'><h1>Academic Analysis</h1><div class='muted'>Analysis uses the same configured grading and points engine used by report cards.</div><div class='card section'><form method='get' action='/app/academics/analysis' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_ids' class='field' multiple size='3'>{eopts}</select><select name='class_id' class='field'><option value=''>All classes</option>{copts}</select><button class='btn'>Analyse</button></form></div><div class='card section'><h2>Subject Performance</h2><table><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No marks found.</td></tr>'}</tbody></table></div><div class='card section'><h2>Student Results</h2><table><thead><tr><th>Admission</th><th>Student</th><th>Subjects</th><th>Total</th><th>Average</th><th>Overall Grade</th><th>Position</th></tr></thead><tbody>{student_rows or '<tr><td colspan=7>No student results found.</td></tr>'}</tbody></table></div></div><div class='card section no-print'><h2>Overall Grade Comments & Signatures</h2><div class='muted'>Set comments for each configured overall grade. These comments are selected automatically from the learner's overall grade and printed on the report card. Class teacher names come from Roles & Permissions → Class Teacher Assignments; the principal is taken automatically from the staff member whose role is Principal.</div><table><thead><tr><th>Overall Grade</th><th>Class Teacher Comment</th><th>Principal Comment</th><th>Action</th></tr></thead><tbody>{''.join(f"<tr><td><b>{escape(str(r['grade']))}</b></td><td colspan='2'><form method='post' action='/app/report-cards/overall-grade-comments'><input type='hidden' name='rule_id' value='{r['id']}'><textarea name='class_teacher_comment' rows='2' class='field' placeholder='Class teacher comment'>{escape(str(r['class_teacher_comment'] or ''))}</textarea><textarea name='principal_comment' rows='2' class='field' style='margin-top:6px' placeholder='Principal comment'>{escape(str(r['principal_comment'] or ''))}</textarea><button class='btn' style='margin-top:6px'>Save Grade Comments</button></form></td><td></td></tr>" for r in cur.execute("SELECT id,grade,class_teacher_comment,principal_comment FROM overall_grading_rules WHERE school_id=? ORDER BY min_total DESC,id DESC",(sid,)).fetchall()) or "<tr><td colspan='4'>Configure overall grading bands first.</td></tr>"}</tbody></table><div class='grid' style='margin-top:14px'><div><b>Class Teacher</b>: {escape(str(class_teacher_name or 'Not Assigned'))}<div style='margin-top:18px;border-bottom:1px solid #172033;width:85%'></div><small>Signature</small></div><div><b>Principal</b>: {escape(str(principal_name or 'Not Assigned'))}<div style='margin-top:18px;border-bottom:1px solid #172033;width:85%'></div><small>Signature</small></div></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Academic Analysis",body)

@router.post("/app/report-cards/overall-grade-comments")
def save_overall_grade_comments(request: Request, rule_id:int=Form(...), class_teacher_comment:str=Form(""), principal_comment:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to edit overall-grade report comments.",403)
    con=_db();cur=con.cursor();_ensure_overall_grading_table(cur)
    cur.execute("UPDATE overall_grading_rules SET class_teacher_comment=?, principal_comment=? WHERE id=? AND school_id=?",
                (class_teacher_comment.strip(),principal_comment.strip(),rule_id,sid))
    _audit(cur,sid,request,"OVERALL_GRADE_REPORT_COMMENTS","Updated grade-based report card comments")
    con.commit();con.close()
    return RedirectResponse("/app/report-cards?tab=overall-comments",303)

@router.post("/app/report-cards/subject-comment")
def save_subject_comment(request: Request, student_id:int=Form(...), exam_id:int=Form(...), subject_id:int=Form(...), comment:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to edit report comments.", 403)
    con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
    valid=cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone() and cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
    if not valid: con.close(); return HTMLResponse("Invalid report selection.",400)
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO subject_performance_comments(school_id,student_id,exam_id,subject_id,comment,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(school_id,student_id,exam_id,subject_id) DO UPDATE SET comment=excluded.comment,updated_at=excluded.updated_at",
                (sid,student_id,exam_id,subject_id,comment.strip(),now))
    con.commit();con.close()
    return RedirectResponse(f"/app/report-cards?student_id={student_id}&exam_id={exam_id}",303)

@router.post("/app/report-cards/class-teacher-comment")
def save_class_teacher_comment(request: Request, student_id:int=Form(...), exam_id:int=Form(...), comment:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to edit report comments.", 403)
    con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
    valid=cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone() and cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
    if not valid: con.close(); return HTMLResponse("Invalid report selection.",400)
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO class_teacher_comments(school_id,student_id,exam_id,comment,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(school_id,student_id,exam_id) DO UPDATE SET comment=excluded.comment,updated_at=excluded.updated_at",
                (sid,student_id,exam_id,comment.strip(),now))
    con.commit();con.close()
    return RedirectResponse(f"/app/report-cards?student_id={student_id}&exam_id={exam_id}",303)

@router.get("/app/report-card-settings",response_class=HTMLResponse)
def report_card_settings(request: Request, exam_id:int=0, saved:int=0):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to manage report card dates.", 403)
    con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
    exams=cur.execute("SELECT id,name FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    if not exam_id and exams:
        exam_id=int(exams[0]["id"])
    selected=cur.execute("SELECT * FROM report_card_settings WHERE school_id=? AND exam_id=? ORDER BY id DESC LIMIT 1",(sid,exam_id)).fetchone() if exam_id else None
    con.close()
    options="".join(f"<option value='{e['id']}' {'selected' if int(e['id'])==exam_id else ''}>{escape(str(e['name']))}</option>" for e in exams)
    notice="<div style='margin:10px 0;padding:10px;border-radius:8px;background:#ecfdf5;color:#166534;font-weight:700'>Report card dates saved successfully.</div>" if saved else ""
    return _school_page(request,"Report Card Settings",f"""<div class='card section'><h2>Report Card Dates</h2><p class='muted'>Set the opening and closing dates for each examination/reporting period.</p>{notice}<form id='report-card-dates-form' method='post' action='/app/report-card-settings' autocomplete='off'><select id='report-card-exam' name='exam_id' class='field report-exam-field' required><option value='' disabled>Select examination</option>{options}</select><label>Date of Opening</label><input type='date' name='opening_date' class='field report-date-field' style='width:100%;min-height:52px;font-size:17px;padding:12px 14px;box-sizing:border-box' value='{escape(str(selected["opening_date"] if selected else ""))}'><label>Date of Closing</label><input type='date' name='closing_date' class='field report-date-field' style='width:100%;min-height:52px;font-size:17px;padding:12px 14px;box-sizing:border-box' value='{escape(str(selected["closing_date"] if selected else ""))}'><button type='submit' name='save_dates' value='1' class='btn report-save-btn'>Save Dates</button></form><style>.report-exam-field{{width:100%;min-height:58px;font-size:18px;padding:14px 16px;box-sizing:border-box}}.report-date-field{{min-height:58px!important;font-size:18px!important}}.report-save-btn{{margin-top:12px;min-height:52px;padding:13px 22px;font-size:16px;cursor:pointer}}</style></div>""")

@router.post("/app/report-card-settings")
def save_report_card_settings(request: Request, exam_id:int=Form(...), opening_date:str=Form(""), closing_date:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to manage report card dates.", 403)
    con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
    if not cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone():
        con.close();return HTMLResponse("Invalid examination.",400)
    # Save the dates exactly as submitted. Browser date controls already provide valid ISO date values.
    # Save the exact values submitted for this examination. Update every
    # matching legacy row so older duplicate settings cannot override the
    # newly entered dates when the page is reopened.
    matches=cur.execute("SELECT id FROM report_card_settings WHERE school_id=? AND exam_id=?",(sid,exam_id)).fetchall()
    if matches:
        for row in matches:
            cur.execute(
                "UPDATE report_card_settings SET opening_date=?,closing_date=? WHERE id=? AND school_id=?",
                (opening_date,closing_date,row["id"],sid)
            )
    else:
        cur.execute(
            "INSERT INTO report_card_settings(school_id,exam_id,opening_date,closing_date) VALUES(?,?,?,?)",
            (sid,exam_id,opening_date,closing_date)
        )
    con.commit()
    # Verify the values were actually persisted before redirecting.
    saved_row=cur.execute(
        "SELECT opening_date,closing_date FROM report_card_settings WHERE school_id=? AND exam_id=? ORDER BY id DESC LIMIT 1",
        (sid,exam_id)
    ).fetchone()
    con.close()
    if not saved_row or str(saved_row["opening_date"] or "") != opening_date or str(saved_row["closing_date"] or "") != closing_date:
        return HTMLResponse("The report card dates could not be saved. Please try again. <a href='/app/report-card-settings'>Back</a>",500)
    return RedirectResponse(f"/app/report-card-settings?exam_id={exam_id}&saved=1",303)
@router.get("/app/report-cards/class-preview", response_class=HTMLResponse)
def report_cards_class_preview(request: Request, exam_ids: str="", class_id: str=""):
    sid=_school_session(request)
    if not sid:
        return RedirectResponse("/", status_code=303)
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view report cards.", 403)
    try:
        cid=int(class_id)
    except Exception:
        cid=0
    selected_exam_ids=_parse_assessment_ids(exam_ids, "")
    if not cid or not selected_exam_ids:
        return HTMLResponse("<h2>Choose a class/stream and assessment first.</h2>", 400)
    con=_db(); cur=con.cursor()
    try:
        cls=cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?",(cid,sid)).fetchone()
        if not cls:
            return HTMLResponse("Class/stream not found.",404)
        students=cur.execute("""SELECT s.* FROM students s
            WHERE s.school_id=? AND s.class_id=? ORDER BY s.name,s.id""",(sid,cid)).fetchall()
        exams=cur.execute("SELECT id,name,year,term FROM exams WHERE school_id=? AND id IN (%s) ORDER BY id" %
                           ",".join("?" for _ in selected_exam_ids), [sid]+selected_exam_ids).fetchall()
        school=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
        _ensure_report_card_fields(cur); _ensure_overall_grading_table(cur)
        grading_rules=_load_grading_rules(cur,sid)
        overall_rules=_load_overall_grading_rules(cur,sid)
        class_teacher_name,principal_name=_report_signatories(cur,sid,cid)
        school_name=escape(str(school["name"] or "DaviSchool")) if school else "DaviSchool"
        postal=escape("P.O. Box %s" % str(school["postal_address"] or "")) if school and "postal_address" in school.keys() and school["postal_address"] else ""
        postal_code=escape(str(school["postal_code"] or "")) if school and "postal_code" in school.keys() and school["postal_code"] else ""
        logo=str(school["logo_data"] or "") if school and "logo_data" in school.keys() else ""
        school_phone=escape(str(school["phone"] or "")) if school and "phone" in school.keys() and school["phone"] else ""
        school_email=escape(str(school["email"] or "")) if school and "email" in school.keys() and school["email"] else ""
        doc_contact_lines="".join("<div>%s</div>" % x for x in [postal,postal_code] if x)
        doc_right_lines="".join("<div>%s</div>" % x for x in [("☎ "+school_phone) if school_phone else "",("✉ "+school_email) if school_email else ""] if x)
        brand="<div class='doc-header'><div class='doc-logo'>%s</div><div class='doc-school-block'><div class='doc-school'>%s</div><div class='doc-contact'>%s</div></div><div class='doc-right'>%s</div></div>" % (("<img src='%s' alt='School logo'>" % escape(logo)) if logo else "🏫",school_name,doc_contact_lines,doc_right_lines)
        exam_text=", ".join(escape(str(e["name"] or "")) for e in exams)
        term_values=[]
        for e in exams:
            tv=str(e["term"] or "").strip()
            if tv and tv not in term_values: term_values.append(tv)
        term_text=", ".join(escape(x) for x in term_values)
        report_dates=cur.execute("SELECT opening_date,closing_date FROM report_card_settings WHERE school_id=? AND exam_id=? LIMIT 1",(sid,selected_exam_ids[0])).fetchone()
        opening_text=escape(str(report_dates["opening_date"] or "")) if report_dates else ""
        closing_text=escape(str(report_dates["closing_date"] or "")) if report_dates else ""
        cards=[]
        generated_at=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%d/%m/%Y %H:%M:%S EAT")
        footer_html="<div class='print-footer'><i>DaviSchool Management System</i> · Generated: %s</div>" % generated_at
        for st in students:
            try:
                result=_student_result_for_assessments(cur,sid,int(st["id"]),selected_exam_ids,grading_rules,overall_rules)
            except Exception as exc:
                import traceback
                print("DAVISCHOOL BULK REPORT STUDENT RESULT ERROR: id=%s name=%s error=%r" %
                      (st["id"], st["name"], exc), flush=True)
                print(traceback.format_exc(), flush=True)
                cards.append("""<section class='report-card'>
                    <h1>Student Report Card</h1>
                    <div class='student'><b>%s</b><span>Admission No: %s</span></div>
                    <div style='margin-top:20px;padding:14px;border:1px solid #fca5a5;background:#fff1f2'>
                      This student's report could not be generated. Other students in the selected class/stream remain available.
                    </div>
                </section>""" % (escape(str(st["name"] or "")), escape(str(st["admission_no"] or ""))))
                continue
            details=[]
            for rr,mark,grade,points in result["details"]:
                saved_comment=""
                # Comments are stored per student + subject + assessment.
                # Check every selected assessment so a saved comment is not
                # missed merely because it belongs to a different selected exam.
                for comment_exam_id in selected_exam_ids:
                    try:
                        sc=cur.execute("SELECT comment FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=? LIMIT 1",
                                       (sid,st["id"],int(comment_exam_id),rr["subject_id"])).fetchone()
                    except Exception as exc:
                        print("DAVISCHOOL BULK REPORT SUBJECT COMMENT FALLBACK:", repr(exc), flush=True)
                        try: cur.connection.rollback()
                        except Exception: pass
                        sc=None
                    candidate=str(sc["comment"] or "").strip() if sc else ""
                    if candidate:
                        saved_comment=candidate
                        break
                # If a saved subject comment is missing, derive it from the same
                # subject grading rule used for the displayed mark/grade.
                if not saved_comment:
                    try:
                        _, _, saved_comment = _subject_grade_details(
                            cur, sid, int(rr["subject_id"]), float(mark), grading_rules
                        )
                    except Exception as exc:
                        print("DAVISCHOOL BULK REPORT COMMENT DERIVATION FALLBACK:", repr(exc), flush=True)
                        saved_comment = ""
                details.append("<tr><td>%s</td><td>%.1f</td><td>%s</td><td>%.1f</td><td>%s</td></tr>" %
                               (escape(str(rr["name"])),float(mark),escape(str(grade)),float(points),escape(str(saved_comment))))
            try:
                grade_rule=cur.execute("SELECT class_teacher_comment,principal_comment FROM overall_grading_rules WHERE school_id=? AND grade=? ORDER BY id DESC LIMIT 1",
                                       (sid,str(result.get("overall_grade","")))).fetchone()
            except Exception as exc:
                print("DAVISCHOOL BULK REPORT GRADE COMMENT FALLBACK:", repr(exc), flush=True)
                try: cur.connection.rollback()
                except Exception: pass
                grade_rule=None
            cards.append("""<section class='report-card'>
              %s<h1>Student Report Card</h1>
              <div class='student'><span><b>Student Name:</b> <span class='student-name-value'>%s</span></span><span><b>Adm No:</b> %s</span></div>
              <div class='student student-class'><span><b>Class:</b> %s</span><span><b>Stream:</b> %s</span></div>
              <div class='student student-term'><span><b>Term:</b> %s</span><span><b>Assessment:</b> %s</span></div>
              <table><thead><tr><th>Subject</th><th>Marks</th><th>Grade</th><th>Points</th><th>Performance Comments</th></tr></thead>
              <tbody>%s</tbody></table>
              <div class='summary'><div><b>Total marks</b><br><b>%.1f</b></div><div><b>Average</b><br><b>%.1f%%</b></div><div><b>Total points</b><br><b>%.1f</b></div><div><b>Overall grade</b><br><b>%s</b></div></div>
              <div class='comments'><b>Class Teacher's Comment</b><p>%s</p><b>Principal's Comment</b><p>%s</p></div>
              <div class='sign'><div><b>Class Teacher</b>: %s<hr>Signature</div><div><b>Principal</b>: %s<hr>Signature</div></div>
              <div class='report-dates'><b>Date of closing:</b> %s <b>Date of opening:</b> %s</div>
            </section>""" % (brand,escape(str(st["name"])),escape(str(st["admission_no"] or "")),
                              escape(str(cls["name"] or "")),escape(str(cls["stream"] or "")),
                              term_text,exam_text,"".join(details),float(result["total"]),float(result["average"]),float(result["points"]),
                              escape(str(result["overall_grade"])),escape(str((grade_rule["class_teacher_comment"] if grade_rule else "") or "")),
                              escape(str((grade_rule["principal_comment"] if grade_rule else "") or "")),
                              escape(str(class_teacher_name or "Not Assigned")),escape(str(principal_name or "Not Assigned")),
                              closing_text,opening_text) + footer_html)
        body="".join(cards) if cards else "<section class='report-card'><h2>No students found in this class/stream.</h2></section>"
        html="""<!doctype html><html><head><meta charset='utf-8'><title>Class Report Cards Preview</title>
        <style>
        *{box-sizing:border-box}body{margin:0;background:#eef2f7;color:#172033;font-family:Arial,sans-serif}
        .toolbar{position:sticky;top:0;z-index:20;background:#172033;color:#fff;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px}
        .toolbar button{border:0;border-radius:8px;padding:10px 15px;font-weight:800;cursor:pointer;margin-left:6px}
        .toolbar .print{background:#176B3A;color:#fff}.report-card{background:#fff;max-width:1000px;margin:18px auto;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,.12);page-break-after:always}
        .doc-header{display:flex;align-items:flex-start;gap:14px;border-top:2px solid #2E8B57;border-bottom:3px solid #176B3A;padding:8px 4px 10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center;flex:0 0 86px}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school-block{flex:1;min-width:0}.doc-school{font-size:20px;line-height:1.15;font-weight:900;text-transform:uppercase;color:#176B3A}.doc-contact{font-size:10px;color:#334155;margin-top:5px;line-height:1.55}.doc-contact div{display:block;margin:1px 0}.doc-right{font-size:10px;color:#176B3A;line-height:1.65;text-align:left;min-width:155px}.doc-right div{display:block;margin:1px 0}.print-footer{margin-top:18px;padding-top:5px;border-top:2px solid #2E8B57;text-align:center;font-size:8px;color:#176B3A}.print-footer i{font-style:italic}
        h1{text-align:center;font-size:20px;margin:18px 0 8px}.student{display:flex;gap:28px;flex-wrap:wrap;font-size:14px;margin:4px 0}.student span{font-weight:600}.student-name-value{font-size:18px;font-weight:900;display:inline-block}.student-class,.student-term{margin-top:6px}.report-dates{display:flex;gap:24px;flex-wrap:wrap;font-size:12px;margin:14px 0 0}.report-dates b{font-weight:900}
        table{width:100%%;border-collapse:collapse}th,td{border:1px solid #172033;padding:7px;font-size:12px;text-align:left}th{font-weight:900}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}.summary>div{border:1px solid #cbd5e1;padding:10px;text-align:center}.comments{margin-top:14px}.comments p{border:1px solid #cbd5e1;min-height:38px;padding:8px}.sign{display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:30px}.sign hr{margin-top:20px;border:0;border-top:1px solid #172033;width:120px;margin-left:0}
        @page{size:A4 portrait;margin:12mm} @media print{body{background:#fff}.toolbar{display:none!important}.report-card{box-shadow:none;margin:0;max-width:none;width:100%%;min-height:0;page-break-after:always;break-after:page}}
        </style></head><body><div class='toolbar'><div><b>🖨️ Class / Stream Report Cards Preview</b><div style='font-size:12px;opacity:.8'>%s · %d student(s)</div></div><div><button class='print' onclick='window.print()'>🖨️ Print All Report Cards</button><button onclick='window.close()'>✕ Close</button></div></div>%s</body></html>""" % (escape(str(cls["name"] or ""))+(((" · "+escape(str(cls["stream"] or ""))) if cls["stream"] else "")),len(students),body)
        return HTMLResponse(html)
    except Exception as exc:
        import traceback
        print("DAVISCHOOL BULK REPORT PREVIEW ERROR:", repr(exc), flush=True)
        print(traceback.format_exc(), flush=True)
        detail=escape("%s: %s" % (type(exc).__name__, str(exc) or "no exception message"))
        return HTMLResponse("""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Report Card Preview Error</title>
        <style>body{font-family:Arial,sans-serif;background:#f8fafc;padding:24px;color:#172033}.box{max-width:850px;margin:auto;background:#fff;border:1px solid #fecaca;border-radius:12px;padding:22px}code{display:block;background:#f1f5f9;padding:12px;border-radius:8px;white-space:pre-wrap}</style></head>
        <body><div class='box'><h2>Report Card Preview could not be generated</h2><p>The selected class/stream could not be rendered. No student data has been deleted.</p><b>Technical detail</b><code>%s</code><p>Please use this exact technical detail when reporting the error.</p></div></body></html>""" % detail, status_code=500)
    finally:
        con.close()

@router.get("/app/report-cards", response_class=HTMLResponse)
def report_cards(request: Request, exam_id:str="", exam_ids:str="", student_id:str="", class_id:str="", tab:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view report cards.", 403)
    con=_db();cur=con.cursor();_ensure_report_card_fields(cur);_ensure_overall_grading_table(cur);_ensure_class_teacher_assignments_table(cur)
    exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    students=cur.execute("SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    cid=int(class_id) if class_id.isdigit() else 0
    selected_exam_ids=_parse_assessment_ids(exam_ids, exam_id)
    if not selected_exam_ids and exams:
        selected_exam_ids=[int(exams[0]["id"])]
    eid=selected_exam_ids[0] if selected_exam_ids else 0
    # Do not silently select the first student when a class/stream was generated for bulk reports.
    # A class-only selection must stay in bulk mode so the preview contains every student in that class/stream.
    stid=int(student_id) if student_id.isdigit() else (0 if cid else (int(students[0]["id"]) if students else 0))
    st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(stid,sid)).fetchone()
    rows=[];comment=""; class_teacher_comment=""; subject_comments={}; opening_date=""; closing_date=""; report_final=False; position="—"; class_total_students=0; class_teacher_name=""; principal_name=""; grade_comment_rule=None
    if st and eid:
        rows=cur.execute("""SELECT sub.id subject_id,sub.name,m.marks FROM marks m JOIN subjects sub ON sub.id=m.subject_id
          WHERE m.school_id=? AND m.student_id=? AND m.exam_id=? ORDER BY sub.name""",(sid,stid,eid)).fetchall()
        # A report is final only when every subject with a mark for this student
        # has been finalized for the student's class.
        _ensure_academic_locks_table(cur)
        marked_subjects=[r["subject_id"] for r in rows if r["marks"] is not None and str(r["marks"])!=""]
        if marked_subjects:
            locked_count=cur.execute("SELECT COUNT(*) c FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id IN (%s)" %
                                     ",".join("?" for _ in marked_subjects),
                                     [sid,eid,st["class_id"]]+marked_subjects).fetchone()["c"]
            report_final=(int(locked_count)==len(marked_subjects))
        elif rows:
            report_final=False
        # Position is calculated from total marks among students in the same class.
        totals=cur.execute("""SELECT s.id,COALESCE(SUM(m.marks),0) total
          FROM students s LEFT JOIN marks m ON m.student_id=s.id AND m.school_id=? AND m.exam_id=?
          WHERE s.school_id=? AND s.class_id=? GROUP BY s.id ORDER BY total DESC,s.id""",
          (sid,eid,sid,st["class_id"])).fetchall()
        class_total_students=len(totals)
        last_total=None
        last_position=0
        for idx,t in enumerate(totals,1):
            total_value=float(t["total"] or 0)
            if last_total is None or total_value != last_total:
                last_position=idx
                last_total=total_value
            if int(t["id"])==int(st["id"]):
                position=last_position
                break
        cm=cur.execute("SELECT comment FROM report_comments WHERE school_id=? AND student_id=? AND exam_id=? ORDER BY id DESC LIMIT 1",(sid,stid,eid)).fetchone()
        comment=cm["comment"] if cm else ""
        tc=cur.execute("SELECT comment FROM class_teacher_comments WHERE school_id=? AND student_id=? AND exam_id=? LIMIT 1",(sid,stid,eid)).fetchone()
        class_teacher_comment=tc["comment"] if tc else ""
        try:
            report_grading_rules=_load_grading_rules(cur,sid)
        except Exception as exc:
            print("DAVISCHOOL REPORT GRADING COMMENT FALLBACK:",repr(exc),flush=True)
            report_grading_rules={}
        for sr in rows:
            saved_comment=""
            # A multi-assessment report may display an averaged subject mark.
            # Find the saved comment across all selected assessments instead
            # of only checking the first assessment.
            for comment_exam_id in selected_exam_ids:
                sc=cur.execute("SELECT comment FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=? LIMIT 1",
                               (sid,stid,int(comment_exam_id),sr["subject_id"])).fetchone()
                candidate=str(sc["comment"] or "").strip() if sc else ""
                if candidate:
                    saved_comment=candidate
                    break
            if not saved_comment and sr["marks"] is not None:
                try:
                    _,_,saved_comment=_subject_grade_details(cur,sid,int(sr["subject_id"]),sr["marks"],report_grading_rules)
                except Exception as exc:
                    print("DAVISCHOOL REPORT GRADE COMMENT FALLBACK:",repr(exc),flush=True)
            subject_comments[int(sr["subject_id"])]=saved_comment
        rs=cur.execute("SELECT opening_date,closing_date FROM report_card_settings WHERE school_id=? AND exam_id=? LIMIT 1",(sid,eid)).fetchone()
        if rs:
            opening_date=rs["opening_date"] or ""
            closing_date=rs["closing_date"] or ""
    eopts="".join(f"<option value='{e['id']}' {'selected' if e['id']==eid else ''}>{escape(str(e['name']))} {escape(str(e['year'] or ''))}</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))}{(' · '+escape(str(c['stream'] or ''))) if c['stream'] else ''}</option>" for c in classes)
    sopts="".join(f"<option value='{s['id']}' {'selected' if s['id']==stid else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    result=_student_result_for_assessments(cur,sid,stid,selected_exam_ids,_load_grading_rules(cur,sid),_load_overall_grading_rules(cur,sid)) if st and selected_exam_ids else {"rows":[],"details":[],"total":0.0,"points":0.0,"count":0,"average":0.0,"overall_grade":"—"}
    total=result["total"];avg=result["average"]
    if st:
        class_teacher_name, principal_name = _report_signatories(cur,sid,int(st["class_id"] or 0))
    if result.get("overall_grade") and result.get("overall_grade") != "—":
        grade_comment_rule=cur.execute("SELECT class_teacher_comment,principal_comment FROM overall_grading_rules WHERE school_id=? AND grade=? ORDER BY id DESC LIMIT 1",(sid,str(result["overall_grade"]))).fetchone()
    markrows="".join(f"<tr><td>{escape(str(r['name']))}</td><td>{mark:.1f}</td><td>{escape(str(grade))}</td><td>{points:.1f}</td></tr>" for r,mark,grade,points in result["details"])
    school_row=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
    school_name=escape(str(school_row["name"] or "DaviSchool")) if school_row else "DaviSchool"
    school_email=escape(str(school_row["email"] or "")) if school_row else ""
    school_phone=escape(str(school_row["phone"] or "")) if school_row else ""
    school_postal=escape("P.O. Box %s" % str(school_row["postal_address"] or "")) if school_row and "postal_address" in school_row.keys() and school_row["postal_address"] else ""
    school_postal_code=escape(str(school_row["postal_code"] or "")) if school_row and "postal_code" in school_row.keys() else ""
    school_logo=str(school_row["logo_data"] or "") if school_row and "logo_data" in school_row.keys() else ""
    doc_contact_lines = "".join("<div>%s</div>" % x for x in [school_postal, school_postal_code] if x)
    doc_right_lines = "".join("<div>%s</div>" % x for x in [("☎ "+school_phone) if school_phone else "", ("✉ "+school_email) if school_email else ""] if x)
    doc_brand="<div class='doc-header'><div class='doc-logo'>%s</div><div class='doc-school-block'><div class='doc-school'>%s</div><div class='doc-contact'>%s</div></div><div class='doc-right'>%s</div></div>" % (("<img src='%s' alt='School logo'>" % escape(school_logo)) if school_logo else "🏫",school_name,doc_contact_lines,doc_right_lines)
    final_banner=("<div style='padding:10px;background:#dcfce7;color:#166534;border-radius:9px;font-weight:800'>✅ FINAL REPORT — all recorded subjects are finalized.</div>" if report_final else "<div style='padding:10px;background:#fef3c7;color:#92400e;border-radius:9px;font-weight:800'>📝 DRAFT REPORT — finalize all recorded subject marks before printing the final report.</div>")
    print_script="""<script>
function printReportCard(){
  var doc=document.getElementById('report');
  if(!doc){window.print();return;}
  var w=window.open('', '_blank', 'width=1100,height=800');
  if(!w){window.print();return;}
  var generatedAt=new Intl.DateTimeFormat('en-KE',{
    timeZone:'Africa/Nairobi',year:'numeric',month:'2-digit',day:'2-digit',
    hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false
  }).format(new Date())+' EAT';
  var css='*{box-sizing:border-box}body{margin:0;background:#fff;color:#172033;font-family:Arial,sans-serif}.report-document{display:block!important;width:100%!important;margin:0!important;padding:0!important;border:0!important;box-shadow:none!important}.no-print{display:none!important}.doc-header{display:flex;align-items:flex-start;gap:14px;border-top:2px solid #2E8B57;border-bottom:3px solid #176B3A;padding:8px 4px 10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center;flex:0 0 86px}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school-block{flex:1;min-width:0}.doc-school{font-size:20px;line-height:1.15;font-weight:900;text-transform:uppercase;color:#176B3A}.doc-contact{font-size:10px;color:#334155;margin-top:5px;line-height:1.55}.doc-contact div{display:block;margin:1px 0}.doc-right{font-size:10px;color:#176B3A;line-height:1.65;text-align:left;min-width:155px}.doc-right div{display:block;margin:1px 0}.marksheet-school{display:none!important}table{width:100%;border-collapse:collapse}th{background:#176B3A!important;color:#fff!important}th,td{border:1px solid #176B3A;padding:6px;font-size:10px;text-align:left}.kpi{font-size:18px;font-weight:900}.card{border:0;box-shadow:none}.report-comment-form{display:none}.print-footer{position:fixed;left:0;right:0;bottom:0;text-align:center;border-top:2px solid #2E8B57;padding-top:4px;font-size:8px;color:#176B3A;background:#fff}@page{size:A4;margin:10mm 10mm 15mm}';
  var footer='<div class="print-footer"><i>DaviSchool Management System</i> · Generated: '+generatedAt+'</div>';
  var previewBar='<div class="report-preview-bar no-print"><div><b>🖨️ Student Report Card Preview</b><span>Review the complete report card before printing.</span></div><div><button type="button" onclick="window.print()">🖨️ Print Report Card</button><button type="button" onclick="window.close()">✕ Close Preview</button></div></div>';
  var previewCss='.report-preview-bar{position:sticky;top:0;z-index:9999;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 16px;margin:0 0 14px;background:#172033;color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.15);font-family:Arial,sans-serif}.report-preview-bar span{display:block;font-size:12px;font-weight:400;margin-top:3px;opacity:.85}.report-preview-bar button{border:0;border-radius:8px;padding:10px 14px;margin-left:7px;font-weight:800;cursor:pointer;background:#fff;color:#172033}.report-preview-bar button:first-child{background:#176B3A;color:#fff}@media print{.report-preview-bar{display:none!important}}';
  var html='<!doctype html><html><head><meta charset="utf-8"><title>Student Report Card Preview</title><style>'+css+previewCss+'</style></head><body>'+previewBar+doc.outerHTML.replace('id="report"','class="report-document"')+footer+'</body></html>';
  w.document.open();w.document.write(html);w.document.close();w.focus();
}
</script>""";
    bulk_btn=(f"<div style='margin-top:10px;padding:12px;border:2px solid #176B3A;border-radius:10px;background:#f0fdf4'><b>📚 Whole Class / Stream Report</b><div class='muted' style='margin:5px 0 9px'>The preview below contains every student in the selected class/stream, not just the first student.</div><a class='btn' style='display:inline-block;text-decoration:none;background:#176B3A' target='_blank' href='/app/report-cards/class-preview?exam_ids={quote(','.join(str(x) for x in selected_exam_ids))}&class_id={cid}'>🖨️ Print All Class / Stream Reports</a> <a class='btn' style='display:inline-block;text-decoration:none' href='/app/report-cards/class-pdf?exam_ids={quote(','.join(str(x) for x in selected_exam_ids))}&class_id={cid}'>⬇️ Download All Class / Stream Reports</a></div>" if cid and eid else "")
    report_pdf_query=quote(",".join(str(x) for x in selected_exam_ids))
    print_btn=((
        "<button type='button' class='btn' style='margin-top:8px;background:#176B3A' onclick='printReportCard()'>🖨️ Print MarkSheet / Report Preview</button> "
        + f"<a class='btn' style='display:inline-block;margin-top:8px;text-decoration:none' href='/app/report-cards/pdf?exam_ids={report_pdf_query}&student_id={stid}'>⬇️ Download PDF</a>"
    ) if st and eid else "")
    report_html=f"""<div class='card section' id='report' style='background:white'>{doc_brand}<h2>{escape(str(st['name']))}</h2><div class='student'><span><b>Student Name:</b> <span class='student-name-value'>{escape(str(st['name'] or ''))}</span></span><span><b>Adm No:</b> {escape(str(st['admission_no'] or ''))}</span></div><div class='student student-class'><span><b>Class:</b> {escape(str(st['class_name'] or ''))}</span><span><b>Stream:</b> {escape(str(st['stream'] or ''))}</span></div><div class='student student-term'><span><b>Term:</b> {escape(str(exams[0]['term'] or '') if exams else '')}</span><span><b>Assessment:</b> {escape(str(exams[0]['name'] if exams else ''))}</span></div>{final_banner}<table style='margin-top:14px'><thead><tr><th>Subject</th><th>Marks</th><th>Grade</th><th>Points</th><th>Performance Comments</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r['name']))}</td><td>{mark:.1f}</td><td>{escape(str(grade))}</td><td>{points:.1f}</td><td>{escape(str(subject_comments.get(int(r['subject_id']),'')))}</td></tr>" for r,mark,grade,points in result["details"])}</tbody></table><div class='grid'><div class='card'><div class='label'>Subjects</div><div class='kpi'>{len(rows)}</div></div><div class='card'><div class='label'><b>Total marks</b></div><div class='kpi'>{total:.1f}</div></div><div class='card'><div class='label'>Average</div><div class='kpi'>{avg:.1f}%</div></div><div class='card'><div class='label'><b>Total points</b></div><div class='kpi'>{result["points"]:.1f}</div></div><div class='card'><div class='label'><b>Overall grade</b></div><div class='kpi'>{escape(str(result["overall_grade"]))}</div></div><div class='card'><div class='label'>Position</div><div class='kpi'>{position} / {class_total_students}</div></div></div><div class='report-comment-form'><form method='post' action='/app/report-cards/comment'><input type='hidden' name='exam_id' value='{eid}'><input type='hidden' name='student_id' value='{stid}'><textarea name='comment' class='field' rows='3' placeholder='Teacher / principal comment'>{escape(str(comment or ''))}</textarea><button class='btn' style='margin-top:8px'>Save Comment</button></form></div><div style='margin-top:14px'><b>Class Teacher's Comment</b><div style='border:1px solid #cbd5e1;border-radius:8px;padding:10px;min-height:55px'>{escape(str((grade_comment_rule["class_teacher_comment"] if grade_comment_rule else "") or class_teacher_comment or ""))}</div></div><div style='margin-top:14px'><b>Principal's Comment</b><div style='border:1px solid #cbd5e1;border-radius:8px;padding:10px;min-height:55px'>{escape(str((grade_comment_rule["principal_comment"] if grade_comment_rule else "") or ""))}</div></div><div class='grid' style='margin-top:18px'><div><b>Class Teacher: {escape(str(class_teacher_name or 'Not Assigned'))}</b><div style='margin-top:18px;border-bottom:1px solid #172033;width:85%'></div><small>Signature</small></div><div><b>Principal: {escape(str(principal_name or 'Not Assigned'))}</b><div style='margin-top:18px;border-bottom:1px solid #172033;width:85%'></div><small>Signature</small></div></div><div class='report-dates'><b>Date of closing:</b> {escape(str(closing_date or ''))} <b>Date of opening:</b> {escape(str(opening_date or ''))}</div><div style='margin-top:14px'><b>Additional Report Comment</b><div style='border:1px solid #cbd5e1;border-radius:8px;padding:10px;min-height:45px'>{escape(str(comment or ''))}</div></div>{print_btn}{print_script}</div>""" if st else "<div class='card section'>Select a student and examination.</div>"
    subject_editor="".join(f"""<div class='card' style='margin-top:10px'><div style='font-weight:800;margin-bottom:7px'>{escape(str(r['name']))}</div><form method='post' action='/app/report-cards/subject-comment'><input type='hidden' name='student_id' value='{stid}'><input type='hidden' name='exam_id' value='{eid}'><input type='hidden' name='subject_id' value='{r['subject_id']}'><textarea name='comment' class='field' rows='2' placeholder='Performance comment for this subject'>{escape(str(subject_comments.get(int(r['subject_id']),'')))}</textarea><button class='btn' style='margin-top:7px'>Save Subject Comment</button></form></div>""" for r in rows) if st and eid else ""
    teacher_editor=f"""<div class='card section no-print'><h2>Class Teacher's Comment</h2><form method='post' action='/app/report-cards/class-teacher-comment'><input type='hidden' name='student_id' value='{stid}'><input type='hidden' name='exam_id' value='{eid}'><textarea name='comment' class='field' rows='4' placeholder='Enter the class teacher's comment'>{escape(str(class_teacher_comment or ''))}</textarea><button class='btn' style='margin-top:8px'>Save Class Teacher Comment</button></form></div>""" if st and eid else ""
    overall_rows=cur.execute("SELECT id,grade,min_total,max_total,class_teacher_comment,principal_comment FROM overall_grading_rules WHERE school_id=? ORDER BY min_total DESC,id DESC",(sid,)).fetchall()
    overall_comment_rows_html = (
        "".join(
            "<tr><td><b>%s</b></td><td>%.1f%% – %.1f%%</td><td colspan='2'><form method='post' action='/app/report-cards/overall-grade-comments'><input type='hidden' name='rule_id' value='%s'><div class='grid'><textarea name='class_teacher_comment' rows='3' class='field' placeholder='Class teacher performance comment'>%s</textarea><textarea name='principal_comment' rows='3' class='field' placeholder='Principal performance comment'>%s</textarea></div><button class='btn' style='margin-top:8px'>Save Performance Comments</button></form></td><td></td></tr>"
            % (
                escape(str(r["grade"] or "")),
                float(r["min_total"] or 0),
                float(r["max_total"] or 0),
                r["id"],
                escape(str(r["class_teacher_comment"] or "")),
                escape(str(r["principal_comment"] or "")),
            )
            for r in overall_rows
        )
        if overall_rows
        else "<tr><td colspan='5'>No overall grading bands configured. Create the overall grade bands first.</td></tr>"
    )
    overall_comment_editor = (
        "<div class='card section no-print'><h2>Performance Comments by Overall Grade</h2>"
        "<div class='muted'>Set the class teacher and principal performance comment for each overall grade. The matching comments are automatically placed on the student's report card according to the calculated overall grade.</div>"
        "<table><thead><tr><th>Grade</th><th>Range</th><th>Class Teacher Performance Comment</th><th>Principal Performance Comment</th><th>Action</th></tr></thead><tbody>"
        + overall_comment_rows_html
        + "</tbody></table>"
        "<div class='grid' style='margin-top:14px'><div><b>Class Teacher:</b> "
        + escape(str(class_teacher_name or "Not Assigned"))
        + "<div style='margin-top:18px;border-bottom:1px solid #172033;width:85%'></div><small>Signature</small></div><div><b>Principal:</b> "
        + escape(str(principal_name or "Not Assigned"))
        + "<div style='margin-top:18px;border-bottom:1px solid #172033;width:85%'></div><small>Signature</small></div></div></div>"
    )
    body=f"""<div class='page'><h1>Report Cards</h1><div class='muted'>Select one or more assessments. Multiple selections are averaged subject-by-subject before grade, points, total and overall average are calculated.</div><div class='muted' style='margin-top:4px'>Printable and downloadable documents include the DaviSchool Management System footer and exact generation time.</div><div class='card section no-print'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_ids' class='field' multiple size='3'>{eopts}</select><select name='class_id' class='field'><option value=''>Choose class for bulk report cards</option>{copts}</select><select name='student_id' class='field'><option value=''>Choose individual student (optional)</option>{sopts}</select><button class='btn'>Generate</button></form>{bulk_btn}</div><div class='card section no-print' style='display:flex;gap:8px;flex-wrap:wrap'><a class='btn' href='/app/report-cards?exam_id={eid}&student_id={stid}&tab=report'>📄 Report Card</a><a class='btn' href='/app/report-cards?exam_id={eid}&student_id={stid}&tab=overall-comments'>📝 Overall Grade Comments & Signatures</a><a class='btn' href='/app/report-card-settings?exam_id={eid}'>📅 Report Dates</a></div>{report_html if tab != 'overall-comments' else ''}{teacher_editor if tab != 'overall-comments' else ''}{overall_comment_editor if tab == 'overall-comments' else ''}<div class='card section no-print'><h2>Subject Performance Comments</h2><div class='muted'>Enter an individual performance comment for each subject. These comments appear on the printed report card.</div>{subject_editor or '<div class="muted" style="margin-top:10px">Select a student and examination first.</div>'}</div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff}}@media print{{.no-print{{display:none!important}}}}</style>"""
    return _school_page(request,"Report Cards",body)

@router.post("/app/report-cards/comment")
def report_comment(request: Request, exam_id:int=Form(...), student_id:int=Form(...), comment:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to edit report comments.", 403)
    con=_db();cur=con.cursor()
    if cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone():
        cur.execute("INSERT INTO report_comments(school_id,student_id,exam_id,comment,created_at) VALUES(?,?,?,?,?)",(sid,student_id,exam_id,comment.strip(),datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")))
        _audit(cur,sid,request,"REPORT_COMMENT","Updated report comment")
    con.commit();con.close();return RedirectResponse(f"/app/report-cards?exam_id={exam_id}&student_id={student_id}",303)

@router.get("/app/academics/subject-analysis", response_class=HTMLResponse)
def subject_analysis_page(request: Request, exam_id: str = "", exam_ids: str = "", class_id: str = ""):
    sid=_school_session(request)
    if not sid:
        return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view subject analysis.", 403)
    con=_db(); cur=con.cursor()
    try:
        exams=cur.execute("SELECT id,name,year,term FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
        subjects=cur.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
        selected_exam_ids=_parse_assessment_ids(exam_ids, exam_id)
        if not selected_exam_ids and exams:
            selected_exam_ids=[int(exams[0]["id"])]
        eid=selected_exam_ids[0] if selected_exam_ids else 0
        cid=int(class_id) if class_id.isdigit() else 0
        stats=[]
        if selected_exam_ids:
            sql="""SELECT sub.id,sub.name subject,COUNT(m.id) entries,
                    COALESCE(AVG(m.marks),0) average,
                    COALESCE(MAX(m.marks),0) highest,
                    COALESCE(MIN(m.marks),0) lowest
                   FROM subjects sub
                   LEFT JOIN marks m ON m.subject_id=sub.id AND m.exam_id IN (PLACEHOLDERS) AND m.school_id=?
                   LEFT JOIN students st ON st.id=m.student_id AND st.school_id=m.school_id
                   WHERE sub.school_id=?"""
            params=list(selected_exam_ids)+[sid,sid]
            if cid:
                sql+=" AND st.class_id=?"
                params.append(cid)
            sql+=" GROUP BY sub.id,sub.name ORDER BY sub.name"
            stats=cur.execute(sql.replace("PLACEHOLDERS",",".join("?" for _ in selected_exam_ids)),params).fetchall()
    except Exception as exc:
        print("DAVISCHOOL SUBJECT ANALYSIS PAGE FAILED:",repr(exc),flush=True)
        try: con.rollback()
        except Exception: pass
        exams=[]; classes=[]; subjects=[]; eid=0; cid=0; stats=[]
    finally:
        pass
    eopts="".join(f"<option value='{e['id']}' {'selected' if int(e['id'])==eid else ''}>{escape(str(e['name']))} {escape(str(e['year'] or ''))}</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if int(c['id'])==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    subject_comment_rules=_load_grading_rules(cur,sid) if stats else {}
    rows="".join(f"<tr><td>{escape(str(r['subject']))}</td><td>{int(r['entries'] or 0)}</td><td>{float(r['average'] or 0):.2f}</td><td>{float(r['highest'] or 0):.1f}</td><td>{float(r['lowest'] or 0):.1f}</td><td>{escape(str(_subject_grade_details(cur,sid,int(r['id']),float(r['average'] or 0),subject_comment_rules)[2] or ''))}</td></tr>" for r in stats)
    con.close()
    body=f"""<div class='page'><h1>Subject Analysis</h1><div class='muted'>Compare subject performance for the selected examination and class.</div>
<div class='card section'><form method='get' action='/app/academics/subject-analysis' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_id' class='field'><option value=''>Select examination</option>{eopts}</select><select name='class_id' class='field'><option value=''>All classes</option>{copts}</select><button class='btn'>Analyse</button></form></div>
<div class='card section'><div class='marksheet-scroll subject-analysis-scroll' tabindex='0'><table class='subject-analysis-table'><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th><th>Performance Comment</th></tr></thead><tbody>{rows or "<tr><td colspan='6'>No marks found for the selected examination/class.</td></tr>"}</tbody></table></div></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}.subject-analysis-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y}}.subject-analysis-table{{width:max-content;min-width:760px}}</style>"""
    return _school_page(request,"Subject Analysis",body)

@router.get("/app/academics/student-analysis", response_class=HTMLResponse)
def student_analysis_page(request: Request, exam_id: str = "", exam_ids: str = "", student_id: str = ""):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view student analysis.", 403)
    con=_db(); cur=con.cursor()
    exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    students=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(sid,)).fetchall()
    selected_exam_ids=_parse_assessment_ids(exam_ids, exam_id)
    if not selected_exam_ids and exams:
        selected_exam_ids=[int(exams[0]["id"])]
    eid=selected_exam_ids[0] if selected_exam_ids else 0
    stid=int(student_id) if student_id.isdigit() else (int(students[0]["id"]) if students else 0)
    st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(stid,sid)).fetchone()
    analysis_grading_rules=_load_grading_rules(cur,sid) if st and eid else []
    result=_student_result_for_assessments(cur,sid,stid,selected_exam_ids,analysis_grading_rules,None) if st and eid else {"details":[],"total":0.0,"points":0.0,"count":0,"average":0.0,"overall_grade":"—"}
    eopts="".join(f"<option value='{e['id']}' {'selected' if int(e['id']) in selected_exam_ids else ''}>{escape(str(e['name']))} {escape(str(e['year'] or ''))}</option>" for e in exams)
    sopts="".join(f"<option value='{s['id']}' {'selected' if int(s['id'])==stid else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    rows="".join(f"<tr><td>{escape(str(r['name']))}</td><td>{mark:.1f}</td><td>{escape(str(grade))}</td><td>{points:.1f}</td><td>{escape(str(_subject_grade_details(cur,sid,int(r['subject_id']),mark,analysis_grading_rules)[2] or ''))}</td></tr>" for r,mark,grade,points in result["details"])
    con.close()
    body=f"""<div class='page'><h1>Student Analysis</h1><div class='muted'>Detailed performance for one learner using the same grading engine as the report card.</div>
<div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_ids' class='field' multiple size='4'>{eopts}</select><select name='student_id' class='field'>{sopts}</select><button class='btn'>Analyse</button><a class='btn' style='text-decoration:none;text-align:center' href='/app/academics/student-analysis/pdf?exam_ids={",".join(str(x) for x in selected_exam_ids)}&student_id={stid}'>⬇️ Download PDF</a></form></div>
<div class='grid'><div class='card'><div class='label'>Student</div><div class='kpi' style='font-size:18px'>{escape(str(st["name"] if st else "—"))}</div></div><div class='card'><div class='label'>Total</div><div class='kpi'>{result["total"]:.1f}</div></div><div class='card'><div class='label'>Average</div><div class='kpi'>{result["average"]:.1f}%</div></div><div class='card'><div class='label'>Overall Grade</div><div class='kpi'>{escape(str(result["overall_grade"]))}</div></div></div>
<div class='card section'><h2>Subject Results</h2><table><thead><tr><th>Subject</th><th>Mark</th><th>Grade</th><th>Points</th><th>Performance Comment</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No marks recorded for this student and examination.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Student Analysis",body)


@router.get("/app/academics/class-analysis", response_class=HTMLResponse)
def class_analysis_page(request: Request, exam_id: str = "", exam_ids: str = "", class_id: str = ""):
    sid=_school_session(request)
    if not sid:
        return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view class analysis.", 403)
    con=_db(); cur=con.cursor()
    try:
        exams=cur.execute("SELECT id,name,year,term FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
        selected_exam_ids=_parse_assessment_ids(exam_ids, exam_id)
        if not selected_exam_ids and exams:
            selected_exam_ids=[int(exams[0]["id"])]
        eid=selected_exam_ids[0] if selected_exam_ids else 0
        cid=int(class_id) if class_id.isdigit() else 0
        stats=[]; ranking=[]
        if selected_exam_ids and cid:
            placeholders=",".join("?" for _ in selected_exam_ids)
            stats=cur.execute("""SELECT sub.id subject_id,sub.name subject,COUNT(m.id) entries,COALESCE(AVG(m.marks),0) average,
                COALESCE(MAX(m.marks),0) highest,COALESCE(MIN(m.marks),0) lowest
                FROM subjects sub LEFT JOIN marks m ON m.subject_id=sub.id AND m.exam_id IN (PLACEHOLDERS) AND m.school_id=?
                LEFT JOIN students st ON st.id=m.student_id AND st.school_id=m.school_id
                WHERE sub.school_id=? AND st.class_id=? GROUP BY sub.id,sub.name ORDER BY sub.name""".replace("PLACEHOLDERS",placeholders),
                list(selected_exam_ids)+[sid,sid,cid]).fetchall()
            students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? AND class_id=? ORDER BY name",(sid,cid)).fetchall()
            for st in students:
                try:
                    res=_student_result_for_assessments(cur,sid,int(st["id"]),selected_exam_ids,_load_grading_rules(cur,sid),None)
                except Exception as exc:
                    print("DAVISCHOOL CLASS ANALYSIS RESULT FALLBACK:",repr(exc),flush=True)
                    res={"total":0.0,"average":0.0,"overall_grade":"—","count":0}
                ranking.append((st,res))
            ranking.sort(key=lambda x:(-float(x[1]["total"]),str(x[0]["name"])))
    except Exception as exc:
        print("DAVISCHOOL CLASS ANALYSIS PAGE FAILED:",repr(exc),flush=True)
        try: con.rollback()
        except Exception: pass
        exams=[]; classes=[]; eid=0; cid=0; stats=[]; ranking=[]
    finally:
        con.close()
    eopts="".join(f"<option value='{e['id']}' {'selected' if int(e['id']) in selected_exam_ids else ''}>{escape(str(e['name']))} {escape(str(e['year'] or ''))}</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if int(c['id'])==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    class_comment_rules=_load_grading_rules(cur,sid) if stats else {}
    ar="".join(f"<tr><td>{escape(str(x['subject']))}</td><td>{int(x['entries'] or 0)}</td><td>{float(x['average'] or 0):.2f}</td><td>{float(x['highest'] or 0):.1f}</td><td>{float(x['lowest'] or 0):.1f}</td><td>{escape(str(_subject_grade_details(cur,sid,int(x['subject_id']),float(x['average'] or 0),class_comment_rules)[2] or ''))}</td></tr>" for x in stats)
    sr="".join(f"<tr><td>{i}</td><td>{escape(str(st['admission_no'] or ''))}</td><td>{escape(str(st['name']))}</td><td>{res['total']:.1f}</td><td>{res['average']:.1f}%</td><td>{escape(str(res['overall_grade']))}</td></tr>" for i,(st,res) in enumerate(ranking,1))
    body=f"""<div class='page'><h1>Class Analysis</h1><div class='muted'>Class-level subject performance and learner results.</div>
<div class='card section'><form method='get' action='/app/academics/class-analysis' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_ids' class='field' multiple size='4'><option value=''>Select examination</option>{eopts}</select><select name='class_id' class='field'><option value=''>Select class</option>{copts}</select><button class='btn'>Analyse</button></form></div>
<div class='card section'><h2>Subject Performance</h2><div class='marksheet-scroll class-analysis-scroll' tabindex='0'><table class='class-analysis-table'><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th><th>Performance Comment</th></tr></thead><tbody>{ar or "<tr><td colspan='6'>Select an examination and class.</td></tr>"}</tbody></table></div></div>
<div class='card section'><h2>Learner Ranking</h2><div class='marksheet-scroll class-analysis-scroll' tabindex='0'><table class='class-analysis-table'><thead><tr><th>Position</th><th>Admission</th><th>Student</th><th>Total</th><th>Average</th><th>Grade</th></tr></thead><tbody>{sr or "<tr><td colspan='6'>No learner results found.</td></tr>"}</tbody></table></div></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}.class-analysis-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y}}.class-analysis-table{{width:max-content;min-width:760px}}</style>"""
    return _school_page(request,"Class Analysis",body)

@router.get("/app/students/promotion", response_class=HTMLResponse)
def student_promotion_page(request: Request, class_id: str = ""):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if not _require_permission(request, sid, "students.edit"):
        return HTMLResponse("You do not have permission to promote or transfer students.", 403)
    con = _db()
    cur = con.cursor()
    _ensure_student_history_table(cur)
    classes = cur.execute(
        "SELECT * FROM classes WHERE school_id=? ORDER BY name,stream", (sid,)
    ).fetchall()
    cid = int(class_id) if class_id.isdigit() else 0
    students = cur.execute(
        """SELECT s.id,s.name,s.admission_no,s.class_id,c.name class_name,c.stream
           FROM students s LEFT JOIN classes c ON c.id=s.class_id
           WHERE s.school_id=? AND s.class_id=?
           ORDER BY s.name""",
        (sid, cid)
    ).fetchall() if cid else []
    con.commit()
    con.close()
    copts = "".join(
        f"<option value='{c['id']}' {'selected' if int(c['id'])==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>"
        for c in classes
    )
    topts = "".join(
        f"<option value='{c['id']}'>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>"
        for c in classes
        if int(c["id"]) != cid
    )
    rows = "".join(
        f"<tr><td>{escape(str(s['admission_no'] or ''))}</td><td>{escape(str(s['name']))}</td>"
        f"<td>{escape(str(s['class_name'] or ''))} {escape(str(s['stream'] or ''))}</td>"
        f"<td><select name='to_class_{s['id']}' class='field'><option value=''>Keep current class</option>{topts}</select></td></tr>"
        for s in students
    )
    body = f"""<div class='page'><h1>Student Promotion / Transfer</h1>
<div class='muted'>Move learners between classes while preserving their existing marks, attendance and financial records. Every change is recorded in the student class history.</div>
<div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr auto;gap:10px'>
<select name='class_id' class='field'><option value=''>Select current class</option>{copts}</select>
<button class='btn'>Load Students</button></form></div>
<div class='card section'><form method='post' action='/app/students/promotion'>
<input type='hidden' name='from_class_id' value='{cid}'>
<table><thead><tr><th>Admission</th><th>Student</th><th>Current Class</th><th>Promote / Transfer To</th></tr></thead>
<tbody>{rows or "<tr><td colspan='4'>Select a class to load its students.</td></tr>"}</tbody></table>
{"<button class='btn' style='margin-top:12px'>Save Class Changes</button>" if students else ""}
</form></div>
<div class='card section'><b>Important:</b> Promotion changes only the student's current class. Historical academic records remain attached to their original examination, year and school.</div>
</div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:white}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}</style>"""
    return _school_page(request, "Student Promotion / Transfer", body)


@router.post("/app/students/promotion")
async def student_promotion_save(request: Request, from_class_id: int = Form(...)):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if not _require_permission(request, sid, "students.edit"):
        return HTMLResponse("You do not have permission to promote or transfer students.", 403)
    form = await request.form()
    con = _db()
    cur = con.cursor()
    _ensure_student_history_table(cur)
    if not cur.execute(
        "SELECT id FROM classes WHERE id=? AND school_id=?", (from_class_id, sid)
    ).fetchone():
        con.close()
        return HTMLResponse("Invalid current class. <a href='/app/students/promotion'>Back</a>", 400)
    changed = 0
    now = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    for key, value in form.multi_items():
        if not key.startswith("to_class_"):
            continue
        try:
            student_id = int(key.split("_", 2)[2])
            to_class_id = int(str(value)) if str(value).isdigit() else 0
        except Exception:
            continue
        if not to_class_id or to_class_id == from_class_id:
            continue
        if not cur.execute(
            "SELECT id FROM classes WHERE id=? AND school_id=?", (to_class_id, sid)
        ).fetchone():
            continue
        student = cur.execute(
            "SELECT id,class_id FROM students WHERE id=? AND school_id=? AND class_id=?",
            (student_id, sid, from_class_id)
        ).fetchone()
        if not student:
            continue
        cur.execute(
            "UPDATE students SET class_id=? WHERE id=? AND school_id=?",
            (to_class_id, student_id, sid)
        )
        cur.execute(
            """INSERT INTO student_class_history
               (school_id,student_id,from_class_id,to_class_id,changed_at,changed_by,reason)
               VALUES(?,?,?,?,?,?,?)""",
            (sid, student_id, from_class_id, to_class_id, now,
             request.session.get("email", ""), "Promotion / transfer")
        )
        _audit(cur, sid, request, "STUDENT_CLASS_CHANGE",
               f"Moved student {student_id} from class {from_class_id} to {to_class_id}")
        changed += 1
    con.commit()
    con.close()
    return RedirectResponse(f"/app/students/promotion?class_id={from_class_id}&changed={changed}", 303)


@router.get("/app/attendance", response_class=HTMLResponse)
def attendance_page(request: Request, class_id:str="", date:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "attendance.view"):
        return HTMLResponse("You do not have permission to view attendance.", 403)
    today=date or datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d")
    cid=int(class_id) if class_id.isdigit() else 0
    con=_db();cur=con.cursor()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    students=cur.execute("SELECT s.id,s.name,s.admission_no,COALESCE(a.status,'Present') status FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.school_id=? AND a.date=? WHERE s.school_id=? AND s.class_id=? ORDER BY s.name",(sid,today,sid,cid)).fetchall() if cid else []
    con.close()
    opts="".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    rows="".join(f"<tr><td>{escape(str(s['admission_no'] or ''))}</td><td>{escape(str(s['name']))}</td><td><select name='status_{s['id']}' class='field'><option {'selected' if s['status']=='Present' else ''}>Present</option><option {'selected' if s['status']=='Absent' else ''}>Absent</option><option {'selected' if s['status']=='Late' else ''}>Late</option><option {'selected' if s['status']=='Excused' else ''}>Excused</option></select></td></tr>" for s in students)
    body=f"""<div class='page'><h1>Attendance</h1><div class='muted'>Daily class register with bulk status saving.</div><div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='class_id' class='field'><option value=''>Select class</option>{opts}</select><input type='date' name='date' value='{today}' class='field'><button class='btn'>Load Register</button></form></div><div class='card section'><form method='post' action='/app/attendance/save'><input type='hidden' name='class_id' value='{cid}'><input type='hidden' name='date' value='{today}'><table><thead><tr><th>Admission</th><th>Student</th><th>Status</th></tr></thead><tbody>{rows or '<tr><td colspan=3>Select a class and date.</td></tr>'}</tbody></table>{'<button class="btn" style="margin-top:12px">Save Attendance</button>' if students else ''}</form></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Attendance",body)

@router.post("/app/attendance/save")
async def attendance_save(request: Request, class_id:int=Form(...), date:str=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "attendance.edit"):
        return HTMLResponse("You do not have permission to edit attendance.", 403)
    form=await request.form();con=_db();cur=con.cursor()
    if not _teacher_class_authorized(cur, request, sid, class_id):
        con.close()
        return HTMLResponse("You are not allocated to this class.", 403)
    students=cur.execute("SELECT id FROM students WHERE school_id=? AND class_id=?",(sid,class_id)).fetchall()
    for s in students:
        status=str(form.get(f"status_{s['id']}","Present"))
        old=cur.execute("SELECT id FROM attendance WHERE school_id=? AND student_id=? AND date=?",(sid,s["id"],date)).fetchone()
        if old: cur.execute("UPDATE attendance SET status=? WHERE id=? AND school_id=?",(status,old["id"],sid))
        else: cur.execute("INSERT INTO attendance(school_id,student_id,date,status) VALUES(?,?,?,?)",(sid,s["id"],date,status))
    _audit(cur,sid,request,"ATTENDANCE_SAVE",f"Saved attendance for class {class_id} on {date}")
    con.commit();con.close();return RedirectResponse(f"/app/attendance?class_id={class_id}&date={date}",303)


@router.get("/app/users", response_class=HTMLResponse)
def users_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "users.manage"):
        return HTMLResponse("You do not have permission to manage users.", 403)
    con=_db();cur=con.cursor()
    _ensure_user_account_columns(cur, con)
    # Read only this school's accounts. The joins are also school-scoped so
    # a linked profile from another school can never affect the account row.
    users=cur.execute("""SELECT u.*,t.name teacher_name,s.name student_name
        FROM users u
        LEFT JOIN teachers t ON t.id=u.teacher_id AND t.school_id=u.school_id
        LEFT JOIN students s ON s.id=u.student_id AND s.school_id=u.school_id
        WHERE u.school_id=? ORDER BY u.id DESC""",(sid,)).fetchall()
    teachers=cur.execute("SELECT id,name,email FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    _ensure_teacher_allocations_table(cur)
    _ensure_class_teacher_assignments_table(cur)
    classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    assignments=cur.execute("SELECT class_id,teacher_id FROM class_teacher_assignments WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    allocations=cur.execute("""SELECT teacher_id,class_id,subject_id FROM teacher_allocations WHERE school_id=? ORDER BY teacher_id,class_id,subject_id""",(sid,)).fetchall()
    # Resolve the just-created account BEFORE closing the database connection.
    # Previously the fallback query below used a cursor after con.close(), which
    # caused psycopg.OperationalError: the connection is closed and prevented
    # the credentials popup from being rendered.
    created_flag=str(request.query_params.get("created","")).strip()=="1"
    created_email=str(request.query_params.get("email","")).strip().lower()
    created_username=str(request.query_params.get("username","")).strip().lower()
    created_credentials=request.session.pop("created_account_credentials",None) if created_flag else None
    if created_credentials:
        created_username=str(created_credentials.get("username") or "").lower()
    # The saved account row is the authoritative source for the confirmation
    # popup. Session credentials are only a fallback for the generated username.
    created_account=next((u for u in users if created_username and str(u["username"] or "").lower()==created_username), None)
    if not created_account and created_username:
        created_account=cur.execute("SELECT u.*,t.name teacher_name,s.name student_name FROM users u LEFT JOIN teachers t ON t.id=u.teacher_id AND t.school_id=u.school_id LEFT JOIN students s ON s.id=u.student_id AND s.school_id=u.school_id WHERE u.school_id=? AND lower(u.username)=?",(sid,created_username)).fetchone()
    if not created_account and created_email:
        created_account=next((u for u in users if str(u["email"] or "").lower()==created_email), None)
    if not created_account and created_flag and users:
        created_account=users[0]
    # All database reads for this page are complete; close only after the
    # created-account lookup has finished.
    con.close()
    # Use the most recently saved Class Teacher assignment for the account table.
    # The assignment table is class-scoped (UNIQUE school_id + class_id), so a teacher
    # can technically have more than one row in legacy data. The assignments query
    # is explicitly newest-first, and setdefault keeps the newest class authoritative.
    class_by_teacher={}
    for a in assignments:
        class_by_teacher.setdefault(int(a["teacher_id"]), int(a["class_id"]))
    rows=""
    for u in users:
        role_name=str(u["role"] or "")
        linked=escape(str(u["teacher_name"] or u["student_name"] or "—"))
        if role_name=="teacher" and u["teacher_id"] and class_by_teacher.get(int(u["teacher_id"])):
            ca=next((x for x in classes if int(x["id"])==class_by_teacher[int(u["teacher_id"])]),None)
            if ca:
                linked += " · 🏫 " + escape(str(ca["name"] or "")) + ((" · "+escape(str(ca["stream"] or ""))) if ca["stream"] else "")
        safe_name=escape(str(u["full_name"] or "user")).replace("'","&#39;")
        if role_name=="school_admin":
            actions="<span style='display:inline-block;padding:6px 9px;border-radius:7px;background:#f1f5f9;color:#64748b;font-size:11px;font-weight:700'>🔒 Super Admin</span>"
        else:
            actions=f"<div style='display:flex;gap:6px;flex-wrap:wrap'><a href='/app/users/edit/{int(u['id'])}' style='display:inline-block;padding:6px 9px;border-radius:7px;background:#e0f2fe;color:#075985;text-decoration:none;font-size:11px;font-weight:700'>✏️ Edit</a><form method='post' action='/app/users/delete/{int(u['id'])}' style='display:inline' onsubmit=\"return confirm('Delete {safe_name} account? This cannot be undone.')\"><button type='submit' style='border:0;padding:6px 9px;border-radius:7px;background:#fee2e2;color:#991b1b;font-size:11px;font-weight:700;cursor:pointer'>🗑️ Delete</button></form></div>"
        rows += f"<tr><td>{escape(str(u['full_name'] or ''))}</td><td>{escape(str(u['username'] or u['email'] or ''))}</td><td>{escape(str(u['temporary_password'] or '—'))}</td><td>{escape(str(u['email'] or ''))}</td><td>{escape(role_name)}</td><td>{linked}</td><td>{actions}</td></tr>"
    topts="".join(f"<option value='{t['id']}'>{escape(str(t['name']))}</option>" for t in teachers)
    teacher_alloc_map={}
    for a in allocations:
        tid_alloc=int(a["teacher_id"])
        cid_alloc=int(a["class_id"])
        sid_alloc=int(a["subject_id"])
        entry=teacher_alloc_map.setdefault(str(tid_alloc),{"classes":[],"subjects_by_class":{},"has_subject":False})
        if cid_alloc not in entry["classes"]:
            entry["classes"].append(cid_alloc)
        entry["subjects_by_class"].setdefault(str(cid_alloc),[])
        if sid_alloc not in entry["subjects_by_class"][str(cid_alloc)]:
            entry["subjects_by_class"][str(cid_alloc)].append(sid_alloc)
        entry["has_subject"]=True
    class_teacher_map={str(int(a["teacher_id"])):int(a["class_id"]) for a in assignments}
    for tid_alloc,cid_alloc in class_teacher_map.items():
        entry=teacher_alloc_map.setdefault(tid_alloc,{"classes":[],"subjects_by_class":{},"has_subject":False})
        entry["class_teacher_class"]=cid_alloc
    for tid_alloc,entry in teacher_alloc_map.items():
        ct=entry.get("class_teacher_class")
        has_subject=bool(entry.get("has_subject"))
        entry["teacher_type"]="both" if ct and has_subject else ("class_teacher" if ct else "subject_teacher")
    teacher_data_json=json.dumps({str(t["id"]): {"name": str(t["name"] or ""), "email": str(t["email"] or "")} for t in teachers})
    teacher_allocation_json=json.dumps(teacher_alloc_map)
    # Use the one-time session credentials as the primary popup source.
    # The popup must not depend on re-finding the newly-created account row.
    modal_username=escape(str((created_credentials or {}).get("username") or (created_account["username"] if created_account else "") or created_username))
    modal_password=escape(str((created_credentials or {}).get("password") or (created_account["temporary_password"] if created_account else "") or ""))
    credential_modal = ""
    if created_flag and modal_username and modal_password:
        credential_modal = (
            "<div id=\"credentialModal\" style=\"display:flex;position:fixed;inset:0;"
            "background:rgba(15,23,42,.65);z-index:99999;align-items:center;"
            "justify-content:center;padding:20px\">"
            "<div style=\"background:#fff;border-radius:16px;max-width:430px;width:100%;"
            "padding:24px;box-shadow:0 20px 50px rgba(0,0,0,.25)\">"
            "<h2 style=\"margin:0 0 10px\">✅ Account Created</h2>"
            "<p style=\"margin:0 0 16px;color:#475569\">The teacher account has been created successfully. "
            "Save these login credentials.</p>"
            "<div style=\"background:#f8fafc;border-radius:10px;padding:14px;margin-bottom:16px\">"
            "<b>Username</b><div style=\"font-size:20px;font-weight:800;margin:4px 0 12px\">"
            + modal_username
            + "</div><b>Password</b><div style=\"font-size:20px;font-weight:800;margin-top:4px\">"
            + modal_password
            + "</div></div><button type=\"button\" id=\"credentialOkay\" class=\"btn\" "
            "style=\"width:100%\">OK</button></div></div>"
            "<script>(function(){function closeCredentialModal(){"
            "var m=document.getElementById('credentialModal');if(m)m.style.display='none';}"
            "var o=document.getElementById('credentialOkay');"
            "if(o)o.addEventListener('click',closeCredentialModal);})();</script>"
        )
    sopts="".join(f"<option value='{s['id']}'>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    created_display_username=escape(str((created_credentials or {}).get("username") or request.query_params.get("username","")))
    created_display_password=escape(str((created_credentials or {}).get("password") or (created_account["temporary_password"] if created_account else "") or ""))
    created_display_name=escape(str((created_account["full_name"] if created_account else "") or (created_account["email"] if created_account else "")))
    if created_flag and created_account:
        success_block=f"<div class='card section' style='border:1px solid #86efac;background:#f0fdf4;color:#166534'><b>✅ Account created successfully.</b> {created_display_name} is now in the Accounts table.<br><br><b>Username:</b> {created_display_username}<br><b>Temporary Password:</b> {created_display_password}<br><span style='font-size:12px'>Please save these credentials before leaving this page.</span></div>"
    elif created_flag:
        success_block="<div class='card section' style='border:1px solid #fecaca;background:#fef2f2;color:#991b1b'><b>Account was saved but could not be found in this school's Accounts list.</b> Please refresh and report this message if it remains.</div>"
    else:
        success_block=""
    body=f"""<div class='page'><h1>User Management</h1><div class='muted'>Create school accounts and link them to staff or students.</div>
{success_block}
{credential_modal}<div class='card section'><h2>Create user account</h2>
<div class='muted' style='margin-bottom:12px'>For teacher accounts, select the teacher from the existing Teachers records. The School Admin assigns the teacher's role, class/stream and subjects here; no teacher name needs to be retyped.</div>
<form method='post' action='/app/users/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px' id='createUserForm'>
<select name='role' id='newRole' class='field'><option value='teacher'>Teacher</option><option value='school_admin'>School Admin</option><option value='parent'>Parent</option><option value='student'>Student</option><option value='accountant'>Accountant</option><option value='registrar'>Registrar</option></select>
<select name='teacher_id' id='newTeacher' class='field'><option value=''>Select Teacher from Teachers Records</option>{topts}</select>
<input name='email' id='newTeacherEmail' type='email' placeholder='Email from teacher record (optional)' class='field'>
<div class='muted' style='grid-column:1/-1;padding:10px;background:#f8fafc;border-radius:9px'>Username and password are generated automatically when the account is created.</div>
<select name='teacher_type' id='teacherType' class='field'><option value='subject_teacher'>Subject Teacher</option><option value='class_teacher'>Class Teacher</option><option value='both'>Class Teacher + Subject Teacher</option></select>
<div id='classFieldWrap' style='display:none;grid-column:1/-1'><label style='display:block;font-weight:800;color:#334155;margin:2px 0 6px'>Classes / Streams</label><select id='classIdsSelect' class='field' multiple size='4' title='Classes automatically linked to this teacher'>{''.join(f"<option value='{x['id']}'>{escape(str(x['name']))}{(' — '+escape(str(x['stream'] or ''))) if x['stream'] else ''}</option>" for x in classes)}</select><div class='muted' style='margin-top:5px'>Classes are filled automatically from the teacher's existing Subject Allocations / Class Teacher assignment.</div></div>
<div id='subjectFieldWrap' style='display:none;grid-column:1/-1'><label style='display:block;font-weight:800;color:#334155;margin:2px 0 6px'>Subjects</label><select id='subjectIdsSelect' class='field' multiple size='4' title='Subjects automatically linked to this teacher'>{''.join(f"<option value='{x['id']}'>{escape(str(x['name']))}</option>" for x in subjects)}</select><div class='muted' style='margin-top:5px'>Subjects are filled automatically from the teacher's existing allocations.</div></div>
<input type='hidden' name='class_ids_csv' id='classIdsCsv'><input type='hidden' name='subject_ids_csv' id='subjectIdsCsv'>
<select name='student_id' class='field'><option value=''>Link student (for student/parent account)</option>{sopts}</select>
<button class='btn' style='grid-column:1/-1'>Create Account</button></form>
<div class='muted' style='margin-top:10px'>Class Teacher: select exactly one class/stream. Subject Teacher: select all classes/streams and subjects they teach. Both: assign both.</div>
</div>
<script>
(function(){{
 const role=document.getElementById('newRole'), teacher=document.getElementById('newTeacher'), email=document.getElementById('newTeacherEmail');
 const type=document.getElementById('teacherType'), cs=document.getElementById('classIdsSelect'), ss=document.getElementById('subjectIdsSelect');
 const cw=document.getElementById('classFieldWrap'), sw=document.getElementById('subjectFieldWrap');
 const cc=document.getElementById('classIdsCsv'), sc=document.getElementById('subjectIdsCsv');
 async function loadTeacherLinks(){{
   if(role.value!=='teacher'){{
     cw.style.display='none'; sw.style.display='none'; cc.value=''; sc.value=''; return;
   }}
   cw.style.display='block'; sw.style.display='block';
   try{{
     if(!teacher.value){{
       email.value=''; cc.value=''; sc.value='';
       Array.from(cs.options).forEach(o=>{{o.selected=false;o.hidden=true;o.disabled=true;}});
       Array.from(ss.options).forEach(o=>{{o.hidden=true;o.disabled=true;o.selected=false;}});
       return;
     }}
     const response=await fetch('/app/users/teacher-links?teacher_id='+encodeURIComponent(teacher.value),{{credentials:'same-origin',cache:'no-store'}});
     if(!response.ok) throw new Error('Teacher links request failed');
     const data=await response.json();
     if(data.teacher && data.teacher.email) email.value=data.teacher.email;
     if(data.teacher_type) type.value=data.teacher_type;
     const wantedClasses=new Set((data.classes||[]).map(String));
     Array.from(cs.options).forEach(o=>{{
       const allowed=wantedClasses.has(String(o.value));
       o.hidden=!allowed;
       o.disabled=!allowed;
       o.selected=allowed;
     }});
     const allowed=new Set();
     Object.values(data.subjects_by_class||{{}}).forEach(list=>(list||[]).forEach(v=>allowed.add(String(v))));
     Array.from(ss.options).forEach(o=>{{
       const isAllowed=allowed.has(String(o.value));
       o.hidden=!isAllowed;
       o.disabled=!isAllowed;
       o.selected=isAllowed;
     }});
     cc.value=Array.from(cs.selectedOptions).map(o=>o.value).join(',');
     sc.value=Array.from(ss.selectedOptions).map(o=>o.value).join(',');
   }}catch(err){{
     console.error('Teacher allocation load failed',err);
   }}
 }}
 teacher.addEventListener('change',loadTeacherLinks);
 role.addEventListener('change',loadTeacherLinks);
 cs.addEventListener('change',function(){{
   cc.value=Array.from(cs.selectedOptions).map(o=>o.value).join(',');
   if(role.value==='teacher' && teacher.value) loadTeacherLinks();
 }});
 ss.addEventListener('change',function(){{sc.value=Array.from(ss.selectedOptions).map(o=>o.value).join(',');}});
 document.getElementById('createUserForm').addEventListener('submit',function(){{
   cc.value=Array.from(cs.selectedOptions).map(o=>o.value).join(',');
   sc.value=Array.from(ss.selectedOptions).map(o=>o.value).join(',');
 }});
}})();
</script>
</div>
<div class='card section'><h2>Accounts ({len(users)})</h2><div style='overflow-x:auto'><table><thead><tr><th>Name</th><th>Username</th><th>Password</th><th>Email</th><th>Role</th><th>Linked profile / class</th><th>Actions</th></tr></thead><tbody>{rows or '<tr><td colspan=7>No users yet.</td></tr>'}</tbody></table></div></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"User Management",body)

@router.get("/app/users/edit/{uid}", response_class=HTMLResponse)
def users_edit_page(request: Request, uid: int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "users.manage"):
        return HTMLResponse("You do not have permission to manage users.",403)
    con=_db();cur=con.cursor()
    user=cur.execute("SELECT * FROM users WHERE id=? AND school_id=?",(uid,sid)).fetchone()
    teachers=cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    _ensure_class_teacher_assignments_table(cur)
    classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    assigned_class=cur.execute("SELECT class_id FROM class_teacher_assignments WHERE school_id=? AND teacher_id=? ORDER BY id DESC LIMIT 1",(sid,int(user["teacher_id"] or 0))).fetchone() if user["teacher_id"] else None
    con.close()
    if not user:return HTMLResponse("User account not found. <a href='/app/users'>Back</a>",404)
    if str(user["role"] or "")=="school_admin":
        return HTMLResponse("School Admin accounts can only be edited by the Super Admin. <a href='/app/users'>Back</a>",403)
    topts="".join(f"<option value='{t['id']}' {'selected' if user['teacher_id'] and int(user['teacher_id'])==int(t['id']) else ''}>{escape(str(t['name']))}</option>" for t in teachers)
    sopts="".join(f"<option value='{s['id']}' {'selected' if user['student_id'] and int(user['student_id'])==int(s['id']) else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    classopts="".join(f"<option value='{x['id']}' {'selected' if assigned_class and int(assigned_class['class_id'])==int(x['id']) else ''}>{escape(str(x['name']))}{(' — '+escape(str(x['stream'] or ''))) if x['stream'] else ''}</option>" for x in classes)
    body=f"""<div class='page'><h1>✏️ Edit User</h1><div class='muted'>Update the account details and linked profile.</div>
<div class='card section'><form method='post' action='/app/users/edit/{uid}' style='display:grid;grid-template-columns:repeat(2,1fr);gap:10px'>
<input name='full_name' required value="{escape(str(user['full_name'] or ''))}" placeholder='Full name' class='field'><input name='email' type='email' required value="{escape(str(user['email'] or ''))}" placeholder='Email' class='field'>
<input name='password' type='password' minlength='8' placeholder='New password (optional)' class='field'><input name='password_confirm' type='password' minlength='8' placeholder='Confirm new password' class='field'>
<select name='role' class='field'><option value='teacher' {'selected' if user['role']=='teacher' else ''}>Teacher</option><option value='parent' {'selected' if user['role']=='parent' else ''}>Parent</option><option value='student' {'selected' if user['role']=='student' else ''}>Student</option><option value='accountant' {'selected' if user['role']=='accountant' else ''}>Accountant</option><option value='registrar' {'selected' if user['role']=='registrar' else ''}>Registrar</option></select>
<select name='teacher_id' class='field'><option value=''>Link teacher (optional)</option>{topts}</select><select name='class_id' class='field'><option value=''>Link class (for Class Teacher)</option>{classopts}</select><select name='student_id' class='field'><option value=''>Link student (optional)</option>{sopts}</select>
<div style='grid-column:1/-1;display:flex;gap:8px;justify-content:flex-end'><a href='/app/users' style='padding:11px 16px;border:1px solid #dbe2ea;border-radius:9px;text-decoration:none;color:#334155'>Cancel</a><button class='btn'>💾 Save Changes</button></div></form></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Edit User",body)

@router.post("/app/users/edit/{uid}")
def users_edit(request: Request, uid: int, full_name:str=Form(...), email:str=Form(...), password:str=Form(""), password_confirm:str=Form(""), role:str=Form(...), teacher_id:str=Form(""), class_id:str=Form(""), student_id:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "users.manage"):
        return HTMLResponse("You do not have permission to manage users.",403)
    allowed={"teacher","parent","student","accountant","registrar"}
    con=_db();cur=con.cursor()
    user=cur.execute("SELECT * FROM users WHERE id=? AND school_id=?",(uid,sid)).fetchone()
    if not user: con.close(); return HTMLResponse("User account not found. <a href='/app/users'>Back</a>",404)
    if str(user["role"] or "")=="school_admin": con.close(); return HTMLResponse("School Admin accounts can only be edited by the Super Admin. <a href='/app/users'>Back</a>",403)
    if role not in allowed: con.close(); return HTMLResponse("Invalid role. <a href='/app/users'>Back</a>",400)
    email_v=email.strip().lower()
    duplicate=cur.execute("SELECT id FROM users WHERE lower(email)=? AND id<>?",(email_v,uid)).fetchone()
    if duplicate: con.close(); return HTMLResponse("Email already exists. <a href='/app/users'>Back</a>",409)
    tid=int(teacher_id) if teacher_id.isdigit() else None
    stid=int(student_id) if student_id.isdigit() else None
    if tid and not cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(tid,sid)).fetchone(): con.close(); return HTMLResponse("Selected teacher does not belong to this school. <a href='/app/users'>Back</a>",400)
    if stid and not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(stid,sid)).fetchone(): con.close(); return HTMLResponse("Selected student does not belong to this school. <a href='/app/users'>Back</a>",400)
    if role=="teacher" and not tid: con.close(); return HTMLResponse("Teacher accounts must be linked to a teacher profile. <a href='/app/users'>Back</a>",400)
    if role in ("student","parent") and not stid: con.close(); return HTMLResponse("Student and parent accounts must be linked to a student profile. <a href='/app/users'>Back</a>",400)
    if role not in ("teacher","student","parent") and (tid or stid): con.close(); return HTMLResponse("This role cannot be linked to a teacher or student profile. <a href='/app/users'>Back</a>",400)
    from app.main import hash_password
    if password and len(password)<8: con.close(); return HTMLResponse("Password must be at least 8 characters. <a href='/app/users'>Back</a>",400)
    if password and password != password_confirm: con.close(); return HTMLResponse("New password and confirmation do not match. <a href='/app/users'>Back</a>",400)
    if password:
        cur.execute("UPDATE users SET email=?,full_name=?,password=?,role=?,teacher_id=?,student_id=? WHERE id=? AND school_id=?",(email_v,full_name.strip(),hash_password(password),role,tid,stid,uid,sid))
    else:
        cur.execute("UPDATE users SET email=?,full_name=?,role=?,teacher_id=?,student_id=? WHERE id=? AND school_id=?",(email_v,full_name.strip(),role,tid,stid,uid,sid))
    if role=="teacher" and tid:
        _ensure_class_teacher_assignments_table(cur)
        cid=int(class_id) if class_id.isdigit() else None
        if cid:
            if not cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(cid,sid)).fetchone():
                con.close(); return HTMLResponse("Selected class does not belong to this school. <a href='/app/users'>Back</a>",400)
            cur.execute("DELETE FROM class_teacher_assignments WHERE school_id=? AND teacher_id=? AND class_id<>?",(sid,tid,cid))
            now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""INSERT INTO class_teacher_assignments(school_id,class_id,teacher_id,assigned_at)
                           VALUES(?,?,?,?)
                           ON CONFLICT(school_id,class_id) DO UPDATE SET teacher_id=excluded.teacher_id,assigned_at=excluded.assigned_at""",(sid,cid,tid,now))
        else:
            cur.execute("DELETE FROM class_teacher_assignments WHERE school_id=? AND teacher_id=?",(sid,tid))
    elif tid:
        _ensure_class_teacher_assignments_table(cur)
        cur.execute("DELETE FROM class_teacher_assignments WHERE school_id=? AND teacher_id=?",(sid,tid))
    _audit(cur,sid,request,"USER_UPDATE",f"Updated {role} account {email_v}")
    con.commit();con.close();return RedirectResponse("/app/users",303)

@router.post("/app/users/delete/{uid}")
def users_delete(request: Request, uid: int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "users.manage"):
        return HTMLResponse("You do not have permission to manage users.",403)
    con=_db();cur=con.cursor()
    user=cur.execute("SELECT id,role,email,full_name FROM users WHERE id=? AND school_id=?",(uid,sid)).fetchone()
    if not user: con.close(); return HTMLResponse("User account not found. <a href='/app/users'>Back</a>",404)
    if str(user["role"] or "")=="school_admin":
        con.close(); return HTMLResponse("School Admin accounts can only be deleted by the Super Admin. <a href='/app/users'>Back</a>",403)
    if int(uid)==int(request.session.get("user_id") or 0):
        con.close(); return HTMLResponse("You cannot delete your own active account. <a href='/app/users'>Back</a>",400)
    cur.execute("DELETE FROM users WHERE id=? AND school_id=?",(uid,sid))
    _audit(cur,sid,request,"USER_DELETE",f"Deleted {user['role']} account {user['email']}")
    con.commit();con.close();return RedirectResponse("/app/users",303)

@router.get("/app/users/teacher-links")
def users_teacher_links(request: Request, teacher_id: int = 0):
    sid=_school_session(request)
    if not sid:
        return JSONResponse({"detail":"Not authenticated"}, status_code=401)
    if not _require_permission(request, sid, "users.manage"):
        return JSONResponse({"detail":"Not authorized"}, status_code=403)
    con=_db(); cur=con.cursor()
    try:
        teacher=cur.execute("SELECT id,name,email,role FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone()
        if not teacher:
            return JSONResponse({"classes":[],"subjects_by_class":{},"teacher_type":"subject_teacher"})
        _ensure_teacher_allocations_table(cur)
        _ensure_class_teacher_assignments_table(cur)
        allocations=cur.execute("""SELECT a.class_id,a.subject_id,c.name class_name,c.stream,s.name subject_name
            FROM teacher_allocations a
            JOIN classes c ON c.id=a.class_id AND c.school_id=a.school_id
            JOIN subjects s ON s.id=a.subject_id AND s.school_id=a.school_id
            WHERE a.school_id=? AND a.teacher_id=?
            ORDER BY c.name,c.stream,s.name""",(sid,teacher_id)).fetchall()
        class_teacher=cur.execute("SELECT class_id FROM class_teacher_assignments WHERE school_id=? AND teacher_id=? LIMIT 1",(sid,teacher_id)).fetchone()
        classes=[]
        subjects_by_class={}
        for row in allocations:
            cid=int(row["class_id"])
            if cid not in classes:
                classes.append(cid)
            subjects_by_class.setdefault(str(cid),[])
            if int(row["subject_id"]) not in subjects_by_class[str(cid)]:
                subjects_by_class[str(cid)].append(int(row["subject_id"]))
        if class_teacher and int(class_teacher["class_id"]) not in classes:
            classes.append(int(class_teacher["class_id"]))
        ct=bool(class_teacher)
        st=bool(allocations)
        teacher_type="both" if ct and st else ("class_teacher" if ct else "subject_teacher")
        return JSONResponse({"teacher":{"id":int(teacher["id"]),"name":str(teacher["name"] or ""),"email":str(teacher["email"] or "")},
            "classes":classes,"subjects_by_class":subjects_by_class,
            "class_teacher_class":int(class_teacher["class_id"]) if class_teacher else None,
            "teacher_type":teacher_type})
    finally:
        con.close()


@router.get("/app/users/add")
def users_add_get(request: Request):
    # The account-creation endpoint is POST-only. Redirect accidental GET
    # requests back to User Management instead of exposing FastAPI's 405 JSON.
    return RedirectResponse("/app/users",303)

@router.post("/app/users")
def users_add_legacy(request: Request, email:str=Form(""), role:str=Form("teacher"), teacher_id:str=Form(""), class_id:str=Form(""), class_ids_csv:str=Form(""), subject_ids_csv:str=Form(""), teacher_type:str=Form("subject_teacher"), student_id:str=Form("")):
    # Compatibility for browsers or cached scripts that submit the User Management
    # account form to /app/users instead of its dedicated /app/users/add action.
    # Keep this path strictly delegated so there is only one account-creation flow.
    return users_add(request, email, role, teacher_id, class_id, class_ids_csv, subject_ids_csv, teacher_type, student_id)

@router.post("/app/users/add")
def users_add(request: Request, email:str=Form(""), role:str=Form("teacher"), teacher_id:str=Form(""), class_id:str=Form(""), class_ids_csv:str=Form(""), subject_ids_csv:str=Form(""), teacher_type:str=Form("subject_teacher"), student_id:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "users.manage"):
        return HTMLResponse("You do not have permission to manage users.", 403)
    email=(email or "").strip()
    allowed={"school_admin","teacher","parent","student","accountant","registrar"}
    if role not in allowed:return HTMLResponse("Invalid role. <a href='/app/users'>Back</a>",400)
    con=_db();cur=con.cursor()
    try:
        _ensure_user_account_columns(cur, con)
        email_v=email.strip().lower()
        full_name=""
        tid=int(teacher_id) if teacher_id.isdigit() else None
        stid=int(student_id) if student_id.isdigit() else None

        if tid and not cur.execute("SELECT id,name,email FROM teachers WHERE id=? AND school_id=?",(tid,sid)).fetchone():
            return HTMLResponse("Selected teacher does not belong to this school. <a href='/app/users'>Back</a>",400)
        if stid and not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(stid,sid)).fetchone():
            return HTMLResponse("Selected student does not belong to a student record in this school. <a href='/app/users'>Back</a>",400)
        if role=="teacher" and not tid:
            return HTMLResponse("Teacher accounts must be linked to a teacher profile selected from Teachers Records.",400)
        if role in ("student","parent") and not stid:
            return HTMLResponse("Student and parent accounts must be linked to a student profile. <a href='/app/users'>Back</a>",400)
        if role not in ("teacher","student","parent") and (tid or stid):
            return HTMLResponse("This role cannot be linked to a teacher or student profile. <a href='/app/users'>Back</a>",400)

        if role=="teacher":
            teacher_row=cur.execute("SELECT name,email FROM teachers WHERE id=? AND school_id=?",(tid,sid)).fetchone()
            if teacher_row:
                # The selected Teachers record is authoritative. This also
                # makes account creation work if browser-side JavaScript did
                # not populate the readonly name/email fields.
                full_name=str(teacher_row["name"] or "").strip()
                if teacher_row["email"] and not email_v:
                    email_v=str(teacher_row["email"]).strip().lower()

        # Teacher login credentials are based on the teacher record:
        # username = teacher email; password = first name + generated digits.
        # This keeps teacher credentials predictable for the school admin while
        # still making the initial password unique.
        if role=="teacher":
            if not email_v:
                return HTMLResponse("The selected teacher must have an email address before a teacher account can be created. Please add the email in Teachers Records and try again. <a href='/app/users'>Back</a>",400)
            existing_email_account=cur.execute(
                "SELECT id FROM users WHERE lower(username)=? OR (school_id=? AND lower(email)=?) LIMIT 1",
                (email_v,sid,email_v)
            ).fetchone()
            if existing_email_account:
                return HTMLResponse("A user account already exists for this teacher email. Please edit the existing account instead of creating another one. <a href='/app/users'>Back</a>",400)

        class_ids=[int(x) for x in str(class_ids_csv or "").split(",") if x.strip().isdigit()]
        subject_ids=[int(x) for x in str(subject_ids_csv or "").split(",") if x.strip().isdigit()]
        class_ids=list(dict.fromkeys(class_ids)); subject_ids=list(dict.fromkeys(subject_ids))

        if role=="teacher":
            if teacher_type not in ("class_teacher","subject_teacher","both"):
                teacher_type="subject_teacher"

            # The database is authoritative. If the browser did not submit the
            # hidden allocation fields, rebuild them from the teacher's existing
            # allocations/class-teacher assignment instead of rejecting the account.
            _ensure_teacher_allocations_table(cur)
            _ensure_class_teacher_assignments_table(cur)
            existing_allocations=cur.execute(
                "SELECT class_id,subject_id FROM teacher_allocations WHERE school_id=? AND teacher_id=? ORDER BY class_id,subject_id",
                (sid,tid)
            ).fetchall()
            existing_class_teacher=cur.execute(
                "SELECT class_id FROM class_teacher_assignments WHERE school_id=? AND teacher_id=? ORDER BY id DESC LIMIT 1",
                (sid,tid)
            ).fetchone()

            if not class_ids:
                class_ids=list(dict.fromkeys(int(x["class_id"]) for x in existing_allocations))
            if existing_class_teacher and int(existing_class_teacher["class_id"]) not in class_ids:
                class_ids.append(int(existing_class_teacher["class_id"]))
            if not subject_ids:
                subject_ids=list(dict.fromkeys(int(x["subject_id"]) for x in existing_allocations))

            # If exactly one class is selected and no subject is selected while
            # the default Subject Teacher option is unchanged, treat it as a
            # Class Teacher assignment only when that teacher is already assigned
            # as a class teacher. Otherwise retain Subject Teacher validation.
            if teacher_type=="subject_teacher" and len(class_ids)==1 and not subject_ids and existing_class_teacher:
                teacher_type="class_teacher"

            # Account creation must remain possible even when the allocation
            # selector submits no values. Existing teacher allocations are used
            # automatically; missing allocations should not block login creation.
            if teacher_type in ("class_teacher","both") and len(class_ids)!=1:
                if teacher_type=="both" and class_ids:
                    class_ids=[class_ids[0]]
                elif teacher_type=="class_teacher" and class_ids:
                    class_ids=[class_ids[0]]
                else:
                    teacher_type="subject_teacher"
            if teacher_type in ("subject_teacher","both") and (not class_ids or not subject_ids):
                # Keep the account creation independent of allocation selection.
                # Allocations can be edited from Teacher Links afterward.
                if not class_ids and existing_class_teacher:
                    class_ids=[int(existing_class_teacher["class_id"])]
                if not class_ids and existing_allocations:
                    class_ids=[int(existing_allocations[0]["class_id"])]
                if not subject_ids and existing_allocations:
                    subject_ids=list(dict.fromkeys(int(x["subject_id"]) for x in existing_allocations))
                if not class_ids or not subject_ids:
                    teacher_type="class_teacher" if existing_class_teacher and class_ids else "subject_teacher"

            if class_ids:
                valid_classes=cur.execute("SELECT id FROM classes WHERE school_id=? AND id IN (%s)"%(",".join("?"*len(class_ids)),),[sid]+class_ids).fetchall()
            else:
                valid_classes=[]
            if subject_ids:
                valid_subjects=cur.execute("SELECT id FROM subjects WHERE school_id=? AND id IN (%s)"%(",".join("?"*len(subject_ids)),),[sid]+subject_ids).fetchall()
            else:
                valid_subjects=[]
            if len(valid_classes)!=len(class_ids) or len(valid_subjects)!=len(subject_ids):
                return HTMLResponse("One or more selected classes/subjects do not belong to this school.",400)

        from app.main import hash_password, verify_password
        import secrets
        if role=="teacher":
            first_name=re.sub(r"[^A-Za-z0-9]", "", full_name.split()[0] if full_name.split() else "Teacher")
            generated_password=first_name+"@"+str(datetime.now(ZoneInfo("Africa/Nairobi")).year)
            username=email_v
        else:
            generated_password="DS-"+secrets.token_urlsafe(8)
            base_username=re.sub(r"[^a-z0-9]+","",full_name.lower()) or "user"
            username=base_username
            if username=="user" and tid:
                username="teacher"
            username=username[:40]
            username_suffix=secrets.randbelow(9000)+1000
            if cur.execute("SELECT id FROM users WHERE lower(username)=?",(username.lower(),)).fetchone():
                username=f"{username}{username_suffix}"
            suffix=1
            while cur.execute("SELECT id FROM users WHERE lower(username)=?",(username.lower(),)).fetchone():
                suffix += 1
                username=f"{base_username}{suffix}"
        # Build and verify the credential hash before inserting the account.
        # This guarantees that the credential displayed to the School Admin is
        # exactly the credential the login verifier can validate.
        password_hash=hash_password(generated_password)
        password_ok,_=verify_password(generated_password,password_hash)
        if not password_ok:
            return HTMLResponse("The generated password could not be validated. No account was added. Please try again.",500)
        cur.execute("INSERT INTO users(username,email,password,role,full_name,school_id,teacher_id,student_id,temporary_password) VALUES(?,?,?,?,?,?,?,?,?)",
                    (username,email_v,password_hash,role,full_name.strip(),sid,tid,stid,generated_password))

        if role=="teacher" and tid:
            _ensure_teacher_allocations_table(cur)
            _ensure_class_teacher_assignments_table(cur)
            if teacher_type in ("class_teacher","both"):
                cid=class_ids[0]
                now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
                cur.execute("""INSERT INTO class_teacher_assignments(school_id,class_id,teacher_id,assigned_at)
                               VALUES(?,?,?,?)
                               ON CONFLICT(school_id,class_id) DO UPDATE SET teacher_id=excluded.teacher_id,assigned_at=excluded.assigned_at""",
                            (sid,cid,tid,now))
            if teacher_type in ("subject_teacher","both"):
                for cid in class_ids:
                    for subject_id in subject_ids:
                        cur.execute("INSERT OR IGNORE INTO teacher_allocations(school_id,teacher_id,class_id,subject_id) VALUES(?,?,?,?)",
                                    (sid,tid,cid,subject_id))

        try:
            _audit(cur,sid,request,"USER_CREATE",f"Created {role} account {email_v}")
        except Exception as audit_exc:
            # Audit logging must never prevent a valid account from being saved.
            print("DAVISCHOOL USER CREATE AUDIT WARNING:",repr(audit_exc),flush=True)
        con.commit()

        # Verify that the committed account is actually visible to the same
        # school before redirecting to the Accounts table.
        created=cur.execute("SELECT id FROM users WHERE school_id=? AND lower(username)=?",(sid,username.lower())).fetchone()
        if not created:
            return HTMLResponse("The account could not be verified after saving. No account was added. <a href='/app/users'>Back</a>",500)
        # Show the generated credentials directly from the successful POST response.
        # This avoids depending on the session/redirect cycle for the one-time popup.
        # The account has already been committed and verified above, so existing
        # records and marks are unaffected.
        safe_username=escape(str(username))
        safe_password=escape(str(generated_password))
        # Preserve the current browser tab's isolated session when the
        # credentials page returns to User Management. The tab-session
        # middleware identifies the authenticated session by ds_tab; omitting
        # it would create a fresh tab session and send the user to login.
        current_tab=str(request.query_params.get("ds_tab") or "").strip()
        safe_tab=escape(current_tab, quote=True)
        users_return_url="/app/users"
        if safe_tab:
            users_return_url += "?ds_tab=" + quote(safe_tab)
        credential_page=f"""<!doctype html><html><head>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Account Created - DaviSchool</title>
<style>
body{{margin:0;background:#eef2f7;font-family:Arial,sans-serif;min-height:100vh}}
.overlay{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;box-sizing:border-box;background:rgba(15,23,42,.65)}}
.modal{{background:#fff;border-radius:16px;max-width:430px;width:100%;padding:24px;box-shadow:0 20px 50px rgba(0,0,0,.25);box-sizing:border-box}}
h2{{margin:0 0 10px;color:#172033}}.muted{{color:#475569;margin:0 0 16px}}
.credentials{{background:#f8fafc;border-radius:10px;padding:14px;margin-bottom:16px}}
.value{{font-size:20px;font-weight:800;margin:4px 0 12px;word-break:break-word}}
button{{width:100%;padding:12px;border:0;border-radius:9px;background:#176B3A;color:#fff;font-weight:800;font-size:15px;cursor:pointer}}
</style></head><body><div class='overlay'><div class='modal'>
<h2>✅ Account Created</h2>
<p class='muted'>The teacher account has been created successfully. Save these login credentials.</p>
<div class='credentials'><b>Username</b><div class='value'>{safe_username}</div>
<b>Password</b><div class='value' style='margin-bottom:0'>{safe_password}</div></div>
<button type='button' onclick="window.location.href='{users_return_url}'; return false;">OK</button>
</div></div></body></html>"""
        return HTMLResponse(credential_page, status_code=200)
    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        import traceback
        print("DAVISCHOOL USER CREATE ERROR:", repr(exc), flush=True)
        print(traceback.format_exc(), flush=True)
        detail=escape(f"{type(exc).__name__}: {str(exc) or 'No exception message'}")[:1000]
        return HTMLResponse(
            "Unable to create the account.<br><br><b>Technical detail:</b> " + detail +
            "<br><br><a href='/app/users'>Back to User Management</a>", 500
        )
    finally:
        try:
            con.close()
        except Exception:
            pass


@router.get("/app/classes", response_class=HTMLResponse)
def classes_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "classes.view"):
        return HTMLResponse("You do not have permission to view classes.", 403)
    con=_db();cur=con.cursor()
    _ensure_class_teacher_assignments_table(cur)
    rows=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    teachers=cur.execute("SELECT id,name,role,status FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    assignments=cur.execute(
        """SELECT a.class_id,a.teacher_id
           FROM class_teacher_assignments a
           WHERE a.school_id=?
           ORDER BY a.id DESC""",
        (sid,)
    ).fetchall()
    con.close()
    # Deterministically use the newest assignment for each class so an older
    # duplicate can never make the page show the wrong current teacher.
    assigned_by_class={}
    for a in assignments:
        cid=int(a["class_id"])
        if cid not in assigned_by_class:
            assigned_by_class[cid]=int(a["teacher_id"])
    teacher_options=lambda selected_id: "".join(
        "<option value='%s' %s>%s%s</option>" % (
            t["id"],
            "selected" if selected_id and int(t["id"])==int(selected_id) else "",
            escape(str(t["name"] or "")),
            (" — "+escape(str(t["role"] or ""))) if t["role"] else ""
        )
        for t in teachers
    )
    current_ds_tab=str(request.query_params.get("ds_tab") or "").strip()
    current_ds_tab_q=("?" + "ds_tab=" + quote(current_ds_tab,safe="")) if current_ds_tab else ""
    trs="".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><form method='post' action='/app/classes/class-teacher' onsubmit='this.submit(); return false;' style='display:flex;gap:7px;align-items:center;flex-wrap:wrap'>"
        "<input type='hidden' name='class_id' value='%s'><select name='teacher_id' class='field teacher-select' required><option value=''>Select Class Teacher</option>%s</select>"
        "<button class='btn teacher-btn'>👨‍🏫 Set Class Teacher</button></form></td><td class='class-actions'><a class='btn edit' href='/app/classes/edit/%s%s'>Edit</a> "
        "<form method='post' action='/app/classes/delete/%s%s' style='display:inline' onsubmit='if(!confirm(&quot;Delete this class/stream? This action cannot be undone.&quot;)) return false; this.submit(); return false;'>"
        "<button type='submit' formaction='/app/classes/delete/%s%s' formmethod='post' class='btn danger'>Delete</button></form></td></tr>" % (
            escape(str(x["name"])),
            escape(str(x["level"] or "")),
            escape(str(x["stream"] or "")),
            escape(str(next((t["name"] for t in teachers if int(t["id"])==assigned_by_class.get(int(x["id"]),-1)), "Not Assigned"))),
            x["id"],
            teacher_options(assigned_by_class.get(int(x["id"]))),
            x["id"], current_ds_tab_q,
            x["id"], current_ds_tab_q,
            x["id"], current_ds_tab_q
        )
        for x in rows
    )
    body=f"""<div class='page'><h1>Classes & Streams</h1>
<div class='card section'><div class='classes-filter-scroll' tabindex='0'><form method='post' action='/app/classes/add' class='classes-filter-form'><input name='name' required placeholder='Class name e.g. Grade 6' class='field'><select name='level' class='field'><option value=''>Select level</option><option>Pre-Primary</option><option>Lower Primary</option><option>Upper Primary</option><option>Junior Secondary</option><option>Senior Secondary</option><option>College</option><option>Other</option></select><input name='stream' placeholder='Stream' class='field'><button class='btn'>Add Class</button></form></div></div>
<div class='card section'><h2>👨‍🏫 Class Teachers</h2><div class='muted'>Select a teacher for each class or stream. The selected teacher is automatically used as the Class Teacher on that class's report cards, including the name and signature line.</div>
<div class='marksheet-scroll classes-table-scroll' tabindex='0'><table class='classes-table'><thead><tr><th>Name</th><th>Level</th><th>Stream</th><th>Current Class Teacher</th><th>Set Class Teacher</th><th>Actions</th></tr></thead><tbody>{trs or '<tr><td colspan=6>No classes.</td></tr>'}</tbody></table></div></div></div>
<style>.classes-filter-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;padding-bottom:6px}}.classes-filter-form{{display:grid;grid-template-columns:260px 220px 180px auto;gap:10px;width:max-content;min-width:100%}}.classes-table-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;padding-bottom:8px}}.classes-table{{width:max-content;min-width:900px}}.subject-actions{{white-space:nowrap}}.edit{{background:#176B3A!important;color:#fff!important;text-decoration:none;display:inline-block;margin-right:6px}}.danger{{background:#b91c1c!important;color:#fff!important;cursor:pointer}}.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800;cursor:pointer}}.teacher-select{{min-width:220px}}.teacher-btn{{white-space:nowrap}}</style>"""
    return _school_page(request,"Classes",body)

@router.post("/app/classes/add")
def classes_add(request: Request, name: str = Form(...), level: str = Form(""), stream: str = Form("")):
    sid = _school_session(request)
    if not sid:
        return RedirectResponse("/", 303)
    if not _require_permission(request, sid, "classes.create"):
        return HTMLResponse("You do not have permission to create classes.", 403)
    name_v = name.strip()
    level_v = level.strip()
    stream_v = stream.strip()
    if not name_v:
        return HTMLResponse("Class name is required. <a href='/app/classes'>Back</a>", 400)
    con = _db()
    cur = con.cursor()
    try:
        duplicate = cur.execute(
            """SELECT id FROM classes
               WHERE school_id=? AND lower(name)=lower(?) AND lower(COALESCE(stream,''))=lower(?)""",
            (sid, name_v, stream_v)
        ).fetchone()
        if duplicate:
            con.close()
            return HTMLResponse("That class/stream already exists in this school. <a href='/app/classes'>Back</a>", 400)
        cur.execute(
            "INSERT INTO classes(school_id,name,level,stream) VALUES(?,?,?,?)",
            (sid, name_v, level_v, stream_v)
        )
        _audit(cur, sid, request, "CLASS_CREATE", "%s %s"%(name_v, stream_v))
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/app/classes", 303)

@router.get("/app/classes/edit/{class_id}", response_class=HTMLResponse)
def classes_edit_page(request: Request, class_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "classes.create"):
        return HTMLResponse("You do not have permission to edit classes.",403)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id,name,level,stream FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
    con.close()
    if not row:return HTMLResponse("Class/stream not found. <a href='/app/classes'>Back</a>",404)
    body=f"""<div class='page'><h1>Edit Class / Stream</h1><div class='card section'><div class='marksheet-scroll class-edit-scroll' tabindex='0'><form method='post' action='/app/classes/edit/{class_id}' class='class-edit-form'><input name='name' required class='field' value='{escape(str(row["name"] or ""),quote=True)}' placeholder='Class name'><select name='level' class='field'><option value=''>Select level</option>{''.join("<option selected" if str(row["level"] or "")==v else "<option" for v in ["Pre-Primary","Lower Primary","Upper Primary","Junior Secondary","Senior Secondary","College","Other"])}></select><input name='stream' class='field' value='{escape(str(row["stream"] or ""),quote=True)}' placeholder='Stream'><button class='btn'>Save Changes</button><a class='btn secondary' href='/app/classes'>Cancel</a></form></div></div><style>.class-edit-scroll{{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;padding-bottom:8px}}.class-edit-form{{display:grid;grid-template-columns:260px 220px 180px auto auto;gap:10px;width:max-content;min-width:100%}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800;text-decoration:none;cursor:pointer;white-space:nowrap}}.secondary{{background:#64748b}}</style></div>"""
    return _school_page(request,"Edit Class / Stream",body)

@router.post("/app/classes/edit/{class_id}")
def classes_edit(request: Request,class_id:int,name:str=Form(...),level:str=Form(""),stream:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request,sid,"classes.create"):
        return HTMLResponse("You do not have permission to edit classes.",403)
    name_v=name.strip(); level_v=level.strip(); stream_v=stream.strip()
    if not name_v:return HTMLResponse("Class name is required. <a href='/app/classes'>Back</a>",400)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
    if not row: con.close(); return HTMLResponse("Class/stream not found. <a href='/app/classes'>Back</a>",404)
    dup=cur.execute("SELECT id FROM classes WHERE school_id=? AND id<>? AND lower(name)=lower(?) AND lower(COALESCE(stream,''))=lower(?)",(sid,class_id,name_v,stream_v)).fetchone()
    if dup: con.close(); return HTMLResponse("That class/stream already exists in this school. <a href='/app/classes'>Back</a>",400)
    try:
        cur.execute("UPDATE classes SET name=?,level=?,stream=? WHERE id=? AND school_id=?",(name_v,level_v,stream_v,class_id,sid))
        _audit(cur,sid,request,"CLASS_EDIT","Edited class %s"%(class_id,))
        con.commit()
    except Exception as exc:
        try: con.rollback()
        except Exception: pass
        con.close()
        return HTMLResponse("Unable to update this class.<br><br><b>Technical detail:</b> "+escape(str(exc)),409)
    con.close()
    return RedirectResponse("/app/classes",303)

@router.post("/app/classes/delete/{class_id}")
def classes_delete(request: Request,class_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request,sid,"classes.create"):
        return HTMLResponse("You do not have permission to delete classes.",403)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id,name,stream FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
    if not row: con.close(); return HTMLResponse("Class/stream not found. <a href='/app/classes'>Back</a>",404)
    try:
        cur.execute("DELETE FROM classes WHERE id=? AND school_id=?",(class_id,sid))
        con.commit()
    except Exception as exc:
        try: con.rollback()
        except Exception: pass
        con.close()
        return HTMLResponse("Unable to delete this class/stream.<br><br><b>Technical detail:</b> "+escape(str(exc)),409)
    con.close()
    try:
        audit_con=_db(); audit_cur=audit_con.cursor()
        try:
            _audit(audit_cur,sid,request,"CLASS_DELETE","Deleted class %s"%(class_id,)); audit_con.commit()
        except Exception:
            try: audit_con.rollback()
            except Exception: pass
        finally: audit_con.close()
    except Exception: pass
    return RedirectResponse("/app/classes",303)

@router.post("/app/classes/class-teacher")
def classes_class_teacher(request: Request,class_id:int=Form(...),teacher_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not (_require_permission(request, sid, "settings.manage") or _require_permission(request, sid, "classes.create")):
        return HTMLResponse("You do not have permission to assign class teachers.",403)
    con=_db();cur=con.cursor()
    _ensure_class_teacher_assignments_table(cur)
    valid_class=cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
    valid_teacher=cur.execute("SELECT id,name FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone()
    if not valid_class or not valid_teacher:
        con.close()
        return HTMLResponse("Invalid class or teacher selection. <a href='/app/classes'>Back</a>",400)
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    # Do not rely on ON CONFLICT here: older production databases may have
    # the assignment table without the composite UNIQUE constraint.  Updating
    # an existing assignment first keeps the button functional on both the
    # legacy and current schemas without altering any existing class records.
    # Replace the class assignment atomically at the application level.
    # This deliberately removes any stale/duplicate rows first, then writes
    # exactly one row for the selected teacher.  It works even when a legacy
    # production database has a different UNIQUE constraint definition.
    cur.execute(
        "DELETE FROM class_teacher_assignments WHERE school_id=? AND class_id=?",
        (sid,class_id)
    )
    cur.execute(
        """INSERT INTO class_teacher_assignments
           (school_id,class_id,teacher_id,assigned_at)
           VALUES(?,?,?,?)""",
        (sid,class_id,teacher_id,now)
    )
    saved_assignment=cur.execute(
        """SELECT a.teacher_id,t.name FROM class_teacher_assignments a
           JOIN teachers t ON t.id=a.teacher_id AND t.school_id=?
           WHERE a.school_id=? AND a.class_id=?
           ORDER BY a.id DESC LIMIT 1""",
        (sid,sid,class_id)
    ).fetchone()
    if not saved_assignment or int(saved_assignment["teacher_id"]) != int(teacher_id):
        con.rollback()
        con.close()
        return HTMLResponse("The class teacher assignment could not be saved. Please try again. <a href='/app/classes'>Back</a>",500)
    _audit(cur,sid,request,"CLASS_TEACHER_ASSIGNMENT","Assigned %s as class teacher for class %s"%(str(valid_teacher["name"] or ""),class_id))
    con.commit()
    con.close()
    return RedirectResponse("/app/classes",303)

@router.get("/app/subjects", response_class=HTMLResponse)
def subjects_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "subjects.view"):
        return HTMLResponse("You do not have permission to view subjects.", 403)
    con=_db();cur=con.cursor(); rows=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall();con.close()
    current_ds_tab=str(request.query_params.get("ds_tab") or "").strip()
    current_ds_tab_q=("?" + "ds_tab=" + quote(current_ds_tab,safe="")) if current_ds_tab else ""
    trs="".join(f"<tr><td>{escape(str(x['name']))}</td><td>{escape(str(x['code'] or ''))}</td><td>{escape(str(x['initial'] or ''))}</td><td class='subject-actions'><a class='btn edit' href='/app/subjects/edit/{x['id']}'>Edit</a><form method='post' action='/app/subjects/delete/{x['id']}{current_ds_tab_q}' style='display:inline' onsubmit='return confirm(&quot;Delete this subject? This action cannot be undone.&quot;);'><button type='submit' formaction='/app/subjects/delete/{x['id']}{current_ds_tab_q}' formmethod='post' class='btn danger'>Delete</button></form></td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Subjects</h1><div class='card section'><div class='subjects-filter-scroll' tabindex='0'><form method='post' action='/app/subjects/add' class='subjects-filter-form'><input name='name' required placeholder='Subject name' class='field'><input name='code' placeholder='Code' class='field'><input name='initial' placeholder='Initial' class='field'><button type='submit' formaction='/app/subjects/add{current_ds_tab_q}' formmethod='post' class='btn'>Add Subject</button></form></div></div><div class='card section'><div class='marksheet-scroll subjects-table-scroll' tabindex='0'><table class='subjects-table'><thead><tr><th>Subject</th><th>Code</th><th>Initial</th><th>Actions</th></tr></thead><tbody>{trs or '<tr><td colspan=4>No subjects.</td></tr>'}</tbody></table></div></div></div><style>.subjects-filter-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;padding-bottom:6px}}.subjects-filter-form{{display:grid;grid-template-columns:260px 220px 180px auto;gap:10px;width:max-content;min-width:100%}}.subjects-table-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;padding-bottom:8px}}.subjects-table{{width:max-content;min-width:700px}}.subjects-table th:first-child,.subjects-table td:first-child{{width:250px;min-width:250px;max-width:250px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Subjects",body)

@router.post("/app/subjects/add")
def subjects_add(request: Request,name:str=Form(...),code:str=Form(""),initial:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "subjects.create"):
        return HTMLResponse("You do not have permission to create subjects.", 403)
    name_v=name.strip(); code_v=code.strip(); initial_v=initial.strip()
    if not name_v:return HTMLResponse("Subject name is required. <a href='/app/subjects'>Back</a>",400)
    con=_db();cur=con.cursor()
    if cur.execute("SELECT id FROM subjects WHERE school_id=? AND lower(name)=lower(?)",(sid,name_v)).fetchone():
        con.close();return HTMLResponse("That subject already exists in this school. <a href='/app/subjects'>Back</a>",400)
    if code_v and cur.execute("SELECT id FROM subjects WHERE school_id=? AND lower(code)=lower(?)",(sid,code_v)).fetchone():
        con.close();return HTMLResponse("That subject code already exists in this school. <a href='/app/subjects'>Back</a>",400)
    cur.execute("INSERT INTO subjects(school_id,name,code,initial) VALUES(?,?,?,?)",(sid,name_v,code_v,initial_v))
    _audit(cur,sid,request,"SUBJECT_CREATE",name_v);con.commit();con.close();return RedirectResponse("/app/subjects" + (("?ds_tab=" + quote(request.query_params.get("ds_tab"),safe="")) if request.query_params.get("ds_tab") else ""),303)
@router.get("/app/subjects/edit/{subject_id}", response_class=HTMLResponse)
def subjects_edit_page(request: Request, subject_id: int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "subjects.create"):
        return HTMLResponse("You do not have permission to edit subjects.", 403)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id,name,code,initial FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    con.close()
    if not row:
        return HTMLResponse("Subject not found. <a href='/app/subjects'>Back</a>",404)
    body=f"""<div class='page'><h1>Edit Subject</h1><div class='card section'><form method='post' action='/app/subjects/edit/{subject_id}' style='display:grid;grid-template-columns:1fr 1fr 1fr auto auto;gap:10px'><input name='name' required class='field' value='{escape(str(row["name"] or ""), quote=True)}' placeholder='Subject name'><input name='code' class='field' value='{escape(str(row["code"] or ""), quote=True)}' placeholder='Code'><input name='initial' class='field' value='{escape(str(row["initial"] or ""), quote=True)}' placeholder='Initial'><button class='btn'>Save Changes</button><a class='btn secondary' href='/app/subjects'>Cancel</a></form></div><style>.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800;text-decoration:none;cursor:pointer}}.secondary{{background:#64748b}} </style></div>"""
    return _school_page(request,"Edit Subject",body)

@router.post("/app/subjects/edit/{subject_id}")
def subjects_edit(request: Request, subject_id: int, name: str=Form(...), code: str=Form(""), initial: str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "subjects.create"):
        return HTMLResponse("You do not have permission to edit subjects.",403)
    name_v=name.strip(); code_v=code.strip(); initial_v=initial.strip()
    if not name_v:return HTMLResponse("Subject name is required. <a href='/app/subjects'>Back</a>",400)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    duplicate_name=cur.execute("SELECT id FROM subjects WHERE school_id=? AND lower(name)=lower(?) AND id<>?",(sid,name_v,subject_id)).fetchone()
    duplicate_code=cur.execute("SELECT id FROM subjects WHERE school_id=? AND lower(code)=lower(?) AND id<>?",(sid,code_v,subject_id)).fetchone() if code_v else None
    if not row:
        con.close();return HTMLResponse("Subject not found. <a href='/app/subjects'>Back</a>",404)
    if duplicate_name:
        con.close();return HTMLResponse("That subject already exists in this school. <a href='/app/subjects'>Back</a>",400)
    if duplicate_code:
        con.close();return HTMLResponse("That subject code already exists in this school. <a href='/app/subjects'>Back</a>",400)
    cur.execute("UPDATE subjects SET name=?,code=?,initial=? WHERE id=? AND school_id=?",(name_v,code_v,initial_v,subject_id,sid))
    _audit(cur,sid,request,"SUBJECT_EDIT",name_v)
    con.commit();con.close()
    return RedirectResponse("/app/subjects",303)

@router.post("/app/subjects/delete/{subject_id}")
def subjects_delete(request: Request, subject_id: int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "subjects.create"):
        return HTMLResponse("You do not have permission to delete subjects.",403)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id,name FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not row:
        con.close();return HTMLResponse("Subject not found. <a href='/app/subjects'>Back</a>",404)
    subject_name=str(row["name"] or subject_id)
    try:
        cur.execute("DELETE FROM subjects WHERE id=? AND school_id=?",(subject_id,sid))
        con.commit()
    except Exception as exc:
        try: con.rollback()
        except Exception: pass
        con.close()
        return HTMLResponse("Unable to delete this subject.<br><br><b>Technical detail:</b> " + escape(str(exc)), 409)
    con.close()

    # Audit logging must never be allowed to undo a successful subject deletion.
    try:
        audit_con=_db(); audit_cur=audit_con.cursor()
        try:
            _audit(audit_cur,sid,request,"SUBJECT_DELETE",subject_name)
            audit_con.commit()
        except Exception:
            try: audit_con.rollback()
            except Exception: pass
        finally:
            audit_con.close()
    except Exception:
        pass

    return RedirectResponse("/app/subjects",303)

@router.get("/app/exams", response_class=HTMLResponse)
def exams_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "exams.view"):
        return HTMLResponse("You do not have permission to view examinations.", 403)
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall();con.close()
    trs="".join(f"<tr><td>{escape(str(x['name']))}</td><td>{escape(str(x['exam_type'] or ''))}</td><td>{escape(str(x['term'] or ''))}</td><td>{escape(str(x['year'] or ''))}</td><td><a class='btn edit' href='/app/exams/edit/{x['id']}'>Edit</a> <form method='post' action='/app/exams/delete/{x['id']}' style='display:inline' onsubmit='if(!confirm(&quot;Delete this examination? This action cannot be undone.&quot;)) return false; this.submit(); return false;'><button type='submit' formaction='/app/exams/delete/{x['id']}' formmethod='post' class='btn danger'>Delete</button></form></td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Examinations</h1><div class='card section'><div class='examination-filter-scroll' tabindex='0'><form id='create-exam-form' method='post' action='/app/exams/add' class='examination-filter-form' ><input name='name' required placeholder='Exam name' class='field'><select name='exam_type' class='field'><option value=''>Select exam type</option><option>CAT</option><option>Mid-Term</option><option>End-Term</option><option>Mock</option><option>Final</option><option>SBA/CBA</option></select><select name='term' class='field'><option value=''>Select term</option><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><select name='year' class='field'>{''.join('<option>'+y+'</option>' for y in YEAR_OPTIONS)}</select><button type='submit' class='btn create-exam-btn'>Create Exam</button></form></div></div><div class='card section'><div class='marksheet-scroll examination-table-scroll' tabindex='0'><table class='examination-table'><thead><tr><th>Name</th><th>Type</th><th>Term</th><th>Year</th><th>Actions</th></tr></thead><tbody>{trs or '<tr><td colspan=5>No examinations.</td></tr>'}</tbody></table></div></div></div><style>.examination-filter-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;padding-bottom:6px}}.examination-filter-form{{display:grid;grid-template-columns:260px 220px 220px 150px auto;gap:10px;width:max-content;min-width:100%}}.examination-table-scroll{{width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:auto;-webkit-overflow-scrolling:touch;padding-bottom:8px}}.examination-table{{width:max-content;min-width:900px}}.create-exam-btn{{min-width:140px;position:sticky;right:0;z-index:10;pointer-events:auto;cursor:pointer;display:inline-block;white-space:nowrap;background:#176B3A!important;color:#fff!important}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800;text-decoration:none;cursor:pointer}}.edit{{background:#176B3A;margin-right:5px}}.danger{{background:#b91c1c}}</style>"""
    return _school_page(request,"Examinations",body)

@router.post("/app/exams")
@router.post("/app/exams/add")
def exams_add(request: Request,name:str=Form(...),exam_type:str=Form(""),term:str=Form(""),year:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "exams.create"):
        return HTMLResponse("You do not have permission to create examinations.", 403)
    name_v=name.strip(); type_v=exam_type.strip(); term_v=term.strip(); year_v=year.strip()
    if not name_v:return HTMLResponse("Examination name is required. <a href='/app/exams'>Back</a>",400)
    con=_db();cur=con.cursor()
    if cur.execute("SELECT id FROM exams WHERE school_id=? AND lower(name)=lower(?) AND lower(COALESCE(term,''))=lower(?) AND lower(COALESCE(year,''))=lower(?)",(sid,name_v,term_v,year_v)).fetchone():
        con.close();return HTMLResponse("That examination already exists for this term and year. <a href='/app/exams'>Back</a>",400)
    cur.execute("INSERT INTO exams(school_id,name,term,year,exam_type) VALUES(?,?,?,?,?)",(sid,name_v,term_v,year_v,type_v))
    _audit(cur,sid,request,"EXAM_CREATE",name_v);con.commit();con.close();return RedirectResponse("/app/exams",303)

@router.get("/app/exams/edit/{exam_id}", response_class=HTMLResponse)
def exams_edit_page(request: Request, exam_id: int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "exams.create"):
        return HTMLResponse("You do not have permission to edit examinations.",403)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id,name,exam_type,term,year FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
    con.close()
    if not row:return HTMLResponse("Examination not found. <a href='/app/exams'>Back</a>",404)
    year_opts="".join("<option value='%s' %s>%s</option>"%(escape(y,quote=True),"selected" if str(row["year"] or "")==y else "",y) for y in YEAR_OPTIONS)
    body=f"""<div class='page'><h1>Edit Examination</h1><div class='card section'><div class='marksheet-scroll exam-edit-scroll' tabindex='0'><form method='post' action='/app/exams/edit/{exam_id}' class='exam-edit-form'><input name='name' required class='field' value='{escape(str(row["name"] or ""),quote=True)}' placeholder='Exam name'><select name='exam_type' class='field'><option value=''>Select exam type</option><option {'selected' if row["exam_type"]=="CAT" else ''}>CAT</option><option {'selected' if row["exam_type"]=="Mid-Term" else ''}>Mid-Term</option><option {'selected' if row["exam_type"]=="End-Term" else ''}>End-Term</option><option {'selected' if row["exam_type"]=="Mock" else ''}>Mock</option><option {'selected' if row["exam_type"]=="Final" else ''}>Final</option><option {'selected' if row["exam_type"]=="SBA/CBA" else ''}>SBA/CBA</option></select><select name='term' class='field'><option value=''>Select term</option><option {'selected' if row["term"]=="Term 1" else ''}>Term 1</option><option {'selected' if row["term"]=="Term 2" else ''}>Term 2</option><option {'selected' if row["term"]=="Term 3" else ''}>Term 3</option></select><select name='year' class='field'>{year_opts}</select><button class='btn'>Save Changes</button><a class='btn secondary' href='/app/exams'>Cancel</a></form></div></div><style>.exam-edit-scroll{{display:block;width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;overscroll-behavior-x:contain;padding-bottom:8px;box-sizing:border-box;scrollbar-gutter:stable}}.exam-edit-scroll:focus{{outline:2px solid #94a3b8;outline-offset:2px}}.exam-edit-form{{display:grid;grid-template-columns:260px 220px 220px 150px auto auto;gap:10px;width:max-content;min-width:100%}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800;text-decoration:none;cursor:pointer;white-space:nowrap}}.secondary{{background:#64748b}}</style></div>"""
    return _school_page(request,"Edit Examination",body)

@router.post("/app/exams/edit/{exam_id}")
def exams_edit(request: Request, exam_id:int, name:str=Form(...), exam_type:str=Form(""), term:str=Form(""), year:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "exams.create"):
        return HTMLResponse("You do not have permission to edit examinations.",403)
    name_v=name.strip(); type_v=exam_type.strip(); term_v=term.strip(); year_v=year.strip()
    if not name_v:return HTMLResponse("Examination name is required. <a href='/app/exams'>Back</a>",400)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
    duplicate=cur.execute("SELECT id FROM exams WHERE school_id=? AND lower(name)=lower(?) AND lower(COALESCE(term,''))=lower(?) AND lower(COALESCE(year,''))=lower(?) AND id<>?",(sid,name_v,term_v,year_v,exam_id)).fetchone()
    if not row:
        con.close();return HTMLResponse("Examination not found. <a href='/app/exams'>Back</a>",404)
    if duplicate:
        con.close();return HTMLResponse("That examination already exists for this term and year. <a href='/app/exams'>Back</a>",400)
    cur.execute("UPDATE exams SET name=?,exam_type=?,term=?,year=? WHERE id=? AND school_id=?",(name_v,type_v,term_v,year_v,exam_id,sid))
    _audit(cur,sid,request,"EXAM_EDIT",name_v)
    con.commit();con.close()
    return RedirectResponse("/app/exams",303)

@router.post("/app/exams/delete/{exam_id}")
def exams_delete(request: Request, exam_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "exams.create"):
        return HTMLResponse("You do not have permission to delete examinations.",403)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id,name FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone()
    if not row:
        con.close();return HTMLResponse("Examination not found. <a href='/app/exams'>Back</a>",404)
    exam_name=str(row["name"] or exam_id)
    try:
        cur.execute("DELETE FROM exams WHERE id=? AND school_id=?",(exam_id,sid))
        con.commit()
    except Exception as exc:
        try: con.rollback()
        except Exception: pass
        con.close()
        return HTMLResponse("Unable to delete this examination.<br><br><b>Technical detail:</b> " + escape(str(exc)),409)
    con.close()
    try:
        audit_con=_db(); audit_cur=audit_con.cursor()
        try:
            _audit(audit_cur,sid,request,"EXAM_DELETE",exam_name)
            audit_con.commit()
        except Exception:
            try: audit_con.rollback()
            except Exception: pass
        finally:
            audit_con.close()
    except Exception:
        pass
    return RedirectResponse("/app/exams",303)

@router.get("/app/finance/fees", response_class=HTMLResponse)
def fees_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "fees.view"):
        return HTMLResponse("You do not have permission to view fees.", 403)
    con=_db();cur=con.cursor()
    students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    fees=cur.execute("""SELECT f.*,s.name student_name,s.admission_no FROM fees f JOIN students s ON s.id=f.student_id
        WHERE f.school_id=? ORDER BY f.id DESC LIMIT 100""",(sid,)).fetchall()
    con.close()
    sopts="".join(f"<option value='{s['id']}'>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    trs="".join(f"<tr><td>{escape(str(x['student_name']))}</td><td>{x['amount']}</td><td>{x['paid'] or 0}</td><td>{x['status'] or 'Pending'}</td><td>{escape(str(x['description'] or ''))}</td></tr>" for x in fees)
    body=f"""<div class='page'><h1>Fees & Student Charges</h1><div class='card section'><h2>Charge a student</h2><form method='post' action='/app/finance/fees/add' class='formgrid'><select name='student_id' class='field' required>{sopts}</select><input name='amount' type='number' step='0.01' min='0' required placeholder='Amount' class='field'><select name='description' required class='field'><option value=''>Select charge type</option><option>Tuition Fees</option><option>Activity Fees</option><option>Examination Fees</option><option>Transport</option><option>Boarding</option><option>Lunch / Meals</option><option>Uniform</option><option>Books</option><option>Other</option></select><input name='due_date' type='date' class='field'><button class='btn'>Post Charge</button></form></div><div class='card section'><h2>Receive fee payment</h2><form method='post' action='/app/finance/payments' class='formgrid'><select name='student_id' class='field' required>{sopts}</select><input name='amount' type='number' step='0.01' min='0.01' required placeholder='Amount' class='field'><select name='method' class='field'><option>Cash</option><option>Bank</option><option>Mobile Money</option><option>Cheque</option><option>Card</option><option>Other</option></select><input name='reference' placeholder='Receipt / reference' class='field'><button class='btn'>Record Payment</button></form></div><div class='card section'><table><thead><tr><th>Student</th><th>Charged</th><th>Paid</th><th>Status</th><th>Description</th></tr></thead><tbody>{trs or '<tr><td colspan=5>No fee charges.</td></tr>'}</tbody></table></div></div><style>.formgrid{{display:grid;grid-template-columns:1.5fr 1fr 1.5fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Fees",body)

@router.post("/app/finance/fees/add")
def fees_add(request: Request,student_id:int=Form(...),amount:float=Form(...),description:str=Form(...),due_date:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "fees.edit"):
        return HTMLResponse("You do not have permission to post fee charges.", 403)
    if amount <= 0:
        return HTMLResponse("Fee amount must be greater than zero. <a href='/app/finance/fees'>Back</a>",400)
    if not description.strip():
        return HTMLResponse("Fee description is required. <a href='/app/finance/fees'>Back</a>",400)
    con=_db();cur=con.cursor()
    if not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone():
        con.close();return HTMLResponse("Student not found in this school. <a href='/app/finance/fees'>Back</a>",404)
    cur.execute("INSERT INTO fees(school_id,student_id,amount,paid,description,due_date,status) VALUES(?,?,?,?,?,?,?)",(sid,student_id,amount,0,description.strip(),due_date or None,"Pending"))
    _audit(cur,sid,request,"FEE_CHARGE",f"Charged {amount} to student {student_id}")
    con.commit();con.close();return RedirectResponse("/app/finance/fees",303)

@router.post("/app/finance/payments")
def fee_payment(request: Request,student_id:int=Form(...),amount:float=Form(...),reference:str=Form(""),method:str=Form("Cash")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "fees.edit"):
        return HTMLResponse("You do not have permission to record fee payments.", 403)
    if amount <= 0:return HTMLResponse("Payment amount must be greater than zero. <a href='/app/finance/fees'>Back</a>",400)
    con=_db();cur=con.cursor()
    if not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone():
        con.close();return HTMLResponse("Student not found in this school. <a href='/app/finance/fees'>Back</a>",404)
    charges=cur.execute("SELECT id,amount,paid FROM fees WHERE school_id=? AND student_id=? AND COALESCE(amount,0)>COALESCE(paid,0) ORDER BY id",(sid,student_id)).fetchall()
    outstanding=sum(max(0,float(f["amount"] or 0)-float(f["paid"] or 0)) for f in charges)
    if outstanding <= 0:
        con.close();return HTMLResponse("This student has no outstanding fee balance. <a href='/app/finance/fees'>Back</a>",400)
    if amount > outstanding:
        con.close();return HTMLResponse(f"Payment exceeds outstanding balance ({outstanding:.2f}). <a href='/app/finance/fees'>Back</a>",400)
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d")
    cur.execute("INSERT INTO fee_payments(school_id,student_id,amount,reference,method,date,received_by) VALUES(?,?,?,?,?,?,?)",(sid,student_id,amount,reference.strip(),method.strip() or "Cash",now,str(request.session.get("email",""))))
    remaining=amount
    for f in charges:
        if remaining<=0:break
        applied=min(remaining,float(f["amount"])-float(f["paid"] or 0)); newpaid=float(f["paid"] or 0)+applied; remaining-=applied
        cur.execute("UPDATE fees SET paid=?,status=? WHERE id=? AND school_id=?",(newpaid,"Paid" if newpaid>=float(f["amount"]) else "Partial",f["id"],sid))
    cur.execute("INSERT INTO cashbook(school_id,date,reference,description,debit,credit,account) VALUES(?,?,?,?,?,?,?)",(sid,now,reference.strip(),"School fee receipt",0,amount,"Fees"))
    _audit(cur,sid,request,"FEE_PAYMENT",f"Received {amount} from student {student_id}")
    con.commit();con.close();return RedirectResponse("/app/finance/fees",303)

# Additional native DaviSchool workspaces
def _simple_rows(rows, cols):
    return "".join("<tr>"+"".join(f"<td>{escape(str(row[c] if row[c] is not None else ''))}</td>" for c in cols)+"</tr>" for row in rows)

# The timetable workspace is implemented in the isolated aSc-style manager module.
# Keeping it in its own router prevents timetable changes from touching the other
# DaviSchool school-side modules.
from app.timetable_manager import router as timetable_manager_router
router.include_router(timetable_manager_router)

@router.get("/app/announcements", response_class=HTMLResponse)
def announcements_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "communications.view"):
        return HTMLResponse("You do not have permission to view announcements.", 403)
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM announcements WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall();con.close()
    tr=_simple_rows(rows,["title","message","audience","created_at"])
    body=f"""<div class='page'><h1>Announcements</h1><div class='muted'>Publish school notices and internal communications.</div>
<div class='card section'><h2>New announcement</h2><form method='post' action='/app/announcements/add' style='display:grid;gap:10px'><input name='title' required placeholder='Title' class='field'><select name='audience' class='field'><option>All</option><option>Students</option><option>Parents</option><option>Teachers</option><option>Staff</option></select><textarea name='message' required placeholder='Message' class='field' rows='5'></textarea><button class='btn'>Publish Announcement</button></form></div>
<div class='card section'><h2>Published announcements ({len(rows)})</h2><table><thead><tr><th>Title</th><th>Message</th><th>Audience</th><th>Created</th></tr></thead><tbody>{tr or '<tr><td colspan=4>No announcements yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Announcements",body)

@router.post("/app/announcements/add")
def announcements_add(request: Request,title:str=Form(...),message:str=Form(...),audience:str=Form("All")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "communications.edit"):
        return HTMLResponse("You do not have permission to publish announcements.", 403)
    con=_db();cur=con.cursor();now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO announcements(school_id,title,message,audience,created_at) VALUES(?,?,?,?,?)",(sid,title.strip(),message.strip(),audience,now))
    _audit(cur,sid,request,"ANNOUNCEMENT_CREATE",title.strip());con.commit();con.close();return RedirectResponse("/app/announcements",303)

@router.get("/app/roles", response_class=HTMLResponse)
def roles_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "settings.manage"):
        return HTMLResponse("You do not have permission to manage roles and permissions.", 403)
    con=_db();cur=con.cursor()
    rows=cur.execute("SELECT * FROM roles_permissions WHERE school_id=? ORDER BY role,permission",(sid,)).fetchall()
    _ensure_class_teacher_assignments_table(cur)
    classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    teachers=cur.execute("SELECT id,name,role FROM teachers WHERE school_id=? AND COALESCE(status,'active')='active' ORDER BY name",(sid,)).fetchall()
    assignments=cur.execute("""SELECT a.id,a.class_id,a.teacher_id,c.name class_name,c.stream,t.name teacher_name
        FROM class_teacher_assignments a JOIN classes c ON c.id=a.class_id JOIN teachers t ON t.id=a.teacher_id
        WHERE a.school_id=? ORDER BY c.name,c.stream""",(sid,)).fetchall()
    con.close()
    tr=_simple_rows(rows,["role","permission","enabled"])
    class_opts="".join("<option value='%s'>%s%s</option>"%(c["id"],escape(str(c["name"])),(" · "+escape(str(c["stream"] or ""))) if c["stream"] else "") for c in classes)
    teacher_opts="".join("<option value='%s'>%s — %s</option>"%(t["id"],escape(str(t["name"])),escape(str(t["role"] or ""))) for t in teachers)
    assignment_rows=[]
    for a in assignments:
        assignment_rows.append(
            "<tr><td>%s%s</td><td>%s</td><td><a class='btn edit' href='/app/roles/class-teacher-assignment/edit/%s'>Edit</a></td></tr>"
            % (
                escape(str(a["class_name"])),
                (" · " + escape(str(a["stream"] or ""))) if a["stream"] else "",
                escape(str(a["teacher_name"])),
                a["id"],
            )
        )
    assignment_rows="".join(assignment_rows)
    body=f"""<div class='page'><h1>Roles & Permissions</h1><div class='muted'>Control permissions for school roles.</div>
<div class='card section'><h2>Class Teacher Assignments</h2><div class='muted'>Assign the staff member who has the Class Teacher responsibility to each class. Report cards automatically use this assignment for the class teacher name and signature line.</div>
<form method='post' action='/app/roles/class-teacher-assignment' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='class_id' class='field' required><option value=''>Select class</option>{class_opts}</select><select name='teacher_id' class='field' required><option value=''>Select class teacher</option>{teacher_opts}</select><button class='btn'>Save Assignment</button></form>
<table style='margin-top:14px'><thead><tr><th>Class</th><th>Class Teacher</th><th>Actions</th></tr></thead><tbody>{assignment_rows or "<tr><td colspan='3'>No class teacher assignments yet.</td></tr>"}</tbody></table></div>
<div class='card section'><h2>Grant permission</h2><form method='post' action='/app/roles/add' style='display:grid;grid-template-columns:1fr 2fr 1fr;gap:10px'><select name='role' class='field'><option>school_admin</option><option>teacher</option><option>parent</option><option>student</option><option>accountant</option><option>registrar</option></select><select name='permission' required class='field'><option value=''>Select permission</option><option>students.view</option><option>students.create</option><option>students.edit</option><option>classes.view</option><option>classes.create</option><option>subjects.view</option><option>subjects.create</option><option>exams.view</option><option>exams.create</option><option>marks.view</option><option>marks.edit</option><option>attendance.view</option><option>attendance.edit</option><option>timetable.view</option><option>timetable.edit</option><option>fees.view</option><option>fees.edit</option><option>finance.view</option><option>finance.edit</option><option>reports.view</option><option>reports.edit</option><option>staff.view</option><option>staff.create</option><option>staff.edit</option><option>communications.view</option><option>communications.edit</option><option>settings.view</option><option>settings.edit</option><option>audit.view</option><option>users.manage</option><option>settings.manage</option></select><select name='enabled' class='field'><option value='1'>Enabled</option><option value='0'>Disabled</option></select><button class='btn'>Save Permission</button></form></div>
<div class='card section'><h2>Configured permissions ({len(rows)})</h2><table><thead><tr><th>Role</th><th>Permission</th><th>Enabled</th></tr></thead><tbody>{tr or '<tr><td colspan=3>No custom permissions yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Roles & Permissions",body)

@router.post("/app/roles/class-teacher-assignment")
def save_class_teacher_assignment(request: Request, class_id:int=Form(...), teacher_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "settings.manage"):
        return HTMLResponse("You do not have permission to manage class teacher assignments.",403)
    con=_db();cur=con.cursor();_ensure_class_teacher_assignments_table(cur)
    valid_class=cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
    valid_teacher=cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=? AND COALESCE(status,'active')='active'",(teacher_id,sid)).fetchone()
    if not valid_class or not valid_teacher:
        con.close();return HTMLResponse("Invalid class or teacher selection. <a href='/app/roles'>Back</a>",400)
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    # Update an existing assignment for this class, otherwise create one.
    # This avoids relying on database-specific UPSERT syntax and works with
    # both the existing SQLite database and the PostgreSQL deployment.
    existing=cur.execute(
        "SELECT id FROM class_teacher_assignments WHERE school_id=? AND class_id=? LIMIT 1",
        (sid,class_id)
    ).fetchone()
    if existing:
        cur.execute(
            "UPDATE class_teacher_assignments SET teacher_id=?,assigned_at=? WHERE id=? AND school_id=?",
            (teacher_id,now,existing["id"],sid)
        )
        action="CLASS_TEACHER_ASSIGNMENT_EDIT"
        detail="Updated class teacher assignment for class %s"%class_id
    else:
        cur.execute(
            "INSERT INTO class_teacher_assignments(school_id,class_id,teacher_id,assigned_at) VALUES(?,?,?,?)",
            (sid,class_id,teacher_id,now)
        )
        action="CLASS_TEACHER_ASSIGNMENT"
        detail="Assigned class teacher for class %s"%class_id
    _audit(cur,sid,request,action,detail)
    con.commit()
    con.close()
    return RedirectResponse("/app/roles",303)

@router.get("/app/roles/class-teacher-assignment/edit/{assignment_id}", response_class=HTMLResponse)
def edit_class_teacher_assignment_page(request: Request, assignment_id: int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "settings.manage"):
        return HTMLResponse("You do not have permission to manage class teacher assignments.",403)
    con=_db();cur=con.cursor();_ensure_class_teacher_assignments_table(cur)
    assignment=cur.execute("""SELECT id,class_id,teacher_id FROM class_teacher_assignments
                              WHERE id=? AND school_id=?""",(assignment_id,sid)).fetchone()
    classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    teachers=cur.execute("SELECT id,name,role FROM teachers WHERE school_id=? AND COALESCE(status,'active')='active' ORDER BY name",(sid,)).fetchall()
    con.close()
    if not assignment:
        return HTMLResponse("Class teacher assignment not found. <a href='/app/roles'>Back</a>",404)
    class_opts="".join("<option value='%s' %s>%s%s</option>"%(c["id"],"selected" if int(c["id"])==int(assignment["class_id"]) else "",escape(str(c["name"] or "")),(" · "+escape(str(c["stream"] or ""))) if c["stream"] else "") for c in classes)
    teacher_opts="".join("<option value='%s' %s>%s — %s</option>"%(t["id"],"selected" if int(t["id"])==int(assignment["teacher_id"]) else "",escape(str(t["name"] or "")),escape(str(t["role"] or ""))) for t in teachers)
    body=f"""<div class='page'><h1>Edit Class Teacher Assignment</h1><div class='muted'>Change the class or teacher for this assignment.</div>
<div class='card section'><form method='post' action='/app/roles/class-teacher-assignment/edit/{assignment_id}' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'>
<select name='class_id' class='field' required><option value=''>Select class</option>{class_opts}</select>
<select name='teacher_id' class='field' required><option value=''>Select class teacher</option>{teacher_opts}</select>
<button class='btn'>Save Changes</button><a class='btn secondary' href='/app/roles'>Cancel</a></form></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{display:inline-block;padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}}.secondary{{background:#64748b}}.edit{{background:#176B3A;margin-right:5px}}.danger{{background:#b91c1c}}</style></div>"""
    return _school_page(request,"Edit Class Teacher Assignment",body)


@router.post("/app/roles/class-teacher-assignment/edit/{assignment_id}")
def edit_class_teacher_assignment(request: Request, assignment_id: int, class_id:int=Form(...), teacher_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "settings.manage"):
        return HTMLResponse("You do not have permission to manage class teacher assignments.",403)
    con=_db();cur=con.cursor();_ensure_class_teacher_assignments_table(cur)
    assignment=cur.execute("SELECT id FROM class_teacher_assignments WHERE id=? AND school_id=?",(assignment_id,sid)).fetchone()
    valid_class=cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone()
    valid_teacher=cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=? AND COALESCE(status,'active')='active'",(teacher_id,sid)).fetchone()
    duplicate=cur.execute("SELECT id FROM class_teacher_assignments WHERE school_id=? AND class_id=? AND id<>?",(sid,class_id,assignment_id)).fetchone()
    if not assignment:
        con.close();return HTMLResponse("Class teacher assignment not found. <a href='/app/roles'>Back</a>",404)
    if not valid_class or not valid_teacher:
        con.close();return HTMLResponse("Invalid class or teacher selection. <a href='/app/roles'>Back</a>",400)
    if duplicate:
        con.close();return HTMLResponse("That class already has a class teacher assignment. <a href='/app/roles'>Back</a>",400)
    now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE class_teacher_assignments SET class_id=?,teacher_id=?,assigned_at=? WHERE id=? AND school_id=?",(class_id,teacher_id,now,assignment_id,sid))
    _audit(cur,sid,request,"CLASS_TEACHER_ASSIGNMENT_EDIT","Edited class teacher assignment %s"%assignment_id)
    con.commit();con.close()
    return RedirectResponse("/app/roles",303)


@router.post("/app/roles/class-teacher-assignment/delete/{assignment_id}")
def delete_class_teacher_assignment(request: Request, assignment_id:int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "settings.manage"):
        return HTMLResponse("You do not have permission to manage class teacher assignments.",403)
    con=_db();cur=con.cursor();_ensure_class_teacher_assignments_table(cur)
    assignment=cur.execute("SELECT id FROM class_teacher_assignments WHERE id=? AND school_id=?",(assignment_id,sid)).fetchone()
    if not assignment:
        con.close();return HTMLResponse("Class teacher assignment not found. <a href='/app/roles'>Back</a>",404)
    cur.execute("DELETE FROM class_teacher_assignments WHERE id=? AND school_id=?",(assignment_id,sid))
    _audit(cur,sid,request,"CLASS_TEACHER_ASSIGNMENT_DELETE","Deleted class teacher assignment %s"%assignment_id)
    con.commit();con.close()
    return RedirectResponse("/app/roles",303)


@router.post("/app/roles/add")
def roles_add(request: Request,role:str=Form(...),permission:str=Form(...),enabled:int=Form(1)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "settings.manage"):
        return HTMLResponse("You do not have permission to manage roles and permissions.", 403)
    allowed_roles={"school_admin","teacher","parent","student","accountant","registrar"}
    allowed_permissions={"students.view","students.create","students.edit","classes.view","classes.create","subjects.view","subjects.create","exams.view","exams.create","marks.view","marks.edit","attendance.view","attendance.edit","timetable.view","timetable.edit","fees.view","fees.edit","finance.view","finance.edit","reports.view","reports.edit","staff.view","staff.create","staff.edit","communications.view","communications.edit","settings.view","settings.edit","audit.view","users.manage","class_teacher.view","class_teacher.edit","settings.manage"}
    role_v=role.strip(); perm_v=permission.strip(); enabled_v=1 if int(enabled) else 0
    if role_v not in allowed_roles or perm_v not in allowed_permissions:
        return HTMLResponse("Invalid role or permission. <a href='/app/roles'>Back</a>",400)
    con=_db();cur=con.cursor()
    existing=cur.execute("SELECT id FROM roles_permissions WHERE school_id=? AND role=? AND permission=? ORDER BY id DESC LIMIT 1",(sid,role_v,perm_v)).fetchone()
    if existing:
        cur.execute("UPDATE roles_permissions SET enabled=? WHERE id=? AND school_id=?",(enabled_v,existing["id"],sid))
    else:
        cur.execute("INSERT INTO roles_permissions(school_id,role,permission,enabled) VALUES(?,?,?,?)",(sid,role_v,perm_v,enabled_v))
    _audit(cur,sid,request,"PERMISSION_CHANGE",f"{role_v}: {perm_v}={enabled_v}");con.commit();con.close();return RedirectResponse("/app/roles",303)

@router.get("/app/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "audit.view"):
        return HTMLResponse("You do not have permission to view the audit trail.", 403)
    con=_db();cur=con.cursor()
    rows=cur.execute("SELECT * FROM system_audit WHERE school_id=? ORDER BY id DESC LIMIT 500",(sid,)).fetchall()
    con.close()
    tr=_simple_rows(rows,["timestamp","user_email","action","details"])
    body=f"""<div class='page'><h1>Audit Trail</h1>
<div class='muted'>Security and activity history for this school.</div>
<div class='card section'>
<div style='display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap'>
<h2 style='margin:0'>Recent activity ({len(rows)})</h2>
<form method='post' action='/app/audit/clear' onsubmit="return confirm('Clear all audit trail records for this school? This action cannot be undone.');">
<button class='btn' type='submit' style='background:#b91c1c!important;border-color:#b91c1c!important'>🗑️ Clear</button>
</form></div>
<table><thead><tr><th>Timestamp</th><th>User</th><th>Action</th><th>Details</th></tr></thead><tbody>{tr or '<tr><td colspan=4>No activity recorded yet.</td></tr>'}</tbody></table>
</div></div>"""
    return _school_page(request,"Audit Trail",body)

@router.post("/app/audit/clear")
def audit_clear(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "audit.view"):
        return HTMLResponse("You do not have permission to clear the audit trail.",403)
    con=_db();cur=con.cursor()
    cur.execute("DELETE FROM system_audit WHERE school_id=?",(sid,))
    con.commit();con.close()
    return RedirectResponse("/app/audit",303)

@router.get("/app/accounting", response_class=HTMLResponse)
def accounting_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "finance.view"):
        return HTMLResponse("You do not have permission to view accounting.", 403)
    con=_db();cur=con.cursor()
    expenses=cur.execute("SELECT * FROM expenses WHERE school_id=? ORDER BY id DESC LIMIT 100",(sid,)).fetchall()
    vouchers=cur.execute("SELECT * FROM payment_vouchers WHERE school_id=? ORDER BY id DESC LIMIT 100",(sid,)).fetchall()
    lpos=cur.execute("SELECT * FROM lpos WHERE school_id=? ORDER BY id DESC LIMIT 100",(sid,)).fetchall()
    cash=cur.execute("SELECT COALESCE(SUM(credit),0) credit,COALESCE(SUM(debit),0) debit FROM cashbook WHERE school_id=?",(sid,)).fetchone()
    con.close()
    exp_total=sum(float(x["amount"] or 0) for x in expenses)
    body=f"""<div class='page'><h1>Accounting</h1><div class='muted'>School accounting workspace: expenses, vouchers, LPOs and cashbook.</div>
<div class='grid'><div class='card'><div class='label'>Expenses listed</div><div class='kpi'>{exp_total:,.2f}</div></div><div class='card'><div class='label'>Cash credits</div><div class='kpi'>{float(cash['credit'] or 0):,.2f}</div></div><div class='card'><div class='label'>Cash debits</div><div class='kpi'>{float(cash['debit'] or 0):,.2f}</div></div><div class='card'><div class='label'>Open LPOs</div><div class='kpi'>{len(lpos)}</div></div></div>
<div class='card section'><h2>Record expense</h2><form method='post' action='/app/accounting/expense' style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'><select name='category' required class='field'><option value=''>Select expense category</option><option>Salaries</option><option>Utilities</option><option>Stationery</option><option>Repairs & Maintenance</option><option>Transport</option><option>Food & Catering</option><option>Learning Materials</option><option>Rent</option><option>Other</option></select><input name='description' required placeholder='Description' class='field'><input name='amount' required type='number' step='0.01' placeholder='Amount' class='field'><input name='paid_to' placeholder='Paid to' class='field'><input name='voucher_no' placeholder='Voucher no.' class='field'><input name='date' type='date' class='field'><button class='btn'>Save Expense</button></form></div>
<div class='card section'><h2>Expenses</h2><table><thead><tr><th>Category</th><th>Description</th><th>Amount</th><th>Paid To</th><th>Voucher</th><th>Date</th></tr></thead><tbody>{_simple_rows(expenses,['category','description','amount','paid_to','voucher_no','date']) or '<tr><td colspan=6>No expenses yet.</td></tr>'}</tbody></table></div>
<div class='card section'><h2>Payment Vouchers ({len(vouchers)})</h2><table><thead><tr><th>Voucher</th><th>Payee</th><th>Description</th><th>Amount</th><th>Date</th><th>Status</th></tr></thead><tbody>{_simple_rows(vouchers,['voucher_no','payee','description','amount','date','status']) or '<tr><td colspan=6>No vouchers yet.</td></tr>'}</tbody></table></div>
<div class='card section'><h2>LPOs ({len(lpos)})</h2><table><thead><tr><th>LPO</th><th>Supplier</th><th>Description</th><th>Amount</th><th>Date</th><th>Status</th></tr></thead><tbody>{_simple_rows(lpos,['lpo_no','supplier','description','amount','date','status']) or '<tr><td colspan=6>No LPOs yet.</td></tr>'}</tbody></table></div>
</div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Accounting",body)

@router.post("/app/accounting/expense")
def accounting_expense(request: Request,category:str=Form(...),description:str=Form(...),amount:float=Form(...),paid_to:str=Form(""),voucher_no:str=Form(""),date:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)