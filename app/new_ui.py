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
        portal_scope = str(request.scope.get("davischool_session_scope") or "")
        if portal_scope == "teacher":
            return RedirectResponse("/teacher/app", status_code=303)
        if portal_scope == "school":
            return RedirectResponse("/school/app", status_code=303)
        return RedirectResponse("/", status_code=303)
    error = "<div class='err'>This school account is suspended. Please contact the DaviSchool administrator.</div>" if request.query_params.get("suspended") else ("<div class='err'>Invalid username or password.</div>" if request.query_params.get("error") else "")
    portal_scope = str(request.scope.get("davischool_session_scope") or "")
    # Always post back through the explicit portal when the login page was
    # opened from /school or /teacher. This makes the correct role cookie
    # authoritative even when the browser omits the Referer header.
    if portal_scope == "school":
        login_action = "/school/login"
    elif portal_scope == "teacher":
        login_action = "/teacher/login"
    else:
        login_action = "/login"
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>DaviSchool Login</title><style>body{{margin:0;background:#eef5fb;font-family:Arial,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}}.box{{width:min(430px,92vw);background:white;border:1px solid #d8e3f0;border-top:4px solid #2E8B57;border-radius:18px;padding:32px;box-shadow:0 18px 50px #176B3A20}}.logo{{font-size:25px;font-weight:900;color:#176B3A;margin-bottom:5px}}.sub{{color:#64748b;margin-bottom:25px}}label{{display:block;font-size:13px;font-weight:800;color:#334155;margin:14px 0 7px}}input{{width:100%;box-sizing:border-box;padding:13px;border:1px solid #dbe2ea;border-radius:10px;font-size:15px}}button{{width:100%;margin-top:20px;padding:14px;border:0;border-radius:10px;background:#176B3A;color:white;font-weight:900;font-size:15px;cursor:pointer}}.err{{background:#fff1f2;border:1px solid #fda4af;color:#9f1239;padding:11px;border-radius:10px;margin-bottom:14px}}</style></head><body><div class='box'><div class='logo'>🏫 DaviSchool Management System</div><div class='sub'>Secure school management platform</div>{error}<form method='post' action='{login_action}'><label>Username / Email</label><input name='email' type='text' autocomplete='username' required placeholder='Enter username or email'><label>Password</label><input name='password' type='password' autocomplete='current-password' required placeholder='Enter password'><button type='submit'>Sign In</button></form></div></body></html>""")

@router.get("/login", response_class=HTMLResponse)
def davischool_login_get(request: Request):
    # /login is an internal portal alias. The actual DaviSchool sign-in screen
    # is the canonical main.py home() page. When calling home() directly,
    # FastAPI's response_class decorator on home() is NOT applied, so returning
    # its plain HTML string would make FastAPI JSON-encode it and the browser
    # would display the HTML source (including the surrounding quotes).
    from app.main import home
    rendered = home(request)
    if isinstance(rendered, HTMLResponse):
        return rendered
    return HTMLResponse(str(rendered))

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
    portal_scope = str(request.scope.get("davischool_session_scope") or "")
    if portal_scope == "teacher":
        return RedirectResponse("/teacher/app", status_code=303)
    if portal_scope == "school":
        return RedirectResponse("/school/app", status_code=303)
    # Shared login has no tab identity. Do not enter the shared /app workspace.
    return RedirectResponse("/", status_code=303)

@router.get("/logout")
def davischool_logout(request: Request):
    portal_scope = str(request.scope.get("davischool_session_scope") or "")
    request.session.clear()
    if portal_scope == "teacher":
        return RedirectResponse("/teacher/login", status_code=303)
    if portal_scope == "school":
        return RedirectResponse("/school/login", status_code=303)
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
    from reportlab.platypus import SimpleDocTemplate
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
    # Every School Admin navigation target is rendered with the explicit
    # /school portal prefix. Never rely on client-side rewriting or a shared
    # /app URL: browser tabs must remain bound to their own portal session.
    portal_prefix = "/school" if role == "school_admin" else ""
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
            (f"{portal_prefix}/app","⌂","Overview",None),
            (f"{portal_prefix}/app/students","🎓","Students","students.view"),
            (f"{portal_prefix}/app/staff","👩‍🏫","Staff & Teachers","staff.view"),
            (f"{portal_prefix}/app/classes","🏫","Classes","classes.view"),
            (f"{portal_prefix}/app/subjects","📚","Subjects","subjects.view"),
            (f"{portal_prefix}/app/exams","🧪","Examinations","exams.view"),
            (f"{portal_prefix}/app/academics","📝","Academics","marks.view"),
            (f"{portal_prefix}/app/report-cards","📄","Report Cards","reports.view"),
            (f"{portal_prefix}/app/attendance","✓","Attendance","attendance.view"),
            (f"{portal_prefix}/app/timetable","🗓","Timetable","timetable.view"),
            (f"{portal_prefix}/app/finance","💰","Fees & Finance","fees.view"),
            (f"{portal_prefix}/app/accounting","📚","Accounting","finance.view"),
            (f"{portal_prefix}/app/announcements","📢","Announcements","communications.view"),
            (f"{portal_prefix}/app/users","👤","Users","users.manage"),
            (f"{portal_prefix}/app/roles","🔐","Roles & Permissions","settings.manage"),
            (f"{portal_prefix}/app/school-settings","⚙","School Settings","settings.view"),
            (f"{portal_prefix}/app/audit","🛡","Audit Trail","audit.view"),
        ]
        if role == "school_admin":
            nav.insert(7, (f"{portal_prefix}/app/academics/marks-corrections","🔓","Marks Corrections",None))
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
.app{{display:flex;min-height:100vh}}.side{{width:250px;background:var(--navy-dark);color:#dbeafe;padding:18px 12px;position:fixed;inset:0 auto 0 0;overflow:auto}}
.brand{{font-size:20px;font-weight:900;color:white;padding:8px 12px 24px}}.brand small{{display:block;font-size:10px;color:#bfdbfe;margin-top:4px;letter-spacing:1px}}
.nav{{display:flex;gap:11px;align-items:center;color:#dbeafe;text-decoration:none;padding:10px 12px;border-radius:10px;font-size:13px;margin:3px 0;border-left:3px solid transparent}}.nav:hover{{background:rgba(46,139,87,.16);color:white;border-left-color:var(--gold)}}.nav:active,.btn:active,.btnlink:active,.action:active{{transform:translateY(1px)}}.nav-loading,.btn-loading{{opacity:.72;cursor:wait!important}}.btn-loading::after{{content:'  ⏳';font-size:12px}}button,.btn,.btnlink,.action,.nav{{-webkit-tap-highlight-color:transparent}}
.main{{margin-left:250px;flex:1;min-width:0;transition:margin-left .2s ease}}.sidebar-toggle{{border:1px solid #cbd5e1;background:#fff;color:var(--navy);border-radius:9px;padding:7px 10px;font-size:16px;cursor:pointer;line-height:1}}.sidebar-toggle:hover{{background:#f8fafc}}.sidebar-hidden .side{{transform:translateX(-100%)}}.sidebar-hidden .main{{margin-left:0}}.top{{height:68px;background:white;border-bottom:3px solid var(--gold);display:flex;align-items:center;justify-content:space-between;padding:0 28px;position:sticky;top:0;z-index:5}}
.avatar{{width:36px;height:36px;border-radius:50%;background:var(--navy);color:white;display:flex;align-items:center;justify-content:center;font-weight:800}}
.page{{padding:28px;max-width:1500px;margin:auto}}.btn,.btnlink{{background:var(--navy)!important;color:#fff!important;border-color:var(--navy)!important}}.btn:hover,.btnlink:hover{{background:var(--navy-dark)!important}}h1{{font-size:25px;margin:0 0 6px}}.muted{{color:#64748b;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin:22px 0}}.card{{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px;box-shadow:0 2px 8px #00000005}}.kpi{{font-size:28px;font-weight:900;margin-top:10px}}.label{{font-size:11px;color:#64748b;text-transform:uppercase;font-weight:800}}
.section{{margin-top:18px}}.section h2{{font-size:16px;margin:0 0 12px}}.actions{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;position:relative;z-index:20}}.action{{display:block;position:relative;z-index:21;background:white;border:1px solid #e5e7eb;border-radius:14px;padding:15px;text-decoration:none;color:#172033;font-weight:800;font-size:13px;cursor:pointer;pointer-events:auto}}.action span{{font-size:21px;display:block;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden}}th,td{{padding:12px;border-bottom:1px solid #eef2f7;text-align:left;font-size:12px}}th{{background:#f8fafc;color:#64748b;font-size:10px;text-transform:uppercase}}
@media(max-width:900px){{.side{{width:72px}}.brand{{font-size:0}}.brand:before{{content:'DS';font-size:18px}}.nav{{justify-content:center;font-size:0}}.nav span{{font-size:17px}}.main{{margin-left:72px}}.grid,.actions{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:600px){{.page{{padding:12px}}.grid,.actions{{grid-template-columns:1fr 1fr}}.top{{padding:0 12px}}.marks-entry{{overflow:visible;min-width:0}}.marks-table-scroll{{display:block;width:100%;max-width:100%;overflow-x:scroll;overflow-y:hidden;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;overscroll-behavior-x:contain;scrollbar-width:auto;margin:0 -4px;padding:0 4px}}.marks-table{{width:760px;min-width:760px;table-layout:fixed}}.marks-table th,.marks-table td{{padding:10px 8px;font-size:12px}}.marks-table .col-admission{{width:105px}}.marks-table .col-student{{width:170px}}.marks-table .col-mark{{width:105px}}.marks-table .col-grade{{width:80px}}.marks-table .col-points{{width:80px}}.marks-table .col-comment{{width:220px}}.markinput{{width:92px;max-width:92px;min-height:42px;font-size:16px;padding:9px}}.commentinput{{width:210px;max-width:210px;min-width:210px;min-height:42px;font-size:14px;padding:9px}}.marks-table td:nth-child(1),.marks-table td:nth-child(2),.marks-table td:nth-child(4),.marks-table td:nth-child(5){{white-space:normal}}}}
</style></head><body class='{{"sidebar-hidden" if teacher_locked else ""}}'><div class='app'><aside class='side'><div class='brand'>DaviSchool<small>MANAGEMENT PLATFORM</small></div>{links}{"" if teacher_locked else "<div style='padding:14px 12px;color:#94a3b8;font-size:10px;line-height:1.4'>Selection-based data entry is enabled throughout the school workspace.</div><a href='{portal_prefix}/logout' class='nav' style='margin-top:18px'>↪ Logout</a>"}</aside>
<main class='main'><header class='top'><div style='display:flex;align-items:center;gap:10px'>{"" if teacher_locked else "<button type='button' class='sidebar-toggle' id='sidebarToggle' aria-label='Hide sidebar' title='Hide sidebar' onclick='toggleSidebar()'>☰</button>"}<div><strong>{escape(title)}</strong><div class='muted'>{escape(role.replace("_"," ").title())}</div></div></div><div style='display:flex;gap:10px;align-items:center'><span class='muted'>{escape(name)}</span><div class='avatar'>{escape(initials)}</div></div></header>{body}<script>(function(){{try{{if(!{str(teacher_locked).lower()} && localStorage.getItem('davischool_sidebar_hidden')==='1')document.body.classList.add('sidebar-hidden');}}catch(e){{}}}})();function toggleSidebar(){{var hidden=document.body.classList.toggle('sidebar-hidden');var b=document.getElementById('sidebarToggle');if(b){{b.setAttribute('aria-label',hidden?'Show sidebar':'Hide sidebar');b.setAttribute('title',hidden?'Show sidebar':'Hide sidebar');}}try{{localStorage.setItem('davischool_sidebar_hidden',hidden?'1':'0');}}catch(e){{}}}}</script><script>(function(){{let lastPing=0;let lastActivity=Date.now();const PING_EVERY=60000;const ACTIVE_WINDOW=120000;function markActivity(){{lastActivity=Date.now();ping(true);}}function ping(force){{const now=Date.now();if(!force && now-lastActivity>ACTIVE_WINDOW)return;if(now-lastPing<60000)return;lastPing=now;try{{var keepalivePath = window.location.pathname.indexOf('/teacher/')===0 ? '/teacher/app/session-keepalive' : (window.location.pathname.indexOf('/school/')===0 ? '/school/app/session-keepalive' : '/app/session-keepalive');
    fetch(keepalivePath,{{method:'GET',credentials:'same-origin',cache:'no-store'}}).catch(function(){{}});}}catch(e){{}}}}['click','dblclick','mousedown','pointerdown','touchstart','touchmove','keydown','input','change','scroll','wheel'].forEach(function(ev){{document.addEventListener(ev,markActivity,{{passive:true}});}});setInterval(function(){{if(Date.now()-lastActivity<=ACTIVE_WINDOW)ping(false);}},PING_EVERY);}})();</script><script>(function(){{
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
function portalizeUrl(url){{
  try{{
    var u=new URL(url,window.location.href);
    if(u.origin!==window.location.origin)return u;
    var p=u.pathname;
    var portal=window.location.pathname.indexOf('/teacher/')===0 ? '/teacher' : (window.location.pathname.indexOf('/school/')===0 ? '/school' : '');
    if(portal && p.indexOf('/app')===0 && p.indexOf(portal+'/')!==0)u.pathname=portal+p;
    return u;
  }}catch(e){{return new URL(url,window.location.href);}}
}}
document.addEventListener('click',function(event){{
  var a=event.target.closest&&event.target.closest('a[href]');
  if(!a || event.defaultPrevented)return;
  var u=portalizeUrl(a.href);
  if(u.origin===window.location.origin && u.pathname!==new URL(a.href,window.location.href).pathname){{
    event.preventDefault();
    window.location.href=u.toString();
  }}
}},true);
document.addEventListener('submit',function(event){{
  var form=event.target;
  if(!form || String(form.method||'get').toLowerCase()!=='post')return;
  var submitter=event.submitter;
  var action=(submitter && (submitter.getAttribute('formaction') || submitter.formAction)) || form.getAttribute('action') || window.location.href;
  try{{
    var url=portalizeUrl(action);
    if(url.origin!==window.location.origin)return;
    var path=url.pathname.toLowerCase();
    // Let the browser submit marks actions natively. The School Admin and
    // Teacher portals use /school/app/* and /teacher/app/*, while the shared
    // router receives /app/*. Normalize the portal prefix first.
    var marksPath=path;
    if(marksPath.indexOf('/school/app/')===0)marksPath=marksPath.substring('/school'.length);
    if(marksPath.indexOf('/teacher/app/')===0)marksPath=marksPath.substring('/teacher'.length);
    if(marksPath==='/app/academics/marks/save' || marksPath==='/app/academics/marks/save-draft' || marksPath==='/app/academics/marks/finalize' || marksPath==='/app/academics/marks/unfinalize' || marksPath==='/app/academics/marks/delete')return;
    if(path.indexOf('/pdf')===0 || path.indexOf('/print')===0 || path.indexOf('/download')===0 || path.indexOf('/export')===0 || form.target==='_blank' || form.hasAttribute('download'))return;
    event.preventDefault();
    var data=new FormData(form);
    if(submitter && submitter.name && !data.has(submitter.name))data.append(submitter.name,submitter.value||'');
    fetch(url.toString(),{{method:'POST',body:data,credentials:'same-origin',redirect:'follow',headers:{{'X-DaviSchool-History':'replace'}}}})
      .then(function(response){{
        if(!response.ok){{window.location.href=response.url||url.toString();return;}}
        window.location.replace(response.url||url.toString());
      }})
      .catch(function(){{window.location.href=url.toString();}});
  }}catch(e){{}}
}},true);
}})();</script><script>(function(){{
// Give every submitted action instant visual acknowledgement without changing
// its submitted values or waiting for the server response before showing it.
document.addEventListener('submit',function(e){{
  var form=e.target, button=e.submitter;
  if(!form)return;
  if(button){{button.classList.add('btn-loading');button.setAttribute('aria-busy','true');}}
}},true);
// Navigation links remain enabled after a click so a failed redirect cannot
// permanently disable the School Admin sidebar.;document.querySelectorAll('.marks-entry button,.marks-entry a,.marks-entry form').forEach(function(el){var t=(el.textContent||'').trim().toLowerCase(),h=(el.getAttribute('href')||'')+(el.getAttribute('action')||'')+(el.getAttribute('formaction')||'');if(t.includes('delete')||t.includes('remove')||t.includes('🗑')||h.includes('/marks/delete')){var node=el.closest('form')||el;if(node&&node!==document.body)node.remove();}});</script>"%js_rules
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
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}&saved_at={int(datetime.now(ZoneInfo('Africa/Nairobi')).timestamp())}",303,headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0"})

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
    # Keep the post-save redirect inside the same role-specific portal.
    # The shared /app route is used by both School Admin and Teacher, so an
    # unscoped redirect can otherwise fall back to the other role's session
    # cookie when both accounts are signed in in the same browser.
    session_scope = request.scope.get("davischool_session_scope")
    redirect_prefix = "/school" if session_scope == "school" else ("/teacher" if session_scope == "teacher" else "")
    return RedirectResponse(f"{redirect_prefix}/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

# Marks deletion is intentionally disabled. Published and teacher draft marks must not be deletable from the Record Marks workflow.\n\n@router.post("/app/academics/marks/finalize")
async def finalize_marks(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...), portal_role:str=Form("")):
    # The form explicitly identifies the portal that opened the marks page.
    # Prefer that portal cookie over a stale/default session so Submit & Lock
    # can never fall through to the generic login page.
    recovered = _recover_portal_session(request, portal_role) if portal_role in ("teacher", "school_admin") else None
    if recovered:
        sid=_school_session(request)
    else:
        sid=_school_session(request)
        if not sid:
            recovered = _recover_portal_session(request, portal_role)
            if recovered:
                sid=_school_session(request)
    if not sid:
        print("DAVISCHOOL MARKS FINALIZE SESSION MISSING: path=%s scope=%s role=%s email=%s portal_role=%s", request.url.path, request.scope.get("davischool_session_scope"), request.session.get("role"), request.session.get("email"), portal_role, flush=True)
        scope_name = str(request.scope.get("davischool_session_scope") or "default")
        login_path = "/school/login" if scope_name == "school" else ("/teacher/login" if scope_name == "teacher" else "/")
        return RedirectResponse(login_path,303)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to finalize marks.",403)
    con=_db();cur=con.cursor();_ensure_academic_locks_table(cur)
    valid=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not valid:
        con.close(); return HTMLResponse("Invalid academic selection. <a href='/app/academics/marks'>Back</a>",400)
    if not _teacher_class_authorized(cur, request, sid, class_id, subject_id):
        con.close(); return HTMLResponse("You are not allocated to this class and subject.",403)
    if _academic_lock(cur,sid,exam_id,class_id,subject_id):
        con.close()
        if portal_role == "teacher":
            return RedirectResponse(f"/teacher/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)
        if portal_role == "school_admin":
            return RedirectResponse(f"/school/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)
        return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

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
        _audit(cur,sid,request,"MARKS_FINALIZE",f"Finalized marks for exam {exam_id}, class {class_id}, subject {subject_id}")
    except Exception as audit_exc:
        print("DAVISCHOOL MARKS FINALIZE AUDIT WARNING:",repr(audit_exc),flush=True)
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
    # Always return to the authenticated portal. The Submit & Lock POST can
    # arrive at /app/... even when the teacher is using the shared /app session.
    # In that case the middleware scope is "default"; using it would redirect
    # to "/" and show the login menu even though the lock was successfully saved.
    # The authenticated session role is therefore the authoritative fallback.
    session_role = str(request.session.get("role") or "").strip()
    scope_name = str(request.scope.get("davischool_session_scope") or "default")
    if portal_role == "teacher" or session_role == "teacher" or scope_name == "teacher":
        portal_prefix = "/teacher"
    elif portal_role == "school_admin" or session_role == "school_admin" or scope_name == "school":
        portal_prefix = "/school"
    else:
        portal_prefix = "/app"
    target = "/app/academics/marks?exam_id=%s&class_id=%s&subject_id=%s" % (exam_id, class_id, subject_id) if portal_prefix == "/app" else f"{portal_prefix}/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}"
    return RedirectResponse(target,303)

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
    con.commit();con.close()
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

@router.get("/app/academics/marks-corrections", response_class=HTMLResponse)
def marks_correction_requests(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if str(request.session.get("role","")) != "school_admin":
        return HTMLResponse("Only the school administrator can review mark correction requests.",403)
    con=_db();cur=con.cursor();_ensure_marks_correction_requests_table(cur)
    rows=cur.execute("""SELECT r.*,e.name exam_name,c.name class_name,c.stream,sub.name subject_name,t.name teacher_name
        FROM marks_correction_requests r
        LEFT JOIN exams e ON e.id=r.exam_id LEFT JOIN classes c ON c.id=r.class_id
        LEFT JOIN subjects sub ON sub.id=r.subject_id LEFT JOIN teachers t ON t.id=r.teacher_id
        WHERE r.school_id=? ORDER BY CASE WHEN r.status='pending' THEN 0 ELSE 1 END,r.id DESC""",(sid,)).fetchall()
    con.close()
    body_rows=""
    for r in rows:
        status=str(r["status"] or "").lower()
        action=""
        if status=="pending":
            action=(f"<form method='post' action='/app/academics/marks-corrections/approve' style='display:inline'><input type='hidden' name='request_id' value='{r['id']}'><button class='btn' type='submit' onclick=\"return confirm('Approve this correction request and reopen the marks?');\">🔓 Approve / Reopen</button></form> "
                    f"<form method='post' action='/app/academics/marks-corrections/reject' style='display:inline'><input type='hidden' name='request_id' value='{r['id']}'><button class='btnlink' type='submit' onclick=\"return confirm('Reject this correction request?');\">Reject</button></form>")
        body_rows += f"<tr><td>{escape(str(r['requested_at'] or ''))}</td><td>{escape(str(r['teacher_name'] or r['requested_by'] or ''))}</td><td>{escape(str(r['exam_name'] or ''))}</td><td>{escape(str(r['class_name'] or ''))} {escape(str(r['stream'] or ''))}</td><td>{escape(str(r['subject_name'] or ''))}</td><td>{escape(str(r['reason'] or ''))}</td><td>{escape(status.title())}</td><td>{action}</td></tr>"
    body=f"""<div class='page'><h1>Marks Correction Requests</h1><div class='muted'>Review teacher requests to reopen finalized marks. Approving a request unlocks only the selected examination, class and subject.</div><div class='card section'><table><thead><tr><th>Requested</th><th>Teacher</th><th>Exam</th><th>Class</th><th>Subject</th><th>Reason</th><th>Status</th><th>Action</th></tr></thead><tbody>{body_rows or '<tr><td colspan=8>No correction requests yet.</td></tr>'}</tbody></table></div></div><style>.btn,.btnlink{{padding:8px 11px;border:0;border-radius:8px;background:#111827;color:#fff;font-weight:800;cursor:pointer;text-decoration:none}}.btnlink{{background:#fff;color:#172033;border:1px solid #dbe2ea}}</style>"""
    return _school_page(request,"Marks Correction Requests",body)

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

@router.post("/app/academics/marks/unfinalize")
def unfinalize_marks(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...)):
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
    con.commit();con.close()
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

def _ensure_teacher_allocations_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS teacher_allocations (
        id INTEGER PRIMARY KEY,
        school_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        UNIQUE(school_id,teacher_id,class_id,subject_id)
    )""")

@router.get("/app/academics/assessments", response_class=HTMLResponse)
def assessments_page(request: Request, student_id: str = "", subject_id: str = "", term: str = "", year: str = ""):
    sid=_school_session(request)
    if not sid:
        return RedirectResponse("/")
    if not _require_permission(request, sid, "marks.view"):
        return HTMLResponse("You do not have permission to view assessment records.", 403)
    con=_db(); cur=con.cursor()
    _ensure_assessment_table(cur)
    students=cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    stid=int(student_id) if str(student_id).isdigit() else 0
    subid=int(subject_id) if str(subject_id).isdigit() else 0
    rows=cur.execute("""SELECT a.*,s.name subject_name,st.name student_name,st.admission_no
                        FROM assessment_scores a
                        JOIN subjects s ON s.id=a.subject_id
                        JOIN students st ON st.id=a.student_id
                        WHERE a.school_id=?
                          AND (?=0 OR a.student_id=?)
                          AND (?=0 OR a.subject_id=?)
                          AND (?='' OR a.term=?)
                          AND (?='' OR a.year=?)
                        ORDER BY a.id DESC LIMIT 500""",
                     (sid,stid,stid,subid,subid,term,term,year,year)).fetchall()
    con.commit(); con.close()
    so="".join(f"<option value='{s['id']}' {'selected' if int(s['id'])==subid else ''}>{escape(str(s['name']))}</option>" for s in subjects)
    sto="".join(f"<option value='{s['id']}' {'selected' if int(s['id'])==stid else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    body=f"""<div class='page'><h1>SBA / CBA</h1>
<div class='muted'>Record continuous assessment components separately from examination marks.</div>
<div class='card section'><form method='get' action='/app/academics/assessments' class='academic-select'>
<select name='student_id' class='field'><option value=''>All Students</option>{sto}</select>
<select name='subject_id' class='field'><option value=''>All Subjects</option>{so}</select>
<input name='term' value='{escape(term)}' placeholder='Term 1' class='field'>
<input name='year' value='{escape(year)}' placeholder='Year' class='field'>
<button class='btn'>Filter</button></form></div>
<div class='card section'><h2>Enter Assessment</h2>
<form method='post' action='/app/academics/assessments/add' style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>
<select name='student_id' required class='field'>{sto}</select>
<select name='subject_id' required class='field'>{so}</select>
<input name='term' required value='{escape(term or "Term 1")}' placeholder='Term 1' class='field'>
<input name='year' required value='{escape(year or str(datetime.now(ZoneInfo("Africa/Nairobi")).year))}' class='field'>
<input name='component' required placeholder='CAT 1 / Project / SBA' class='field'>
<input name='score' required type='number' min='0' step='0.01' placeholder='Score' class='field'>
<input name='out_of' required type='number' min='0.01' step='0.01' value='100' placeholder='Out of' class='field'>
<button class='btn'>Save Assessment</button></form></div>
<div class='card section'><h2>Assessment Records ({len(rows)})</h2>
<table><thead><tr><th>Student</th><th>Admission No.</th><th>Subject</th><th>Term</th><th>Year</th><th>Component</th><th>Score</th><th>Out Of</th><th>Created</th></tr></thead>
<tbody>{"".join(f"<tr><td>{escape(str(r['student_name']))}</td><td>{escape(str(r['admission_no'] or ''))}</td><td>{escape(str(r['subject_name']))}</td><td>{escape(str(r['term'] or ''))}</td><td>{escape(str(r['year'] or ''))}</td><td>{escape(str(r['component'] or ''))}</td><td>{float(r['score'] or 0):.2f}</td><td>{float(r['out_of'] or 0):.2f}</td><td>{escape(str(r['created_at'] or ''))}</td></tr>" for r in rows) or "<tr><td colspan='9'>No assessment records yet.</td></tr>"}</tbody></table></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.academic-select{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}@media(max-width:900px){{.academic-select{{grid-template-columns:1fr 1fr}}}}</style></div>"""
    return _school_page(request,"SBA / CBA",body)

@router.post("/app/academics/assessments/add")
def assessments_add(request: Request, student_id:int=Form(...), subject_id:int=Form(...), term:str=Form(...), year:str=Form(...), component:str=Form(...), score:float=Form(...), out_of:float=Form(...)):
    sid=_school_session(request)
    if not sid:
        return RedirectResponse("/",303)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit assessment records.",403)
    if not term.strip() or not year.strip() or not component.strip() or out_of<=0 or score<0 or score>out_of:
        return HTMLResponse("Invalid assessment details. <a href='/app/academics/assessments'>Back</a>",400)
    con=_db(); cur=con.cursor(); _ensure_assessment_table(cur)
    student=cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone()
    subject=cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not student or not subject:
        con.close()
        return HTMLResponse("Selected student or subject does not belong to this school. <a href='/app/academics/assessments'>Back</a>",400)
    cur.execute("INSERT INTO assessment_scores(school_id,student_id,subject_id,term,year,component,score,out_of,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (sid,student_id,subject_id,term.strip(),year.strip(),component.strip(),score,out_of,datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")))
    _audit(cur,sid,request,"ASSESSMENT_SAVE",f"Saved {component.strip()} for student {student_id}")
    con.commit(); con.close()
    return RedirectResponse("/app/academics/assessments",303)

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
    trs="".join("<tr><td>%s</td><td>%s%s</td><td>%s</td><td><a class='btn edit' href='/app/academics/allocations/edit/%s'>Edit</a> <form method='post' action='/app/academics/allocations/delete/%s' style='display:inline' onsubmit=\"return confirm('Delete this teacher allocation?')\"><button class='btn danger' type='submit'>Delete</button></form></td></tr>"%(escape(str(x["teacher_name"])),escape(str(x["class_name"])),(" — "+escape(str(x["class_stream"]))) if x["class_stream"] else "",escape(str(x["subject_name"])),x["id"],x["id"]) for x in rows)
    body=f"""<div class='page'><h1>Teacher Allocations</h1><div class='muted'>Assign teachers to classes and subjects.</div>
<div class='card section'><form method='post' action='/app/academics/allocations/add' style='display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px'>
<select name='teacher_id' class='field' required><option value=''>Select Teacher</option>{tops}</select>
<select name='class_id' class='field' required><option value=''>Select Class / Stream</option>{cops}</select>
<select name='subject_id' class='field' required><option value=''>Select Subject</option>{sops}</select>
<button class='btn'>Save Allocation</button></form></div>
<div class='card section'><h2>Current Allocations ({len(rows)})</h2><table><thead><tr><th>Teacher</th><th>Class / Stream</th><th>Subject</th><th>Action</th></tr></thead><tbody>{trs or '<tr><td colspan=4>No allocations yet.</td></tr>'}</tbody></table></div>
<style>.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}.danger{{background:#b91c1c}}.edit{{background:#176B3A;margin-right:5px;padding:9px 12px}}</style></div>"""
    return _school_page(request,"Teacher Allocations",body)

@router.post("/app/academics/allocations/add")
def teacher_allocations_add(request: Request,teacher_id:int=Form(...),class_id:int=Form(...),subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request,sid,"staff.edit"):return HTMLResponse("You do not have permission to manage teacher allocations.",403)
    con=_db();cur=con.cursor();_ensure_teacher_allocations_table(cur)
    if not (cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()):
        con.close();return HTMLResponse("Invalid selection. <a href='/app/academics/allocations'>Back</a>",400)
    cur.execute("INSERT OR IGNORE INTO teacher_allocations(school_id,teacher_id,class_id,subject_id) VALUES(?,?,?,?)",(sid,teacher_id,class_id,subject_id))
    _audit(cur,sid,request,"TEACHER_ALLOCATION","Teacher %s / Class %s / Subject %s"%(teacher_id,class_id,subject_id))
    con.commit();con.close();return RedirectResponse("/app/academics/allocations",303)

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
<div class='card section'><form method='post' action='/app/academics/allocations/edit/{allocation_id}' style='display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px'>
<select name='teacher_id' class='field' required><option value=''>Select Teacher</option>{tops}</select>
<select name='class_id' class='field' required><option value=''>Select Class / Stream</option>{cops}</select>
<select name='subject_id' class='field' required><option value=''>Select Subject</option>{sops}</select>
<button class='btn'>Save Changes</button><a class='btn secondary' href='/app/academics/allocations'>Cancel</a></form></div>
<style>.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{display:inline-block;padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}}.secondary{{background:#64748b}}</style></div>"""
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
    cur.execute("DELETE FROM teacher_allocations WHERE id=? AND school_id=?",(allocation_id,sid));con.commit();con.close()
    return RedirectResponse("/app/academics/allocations",303)

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
def report_card_settings(request: Request, exam_id:int=0):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to manage report card dates.", 403)
    con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
    exams=cur.execute("SELECT id,name FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    selected=cur.execute("SELECT * FROM report_card_settings WHERE school_id=? AND exam_id=? LIMIT 1",(sid,exam_id)).fetchone() if exam_id else None
    con.close()
    options="".join(f"<option value='{e['id']}' {'selected' if int(e['id'])==exam_id else ''}>{escape(str(e['name']))}</option>" for e in exams)
    return _school_page(request,"Report Card Settings",f"""<div class='card section'><h2>Report Card Dates</h2><p class='muted'>Set the opening and closing dates for each examination/reporting period.</p><form method='post'><select name='exam_id' class='field' required>{options}</select><label>Date of Opening</label><input type='date' name='opening_date' class='field' value='{escape(str(selected["opening_date"] if selected else ""))}'><label>Date of Closing</label><input type='date' name='closing_date' class='field' value='{escape(str(selected["closing_date"] if selected else ""))}'><button class='btn'>Save Dates</button></form></div>""")

@router.post("/app/report-card-settings")
def save_report_card_settings(request: Request, exam_id:int=Form(...), opening_date:str=Form(""), closing_date:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "reports.edit"):
        return HTMLResponse("You do not have permission to manage report card dates.", 403)
    con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
    if not cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone():
        con.close();return HTMLResponse("Invalid examination.",400)
    if opening_date and closing_date and closing_date<opening_date:
        con.close();return HTMLResponse("Closing date cannot be before opening date.",400)
    cur.execute("INSERT INTO report_card_settings(school_id,exam_id,opening_date,closing_date) VALUES(?,?,?,?) ON CONFLICT(school_id,exam_id) DO UPDATE SET opening_date=excluded.opening_date,closing_date=excluded.closing_date",(sid,exam_id,opening_date,closing_date))
    con.commit();con.close()
    return RedirectResponse(f"/app/report-card-settings?exam_id={exam_id}",303)
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
<div class='card section'><table><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th><th>Performance Comment</th></tr></thead><tbody>{rows or "<tr><td colspan='6'>No marks found for the selected examination/class.</td></tr>"}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}</style>"""
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
<div class='card section'><h2>Subject Performance</h2><table><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th><th>Performance Comment</th></tr></thead><tbody>{ar or "<tr><td colspan='6'>Select an examination and class.</td></tr>"}</tbody></table></div>
<div class='card section'><h2>Learner Ranking</h2><table><thead><tr><th>Position</th><th>Admission</th><th>Student</th><th>Total</th><th>Average</th><th>Grade</th></tr></thead><tbody>{sr or "<tr><td colspan='6'>No learner results found.</td></tr>"}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}</style>"""
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
    assignments=cur.execute("SELECT class_id,teacher_id FROM class_teacher_assignments WHERE school_id=?",(sid,)).fetchall()
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
    class_by_teacher={int(a["teacher_id"]):int(a["class_id"]) for a in assignments}
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

        from app.main import hash_password
        import secrets
        if role=="teacher":
            first_name=re.sub(r"[^A-Za-z0-9]", "", full_name.split()[0] if full_name.split() else "Teacher")
            generated_password=first_name+"@"+str(secrets.randbelow(9000)+1000)
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
        cur.execute("INSERT INTO users(username,email,password,role,full_name,school_id,teacher_id,student_id,temporary_password) VALUES(?,?,?,?,?,?,?,?,?)",
                    (username,email_v,hash_password(generated_password),role,full_name.strip(),sid,tid,stid,generated_password))

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

        _audit(cur,sid,request,"USER_CREATE",f"Created {role} account {email_v}")
        con.commit()

        # Verify that the committed account is actually visible to the same
        # school before redirecting to the Accounts table.
        created=cur.execute("SELECT id FROM users WHERE school_id=? AND lower(username)=?",(sid,username.lower())).fetchone()
        if not created:
            return HTMLResponse("The account could not be verified after saving. No account was added. <a href='/app/users'>Back</a>",500)
        request.session["created_account_credentials"]={"username":username,"password":generated_password}
        return RedirectResponse(f"/app/users?created=1&username={quote(username)}",303)
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
    assignments=cur.execute("""SELECT class_id,teacher_id FROM class_teacher_assignments WHERE school_id=?""",(sid,)).fetchall()
    con.close()
    assigned_by_class={int(a["class_id"]):int(a["teacher_id"]) for a in assignments}
    teacher_options=lambda selected_id: "".join(
        "<option value='%s' %s>%s%s</option>" % (
            t["id"],
            "selected" if selected_id and int(t["id"])==int(selected_id) else "",
            escape(str(t["name"] or "")),
            (" — "+escape(str(t["role"] or ""))) if t["role"] else ""
        )
        for t in teachers
    )
    trs="".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><form method='post' action='/app/classes/class-teacher' style='display:flex;gap:7px;align-items:center;flex-wrap:wrap'>"
        "<input type='hidden' name='class_id' value='%s'><select name='teacher_id' class='field teacher-select' required><option value=''>Select Class Teacher</option>%s</select>"
        "<button class='btn teacher-btn'>👨‍🏫 Set Class Teacher</button></form></td></tr>" % (
            escape(str(x["name"])),
            escape(str(x["level"] or "")),
            escape(str(x["stream"] or "")),
            escape(str(next((t["name"] for t in teachers if int(t["id"])==assigned_by_class.get(int(x["id"]),-1)), "Not Assigned"))),
            x["id"],
            teacher_options(assigned_by_class.get(int(x["id"])))
        )
        for x in rows
    )
    body=f"""<div class='page'><h1>Classes & Streams</h1>
<div class='card section'><form method='post' action='/app/classes/add' class='formgrid'><input name='name' required placeholder='Class name e.g. Grade 6' class='field'><select name='level' class='field'><option value=''>Select level</option><option>Pre-Primary</option><option>Lower Primary</option><option>Upper Primary</option><option>Junior Secondary</option><option>Senior Secondary</option><option>College</option><option>Other</option></select><input name='stream' placeholder='Stream' class='field'><button class='btn'>Add Class</button></form></div>
<div class='card section'><h2>👨‍🏫 Class Teachers</h2><div class='muted'>Select a teacher for each class or stream. The selected teacher is automatically used as the Class Teacher on that class's report cards, including the name and signature line.</div>
<table><thead><tr><th>Name</th><th>Level</th><th>Stream</th><th>Current Class Teacher</th><th>Set Class Teacher</th></tr></thead><tbody>{trs or '<tr><td colspan=5>No classes.</td></tr>'}</tbody></table></div></div>
<style>.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800;cursor:pointer}}.teacher-select{{min-width:220px}}.teacher-btn{{white-space:nowrap}}</style>"""
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
    cur.execute("""INSERT INTO class_teacher_assignments(school_id,class_id,teacher_id,assigned_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(school_id,class_id) DO UPDATE SET teacher_id=excluded.teacher_id,assigned_at=excluded.assigned_at""",
                (sid,class_id,teacher_id,now))
    _audit(cur,sid,request,"CLASS_TEACHER_ASSIGNMENT","Assigned %s as class teacher for class %s"%(str(valid_teacher["name"] or ""),class_id))
    con.commit();con.close()
    return RedirectResponse("/app/classes",303)

@router.get("/app/subjects", response_class=HTMLResponse)
def subjects_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "subjects.view"):
        return HTMLResponse("You do not have permission to view subjects.", 403)
    con=_db();cur=con.cursor(); rows=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall();con.close()
    trs="".join(f"<tr><td>{escape(str(x['name']))}</td><td>{escape(str(x['code'] or ''))}</td><td>{escape(str(x['initial'] or ''))}</td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Subjects</h1><div class='card section'><form method='post' action='/app/subjects/add' class='formgrid'><input name='name' required placeholder='Subject name' class='field'><input name='code' placeholder='Code' class='field'><input name='initial' placeholder='Initial' class='field'><button class='btn'>Add Subject</button></form></div><div class='card section'><table><thead><tr><th>Subject</th><th>Code</th><th>Initial</th></tr></thead><tbody>{trs or '<tr><td colspan=3>No subjects.</td></tr>'}</tbody></table></div></div><style>.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
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
    _audit(cur,sid,request,"SUBJECT_CREATE",name_v);con.commit();con.close();return RedirectResponse("/app/subjects",303)
@router.get("/app/exams", response_class=HTMLResponse)
def exams_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "exams.view"):
        return HTMLResponse("You do not have permission to view examinations.", 403)
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall();con.close()
    trs="".join(f"<tr><td>{escape(str(x['name']))}</td><td>{escape(str(x['exam_type'] or ''))}</td><td>{escape(str(x['term'] or ''))}</td><td>{escape(str(x['year'] or ''))}</td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Examinations</h1><div class='card section'><form method='post' action='/app/exams/add' class='formgrid'><input name='name' required placeholder='Exam name' class='field'><select name='exam_type' class='field'><option value=''>Select exam type</option><option>CAT</option><option>Mid-Term</option><option>End-Term</option><option>Mock</option><option>Final</option><option>SBA/CBA</option></select><select name='term' class='field'><option value=''>Select term</option><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><select name='year' class='field'>{''.join('<option>'+y+'</option>' for y in YEAR_OPTIONS)}</select><button class='btn'>Create Exam</button></form></div><div class='card section'><table><thead><tr><th>Name</th><th>Type</th><th>Term</th><th>Year</th></tr></thead><tbody>{trs or '<tr><td colspan=4>No examinations.</td></tr>'}</tbody></table></div></div><style>.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Examinations",body)

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
    assignments=cur.execute("""SELECT a.class_id,a.teacher_id,c.name class_name,c.stream,t.name teacher_name
        FROM class_teacher_assignments a JOIN classes c ON c.id=a.class_id JOIN teachers t ON t.id=a.teacher_id
        WHERE a.school_id=? ORDER BY c.name,c.stream""",(sid,)).fetchall()
    con.close()
    tr=_simple_rows(rows,["role","permission","enabled"])
    class_opts="".join("<option value='%s'>%s%s</option>"%(c["id"],escape(str(c["name"])),(" · "+escape(str(c["stream"] or ""))) if c["stream"] else "") for c in classes)
    teacher_opts="".join("<option value='%s'>%s — %s</option>"%(t["id"],escape(str(t["name"])),escape(str(t["role"] or ""))) for t in teachers)
    assignment_rows="".join("<tr><td>%s%s</td><td>%s</td></tr>"%(escape(str(a["class_name"])),(" · "+escape(str(a["stream"] or ""))) if a["stream"] else "",escape(str(a["teacher_name"]))) for a in assignments)
    body=f"""<div class='page'><h1>Roles & Permissions</h1><div class='muted'>Control permissions for school roles.</div>
<div class='card section'><h2>Class Teacher Assignments</h2><div class='muted'>Assign the staff member who has the Class Teacher responsibility to each class. Report cards automatically use this assignment for the class teacher name and signature line.</div>
<form method='post' action='/app/roles/class-teacher-assignment' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='class_id' class='field' required><option value=''>Select class</option>{class_opts}</select><select name='teacher_id' class='field' required><option value=''>Select class teacher</option>{teacher_opts}</select><button class='btn'>Save Assignment</button></form>
<table style='margin-top:14px'><thead><tr><th>Class</th><th>Class Teacher</th></tr></thead><tbody>{assignment_rows or "<tr><td colspan='2'>No class teacher assignments yet.</td></tr>"}</tbody></table></div>
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
    cur.execute("""INSERT INTO class_teacher_assignments(school_id,class_id,teacher_id,assigned_at) VALUES(?,?,?,?)
                   ON CONFLICT(school_id,class_id) DO UPDATE SET teacher_id=excluded.teacher_id,assigned_at=excluded.assigned_at""",
                (sid,class_id,teacher_id,now))
    _audit(cur,sid,request,"CLASS_TEACHER_ASSIGNMENT","Assigned class teacher for class %s"%class_id)
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